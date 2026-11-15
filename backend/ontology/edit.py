"""사람이 온톨로지를 수정하는 연산과 수정 전 검사.

화면은 연산 목록(JSON)을 보내고, 백엔드는 작업본의 복사본에 적용한 뒤 검사한다.
수정으로 새로 생긴 오류가 있으면 적용하지 않는다. DB의 실제 데이터는 건드리지 않는다.

연산 (op 이름과 인자):
  set_label            iri, value
  set_comment          iri, value                 설명 (값 의미 설명은 빼고 모두 바꾼다)
  set_value_description iri, value                코드값 의미 (예: rating 'PG' = ...). 빈 문자열이면 지운다
  set_parents          iri, values[]              상위 클래스
  set_domain           iri, values[]
  set_range            iri, values[]              객체 속성은 클래스 IRI, 데이터 속성은 xsd:… 자료형
  rename               iri, name                  IRI 이름 바꾸기 (모든 트리플에서 바꾼다)
  add_object_property  name, label?, comment?, domain, range, source?{table, column}
  delete_property      iri                        객체·데이터 속성 삭제 (그 속성을 쓰는 제약도 함께)
  add_triple           s, p, o, kind(iri|literal), lang?, datatype?
  remove_triple        s, p, o, kind, lang?, datatype?
"""
from __future__ import annotations

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import OWL, PROV, RDF, RDFS, XSD

from backend.ontology import naming
from backend.ontology.store import copy_graph
# 코드값 의미는 rdfs:comment 로 넣되 VALUE_PREFIX 머리말을 붙여 일반 설명과 구분한다.
# 논문 에이전트 프롬프트가 설명을 rdfs:comment 로 찾게 하므로, 에이전트가 따로 배우지 않아도 읽을 수 있다.
from backend.ontology.view import _PREFIXES, VALUE_PREFIX, render, short

DATATYPES = {str(XSD[t]) for t in (
    "string", "integer", "int", "long", "short", "decimal", "float", "double", "boolean", "date", "dateTime",
    "time", "gYear", "anyURI", "nonNegativeInteger", "positiveInteger", "base64Binary", "hexBinary", "duration",
)} | {str(RDFS.Literal)}


class EditError(ValueError):
    """잘못된 연산 (없는 IRI, 형식 오류 등)."""


def expand(term: str) -> URIRef:
    """'ont:Film', 'xsd:string', 전체 IRI 를 모두 받는다."""
    t = str(term).strip()
    if not t:
        raise EditError("빈 IRI입니다.")
    for full, prefix in _PREFIXES:
        if t.startswith(prefix):
            return URIRef(full + t[len(prefix):])
    if "://" in t:
        return URIRef(t)
    raise EditError(f"IRI 형식이 아닙니다: {t} (예: ont:Film, xsd:string, http://…)")


def _need(g: Graph, iri: str) -> URIRef:
    u = expand(iri)
    if (u, None, None) not in g and (None, None, u) not in g:
        raise EditError(f"온톨로지에 없는 요소입니다: {short(u)}")
    return u


def _lang_of(g: Graph, s: URIRef, p: URIRef) -> str | None:
    for o in g.objects(s, p):
        if isinstance(o, Literal) and o.language:
            return o.language
    return None


def _text(g: Graph, s: URIRef, p: URIRef, value: str) -> Literal:
    """기존 값과 같은 언어 태그를 붙인다 (한글이 들어 있으면 태그 없이)."""
    lang = _lang_of(g, s, p)
    if lang and any(ord(ch) > 0x2FF for ch in value):
        lang = None
    return Literal(value, lang=lang)


def _is_value_note(o) -> bool:
    return isinstance(o, Literal) and str(o).startswith(VALUE_PREFIX)


def _literal(spec: dict) -> Literal:
    lang, dtype = spec.get("lang") or None, spec.get("datatype") or None
    if lang:
        return Literal(spec["o"], lang=lang)
    return Literal(spec["o"], datatype=expand(dtype) if dtype else None)


def _object(spec: dict):
    kind = spec.get("kind", "iri")
    if kind == "literal":
        return _literal(spec)
    if kind == "iri":
        return expand(spec["o"])
    raise EditError("빈 노드(제약식) 값은 이 화면에서 직접 고칠 수 없습니다.")


