"""이름 규칙. 생성기, 화면, 에이전트가 모두 이 모듈의 함수로 IRI를 만든다.

RIGOR(https://github.com/NadeenAhmad/RIGOR, MIT License, Copyright (c) 2026 Nadeen Fathallah)의
to_class_name / data_property_name / object_property_name_for_fk 규칙을 그대로 옮겼다.
논문에서 만든 온톨로지(data/paper/*.owl)와 같은 IRI가 나온다.
"""
from __future__ import annotations

import re
from urllib.parse import quote, unquote

from rdflib import Namespace, URIRef

ONTOLOGY_IRI = "http://example.org/ontology"
ONT = Namespace(f"{ONTOLOGY_IRI}#")
PROVENANCE_PREFIX = f"{ONTOLOGY_IRI}/provenance/"


def safe_local_name(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_\-]", "_", str(name).strip())
    return re.sub(r"_+", "_", s) or "Unnamed"


def to_class_name(name: str) -> str:
    parts = re.split(r"[_\s\-]+", str(name).strip())
    return "".join(p[:1].upper() + p[1:] for p in parts if p) or "UnnamedClass"


def humanize_identifier(name: str) -> str:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(name))
    return re.sub(r"\s+", " ", s.replace("_", " ").replace("-", " ")).strip()


def data_property_name(table: str, column: str) -> str:
    """테이블 이름을 앞에 붙여, 여러 테이블에 같은 컬럼 이름이 있어도 충돌하지 않게 한다."""
    return safe_local_name(f"{table}_{column}")


def object_property_name(table: str, column: str, ref_table: str) -> str:
    """외래 키 → 관계 이름. 예: rental.inventory_id → rental_hasInventory"""
    if ref_table == table:  # 자기참조
        return safe_local_name(f"{table}_{column}")
    if column.lower().endswith("id") and column[:-2]:
        return safe_local_name(f"{table}_has{to_class_name(column[:-2])}")
    return safe_local_name(f"{table}_has{to_class_name(ref_table)}")


def class_iri(table: str) -> URIRef:
    return ONT[safe_local_name(to_class_name(table))]


def data_property_iri(table: str, column: str) -> URIRef:
    return ONT[data_property_name(table, column)]


def object_property_iri(table: str, column: str, ref_table: str) -> URIRef:
    return ONT[object_property_name(table, column, ref_table)]


def provenance_iri(table: str, column: str | None = None) -> URIRef:
    """prov:wasDerivedFrom 값. 클래스는 '.../provenance/테이블', 속성은 '.../provenance/테이블/컬럼'."""
    if column is None:
        return URIRef(f"{PROVENANCE_PREFIX}{table}")
    return URIRef(f"{PROVENANCE_PREFIX}{table}/{quote(column)}")


def parse_provenance(iri: str) -> tuple[str, str | None] | None:
    """provenance_iri의 역함수. 출처 IRI가 아니면 None."""
    s = str(iri)
    if not s.startswith(PROVENANCE_PREFIX):
        return None
    table, _, column = s[len(PROVENANCE_PREFIX):].partition("/")
    return unquote(table), (unquote(column) if column else None)


def local_name(iri: str) -> str:
    s = str(iri)
    return s.rsplit("#", 1)[-1] if "#" in s else s.rsplit("/", 1)[-1]
