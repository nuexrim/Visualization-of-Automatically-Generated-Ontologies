"""온톨로지 생성 → 목록 → 불러오기 흐름 (실제 DB 필요). 파일은 임시 폴더에 쓴다."""
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.ontology import store
from backend.paths import PAPER


def generate(client, db, mode="direct"):
    """SSE 응답을 이벤트 목록으로 읽는다."""
    import json

    res = client.post(f"/api/dbs/{db}/ontology/generate?mode={mode}")
    assert res.status_code == 200, res.text
    return [json.loads(line[6:]) for line in res.text.splitlines() if line.startswith("data: ")]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    c = TestClient(app)
    try:
        c.get("/api/dbs").raise_for_status()
    except Exception as e:
        pytest.skip(f"DB 연결 불가: {e}")
    return c


def test_no_ontology_until_loaded(client):
    assert client.get("/api/dbs/movie_3/ontology").status_code == 404
    events = generate(client, "movie_3")
    assert events[0]["type"] == "start" and events[0]["order"][0] != "payment"  # 참조되는 테이블이 먼저
    assert [e["type"] for e in events].count("table_done") == 16 and events[-1]["type"] == "done"
    info = events[-1]["file"]
    assert info["kind"] == "direct-mapping" and info["counts"]["classes"] == 16 and not info["loaded"]
    # 생성만으로는 불러온 상태가 되지 않는다
    assert client.get("/api/dbs/movie_3/ontology").status_code == 404

    files = client.get("/api/dbs/movie_3/ontology/files").json()
    assert [f["filename"] for f in files] == [info["filename"]]

    view = client.post("/api/dbs/movie_3/ontology/load", json={"filename": info["filename"]}).json()
    assert view["filename"] == info["filename"] and len(view["classes"]) == 16
    assert client.get("/api/dbs/movie_3/ontology?turtle=true").json()["turtle"].startswith("@prefix")
    # 다른 DB에는 영향이 없다
    assert client.get("/api/dbs/synthea/ontology").status_code == 404


def test_upload_paper_owl_and_reject_garbage(client):
    owl = (PAPER / "synthea.owl").read_bytes()
    info = client.post("/api/dbs/synthea/ontology/upload", files={"file": ("synthea.owl", owl)}).json()
    assert info["kind"] == "upload" and info["counts"] == {"classes": 11, "data_properties": 67, "object_properties": 18, "triples": 1435}
    assert client.post("/api/dbs/synthea/ontology/upload", files={"file": ("x.owl", b"not rdf")}).status_code == 400


def test_load_rejects_unknown_or_unsafe_names(client):
    for name in ("nope.ttl", "../movie_3/x.ttl", "/etc/passwd"):
        assert client.post("/api/dbs/movie_3/ontology/load", json={"filename": name}).status_code == 404


def test_rigor_mode_needs_key_and_model(client, monkeypatch):
    monkeypatch.delenv("ONTOLOGY_GEN_MODEL", raising=False)
    assert client.post("/api/dbs/movie_3/ontology/generate?mode=rigor").status_code == 400
    assert client.post("/api/dbs/movie_3/ontology/generate?mode=nope").status_code == 400


def test_chat_requires_loaded_ontology_and_question(client, monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert client.post("/api/dbs/movie_3/chat", json={"question": "  "}).status_code == 400
    res = client.post("/api/dbs/movie_3/chat", json={"question": "How many films?"})
    assert res.status_code == 400 and "온톨로지" in res.json()["detail"]
    assert client.get("/api/agent/prompt").json()["tools"] == ["ontology_query", "sql_query"]
