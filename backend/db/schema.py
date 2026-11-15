"""PostgreSQL에서 스키마(테이블, 컬럼, 타입, PK, FK)를 추출하고 컬럼 설명을 붙인다."""
from __future__ import annotations

import psycopg

from backend.db.descriptions import describe
from backend.db.graph_stats import compute_stats

COLUMNS_SQL = """
SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull
FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY c.relname, a.attnum
"""

PK_SQL = """
SELECT c.relname, a.attname
FROM pg_constraint k
JOIN pg_class c ON c.oid = k.conrelid
JOIN pg_namespace n ON n.oid = k.connamespace
JOIN unnest(k.conkey) WITH ORDINALITY AS u(attnum, ord) ON true
JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = u.attnum
WHERE k.contype = 'p' AND n.nspname = 'public'
ORDER BY c.relname, u.ord
"""

# 컬럼 하나짜리 UNIQUE 제약
UNIQUE_SQL = """
SELECT c.relname, a.attname
FROM pg_constraint k
JOIN pg_class c ON c.oid = k.conrelid
JOIN pg_namespace n ON n.oid = k.connamespace
JOIN pg_attribute a ON a.attrelid = k.conrelid AND a.attnum = k.conkey[1]
WHERE k.contype = 'u' AND n.nspname = 'public' AND cardinality(k.conkey) = 1
"""

# FK 제약의 컬럼 쌍마다 한 행 (복합 FK면 ncols > 1)
FK_SQL = """
SELECT k.conname, src.relname, sa.attname, dst.relname, da.attname, cardinality(k.conkey)
FROM pg_constraint k
JOIN pg_class src ON src.oid = k.conrelid
JOIN pg_class dst ON dst.oid = k.confrelid
JOIN pg_namespace n ON n.oid = k.connamespace
JOIN unnest(k.conkey, k.confkey) WITH ORDINALITY AS u(src_att, dst_att, ord) ON true
JOIN pg_attribute sa ON sa.attrelid = k.conrelid AND sa.attnum = u.src_att
JOIN pg_attribute da ON da.attrelid = k.confrelid AND da.attnum = u.dst_att
WHERE k.contype = 'f' AND n.nspname = 'public'
ORDER BY src.relname, k.conname, u.ord
"""

ROWS_SQL = """
SELECT c.relname, c.reltuples::bigint
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r'
"""


def extract_schema(conn: psycopg.Connection, db: str) -> dict:
    pks: dict[str, list[str]] = {}
    for table, col in conn.execute(PK_SQL):
        pks.setdefault(table, []).append(col)

    fks = [
        {"name": name, "from_table": st, "from_column": sc, "to_table": dt, "to_column": dc, "composite": n > 1}
        for name, st, sc, dt, dc, n in conn.execute(FK_SQL)
    ]
    fk_by_col = {(f["from_table"], f["from_column"]): f for f in fks}
    rows = dict(conn.execute(ROWS_SQL).fetchall())
    unique = set(conn.execute(UNIQUE_SQL).fetchall())

    tables: dict[str, dict] = {}
    for table, col, typ, nullable in conn.execute(COLUMNS_SQL):
        t = tables.setdefault(
            table, {"name": table, "row_count": max(rows.get(table, 0), 0), "primary_key": pks.get(table, []), "columns": []}
        )
        fk = fk_by_col.get((table, col))
        t["columns"].append({
            "name": col,
            "type": typ,
            "nullable": nullable,
            "pk": col in pks.get(table, []),
            "unique": (table, col) in unique,
            "fk": {"table": fk["to_table"], "column": fk["to_column"]} if fk else None,
            **describe(db, table, col),
        })

    stats = compute_stats(
        list(tables), [(f["from_table"], f["to_table"], 2 if f["composite"] else 1) for f in fks]
    )
    return {"db": db, "tables": list(tables.values()), "foreign_keys": fks, "stats": stats.as_dict()}
