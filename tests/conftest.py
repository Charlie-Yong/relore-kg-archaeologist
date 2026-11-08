"""Collector tests use a disposable SQLite file or an explicitly configured test DB."""

import os

import pytest

from historykg.ingest.index import make_engine, metadata


@pytest.fixture(params=["sqlite", "postgresql"])
def database_url(request, tmp_path):
    if request.param == "sqlite":
        yield "sqlite:///" + (tmp_path / "collector.sqlite3").as_posix()
        return
    url = os.environ.get("HISTORYKG_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set HISTORYKG_TEST_POSTGRES_URL for the real PostgreSQL checks")
    engine = make_engine(url)
    try:
        if not (engine.url.database or "").endswith("_test"):
            pytest.fail("Collector tests require a dedicated database whose name ends with _test")
        metadata.drop_all(engine)
    finally:
        engine.dispose()
    yield url
