"""테스트용 DB 준비: data/dumps 의 두 덤프를 불러오고, 테스트가 직접 불러온 것은 끝나면 지운다.

PostgreSQL이 떠 있지 않으면 DB가 필요한 테스트는 건너뛴다.
"""
import pytest

from backend.paths import DATA

SAMPLES = ("movie_3", "synthea")


@pytest.fixture(scope="session", autouse=True)
def sample_dbs():
    from backend.db import importer

    try:
        existing = {d["name"] for d in importer.list_databases()}
    except Exception:  # noqa: BLE001 - DB가 없으면 각 테스트가 스스로 건너뛴다
        yield
        return
    created = []
    for name in SAMPLES:
        if name not in existing:
            importer.import_file(DATA / "dumps" / f"{name}.dump", f"{name}.dump")
            created.append(name)
    yield
    for name in created:
        importer.drop_database(name)
