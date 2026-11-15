"""DB 파일 불러오기. 파일을 PostgreSQL의 새 데이터베이스로 올리고, 불러온 DB 목록을 관리한다.

지원 형식 (파일 내용으로 판별):
  - PostgreSQL 덤프 (pg_dump 사용자 지정 형식, 보통 .dump)  → pg_restore
  - PostgreSQL SQL 스크립트 (.sql)                          → psql
  - SQLite 파일 (.sqlite / .db)                             → 논문 실험의 sqlite_to_pg.py 로 이전
불러온 DB에는 데이터베이스 주석(COMMENT ON DATABASE)으로 표시를 남겨, 이 프로그램이 만든 것만 목록에 나온다.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from psycopg import sql

from backend.db.connection import DB_NAME_RE, admin_connect, admin_user, conn_params, maintenance_connect
from backend.paths import PAPER

TAG = "ontolens:"
RESERVED = {"postgres", "template0", "template1"}
FORMATS = {"pg_dump": "PostgreSQL 덤프", "sql": "SQL 스크립트", "sqlite": "SQLite"}


class ImportError_(Exception):
    """사용자에게 그대로 보여줄 수 있는 불러오기 오류."""


def name_from_filename(filename: str) -> str:
    """파일 이름 → DB 이름. 예: 'Movie 3.dump' → 'movie_3'"""
    stem = Path(filename).name
    for suffix in (".dump", ".sql", ".sqlite3", ".sqlite", ".db", ".backup", ".pgdump"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    name = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", stem.lower())).strip("_")[:49]
    if not name:
        name = "db"
    if not name[0].isalpha():
        name = ("db_" + name)[:49]
    return name


def detect_format(path: Path) -> str:
    with path.open("rb") as f:
        head = f.read(4096)
    if head.startswith(b"PGDMP"):
        return "pg_dump"
    if head.startswith(b"SQLite format 3\x00"):
        return "sqlite"
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    if re.search(r"\b(CREATE|INSERT|COPY|SET|BEGIN|SELECT|ALTER)\b", text, re.I):
        return "sql"
    raise ImportError_("지원하지 않는 파일입니다. PostgreSQL 덤프(.dump), SQL 스크립트(.sql), SQLite 파일(.sqlite)만 불러올 수 있습니다.")


def list_databases() -> list[dict]:
    """이 프로그램으로 불러온 DB 목록 (이름순)."""
    with maintenance_connect() as conn:
        rows = conn.execute(
            "SELECT d.datname, shobj_description(d.oid, 'pg_database') FROM pg_database d "
            "WHERE NOT d.datistemplate AND shobj_description(d.oid, 'pg_database') LIKE %s ORDER BY 1",
            (TAG + "%",),
        ).fetchall()
    out = []
    for name, comment in rows:
        try:
            meta = json.loads(comment[len(TAG):])
        except json.JSONDecodeError:
            meta = {}
        out.append({"name": name, **meta})
    return out


def is_imported(name: str) -> bool:
    return any(d["name"] == name for d in list_databases())


def _database_exists(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone() is not None


def _pg_env() -> dict[str, str]:
    user, password = admin_user()
    p = conn_params()
    return {**os.environ, "PGHOST": p["host"], "PGPORT": p["port"], "PGUSER": user, "PGPASSWORD": password}


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, env=_pg_env(), capture_output=True, text=True, timeout=1800)
    except FileNotFoundError as e:
        raise ImportError_(f"{cmd[0]} 프로그램을 찾을 수 없습니다 (PostgreSQL 클라이언트 설치 필요).") from e
    except subprocess.TimeoutExpired as e:
        raise ImportError_("복원이 30분을 넘어 중단했습니다.") from e


def _errors(stderr: str) -> list[str]:
    return [ln.strip() for ln in stderr.splitlines() if re.search(r"\b(error|ERROR|FATAL|오류)\b", ln)][:10]


def _restore_sqlite(path: Path, name: str) -> list[str]:
    script = PAPER / "sqlite_to_pg" / "sqlite_to_pg.py"
    spec = importlib.util.spec_from_file_location("sqlite_to_pg", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    user, password = admin_user()
    p = conn_params()
    from urllib.parse import quote

    args = argparse.Namespace(
        sqlite=path, dsn=f"postgresql://{quote(user)}:{quote(password)}@{p['host']}:{p['port']}/{name}", schema="public",
        lowercase_identifiers=False, replace=False, skip_invalid_fk=True, allow_skip=True, mixed_as_text=True,
    )
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            mod.convert(args)
    except mod.MigrationError as e:
        raise ImportError_(f"SQLite 파일을 옮기지 못했습니다: {e}") from e
    return [ln.strip() for ln in out.getvalue().splitlines() if ("경고" in ln or "건너" in ln) and not ln.strip().startswith("완료")][:10]


def import_file(path: Path, filename: str, replace: bool = False) -> dict:
    """파일을 새 데이터베이스로 올린다. 같은 이름이 있으면 replace=True 일 때만 바꾼다."""
    name = name_from_filename(filename)
    if name in RESERVED or name == admin_user()[0] or not DB_NAME_RE.fullmatch(name):
        raise ImportError_(f"'{name}'은(는) DB 이름으로 쓸 수 없습니다. 파일 이름을 바꿔 주세요.")
    fmt = detect_format(path)

    with maintenance_connect() as conn:
        if _database_exists(conn, name):
            if not is_imported(name):
                raise ImportError_(f"PostgreSQL에 '{name}' 데이터베이스가 이미 있는데, 이 프로그램으로 불러온 것이 아니라서 건드리지 않았습니다.")
            if not replace:
                raise FileExistsError(name)
            conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(sql.Identifier(name)))

    try:
        if fmt == "pg_dump":
            res = _run(["pg_restore", "-d", name, "--no-owner", "--no-privileges", str(path)])
            warnings = _errors(res.stderr)
        elif fmt == "sql":
            res = _run(["psql", "-d", name, "-q", "-v", "ON_ERROR_STOP=0", "-f", str(path)])
            warnings = _errors(res.stderr)
        else:
            warnings = _restore_sqlite(path, name)

        agent = os.environ["AGENT_DB_USER"]
        with admin_connect(name) as conn:
            tables = conn.execute(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relkind = 'r'"
            ).fetchone()[0]
            if tables == 0:
                detail = f" ({warnings[0]})" if warnings else ""
                raise ImportError_("파일을 읽었지만 public 스키마에 테이블이 하나도 만들어지지 않았습니다." + detail)
            # 에이전트 계정에는 읽기 권한만 준다
            conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(name)))
            conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            conn.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(name), sql.Identifier(agent)))
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(agent)))
            conn.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(agent)))
            conn.execute("ANALYZE")
            conn.commit()
        meta = {"source": Path(filename).name, "format": fmt, "imported_at": datetime.now().isoformat(timespec="seconds"), "tables": tables}
        with maintenance_connect() as conn:
            conn.execute(sql.SQL("COMMENT ON DATABASE {} IS {}").format(sql.Identifier(name), sql.Literal(TAG + json.dumps(meta, ensure_ascii=False))))
    except BaseException:
        with maintenance_connect() as conn:  # 실패하면 만들다 만 DB를 남기지 않는다
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        raise
    return {"name": name, **meta, "warnings": warnings}


def drop_database(name: str) -> None:
    """불러온 DB를 PostgreSQL에서 지운다 (원본 파일과 온톨로지 파일은 그대로 둔다)."""
    if not is_imported(name):
        raise KeyError(name)
    with maintenance_connect() as conn:
        conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
