"""sparql 조건 ReAct 에이전트 실행 (LangChain / LangGraph). 단계마다 구조화된 이벤트를 내보낸다.

논문 실험 코드(agent.py, main.py)와 같은 구성:
- 도구 2개: ontology_query(SPARQL로 온톨로지 검색), sql_query(PostgreSQL 질의)
- 온톨로지 검색이 결과를 돌려주기 전에는 sql_query 를 코드로 거절한다
- 질문당 최대 50단계, 도구 결과는 최대 50행
"""
from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator

from langchain.tools import tool
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from langgraph.prebuilt import create_react_agent
from rdflib import Graph

from backend.agent import prompts, tools

RECURSION_LIMIT = 50
MAX_TOKENS = 4096

Event = dict


def default_model() -> str:
    model = (os.environ.get("AGENT_MODEL") or "").strip()
    if not model:
        raise RuntimeError("AGENT_MODEL 환경 변수가 비어 있습니다 (.env 확인).")
    if not (os.environ.get("ANTHROPIC_API_KEY") or "").strip():
        raise RuntimeError("ANTHROPIC_API_KEY 환경 변수가 비어 있습니다 (.env 확인).")
    return model


def anthropic_chat_model(model: str):
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(model=model, max_tokens=MAX_TOKENS)


def build_tools(db: str, schema: dict, get_graph: Callable[[], Graph | None]):
    """질문 하나에 쓰는 도구 묶음. '온톨로지를 검색했는가'는 질문마다 새로 센다."""
    gate = {"searched": False}

    @tool(response_format="content_and_artifact")
    def sql_query(query: str):
        """Run a read-only SQL SELECT query and return the result rows."""
        if not gate["searched"]:
            # 프롬프트만으로는 모델이 SQL부터 쓸 수 있으므로 코드로 거절한다
            return prompts.GATE_MESSAGE, {"ok": False, "rejected": True}
        result = tools.run_sql(db, query)
        return result.text, {"ok": result.ok, "rejected": False, "table": result.table,
                             "viz": tools.sql_join_path(query, schema) if result.ok else {}}

    @tool(response_format="content_and_artifact")
    def ontology_query(query: str):
        """Search the database ontology with a SPARQL SELECT query. Use it to find classes,
        properties, relationships and their source table/column (prov:wasDerivedFrom)."""
        graph = get_graph()  # 호출할 때마다 읽으므로 사람이 수정한 내용이 바로 반영된다
        if graph is None:
            return "ERROR: 불러온 온톨로지가 없습니다.", {"ok": False, "rejected": False}
        result = tools.run_ontology_sparql(graph, query)
        if result.ok:
            gate["searched"] = True  # 스키마가 실제로 검색됐을 때만 SQL을 허용
        return result.text, {"ok": result.ok, "rejected": False, "table": result.table, "viz": result.viz}

    return [ontology_query, sql_query]


def _text(content) -> str:
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type", "text") == "text")
    return content or ""


def run(db: str, schema: dict, get_graph: Callable[[], Graph | None], question: str, evidence: str = "",
        use_evidence: bool = True, llm=None, model: str | None = None) -> Iterator[Event]:
    """에이전트를 실행하며 이벤트를 내보낸다.

    이벤트: start → (thought → tool_call → tool_result)* → answer | error
    """
    started = time.monotonic()
    model = model or (default_model() if llm is None else "test")
    llm = llm or anthropic_chat_model(model)
    agent = create_react_agent(llm, build_tools(db, schema, get_graph), prompt=prompts.SYSTEM_PROMPT)
    user = prompts.user_message(question, evidence, use_evidence)
    yield {"type": "start", "db": db, "question": question.strip(), "evidence": (evidence or "").strip(),
           "use_evidence": bool(use_evidence and (evidence or "").strip()), "model": model, "prompt": user}

    step, mark = 0, time.monotonic()
    tokens = {"input": 0, "output": 0}
    calls: dict[str, dict] = {}       # tool_call_id → {tool, query, step}
    final_sql, final_table, answer = None, None, ""
    searched_ok = False

    def elapsed() -> float:
        nonlocal mark
        t = time.monotonic()
        d, mark = round(t - mark, 2), t
        return d

    try:
        stream = agent.stream({"messages": [{"role": "user", "content": user}]},
                              config={"recursion_limit": RECURSION_LIMIT}, stream_mode="updates")
        for update in stream:
            for node_output in update.values():
                for m in (node_output or {}).get("messages", []):
                    if isinstance(m, AIMessage):
                        usage = m.usage_metadata or {}
                        tokens["input"] += usage.get("input_tokens", 0)
                        tokens["output"] += usage.get("output_tokens", 0)
                        text = _text(m.content).strip()
                        seconds = elapsed()
                        if m.tool_calls:
                            if text:
                                yield {"type": "thought", "text": text, "seconds": seconds,
                                       "tokens": {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0)}}
                            for tc in m.tool_calls:
                                step += 1
                                query = (tc.get("args") or {}).get("query", "")
                                calls[tc["id"]] = {"tool": tc["name"], "query": query, "step": step}
                                yield {"type": "tool_call", "step": step, "id": tc["id"], "tool": tc["name"], "input": query,
                                       "seconds": 0 if text else seconds,
                                       "tokens": None if text else {"input": usage.get("input_tokens", 0), "output": usage.get("output_tokens", 0)}}
                        else:
                            answer = text
                    elif isinstance(m, ToolMessage):
                        call = calls.get(m.tool_call_id, {"tool": m.name, "query": "", "step": step})
                        art = m.artifact if isinstance(m.artifact, dict) else {}
                        ok, rejected = bool(art.get("ok")), bool(art.get("rejected"))
                        if call["tool"] == "ontology_query" and ok:
                            searched_ok = True
                        if call["tool"] == "sql_query" and not rejected:
                            final_sql = call["query"]      # 마지막으로 실행한 SQL
                            final_table = art.get("table") if ok else None
                        yield {"type": "tool_result", "step": call["step"], "id": m.tool_call_id, "tool": call["tool"],
                               "output": _text(m.content), "ok": ok, "rejected": rejected, "seconds": elapsed(),
                               "table": art.get("table"), "viz": art.get("viz") or {}}
    except GraphRecursionError:
        yield {"type": "error", "message": f"질문당 최대 {RECURSION_LIMIT}단계를 넘어 중단했습니다.",
               "seconds_total": round(time.monotonic() - started, 2), "tokens_total": tokens}
        return
    except Exception as e:  # noqa: BLE001
        yield {"type": "error", "message": f"{type(e).__name__}: {e}",
               "seconds_total": round(time.monotonic() - started, 2), "tokens_total": tokens}
        return

    yield {"type": "answer", "text": answer, "final_sql": final_sql, "table": final_table,
           "viz": tools.sql_join_path(final_sql, schema) if final_sql else {}, "searched_ontology": searched_ok,
           "steps": step, "seconds": elapsed(), "seconds_total": round(time.monotonic() - started, 2), "tokens_total": tokens}
