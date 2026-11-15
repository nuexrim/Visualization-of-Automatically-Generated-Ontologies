"""RIGOR 방식 온톨로지 생성 파이프라인 (내장 생성기).

테이블을 외래 키 의존 순서로 하나씩 처리한다. 테이블마다:
  1) Direct Mapping 뼈대를 만들어 먼저 병합  (포괄성 보장)
  2) 맥락 검색: 컬럼 설명 CSV, 이미 만들어진 온톨로지 부분
  3) 생성 LLM이 의미 보강 (Manchester Syntax 조각)
  4) 판정 LLM이 검토 → 통과하면 파싱·검사 후 병합, 끝내 실패하면 Direct Mapping 결과만 유지

흐름과 프롬프트는 RIGOR(https://github.com/NadeenAhmad/RIGOR, MIT License, Copyright (c) 2026 Nadeen Fathallah)의
run_semantic_enrichment / OntologyLLM / JudgeLLM 을 옮긴 것이다. 다른 점:
- 파서를 바꾸고(manchester.py) 파싱 결과 검사 단계를 더했다 (빈 결과·선언 없는 클래스·출처 누락).
- 맥락 검색은 임베딩 대신 외래 키로 이어진 클래스를 직접 고른다.
- 라벨은 요소마다 하나만 남긴다 (보강된 라벨이 Direct Mapping 라벨을 대신함).
진행 상황은 이벤트(dict)를 yield 해서 알린다.
"""
from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Generator, Iterator
from dataclasses import dataclass, field
from urllib.parse import quote

from rdflib import BNode, Graph, URIRef
from rdflib.namespace import OWL, PROV, RDF, RDFS, XSD

from backend.db.descriptions import load_descriptions
from backend.ontology import naming
from backend.ontology.direct_mapping import _xsd_prefixed, bind_namespaces, direct_mapping_for_table, fk_order
from backend.ontology.manchester import parse_manchester
from backend.ontology.view import graph_to_view

MAX_JUDGE_RETRIES = 2
SYSTEM_PROMPT = "You generate OWL 2 ontology fragments in Manchester Syntax. Return only valid Manchester Syntax and no explanation."

Event = dict
#: 프롬프트를 받아 진행 이벤트를 내보내다가 응답 문자열을 돌려주는 함수
LLM = Callable[[str], Generator[Event, None, str]]


# ---------------------------------------------------------------- LLM (Anthropic)

@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


def anthropic_llm(model: str, usage: Usage) -> LLM:
    import anthropic

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY 는 환경 변수에서만 읽는다

    def call(prompt: str) -> Generator[Event, None, str]:
        last: Exception | None = None
        for attempt in range(1, 4):
            try:
                chars, tick = 0, time.monotonic()
                with client.messages.stream(model=model, max_tokens=16000, system=SYSTEM_PROMPT,
                                            messages=[{"role": "user", "content": prompt}]) as stream:
                    for text in stream.text_stream:
                        chars += len(text)
                        if time.monotonic() - tick > 0.7:
                            tick = time.monotonic()
                            yield {"type": "llm_progress", "chars": chars}
                    msg = stream.get_final_message()
                usage.calls += 1
                usage.input_tokens += msg.usage.input_tokens
                usage.output_tokens += msg.usage.output_tokens
                if msg.stop_reason == "refusal":
                    return ""
                return "".join(b.text for b in msg.content if b.type == "text").strip()
            except anthropic.AuthenticationError:
                raise
            except Exception as e:  # noqa: BLE001 - 일시적 오류는 다시 시도한다
                last = e
                if attempt < 3:
                    yield {"type": "llm_retry", "attempt": attempt, "error": str(e)[:200]}
                    time.sleep(2 ** (attempt - 1))
        raise RuntimeError(f"LLM 호출 실패: {last}")

    return call


