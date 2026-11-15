"""PostgreSQL 연결. 접속 정보는 환경 변수(.env)에서만 읽는다."""
from __future__ import annotations

import os
import re
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

#: 불러온 DB에 붙이는 이름 규칙 (소문자·숫자·밑줄)
DB_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,48}$")


def conn_params() -> dict[str, str]:
    return {"host": os.environ.get("PGHOST", "localhost"), "port": os.environ.get("PGPORT", "5433")}


def _conninfo(db: str, user: str, password: str) -> str:
    return psycopg.conninfo.make_conninfo(**conn_params(), dbname=db, user=user, password=password)


def _checked(db: str) -> str:
    if not DB_NAME_RE.fullmatch(db):
        raise ValueError(f"올바르지 않은 DB 이름: {db}")
    return db


def admin_user() -> tuple[str, str]:
    return os.environ["POSTGRES_USER"], os.environ["POSTGRES_PASSWORD"]


def admin_connect(db: str) -> psycopg.Connection:
    """스키마 추출·검증용 (관리자 계정)."""
    return psycopg.connect(_conninfo(_checked(db), *admin_user()))


def maintenance_connect() -> psycopg.Connection:
    """DB 만들기·지우기·목록 조회용. 트랜잭션 없이 실행한다."""
    return psycopg.connect(_conninfo("postgres", *admin_user()), autocommit=True)


def agent_connect(db: str) -> psycopg.Connection:
    """에이전트의 SQL 실행용 (읽기 전용 계정)."""
    return psycopg.connect(
        _conninfo(_checked(db), os.environ["AGENT_DB_USER"], os.environ["AGENT_DB_PASSWORD"])
    )
