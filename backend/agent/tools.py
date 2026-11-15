"""에이전트 도구 두 개의 실제 동작 (논문 실험 코드 db.py 와 같은 규칙).

- 온톨로지 검색: 지금 불러온 온톨로지 그래프에 SPARQL SELECT 실행. 구조만 읽는다 (데이터에는 질의하지 않음).
- SQL 실행: PostgreSQL에 읽기 전용 계정으로 SELECT 실행.
둘 다 LLM에게 줄 문자열과, 화면 시각화에 쓸 정보를 함께 돌려준다.
"""
from __future__ import annotations

import datetime as dt
import decimal
import time
from dataclasses import dataclass, field

import sqlglot
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, PROV, RDF, RDFS, XSD
from sqlglot import exp

from backend.db.connection import agent_connect
from backend.ontology import naming

MAX_ROWS = 50
SQL_TIMEOUT_SEC = 30
PREFIXES = {"ont": str(naming.ONT), "prov": str(PROV), "owl": str(OWL), "rdfs": str(RDFS), "rdf": str(RDF), "xsd": str(XSD)}
# RIGOR 출력에 섞일 수 있는 가짜 클래스(제약을 이름으로 오인한 것)는 검색 결과에서 뺀다
NOISE = ("_exactly_", "_max_", "_min_", "Unnamed")


@dataclass
class ToolResult:
    text: str                      # LLM에게 보여주는 내용
    ok: bool
    viz: dict = field(default_factory=dict)       # 캔버스 강조용
    table: dict | None = None      # 화면의 결과 표 {columns, rows, truncated}


# ---------------------------------------------------------------- 온톨로지 검색 (SPARQL)

def _short(term) -> str:
    """LLM에게 줄 때 주소를 짧게 줄인다 (토큰 절약): ont:Film → 'Film', 출처 → 'film/title'."""
    if isinstance(term, URIRef):
        s = str(term)
        if "/provenance/" in s:
            return s.split("/provenance/", 1)[1]
        return s[len(str(naming.ONT)):] if s.startswith(str(naming.ONT)) else s
    if isinstance(term, BNode):
        return "_:blank"
    return "" if term is None else str(term)


def _source_of(g: Graph, entity: URIRef) -> tuple[str, str | None] | None:
    for o in g.objects(entity, PROV.wasDerivedFrom):
        parsed = naming.parse_provenance(str(o))
        if parsed:
            return parsed
    return None


def run_ontology_sparql(graph: Graph, query: str) -> ToolResult:
    try:
        res = graph.query(query, initNs=PREFIXES)
        if res.type != "SELECT":
            return ToolResult("ERROR: SELECT 쿼리만 사용하세요.", ok=False)
        cols = [str(v) for v in res.vars]
        lines, iris, sources = [], [], []
        for row in res:
            cells = [_short(c) for c in row]
            if any(n in c for c in cells for n in NOISE):
                continue
            lines.append("\t".join(cells))
            for c in row:
                if not isinstance(c, URIRef):
                    continue
                prov = naming.parse_provenance(str(c))
                if prov:
                    sources.append(prov)
                elif str(c).startswith(str(naming.ONT)):
                    iris.append(c)
            if len(lines) >= MAX_ROWS:
                break
    except Exception as e:  # noqa: BLE001 - 문법 오류 등은 그대로 LLM에게 돌려준다
        return ToolResult(f"ERROR: {e}", ok=False)
    if not lines:
        return ToolResult("(no results)", ok=False)

    # 시각화: 결과에 나온 클래스·속성과, 그것들이 유래한 테이블·컬럼
    iris = list(dict.fromkeys(iris))
    for e in iris:
        src = _source_of(graph, e)
        if src:
            sources.append(src)
    sources = list(dict.fromkeys(sources))
    kinds = {OWL.Class: "classes", OWL.ObjectProperty: "object_properties", OWL.DatatypeProperty: "data_properties"}
    viz: dict = {"classes": [], "object_properties": [], "data_properties": [],
                 "tables": list(dict.fromkeys(t for t, _ in sources)),
                 "columns": [{"table": t, "column": c} for t, c in sources if c]}
    for e in iris:
        for rdf_type, key in kinds.items():
            if (e, RDF.type, rdf_type) in graph:
                viz[key].append(str(e))
    return ToolResult("\t".join(cols) + "\n" + "\n".join(lines), ok=True, viz=viz,
                      table={"columns": cols, "rows": [ln.split("\t") for ln in lines], "truncated": len(lines) >= MAX_ROWS})


# ---------------------------------------------------------------- SQL 실행

def _is_select(query: str) -> bool | None:
    """SELECT 한 문장이면 True, 아니면 False, 판단할 수 없으면 None."""
    try:
        statements = [s for s in sqlglot.parse(query, read="postgres") if s is not None]
    except Exception:  # noqa: BLE001
        return None
    if len(statements) != 1:
        return False
    return isinstance(statements[0], (exp.Select, exp.Union, exp.Intersect, exp.Except, exp.Subquery))


