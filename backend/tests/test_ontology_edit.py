"""사람이 온톨로지를 수정하는 흐름: 수정 → 검사 → 되돌리기 → 저장(버전) → diff → 에이전트 반영 (실제 DB 필요)."""
import json

import pytest
from fastapi.testclient import TestClient
from rdflib import Literal, URIRef
from rdflib.namespace import RDFS

from backend.agent.tools import run_ontology_sparql
from backend.app.main import app
from backend.ontology import edit, store

ONT = "http://example.org/ontology#"
DB = "movie_3"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    monkeypatch.setattr(store, "_work", {})
    c = TestClient(app)
    try:
        c.get("/api/dbs").raise_for_status()
    except Exception as e:
        pytest.skip(f"DB 연결 불가: {e}")
    res = c.post(f"/api/dbs/{DB}/ontology/generate?mode=direct")
    done = [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")][-1]
    c.post(f"/api/dbs/{DB}/ontology/load", json={"filename": done["file"]["filename"]}).raise_for_status()
    c.origin = done["file"]["filename"]
    return c


def patch(client, *ops, status=200):
    res = client.patch(f"/api/dbs/{DB}/ontology", json={"ops": list(ops)})
    assert res.status_code == status, res.text
    return res.json()


def objprop(view, name):
    return next(p for p in view["object_properties"] if p["name"] == name)


def test_edit_is_used_by_agent_immediately(client):
    """수정한 설명이 저장 전에도 에이전트의 SPARQL 검색에 바로 나온다."""
    iri = ONT + "rental_hasCustomer"
    view = patch(client, {"op": "set_comment", "iri": iri, "value": "The customer who rented the item (edited)."})
    assert objprop(view, "rental_hasCustomer")["comments"] == ["The customer who rented the item (edited)."]
    assert view["history"] == {"can_undo": True, "can_redo": False, "changes": 1, "undo_label": "ont:rental_hasCustomer 설명 수정", "redo_label": None}
    result = run_ontology_sparql(store.current_graph(DB), f"SELECT ?c WHERE {{ <{iri}> rdfs:comment ?c }}")
    assert result.ok and "(edited)" in result.text
    # 불러온 파일 자체는 바뀌지 않는다
    assert (URIRef(iri), RDFS.comment, Literal("The customer who rented the item (edited).")) not in store.file_graph(DB, client.origin)


def test_undo_redo(client):
    iri = ONT + "Film"
    patch(client, {"op": "set_label", "iri": iri, "value": "Movie"})
    label = lambda: next(c for c in client.get(f"/api/dbs/{DB}/ontology").json()["classes"] if c["iri"] == iri)["label"]
    assert label() == "Movie"
    h = client.post(f"/api/dbs/{DB}/ontology/undo").json()["history"]
    assert h["can_redo"] and h["changes"] == 0  # 파일과 같은 상태로 돌아왔다
    assert label() == "Film"
    client.post(f"/api/dbs/{DB}/ontology/redo").raise_for_status()
    assert label() == "Movie"
    assert client.post(f"/api/dbs/{DB}/ontology/redo").status_code == 409


def test_rename_and_value_description(client):
    view = patch(client, {"op": "rename", "iri": ONT + "rental_hasCustomer", "name": "rentedBy"},
                 {"op": "set_value_description", "iri": ONT + "film_rating", "value": "G = general audiences, NC-17 = adults only"})
    p = objprop(view, "rentedBy")
    assert p["domains"] == [ONT + "Rental"] and p["ranges"] == [ONT + "Customer"] and p["source"] == {"table": "rental", "column": "customer_id"}
    assert not any(x["name"] == "rental_hasCustomer" for x in view["object_properties"])
    rating = next(x for x in view["data_properties"] if x["name"] == "film_rating")
    assert rating["value_description"].startswith("G = general") and not any("Value meanings" in c for c in rating["comments"])
    # 이미 있는 이름으로 바꾸면 거부
    patch(client, {"op": "rename", "iri": ONT + "rentedBy", "name": "rental_hasStaff"}, status=400)


def test_check_rejects_bad_edits(client):
    """도메인·범위 클래스, 출처 테이블·컬럼, 자료형, 상위 클래스 순환을 검사한다. 거부되면 작업본은 그대로."""
    bad = [
        {"op": "set_range", "iri": ONT + "rental_hasCustomer", "values": ["ont:NoSuchClass"]},
        {"op": "add_object_property", "name": "film_hasDirector", "domain": "ont:Film", "range": "ont:Actor", "source": {"table": "film", "column": "director_id"}},
        {"op": "set_range", "iri": ONT + "film_title", "values": ["ont:Film"]},
        {"op": "set_parents", "iri": ONT + "Film", "values": ["ont:Film"]},
    ]
    codes = []
    for op in bad:
        detail = patch(client, op, status=422)["detail"]
        codes.append(detail["issues"][0]["code"])
    assert codes == ["unknown_class", "unknown_source", "bad_datatype", "subclass_cycle"]
    assert client.get(f"/api/dbs/{DB}/ontology").json()["history"]["changes"] == 0
    # 올바른 관계 추가는 통과
    view = patch(client, {"op": "add_object_property", "name": "film_hasActor", "label": "has actor", "domain": "ont:Film", "range": "ont:Actor"})
    assert objprop(view, "film_hasActor")["ranges"] == [ONT + "Actor"]
    assert any(i["code"] == "missing_source" and i["iri"].endswith("film_hasActor") for i in view["issues"])


def test_triples_and_delete(client):
    s = ONT + "Language"
    view = patch(client, {"op": "add_triple", "s": s, "p": "rdfs:seeAlso", "o": "http://example.org/doc", "kind": "iri"},
                 {"op": "add_triple", "s": s, "p": "rdfs:comment", "o": "언어", "kind": "literal"})
    rows = view["triples"][s]
    assert {"p": "rdfs:seeAlso", "o": "http://example.org/doc"}.items() <= next(r for r in rows if r["p"] == "rdfs:seeAlso").items()
    patch(client, {"op": "remove_triple", "s": s, "p": "rdfs:comment", "o": "언어", "kind": "literal"})
    patch(client, {"op": "remove_triple", "s": s, "p": "rdfs:comment", "o": "언어", "kind": "literal"}, status=400)
    view = patch(client, {"op": "delete_property", "iri": ONT + "film_hasOriginalLanguage"})
    assert not any(p["name"] == "film_hasOriginalLanguage" for p in view["object_properties"])
    assert ONT + "film_hasOriginalLanguage" not in view["triples"]


def test_save_version_and_diff(client):
    patch(client, {"op": "set_label", "iri": ONT + "Film", "value": "Movie"})
    res = client.post(f"/api/dbs/{DB}/ontology/save", json={"note": "label test"})
    assert res.status_code == 200, res.text
    info = res.json()["file"]
    assert info["kind"] == "edit" and info["parent"] == client.origin and info["origin"] == client.origin and info["loaded"]
    assert res.json()["ontology"]["history"]["changes"] == 0
    assert [f["filename"] for f in client.get(f"/api/dbs/{DB}/ontology/versions").json()] == [info["filename"], client.origin]
    # 저장한 파일을 다시 읽어도 수정이 남아 있다
    store._work.clear()
    assert next(c for c in client.get(f"/api/dbs/{DB}/ontology").json()["classes"] if c["name"] == "Film")["label"] == "Movie"

    patch(client, {"op": "set_comment", "iri": ONT + "Film", "value": "A movie."})
    d = client.get(f"/api/dbs/{DB}/ontology/diff").json()
    assert d["against"] == client.origin and d["unsaved_changes"] == 1
    film = next(i for i in d["items"] if i["name"] == "ont:Film")
    assert ["rdfs:label", '"Movie"@en'] in film["added"] and ["rdfs:label", '"Film"@en'] in film["removed"]
    assert ["rdfs:comment", '"A movie."@en'] in film["added"]


def test_diff_unit():
    from rdflib import Graph

    a, b = Graph(), Graph()
    s = URIRef(ONT + "X")
    a.add((s, RDFS.label, Literal("x")))
    b.add((s, RDFS.label, Literal("y")))
    b.add((URIRef(ONT + "Y"), RDFS.label, Literal("y")))
    items = {i["name"]: i for i in edit.diff(a, b)}
    assert items["ont:X"]["status"] == "changed" and items["ont:Y"]["status"] == "added"
    assert items["ont:X"]["removed"] == [["rdfs:label", '"x"']]


def test_work_survives_restart(client):
    """저장하지 않은 수정과 되돌리기 기록은 백엔드를 다시 시작해도 남는다 (data/ontologies/<db>/_work/)."""
    iri = ONT + "Film"
    patch(client, {"op": "set_label", "iri": iri, "value": "Movie"})
    patch(client, {"op": "set_comment", "iri": iri, "value": "A movie."})
    client.post(f"/api/dbs/{DB}/ontology/undo").raise_for_status()
    assert len(list((store.ROOT / DB / "_work").glob("*.ttl"))) == 3  # 원본·수정 1·수정 2

    store._work.clear()  # 재시작 흉내
    view = client.get(f"/api/dbs/{DB}/ontology").json()
    assert next(c for c in view["classes"] if c["iri"] == iri)["label"] == "Movie"
    assert view["history"] == {"can_undo": True, "can_redo": True, "changes": 1, "undo_label": "ont:Film 라벨 수정", "redo_label": "ont:Film 설명 수정"}
    # 에이전트가 읽는 그래프도 기록에서 되살린 작업본
    assert run_ontology_sparql(store.current_graph(DB), f'SELECT ?l WHERE {{ <{iri}> rdfs:label ?l }}').text.count("Movie") == 1

    store._work.clear()
    client.post(f"/api/dbs/{DB}/ontology/undo").raise_for_status()
    assert client.get(f"/api/dbs/{DB}/ontology").json()["history"]["changes"] == 0

    # 다른 파일을 불러오면 기록은 지워진다
    client.post(f"/api/dbs/{DB}/ontology/load", json={"filename": client.origin}).raise_for_status()
    assert not (store.ROOT / DB / "_work").exists()
