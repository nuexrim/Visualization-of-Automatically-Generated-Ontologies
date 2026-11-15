"""Direct Mapping: 스키마 → OWL 뼈대 (테이블 → 클래스, 일반 컬럼 → 데이터 속성, 외래 키 → 객체 속성).

RIGOR의 direct_mapping_graph_for_table 과, 논문 실험에서 쓴 스키마 추출(config/db_to_schema.py)의
자료형 규칙을 옮긴 것이다 (MIT License, Copyright (c) 2026 Nadeen Fathallah).
"""
from __future__ import annotations

import re
from collections import defaultdict, deque

import psycopg
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, PROV, RDF, RDFS, SKOS, XSD

from backend.ontology import naming

PG_TO_XSD = {
    "bigint": XSD.integer, "integer": XSD.integer, "int": XSD.integer, "smallint": XSD.integer,
    "double precision": XSD.double, "real": XSD.float, "numeric": XSD.decimal, "decimal": XSD.decimal,
    "text": XSD.string, "character varying": XSD.string, "varchar": XSD.string, "character": XSD.string, "char": XSD.string,
    "boolean": XSD.boolean, "date": XSD.date, "time without time zone": XSD.time, "time": XSD.time,
    "timestamp without time zone": XSD.dateTime, "timestamp with time zone": XSD.dateTime, "timestamp": XSD.dateTime,
    "bytea": XSD.base64Binary,
}
# 텍스트 컬럼인데 모든 값이 날짜 모양이면 날짜 자료형으로 본다 (먼저 맞는 규칙 적용)
DATE_RULES = [
    (XSD.dateTime, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d+)?$"),
    (XSD.date, r"^\d{4}-\d{2}-\d{2}$"),
]


def bind_namespaces(g: Graph) -> Graph:
    g.bind("", naming.ONT)
    g.bind("ont", naming.ONT)
    g.bind("owl", OWL)
    g.bind("xsd", XSD)
    g.bind("rdfs", RDFS)
    g.bind("prov", PROV)
    g.bind("skos", SKOS)
    return g


def _fix_date_type(column: str, xsd: URIRef) -> URIRef:
    """컬럼 이름으로 날짜 자료형을 추정 (RIGOR fix_date_type)."""
    lower = column.lower()
    if xsd in {XSD.float, XSD.double, XSD.decimal, XSD.string}:
        if any(tok in lower for tok in ("datetime", "timestamp", "created_at", "updated_at")):
            return XSD.dateTime
        if "date" in lower:
            return XSD.date
        if lower.endswith("time") or "_time" in lower:
            return XSD.time
    return xsd


def column_xsd_types(schema: dict, conn: psycopg.Connection | None = None) -> dict[tuple[str, str], URIRef]:
    """{(테이블, 컬럼): xsd 자료형}. conn을 주면 텍스트 컬럼의 실제 값을 보고 날짜 자료형을 추정한다."""
    out: dict[tuple[str, str], URIRef] = {}
    for t in schema["tables"]:
        for c in t["columns"]:
            base = re.sub(r"\(.*\)", "", c["type"]).strip().lower()
            xsd = PG_TO_XSD.get(base, XSD.string)
            if conn is not None and xsd == XSD.string and not c["pk"] and not c["fk"]:
                col, tab = c["name"].replace('"', '""'), t["name"].replace('"', '""')
                for new, pattern in DATE_RULES:
                    bad, n = conn.execute(
                        f'SELECT count(*) FILTER (WHERE "{col}" IS NOT NULL AND "{col}" !~ %s), count("{col}") FROM "{tab}"',
                        (pattern,),
                    ).fetchone()
                    if n and not bad:
                        xsd = new
                        break
            out[(t["name"], c["name"])] = _fix_date_type(c["name"], xsd)
    return out


def fk_order(schema: dict) -> list[str]:
    """외래 키 의존 순서: 참조되는 테이블이 참조하는 테이블보다 먼저 (RIGOR traverse_schema_fk_order)."""
    names = [t["name"] for t in schema["tables"]]
    children: dict[str, set[str]] = defaultdict(set)
    indegree = {t: 0 for t in names}
    for fk in schema["foreign_keys"]:
        child, parent = fk["from_table"], fk["to_table"]
        if parent != child and child not in children[parent]:
            children[parent].add(child)
            indegree[child] += 1
    roots = sorted(t for t, d in indegree.items() if d == 0)
    queue, seen, order = deque(roots or sorted(names)), set(), []
    while queue:
        t = queue.popleft()
        if t in seen:
            continue
        seen.add(t)
        order.append(t)
        for child in sorted(children[t]):
            indegree[child] -= 1
            if indegree[child] <= 0:
                queue.append(child)
    return order + [t for t in sorted(names) if t not in seen]  # 순환에 걸린 테이블은 이름순으로 뒤에