def _remove_restrictions_on(g: Graph, prop: URIRef) -> None:
    """owl:onProperty prop 인 제약(빈 노드)과 그것을 가리키는 트리플을 지운다."""
    for b in list(g.subjects(OWL.onProperty, prop)):
        if not isinstance(b, BNode):
            continue
        for t in list(g.triples((None, None, b))):
            g.remove(t)
        for t in list(g.triples((b, None, None))):
            g.remove(t)


def _describe(op: dict, g: Graph) -> str:
    """되돌리기 메뉴에 보여줄 짧은 설명."""
    name = lambda k: short(expand(op[k])) if op.get(k) else ""
    kind = op.get("op")
    return {
        "set_label": f"{name('iri')} 라벨 수정",
        "set_comment": f"{name('iri')} 설명 수정",
        "set_value_description": f"{name('iri')} 코드값 설명 수정",
        "set_parents": f"{name('iri')} 상위 클래스 수정",
        "set_domain": f"{name('iri')} 도메인 수정",
        "set_range": f"{name('iri')} 범위 수정",
        "rename": f"{name('iri')} → ont:{op.get('name', '')} 이름 변경",
        "add_object_property": f"관계 ont:{op.get('name', '')} 추가",
        "delete_property": f"{name('iri')} 삭제",
        "add_triple": f"{name('s')} 트리플 추가",
        "remove_triple": f"{name('s')} 트리플 삭제",
    }.get(kind, str(kind))


def apply_op(g: Graph, op: dict) -> None:
    kind = op.get("op")
    if kind == "set_label":
        s = _need(g, op["iri"])
        value = str(op["value"]).strip()
        g.remove((s, RDFS.label, None))
        if value:
            g.add((s, RDFS.label, Literal(value, lang="en") if value.isascii() else Literal(value)))
    elif kind == "set_comment":
        s = _need(g, op["iri"])
        value = str(op["value"]).strip()
        lit = _text(g, s, RDFS.comment, value)
        for o in list(g.objects(s, RDFS.comment)):
            if not _is_value_note(o):
                g.remove((s, RDFS.comment, o))
        if value:
            g.add((s, RDFS.comment, lit))
    elif kind == "set_value_description":
        s = _need(g, op["iri"])
        for o in list(g.objects(s, RDFS.comment)):
            if _is_value_note(o):
                g.remove((s, RDFS.comment, o))
        value = str(op["value"]).strip()
        if value:
            g.add((s, RDFS.comment, Literal(VALUE_PREFIX + value)))
    elif kind in ("set_parents", "set_domain", "set_range"):
        s = _need(g, op["iri"])
        p = {"set_parents": RDFS.subClassOf, "set_domain": RDFS.domain, "set_range": RDFS.range}[kind]
        values = [expand(v) for v in op.get("values", [])]
        # 상위 클래스: 이름 있는 상위 클래스만 바꾸고, 제약(빈 노드)으로 된 subClassOf 는 그대로 둔다
        for o in list(g.objects(s, p)):
            if isinstance(o, URIRef):
                g.remove((s, p, o))
        for v in values:
            g.add((s, p, v))
    elif kind == "rename":
        old = _need(g, op["iri"])
        name = str(op["name"]).strip()
        if naming.safe_local_name(name) != name:
            raise EditError(f"이름에는 영문, 숫자, _, - 만 쓸 수 있습니다: {name!r}")
        new = naming.ONT[name]
        if new == old:
            return
        if (new, None, None) in g or (None, None, new) in g:
            raise EditError(f"이미 있는 이름입니다: ont:{name}")
        for s, p, o in list(g):
            if old in (s, p, o):
                g.remove((s, p, o))
                g.add((new if s == old else s, new if p == old else p, new if o == old else o))
    elif kind == "add_object_property":
        name = str(op.get("name", "")).strip()
        if not name or naming.safe_local_name(name) != name:
            raise EditError(f"관계 이름에는 영문, 숫자, _, - 만 쓸 수 있습니다: {name!r}")
        p = naming.ONT[name]
        if (p, None, None) in g or (None, None, p) in g:
            raise EditError(f"이미 있는 이름입니다: ont:{name}")
        g.add((p, RDF.type, OWL.ObjectProperty))
        g.add((p, RDFS.domain, expand(op["domain"])))
        g.add((p, RDFS.range, expand(op["range"])))
        g.add((p, RDFS.label, Literal(str(op.get("label") or naming.humanize_identifier(name)), lang="en")))
        if op.get("comment"):
            g.add((p, RDFS.comment, Literal(str(op["comment"]))))
        src = op.get("source") or {}
        if src.get("table"):
            g.add((p, PROV.wasDerivedFrom, naming.provenance_iri(src["table"], src.get("column") or None)))
    elif kind == "delete_property":
        p = _need(g, op["iri"])
        if not ((p, RDF.type, OWL.ObjectProperty) in g or (p, RDF.type, OWL.DatatypeProperty) in g):
            raise EditError(f"속성이 아닙니다: {short(p)}")
        _remove_restrictions_on(g, p)
        for t in list(g.triples((p, None, None))) + list(g.triples((None, p, None))) + list(g.triples((None, None, p))):
            g.remove(t)
    elif kind == "add_triple":
        s, p, o = expand(op["s"]), expand(op["p"]), _object(op)
        g.add((s, p, o))
    elif kind == "remove_triple":
        s, p, o = expand(op["s"]), expand(op["p"]), _object(op)
        if (s, p, o) not in g:
            raise EditError("지울 트리플이 온톨로지에 없습니다.")
        g.remove((s, p, o))
    else:
        raise EditError(f"알 수 없는 연산입니다: {kind}")


