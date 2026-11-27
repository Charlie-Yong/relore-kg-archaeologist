"""Rebuild a local discussion index per frozen dataset without network access."""

from __future__ import annotations

import dataclasses
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from sqlalchemy import Column, MetaData, String, Table, Text, select, text
from sqlalchemy.engine import make_url

from historykg import collector
from historykg.ids import canonical_json, text_hash
from historykg.ingest.github import ThreadPayload, discussion_mapping
from historykg.ingest.index import make_engine
from historykg.io import read_json, write_json

VERSION = "dataset_discussion_index_v1"


def _namespace(dataset: str) -> str:
    return "hgd_" + text_hash(dataset)[:32]


def index_url(base_url: str | None, descriptor: dict) -> str:
    if descriptor["version"] != VERSION:
        raise ValueError("冻结讨论索引版本已更新，请从原冻结包重新导入（load）。")
    if descriptor["backend"] == "sqlite":
        return "sqlite:///" + descriptor["path"]
    if not base_url:
        raise ValueError("冻结Postgres索引需要原配置database_url")
    parsed = make_url(base_url)
    if parsed.get_backend_name() not in {"postgresql", "postgres"}:
        raise ValueError("冻结索引后端与配置不一致")
    # Namespace is computed from dataset_id, never interpolated user SQL.
    namespace = descriptor["namespace"]
    if not namespace.startswith("hgd_") or len(namespace) != 36 or any(
        c not in "0123456789abcdef" for c in namespace[4:]
    ):
        raise ValueError("非法冻结索引命名空间")
    return parsed.update_query_dict({
        "options": "-csearch_path=" + namespace
    }).render_as_string(hide_password=False)


def _metadata_table():
    return Table("hg_frozen_index", MetaData(), Column("id", String, primary_key=True),
                 Column("record", String, nullable=False))


def _sources_table(metadata=None):
    return Table(
        "hg_frozen_sources",
        metadata or MetaData(),
        Column("source_id", String, primary_key=True),
        Column("repo", String, nullable=False),
        Column("kind", String, nullable=False),
        Column("origin_key", String, nullable=False),
        Column("url", String, nullable=False),
        Column("title", Text),
        Column("author", String),
        Column("occurred_at", String),
        Column("trust_tier", String),
        Column("text_sha256", String, nullable=False),
        Column("text", Text, nullable=False),
        Column("record_json", Text, nullable=False),
    )


def _populate_source_index(scoped_url: str, sources: list[dict]) -> None:
    engine = make_engine(scoped_url)
    try:
        table = _sources_table()
        table.create(engine, checkfirst=True)
        rows = [
            {
                "source_id": s["source_id"],
                "repo": s["repo"],
                "kind": s["kind"],
                "origin_key": s["origin_key"],
                "url": s["url"],
                "title": s.get("title") or "",
                "author": s.get("author"),
                "occurred_at": s.get("occurred_at"),
                "trust_tier": s.get("trust_tier"),
                "text_sha256": s["text_sha256"],
                "text": s["text"],
                "record_json": canonical_json(s),
            }
            for s in sources
        ]
        with engine.begin() as conn:
            conn.execute(table.delete())
            for i in range(0, len(rows), 1000):
                conn.execute(table.insert(), rows[i : i + 1000])
    finally:
        engine.dispose()
    parsed = make_url(scoped_url)
    if parsed.get_backend_name() == "sqlite" and parsed.database:
        with sqlite3.connect(parsed.database) as raw_conn:
            raw_conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS hg_frozen_sources_fts "
                "USING fts5(source_id UNINDEXED, origin_key, title, text, tokenize='trigram')"
            )
            raw_conn.execute("DELETE FROM hg_frozen_sources_fts")
            raw_conn.executemany(
                "INSERT INTO hg_frozen_sources_fts (source_id, origin_key, title, text) "
                "VALUES (?, ?, ?, ?)",
                [
                    (s["source_id"], s["origin_key"], s.get("title") or "", s["text"])
                    for s in sources
                ],
            )
            raw_conn.execute(
                "CREATE TABLE IF NOT EXISTS hg_short_tokens "
                "(token TEXT NOT NULL, source_id TEXT NOT NULL, PRIMARY KEY (token, source_id))"
            )
            raw_conn.execute("DELETE FROM hg_short_tokens")
            short_rows = []
            for s in sources:
                blob = " ".join((s["origin_key"], s.get("title") or "", s["text"])).lower()
                seen_short = set()
                for run in re.findall(r"[\u3400-\u9fff]+", blob):
                    for i in range(max(1, len(run) - 1)):
                        tok = run[i : i + 2]
                        if len(tok) <= 2:
                            seen_short.add(tok)
                for tok in re.findall(r"[a-z_][a-z_0-9]*", blob):
                    if 1 <= len(tok) <= 2:
                        seen_short.add(tok)
                for tok in seen_short:
                    short_rows.append((tok, s["source_id"]))
            raw_conn.executemany(
                "INSERT OR IGNORE INTO hg_short_tokens (token, source_id) VALUES (?, ?)",
                short_rows,
            )
            raw_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_hg_sources_origin ON hg_frozen_sources(origin_key)"
            )
            raw_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_hg_sources_kind ON hg_frozen_sources(kind)"
            )
            raw_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_hg_sources_url ON hg_frozen_sources(url)"
            )
            raw_conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_hg_short_tok ON hg_short_tokens(token)"
            )
            raw_conn.commit()


