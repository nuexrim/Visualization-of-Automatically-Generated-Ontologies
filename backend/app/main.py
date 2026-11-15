"""OntoLens 백엔드 API."""
from __future__ import annotations

import asyncio
import json
import queue
import tempfile
from datetime import datetime
import threading
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.agent import history, prompts, runner
from backend.db import importer
from backend.db.connection import DB_NAME_RE, admin_connect
from backend.db.graph_stats import stats_from_db
from backend.db.questions import questions_for
from backend.db.schema import extract_schema
from backend.ontology import edit, rigor, store
from backend.ontology.direct_mapping import column_xsd_types
from backend.ontology.view import graph_to_view

app = FastAPI(title="OntoLens")

#: DB마다 온톨로지 생성은 한 번에 하나만
_generating: dict[str, threading.Lock] = {}


def _check_db(db: str) -> str:
    """이 프로그램으로 불러온 DB인지 확인한다."""
    if not DB_NAME_RE.fullmatch(db) or not importer.is_imported(db):
        raise HTTPException(404, f"불러온 적 없는 DB입니다: {db}")
    return db


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/dbs")
def list_dbs() -> list[dict]:
    """불러온 DB 목록과 그래프 통계. 처음에는 비어 있다."""
    out = []
    for d in importer.list_databases():
        with admin_connect(d["name"]) as conn:
            out.append({**d, "stats": stats_from_db(conn).as_dict()})
    return out


MAX_DB_UPLOAD_BYTES = 2 * 1024**3


@app.post("/api/dbs/import")
def import_db(file: UploadFile, replace: bool = Form(False)) -> dict:
    """DB 파일(.dump / .sql / .sqlite)을 불러온다. PostgreSQL에 올린 뒤 이름과 그래프 통계를 돌려준다."""
    filename = file.filename or "database.dump"
    with tempfile.TemporaryDirectory(prefix="ontolens-import-") as tmp:
        path = Path(tmp) / "upload"
        size = 0
        with path.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_DB_UPLOAD_BYTES:
                    raise HTTPException(413, "파일이 너무 큽니다 (최대 2GB).")
                out.write(chunk)
        try:
            info = importer.import_file(path, filename, replace=replace)
        except FileExistsError as e:
            raise HTTPException(409, f"'{e.args[0]}' DB가 이미 있습니다.") from e
        except importer.ImportError_ as e:
            raise HTTPException(400, str(e)) from e
    with admin_connect(info["name"]) as conn:
        return {**info, "stats": stats_from_db(conn).as_dict()}


@app.delete("/api/dbs/{db}")
def delete_db(db: str) -> dict:
    """불러온 DB를 닫는다 (PostgreSQL에서 지움). 원본 파일과 만들어 둔 온톨로지 파일은 남는다."""
    _check_db(db)
    lock = _generating.setdefault(db, threading.Lock())
    if lock.locked():
        raise HTTPException(409, "온톨로지를 생성하는 중에는 닫을 수 없습니다.")
    importer.drop_database(db)
    return {"ok": True}


@app.get("/api/dbs/{db}/schema")
def get_schema(db: str) -> dict:
    with admin_connect(_check_db(db)) as conn:
        return extract_schema(conn, db)


@app.get("/api/dbs/{db}/questions")
def get_questions(db: str) -> list[dict]:
    return questions_for(_check_db(db))


# ---------------------------------------------------------------- 온톨로지

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class LoadRequest(BaseModel):
    filename: str





def sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.post("/api/dbs/{db}/ontology/generate")
def generate_ontology(db: str, mode: str = "rigor") -> StreamingResponse:
    """온톨로지 파일을 만든다. 진행 상황을 SSE로 보낸다.

    mode=rigor : 테이블마다 Direct Mapping → 맥락 검색 → 생성 LLM 보강 → 판정 LLM 검토
    mode=direct: Direct Mapping만 (LLM 호출 없음)
    만든 파일은 불러오기 전까지 화면과 에이전트에 쓰이지 않는다.
    """
    _check_db(db)
    if mode not in ("rigor", "direct"):
        raise HTTPException(400, "mode는 rigor 또는 direct 여야 합니다.")
    usage = rigor.Usage()
    model = None
    if mode == "rigor":
        try:
            model = rigor.default_model()
        except RuntimeError as e:
            raise HTTPException(400, str(e)) from e
    lock = _generating.setdefault(db, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(409, f"{db}의 온톨로지를 이미 생성하는 중입니다.")

    # 생성은 별도 스레드에서 돌고, 이벤트를 큐로 넘긴다. 브라우저가 연결을 끊으면(중지) 다음 이벤트에서 멈춘다.
    events: queue.Queue[dict | None] = queue.Queue()
    cancelled = threading.Event()

    def work() -> None:
        try:
            with admin_connect(db) as conn:
                schema = extract_schema(conn, db)
                xsd = column_xsd_types(schema, conn)
            llm = rigor.anthropic_llm(model, usage) if model else None
            result: dict = {}
            for event in rigor.generate(db, schema, xsd, llm, result):
                if cancelled.is_set():
                    return
                if event["type"] == "start":
                    event["model"] = model
                events.put(event)
            outcomes = result["outcomes"]
            enriched = sum(o == "enriched" for o in outcomes.values())
            if mode == "rigor":
                note = (f"RIGOR 방식 · 모델 {model} · 보강 {enriched}/{len(outcomes)} 테이블 · "
                        f"LLM 호출 {usage.calls}회 (입력 {usage.input_tokens:,} / 출력 {usage.output_tokens:,} 토큰)")
                info = store.save(db, result["graph"], "rigor", f"rigor_{model}", note=note)
            else:
                info = store.save(db, result["graph"], "direct-mapping", "direct-mapping", note="Direct Mapping (LLM 보강 없음)")
            events.put({"type": "done", "file": info, "outcomes": outcomes, "warnings": result["warnings"][:50],
                        "usage": {"calls": usage.calls, "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}})
        except Exception as e:  # noqa: BLE001 - 어떤 오류든 화면에 알린다
            events.put({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            lock.release()
            events.put(None)

    threading.Thread(target=work, name=f"generate-{db}", daemon=True).start()

    async def stream() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        try:
            while (event := await loop.run_in_executor(None, events.get)) is not None:
                yield sse(event)
        finally:
            cancelled.set()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/dbs/{db}/ontology/files")
def list_ontology_files(db: str) -> list[dict]:
    return store.list_files(_check_db(db))


@app.post("/api/dbs/{db}/ontology/upload")
async def upload_ontology(db: str, file: UploadFile) -> dict:
    _check_db(db)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "파일이 너무 큽니다 (최대 20MB).")
    try:
        return store.save_upload(db, file.filename or "upload.owl", content)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/dbs/{db}/ontology/load")
def load_ontology(db: str, req: LoadRequest) -> dict:
    try:
        store.load(_check_db(db), req.filename)
    except FileNotFoundError as e:
        raise HTTPException(404, f"파일이 없습니다: {req.filename}") from e
    return get_ontology(db)


@app.delete("/api/dbs/{db}/ontology")
def unload_ontology(db: str) -> dict:
    store.unload(_check_db(db))
    return {"ok": True}


@app.get("/api/dbs/{db}/ontology")
def get_ontology(db: str, turtle: bool = False) -> dict:
    """지금 불러온 온톨로지. 없으면 404."""
    graph = store.current_graph(_check_db(db))
    filename = store.current_filename(db)
    if graph is None or filename is None:
        raise HTTPException(404, "불러온 온톨로지가 없습니다.")
    out = _ontology_out(db, graph, filename)
    if turtle:
        out["turtle"] = store.read_text(db, filename)
    return out


def _ontology_out(db: str, graph, filename: str) -> dict:
    """화면용 JSON + 수정 기록 상태(되돌리기 가능 여부, 저장 안 한 수정 수)."""
    return {"filename": filename, **graph_to_view(graph), "history": store.history(db)}


# ---------------------------------------------------------------- 사람이 수정하기

class PatchRequest(BaseModel):
    ops: list[dict]


class SaveRequest(BaseModel):
    note: str = ""


def _schema(db: str) -> dict:
    with admin_connect(db) as conn:
        return extract_schema(conn, db)


def _work_or_404(db: str) -> store.Work:
    w = store.work(_check_db(db))
    if w is None:
        raise HTTPException(404, "불러온 온톨로지가 없습니다.")
    return w


@app.patch("/api/dbs/{db}/ontology")
def patch_ontology(db: str, req: PatchRequest) -> dict:
    """수정 연산을 작업본에 적용한다. 수정으로 새 오류가 생기면 적용하지 않고 422로 이유를 돌려준다.

    작업본은 화면과 에이전트가 바로 쓰므로, 수정 내용이 다음 질의부터 반영된다.
    """
    w = _work_or_404(db)
    schema = _schema(db)
    try:
        new_graph, label = edit.apply_ops(w.graph, req.ops)
    except edit.EditError as e:
        raise HTTPException(400, str(e)) from e
    before = edit.check(w.graph, schema)
    after = edit.check(new_graph, schema)
    errors = edit.new_errors(before, after)
    if errors:
        raise HTTPException(422, {"message": "검사를 통과하지 못해 적용하지 않았습니다.", "issues": errors})
    store.commit(db, new_graph, label)
    return {**_ontology_out(db, new_graph, w.filename), "issues": after, "applied": label}


@app.post("/api/dbs/{db}/ontology/undo")
def undo_ontology(db: str) -> dict:
    w = _work_or_404(db)
    if not store.undo(db):
        raise HTTPException(409, "되돌릴 수정이 없습니다.")
    return _ontology_out(db, w.graph, w.filename)


@app.post("/api/dbs/{db}/ontology/redo")
def redo_ontology(db: str) -> dict:
    w = _work_or_404(db)
    if not store.redo(db):
        raise HTTPException(409, "다시 할 수정이 없습니다.")
    return _ontology_out(db, w.graph, w.filename)


@app.get("/api/dbs/{db}/ontology/check")
def check_ontology(db: str) -> list[dict]:
    w = _work_or_404(db)
    return edit.check(w.graph, _schema(db))


@app.post("/api/dbs/{db}/ontology/save")
def save_ontology(db: str, req: SaveRequest) -> dict:
    """작업본을 새 버전 파일로 저장하고 그 파일을 불러온다. 오류가 있으면 저장하지 않는다."""
    w = _work_or_404(db)
    schema = _schema(db)
    issues = edit.check(w.graph, schema)
    # 자동 생성 원본에 원래 있던 문제는 막지 않는다
    origin = edit.check(store.file_graph(db, store.file_info(db, w.filename)["origin"]), schema)
    errors = edit.new_errors(origin, issues)
    if errors:
        raise HTTPException(422, {"message": "검사를 통과하지 못해 저장하지 않았습니다.", "issues": errors})
    info = store.save_work(db, req.note.strip())
    return {"file": info, "ontology": _ontology_out(db, w.graph, info["filename"]), "issues": issues}


@app.get("/api/dbs/{db}/ontology/versions")
def ontology_versions(db: str) -> list[dict]:
    """지금 불러온 파일과 같은 자동 생성 원본에서 나온 버전들 (원본 포함, 최신 순)."""
    name = store.current_filename(_check_db(db))
    if name is None:
        return []
    origin = store.file_info(db, name)["origin"]
    return [f for f in store.list_files(db) if f["origin"] == origin]


@app.get("/api/dbs/{db}/ontology/diff")
def ontology_diff(db: str, against: str | None = None) -> dict:
    """작업본과 다른 파일의 차이. against 를 주지 않으면 자동 생성 원본과 비교한다."""
    w = _work_or_404(db)
    target = against or store.file_info(db, w.filename)["origin"]
    try:
        base = store.file_graph(db, target)
    except FileNotFoundError as e:
        raise HTTPException(404, f"파일이 없습니다: {target}") from e
    items = edit.diff(base, w.graph)
    return {"against": target, "current": w.filename, "unsaved_changes": store.history(db)["changes"], "items": items,
            "summary": {"subjects": len(items), "added": sum(len(i["added"]) for i in items), "removed": sum(len(i["removed"]) for i in items)}}


# ---------------------------------------------------------------- 채팅 (sparql 조건 에이전트)

class ChatRequest(BaseModel):
    question: str
    evidence: str = ""
    use_evidence: bool = True


@app.get("/api/agent/prompt")
def agent_prompt() -> dict:
    """에이전트의 시스템 프롬프트와 실행 조건 (화면의 설정 메뉴에서 본다)."""
    import os

    return {
        "system_prompt": prompts.SYSTEM_PROMPT,
        "gate_message": prompts.GATE_MESSAGE,
        "model": (os.environ.get("AGENT_MODEL") or "").strip() or None,
        "tools": ["ontology_query", "sql_query"],
        "limits": {"max_steps": runner.RECURSION_LIMIT, "max_rows": 50, "sql_timeout_sec": 30, "max_tokens": runner.MAX_TOKENS},
    }


@app.post("/api/dbs/{db}/chat")
def chat(db: str, req: ChatRequest) -> StreamingResponse:
    """질문을 실행한다. 에이전트의 각 단계를 SSE로 보내고, 끝나면 기록을 저장한다."""
    _check_db(db)
    if not req.question.strip():
        raise HTTPException(400, "질문이 비어 있습니다.")
    ontology_file = store.current_filename(db)
    if ontology_file is None:
        raise HTTPException(400, "먼저 온톨로지 파일을 불러오세요. 에이전트는 온톨로지를 검색한 뒤에만 SQL을 실행합니다.")
    unsaved = store.history(db)["changes"]
    if unsaved:  # 기록에 "저장하지 않은 수정이 반영된 상태"였음을 남긴다
        ontology_file = f"{ontology_file} + 저장 안 한 수정 {unsaved}건"
    try:
        model = runner.default_model()
    except RuntimeError as e:
        raise HTTPException(400, str(e)) from e
    with admin_connect(db) as conn:
        schema = extract_schema(conn, db)

    run_id = history.new_run_id()
    meta = {"db": db, "created_at": datetime.now().isoformat(timespec="seconds"), "question": req.question.strip(),
            "evidence": req.evidence.strip(), "use_evidence": req.use_evidence, "ontology_file": ontology_file, "model": model}
    events: queue.Queue[dict | None] = queue.Queue()
    cancelled = threading.Event()

    def work() -> None:
        log: list[dict] = []
        try:
            for event in runner.run(db, schema, lambda: store.current_graph(db), req.question, req.evidence, req.use_evidence, model=model):
                if event["type"] == "start":
                    event.update(run_id=run_id, ontology_file=ontology_file)
                log.append(event)
                if cancelled.is_set():
                    log.append({"type": "error", "message": "사용자가 중지했습니다."})
                    break
                events.put(event)
        except Exception as e:  # noqa: BLE001
            log.append({"type": "error", "message": f"{type(e).__name__}: {e}"})
            events.put(log[-1])
        finally:
            history.save(db, run_id, meta, log)  # 모든 단계를 파일에 남긴다
            events.put(None)

    threading.Thread(target=work, name=f"chat-{db}", daemon=True).start()

    async def stream() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        try:
            while (event := await loop.run_in_executor(None, events.get)) is not None:
                yield sse(event)
        finally:
            cancelled.set()

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/dbs/{db}/chat/runs")
def list_chat_runs(db: str) -> list[dict]:
    return history.list_runs(_check_db(db))


@app.get("/api/dbs/{db}/chat/runs/{run_id}")
def get_chat_run(db: str, run_id: str) -> dict:
    try:
        return history.load(_check_db(db), run_id)
    except FileNotFoundError as e:
        raise HTTPException(404, "기록이 없습니다.") from e
