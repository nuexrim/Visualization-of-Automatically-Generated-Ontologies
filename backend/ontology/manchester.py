"""생성 LLM이 내놓는 Manchester Syntax 조각을 rdflib 그래프로 읽는다.

RIGOR의 parse_llm_ontology 를 대신한다. 원본 파서의 결함을 막는다:
- `p exactly 1 X` 같은 제약을 클래스 이름으로 오인해 가짜 클래스를 만들던 문제 → 제약으로 읽고, 못 읽는 식은 버리고 경고
- `InverseOf:` 를 무시하던 문제 → owl:inverseOf 로 읽음
- 여러 줄에 걸친 `SubClassOf:` 항목을 조용히 버리던 문제 → 구획 단위로 읽음
읽지 못한 것은 전부 warnings 에 남겨 호출한 쪽이 검사할 수 있게 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, PROV, RDF, RDFS, SKOS, XSD

from backend.ontology import naming
from backend.ontology.direct_mapping import bind_namespaces

XSD_NAMES = {
    "string": XSD.string, "integer": XSD.integer, "int": XSD.integer, "long": XSD.integer, "float": XSD.float,
    "boolean": XSD.boolean, "bool": XSD.boolean, "datetime": XSD.dateTime, "date": XSD.date, "time": XSD.time,
    "decimal": XSD.decimal, "double": XSD.double, "base64binary": XSD.base64Binary, "anyuri": XSD.anyURI,
    "gyear": XSD.gYear, "nonnegativeinteger": XSD.nonNegativeInteger, "positiveinteger": XSD.positiveInteger,
}
FRAME_KINDS = {"Class": OWL.Class, "DataProperty": OWL.DatatypeProperty, "ObjectProperty": OWL.ObjectProperty}
# 읽지 않고 넘기는 최상위 구획
SKIPPED_FRAMES = ("Prefix", "Ontology", "Import", "AnnotationProperty", "Individual", "Datatype")
TOP_LEVEL_AXIOMS = ("DisjointClasses", "EquivalentClasses", "DisjointProperties", "EquivalentProperties")
SECTIONS = (
    "Annotations", "SubClassOf", "EquivalentTo", "DisjointWith", "DisjointUnionOf", "HasKey",
    "Domain", "Range", "SubPropertyOf", "InverseOf", "Characteristics", "SubPropertyChain",
)
CHARACTERISTICS = {
    "functional": OWL.FunctionalProperty, "inversefunctional": OWL.InverseFunctionalProperty,
    "transitive": OWL.TransitiveProperty, "symmetric": OWL.SymmetricProperty, "asymmetric": OWL.AsymmetricProperty,
    "reflexive": OWL.ReflexiveProperty, "irreflexive": OWL.IrreflexiveProperty,
}
_NAME = r"[A-Za-z_][A-Za-z0-9_\-]*"
_HEADER = re.compile(rf"^({'|'.join(list(FRAME_KINDS) + list(SKIPPED_FRAMES) + list(TOP_LEVEL_AXIOMS))})\s*:\s*(.*)$")
_SECTION = re.compile(rf"^({'|'.join(SECTIONS)})\s*:\s*(.*)$")


@dataclass
class ParseResult:
    graph: Graph
    warnings: list[str] = field(default_factory=list)
    #: `Class:` / `DataProperty:` / `ObjectProperty:` 로 선언된 이름들
    declared: set[URIRef] = field(default_factory=set)
    #: 상위 클래스·도메인·범위 등으로 "언급만" 된 클래스 (선언 여부는 호출한 쪽이 검사)
    referenced_classes: set[URIRef] = field(default_factory=set)


def strip_fences(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines() if not line.strip().startswith("```"))


def split_top_level(text: str) -> list[str]:
    """쉼표로 나누되 따옴표, 괄호, <IRI> 안의 쉼표는 건드리지 않는다."""
    items, cur, depth, quote, angle, i = [], [], 0, False, False, 0
    while i < len(text):
        ch = text[i]
        if quote:
            cur.append(ch)
            if ch == "\\" and i + 1 < len(text):
                cur.append(text[i + 1])
                i += 1
            elif ch == '"':
                quote = False
        elif angle:
            cur.append(ch)
            angle = ch != ">"
        elif ch == '"':
            quote = True
            cur.append(ch)
        elif ch == "<" and re.match(r"<[A-Za-z][A-Za-z0-9+.\-]*:[^\s<>]*>", text[i:]):
            angle = True
            cur.append(ch)
        elif ch in "([{":
            depth += 1
            cur.append(ch)
        elif ch in ")]}":
            depth = max(0, depth - 1)
            cur.append(ch)
        elif ch == "," and depth == 0:
            items.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    items.append("".join(cur).strip())
    return [x for x in items if x]


def _entity(token: str) -> URIRef | None:
    """클래스·속성 이름 하나 → IRI. 이름 하나가 아니면 None (식을 이름으로 오인하지 않는다)."""
    t = token.strip()
    if t.startswith("<") and t.endswith(">"):
        return URIRef(t[1:-1])
    if t in ("owl:Thing", "Thing"):
        return OWL.Thing
    if t.startswith(":"):
        t = t[1:]
    elif t.startswith("ont:"):
        t = t[4:]
    return naming.ONT[t] if re.fullmatch(_NAME, t) else None


def _datatype(token: str) -> URIRef | None:
    t = token.strip()
    if t.startswith("<") and t.endswith(">") and t[1:-1].startswith(str(XSD)):
        return URIRef(t[1:-1])
    if t.lower().startswith("xsd:"):
        return XSD_NAMES.get(t[4:].lower())
    return None


def _literal(text: str) -> Literal | None:
    m = re.fullmatch(r'"((?:[^"\\]|\\.)*)"(?:@([A-Za-z\-]+)|\^\^(\S+))?', text.strip(), re.S)
    if not m:
        return None
    value = re.sub(r"\\(.)", r"\1", m.group(1))
    if m.group(3):
        return Literal(value, datatype=_datatype(m.group(3)) or XSD.string)
    return Literal(value, lang=m.group(2) or "en")


class _Parser:
    def __init__(self) -> None:
        self.r = ParseResult(bind_namespaces(Graph()))
        self.g = self.r.graph

    def warn(self, msg: str) -> None:
        self.r.warnings.append(msg)

    def cls(self, token: str) -> URIRef | None:
        c = _entity(token)
        if c is not None and c != OWL.Thing:
            self.r.referenced_classes.add(c)
        return c

    # ---- 클래스 식 (SubClassOf / EquivalentTo 의 항목) ----
    def class_expression(self, expr: str, subject_name: str):
        e = expr.strip()
        while e.startswith("(") and e.endswith(")"):
            e = e[1:-1].strip()
        m = re.fullmatch(rf"(:?{_NAME})\s+(some|only)\s+(\S+)", e)
        if m:
            filler = _datatype(m.group(3)) or self.cls(m.group(3))
            if filler is None:
                return self.warn(f"{subject_name}: 제약의 대상 '{m.group(3)}'을(를) 읽지 못해 버림: {e}")
            b = BNode()
            self.g.add((b, RDF.type, OWL.Restriction))
            self.g.add((b, OWL.onProperty, _entity(m.group(1))))
            self.g.add((b, OWL.someValuesFrom if m.group(2) == "some" else OWL.allValuesFrom, filler))
            return b
        m = re.fullmatch(rf"(:?{_NAME})\s+(exactly|min|max)\s+(\d+)(?:\s+(\S+))?", e)
        if m:  # 개수 제약. 원본 파서는 이것을 클래스 이름으로 오인했다.
            n = Literal(int(m.group(3)), datatype=XSD.nonNegativeInteger)
            b = BNode()
            self.g.add((b, RDF.type, OWL.Restriction))
            self.g.add((b, OWL.onProperty, _entity(m.group(1))))
            word, on = m.group(2), m.group(4)
            if on and on not in ("owl:Thing", "Thing", "rdfs:Literal"):
                dt = _datatype(on)
                target = dt or self.cls(on)
                if target is None:
                    return self.warn(f"{subject_name}: 개수 제약의 대상 '{on}'을(를) 읽지 못해 버림: {e}")
                pred = {"exactly": OWL.qualifiedCardinality, "min": OWL.minQualifiedCardinality, "max": OWL.maxQualifiedCardinality}[word]
                self.g.add((b, OWL.onDataRange if dt else OWL.onClass, target))
            else:
                pred = {"exactly": OWL.cardinality, "min": OWL.minCardinality, "max": OWL.maxCardinality}[word]
            self.g.add((b, pred, n))
            return b
        named = self.cls(e)
        if named is not None:
            return named
        self.warn(f"{subject_name}: 읽을 수 없는 식이라 버림: {e[:120]}")
        return None

    def annotations(self, subject: URIRef, body: str, name: str) -> None:
        for item in split_top_level(body):
            m = re.match(r"(\S+)\s+(.+)$", item, re.S)
            if not m:
                self.warn(f"{name}: 읽을 수 없는 주석 항목: {item[:80]}")
                continue
            key, value = m.group(1).lower(), m.group(2).strip()
            if key in ("rdfs:label", "rdfs:comment", "skos:definition", "skos:preflabel"):
                lit = _literal(value)
                if lit is None:
                    self.warn(f"{name}: {m.group(1)} 값이 문자열이 아니라 버림: {value[:80]}")
                    continue
                pred = {"rdfs:label": RDFS.label, "rdfs:comment": RDFS.comment,
                        "skos:definition": SKOS.definition, "skos:preflabel": SKOS.prefLabel}[key]
                self.g.add((subject, pred, lit))
            elif key in ("prov:wasderivedfrom", "skos:exactmatch", "skos:closematch", "rdfs:seealso"):
                if not (value.startswith("<") and value.endswith(">")):
                    self.warn(f"{name}: {m.group(1)} 값이 IRI가 아니라 버림: {value[:80]}")
                    continue
                pred = {"prov:wasderivedfrom": PROV.wasDerivedFrom, "skos:exactmatch": SKOS.exactMatch,
                        "skos:closematch": SKOS.closeMatch, "rdfs:seealso": RDFS.seeAlso}[key]
                self.g.add((subject, pred, URIRef(value[1:-1])))
            else:
                self.warn(f"{name}: 지원하지 않는 주석 속성 {m.group(1)}")

    def frame(self, kind: str, name: str, sections: list[tuple[str, str]]) -> None:
        subject = _entity(name)
        if subject is None or subject == OWL.Thing:
            return self.warn(f"{kind} 이름이 올바르지 않아 구획 전체를 버림: {name[:80]}")
        self.g.add((subject, RDF.type, FRAME_KINDS[kind]))
        self.r.declared.add(subject)
        is_class, is_data = kind == "Class", kind == "DataProperty"
        for section, body in sections:
            items = split_top_level(body)
            if section == "Annotations":
                self.annotations(subject, body, name)
            elif is_class and section in ("SubClassOf", "EquivalentTo"):
                pred = RDFS.subClassOf if section == "SubClassOf" else OWL.equivalentClass
                for item in items:
                    node = self.class_expression(item, name)
                    if node is not None and node != subject:
                        self.g.add((subject, pred, node))
            elif is_class and section == "DisjointWith":
                for item in items:
                    other = self.cls(item)
                    if other is None:
                        self.warn(f"{name}: DisjointWith 대상이 클래스 이름이 아니라 버림: {item[:80]}")
                    elif other != subject:
                        self.g.add((subject, OWL.disjointWith, other))
            elif is_class and section == "HasKey":
                props = [_entity(t) for t in re.split(r"[\s,]+", body.strip()) if t]
                if props and all(p is not None for p in props):
                    head = cur = BNode()
                    self.g.add((subject, OWL.hasKey, head))
                    for i, p in enumerate(props):
                        self.g.add((cur, RDF.first, p))
                        nxt = RDF.nil if i == len(props) - 1 else BNode()
                        self.g.add((cur, RDF.rest, nxt))
                        cur = nxt
                else:
                    self.warn(f"{name}: HasKey 를 읽지 못해 버림: {body[:80]}")
            elif not is_class and section == "Domain":
                for item in items:
                    d = self.cls(item)
                    if d is None:
                        self.warn(f"{name}: Domain 이 클래스 이름이 아니라 버림: {item[:80]}")
                    else:
                        self.g.add((subject, RDFS.domain, d))
            elif not is_class and section == "Range":
                for item in items:
                    rng = _datatype(item) if is_data else self.cls(item)
                    if rng is None:
                        what = "XSD 자료형" if is_data else "클래스 이름"
                        self.warn(f"{name}: Range 가 {what}이(가) 아니라 버림: {item[:80]}")
                    else:
                        self.g.add((subject, RDFS.range, rng))
            elif not is_class and section in ("SubPropertyOf", "EquivalentTo", "InverseOf"):
                if section == "InverseOf" and is_data:
                    self.warn(f"{name}: 데이터 속성에는 InverseOf 를 쓸 수 없어 버림")
                    continue
                pred = {"SubPropertyOf": RDFS.subPropertyOf, "EquivalentTo": OWL.equivalentProperty, "InverseOf": OWL.inverseOf}[section]
                for item in items:
                    other = _entity(item)
                    if other is None:
                        self.warn(f"{name}: {section} 대상이 속성 이름이 아니라 버림: {item[:80]}")
                    elif other != subject:
                        self.g.add((subject, pred, other))
            elif not is_class and section == "Characteristics":
                for item in items:
                    c = CHARACTERISTICS.get(item.strip().lower())
                    if c is None:
                        self.warn(f"{name}: 알 수 없는 Characteristics '{item[:40]}'")
                    else:
                        self.g.add((subject, RDF.type, c))
            elif body.strip():
                self.warn(f"{name}: {kind} 에서 지원하지 않는 구획 {section} 을(를) 버림")

    def top_level_axiom(self, kind: str, body: str) -> None:
        if kind != "DisjointClasses":
            return self.warn(f"지원하지 않는 최상위 구문 {kind} 을(를) 버림")
        classes = [self.cls(t) for t in split_top_level(body)]
        if len(classes) < 2 or any(c is None for c in classes):
            return self.warn(f"DisjointClasses 를 읽지 못해 버림: {body[:80]}")
        for i, a in enumerate(classes):
            for b in classes[i + 1:]:
                self.g.add((a, OWL.disjointWith, b))


def parse_manchester(text: str) -> ParseResult:
    p = _Parser()
    frame: tuple[str, str] | None = None  # (종류, 이름)
    sections: list[list[str]] = []        # [[구획 이름, 본문], ...]
    skipping = False

    def flush() -> None:
        if frame and frame[0] in FRAME_KINDS:
            p.frame(frame[0], frame[1], [(s, b) for s, b in sections])
        elif frame and frame[0] in TOP_LEVEL_AXIOMS:
            p.top_level_axiom(frame[0], frame[1] + " " + " ".join(b for _, b in sections))

    for raw in strip_fences(text).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        h = _HEADER.match(line)
        # 주석 본문 안의 "Class: ..." 같은 문장을 새 구획으로 오인하지 않게, 따옴표가 열려 있으면 본문으로 본다
        open_quote = bool(sections) and sections[-1][1].replace('\\"', "").count('"') % 2 == 1
        if h and not open_quote:
            flush()
            kind, rest = h.group(1), h.group(2).strip()
            skipping = kind in SKIPPED_FRAMES
            frame, sections = (kind, rest), []
            if kind in TOP_LEVEL_AXIOMS:
                frame, sections = (kind, ""), [["", rest]]
            continue
        if skipping or frame is None:
            if frame is None:
                p.warn(f"구획 밖의 줄을 버림: {line[:80]}")
            continue
        s = None if open_quote else _SECTION.match(line)
        if s:
            sections.append([s.group(1), s.group(2)])
        elif sections:
            sections[-1][1] += " " + line
        else:
            p.warn(f"{frame[1]}: 구획 이름 없이 나온 줄을 버림: {line[:80]}")
    flush()
    return p.r