def apply_ops(g: Graph, ops: list[dict]) -> tuple[Graph, str]:
    """복사본에 연산을 차례로 적용한다. (새 그래프, 되돌리기용 설명)"""
    if not ops:
        raise EditError("연산이 없습니다.")
    out = copy_graph(g)
    for op in ops:
        try:
            apply_op(out, op)
        except KeyError as e:
            raise EditError(f"{op.get('op')}: 인자 {e.args[0]!r}가 없습니다.") from e
    label = _describe(ops[0], g) + (f" 외 {len(ops) - 1}건" if len(ops) > 1 else "")
    return out, label


# ---------------------------------------------------------------- 검사

def check(g: Graph, schema: dict) -> list[dict]:
    """구조 검사. 각 문제는 {level: error|warning, code, iri, message}.

    - 도메인·범위·상위 클래스가 실제로 있는 클래스(또는 자료형)인지
    - 출처(prov:wasDerivedFrom)의 테이블·컬럼이 실제 DB에 있는지
    - 이름 충돌: 같은 IRI가 클래스와 속성, 또는 객체 속성과 데이터 속성으로 동시에 선언됐는지
    - 상위 클래스 순환 (A ⊑ B ⊑ A)
    """
    issues: list[dict] = []
    add = lambda level, code, iri, msg: issues.append({"level": level, "code": code, "iri": str(iri), "message": msg})
    classes = {s for s in g.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)}
    objprops = {s for s in g.subjects(RDF.type, OWL.ObjectProperty) if isinstance(s, URIRef)}
    dataprops = {s for s in g.subjects(RDF.type, OWL.DatatypeProperty) if isinstance(s, URIRef)}
    ont = str(naming.ONT)

    for x in classes & (objprops | dataprops):
        add("error", "name_clash", x, f"{short(x)}가 클래스이면서 속성으로도 선언되어 있습니다.")
    for x in objprops & dataprops:
        add("error", "name_clash", x, f"{short(x)}가 객체 속성이면서 데이터 속성으로도 선언되어 있습니다.")

    for p in sorted(objprops):
        for pred, word in ((RDFS.domain, "도메인"), (RDFS.range, "범위")):
            values = [o for o in g.objects(p, pred) if isinstance(o, URIRef)]
            if not values:
                add("warning", f"missing_{'domain' if pred == RDFS.domain else 'range'}", p, f"{short(p)}에 {word}이 없습니다.")
            for o in values:
                if o not in classes:
                    add("error", "unknown_class", p, f"{short(p)}의 {word} {short(o)}는 온톨로지에 없는 클래스입니다.")
    for p in sorted(dataprops):
        for o in g.objects(p, RDFS.domain):
            if isinstance(o, URIRef) and o not in classes:
                add("error", "unknown_class", p, f"{short(p)}의 도메인 {short(o)}는 온톨로지에 없는 클래스입니다.")
        for o in g.objects(p, RDFS.range):
            if isinstance(o, URIRef) and str(o) not in DATATYPES:
                add("error", "bad_datatype", p, f"{short(p)}의 범위 {short(o)}는 XML Schema 자료형이 아닙니다.")
    for c in sorted(classes):
        for o in g.objects(c, RDFS.subClassOf):
            # 자기 네임스페이스(ont:)의 상위 클래스는 선언되어 있어야 한다. 외부 클래스(예: schema.org)는 허용
            if isinstance(o, URIRef) and str(o).startswith(ont) and o not in classes:
                add("error", "unknown_class", c, f"{short(c)}의 상위 클래스 {short(o)}는 온톨로지에 없는 클래스입니다.")

    # 상위 클래스 순환
    parents = {c: {o for o in g.objects(c, RDFS.subClassOf) if isinstance(o, URIRef)} for c in classes}
    for c in sorted(classes):
        seen, stack = set(), list(parents.get(c, ()))
        while stack:
            x = stack.pop()
            if x == c:
                add("error", "subclass_cycle", c, f"{short(c)}가 자기 자신의 상위 클래스가 됩니다 (순환).")
                break
            if x not in seen:
                seen.add(x)
                stack.extend(parents.get(x, ()))

    # 출처
    tables = {t["name"]: {c["name"] for c in t["columns"]} for t in schema["tables"]}
    for s, o in g.subject_objects(PROV.wasDerivedFrom):
        parsed = naming.parse_provenance(str(o))
        if not parsed:
            continue
        table, column = parsed
        if table not in tables:
            add("error", "unknown_source", s, f"{short(s)}의 출처 테이블 '{table}'이 DB에 없습니다.")
        elif column is not None and column not in tables[table]:
            add("error", "unknown_source", s, f"{short(s)}의 출처 컬럼 '{table}.{column}'이 DB에 없습니다.")
    for x in sorted(classes | objprops | dataprops):
        if str(x).startswith(ont) and (x, PROV.wasDerivedFrom, None) not in g:
            add("warning", "missing_source", x, f"{short(x)}에 출처(prov:wasDerivedFrom)가 없습니다.")
    return issues