def default_model() -> str:
    model = (os.environ.get("ONTOLOGY_GEN_MODEL") or "").strip()
    if not model:
        raise RuntimeError("ONTOLOGY_GEN_MODEL 환경 변수가 비어 있습니다 (.env 확인).")
    if not (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        raise RuntimeError("ANTHROPIC_API_KEY 환경 변수가 비어 있습니다 (.env 확인).")
    return model


# ---------------------------------------------------------------- 프롬프트에 넣을 텍스트

def render_direct_mapping_manchester(table: dict, xsd: dict, known_tables: set[str]) -> str:
    name = table["name"]
    cls = naming.to_class_name(name)
    lines = [
        f"Prefix: : <{naming.ONTOLOGY_IRI}#>",
        "Prefix: xsd: <http://www.w3.org/2001/XMLSchema#>",
        "Prefix: rdfs: <http://www.w3.org/2000/01/rdf-schema#>",
        "Prefix: owl: <http://www.w3.org/2002/07/owl#>",
        "Prefix: prov: <http://www.w3.org/ns/prov#>",
        "",
        f"Ontology: <{naming.ONTOLOGY_IRI}>",
        "",
        f"Class: {cls}",
        "  Annotations:",
        f'    rdfs:label "{naming.humanize_identifier(cls)}"@en,',
        f"    rdfs:comment \"Class generated from source table '{name}'.\"@en,",
        f"    prov:wasDerivedFrom <{naming.ONTOLOGY_IRI}/provenance/{name}>",
    ]
    keys, restrictions = [], []
    for c in table["columns"]:
        col = c["name"]
        if c["fk"] and c["fk"]["table"] in known_tables:
            ref = c["fk"]["table"]
            prop, rng, kind = naming.object_property_name(name, col, ref), naming.to_class_name(ref), "ObjectProperty"
            comment = f"Foreign-key relationship from {name}.{col} to {ref}.{c['fk']['column']}."
            if ref == name:
                comment += f" This is an explicit recursive self-referential relationship within {cls}."
        elif c["fk"]:
            continue
        else:
            prop, rng, kind = naming.data_property_name(name, col), _xsd_prefixed(xsd[(name, col)]), "DataProperty"
            comment = f"Column {name}.{col}; datatype {rng}."
            if xsd[(name, col)] == XSD.integer and re.search(r"(stage|score|status|grade|class|category|type)$", col, re.I):
                comment += " This integer-valued property may encode a categorical or ordinal concept; consult source documentation for value meanings."
        lines += [
            "",
            f"{kind}: {prop}",
            "  Annotations:",
            f'    rdfs:label "{naming.humanize_identifier(prop)}"@en,',
            f'    rdfs:comment "{comment}"@en,',
            f"    prov:wasDerivedFrom <{naming.ONTOLOGY_IRI}/provenance/{name}/{quote(col)}>",
            f"  Domain: {cls}",
            f"  Range: {rng}",
        ]
        restrictions.append(f"{prop} only {rng}")
        if c["pk"] or c.get("unique") or not c["nullable"]:
            restrictions.append(f"{prop} some {rng}")
        if c["pk"]:
            keys.append(prop)
    if keys or restrictions:
        lines += ["", f"Class: {cls}"]
        if keys:
            lines.append(f"  HasKey: {' '.join(keys)}")
        lines += [f"  SubClassOf: {r}" for r in restrictions]
    return "\n".join(lines)


def schema_json_for_table(table: dict, tables: dict[str, dict], xsd: dict) -> str:
    """현재 테이블과 외래 키가 가리키는 테이블의 스키마."""
    relevant = [table["name"]] + sorted({c["fk"]["table"] for c in table["columns"] if c["fk"] and c["fk"]["table"] in tables} - {table["name"]})
    data = {}
    for t in relevant:
        tb = tables[t]
        data[t] = {
            "columns": {
                c["name"]: {"xsd_type": _xsd_prefixed(xsd[(t, c["name"])]), "nullable": c["nullable"],
                            "unique": bool(c.get("unique")), "primary_key": c["pk"]}
                for c in tb["columns"]
            },
            "foreign_keys": [
                {"column": c["name"], "references_table": c["fk"]["table"], "references_column": c["fk"]["column"]}
                for c in tb["columns"] if c["fk"]
            ],
        }
    return json.dumps(data, indent=2)


def foreign_keys_text(table: dict) -> str:
    fks = [c for c in table["columns"] if c["fk"]]
    if not fks:
        return "None"
    return "\n".join(f"  - Column '{c['name']}' references {c['fk']['table']}.{c['fk']['column']}" for c in fks)


def documentation_for_table(db: str, table: dict) -> str:
    """컬럼 설명 CSV(BIRD database_description)에서 이 테이블 부분."""
    desc = load_descriptions(db).get(table["name"].lower(), {})
    lines = []
    for c in table["columns"]:
        d = desc.get(c["name"].lower())
        if not d or not (d["description"] or d["value_description"]):
            continue
        line = f"- {table['name']}.{c['name']}"
        if d["label"]:
            line += f" ({d['label']})"
        line += f": {d['description'] or 'no description'}"
        if d["value_description"]:
            line += " | values: " + " ".join(d["value_description"].split())
        lines.append(line)
    return f"[database_description/{table['name']}.csv]\n" + "\n".join(lines) if lines else ""


def core_context_for_table(core: Graph, table: dict, tables: dict[str, dict]) -> str:
    """이미 만들어진 온톨로지에서 이 테이블과 외래 키로 이어진 클래스와 그 속성 요약."""
    related = sorted({c["fk"]["table"] for c in table["columns"] if c["fk"] and c["fk"]["table"] in tables} - {table["name"]})
    chunks = []
    for t in related:
        cls = naming.class_iri(t)
        if (cls, RDF.type, OWL.Class) not in core:
            continue
        label = core.value(cls, RDFS.label)
        comments = sorted((str(o) for o in core.objects(cls, RDFS.comment)), key=len)
        text = f"Class: {naming.local_name(cls)} IRI: {cls}"
        if label:
            text += f" Label: {label}"
        if comments:
            text += f" Comment: {comments[-1][:200]}"
        parents = [naming.local_name(o) for o in core.objects(cls, RDFS.subClassOf) if isinstance(o, URIRef)]
        if parents:
            text += f" SubClassOf: {', '.join(sorted(parents))}"
        chunks.append(text)
        for p in sorted(core.subjects(RDFS.domain, cls)):
            rng = core.value(p, RDFS.range)
            chunks.append(f"Property: {naming.local_name(p)} Label: {core.value(p, RDFS.label) or ''} Range: {rng}")
    # 지금까지 추가된 상위 클래스 (재사용하도록)
    table_classes = {naming.class_iri(t) for t in tables}
    for c in sorted(s for s in core.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef) and s not in table_classes):
        chunks.append(f"Class: {naming.local_name(c)} IRI: {c} Label: {core.value(c, RDFS.label) or ''} (shared superclass)")
    return "\n".join(chunks[:60])


