#!/usr/bin/env bash
# PostgreSQL 초기 설정: 에이전트용 읽기 전용 계정만 만든다.
# DB는 미리 복원하지 않는다. 화면의 "DB 불러오기"로 파일을 올리면 그때 데이터베이스가 만들어진다.
# docker(postgres 이미지의 /docker-entrypoint-initdb.d)와 로컬 실행 양쪽에서 쓴다.
# 필요 환경 변수: POSTGRES_USER, AGENT_DB_USER, AGENT_DB_PASSWORD
set -euo pipefail

ADMIN="${POSTGRES_USER:?POSTGRES_USER 필요}"
AGENT="${AGENT_DB_USER:?AGENT_DB_USER 필요}"
AGENT_PW="${AGENT_DB_PASSWORD:?AGENT_DB_PASSWORD 필요}"

# 읽기 전용 역할 (이미 있으면 비밀번호만 갱신). 각 DB의 SELECT 권한은 불러올 때 준다.
psql -v ON_ERROR_STOP=1 -U "$ADMIN" -d postgres -v agent="$AGENT" -v pw="$AGENT_PW" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', :'agent')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'agent') \gexec
SELECT format('ALTER ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE', :'agent', :'pw') \gexec
SELECT format('ALTER ROLE %I SET default_transaction_read_only = on', :'agent') \gexec
SELECT format('ALTER ROLE %I SET statement_timeout = %L', :'agent', '30s') \gexec
SQL
echo ">> 완료"
