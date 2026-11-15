"""에이전트: SPARQL 검색, SQL 실행 차단 조건, 읽기 전용 SQL, 조인 경로, 이벤트 순서."""
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from backend.agent import prompts, runner, tools
from backend.db.connection import admin_connect
from backend.db.schema import extract_schema
from backend.ontology.direct_mapping import direct_mapping
from backend.paths import PAPER

ONT = "http://example.org/ontology#"


@pytest.fixture(scope="module")
def movie():
    try:
        conn = admin_connect("movie_3")
    except Exception as e:
        pytest.skip(f"DB 연결 불가: {e}")
    with conn:
        schema = extract_schema(conn, "movie_3")
        return schema, direct_mapping(schema, conn)


def test_system_prompt_is_the_paper_prompt():
    import importlib.util

    spec = importlib.util.spec_from_file_location("paper_agent_src", PAPER / "agent" / "agent.py")
    src = (PAPER / "agent" / "agent.py").read_text(encoding="utf-8")
    # 논문 코드에서 프롬프트 정의 부분만 실행해 비교한다 (나머지는 db 모듈이 필요하다)
    ns: dict = {}
    exec(src[src.index("SQL_PROMPT = ("):src.index("PROMPTS = {")], ns)  # noqa: S102
    assert prompts.SYSTEM_PROMPT == ns["SQL_PROMPT"] + ns["ONTOLOGY_PROMPT"]
    assert spec is not None


def test_user_message_hint():
    assert prompts.user_message("Q?", "E", True) == "Q?\n\nHint: E"
    assert prompts.user_message("Q?", "E", False) == "Q?"
    assert prompts.user_message("Q?", "", True) == "Q?"


# ---- SPARQL 검색

def test_sparql_search_returns_short_names_and_viz(movie):
    _, g = movie
    r = tools.run_ontology_sparql(g, 'SELECT ?e ?src WHERE { ?e prov:wasDerivedFrom ?src . FILTER(CONTAINS(STR(?src), "/rental")) }')
    assert r.ok and r.text.splitlines()[0] == "e\tsrc"
    assert "Rental\trental" in r.text and "rental_hasInventory\trental/inventory_id" in r.text
    assert ONT + "Rental" in r.viz["classes"] and ONT + "rental_hasInventory" in r.viz["object_properties"]
    assert set(r.viz["tables"]) == {"rental", "payment", "film"}  # "/rental" 은 payment/rental_id, film/rental_rate 에도 걸린다
    assert {"table": "rental", "column": "inventory_id"} in r.viz["columns"]


def test_sparql_search_limits_and_errors(movie):
    _, g = movie
    many = tools.run_ontology_sparql(g, "SELECT ?p WHERE { ?p a owl:DatatypeProperty }")
    assert len(many.text.splitlines()) == 1 + tools.MAX_ROWS and many.table["truncated"]
    assert tools.run_ontology_sparql(g, "SELECT ?x WHERE { ?x a ont:Nothing }").text == "(no results)"
    assert tools.run_ontology_sparql(g, "ASK { ?s ?p ?o }").text.startswith("ERROR")
    assert tools.run_ontology_sparql(g, "SELEC nonsense").text.startswith("ERROR")


# ---- SQL 실행

def test_sql_is_read_only_and_limited(movie):
    ok = tools.run_sql("movie_3", "SELECT payment_id FROM payment ORDER BY payment_id")
    assert ok.ok and len(ok.table["rows"]) == tools.MAX_ROWS and ok.table["truncated"]
    for bad in ("DELETE FROM actor", "UPDATE actor SET first_name = 'x'", "SELECT 1; DROP TABLE actor", "CREATE TABLE z (i int)"):
        r = tools.run_sql("movie_3", bad)
        assert not r.ok and r.text.startswith("ERROR")
    assert tools.run_sql("movie_3", "SELECT count(*) FROM actor").table["rows"] == [[200]]
    assert tools.run_sql("movie_3", "SELECT nope FROM actor").text.startswith("ERROR")


def test_sql_join_path(movie):
    schema, _ = movie
    sql = ("SELECT c.first_name FROM rental AS r JOIN inventory i ON r.inventory_id = i.inventory_id "
           "JOIN customer c ON c.customer_id = r.customer_id WHERE i.film_id IN (SELECT film_id FROM film WHERE title = 'X')")
    path = tools.sql_join_path(sql, schema)
    assert path["tables"] == ["rental", "inventory", "customer", "film"]
    assert {"left_table": "rental", "left_column": "inventory_id", "right_table": "inventory", "right_column": "inventory_id",
            "fk": {"table": "rental", "column": "inventory_id"}, "via": "join"} in path["joins"]
    assert any(j["fk"] == {"table": "rental", "column": "customer_id"} for j in path["joins"])
    assert {"table": "film", "column": "title"} in path["columns"]
    # IN 하위 질의도 두 테이블을 잇는 경로로 본다 (inventory.film_id → film.film_id 외래 키)
    assert {"left_table": "inventory", "left_column": "film_id", "right_table": "film", "right_column": "film_id",
            "fk": {"table": "inventory", "column": "film_id"}, "via": "subquery"} in path["joins"]
    # 상관 하위 질의가 바깥 테이블을 참조하는 경우
    corr = tools.sql_join_path("SELECT f.title FROM film f WHERE EXISTS (SELECT 1 FROM film_actor fa WHERE fa.film_id = f.film_id)", schema)
    assert [(j["left_table"], j["right_table"], j["via"]) for j in corr["joins"]] == [("film_actor", "film", "subquery")]
    assert tools.sql_join_path("not sql at all (", schema) == {"tables": [], "joins": [], "columns": []}