def generation_prompt(table: str, direct_mapping: str, schema_str: str, fk_str: str, documents: str,
                      core_context: str, external_context: str = "", correction_hint: str = "") -> str:
    documents = documents[:5000] + "..." if len(documents) > 5000 else documents
    return f"""You are receiving a deterministic OWL direct mapping for database table '{table}'.
Your role is semantic enrichment, not schema reconstruction.
The direct mapping is already merged into the core ontology before your delta is applied.
Therefore, your output should refine, annotate, align, or add justified axioms while preserving coverage.
Do not invent source columns.
Do not remove deterministic mappings unless the reason is explicit and valid.

[DIRECT MAPPING FOR THIS TABLE]
{direct_mapping}

[CLEANED DATABASE SCHEMA: CURRENT TABLE + FK TARGETS]
{schema_str}

[FOREIGN KEY CONSTRAINTS FOR '{table}']
{fk_str}

[RETRIEVED DOCUMENTATION]
{documents or 'None'}

[RETRIEVED CURRENT CORE ONTOLOGY CONTEXT]
{core_context or 'None'}

[RETRIEVED EXTERNAL ONTOLOGY HINTS]
{external_context or 'None'}

[CORRECTION INSTRUCTIONS FROM PREVIOUS JUDGE PASS]
{correction_hint or 'None'}

[MANDATORY TASKS]
1. Add or improve rdfs:label and rdfs:comment for every class and property in the direct mapping.
2. Preserve FK modeling as owl:ObjectProperty. Do not output a DataProperty for an FK column.
3. Do not output ETL properties beginning with s_.
4. Add SubClassOf axioms where natural specialization exists.
5. Add comments documenting categorical or ordinal integer encodings when applicable.
6. Add DisjointWith axioms between sibling classes only when logically safe.
7. Add or preserve existential restrictions for not-null, unique, and primary-key properties.
8. Add external alignment using owl:equivalentClass, rdfs:subClassOf, or skos:exactMatch only when supported by retrieved external ontology hints.
9. Add prov:wasDerivedFrom annotations for every newly introduced or modified class/property.

[STRICT CONSTRAINTS]
- A URI must not be both owl:ObjectProperty and owl:DatatypeProperty.
- Every property must have exactly one rdfs:domain and exactly one rdfs:range.
- DataProperty ranges must be XSD datatypes.
- ObjectProperty ranges must be classes.
- Do not create self-referential ObjectProperties unless explicitly meaningful.
- Do not rename deterministic properties unless you also preserve the original property as equivalent or subproperty with provenance.
- Output only Manchester Syntax.

[OUTPUT]
"""


