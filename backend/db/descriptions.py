"""BIRD database_description CSV(컬럼 설명) 읽기."""
from __future__ import annotations

import csv
from functools import lru_cache

from backend.paths import BIRD


def _read_text(path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _clean(s: str | None) -> str:
    return " ".join((s or "").replace("\r", "\n").split()) if s and "\n" not in s.strip() else \
        "\n".join(line.strip() for line in (s or "").replace("\r", "\n").split("\n") if line.strip())


@lru_cache(maxsize=None)
def load_descriptions(db: str) -> dict[str, dict[str, dict[str, str]]]:
    """{테이블(소문자): {컬럼(소문자): {label, description, value_description}}}.

    CSV의 컬럼 이름은 실제 DB와 대소문자가 다를 수 있어 소문자로 맞춰 찾는다.
    """
    out: dict[str, dict[str, dict[str, str]]] = {}
    folder = BIRD / db / "database_description"
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.csv")):
        cols: dict[str, dict[str, str]] = {}
        for row in csv.DictReader(_read_text(path).splitlines(keepends=True)):
            name = (row.get("original_column_name") or "").strip().lower()
            if not name:
                continue
            cols[name] = {
                "label": _clean(row.get("column_name")),
                "description": _clean(row.get("column_description")),
                "value_description": _clean(row.get("value_description")),
            }
        out[path.stem.lower()] = cols
    return out


def describe(db: str, table: str, column: str) -> dict[str, str]:
    return load_descriptions(db).get(table.lower(), {}).get(
        column.lower(), {"label": "", "description": "", "value_description": ""}
    )
