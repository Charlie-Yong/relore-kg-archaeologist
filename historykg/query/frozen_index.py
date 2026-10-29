"""A bounded relore replay per frozen dataset, sharing the configured DB instance."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from relore.github.fetch_thread import ThreadPayload
from relore.store import schema
from relore.store.dialect import make_engine
from sqlalchemy import Column, MetaData, String, Table, select, text
from sqlalchemy.engine import make_url

from historykg import collector
from historykg.ids import canonical_json, text_hash
from historykg.io import read_json, write_json

VERSION = "dataset_relore_replay_v1"


def _namespace(dataset: str) -> str:
    return "hg_" + text_hash(dataset)[:32]


def index_url(base_url: str | None, descriptor: dict) -> str:
    if descriptor["backend"] == "sqlite":
        return "sqlite:///" + descriptor["path"]
    if not base_url:
        raise ValueError("冻结Postgres索引需要原配置database_url")
    parsed = make_url(base_url)
    if parsed.get_backend_name() not in {"postgresql", "postgres"}:
        raise ValueError("冻结索引后端与配置不一致")
    # Namespace is computed from dataset_id, never interpolated user SQL.
    namespace = descriptor["namespace"]
    if not namespace.startswith("hg_") or len(namespace) != 35 or any(
        c not in "0123456789abcdef" for c in namespace[3:]
    ):
        raise ValueError("非法冻结索引命名空间")
    return parsed.update_query_dict({
        "options": "-csearch_path=" + namespace + ",public"
    }).render_as_string(hide_password=False)


def _metadata_table(namespace=None):
    return Table("hg_frozen_index", MetaData(), Column("id", String, primary_key=True),
                 Column("record", String, nullable=False), schema=namespace)


def _payloads(package: dict) -> list[ThreadPayload]:
    root = Path(package["dataset_dir"])
    exported = root / "exports" / "relore_input.json"
    if exported.exists():
        payload = read_json(exported)
        if payload.get("dataset_id") != package["manifest"]["dataset_id"]:
            raise ValueError("冻结relore输入属于其他数据集")
        rows = payload["payloads"]
    else:
        capture_path = package["manifest"].get("collection", {}).get("capture_path")
        mapped = [s for s in package["sources"] if s.get("relore_mapping")]
        if capture_path:
            capture = read_json(capture_path)
            if capture.get("format") != collector.CAPTURE:
                raise ValueError("不是P4采集器的冻结capture")
            rows = capture["payloads"]
        elif mapped:
            raise ValueError("讨论来源有映射但缺冻结capture/exports/relore_input.json")
        else:
            # Synthetic/code-only pools have no relore threads; the common adapter is visible.
            rows = []
    payloads = [ThreadPayload(**{**p, "unread": set(p.get("unread", []))}) for p in rows]
    observed = {}
    repo = package["manifest"]["repo"]
    for p in payloads:
        if p.repo.lower() != repo:
            raise ValueError("冻结讨论输入跨仓库")
        for kind, identity, raw in p.raw_objects():
            key = (p.number, "body" if kind in {"issue", "pr"} else kind, str(identity))
            observed[key] = (raw.get("body") or "").replace("\r\n", "\n").replace("\r", "\n")
    expected = {}
    for source in package["sources"]:
        if m := source.get("relore_mapping"):
            key = (int(m["number"]), m["source_type"], str(m["source_id"]))
            if key in expected:
                raise ValueError("同一讨论原对象映射到多个冻结版本")
            expected[key] = source["text"]
    if expected != observed:
        raise ValueError("冻结capture与C5讨论来源池的原对象/文本不一致")
    serialized = [{**dataclasses.asdict(p), "unread": sorted(p.unread)} for p in payloads]
    if not exported.exists():
        write_json(exported, {"version": VERSION, "dataset_id": package["manifest"]["dataset_id"],
                              "payloads": serialized})
    return payloads


def freeze_index(package: dict, base_url: str | None) -> dict:
    """No network. Index exactly the original threads, not the mutable global repo index."""
    dataset = package["manifest"]["dataset_id"]
    root = Path(package["dataset_dir"])
    payloads = _payloads(package)
    input_hash = text_hash(canonical_json([
        {**dataclasses.asdict(p), "unread": sorted(p.unread)} for p in payloads
    ]))
    backend = make_url(base_url).get_backend_name() if base_url else "sqlite"
    descriptor = {"version": VERSION, "namespace": _namespace(dataset),
                  "input_hash": input_hash, "dataset_fingerprint": package["fingerprint"],
                  "backend": "postgresql" if backend in {"postgresql", "postgres"} else "sqlite"}
    if descriptor["backend"] == "sqlite":
        descriptor["path"] = str(root / "exports" / "relore_index.sqlite3")
    else:
        engine = make_engine(base_url)
        try:
            with engine.begin() as conn:
                conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{descriptor["namespace"]}"'))
            # Explicit schema creation prevents public tables satisfying checkfirst on search_path.
            schema.metadata.create_all(engine.execution_options(
                schema_translate_map={None: descriptor["namespace"]}
            ))
        finally:
            engine.dispose()
    scoped = index_url(base_url, descriptor)
    engine = make_engine(scoped)
    metadata = _metadata_table()
    try:
        metadata.create(engine, checkfirst=True)
        with engine.connect() as conn:
            old = conn.execute(select(metadata.c.record).where(metadata.c.id == dataset)).scalar()
        if old:
            if json.loads(old) != descriptor:
                raise ValueError("冻结relore索引输入已改变，不能覆盖同dataset")
            return descriptor
        result = collector.index_threads(payloads, database_url=scoped)
        if result["status"] not in {"ok", "partial", "empty"}:
            raise ValueError("冻结relore索引回放失败：" + str(result.get("error", {}).get("code")))
        with engine.begin() as conn:
            conn.execute(metadata.insert().values(id=dataset, record=canonical_json(descriptor)))
    finally:
        engine.dispose()
    return descriptor


def verify_index(base_url: str | None, descriptor: dict, dataset: str) -> str:
    scoped = index_url(base_url, descriptor)
    engine = make_engine(scoped)
    metadata = _metadata_table()
    try:
        with engine.connect() as conn:
            row = conn.execute(select(metadata.c.record).where(metadata.c.id == dataset)).scalar()
        if not row or json.loads(row) != descriptor:
            raise ValueError("冻结relore索引不存在或版本不一致")
    finally:
        engine.dispose()
    return scoped


def drop_index(base_url: str | None, descriptor: dict):
    """Only for explicitly owned test namespaces, called by tests rather than query."""
    if descriptor["backend"] == "sqlite":
        Path(descriptor["path"]).unlink(missing_ok=True)
        return
    index_url(base_url, descriptor)  # validate deterministic identifier before SQL
    engine = make_engine(base_url)
    try:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{descriptor["namespace"]}" CASCADE'))
    finally:
        engine.dispose()