def judge_prompt(table: str, direct_mapping: str, delta: str, schema_str: str, fk_str: str, core_context: str) -> str:
    return f"""You are an ontology validation expert. Evaluate the delta ontology fragment generated for table '{table}'.
The deterministic Direct Mapping has already been merged into the core before this delta is applied.
Your task is to ensure the delta does not break RIGOR's guarantees and adds valid semantic enrichment.

[DIRECT MAPPING]
{direct_mapping}

[DELTA ONTOLOGY]
{delta}

[CLEANED SCHEMA]
{schema_str}

[FOREIGN KEY CONSTRAINTS]
{fk_str}

[CURRENT CORE CONTEXT]
{core_context}

[VALIDATION CRITERIA]
Critical:
1. No FK column may appear as a DataProperty if it is modeled as an ObjectProperty.
2. No URI may be both owl:ObjectProperty and owl:DatatypeProperty.
3. Every property must have exactly one domain and one range.
4. DataProperty ranges must be valid XSD datatypes; date/time properties must not be xsd:string or xsd:float.
5. ObjectProperty domain and range must not be identical unless documented as a meaningful recursive relationship.
6. The delta must not remove or contradict deterministic direct mapping coverage.
7. Required primary-key/not-null/unique existential restrictions must be preserved or strengthened.

Important:
8. All class/property labels and comments should be present and in English.
9. Encoded categorical integers should have encoding comments or modeled enumerations.
10. Junction tables should be treated as relationships when appropriate.
11. Core concepts should be reused, subclassed, or aligned rather than duplicated.
12. Disjointness should be used only when logically safe.

Minor:
13. External alignments should be added where supported by retrieved context.
14. Provenance should be present for every new or modified element.

[OUTPUT FORMAT]
Return exactly this structure and no extra text:
Decision: APPROVED | REJECTED | APPROVED_WITH_CORRECTIONS
Critical issues (must fix before merging): [list each issue on a new line, or "none"]
Important issues (should fix before merging): [list each issue on a new line, or "none"]
Minor issues (can fix in a later pass): [list each issue on a new line, or "none"]
Corrected fragment: [full corrected Manchester Syntax if Decision is not APPROVED, otherwise "N/A"]
"""


def parse_judge_response(response: str) -> dict:
    result = {"decision": "REJECTED", "critical": [], "important": [], "minor": [], "corrected": None}
    if not response:
        result["critical"] = ["Judge-LLM returned empty response"]
        return result
    m = re.search(r"Decision:\s*(APPROVED_WITH_CORRECTIONS|APPROVED|REJECTED)", response, re.I)
    if m:
        result["decision"] = m.group(1).upper()

    def section(title: str, next_titles: str) -> list[str]:
        sm = re.search(rf"{title}.*?:\s*(.*?)(?=\n(?:{next_titles})|\Z)", response, re.I | re.S)
        if not sm:
            return []
        text = sm.group(1).strip()
        if text.lower() in {"none", "n/a", ""}:
            return []
        return [ln.strip("- *\t ") for ln in text.splitlines() if ln.strip() and ln.strip("- *\t ").lower() != "none"]

    result["critical"] = section("Critical issues", "Important issues|Minor issues|Corrected fragment")
    result["important"] = section("Important issues", "Minor issues|Corrected fragment")
    result["minor"] = section("Minor issues", "Corrected fragment")
    m2 = re.search(r"Corrected fragment:\s*(.*)\Z", response, re.I | re.S)
    if m2 and m2.group(1).strip().lower() not in {"n/a", "none", "", '"n/a"'}:
        result["corrected"] = m2.group(1).strip()
    return result


