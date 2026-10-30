"""Real database rebuild checks. Frozen replay never invokes an external model."""

from __future__ import annotations

import argparse
import datetime as dt
import os
import platform
import sys
from pathlib import Path

from neo4j import GraphDatabase
from sqlalchemy import text

from historykg import collector
from historykg.graph import load_dataset
from historykg.io import read_json, validate_dataset, write_json
from historykg.query import prepare_query


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--question", default="cache API timeout")
    args = parser.parse_args(argv)
    database = os.environ["HISTORYKG_PLATFORM_DATABASE_URL"]
    uri = os.environ["HISTORYKG_NEO4J_URI"]
    manifest = read_json(args.dataset / "manifest.json")
    validated = validate_dataset(args.dataset)
    assert validated["status"] == "ok", validated
    initialized = collector.initialize_database(database)
    assert initialized["status"] == "ok", initialized
    engine = collector.make_engine(database)
    with engine.connect() as conn:
        postgres_version = conn.execute(text("select version()")).scalar()
    engine.dispose()
    with GraphDatabase.driver(uri, auth=None) as driver:
        with driver.session() as session:
            neo4j_version = session.run(
                "CALL dbms.components() YIELD versions RETURN versions[0] AS version"
            ).single()["version"]
    config = {
        "database_url": database,
        "neo4j_uri": uri,
        "query_output_root": str(args.out.parent / "queries"),
    }
    first = load_dataset(args.dataset, config=config)
    second = load_dataset(args.dataset, config=config)
    assert first["status"] == second["status"] == "ok", (first, second)
    assert first["graph_ready"] and first["retrieval_ready"]
    assert first["counts"] == second["counts"], (first["counts"], second["counts"])
    prepared = prepare_query(
        {"dataset_id": manifest["dataset_id"], "question": args.question, "kind": "search"},
        config=config,
    )
    rendered = prepared.model_dump(mode="json") if hasattr(prepared, "model_dump") else prepared
    assert rendered["status"] == "ok", rendered
    result = {
        "status": "ok",
        "platform": platform.platform(),
        "python": sys.version,
        "dataset_id": manifest["dataset_id"],
        "synthetic": manifest.get("synthetic", False),
        "mode": "frozen_rebuild_no_external_model",
        "postgres_version": postgres_version,
        "neo4j_version": neo4j_version,
        "validation": validated,
        "first_load": first,
        "second_load": second,
        "prepared_query": rendered,
        "new_model_requests": 0,
        "checked_at": dt.datetime.now(dt.UTC).isoformat(),
    }
    write_json(args.out, result)
    print(
        {
            "status": "ok",
            "platform": result["platform"],
            "synthetic": result["synthetic"],
            "dataset_id": result["dataset_id"],
            "new_model_requests": 0,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
