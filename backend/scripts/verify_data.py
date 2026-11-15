"""검증: data/dumps 의 두 DB를 불러온 상태에서, 불러온 DB의 그래프 통계가 논문 표 1과 일치하는지, 에이전트 계정이 읽기 전용인지 확인."""
from __future__ import annotations

import sys

import psycopg

from backend.db.connection import admin_connect, agent_connect
from backend.db.importer import list_databases
from backend.db.graph_stats import FKS_SQL, TABLES_SQL, GraphStats, stats_from_db

EXPECTED = {
    "movie_3": GraphStats(V=16, E=20, C=2, mu=6),
    "synthea": GraphStats(V=11, E=18, C=1, mu=8),
}


def main() -> int:
    ok = True
    names = [d["name"] for d in list_databases() if d["name"] in EXPECTED]
    if not names:
        print("movie_3 / synthea 가 불러와져 있지 않습니다. 화면에서 data/dumps 의 파일을 불러온 뒤 다시 실행하세요.")
        return 1
    for db in names:
        with admin_connect(db) as conn:
            got = stats_from_db(conn)
            tables = [r[0] for r in conn.execute(TABLES_SQL)]
            fks = conn.execute(FKS_SQL).fetchall()
            rows = {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
            no_pk = conn.execute(
                """SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                   WHERE n.nspname='public' AND c.relkind='r' AND NOT EXISTS
                   (SELECT 1 FROM pg_constraint k WHERE k.conrelid=c.oid AND k.contype='p') ORDER BY 1"""
            ).fetchall()
        match = got == EXPECTED[db]
        ok &= match
        print(f"[{db}] {'일치' if match else '불일치'}  계산={got.as_dict()}  기대={EXPECTED[db].as_dict()}")
        print(f"   FK 제약 {len(fks)}개 (자기참조 {sum(s == d for _, s, d, _ in fks)}, 복합 {sum(n > 1 for *_, n in fks)})")
        print(f"   PK 없는 테이블: {[r[0] for r in no_pk] or '없음'}")
        print(f"   행 수: {rows}")

        # 읽기 전용 확인: 쓰기는 반드시 실패해야 한다.
        with agent_connect(db) as conn:
            t = tables[0]
            conn.execute(f'SELECT 1 FROM "{t}" LIMIT 1')
            for stmt in (f'DELETE FROM "{t}"', "CREATE TABLE _x(i int)", "SET default_transaction_read_only = off; CREATE TABLE _x(i int)"):
                try:
                    conn.execute(stmt)
                    print(f"   !! 에이전트 계정으로 쓰기 성공: {stmt}")
                    ok = False
                except psycopg.Error as e:
                    print(f"   쓰기 차단 확인: {stmt[:40]!r} → {type(e).__name__}")
                conn.rollback()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