def new_errors(before: list[dict], after: list[dict]) -> list[dict]:
    """수정으로 새로 생긴 오류만 (원래 파일에 있던 문제 때문에 수정을 막지 않는다)."""
    key = lambda i: (i["code"], i["iri"], i["message"])
    old = {key(i) for i in before if i["level"] == "error"}
    return [i for i in after if i["level"] == "error" and key(i) not in old]


# ---------------------------------------------------------------- 차이 (diff)

def _rows(g: Graph) -> dict[str, set[tuple[str, str]]]:
    """주어(IRI)마다 (속성, 값) 집합. 빈 노드 값은 읽을 수 있는 식으로 풀어서 비교한다."""
    out: dict[str, set[tuple[str, str]]] = {}
    for s, p, o in g:
        if isinstance(s, URIRef):
            val = f'"{o}"' + (f"@{o.language}" if o.language else "") if isinstance(o, Literal) else render(g, o)
            out.setdefault(str(s), set()).add((short(p), val))
    return out


def diff(base: Graph, current: Graph) -> list[dict]:
    """주어별로 추가·삭제된 (속성, 값). [{iri, name, added: [[p, o]], removed: [[p, o]]}]"""
    a, b = _rows(base), _rows(current)
    out = []
    for iri in sorted(set(a) | set(b)):
        removed = sorted(a.get(iri, set()) - b.get(iri, set()))
        added = sorted(b.get(iri, set()) - a.get(iri, set()))
        if added or removed:
            status = "added" if iri not in a else "removed" if iri not in b else "changed"
            out.append({"iri": iri, "name": short(URIRef(iri)), "status": status,
                        "added": [list(x) for x in added], "removed": [list(x) for x in removed]})
    return out
