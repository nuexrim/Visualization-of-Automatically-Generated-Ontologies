"""온톨로지 파일 보관. data/ontologies/<db>/ 에 Turtle 파일로 쌓이고, 그중 하나를 '불러온' 상태로 둔다.

처음에는 불러온 온톨로지가 없다. 생성(또는 업로드)한 파일을 사용자가 불러와야 화면과 에이전트가 쓴다.
"""
from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF

from backend.ontology.direct_mapping import bind_namespaces
from backend.paths import DATA

ROOT = DATA / "ontologies"
_SAFE = re.compile(r"[^A-Za-z0-9가-힣._\-]+")


def _dir(db: str) -> Path:
    d = ROOT / db
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(db: str, filename: str) -> Path:
    """목록에 있는 파일만 허용한다 (경로 조작 방지)."""
    if filename != Path(filename).name or not filename.endswith(".ttl"):
        raise FileNotFoundError(filename)
    p = _dir(db) / filename
    if not p.is_file():
        raise FileNotFoundError(filename)
    return p


@lru_cache(maxsize=32)
def _parse(path: str, mtime_ns: int) -> Graph:  # mtime이 바뀌면 다시 읽는다
    g = Graph()
    g.parse(path, format="turtle")
    return g


def _graph(path: Path) -> Graph:
    return _parse(str(path), path.stat().st_mtime_ns)


def _counts(g: Graph) -> dict[str, int]:
    n = lambda t: len({s for s in g.subjects(RDF.type, t) if isinstance(s, URIRef)})
    return {"classes": n(OWL.Class), "data_properties": n(OWL.DatatypeProperty),
            "object_properties": n(OWL.ObjectProperty), "triples": len(g)}


def _info(db: str, path: Path) -> dict:
    meta_path = path.with_suffix(".json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    return {
        "filename": path.name,
        "created_at": meta.get("created_at") or datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        "kind": meta.get("kind", "unknown"),
        "note": meta.get("note", ""),
        # 수정본이면 바로 앞 파일(parent)과 처음 자동 생성된 파일(origin)
        "parent": meta.get("parent"),
        "origin": meta.get("origin") or path.name,
        "counts": _counts(_graph(path)),
        "loaded": current_filename(db) == path.name,
    }


def save(db: str, g: Graph, kind: str, label: str, note: str = "", extra: dict | None = None) -> dict:
    """그래프를 새 파일로 저장한다. kind: direct-mapping | rigor | upload | edit"""
    now = datetime.now()
    stem = f"{now:%Y%m%d-%H%M%S}_{_SAFE.sub('-', label).strip('-') or kind}"
    path = _dir(db) / f"{stem}.ttl"
    n = 2
    while path.exists():  # 같은 초에 두 번 저장한 경우
        path = _dir(db) / f"{stem}-{n}.ttl"
        n += 1
    bind_namespaces(g).serialize(destination=str(path), format="turtle")
    path.with_suffix(".json").write_text(
        json.dumps({"created_at": now.isoformat(timespec="seconds"), "kind": kind, "note": note, **(extra or {})}, ensure_ascii=False),
        encoding="utf-8",
    )
    return _info(db, path)


def save_upload(db: str, filename: str, content: bytes) -> dict:
    """업로드한 .ttl / .owl / .rdf / .xml 을 읽어 Turtle로 보관한다. 읽을 수 없으면 ValueError."""
    suffix = Path(filename).suffix.lower()
    order = ["turtle", "xml"] if suffix in (".ttl", ".n3") else ["xml", "turtle"]
    g, errors = None, []
    for fmt in order:
        try:
            g = Graph()
            g.parse(data=content, format=fmt)
            break
        except Exception as e:  # noqa: BLE001 - 형식마다 예외 종류가 다르다
            errors.append(f"{fmt}: {str(e).splitlines()[0][:120]}")
            g = None
    if g is None:
        raise ValueError("온톨로지 파일을 읽지 못했습니다 (" + " / ".join(errors) + ")")
    if not _counts(g)["classes"]:
        raise ValueError("파일에 owl:Class가 하나도 없습니다.")
    return save(db, g, "upload", Path(filename).stem, note=f"업로드: {filename}")