# ---------------------------------------------------------------- 결정적 검사

@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _named(g: Graph, t) -> set[URIRef]:
    return {s for s in g.subjects(RDF.type, t) if isinstance(s, URIRef)}


def validate_graph(g: Graph, tables: list[dict], known_tables: set[str]) -> Report:
    """RIGOR validate_graph_against_rigor: 형식 일관성, 도메인·범위, 스키마 포괄성."""
    r = Report()
    obj, data = _named(g, OWL.ObjectProperty), _named(g, OWL.DatatypeProperty)
    for p in sorted(obj & data):
        r.errors.append(f"Property {naming.local_name(p)} is both owl:ObjectProperty and owl:DatatypeProperty")
    for p in sorted(obj | data):
        domains, ranges = list(g.objects(p, RDFS.domain)), list(g.objects(p, RDFS.range))
        if len(domains) != 1:
            r.errors.append(f"Property {naming.local_name(p)} has {len(domains)} domains, expected exactly 1")
        if len(ranges) != 1:
            r.errors.append(f"Property {naming.local_name(p)} has {len(ranges)} ranges, expected exactly 1")
        if p in data and ranges and not str(ranges[0]).startswith(str(XSD)):
            r.errors.append(f"Datatype property {naming.local_name(p)} has non-XSD range {ranges[0]}")
        if p in obj and domains and ranges and domains[0] == ranges[0]:
            comments = " ".join(str(c).lower() for c in g.objects(p, RDFS.comment))
            if "recursive" not in comments and "self" not in comments:
                r.errors.append(f"Object property {naming.local_name(p)} is self-referential without explicit recursive justification")
    for t in tables:
        name = t["name"]
        if (naming.class_iri(name), RDF.type, OWL.Class) not in g:
            r.errors.append(f"Missing class for table {name}")
        for c in t["columns"]:
            dp = naming.data_property_iri(name, c["name"])
            if c["fk"] and c["fk"]["table"] in known_tables:
                op = naming.object_property_iri(name, c["name"], c["fk"]["table"])
                if (op, RDF.type, OWL.ObjectProperty) not in g:
                    r.errors.append(f"Missing ObjectProperty for FK {name}.{c['name']} -> {c['fk']['table']}.{c['fk']['column']}")
                if (dp, RDF.type, OWL.DatatypeProperty) in g:
                    r.errors.append(f"FK column {name}.{c['name']} also appears as DatatypeProperty {naming.local_name(dp)}")
            elif not c["fk"] and (dp, RDF.type, OWL.DatatypeProperty) not in g:
                r.errors.append(f"Missing DatatypeProperty for non-FK column {name}.{c['name']}")
    for e in sorted(_named(g, OWL.Class) | obj | data):
        for pred, what in ((RDFS.label, "rdfs:label"), (RDFS.comment, "rdfs:comment"), (PROV.wasDerivedFrom, "prov:wasDerivedFrom")):
            if not list(g.objects(e, pred)):
                r.warnings.append(f"Missing {what} for {naming.local_name(e)}")
    return r


def inspect_delta(parsed, core: Graph, table: str) -> Report:
    """파싱 결과 검사 (원본 RIGOR에 없는 단계). 병합 전에 조각 자체가 믿을 만한지 본다."""
    r = Report(warnings=list(parsed.warnings))
    g = parsed.graph
    if not parsed.declared or len(g) == 0:
        r.errors.append("The fragment contained no parsable Class / DataProperty / ObjectProperty frames.")
        return r
    # 선언 없이 언급만 된 클래스 = 오타이거나, 식을 이름으로 잘못 쓴 것
    known = _named(core, OWL.Class) | {c for c in parsed.declared if (c, RDF.type, OWL.Class) in g}
    for c in sorted(parsed.referenced_classes - known):
        r.errors.append(f"Class {naming.local_name(c)} is referenced but never declared with a 'Class:' frame (and is not in the core ontology)")
    # 속성으로 쓰였는데 어디에도 선언이 없는 이름
    props = _named(core, OWL.ObjectProperty) | _named(core, OWL.DatatypeProperty) | _named(g, OWL.ObjectProperty) | _named(g, OWL.DatatypeProperty)
    for p in sorted({o for o in g.objects(None, OWL.onProperty) if isinstance(o, URIRef)} - props):
        r.errors.append(f"Restriction uses undeclared property {naming.local_name(p)}")
    for s, o in g.subject_objects(OWL.inverseOf):
        if o not in props:
            r.errors.append(f"InverseOf target {naming.local_name(o)} of {naming.local_name(s)} is not a declared property")
    # 새로 들어온 요소에 출처가 없으면 처리 중인 테이블을 출처로 붙인다 (모든 요소에 출처가 있어야 한다)
    for e in sorted(parsed.declared):
        if not list(core.objects(e, PROV.wasDerivedFrom)) and not list(g.objects(e, PROV.wasDerivedFrom)):
            g.add((e, PROV.wasDerivedFrom, naming.provenance_iri(table)))
            r.warnings.append(f"{naming.local_name(e)}: 출처가 없어 테이블 '{table}'을(를) 출처로 기록함")
    return r


