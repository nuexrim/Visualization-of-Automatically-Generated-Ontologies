"""DB 파일 불러오기: 이름 규칙, 형식 판별, SQLite·SQL 불러오기, 덮어쓰기 규칙."""
import sqlite3

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.db import importer
from backend.db.connection import agent_connect
from backend.paths import DATA


def test_name_from_filename():
    assert importer.name_from_filename("movie_3.dump") == "movie_3"
    assert importer.name_from_filename("My Shop-DB (v2).sqlite") == "my_shop_db_v2"
    assert importer.name_from_filename("2024 sales.sql") == "db_2024_sales"
    assert importer.name_from_filename("학사.db") == "db"


def test_detect_format(tmp_path):
    assert importer.detect_format(DATA / "dumps" / "movie_3.dump") == "pg_dump"
    sql_file = tmp_path / "a.sql"
    sql_file.write_text("CREATE TABLE t (id int primary key);")
    assert importer.detect_format(sql_file) == "sql"
    junk = tmp_path / "junk.bin"
    junk.write_bytes(bytes(range(256)) * 4)
    with pytest.raises(importer.ImportError_):
        importer.detect_format(junk)


@pytest.fixture()
def client():
    c = TestClient(app)
    try:
        c.get("/api/dbs").raise_for_status()
    except Exception as e:
        pytest.skip(f"DB 연결 불가: {e}")
    yield c
    for name in ("ontolens_test_shop", "ontolens_test_sql"):
        if importer.is_imported(name):
            importer.drop_database(name)


def make_sqlite(path):
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE customer (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customer(id), total REAL);
        INSERT INTO customer VALUES (1, 'Kim'), (2, 'Lee');
        INSERT INTO orders VALUES (10, 1, 9.5), (11, 2, 20.0), (12, 1, 3.25);
        """
    )
    con.commit()
    con.close()


def test_import_sqlite_file_builds_erd(client, tmp_path):
    path = tmp_path / "ontolens_test_shop.sqlite"
    make_sqlite(path)
    res = client.post("/api/dbs/import", files={"file": (path.name, path.read_bytes())})
    assert res.status_code == 200, res.text
    info = res.json()
    assert info["name"] == "ontolens_test_shop" and info["format"] == "sqlite"
    assert info["stats"] == {"V": 2, "E": 1, "C": 1, "mu": 0}
    assert "ontolens_test_shop" in [d["name"] for d in client.get("/api/dbs").json()]

    schema = client.get("/api/dbs/ontolens_test_shop/schema").json()
    assert {t["name"]: t["row_count"] for t in schema["tables"]} == {"customer": 2, "orders": 3}
    assert [(f["from_table"], f["from_column"], f["to_table"]) for f in schema["foreign_keys"]] == [("orders", "customer_id", "customer")]

    # 에이전트 계정은 읽기만 된다
    with agent_connect("ontolens_test_shop") as conn:
        assert conn.execute("SELECT count(*) FROM orders").fetchone()[0] == 3
        with pytest.raises(Exception):
            conn.execute("DELETE FROM orders")

    # 같은 이름을 다시 올리면 물어보고(409), replace 를 주면 바뀐다
    again = {"file": (path.name, path.read_bytes())}
    assert client.post("/api/dbs/import", files=again).status_code == 409
    assert client.post("/api/dbs/import", files=again, data={"replace": "true"}).status_code == 200

    assert client.delete("/api/dbs/ontolens_test_shop").json() == {"ok": True}
    assert client.get("/api/dbs/ontolens_test_shop/schema").status_code == 404


def test_import_sql_script(client):
    script = b"CREATE TABLE a (id int PRIMARY KEY);\nCREATE TABLE b (id int PRIMARY KEY, a_id int REFERENCES a(id));\nINSERT INTO a VALUES (1);"
    info = client.post("/api/dbs/import", files={"file": ("ontolens_test_sql.sql", script)}).json()
    assert info["format"] == "sql" and info["stats"]["V"] == 2 and info["stats"]["E"] == 1


def test_rejects_garbage_and_empty_dump(client):
    assert client.post("/api/dbs/import", files={"file": ("x.dump", bytes(range(256)) * 8)}).status_code == 400
    res = client.post("/api/dbs/import", files={"file": ("ontolens_test_sql.sql", b"SELECT 1;")})
    assert res.status_code == 400 and "테이블" in res.json()["detail"]
    assert not importer.is_imported("ontolens_test_sql")  # 실패하면 만들다 만 DB를 남기지 않는다


def test_unknown_db_is_404(client):
    assert client.get("/api/dbs/never_imported/schema").status_code == 404
    assert client.get("/api/dbs/postgres/schema").status_code == 404
    assert client.delete("/api/dbs/postgres").status_code == 404
