"""질의 기록 보관. data/runs/<db>/<run_id>.json 에 질문 하나의 모든 이벤트를 남긴다."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path

from backend.paths import DATA

ROOT = DATA / "runs"
_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")


def new_run_id() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"


def save(db: str, run_id: str, meta: dict, events: list[dict]) -> None:
    d = ROOT / db
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{run_id}.json").write_text(json.dumps({"id": run_id, **meta, "events": events}, ensure_ascii=False), encoding="utf-8")


def _summary(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    events = data.get("events", [])
    last = events[-1] if events else {}
    return {
        "id": data["id"], "created_at": data.get("created_at"), "question": data.get("question", ""),
        "ontology_file": data.get("ontology_file"), "model": data.get("model"),
        "status": last.get("type", "unknown"), "steps": sum(e["type"] == "tool_call" for e in events),
        "seconds_total": last.get("seconds_total"), "final_sql": last.get("final_sql"),
    }


def list_runs(db: str) -> list[dict]:
    d = ROOT / db
    if not d.is_dir():
        return []
    return [_summary(p) for p in sorted(d.glob("*.json"), reverse=True)][:200]


def load(db: str, run_id: str) -> dict:
    if not _ID.fullmatch(run_id):
        raise FileNotFoundError(run_id)
    path = ROOT / db / f"{run_id}.json"
    if not path.is_file():
        raise FileNotFoundError(run_id)
    return json.loads(path.read_text(encoding="utf-8"))