def merge_delta(core: Graph, delta: Graph) -> None:
    """조각을 병합한다. 라벨은 요소마다 하나만 남기고(보강된 것), 나머지는 합집합."""
    for s in {s for s in delta.subjects(RDFS.label, None)}:
        core.remove((s, RDFS.label, None))
    for s, p, o in delta:
        if isinstance(s, BNode) or isinstance(o, BNode):
            continue
        core.add((s, p, o))
    # 빈 노드(제약)는 같은 내용이 이미 있으면 다시 넣지 않는다
    def signature(g: Graph, b: BNode):
        return frozenset((p, o) for p, o in g.predicate_objects(b) if not isinstance(o, BNode))

    for s, p, b in delta.triples((None, None, None)):
        if not isinstance(b, BNode) or isinstance(s, BNode):
            continue
        sig = signature(delta, b)
        if any(isinstance(x, BNode) and signature(core, x) == sig for x in core.objects(s, p)):
            continue
        core.add((s, p, b))
        stack = [b]
        while stack:  # 빈 노드에 딸린 트리플(제약 내용, 리스트)을 따라가며 복사
            n = stack.pop()
            for pp, oo in delta.predicate_objects(n):
                core.add((n, pp, oo))
                if isinstance(oo, BNode):
                    stack.append(oo)


# ---------------------------------------------------------------- 파이프라인

def _counts(g: Graph) -> dict:
    return {"classes": len(_named(g, OWL.Class)), "data_properties": len(_named(g, OWL.DatatypeProperty)),
            "object_properties": len(_named(g, OWL.ObjectProperty)), "triples": len(g)}


