"""Map P4 capture objects into immutable C5 sources and explicit P1 facts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from historykg.contracts import CONTRACT_VERSION
from historykg.ids import entity_id, relation_id, stable_id
from historykg.ingest.discovery import parse_references
from historykg.io import (
    api_closer_matches,
    build_subjects,
    collect_records,
    freeze_api_source,
    make_evidence,
    make_source,
    merge_records,
    read_json,
    write_json,
    write_jsonl,
    write_manifest,
)


def map_capture(
    capture_path: str | Path,
    *,
    dataset_dir: str | Path,
    dataset_id: str,
    snapshot_dir: str | Path | None = None,
) -> dict:
    root = Path(dataset_dir)
    capture = read_json(capture_path)
    repo, now = capture["repo"], capture["retrieved_at"]
    snapshot = read_json(Path(snapshot_dir) / "snapshot.json") if snapshot_dir else {}
    sources, evidence, entities, units, references = [], [], [], [], []
    api_sources, pr_details = {}, {}
    http_responses = list(capture.get("http_responses", []))
    if snapshot_dir:
        for name in ("discovery_http.json", "metadata_http.json"):
            path = Path(snapshot_dir) / name
            if path.exists():
                http_responses.extend(read_json(path).get("http_responses", []))
    for response in http_responses:
        if response["status"] != 200:
            continue
        try:
            payload = json.loads(response["body"])
        except ValueError:
            continue
        parts = urlsplit(response["url"])
        endpoint = parts.scheme + "://" + parts.netloc + parts.path
        item = freeze_api_source(
            dataset_id=dataset_id,
            repo=repo,
            endpoint=endpoint,
            payload=payload,
            params=dict(parse_qsl(parts.query)),
            response_status=response["status"],
            retrieved_at=response.get("retrieved_at", now),
        )
        sources.append(item)
        api_sources[endpoint] = item
        if re.fullmatch(rf"/repos/{re.escape(repo)}/pulls/\d+", parts.path) and isinstance(
            payload, dict
        ):
            pr_details[payload["number"]] = {**payload, "source_id": item["source_id"]}

    def add_entity(kind, keys, props, ev):
        identity = entity_id(kind, repo, *keys)
        entities.append(
            dict(
                contract_version=CONTRACT_VERSION,
                dataset_id=dataset_id,
                id=identity,
                repo=repo,
                type=kind,
                key=keys[0] if keys else repo,
                properties=props,
                evidence_ids=ev,
            )
        )
        return identity

    def cite(source, quote=None):
        if not source["text"]:
            return []
        item = make_evidence(source, quote or source["text"])
        evidence.append(item)
        return [item["evidence_id"]]

    repo_api = api_sources.get(f"https://api.github.com/repos/{repo}")
    add_entity("Project", [], {"display_name": repo}, cite(repo_api) if repo_api else [])
    selected_numbers = {p["number"] for p in capture.get("payloads", [])}
    for payload in capture.get("payloads", []):
        number, thread = payload["number"], payload["thread"]
        kind = "PullRequest" if payload["thread_type"] == "pr" else "Issue"
        body_kind = "pr_body" if kind == "PullRequest" else "issue_body"
        base_url = (
            thread.get("html_url")
            or f"https://github.com/{repo}/{'pull' if kind == 'PullRequest' else 'issues'}/{number}"
        )
        thread_sources = []
        # Title stays metadata; body text remains byte-for-byte apart from LF.
        records = [
            (body_kind, thread, "body", str(number)),
            *[
                ("comment", x, "issue_comment", str(x["id"]))
                for x in payload.get("issue_comments", [])
            ],
            *[("review", x, "review", str(x["id"])) for x in payload.get("reviews", [])],
            *[
                ("review_comment", x, "review_comment", str(x["id"]))
                for x in payload.get("review_comments", [])
            ],
        ]
        body_source = None
        for source_kind, record, relore_kind, origin in records:
            item = make_source(
                dataset_id=dataset_id,
                repo=repo,
                kind=source_kind,
                url=record.get("html_url") or base_url,
                text=record.get("body") or "",
                origin_key=f"{repo}:{relore_kind}:{origin}",
                retrieved_at=now,
                occurred_at=record.get("submitted_at") or record.get("created_at"),
                author=(record.get("user") or {}).get("login"),
                trust_tier="authoritative"
                if record.get("author_association") in {"OWNER", "MEMBER", "COLLABORATOR"}
                else "reported",
                relore_mapping={
                    "repo": repo,
                    "number": number,
                    "source_type": relore_kind,
                    "source_id": origin,
                },
                title=thread.get("title", ""),
                in_reply_to_id=record.get("in_reply_to_id"),
            )
            sources.append(item)
            thread_sources.append(item["source_id"])
            if source_kind == body_kind:
                body_source = item
            for ref in parse_references(item["text"], repo):
                ref.update(
                    source_id=item["source_id"],
                    from_number=number,
                    from_type=kind,
                    resolution="out_of_scope"
                    if ref["target_repo"] != repo
                    else "collected"
                    if ref["number"] in selected_numbers
                    else "over_limit"
                    if len(selected_numbers) >= snapshot.get("profile", {}).get("max_units", 40)
                    else "not_collected",
                )
                references.append(ref)
        props = {
            k: thread.get(k)
            for k in (
                "number",
                "title",
                "state",
                "created_at",
                "closed_at",
                "merged_at",
                "merged",
                "merge_commit_sha",
            )
        }
        ev = cite(body_source)
        api_kind = "pulls" if kind == "PullRequest" else "issues"
        api = api_sources.get(f"https://api.github.com/repos/{repo}/{api_kind}/{number}")
        if api:
            ev += cite(api)
        add_entity(kind, [number], props, ev)
        missing = sorted(payload.get("unread", []))
        units.append(
            dict(
                unit_id=stable_id("SourceUnit", repo, f"thread:{number}"),
                dataset_id=dataset_id,
                topic_group=stable_id("topic", repo, f"thread:{number}"),
                source_ids=thread_sources,
                completeness="partial" if missing else "complete",
                missing_parts=missing,
                origin_thread=base_url,
            )
        )
    # Connected references share one topic, avoiding later development/test splitting.
    parent = {p["number"]: p["number"] for p in capture.get("payloads", [])}

    def find(x):
        while parent[x] != x:
            x = parent[x]
        return x

    for ref in references:
        if ref["target_repo"] == repo and ref["number"] in parent:
            a, b = find(ref["from_number"]), find(ref["number"])
            parent[max(a, b)] = min(a, b)
    for unit, payload in zip(units, capture.get("payloads", []), strict=True):
        unit["topic_group"] = stable_id("topic", repo, f"thread:{find(payload['number'])}")
    # Repeated reads of identical API content retain the first frozen timestamp.
    # The original capture still records every read and its exact request time.
    unique_sources = {}
    for source in sources:
        previous = unique_sources.get(source["source_id"])
        if previous:
            left = {k: v for k, v in previous.items() if k != "retrieved_at"}
            right = {k: v for k, v in source.items() if k != "retrieved_at"}
            if left != right:
                raise ValueError("同source_id存在冲突元数据")
            if source["retrieved_at"] < previous["retrieved_at"]:
                unique_sources[source["source_id"]] = source
        else:
            unique_sources[source["source_id"]] = source
    sources = sorted(unique_sources.values(), key=lambda s: s["source_id"])
    write_jsonl(root / "sources.jsonl", sources)
    write_jsonl(root / "source_units.jsonl", units)
    write_jsonl(root / "p1/entities.jsonl", entities)
    write_jsonl(root / "p1/evidence.jsonl", merge_records(evidence, "evidence_id"))
    write_jsonl(root / "p1/relations.jsonl", [])
    write_jsonl(root / "references.jsonl", references)
    if snapshot_dir:
        snapshot["selected_prs"] = [
            pr_details.get(p["number"], p) for p in snapshot.get("selected_prs", [])
        ]
        snapshot["sources"] = merge_records(sources, "source_id")
        code_input = Path(snapshot_dir) / "code-input/sources.jsonl"
        write_jsonl(code_input, snapshot["sources"])
        snapshot["paths"] = {"sources": str(code_input)}
        snapshot["capture_path"] = str(capture_path)
        write_json(Path(snapshot_dir) / "snapshot.json", snapshot)
    build_subjects(root)
    gaps = list(capture.get("result", {}).get("gaps", []))
    gaps += [
        {
            "reason": "explicit_reference_" + r["resolution"],
            "severity": "coverage" if r["resolution"] == "over_limit" else "warning",
            **r,
        }
        for r in references
        if r["resolution"] not in {"collected", "out_of_scope"}
    ]
    write_manifest(
        root,
        dataset_id=dataset_id,
        repo=repo,
        profile_version=snapshot.get("profile", {}).get("profile_version", "collector_smoke_v1"),
        relore_version="0.3.19",
        relore_commit=capture.get("relore_commit"),
        retrieved_at=now,
        synthetic=False,
        frozen=False,
        coverage={"units": len(units)},
        gaps=gaps,
        license="GitHub public repository material; original authors retain rights",
        collection={
            "capture_path": str(capture_path),
            "github_requests": capture.get("result", {}).get("github_requests"),
        },
    )
    incomplete = capture.get("result", {}).get("status") == "partial" or any(
        g.get("severity", "warning") != "coverage" for g in gaps
    )
    return {
        "status": "partial" if incomplete else "ok",
        "counts": {"sources": len(sources), "units": len(units)},
        "gaps": gaps,
        "artifacts": {"dataset_dir": str(root)},
    }


def finalize_relations(dataset_dir: str | Path) -> dict:
    """P1 facts with resolved P3 Commit endpoints; no dangling or inferred fix edges."""
    root = Path(dataset_dir)
    manifest = read_json(root / "manifest.json")
    repo, dataset = manifest["repo"], manifest["dataset_id"]
    entities = {e["id"]: e for e in collect_records(root, "entities.jsonl")}
    sources = {s["source_id"]: s for s in collect_records(root, "sources.jsonl", shards=False)}
    evidence = collect_records(root / "p1", "evidence.jsonl", shards=False)
    relations = []

    def add(kind, left, right, source, method, occurred_at=None, **props):
        ev = make_evidence(source, source["text"])
        evidence.append(ev)
        relations.append(
            dict(
                contract_version=CONTRACT_VERSION,
                dataset_id=dataset,
                id=relation_id(repo, kind, left, right),
                type=kind,
                from_id=left,
                to_id=right,
                properties=props,
                evidence_ids=[ev["evidence_id"]],
                method=method,
                extractor_version="p1_explicit_v1",
                occurred_at=occurred_at,
            )
        )

    refs = collect_records(root, "references.jsonl", shards=False)
    for ref in refs:
        if (
            ref["target_repo"] != repo
            or ref["semantics"] != "claims_to_close"
            or ref["from_type"] != "PullRequest"
        ):
            continue
        left, right = (
            entity_id("PullRequest", repo, ref["from_number"]),
            entity_id("Issue", repo, ref["number"]),
        )
        if left in entities and right in entities:
            source = sources[ref["source_id"]]
            # Preserve the actual closing verb and reference, with exact source span.
            start = max(0, ref["start"] - 30)
            quote = source["text"][start : ref["end"]]
            ev = make_evidence(source, quote, start=start)
            evidence.append(ev)
            relations.append(
                dict(
                    contract_version=CONTRACT_VERSION,
                    dataset_id=dataset,
                    id=relation_id(repo, "ClaimsToClose", left, right),
                    type="ClaimsToClose",
                    from_id=left,
                    to_id=right,
                    properties={"raw_reference": ref["raw"]},
                    evidence_ids=[ev["evidence_id"]],
                    method="text_rule",
                    extractor_version="p1_explicit_v1",
                    occurred_at=source["occurred_at"],
                )
            )
    for source in sources.values():
        if source["kind"] != "api_response":
            continue
        payload = json.loads(source["text"])
        if (
            isinstance(payload, dict)
            and payload.get("merged") is True
            and payload.get("merge_commit_sha")
        ):
            left = entity_id("PullRequest", repo, payload["number"])
            right = entity_id("Commit", repo, payload["merge_commit_sha"])
            if left in entities and right in entities:
                add("MergedAs", left, right, source, "github_api", payload.get("merged_at"))
        endpoint = source.get("api_metadata", {}).get("endpoint", "")
        match = re.search(r"/issues/(\d+)/(?:timeline|events)$", endpoint)
        if not match:
            continue
        issue_id = entity_id("Issue", repo, int(match[1]))
        if issue_id not in entities:
            continue
        for event in payload if isinstance(payload, list) else [payload]:
            if event.get("event") != "closed":
                continue
            for pr in (e for e in entities.values() if e["type"] == "PullRequest"):
                props = pr["properties"]
                closer = event.get("closer") or event.get("source", {}).get("issue", {})
                explicit = api_closer_matches(closer, repo, props["number"])
                commit = (
                    props.get("merged") is True
                    and props.get("merge_commit_sha")
                    and event.get("commit_id") == props["merge_commit_sha"]
                )
                if explicit or commit:
                    add("Closes", pr["id"], issue_id, source, "github_api", event.get("created_at"))
    combined = {}
    for relation in relations:
        if relation["id"] in combined:
            earlier = combined[relation["id"]]
            earlier["evidence_ids"] = sorted(
                set(earlier["evidence_ids"] + relation["evidence_ids"])
            )
        else:
            combined[relation["id"]] = relation
    write_jsonl(root / "p1/relations.jsonl", sorted(combined.values(), key=lambda r: r["id"]))
    # Preserve producer-owned evidence shards; only add new P1 evidence here.
    write_jsonl(root / "p1/evidence.jsonl", merge_records(evidence, "evidence_id"))
    return {"status": "ok", "counts": {"p1_relations": len(relations)}, "gaps": []}