def list_files(db: str) -> list[dict]:
    return sorted((_info(db, p) for p in _dir(db).glob("*.ttl")), key=lambda i: i["filename"], reverse=True)


def _state_path(db: str) -> Path:
    return _dir(db) / "_state.json"


def current_filename(db: str) -> str | None:
    p = _state_path(db)
    if not p.exists():
        return None
    name = json.loads(p.read_text(encoding="utf-8")).get("current")
    return name if name and (_dir(db) / name).is_file() else None


def load(db: str, filename: str) -> dict:
    """파일을 '불러온' 상태로 만든다. 이후 화면과 에이전트가 이 온톨로지를 쓴다."""
    path = _path(db, filename)
    _state_path(db).write_text(json.dumps({"current": path.name}), encoding="utf-8")
    _drop_work(db)
    return _info(db, path)


def unload(db: str) -> None:
    _state_path(db).unlink(missing_ok=True)
    _drop_work(db)


def file_info(db: str, filename: str) -> dict:
    return _info(db, _path(db, filename))


def file_graph(db: str, filename: str) -> Graph:
    return _graph(_path(db, filename))


# ---------------------------------------------------------------- 사람이 수정하는 작업본
#
# 불러온 파일은 그대로 두고, 수정은 작업본에 한다. 화면과 에이전트는 작업본을 읽으므로
# 수정 내용이 다음 질의부터 바로 반영된다. "저장"하면 작업본을 새 버전 파일로 남긴다.
# 그래프는 바꾸지 않고 통째로 갈아 끼운다 (에이전트가 읽는 중인 그래프가 바뀌지 않게).
# 작업본과 되돌리기 기록은 data/ontologies/<db>/_work/ 에도 남겨, 백엔드를 다시 시작해도 이어진다.
# (그래프마다 스냅숏 파일 하나 + 순서를 적은 _index.json. 바뀌지 않은 그래프는 다시 쓰지 않는다)

UNDO_LIMIT = 100


@dataclass
class Work:
    filename: str
    graph: Graph
    undo: list[tuple[Graph, str]] = field(default_factory=list)   # (이전 그래프, 수정 설명)
    redo: list[tuple[Graph, str]] = field(default_factory=list)
    saved: Graph | None = None   # 파일과 같은 상태의 그래프 (불러올 때·저장할 때)
    saved_depth: int = 0         # 그때의 되돌리기 기록 길이
    snapshots: dict[int, tuple[Graph, str]] = field(default_factory=dict)  # id(그래프) → (그래프, 스냅숏 이름)

    @property
    def changes(self) -> int:
        """파일과 다른 정도 (되돌리기로 저장 시점에 돌아오면 0)."""
        if self.graph is self.saved:
            return 0
        return max(1, abs(len(self.undo) - self.saved_depth))


_work: dict[str, Work] = {}
_work_lock = threading.Lock()


def copy_graph(g: Graph) -> Graph:
    out = Graph()
    for t in g:
        out.add(t)
    for prefix, ns in g.namespaces():
        out.bind(prefix, ns, override=False)
    return out


def _work_dir(db: str) -> Path:
    return _dir(db) / "_work"


def _drop_work(db: str) -> None:
    with _work_lock:
        _work.pop(db, None)
        shutil.rmtree(_work_dir(db), ignore_errors=True)


def _persist(db: str, w: Work) -> None:
    """작업본과 되돌리기 기록을 디스크에 남긴다. _work_lock 을 잡은 채로 부른다."""
    d = _work_dir(db)
    d.mkdir(parents=True, exist_ok=True)
    keep: dict[int, tuple[Graph, str]] = {}

    def key(g: Graph) -> str:
        k = id(g)
        if k not in keep:
            known = w.snapshots.get(k)
            if known is None or known[0] is not g:
                name = uuid.uuid4().hex[:12]
                bind_namespaces(g).serialize(destination=str(d / f"{name}.ttl"), format="turtle")
                known = (g, name)
            keep[k] = known
        return keep[k][1]

    index = {
        "filename": w.filename,
        "graph": key(w.graph),
        "saved": key(w.saved) if w.saved is not None else None,
        "saved_depth": w.saved_depth,
        "undo": [[key(g), label] for g, label in w.undo],
        "redo": [[key(g), label] for g, label in w.redo],
    }
    w.snapshots = keep
    tmp = d / "_index.json.tmp"
    tmp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    tmp.replace(d / "_index.json")
    used = {name for _, name in keep.values()}
    for f in d.glob("*.ttl"):
        if f.stem not in used:
            f.unlink(missing_ok=True)


