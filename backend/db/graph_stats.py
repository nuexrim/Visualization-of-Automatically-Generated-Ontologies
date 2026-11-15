"""스키마 그래프 통계 (논문 2.1.1의 정의).

V: 테이블 수
E: 외래 키로 이어진 서로 다른 테이블 쌍의 수
   (같은 두 테이블 사이 여러 FK는 1쌍, 자기참조 제외, 복합 FK 제외)
C: 연결 묶음(연결 요소) 수
μ: 순환 수 = E − V + C
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import psycopg

TABLES_SQL = """
SELECT c.relname
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
ORDER BY 1
"""

# FK 제약 하나당 한 행: (제약 이름, 참조하는 테이블, 참조되는 테이블, 컬럼 수)
FKS_SQL = """
SELECT con.conname, src.relname, dst.relname, cardinality(con.conkey)
FROM pg_constraint con
JOIN pg_class src ON src.oid = con.conrelid
JOIN pg_class dst ON dst.oid = con.confrelid
JOIN pg_namespace n ON n.oid = con.connamespace
WHERE con.contype = 'f' AND n.nspname = 'public'
ORDER BY 1
"""


@dataclass(frozen=True)
class GraphStats:
    V: int
    E: int
    C: int
    mu: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def compute_stats(tables: list[str], fks: list[tuple[str, str, int]]) -> GraphStats:
    """tables: 테이블 이름, fks: (참조하는 테이블, 참조되는 테이블, FK 컬럼 수)."""
    edges = {
        frozenset((src, dst))
        for src, dst, ncols in fks
        if src != dst and ncols == 1
    }
    parent = {t: t for t in tables}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        a, b = tuple(e)
        parent[find(a)] = find(b)

    v, e, c = len(tables), len(edges), len({find(t) for t in tables})
    return GraphStats(V=v, E=e, C=c, mu=e - v + c)


def stats_from_db(conn: psycopg.Connection) -> GraphStats:
    tables = [r[0] for r in conn.execute(TABLES_SQL)]
    fks = [(src, dst, n) for _, src, dst, n in conn.execute(FKS_SQL)]
    return compute_stats(tables, fks)
