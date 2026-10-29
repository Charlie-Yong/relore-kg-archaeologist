"""One frozen dataset per namespace; no target repository code is executed."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

from historykg import collector
from historykg.contracts import RELATION_ENDPOINTS
from historykg.ids import canonical_json, text_hash
from historykg.io import collect_records, merge_records, read_json, validate_dataset


def settings(config: dict | None) -> dict:
    values = dict(config or {})
    values.update(values.pop("graph", {}) or {})
    return values


class GraphStore:
    """All IDs, lookups and traversals include dataset_id, including Source endpoints."""

    def __init__(self, config: dict | None = None):
        self.config = settings(config)
        uri = self.config.get("neo4j_uri") or os.environ.get("HISTORYKG_NEO4J_URI")
        if not uri:
            raise ValueError("请配置neo4j_uri或HISTORYKG_NEO4J_URI")
        user = self.config.get("neo4j_user") or os.environ.get("HISTORYKG_NEO4J_USER")
        password = self.config.get("neo4j_password") or os.environ.get("HISTORYKG_NEO4J_PASSWORD")
        self.driver = GraphDatabase.driver(
            uri,
            auth=(user, password) if user else None,
            connection_timeout=3,
            connection_acquisition_timeout=5,
            max_transaction_retry_time=0,
        )
        self.database = self.config.get("neo4j_database", "neo4j")

    def __enter__(self):
        try:
            self.driver.verify_connectivity()
        except Exception:
            self.driver.close()
            raise
        return self

    def __exit__(self, *_):
        self.driver.close()

    def run(self, cypher: str, **params) -> list[dict]:
        with self.driver.session(database=self.database) as session:
            return session.execute_read(lambda tx: tx.run(cypher, **params).data())

    def ensure_schema(self):
        with self.driver.session(database=self.database) as session:
            for label, key in (("HGDataset", "dataset_id"),):
                session.run(
                    f"CREATE CONSTRAINT hg_dataset IF NOT EXISTS "
                    f"FOR (n:{label}) REQUIRE n.{key} IS UNIQUE"
                ).consume()
            for label in ("HGRecord", "HGEvidence"):
                session.run(
                    f"CREATE CONSTRAINT {label.lower()}_identity IF NOT EXISTS "
                    f"FOR (n:{label}) REQUIRE (n.dataset_id, n.id) IS UNIQUE"
                ).consume()

    def write(self, package: dict):
        self.ensure_schema()
        dataset = package["manifest"]["dataset_id"]

        def transaction(tx):
            old = tx.run(
                "MERGE (d:HGDataset {dataset_id:$dataset}) "
                "SET d.dataset_id=$dataset "
                "RETURN d.fingerprint AS fingerprint",
                dataset=dataset,
            ).single()
            if old["fingerprint"] and old["fingerprint"] != package["fingerprint"]:
                raise ValueError("同一dataset_id已冻结为其他内容，请建立新数据版本")
            for pool, label, key in (
                ("sources", "HGSource", "source_id"),
                ("entities", "HGEntity", "id"),
                ("evidence", "HGEvidence", "evidence_id"),
            ):
                rows = [
                    {"id": r[key], "record": canonical_json(r), "kind": r.get("type", pool)}
                    for r in package[pool]
                ]
                base = "HGRecord:" if pool != "evidence" else ""
                tx.run(
                    f"UNWIND $rows AS row MERGE (n:{base}{label} "
                    "{dataset_id:$dataset,id:row.id}) "
                    "SET n.record=row.record,n.kind=row.kind",
                    rows=rows,
                    dataset=dataset,
                ).consume()
            # Type names come only from the contract allowlist, never user Cypher.
            for kind in RELATION_ENDPOINTS:
                rows = [
                    {**r, "record": canonical_json(r)}
                    for r in package["relations"] if r["type"] == kind
                ]
                tx.run(
                    "UNWIND $rows AS row "
                    "MATCH (a:HGRecord {dataset_id:$dataset,id:row.from_id}), "
                    "(b:HGRecord {dataset_id:$dataset,id:row.to_id}) "
                    f"MERGE (a)-[r:{kind} {{dataset_id:$dataset,id:row.id}}]->(b) "
                    "SET r.record=row.record",
                    rows=rows,
                    dataset=dataset,
                ).consume()
            tx.run(
                "MATCH (d:HGDataset {dataset_id:$dataset}) "
                "SET d.fingerprint=$fingerprint,d.manifest=$manifest,"
                "d.subjects=$subjects,d.dataset_dir=$dataset_dir,d.ready=true",
                dataset=dataset,
                fingerprint=package["fingerprint"],
                manifest=canonical_json(package["manifest"]),
                subjects=canonical_json(package["subjects"]),
                dataset_dir=package["dataset_dir"],
            ).consume()

        with self.driver.session(database=self.database) as session:
            session.execute_write(transaction)

    def snapshot(self, dataset: str) -> dict | None:
        rows = self.run(
            "MATCH (d:HGDataset {dataset_id:$dataset,ready:true}) RETURN properties(d) AS d",
            dataset=dataset,
        )
        if not rows:
            return None
        meta = rows[0]["d"]
        result = {
            "manifest": json.loads(meta["manifest"]),
            "subjects": json.loads(meta["subjects"]),
            "dataset_dir": meta["dataset_dir"],
            "fingerprint": meta["fingerprint"],
        }
        for pool, label in (("sources", "HGSource"), ("entities", "HGEntity"),
                            ("evidence", "HGEvidence")):
            result[pool] = [json.loads(r["record"]) for r in self.run(
                f"MATCH (n:{label} {{dataset_id:$dataset}}) "
                "RETURN n.record AS record ORDER BY n.id",
                dataset=dataset,
            )]
        result["relations"] = [json.loads(r["record"]) for r in self.run(
            "MATCH (a:HGRecord {dataset_id:$dataset})-[r]->"
            "(b:HGRecord {dataset_id:$dataset}) WHERE r.dataset_id=$dataset "
            "RETURN r.record AS record ORDER BY r.id", dataset=dataset,
        )]
        if fingerprint(result) != meta["fingerprint"]:
            raise ValueError("图库冻结内容校验失败，须从原数据包重建")
        return result

    def paths(self, dataset: str, seed_ids: list[str], *, depth: int = 3,
              limit: int = 50, kinds: list[str] | None = None) -> list[dict]:
        depth, limit = max(1, min(int(depth), 4)), max(1, min(int(limit), 100))
        allowed = set(kinds or RELATION_ENDPOINTS) & RELATION_ENDPOINTS.keys()
        if not allowed or not seed_ids:
            return []
        relationship_types = "|".join(sorted(allowed))
        rows = self.run(
            "MATCH (s:HGRecord {dataset_id:$dataset}) WHERE s.id IN $seeds "
            f"MATCH p=(s)-[:{relationship_types}*1..{depth}]-(t:HGRecord) "
            "WHERE all(n IN nodes(p) WHERE n.dataset_id=$dataset) "
            "AND all(r IN relationships(p) WHERE r.dataset_id=$dataset) "
            "AND all(n IN nodes(p) WHERE single(m IN nodes(p) WHERE m=n)) "
            "RETURN [n IN nodes(p)|n.id] AS entity_ids, "
            "[r IN relationships(p)|r.id] AS relation_ids "
            "ORDER BY size(relation_ids),relation_ids,entity_ids LIMIT $limit",
            dataset=dataset, seeds=sorted(set(seed_ids)), limit=limit,
        )
        # One physical path may be found from both ends; preserve its first stable orientation.
        unique = {}
        for row in rows:
            key = min(tuple(row["relation_ids"]), tuple(reversed(row["relation_ids"])))
            unique.setdefault(key, row)
        return list(unique.values())

    def delete_dataset(self, dataset: str):
        """Explicit namespace cleanup for test/rebuild tooling; never a whole-database delete."""
        with self.driver.session(database=self.database) as session:
            session.execute_write(lambda tx: tx.run(
                "MATCH (n) WHERE n.dataset_id=$dataset DETACH DELETE n", dataset=dataset
            ).consume())


def fingerprint(package: dict) -> str:
    return text_hash(canonical_json({
        key: package[key] for key in ("manifest", "subjects", "sources", "entities",
                                      "evidence", "relations")
    }))


def read_package(dataset_dir: str | Path) -> dict:
    root = Path(dataset_dir).resolve()
    manifest = read_json(root / "manifest.json")
    if not manifest.get("dataset_id") or not manifest.get("repo"):
        raise ValueError("manifest缺dataset_id或repo")
    result = {"manifest": manifest, "dataset_dir": str(root)}
    for name, key, shards in (
        ("sources", "source_id", False), ("entities", "id", True),
        ("relations", "id", True), ("evidence", "evidence_id", True),
        ("subjects", "subject_id", False),
    ):
        result[name] = merge_records(collect_records(root, name + ".jsonl", shards=shards), key) \
            if name != "subjects" else sorted(
                collect_records(root, name + ".jsonl", shards=False), key=lambda r: r[key]
            )
    visible = [{k: s[k] for k in ("source_id", "kind", "url", "text_sha256", "origin_key")}
               for s in result["sources"]]
    if sorted(manifest.get("sources", []), key=lambda r: r["source_id"]) != visible:
        raise ValueError("manifest可见来源清单与冻结来源不一致")
    result["fingerprint"] = fingerprint(result)
    return result


def load_dataset(dataset_dir: str | Path, *, config: dict | None = None, **_kwargs: Any) -> dict:
    """Validate before writing. P1 publishes only when both readiness flags are true."""
    result = dict(dataset_id=None, status="error", graph_ready=False, retrieval_ready=False,
                  rejected=[], counts={}, error=None)
    try:
        report = validate_dataset(dataset_dir)
        result.update(dataset_id=report["dataset_id"], counts=report["counts"])
        if report["status"] != "ok":
            result["rejected"] = report["errors"]
            result["error"] = {"code": "invalid_dataset", "message": "数据校验未通过"}
            return result
        package = read_package(dataset_dir)
        # Doctor validates the real relore backend; supplementary texts share the frozen pool.
        cfg = settings(config)
        retrieval = collector.doctor(database_url=cfg.get("database_url"))
        if retrieval.get("status") != "ok" or not retrieval.get("schema_ready"):
            result["error"] = {"code": "retrieval_unavailable", "details": retrieval}
            return result
        with GraphStore(cfg) as store:
            store.write(package)
            stored = store.snapshot(result["dataset_id"])
            if stored is None or stored["fingerprint"] != package["fingerprint"]:
                raise ValueError("图库/共同来源池读回不一致")
        result.update(status="ok", graph_ready=True, retrieval_ready=True,
                      fingerprint=package["fingerprint"],
                      retrieval_backend={"discussion": "relore.search_history",
                                         "common_sources": "fixed_lexical_rrf_v1",
                                         "visible_source_ids": [s["source_id"]
                                                                for s in package["sources"]]})
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["rejected"].append(str(exc))
        result["error"] = {"code": "dataset_or_configuration", "type": type(exc).__name__,
                           "message": str(exc)}
    except Exception as exc:
        # Driver messages can carry credentials; publish type, retain no connection string.
        result["error"] = {"code": "storage_error", "type": type(exc).__name__,
                           "message": "图或检索服务操作失败"}
    return result
