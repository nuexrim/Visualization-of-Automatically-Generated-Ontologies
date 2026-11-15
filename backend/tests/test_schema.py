"""실제 DB가 떠 있어야 하는 테스트 (docker compose up db)."""
import pytest

from backend.db.connection import admin_connect
from backend.db.schema import extract_schema

EXPECTED = {
    "movie_3": {"tables": 16, "fks": 22, "stats": {"V": 16, "E": 20, "C": 2, "mu": 6}},
    "synthea": {"tables": 11, "fks": 18, "stats": {"V": 11, "E": 18, "C": 1, "mu": 8}},
}


@pytest.fixture(scope="module", params=list(EXPECTED))
def schema(request):
    try:
        conn = admin_connect(request.param)
    except Exception as e:  # DB가 없으면 건너뛴다
        pytest.skip(f"DB 연결 불가: {e}")
    with conn:
        return extract_schema(conn, request.param)


def test_counts_and_stats(schema):
    exp = EXPECTED[schema["db"]]
    assert len(schema["tables"]) == exp["tables"]
    assert len(schema["foreign_keys"]) == exp["fks"]
    assert schema["stats"] == exp["stats"]


def test_fk_columns_exist_and_are_flagged(schema):
    cols = {(t["name"], c["name"]): c for t in schema["tables"] for c in t["columns"]}
    for fk in schema["foreign_keys"]:
        assert (fk["to_table"], fk["to_column"]) in cols
        assert cols[(fk["from_table"], fk["from_column"])]["fk"] == {"table": fk["to_table"], "column": fk["to_column"]}


def test_every_column_is_listed_in_description_csv(schema):
    from backend.db.descriptions import load_descriptions

    desc = load_descriptions(schema["db"])
    missing = [
        (t["name"], c["name"])
        for t in schema["tables"] for c in t["columns"]
        if c["name"].lower() not in desc.get(t["name"].lower(), {})
    ]
    assert missing == []
    # BIRD 원본 CSV에 설명이 비어 있는 컬럼은 소수다 (movie_3에 5개).
    empty = [1 for t in schema["tables"] for c in t["columns"] if not c["description"]]
    assert len(empty) <= 5
