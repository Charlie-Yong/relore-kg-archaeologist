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
from historykg.ingest.index import SEARCH_BACKEND, SEARCH_METHOD
from historykg.io import collect_records, merge_records, read_json, validate_dataset


def settings(config: dict | None) -> dict:
    values = dict(config or {})
    values.update(values.pop("graph", {}) or {})
    return values


def _chunks(rows: list[dict], size: int = 1000):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _entity_scalars(record: dict, ev_to_src: dict[str, str] | None = None) -> dict:
    props = record.get("properties") or {}
    number = props.get("number")
    if isinstance(number, bool) or not isinstance(number, int):
        number = None
    src_map = ev_to_src or {}
    source_ids = sorted(
        {src_map[eid] for eid in record.get("evidence_ids", []) if eid in src_map}
    )
    search_text = None
    if record.get("type") in {"Developer", "Function"}:
        parts = [
            props.get("login"),
            props.get("display_name"),
            props.get("name"),
            props.get("qualified_name"),
            props.get("path"),
        ]
        if isinstance(props.get("logins"), list):
            parts.extend(props["logins"])
        cleaned = [
            str(p).lower()
            for p in parts
            if isinstance(p, (str, int)) and not isinstance(p, bool) and p
        ]
        if cleaned:
            search_text = " ".join(dict.fromkeys(cleaned))
    return {
        "id": record["id"],
        "record": canonical_json(record),
        "kind": record.get("type", "entities"),
        "number": number,
        "tag": props.get("tag") if isinstance(props.get("tag"), str) else None,
        "sha": (props.get("sha") or props.get("commit_sha"))
        if isinstance(props.get("sha") or props.get("commit_sha"), str)
        else None,
        "path": props.get("path") if isinstance(props.get("path"), str) else None,
        "decision_status": props.get("status")
        if record.get("type") == "Decision"
        else None,
        "decision_action": props.get("action")
        if record.get("type") == "Decision"
        else None,
        "source_ids": source_ids,
        "search_text": search_text,
    }


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
            for label in ("HGRecord", "HGEvidence", "HGDeveloper", "HGFunction"):
                session.run(
                    f"CREATE CONSTRAINT {label.lower()}_identity IF NOT EXISTS "
                    f"FOR (n:{label}) REQUIRE (n.dataset_id, n.id) IS UNIQUE"
                ).consume()
            for name, label, cols in (
                ("hg_entity_kind", "HGEntity", "n.dataset_id, n.kind"),
                ("hg_entity_number", "HGEntity", "n.dataset_id, n.kind, n.number"),
                ("hg_entity_tag", "HGEntity", "n.dataset_id, n.kind, n.tag"),
                ("hg_entity_sha", "HGEntity", "n.dataset_id, n.kind, n.sha"),
                ("hg_entity_path", "HGEntity", "n.dataset_id, n.kind, n.path"),
                ("hg_source_kind", "HGSource", "n.dataset_id, n.kind"),
                ("hg_source_url", "HGSource", "n.dataset_id, n.url"),
            ):
                session.run(
                    f"CREATE INDEX {name} IF NOT EXISTS FOR (n:{label}) ON ({cols})"
                ).consume()

    def write(
        self,
        package: dict,
        *,
        allow_evolve: bool = False,
        ev_to_src: dict[str, str] | None = None,
        relation_types: list[str] | None = None,
    ):
        self.ensure_schema()
        dataset = package["manifest"]["dataset_id"]
        src_map = (
            ev_to_src
            if ev_to_src is not None
            else {e["evidence_id"]: e["source_id"] for e in package["evidence"]}
        )
        rel_types = (
            relation_types
            if relation_types is not None
            else sorted({r["type"] for r in package["relations"]})
        )

        def _check_and_prepare(tx):
            old = tx.run(
                "MERGE (d:HGDataset {dataset_id:$dataset}) "
                "SET d.dataset_id=$dataset "
                "RETURN d.fingerprint AS fingerprint",
                dataset=dataset,
            ).single()
            if (
                old["fingerprint"]
                and old["fingerprint"] != package["fingerprint"]
                and not allow_evolve
            ):
                raise ValueError("同一dataset_id已冻结为其他内容，请建立新数据版本")
            tx.run(
                "MATCH (d:HGDataset {dataset_id:$dataset}) SET d.ready=false",
                dataset=dataset,
            ).consume()

        def _exec_batches(session, cypher: str, rows: list[dict], *, size: int = 1000, **extra):
            for batch in _chunks(rows, size):
                session.execute_write(
                    lambda tx, b=batch: tx.run(
                        cypher, rows=b, dataset=dataset, **extra
                    ).consume()
                )

        source_rows = [
            {
                "id": r["source_id"],
                "record": canonical_json(r),
                "kind": r.get("kind", "sources"),
                "url": r.get("url"),
                "occurred_at": r.get("occurred_at"),
            }
            for r in package["sources"]
        ]
        entity_rows = [_entity_scalars(r, src_map) for r in package["entities"]]
        evidence_rows = [
            {"id": r["evidence_id"], "record": canonical_json(r), "kind": "evidence"}
            for r in package["evidence"]
        ]

        with self.driver.session(database=self.database) as session:
            session.execute_write(_check_and_prepare)
            _exec_batches(
                session,
                "UNWIND $rows AS row MERGE (n:HGRecord:HGSource "
                "{dataset_id:$dataset,id:row.id}) "
                "SET n.record=row.record,n.kind=row.kind,"
                "n.url=row.url,n.occurred_at=row.occurred_at",
                source_rows,
                size=500,
            )
            _exec_batches(
                session,
                "UNWIND $rows AS row MERGE (n:HGRecord:HGEntity "
                "{dataset_id:$dataset,id:row.id}) "
                "SET n.record=row.record,n.kind=row.kind,"
                "n.number=row.number,n.tag=row.tag,"
                "n.sha=row.sha,n.path=row.path,"
                "n.decision_status=row.decision_status,"
                "n.decision_action=row.decision_action,"
                "n.source_ids=row.source_ids,n.search_text=row.search_text",
                entity_rows,
                size=1000,
            )
            _exec_batches(
                session,
                "UNWIND $rows AS row MERGE (n:HGEvidence "
                "{dataset_id:$dataset,id:row.id}) "
                "SET n.record=row.record,n.kind=row.kind",
                evidence_rows,
                size=1000,
            )
            for kind, label in (("Developer", "HGDeveloper"), ("Function", "HGFunction")):
                rows = [{"id": r["id"]} for r in package["entities"] if r["type"] == kind]
                _exec_batches(
                    session,
                    "UNWIND $rows AS row "
                    "MATCH (n:HGRecord {dataset_id:$dataset,id:row.id}) "
                    f"SET n:{label}",
                    rows,
                    size=1000,
                )
            # Type names come only from the contract allowlist, never user Cypher.
            for kind in RELATION_ENDPOINTS:
                rows = [
                    {**r, "record": canonical_json(r)}
                    for r in package["relations"] if r["type"] == kind
                ]
                _exec_batches(
                    session,
                    "UNWIND $rows AS row "
                    "MATCH (a:HGRecord {dataset_id:$dataset,id:row.from_id}), "
                    "(b:HGRecord {dataset_id:$dataset,id:row.to_id}) "
                    f"MERGE (a)-[r:{kind} {{dataset_id:$dataset,id:row.id}}]->(b) "
                    "SET r.record=row.record,r.occurred_at=row.occurred_at,r.rel_type=row.type",
                    rows,
                    size=1000,
                )
            session.execute_write(
                lambda tx: tx.run(
                    "MATCH (d:HGDataset {dataset_id:$dataset}) "
                    "SET d.fingerprint=$fingerprint,d.manifest=$manifest,"
                    "d.subjects=$subjects,d.dataset_dir=$dataset_dir,"
                    "d.retrieval_index=$retrieval_index,d.relation_types=$relation_types,d.ready=true",
                    dataset=dataset,
                    fingerprint=package["fingerprint"],
                    manifest=canonical_json(package["manifest"]),
                    subjects=canonical_json(package["subjects"]),
                    dataset_dir=package["dataset_dir"],
                    retrieval_index=canonical_json(package.get("retrieval_index")),
                    relation_types=rel_types,
                ).consume()
            )

    def apply_delta(self, dataset: str, prev_package: dict, next_package: dict) -> dict:
        """Incrementally upsert only new or modified records into an evolving dataset."""
        self.ensure_schema()
        delta_sources = {
            s["source_id"]: s for s in next_package["sources"]
        }
        prev_sources = {s["source_id"]: s for s in prev_package["sources"]}
        new_sources = [s for sid, s in delta_sources.items() if prev_sources.get(sid) != s]

        prev_entities = {e["id"]: e for e in prev_package["entities"]}
        new_entities = [e for e in next_package["entities"] if prev_entities.get(e["id"]) != e]

        prev_ev = {e["evidence_id"]: e for e in prev_package["evidence"]}
        new_ev = [e for e in next_package["evidence"] if prev_ev.get(e["evidence_id"]) != e]

        prev_rels = {r["id"]: r for r in prev_package["relations"]}
        new_rels = [r for r in next_package["relations"] if prev_rels.get(r["id"]) != r]

        removed_entities = sorted(
            prev_entities.keys() - {e["id"] for e in next_package["entities"]}
        )
        removed_sources = sorted(prev_sources.keys() - delta_sources.keys())
        removed_evidence = sorted(
            prev_ev.keys() - {e["evidence_id"] for e in next_package["evidence"]}
        )
        removed_rels = sorted(prev_rels.keys() - {r["id"] for r in next_package["relations"]})
        if removed_entities or removed_sources or removed_evidence or removed_rels:
            with self.driver.session(database=self.database) as session:
                def _cleanup(tx):
                    for batch in _chunks([{"id": x} for x in removed_rels]):
                        tx.run(
                            "MATCH ()-[r]->() WHERE r.dataset_id=$dataset "
                            "AND r.id IN [x IN $batch | x.id] DELETE r",
                            dataset=dataset, batch=batch,
                        ).consume()
                    removed_recs = sorted(set(removed_entities) | set(removed_sources))
                    for batch in _chunks([{"id": x} for x in removed_recs]):
                        tx.run(
                            "MATCH (n:HGRecord {dataset_id:$dataset}) "
                            "WHERE n.id IN [x IN $batch | x.id] DETACH DELETE n",
                            dataset=dataset, batch=batch,
                        ).consume()
                    for batch in _chunks([{"id": x} for x in removed_evidence]):
                        tx.run(
                            "MATCH (n:HGEvidence {dataset_id:$dataset}) "
                            "WHERE n.id IN [x IN $batch | x.id] DELETE n",
                            dataset=dataset, batch=batch,
                        ).consume()
                session.execute_write(_cleanup)

        target_full = {
            **next_package,
            "manifest": {**next_package["manifest"], "dataset_id": dataset},
        }
        delta_pkg = {
            **target_full,
            "fingerprint": fingerprint(target_full),
            "sources": new_sources,
            "entities": new_entities,
            "evidence": new_ev,
            "relations": new_rels,
        }
        self.write(
            delta_pkg,
            allow_evolve=True,
            ev_to_src={e["evidence_id"]: e["source_id"] for e in next_package["evidence"]},
            relation_types=sorted({r["type"] for r in next_package["relations"]}),
        )
        return {
            "sources_upserted": len(new_sources),
            "entities_upserted": len(new_entities),
            "evidence_upserted": len(new_ev),
            "relations_upserted": len(new_rels),
            "fingerprint": target_full["fingerprint"],
        }

    def dataset_meta(self, dataset: str) -> dict | None:
        rows = self.run(
            "MATCH (d:HGDataset {dataset_id:$dataset,ready:true}) RETURN properties(d) AS d",
            dataset=dataset,
        )
        if not rows:
            return None
        meta = rows[0]["d"]
        return {
            "manifest": json.loads(meta["manifest"]),
            "subjects": json.loads(meta["subjects"]),
            "dataset_dir": meta["dataset_dir"],
            "fingerprint": meta["fingerprint"],
            "retrieval_index": json.loads(meta["retrieval_index"])
            if meta.get("retrieval_index") else None,
            "relation_types": meta.get("relation_types"),
        }

    def fetch_extended_subjects(
        self, dataset: str, query_tokens: list[str], *, limit: int = 50
    ) -> list[dict]:
        tokens = sorted({t.lower() for t in query_tokens if len(t) >= 2})
        if not tokens:
            return []
        rows = self.run(
            "MATCH (n:HGEntity {dataset_id:$dataset}) "
            "WHERE n.kind IN ['Developer', 'Function'] "
            "AND any(tok IN $tokens WHERE toLower(coalesce(n.search_text, n.record)) CONTAINS tok) "
            "RETURN n.record AS record ORDER BY n.id LIMIT $limit",
            dataset=dataset,
            tokens=tokens,
            limit=limit,
        )
        return [json.loads(r["record"]) for r in rows]

    def seed_entities_by_sources(
        self, dataset: str, source_ids: list[str], *, limit: int = 8
    ) -> list[str]:
        if not source_ids:
            return []
        order = {sid: i for i, sid in enumerate(source_ids)}
        rows = self.run(
            "MATCH (n:HGEntity {dataset_id:$dataset}) "
            "WHERE any(sid IN coalesce(n.source_ids, []) WHERE sid IN $source_ids) "
            "RETURN n.id AS id, n.source_ids AS source_ids",
            dataset=dataset,
            source_ids=sorted(set(source_ids)),
        )
        ranked = []
        for row in rows:
            ranks = [order[sid] for sid in (row.get("source_ids") or []) if sid in order]
            if ranks:
                ranked.append((min(ranks), row["id"]))
        return [identity for _, identity in sorted(ranked)[:limit]]

    def fetch_entities(
        self,
        dataset: str,
        *,
        ids: list[str] | None = None,
        types: list[str] | None = None,
        numbers: list[int] | None = None,
        tags: list[str] | None = None,
        paths: list[str] | None = None,
    ) -> list[dict]:
        clauses = ["n.dataset_id=$dataset"]
        params: dict[str, Any] = {"dataset": dataset}
        if ids is not None:
            if not ids:
                return []
            clauses.append("n.id IN $ids")
            params["ids"] = sorted(set(ids))
        if types is not None:
            if not types:
                return []
            clauses.append("n.kind IN $types")
            params["types"] = sorted(set(types))
        if numbers is not None:
            if not numbers:
                return []
            clauses.append("n.number IN $numbers")
            params["numbers"] = sorted({int(n) for n in numbers})
        if tags is not None:
            if not tags:
                return []
            clauses.append("n.tag IN $tags")
            params["tags"] = sorted(set(tags))
        if paths is not None:
            if not paths:
                return []
            clauses.append("n.path IN $paths")
            params["paths"] = sorted(set(paths))
        cypher = (
            "MATCH (n:HGEntity) WHERE " + " AND ".join(clauses)
            + " RETURN n.record AS record ORDER BY n.id"
        )
        return [json.loads(r["record"]) for r in self.run(cypher, **params)]

    def fetch_sources(
        self,
        dataset: str,
        *,
        ids: list[str] | None = None,
        kinds: list[str] | None = None,
        urls: list[str] | None = None,
    ) -> list[dict]:
        clauses = ["n.dataset_id=$dataset"]
        params: dict[str, Any] = {"dataset": dataset}
        if ids is not None:
            if not ids:
                return []
            clauses.append("n.id IN $ids")
            params["ids"] = sorted(set(ids))
        if kinds is not None:
            if not kinds:
                return []
            clauses.append("n.kind IN $kinds")
            params["kinds"] = sorted(set(kinds))
        if urls is not None:
            if not urls:
                return []
            clauses.append("n.url IN $urls")
            params["urls"] = sorted(set(urls))
        cypher = (
            "MATCH (n:HGSource) WHERE " + " AND ".join(clauses)
            + " RETURN n.record AS record ORDER BY n.id"
        )
        return [json.loads(r["record"]) for r in self.run(cypher, **params)]

    def fetch_evidence(self, dataset: str, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        rows = self.run(
            "MATCH (n:HGEvidence {dataset_id:$dataset}) WHERE n.id IN $ids "
            "RETURN n.record AS record ORDER BY n.id",
            dataset=dataset,
            ids=sorted(set(ids)),
        )
        return [json.loads(r["record"]) for r in rows]

    def fetch_relations(
        self,
        dataset: str,
        *,
        ids: list[str] | None = None,
        types: list[str] | None = None,
        from_ids: list[str] | None = None,
        to_ids: list[str] | None = None,
        has_occurred_at: bool = False,
    ) -> list[dict]:
        allowed = sorted(set(types) & RELATION_ENDPOINTS.keys()) if types is not None else None
        if types is not None and not allowed:
            return []
        rel_pat = ":" + "|".join(allowed) if allowed else ""
        clauses = ["r.dataset_id=$dataset"]
        params: dict[str, Any] = {"dataset": dataset}
        if ids is not None:
            if not ids:
                return []
            clauses.append("r.id IN $ids")
            params["ids"] = sorted(set(ids))
        if from_ids is not None:
            if not from_ids:
                return []
            clauses.append("a.id IN $from_ids")
            params["from_ids"] = sorted(set(from_ids))
        if to_ids is not None:
            if not to_ids:
                return []
            clauses.append("b.id IN $to_ids")
            params["to_ids"] = sorted(set(to_ids))
        if has_occurred_at:
            clauses.append("r.occurred_at IS NOT NULL")
        cypher = (
            f"MATCH (a:HGRecord {{dataset_id:$dataset}})-[r{rel_pat}]->"
            "(b:HGRecord {dataset_id:$dataset}) WHERE " + " AND ".join(clauses)
            + " RETURN r.record AS record ORDER BY r.id"
        )
        return [json.loads(r["record"]) for r in self.run(cypher, **params)]

    def targeted_cypher_paths(
        self,
        dataset: str,
        seed_ids: list[str],
        intent: str,
        depth: int = 3,
        limit: int = 50,
    ) -> list[dict]:
        """Traverse Issue <-[Closes|ClaimsToClose]- PR -[MergedAs]-> Commit
        -[Touches|ReachableIn]-> target in Cypher."""
        if not seed_ids:
            return []
        seeds = sorted(set(seed_ids))
        paths: list[dict] = []
        if intent == "release":
            rows = self.run(
                "MATCH (p:HGEntity {dataset_id:$dataset})-[r:HasRelease]->"
                "(t:HGEntity {dataset_id:$dataset}) "
                "WHERE t.id IN $seeds AND r.dataset_id=$dataset "
                "RETURN [t.id, p.id] AS entity_ids, [r.id] AS relation_ids "
                "ORDER BY r.id LIMIT $limit",
                dataset=dataset, seeds=seeds, limit=limit,
            )
            return list(rows)
        pr_prefixes: dict[str, tuple[list[str], list[str]]] = {}
        seed_entities = self.fetch_entities(dataset, ids=seeds)
        for ent in seed_entities:
            if ent["type"] == "PullRequest":
                pr_prefixes[ent["id"]] = ([ent["id"]], [])
        issue_ids = [ent["id"] for ent in seed_entities if ent["type"] == "Issue"]
        if issue_ids:
            for row in self.run(
                "MATCH (pr:HGEntity {dataset_id:$dataset})-[r:Closes|ClaimsToClose]->"
                "(iss:HGEntity {dataset_id:$dataset}) "
                "WHERE iss.id IN $issues AND r.dataset_id=$dataset "
                "RETURN iss.id AS iid, pr.id AS pid, r.id AS rid ORDER BY r.id",
                dataset=dataset, issues=issue_ids,
            ):
                nodes, edges = [row["iid"], row["pid"]], [row["rid"]]
                if len(edges) <= depth:
                    paths.append({"entity_ids": nodes, "relation_ids": edges})
                pr_prefixes.setdefault(row["pid"], (nodes, edges))
        commits: dict[str, tuple[list[str], list[str]]] = {}
        if pr_prefixes and depth >= 1:
            for row in self.run(
                "MATCH (pr:HGEntity {dataset_id:$dataset})-[r:MergedAs]->"
                "(c:HGEntity {dataset_id:$dataset}) "
                "WHERE pr.id IN $prs AND r.dataset_id=$dataset "
                "RETURN pr.id AS pid, c.id AS cid, r.id AS rid ORDER BY r.id",
                dataset=dataset, prs=sorted(pr_prefixes),
            ):
                n, e = pr_prefixes[row["pid"]]
                nodes, edges = [*n, row["cid"]], [*e, row["rid"]]
                if len(edges) <= depth:
                    paths.append({"entity_ids": nodes, "relation_ids": edges})
                    commits[row["cid"]] = (nodes, edges)
        last = "ReachableIn" if intent == "membership" else "Touches"
        if commits:
            for row in self.run(
                f"MATCH (c:HGEntity {{dataset_id:$dataset}})-[r:{last}]->"
                "(t:HGEntity {dataset_id:$dataset}) "
                "WHERE c.id IN $commits AND r.dataset_id=$dataset "
                "RETURN c.id AS cid, t.id AS tid, r.id AS rid ORDER BY r.id",
                dataset=dataset, commits=sorted(commits),
            ):
                n, e = commits[row["cid"]]
                if len(e) + 1 <= depth:
                    paths.append({"entity_ids": [*n, row["tid"]], "relation_ids": [*e, row["rid"]]})
        return paths[:limit]

    def snapshot(self, dataset: str) -> dict | None:
        meta = self.dataset_meta(dataset)
        if not meta:
            return None
        result = dict(meta)
        for pool, label, key_field in (
            ("sources", "HGSource", "source_id"),
            ("entities", "HGEntity", "id"),
            ("evidence", "HGEvidence", "evidence_id"),
        ):
            items = [
                json.loads(r["record"])
                for r in self.run(
                    f"MATCH (n:{label} {{dataset_id:$dataset}}) RETURN n.record AS record",
                    dataset=dataset,
                )
            ]
            items.sort(key=lambda r: r[key_field])
            result[pool] = items
        rel_items = [
            json.loads(r["record"])
            for r in self.run(
                "MATCH (a:HGRecord {dataset_id:$dataset})-[r]->"
                "(b:HGRecord {dataset_id:$dataset}) WHERE r.dataset_id=$dataset "
                "RETURN r.record AS record",
                dataset=dataset,
            )
        ]
        rel_items.sort(key=lambda r: r["id"])
        result["relations"] = rel_items
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
        unique = {}
        seeds = sorted(set(seed_ids))
        for hop in range(1, depth + 1):
            remaining = max(1, limit - len(unique))
            rows = self.run(
                "MATCH (s:HGRecord {dataset_id:$dataset}) WHERE s.id IN $seeds "
                f"MATCH p=(s)-[:{relationship_types}*{hop}]-(t:HGRecord) "
                "WHERE all(n IN nodes(p) WHERE n.dataset_id=$dataset) "
                "AND all(r IN relationships(p) WHERE r.dataset_id=$dataset) "
                "AND all(n IN nodes(p) WHERE single(m IN nodes(p) WHERE m=n)) "
                "RETURN [n IN nodes(p)|n.id] AS entity_ids, "
                "[r IN relationships(p)|r.id] AS relation_ids "
                "ORDER BY relation_ids,entity_ids LIMIT $hop_limit",
                dataset=dataset, seeds=seeds, hop_limit=remaining * 2 + 10,
            )
            # One physical path may be found from both ends; preserve its first stable orientation.
            for row in rows:
                key = min(tuple(row["relation_ids"]), tuple(reversed(row["relation_ids"])))
                unique.setdefault(key, row)
                if len(unique) >= limit:
                    return list(unique.values())
        return list(unique.values())

    def delete_dataset(self, dataset: str):
        """Explicit namespace cleanup for test/rebuild tooling; never a whole-database delete."""
        with self.driver.session(database=self.database) as session:
            for cypher in (
                "MATCH (n:HGRecord {dataset_id:$dataset}) WITH n LIMIT 2000 "
                "DETACH DELETE n RETURN count(*) AS c",
                "MATCH (n:HGEvidence {dataset_id:$dataset}) WITH n LIMIT 2000 "
                "DETACH DELETE n RETURN count(*) AS c",
                "MATCH (n) WHERE n.dataset_id=$dataset WITH n LIMIT 2000 "
                "DETACH DELETE n RETURN count(*) AS c",
            ):
                while True:
                    deleted = session.execute_write(
                        lambda tx, q=cypher: tx.run(q, dataset=dataset).single()["c"]
                    )
                    if not deleted:
                        break


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


def validate_extended_dataset(dataset_dir: str | Path) -> dict:
    """Compatibility entry point; all producers now use the shared 1.4.2 validator."""
    return validate_dataset(dataset_dir)


def load_dataset(dataset_dir: str | Path, *, config: dict | None = None, **_kwargs: Any) -> dict:
    """Validate before writing. P1 publishes only when both readiness flags are true."""
    result = dict(dataset_id=None, status="error", graph_ready=False, retrieval_ready=False,
                  rejected=[], counts={}, error=None)
    try:
        report = validate_extended_dataset(dataset_dir)
        result.update(dataset_id=report["dataset_id"], counts=report["counts"])
        if report["status"] != "ok":
            result["rejected"] = report["errors"]
            result["error"] = {"code": "invalid_dataset", "message": "数据校验未通过"}
            return result
        package = read_package(dataset_dir)
        # The discussion index and supplementary texts use the same frozen source pool.
        cfg = settings(config)
        retrieval = collector.doctor(database_url=cfg.get("database_url"))
        if retrieval.get("status") != "ok":
            result["error"] = {"code": "retrieval_unavailable", "details": retrieval}
            return result
        from historykg.query.frozen_index import freeze_index
        package["retrieval_index"] = freeze_index(package, cfg.get("database_url"))
        with GraphStore(cfg) as store:
            store.write(package)
            stored = store.snapshot(result["dataset_id"])
            if stored is None or stored["fingerprint"] != package["fingerprint"]:
                raise ValueError("图库/共同来源池读回不一致")
        result.update(status="ok", graph_ready=True, retrieval_ready=True,
                      fingerprint=package["fingerprint"],
                      retrieval_index=package["retrieval_index"],
                      retrieval_backend={"discussion": SEARCH_BACKEND,
                                         "discussion_method": SEARCH_METHOD,
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
