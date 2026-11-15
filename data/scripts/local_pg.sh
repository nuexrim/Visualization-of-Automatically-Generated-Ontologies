#!/usr/bin/env bash
# Docker 없이 로컬(Homebrew) PostgreSQL로 개발용 DB를 띄운다.
#   data/scripts/local_pg.sh start   # 클러스터 생성(최초 1회) + 기동 + dump 복원(최초 1회)
#   data/scripts/local_pg.sh stop
#   data/scripts/local_pg.sh reset   # 불러온 DB를 모두 지우고 처음 상태로
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
set -a; source "$ROOT/.env"; set +a
PGDATA_DIR="$ROOT/.local/pgdata"
export PGHOST="${PGHOST:-localhost}" PGPORT="${PGPORT:-5433}"

start() {
  local fresh=0
  if [ ! -d "$PGDATA_DIR" ]; then
    mkdir -p "$ROOT/.local"
    local pwfile; pwfile="$(mktemp)"; printf '%s' "$POSTGRES_PASSWORD" > "$pwfile"
    initdb -D "$PGDATA_DIR" -U "$POSTGRES_USER" --pwfile="$pwfile" --auth=scram-sha-256 -E UTF8 --locale=C >/dev/null
    rm -f "$pwfile"; fresh=1
  fi
  pg_ctl -D "$PGDATA_DIR" status >/dev/null 2>&1 || \
    pg_ctl -D "$PGDATA_DIR" -l "$ROOT/.local/pg.log" -o "-p $PGPORT -c listen_addresses=localhost" -w start
  if [ "$fresh" = 1 ]; then
    PGPASSWORD="$POSTGRES_PASSWORD" bash "$ROOT/data/scripts/init_db.sh"
  fi
}
stop() { pg_ctl -D "$PGDATA_DIR" -m fast stop || true; }

case "${1:-start}" in
  start) start ;;
  stop) stop ;;
  reset) stop; rm -rf "$PGDATA_DIR"; start ;;
  *) echo "usage: $0 start|stop|reset"; exit 1 ;;
esac