def has_frozen_sources(scoped_url: str) -> bool:
    parsed = make_url(scoped_url)
    if parsed.get_backend_name() == "sqlite" and parsed.database:
        with sqlite3.connect(parsed.database) as conn:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='hg_frozen_sources'"
            ).fetchone()
            return row is not None
    engine = make_engine(scoped_url)
    try:
        from sqlalchemy import inspect
        return inspect(engine).has_table("hg_frozen_sources")
    finally:
        engine.dispose()


def frozen_source_ids(scoped_url: str) -> list[str]:
    parsed = make_url(scoped_url)
    if parsed.get_backend_name() == "sqlite" and parsed.database:
        with sqlite3.connect(parsed.database) as conn:
            return [
                r[0]
                for r in conn.execute(
                    "SELECT source_id FROM hg_frozen_sources ORDER BY source_id"
                )
            ]
    engine = make_engine(scoped_url)
    table = _sources_table()
    try:
        with engine.connect() as conn:
            return [
                r[0]
                for r in conn.execute(select(table.c.source_id).order_by(table.c.source_id))
            ]
    finally:
        engine.dispose()


def fetch_frozen_sources(
    scoped_url: str,
    *,
    ids: list[str] | None = None,
    kinds: list[str] | None = None,
    url_prefixes: list[str] | None = None,
    origin_keys: list[str] | None = None,
) -> list[dict]:
    parsed = make_url(scoped_url)
    if parsed.get_backend_name() == "sqlite" and parsed.database:
        with sqlite3.connect(parsed.database) as conn:
            if ids is not None:
                if not ids:
                    return []
                unique = sorted(set(ids))
                out = []
                for i in range(0, len(unique), 500):
                    chunk = unique[i : i + 500]
                    marks = ",".join("?" for _ in chunk)
                    out.extend(
                        json.loads(r[0])
                        for r in conn.execute(
                            f"SELECT record_json FROM hg_frozen_sources "
                            f"WHERE source_id IN ({marks})",
                            chunk,
                        )
                    )
                return out
            if origin_keys is not None:
                if not origin_keys:
                    return []
                unique = sorted(set(origin_keys))
                out = []
                for i in range(0, len(unique), 500):
                    chunk = unique[i : i + 500]
                    marks = ",".join("?" for _ in chunk)
                    out.extend(
                        json.loads(r[0])
                        for r in conn.execute(
                            f"SELECT record_json FROM hg_frozen_sources "
                            f"WHERE origin_key IN ({marks})",
                            chunk,
                        )
                    )
                return out
            if kinds is not None:
                if not kinds:
                    return []
                marks = ",".join("?" for _ in kinds)
                return [
                    json.loads(r[0])
                    for r in conn.execute(
                        f"SELECT record_json FROM hg_frozen_sources WHERE kind IN ({marks})",
                        list(kinds),
                    )
                ]
            if url_prefixes is not None:
                if not url_prefixes:
                    return []
                cond = " OR ".join("url LIKE ?" for _ in url_prefixes)
                return [
                    json.loads(r[0])
                    for r in conn.execute(
                        f"SELECT record_json FROM hg_frozen_sources WHERE {cond}",
                        [p + "%" for p in url_prefixes],
                    )
                ]
            return [
                json.loads(r[0])
                for r in conn.execute(
                    "SELECT record_json FROM hg_frozen_sources ORDER BY source_id"
                )
            ]
    engine = make_engine(scoped_url)
    table = _sources_table()
    try:
        stmt = select(table.c.record_json)
        if ids is not None:
            if not ids:
                return []
            stmt = stmt.where(table.c.source_id.in_(sorted(set(ids))))
        elif origin_keys is not None:
            if not origin_keys:
                return []
            stmt = stmt.where(table.c.origin_key.in_(sorted(set(origin_keys))))
        elif kinds is not None:
            if not kinds:
                return []
            stmt = stmt.where(table.c.kind.in_(list(kinds)))
        with engine.connect() as conn:
            return [json.loads(r[0]) for r in conn.execute(stmt)]
    finally:
        engine.dispose()