def _cell(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, decimal.Decimal):
        return float(v) if v == v.to_integral_value() or abs(v.as_tuple().exponent) <= 10 else str(v)
    if isinstance(v, (dt.date, dt.datetime, dt.time)):
        return v.isoformat()
    return str(v)


def run_sql(db: str, query: str) -> ToolResult:
    if _is_select(query) is False:
        return ToolResult("ERROR: SELECT 문 하나만 실행할 수 있습니다.", ok=False)
    try:
        with agent_connect(db) as conn:  # 읽기 전용 계정 (쓰기 권한 없음, default_transaction_read_only=on)
            conn.execute(f"SET statement_timeout = {SQL_TIMEOUT_SEC * 1000}")
            res = conn.execute(query)
            if res.description is None:
                return ToolResult("ERROR: 결과 행이 없는 문장입니다. SELECT 문만 사용하세요.", ok=False)
            cols = [d.name for d in res.description]
            rows = res.fetchmany(MAX_ROWS + 1)
    except Exception as e:  # noqa: BLE001 - 오류 메시지를 LLM이 읽고 고친다
        return ToolResult(f"ERROR: {e}", ok=False)
    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    text = "\t".join(cols) + "\n" + "\n".join("\t".join(map(str, r)) for r in rows)
    return ToolResult(text, ok=True, table={"columns": cols, "rows": [[_cell(v) for v in r] for r in rows], "truncated": truncated})


def sql_join_path(query: str, schema: dict) -> dict:
    """SQL의 FROM/JOIN 테이블과 조인 조건을 뽑아 ERD 위에 그릴 수 있게 한다.

    돌려주는 값: {tables: [...], joins: [{left_table, left_column, right_table, right_column, fk}], columns: [{table, column}]}
    fk 는 그 조인이 실제 외래 키와 일치할 때 {table, column} (외래 키를 가진 쪽).
    """
    out: dict = {"tables": [], "joins": [], "columns": []}
    try:
        tree = sqlglot.parse_one(query, read="postgres")
    except Exception:  # noqa: BLE001 - 파싱할 수 없으면 강조 없이 넘어간다
        return out
    real_tables = {t["name"].lower(): t for t in schema["tables"]}
    fks = {(f["from_table"], f["from_column"], f["to_table"], f["to_column"]) for f in schema["foreign_keys"]}

    def real_column(table: str, name: str) -> str | None:
        for c in real_tables[table.lower()]["columns"]:
            if c["name"].lower() == name.lower():
                return c["name"]
        return None

    seen_cols: set[tuple[str, str]] = set()
    for select in tree.find_all(exp.Select):
        # 이 SELECT 의 FROM/JOIN 에 직접 나온 테이블만 (별칭 → 실제 이름)
        alias: dict[str, str] = {}
        sources = [select.args.get("from") or select.args.get("from_")] + list(select.args.get("joins") or [])  # sqlglot 버전에 따라 키 이름이 다르다
        for src in sources:
            if src is None:
                continue
            t = src.this
            if isinstance(t, exp.Table) and t.name.lower() in real_tables:
                real = real_tables[t.name.lower()]["name"]
                alias[(t.alias or t.name).lower()] = real
                if real not in out["tables"]:
                    out["tables"].append(real)

        def resolve(col: exp.Column) -> tuple[str, str] | None:
            if col.table:
                table = alias.get(col.table.lower())
                candidates = [table] if table else []
            else:
                candidates = list(dict.fromkeys(alias.values()))
            hits = [(t, real_column(t, col.name)) for t in candidates]
            hits = [(t, c) for t, c in hits if c]
            return hits[0] if len(hits) == 1 else None

        for col in select.find_all(exp.Column):
            if col.find_ancestor(exp.Select) is not select:
                continue
            r = resolve(col)
            if r and r not in seen_cols:
                seen_cols.add(r)
                out["columns"].append({"table": r[0], "column": r[1]})

        # 조인 조건: ON 절과 WHERE 절의 "컬럼 = 컬럼"
        for eq in select.find_all(exp.EQ):
            if eq.find_ancestor(exp.Select) is not select:
                continue
            if not (isinstance(eq.left, exp.Column) and isinstance(eq.right, exp.Column)):
                continue
            a, b = resolve(eq.left), resolve(eq.right)
            if not a or not b or a[0] == b[0]:
                continue
            fk = None
            if (a[0], a[1], b[0], b[1]) in fks:
                fk = {"table": a[0], "column": a[1]}
            elif (b[0], b[1], a[0], a[1]) in fks:
                fk = {"table": b[0], "column": b[1]}
            join = {"left_table": a[0], "left_column": a[1], "right_table": b[0], "right_column": b[1], "fk": fk}
            if join not in out["joins"]:
                out["joins"].append(join)
    return out


def now() -> float:
    return time.monotonic()