def _restore(db: str, filename: str) -> Work | None:
    """디스크에 남은 작업본을 읽는다. 지금 불러온 파일의 것이 아니거나 망가졌으면 None."""
    d = _work_dir(db)
    try:
        index = json.loads((d / "_index.json").read_text(encoding="utf-8"))
        if index.get("filename") != filename:
            return None
        graphs: dict[str, Graph] = {}

        def get(name: str) -> Graph:
            if name not in graphs:
                g = Graph()
                g.parse(str(d / f"{name}.ttl"), format="turtle")
                graphs[name] = g
            return graphs[name]

        w = Work(filename, get(index["graph"]),
                 undo=[(get(k), label) for k, label in index["undo"]],
                 redo=[(get(k), label) for k, label in index["redo"]],
                 saved=get(index["saved"]) if index.get("saved") else None,
                 saved_depth=int(index.get("saved_depth", 0)))
        w.snapshots = {id(g): (g, name) for name, g in graphs.items()}
        return w
    except Exception:  # noqa: BLE001 - 없거나 망가진 기록은 버리고 파일에서 새로 시작한다
        return None


def work(db: str) -> Work | None:
    """지금 불러온 파일의 작업본 (메모리 → 디스크 기록 → 파일 순으로 찾는다). 불러온 파일이 없으면 None."""
    name = current_filename(db)
    if name is None:
        return None
    with _work_lock:
        w = _work.get(db)
        if w is None or w.filename != name:
            w = _restore(db, name)
            if w is None:
                shutil.rmtree(_work_dir(db), ignore_errors=True)
                g = copy_graph(_graph(_dir(db) / name))
                w = Work(name, g, saved=g)
            _work[db] = w
        return w


def current_graph(db: str) -> Graph | None:
    w = work(db)
    return w.graph if w is not None else None


def history(db: str) -> dict:
    w = work(db)
    if w is None:
        return {"can_undo": False, "can_redo": False, "changes": 0, "undo_label": None, "redo_label": None}
    return {"can_undo": bool(w.undo), "can_redo": bool(w.redo), "changes": w.changes,
            "undo_label": w.undo[-1][1] if w.undo else None, "redo_label": w.redo[-1][1] if w.redo else None}


def commit(db: str, new_graph: Graph, label: str) -> None:
    w = work(db)
    assert w is not None
    with _work_lock:
        w.undo.append((w.graph, label))
        del w.undo[:-UNDO_LIMIT]
        w.redo.clear()
        w.graph = new_graph
        _persist(db, w)


def undo(db: str) -> bool:
    w = work(db)
    if w is None or not w.undo:
        return False
    with _work_lock:
        prev, label = w.undo.pop()
        w.redo.append((w.graph, label))
        w.graph = prev
        _persist(db, w)
    return True


def redo(db: str) -> bool:
    w = work(db)
    if w is None or not w.redo:
        return False
    with _work_lock:
        nxt, label = w.redo.pop()
        w.undo.append((w.graph, label))
        w.graph = nxt
        _persist(db, w)
    return True


def save_work(db: str, note: str = "") -> dict:
    """작업본을 새 버전 파일로 저장하고 그 파일을 불러온 상태로 만든다 (되돌리기 기록은 이어진다)."""
    w = work(db)
    if w is None:
        raise FileNotFoundError("불러온 온톨로지가 없습니다.")
    base = _info(db, _dir(db) / w.filename)
    info = save(db, copy_graph(w.graph), "edit", "edit", note=note or "사람이 수정한 버전",
                extra={"parent": w.filename, "origin": base["origin"]})
    _state_path(db).write_text(json.dumps({"current": info["filename"]}), encoding="utf-8")
    with _work_lock:
        w.filename = info["filename"]
        w.saved, w.saved_depth = w.graph, len(w.undo)
        _persist(db, w)
    info["loaded"] = True
    return info


def read_text(db: str, filename: str) -> str:
    return _path(db, filename).read_text(encoding="utf-8")