# ---- SQL 실행 차단 조건

def call(tool_list, name, query):
    t = next(t for t in tool_list if t.name == name)
    return t.invoke({"type": "tool_call", "id": "1", "name": name, "args": {"query": query}})


def test_sql_is_refused_until_ontology_search_returns_results(movie):
    schema, g = movie
    tool_list = runner.build_tools("movie_3", schema, lambda: g)
    sql = "SELECT count(*) FROM actor"
    refused = call(tool_list, "sql_query", sql)
    assert refused.content == prompts.GATE_MESSAGE and refused.artifact["rejected"]
    # 결과가 없는 검색, 오류가 난 검색은 "검색한 것"으로 치지 않는다
    call(tool_list, "ontology_query", "SELECT ?x WHERE { ?x a ont:Nothing }")
    call(tool_list, "ontology_query", "broken")
    assert call(tool_list, "sql_query", sql).content == prompts.GATE_MESSAGE
    assert call(tool_list, "ontology_query", "SELECT ?c WHERE { ?c a owl:Class }").artifact["ok"]
    allowed = call(tool_list, "sql_query", sql)
    assert allowed.content == "count\n200" and not allowed.artifact["rejected"]
    # 질문마다 새로 센다
    assert call(runner.build_tools("movie_3", schema, lambda: g), "sql_query", sql).content == prompts.GATE_MESSAGE


# ---- 이벤트 순서 (가짜 모델)

class FakeModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):  # create_react_agent 가 호출한다
        return self


def tool_call(name, query, i):
    return AIMessage(content=f"생각 {i}", tool_calls=[{"name": name, "args": {"query": query}, "id": f"call_{i}"}])


def test_event_stream_records_refused_sql_then_search_sql_answer(movie):
    schema, g = movie
    sql = "SELECT a.first_name FROM actor a JOIN film_actor fa ON fa.actor_id = a.actor_id LIMIT 1"
    script = iter([
        tool_call("sql_query", sql, 1),                                               # 검색 전에 SQL → 거절
        tool_call("ontology_query", "SELECT ?c WHERE { ?c a owl:Class }", 2),
        tool_call("sql_query", sql, 3),
        AIMessage(content="답: 한 명"),
    ])
    events = list(runner.run("movie_3", schema, lambda: g, "Who?", "hint", True, llm=FakeModel(messages=script)))
    kinds = [(e["type"], e.get("tool")) for e in events]
    assert kinds == [
        ("start", None),
        ("thought", None), ("tool_call", "sql_query"), ("tool_result", "sql_query"),
        ("thought", None), ("tool_call", "ontology_query"), ("tool_result", "ontology_query"),
        ("thought", None), ("tool_call", "sql_query"), ("tool_result", "sql_query"),
        ("answer", None),
    ]
    assert events[0]["prompt"] == "Who?\n\nHint: hint"
    results = [e for e in events if e["type"] == "tool_result"]
    assert results[0]["rejected"] and results[0]["output"] == prompts.GATE_MESSAGE
    assert results[1]["ok"] and len(results[1]["viz"]["classes"]) == 16
    assert results[2]["ok"] and results[2]["viz"]["tables"] == ["actor", "film_actor"]
    answer = events[-1]
    assert answer["text"] == "답: 한 명" and answer["final_sql"] == sql and answer["searched_ontology"]
    assert answer["table"]["columns"] == ["first_name"] and answer["steps"] == 3
    assert answer["viz"]["joins"][0]["fk"] == {"table": "film_actor", "column": "actor_id"}


def test_ontology_edits_are_used_immediately(movie):
    """도구는 호출할 때마다 현재 그래프를 읽는다."""
    schema, g = movie
    from rdflib import Graph, Literal, URIRef
    from rdflib.namespace import RDFS

    current = {"g": g}
    tool_list = runner.build_tools("movie_3", schema, lambda: current["g"])
    q = "SELECT ?l WHERE { ont:Film rdfs:label ?l }"
    assert "Film" in call(tool_list, "ontology_query", q).content
    edited = Graph()
    edited += g
    edited.remove((URIRef(ONT + "Film"), RDFS.label, None))
    edited.add((URIRef(ONT + "Film"), RDFS.label, Literal("Motion Picture", lang="en")))
    current["g"] = edited
    assert "Motion Picture" in call(tool_list, "ontology_query", q).content