def _annotate(g: Graph, s: URIRef, label: str, comment: str, source: URIRef) -> None:
    g.add((s, RDFS.label, Literal(label, lang="en")))
    g.add((s, RDFS.comment, Literal(comment, lang="en")))
    g.add((s, PROV.wasDerivedFrom, source))


def _restriction(g: Graph, cls: URIRef, prop: URIRef, kind: URIRef, filler: URIRef) -> None:
    r = BNode()
    g.add((r, RDF.type, OWL.Restriction))
    g.add((r, OWL.onProperty, prop))
    g.add((r, kind, filler))
    g.add((cls, RDFS.subClassOf, r))


def _xsd_prefixed(x: URIRef) -> str:
    s = str(x)
    return f"xsd:{s[len(str(XSD)):]}" if s.startswith(str(XSD)) else s


def direct_mapping_for_table(table: dict, xsd: dict[tuple[str, str], URIRef], known_tables: set[str]) -> Graph:
    """테이블 하나의 Direct Mapping 그래프."""
    g = bind_namespaces(Graph())
    name = table["name"]
    cls = naming.class_iri(name)
    g.add((cls, RDF.type, OWL.Class))
    _annotate(g, cls, naming.humanize_identifier(naming.to_class_name(name)),
              f"Class generated from source table '{name}'.", naming.provenance_iri(name))

    keys: list[URIRef] = []
    for c in table["columns"]:
        col = c["name"]
        required = c["pk"] or c.get("unique") or not c["nullable"]
        if c["fk"]:
            ref = c["fk"]["table"]
            if ref not in known_tables:
                continue
            prop = naming.object_property_iri(name, col, ref)
            rng = naming.class_iri(ref)
            g.add((rng, RDF.type, OWL.Class))
            g.add((prop, RDF.type, OWL.ObjectProperty))
            comment = f"Object property generated from foreign key '{name}.{col}' referencing '{ref}.{c['fk']['column']}'."
            if ref == name:
                comment += f" This is an explicit recursive self-referential relationship within the {naming.to_class_name(name)} class."
            label = naming.humanize_identifier(naming.local_name(prop))
        else:
            prop = naming.data_property_iri(name, col)
            rng = xsd[(name, col)]
            g.add((prop, RDF.type, OWL.DatatypeProperty))
            comment = f"Data property generated from source column '{name}.{col}' with range {_xsd_prefixed(rng)}."
            if rng == XSD.integer and re.search(r"(stage|score|status|grade|class|category|type)$", col, re.I):
                comment += " This integer-valued property may encode a categorical or ordinal concept; consult source documentation for value meanings."
            label = naming.humanize_identifier(col)
        g.add((prop, RDFS.domain, cls))
        g.add((prop, RDFS.range, rng))
        _annotate(g, prop, label, comment, naming.provenance_iri(name, col))
        _restriction(g, cls, prop, OWL.allValuesFrom, rng)
        if required:
            _restriction(g, cls, prop, OWL.someValuesFrom, rng)
        if c["pk"]:
            keys.append(prop)

    if keys:  # owl:hasKey (RDF 리스트)
        head = cur = BNode()
        g.add((cls, OWL.hasKey, head))
        for i, p in enumerate(keys):
            g.add((cur, RDF.first, p))
            nxt = RDF.nil if i == len(keys) - 1 else BNode()
            g.add((cur, RDF.rest, nxt))
            cur = nxt
    return g


def direct_mapping(schema: dict, conn: psycopg.Connection | None = None) -> Graph:
    """DB 전체의 Direct Mapping 그래프 (외래 키 의존 순서로 테이블을 처리해 합친다)."""
    xsd = column_xsd_types(schema, conn)
    tables = {t["name"]: t for t in schema["tables"]}
    g = bind_namespaces(Graph())
    g.add((URIRef(naming.ONTOLOGY_IRI), RDF.type, OWL.Ontology))
    for name in fk_order(schema):
        g += direct_mapping_for_table(tables[name], xsd, set(tables))
    return g