def generate(db: str, schema: dict, xsd: dict, llm: LLM | None, result: dict) -> Iterator[Event]:
    """온톨로지를 만들며 진행 이벤트를 내보낸다. 끝나면 result['graph'] 에 그래프가 들어 있다.

    llm 이 None 이면 Direct Mapping 만 수행한다.
    """
    tables = {t["name"]: t for t in schema["tables"]}
    known = set(tables)
    order = fk_order(schema)
    core = bind_namespaces(Graph())
    core.add((URIRef(naming.ONTOLOGY_IRI), RDF.type, OWL.Ontology))
    yield {"type": "start", "db": db, "order": order, "mode": "rigor" if llm else "direct"}

    outcomes: dict[str, str] = {}
    for index, name in enumerate(order, start=1):
        table = tables[name]

        def step(step_name: str, status: str, **extra) -> Event:
            return {"type": "step", "table": name, "step": step_name, "status": status, **extra}

        yield {"type": "table_start", "table": name, "index": index, "total": len(order)}

        # 1) Direct Mapping 뼈대: 먼저 병합해 포괄성을 보장한다
        yield step("direct_mapping", "running")
        dm_graph = direct_mapping_for_table(table, xsd, known)
        core += dm_graph
        dm_text = render_direct_mapping_manchester(table, xsd, known)
        c = _counts(dm_graph)
        yield step("direct_mapping", "done", detail=f"클래스 1 · 데이터 속성 {c['data_properties']} · 객체 속성 {c['object_properties']}", text=dm_text)

        outcome = "direct_only"
        if llm is not None:
            # 2) 맥락 검색
            yield step("context", "running")
            schema_str = schema_json_for_table(table, tables, xsd)
            fk_str = foreign_keys_text(table)
            docs = documentation_for_table(db, table)
            core_ctx = core_context_for_table(core, table, tables)
            yield step("context", "done",
                       detail=f"컬럼 설명 {max(docs.count(chr(10)), 0)}건 · 기존 온톨로지 요소 {len(core_ctx.splitlines()) if core_ctx else 0}건",
                       text=(docs or "(컬럼 설명 없음)") + "\n\n[이미 만들어진 온톨로지]\n" + (core_ctx or "(없음)"))

            hint, accepted = "", None
            processed = [tables[t] for t in order[:index]]
            for attempt in range(1, MAX_JUDGE_RETRIES + 2):
                # 3) 생성 LLM
                yield step("generate", "running", attempt=attempt)
                delta_raw = yield from llm(generation_prompt(name, dm_text, schema_str, fk_str, docs, core_ctx, "", hint))
                if not delta_raw:
                    hint = "The previous Gen-LLM response was empty. Return a valid Manchester Syntax delta ontology."
                    yield step("generate", "failed", attempt=attempt, detail="빈 응답")
                    continue
                yield step("generate", "done", attempt=attempt, detail=f"{len(delta_raw):,}자", text=delta_raw)

                # 4) 판정 LLM
                yield step("judge", "running", attempt=attempt)
                verdict = parse_judge_response((yield from llm(judge_prompt(name, dm_text, delta_raw, schema_str, fk_str, core_ctx))))
                issues = {k: verdict[k] for k in ("critical", "important", "minor")}
                if verdict["decision"] == "REJECTED":
                    hint = ("The previous attempt was rejected by the Judge-LLM. Fix ALL of these critical issues:\n"
                            + "\n".join(f"- {x}" for x in verdict["critical"]))
                    yield step("judge", "failed", attempt=attempt, decision="REJECTED", issues=issues,
                               detail=f"거부 (치명적 문제 {len(verdict['critical'])}건)")
                    continue
                yield step("judge", "done", attempt=attempt, decision=verdict["decision"], issues=issues,
                           detail="통과" if verdict["decision"] == "APPROVED" else "수정 후 통과")
                text = verdict["corrected"] if verdict["decision"] == "APPROVED_WITH_CORRECTIONS" and verdict["corrected"] else delta_raw

                # 파싱 → 조각 검사 → 병합 후 그래프 검사 (결정적)
                yield step("validate", "running", attempt=attempt)
                parsed = parse_manchester(text)
                report = inspect_delta(parsed, core, name)
                if report.ok:
                    candidate = Graph()
                    candidate += core
                    merge_delta(candidate, parsed.graph)
                    structural = validate_graph(candidate, processed, known)
                    report.errors += structural.errors
                if report.ok:
                    accepted = parsed.graph
                    yield step("validate", "done", attempt=attempt, warnings=report.warnings[:30],
                               detail=f"검사 통과 · 트리플 {len(parsed.graph)}개" + (f" · 경고 {len(report.warnings)}건" if report.warnings else ""))
                    break
                hint = ("The previous fragment passed or was corrected by the Judge-LLM, but failed deterministic RDF graph "
                        "validation after parsing. Fix ALL of these structural errors:\n"
                        + "\n".join(f"- {x}" for x in report.errors[:20]) + "\nReturn only corrected Manchester Syntax.")
                yield step("validate", "failed", attempt=attempt, errors=report.errors[:20], warnings=report.warnings[:30],
                           detail=f"검사 실패 (오류 {len(report.errors)}건)")

            if accepted is not None:
                merge_delta(core, accepted)
                outcome = "enriched"

        # 테이블 처리 후에도 포괄성이 깨지지 않았는지 확인
        post = validate_graph(core, [table], known)
        if not post.ok:
            raise RuntimeError(f"{name}: 병합 후 검사 실패: " + "; ".join(post.errors[:5]))
        outcomes[name] = outcome
        yield {"type": "table_done", "table": name, "index": index, "total": len(order), "outcome": outcome,
               "class_iri": str(naming.class_iri(name)), "counts": _counts(core), "view": graph_to_view(core)}

    final = validate_graph(core, list(tables.values()), known)
    if not final.ok:
        raise RuntimeError("최종 검사 실패: " + "; ".join(final.errors[:5]))
    result["graph"] = core
    result["outcomes"] = outcomes
    result["warnings"] = final.warnings