def fetch_git_diff_sources(scoped_url: str, shas: list[str]) -> list[dict]:
    """Fetch git_output diff-tree sources for specific commit SHAs using FTS5 trigram lookup."""
    clean = sorted({s.lower() for s in shas if isinstance(s, str) and len(s) >= 7})
    if not clean:
        return []
    parsed = make_url(scoped_url)
    if parsed.get_backend_name() == "sqlite" and parsed.database:
        with sqlite3.connect(parsed.database) as conn:
            has_fts = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='hg_frozen_sources_fts'"
            ).fetchone()
            if has_fts:
                matched_ids: set[str] = set()
                for sha in clean:
                    rows = conn.execute(
                        "SELECT source_id FROM hg_frozen_sources_fts "
                        "WHERE hg_frozen_sources_fts MATCH ?",
                        ('"' + sha.replace('"', '""') + '"',),
                    ).fetchall()
                    matched_ids.update(r[0] for r in rows)
                if not matched_ids:
                    return []
                ordered = sorted(matched_ids)
                out: list[dict] = []
                for i in range(0, len(ordered), 500):
                    chunk = ordered[i : i + 500]
                    marks = ",".join("?" for _ in chunk)
                    out.extend(
                        json.loads(r[0])
                        for r in conn.execute(
                            f"SELECT record_json FROM hg_frozen_sources "
                            f"WHERE kind='git_output' AND source_id IN ({marks})",
                            chunk,
                        )
                    )
                return out
    return fetch_frozen_sources(scoped_url, kinds=["git_output"])


