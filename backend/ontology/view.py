"""rdflib 그래프 → 화면용 JSON (클래스, 속성, 관계, 트리플, 출처)."""
from __future__ import annotations

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, PROV, RDF, RDFS, XSD

from backend.ontology import naming

_PREFIXES = [
    (str(naming.ONT), "ont:"), (str(OWL), "owl:"), (str(RDFS), "rdfs:"), (str(RDF), "rdf:"),
    (str(XSD), "xsd:"), (str(PROV), "prov:"), ("http://www.w3.org/2004/02/skos/core#", "skos:"),
]


def short(term) -> str:
    """IRI를 접두어 표기로 줄인다 (예: ont:Film, xsd:integer)."""
    s = str(term)
    prov = naming.parse_provenance(s)
    if prov:
        return f"{prov[0]}.{prov[1]}" if prov[1] else prov[0]
    for full, prefix in _PREFIXES:
        if s.startswith(full):
            return prefix + s[len(full):]
    return s


def _rdf_list(g: Graph, head) -> list:
    out = []
    while head and head != RDF.nil and len(out) < 100:
        first = g.value(head, RDF.first)
        if first is not None:
            out.append(first)
        head = g.value(head, RDF.rest)
    return out


def render(g: Graph, term) -> str:
    """트리플 표에 보여줄 값. 빈 노드(제약, 리스트)는 읽을 수 있는 식으로 풀어 쓴다."""
    if isinstance(term, Literal):
        return str(term)
    if isinstance(term, URIRef):
        return short(term)
    if isinstance(term, BNode):
        prop = g.value(term, OWL.onProperty)
        if prop is not None:
            for pred, word in ((OWL.allValuesFrom, "only"), (OWL.someValuesFrom, "some"), (OWL.hasValue, "value")):
                filler = g.value(term, pred)
                if filler is not None:
                    return f"{short(prop)} {word} {render(g, filler)}"
            for pred, word in ((OWL.cardinality, "exactly"), (OWL.qualifiedCardinality, "exactly"),
                               (OWL.minCardinality, "min"), (OWL.minQualifiedCardinality, "min"),
                               (OWL.maxCardinality, "max"), (OWL.maxQualifiedCardinality, "max")):
                n = g.value(term, pred)
                if n is not None:
                    on = g.value(term, OWL.onClass) or g.value(term, OWL.onDataRange)
                    return f"{short(prop)} {word} {n}" + (f" {render(g, on)}" if on is not None else "")
            return f"restriction on {short(prop)}"
        if g.value(term, RDF.first) is not None:
            return "(" + ", ".join(render(g, x) for x in _rdf_list(g, term)) + ")"
        for pred, word in ((OWL.unionOf, " or "), (OWL.intersectionOf, " and ")):
            lst = g.value(term, pred)
            if lst is not None:
                return "(" + word.join(render(g, x) for x in _rdf_list(g, lst)) + ")"
        return "_:blank"
    return str(term)


def _source(g: Graph, s: URIRef) -> dict | None:
    for o in g.objects(s, PROV.wasDerivedFrom):
        parsed = naming.parse_provenance(str(o))
        if parsed:
            return {"table": parsed[0], "column": parsed[1]}
    return None


#: 코드값 의미 설명은 이 머리말을 붙인 rdfs:comment 로 저장한다 (edit.VALUE_PREFIX 와 같음)
VALUE_PREFIX = "Value meanings: "


def _entity(g: Graph, s: URIRef) -> dict:
    labels = sorted(str(o) for o in g.objects(s, RDFS.label))
    comments = [str(o) for o in g.objects(s, RDFS.comment)]
    values = [c[len(VALUE_PREFIX):] for c in comments if c.startswith(VALUE_PREFIX)]
    return {
        "iri": str(s),
        "name": naming.local_name(s),
        "label": labels[0] if labels else "",
        "comments": sorted((c for c in comments if not c.startswith(VALUE_PREFIX)), key=len),
        "value_description": values[0] if values else "",
        "source": _source(g, s),
    }


def _named(g: Graph, rdf_type) -> list[URIRef]:
    return sorted({s for s in g.subjects(RDF.type, rdf_type) if isinstance(s, URIRef)})


def _uris(g: Graph, s, p) -> list[str]:
    return sorted(str(o) for o in g.objects(s, p) if isinstance(o, URIRef))


def graph_to_view(g: Graph) -> dict:
    class_iris = _named(g, OWL.Class)
    declared = set(class_iris)
    classes = []
    extra_parents: set[URIRef] = set()
    for c in class_iris:
        parents = [o for o in g.objects(c, RDFS.subClassOf) if isinstance(o, URIRef) and o != c and o != OWL.Thing]
        extra_parents.update(p for p in parents if p not in declared)
        classes.append({**_entity(g, c), "parents": sorted(str(p) for p in parents), "external": False})
    for p in sorted(extra_parents):  # 선언 없이 상위 클래스로만 쓰인 것
        classes.append({**_entity(g, p), "parents": [], "external": True})

    data_properties = [
        {**_entity(g, p), "domains": _uris(g, p, RDFS.domain), "ranges": [short(o) for o in _uris(g, p, RDFS.range)]}
        for p in _named(g, OWL.DatatypeProperty)
    ]
    object_properties = [
        {**_entity(g, p), "domains": _uris(g, p, RDFS.domain), "ranges": _uris(g, p, RDFS.range),
         "inverse_of": _uris(g, p, OWL.inverseOf)}
        for p in _named(g, OWL.ObjectProperty)
    ]

    triples: dict[str, list[dict]] = {}
    for s in sorted({s for s in g.subjects() if isinstance(s, URIRef)}):
        rows = [
            {"p": short(p), "p_iri": str(p), "o": render(g, o),
             "kind": "literal" if isinstance(o, Literal) else "iri" if isinstance(o, URIRef) else "expr",
             "o_iri": str(o) if isinstance(o, URIRef) else None,
             "lang": o.language if isinstance(o, Literal) else None,
             "datatype": str(o.datatype) if isinstance(o, Literal) and o.datatype else None}
            for p, o in g.predicate_objects(s)
        ]
        triples[str(s)] = sorted(rows, key=lambda r: (r["p"], r["o"]))

    return {
        "classes": classes,
        "data_properties": data_properties,
        "object_properties": object_properties,
        "triples": triples,
        "counts": {"classes": len(class_iris), "data_properties": len(data_properties),
                   "object_properties": len(object_properties), "triples": len(g)},
    }
