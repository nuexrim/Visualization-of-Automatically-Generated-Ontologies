"""생성 파이프라인: Manchester 파서의 결함 방지, 판정 실패 시 Direct Mapping 유지."""
from rdflib import URIRef
from rdflib.namespace import OWL, PROV, RDF, RDFS, XSD

from backend.ontology import naming, rigor
from backend.ontology.direct_mapping import column_xsd_types
from backend.ontology.manchester import parse_manchester, split_top_level
from backend.tests.test_direct_mapping import SCHEMA

ONT = naming.ONT
APPROVED = "Decision: APPROVED\nCritical issues (must fix before merging): none\nImportant issues (should fix before merging): none\nMinor issues (can fix in a later pass): none\nCorrected fragment: N/A"
REJECTED = "Decision: REJECTED\nCritical issues (must fix before merging):\n- broken\nImportant issues (should fix before merging): none\nMinor issues (can fix in a later pass): none\nCorrected fragment: N/A"

GOOD_FILM = '''```
Class: Film
  Annotations:
    rdfs:label "Motion picture"@en,
    rdfs:comment "A film available for rental, with a title, a \\"release\\" date. Class: not a header"@en
  SubClassOf:
    CreativeWork,
    film_title exactly 1 xsd:string

Class: CreativeWork
  Annotations: rdfs:label "Creative work"@en, rdfs:comment "Any creative work."@en

ObjectProperty: language_isLanguageOfFilm
  Annotations: rdfs:label "is language of film"@en, rdfs:comment "Inverse of film_hasLanguage."@en
  Domain: Language
  Range: Film
  InverseOf: film_hasLanguage
```'''


def test_split_top_level_respects_quotes_and_iris():
    assert split_top_level('rdfs:label "a, b"@en, prov:wasDerivedFrom <http://x/y,z>, p some (A or B)') == [
        'rdfs:label "a, b"@en', "prov:wasDerivedFrom <http://x/y,z>", "p some (A or B)"]


def test_parser_reads_cardinality_as_restriction_not_class():
    r = parse_manchester(GOOD_FILM)
    classes = {s for s in r.graph.subjects(RDF.type, OWL.Class)}
    assert classes == {ONT.Film, ONT.CreativeWork}  # 'film_title_exactly_1_...' 같은 가짜 클래스가 없다
    assert all("exactly" not in str(c) for c in r.graph.all_nodes())
    restriction = next(o for o in r.graph.objects(ONT.Film, RDFS.subClassOf) if not isinstance(o, URIRef))
    assert r.graph.value(restriction, OWL.onProperty) == ONT.film_title
    assert int(r.graph.value(restriction, OWL.qualifiedCardinality)) == 1
    assert r.graph.value(restriction, OWL.onDataRange) == XSD.string
    assert (ONT.Film, RDFS.subClassOf, ONT.CreativeWork) in r.graph


def test_parser_handles_inverse_of_and_quoted_text():
    r = parse_manchester(GOOD_FILM)
    assert (ONT.language_isLanguageOfFilm, OWL.inverseOf, ONT.film_hasLanguage) in r.graph
    comment = str(r.graph.value(ONT.Film, RDFS.comment))
    assert '"release"' in comment and comment.endswith("Class: not a header")


def test_unparsable_expression_is_dropped_with_warning():
    r = parse_manchester("Class: Film\n  SubClassOf: film_title some (xsd:string or xsd:integer), not a class at all")
    assert list(r.graph.objects(ONT.Film, RDFS.subClassOf)) == []
    assert len(r.warnings) == 2


def test_empty_fragment_fails_inspection():
    core = rigor.bind_namespaces(rigor.Graph())
    for text in ("", "Sorry, I cannot help.", "Prefix: : <http://x#>"):
        assert not rigor.inspect_delta(parse_manchester(text), core, "film").ok


def test_undeclared_class_fails_inspection():
    core = rigor.bind_namespaces(rigor.Graph())
    core.add((ONT.Film, RDF.type, OWL.Class))
    report = rigor.inspect_delta(parse_manchester("Class: Film\n  SubClassOf: Ghost"), core, "film")
    assert any("Ghost" in e for e in report.errors)


def scripted(responses):
    """미리 정한 응답을 차례로 돌려주는 가짜 LLM."""
    it = iter(responses)

    def call(prompt):
        yield {"type": "llm_progress", "chars": 1}
        return next(it)

    return call


def run(llm):
    result = {}
    events = list(rigor.generate("movie_3", SCHEMA, column_xsd_types(SCHEMA), llm, result))
    return events, result


def test_direct_only_mode():
    events, result = run(None)
    assert [e["table"] for e in events if e["type"] == "table_done"] == ["language", "film"]
    assert result["outcomes"] == {"language": "direct_only", "film": "direct_only"}
    assert not any(e.get("step") == "generate" for e in events)


LANGUAGE_DELTA = 'Class: Language\n  Annotations: rdfs:label "Language"@en, rdfs:comment "A spoken language of a film."@en'


def test_approved_delta_is_merged_and_new_elements_get_provenance():
    events, result = run(scripted([LANGUAGE_DELTA, APPROVED, GOOD_FILM, APPROVED]))
    g = result["graph"]
    assert result["outcomes"] == {"language": "enriched", "film": "enriched"}
    assert str(g.value(ONT.Film, RDFS.label)) == "Motion picture"  # 라벨은 하나만 남는다
    assert len(list(g.objects(ONT.Film, RDFS.label))) == 1
    assert len(list(g.objects(ONT.Film, RDFS.comment))) == 2       # 설명은 Direct Mapping 것 + 보강된 것
    # LLM이 추가한 상위 클래스·역관계에도 출처가 붙는다
    for new in (ONT.CreativeWork, ONT.language_isLanguageOfFilm):
        assert g.value(new, PROV.wasDerivedFrom) == naming.provenance_iri("film")
    # 포괄성 유지
    assert (naming.data_property_iri("film", "title"), RDF.type, OWL.DatatypeProperty) in g
    done = [e for e in events if e["type"] == "table_done"]
    assert done[-1]["view"]["counts"]["classes"] == 3


def test_rejected_three_times_keeps_direct_mapping_only():
    events, result = run(scripted([LANGUAGE_DELTA, REJECTED] * 3 + [GOOD_FILM, APPROVED]))
    assert result["outcomes"] == {"language": "direct_only", "film": "enriched"}
    assert str(result["graph"].value(ONT.Language, RDFS.label)) == "Language"
    assert len([e for e in events if e.get("step") == "judge" and e["status"] == "failed" and e["table"] == "language"]) == 3


def test_structural_error_triggers_retry_then_fallback():
    # 데이터 속성에 두 번째 범위를 주면 "범위는 정확히 1개" 검사에 걸린다
    bad = 'DataProperty: language_name\n  Annotations: rdfs:label "name"@en\n  Range: xsd:integer'
    events, result = run(scripted([bad, APPROVED] * 3 + [GOOD_FILM, APPROVED]))
    assert result["outcomes"]["language"] == "direct_only"
    failed = [e for e in events if e.get("step") == "validate" and e["status"] == "failed"]
    assert len(failed) == 3 and "ranges" in failed[0]["errors"][0]
    assert list(result["graph"].objects(naming.data_property_iri("language", "name"), RDFS.range)) == [XSD.string]


def test_empty_llm_output_never_passes():
    events, result = run(scripted(["", "", "", GOOD_FILM, APPROVED]))
    assert result["outcomes"]["language"] == "direct_only"
