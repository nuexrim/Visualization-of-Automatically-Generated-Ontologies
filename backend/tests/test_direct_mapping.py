import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, PROV, RDF, RDFS, XSD

from backend.ontology import naming
from backend.ontology.direct_mapping import direct_mapping, fk_order
from backend.ontology.view import graph_to_view


def col(name, typ="bigint", pk=False, fk=None, nullable=True):
    return {"name": name, "type": typ, "pk": pk, "unique": False, "nullable": nullable, "fk": fk}


SCHEMA = {
    "tables": [
        {"name": "film", "columns": [col("film_id", pk=True, nullable=False), col("title", "text", nullable=False),
                                      col("release_date", "text"), col("language_id", fk={"table": "language", "column": "language_id"})]},
        {"name": "language", "columns": [col("language_id", pk=True, nullable=False), col("name", "text")]},
    ],
    "foreign_keys": [{"from_table": "film", "from_column": "language_id", "to_table": "language", "to_column": "language_id"}],
}


def named(g, t):
    return {s for s in g.subjects(RDF.type, t) if isinstance(s, URIRef)}


def test_fk_order_puts_referenced_table_first():
    assert fk_order(SCHEMA) == ["language", "film"]


def test_direct_mapping_shape():
    g = direct_mapping(SCHEMA)
    assert named(g, OWL.Class) == {naming.class_iri("film"), naming.class_iri("language")}
    # 일반 컬럼 → 데이터 속성, 외래 키 → 객체 속성
    assert len(named(g, OWL.DatatypeProperty)) == 5
    op = naming.object_property_iri("film", "language_id", "language")
    assert named(g, OWL.ObjectProperty) == {op}
    assert g.value(op, RDFS.domain) == naming.class_iri("film")
    assert g.value(op, RDFS.range) == naming.class_iri("language")
    assert g.value(op, PROV.wasDerivedFrom) == naming.provenance_iri("film", "language_id")
    assert g.value(naming.data_property_iri("film", "title"), RDFS.range) == XSD.string
    assert g.value(naming.data_property_iri("film", "release_date"), RDFS.range) == XSD.date  # 이름으로 날짜 추정


def test_every_element_has_provenance():
    g = direct_mapping(SCHEMA)
    for s in named(g, OWL.Class) | named(g, OWL.DatatypeProperty) | named(g, OWL.ObjectProperty):
        assert naming.parse_provenance(g.value(s, PROV.wasDerivedFrom)) is not None


def test_view():
    v = graph_to_view(direct_mapping(SCHEMA))
    assert v["counts"]["classes"] == 2 and v["counts"]["object_properties"] == 1
    film = next(c for c in v["classes"] if c["name"] == "Film")
    assert film["source"] == {"table": "film", "column": None}
    rows = v["triples"][film["iri"]]
    assert {"film_title only xsd:string", "film_title some xsd:string"} <= {r["o"].replace("ont:", "") for r in rows if r["p"] == "rdfs:subClassOf"}


@pytest.mark.parametrize("db,tables,data_props,object_props", [("movie_3", 16, 67, 22), ("synthea", 11, 67, 18)])
def test_real_db_matches_paper_ontology(db, tables, data_props, object_props):
    """실제 DB의 Direct Mapping: 클래스 수 = 테이블 수, 모든 요소가 논문 온톨로지에도 같은 IRI로 있다."""
    from backend.db.connection import admin_connect
    from backend.db.schema import extract_schema
    from backend.paths import PAPER

    try:
        conn = admin_connect(db)
    except Exception as e:
        pytest.skip(f"DB 연결 불가: {e}")
    with conn:
        g = direct_mapping(extract_schema(conn, db), conn)
    assert (len(named(g, OWL.Class)), len(named(g, OWL.DatatypeProperty)), len(named(g, OWL.ObjectProperty))) == (tables, data_props, object_props)
    paper = Graph()
    paper.parse(PAPER / f"{db}.owl", format="xml")
    for t in (OWL.Class, OWL.DatatypeProperty, OWL.ObjectProperty):
        assert named(g, t) <= named(paper, t)
    for p in named(g, OWL.DatatypeProperty):
        assert g.value(p, RDFS.range) in set(paper.objects(p, RDFS.range))
