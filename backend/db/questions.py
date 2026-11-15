"""BIRD 예시 질문 (data/bird/questions.json)."""
from __future__ import annotations

import json
from functools import lru_cache

from backend.paths import BIRD


@lru_cache(maxsize=1)
def _all() -> list[dict]:
    path = BIRD / "questions.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def questions_for(db: str) -> list[dict]:
    return [q for q in _all() if q["db_id"] == db]
