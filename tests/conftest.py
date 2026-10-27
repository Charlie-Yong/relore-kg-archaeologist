"""Collector tests use a disposable SQLite file or an explicitly configured test DB."""

import os
import sys
from pathlib import Path

import pytest
from relore.store import schema
from relore.store.dialect import make_engine
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor/relore/tests/fixtures"))


@pytest.fixture(params=["sqlite", "postgresql"])
def database_url(request, tmp_path):
    if request.param == "sqlite":
        yield "sqlite:///" + (tmp_path / "collector.sqlite3").as_posix()
        return
    url = os.environ.get("RELORE_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set RELORE_TEST_POSTGRES_URL for the real PostgreSQL checks")
    engine = make_engine(url)
    if not (engine.url.database or "").endswith("_test"):
        engine.dispose()
        pytest.fail("Collector tests require a dedicated database whose name ends with _test")
    with engine.begin() as conn:
        for table in reversed(schema.metadata.sorted_tables):
            conn.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))
    engine.dispose()
    yield url