def lexical_candidate_sources(
    scoped_url: str, terms: set[str], *, max_candidates: int = 250
) -> list[dict]:
    """Return top frozen sources ranked by distinct term hit count via FTS5 + short index."""
    if not terms:
        return []
    parsed = make_url(scoped_url)
    if parsed.get_backend_name() != "sqlite" or not parsed.database:
        return fetch_frozen_sources(scoped_url)
    with sqlite3.connect(parsed.database) as conn:
        total = conn.execute("SELECT COUNT(*) FROM hg_frozen_sources").fetchone()[0]
        if total <= 500:
            return [
                json.loads(r[0])
                for r in conn.execute(
                    "SELECT record_json FROM hg_frozen_sources ORDER BY source_id"
                )
            ]
        hit_counts: Counter[str] = Counter()
        for term in sorted(terms):
            if len(term) >= 3:
                escaped = '"' + term.replace('"', '""') + '"'
                try:
                    rows = conn.execute(
                        "SELECT source_id FROM hg_frozen_sources_fts "
                        "WHERE hg_frozen_sources_fts MATCH ?",
                        (escaped,),
                    ).fetchall()
                    for r in rows:
                        hit_counts[r[0]] += 1
                    continue
                except sqlite3.OperationalError:
                    pass
            if not term.isdigit():
                rows = conn.execute(
                    "SELECT source_id FROM hg_short_tokens WHERE token = ?", (term,)
                ).fetchall()
                for r in rows:
                    hit_counts[r[0]] += 1
        if not hit_counts:
            # Fallback if query contains only numeric digits (e.g., "372") or punctuation
            for term in sorted(terms):
                if term.isdigit() and len(term) >= 2:
                    rows = conn.execute(
                        "SELECT source_id FROM hg_frozen_sources "
                        "WHERE instr(text, ?) > 0 OR instr(origin_key, ?) > 0 "
                        "OR instr(title, ?) > 0",
                        (term, term, term),
                    ).fetchall()
                    for r in rows:
                        hit_counts[r[0]] += 1
        if not hit_counts:
            return []
        top_ids = [
            sid
            for sid, _ in sorted(hit_counts.items(), key=lambda x: (-x[1], x[0]))[:max_candidates]
        ]
        return fetch_frozen_sources(scoped_url, ids=top_ids)


def _payloads(package: dict) -> list[ThreadPayload]:
    root = Path(package["dataset_dir"])
    exported = root / "exports" / "discussion_input.json"
    legacy = root / "exports" / "relore_input.json"
    source_file = next((path for path in (exported, legacy) if path.exists()), None)
    if source_file:
        payload = read_json(source_file)
        if payload.get("dataset_id") != package["manifest"]["dataset_id"]:
            raise ValueError("冻结讨论输入属于其他数据集")
        rows = payload["payloads"]
    else:
        capture_path = package["manifest"].get("collection", {}).get("capture_path")
        if capture_path:
            capture = read_json(capture_path)
            if capture.get("format") != collector.CAPTURE:
                raise ValueError("不是P4采集器的冻结capture")
            rows = capture["payloads"]
        elif any(discussion_mapping(s) for s in package["sources"]):
            raise ValueError("讨论来源有映射但缺冻结 capture 或导出输入")
        else:
            # Synthetic/code-only pools have no discussion threads.
            rows = []
    payloads = [ThreadPayload.from_capture(row) for row in rows]
    observed = {}
    repo = package["manifest"]["repo"]
    for p in payloads:
        if p.repo.lower() != repo:
            raise ValueError("冻结讨论输入跨仓库")
        for kind, identity, raw in p.objects():
            key = (p.number, kind, identity)
            if key in observed:
                raise ValueError("冻结讨论输入包含重复原对象")
            observed[key] = (raw.get("body") or "").replace("\r\n", "\n").replace("\r", "\n")
    expected = {}
    for source in package["sources"]:
        if m := discussion_mapping(source):
            key = (int(m["number"]), m["source_type"], str(m["source_id"]))
            if key in expected:
                raise ValueError("同一讨论原对象映射到多个冻结版本")
            expected[key] = source["text"]
    if expected != observed:
        raise ValueError("冻结capture与C5讨论来源池的原对象/文本不一致")
    serialized = [{**dataclasses.asdict(p), "unread": sorted(p.unread)} for p in payloads]
    if source_file is None:
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
        descriptor["path"] = str(root / "exports" / "discussion_index.sqlite3")
    else:
        engine = make_engine(base_url)
        try:
            with engine.begin() as conn:
                conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{descriptor["namespace"]}"'))
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
                raise ValueError("冻结讨论索引输入已改变，不能覆盖同dataset")
            if not has_frozen_sources(scoped):
                _populate_source_index(scoped, package["sources"])
            return descriptor
        result = collector.index_threads(payloads, database_url=scoped)
        if result["status"] not in {"ok", "partial", "empty"}:
            raise ValueError("冻结讨论索引回放失败：" + str(result.get("error", {}).get("code")))
        _populate_source_index(scoped, package["sources"])
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
            raise ValueError("冻结讨论索引不存在或版本不一致")
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
