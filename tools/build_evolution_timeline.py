"""Build a verified evolution timeline from frozen knowledge-graph records."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from historykg.io import collect_records, merge_records, read_json, write_json

DEFAULT_CASES = (
    {"slug": "route-option-fix", "issue": 5916, "pull_request": 5917},
    {"slug": "query-route-feature", "issue": 6065, "pull_request": 6133},
    {"slug": "pytest-compat-fix", "issue": 6071, "pull_request": 6095},
    {"slug": "ipv6-partition-fix", "issue": 6093, "pull_request": 6096},
    {"slug": "python-support-policy", "pull_request": 6168},
)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else ""


def _event(
    *,
    event_type: str,
    occurred_at: str | None,
    title: str,
    entity_ids: list[str],
    evidence_ids: list[str],
    **extra: Any,
) -> dict:
    if _parse_time(occurred_at) is None:
        raise ValueError(f"event has no valid timestamp: {title}")
    return {
        "event_type": event_type,
        "occurred_at": occurred_at,
        "title": title,
        "entity_ids": entity_ids,
        "evidence_ids": sorted(set(evidence_ids)),
        **extra,
    }


def build_timeline(dataset_dir: str | Path) -> dict:
    root = Path(dataset_dir).resolve()
    manifest = read_json(root / "manifest.json")
    sources = merge_records(collect_records(root, "sources.jsonl"), "source_id")
    entities = merge_records(collect_records(root, "entities.jsonl"), "id")
    relations = merge_records(collect_records(root, "relations.jsonl"), "id")
    evidence = merge_records(collect_records(root, "evidence.jsonl"), "evidence_id")
    decisions = merge_records(collect_records(root, "decisions.jsonl"), "id")

    source_by_id = {record["source_id"]: record for record in sources}
    entity_by_id = {record["id"]: record for record in entities}
    evidence_by_id = {record["evidence_id"]: record for record in evidence}
    decisions_by_id = {record["id"]: record for record in decisions}

    events = []
    paths_checked = 0
    all_references: set[str] = set()

    releases = sorted(
        (entity for entity in entities if entity["type"] == "Release"),
        key=lambda entity: entity["properties"]["published_at"],
    )
    for release in releases:
        props = release["properties"]
        events.append(
            _event(
                event_type="release_published",
                occurred_at=props["published_at"],
                title=f"Release {props['tag']}",
                entity_ids=[release["id"]],
                evidence_ids=release["evidence_ids"],
                url=props.get("release_url"),
            )
        )
        all_references.update(release["evidence_ids"])

    cases = []
    for spec in DEFAULT_CASES:
        issue = next(
            (
                entity
                for entity in entities
                if entity["type"] == "Issue" and entity["key"] == spec.get("issue")
            ),
            None,
        )
        pull_request = next(
            (
                entity
                for entity in entities
                if entity["type"] == "PullRequest"
                and entity["key"] == spec["pull_request"]
            ),
            None,
        )
        if pull_request is None:
            continue

        case = {
            "slug": spec["slug"],
            "issue_id": issue["id"] if issue else None,
            "pull_request_id": pull_request["id"],
            "commit_id": None,
            "decision_ids": [],
            "touched_paths": [],
            "defined_function_count": 0,
            "defined_function_examples": [],
        }

        if issue:
            props, prefix = issue["properties"], f"Issue #{issue['key']}"
            events.append(
                _event(
                    event_type="issue_opened",
                    occurred_at=props["created_at"],
                    title=f'{prefix} opened: {props["title"]}',
                    entity_ids=[issue["id"]],
                    evidence_ids=issue["evidence_ids"],
                )
            )
            events.append(
                _event(
                    event_type="issue_closed",
                    occurred_at=props["closed_at"],
                    title=f"{prefix} closed",
                    entity_ids=[issue["id"]],
                    evidence_ids=issue["evidence_ids"],
                    interpretation="state_change_only_not_causal_fix_proof",
                )
            )
            all_references.update(issue["evidence_ids"])

        props = pull_request["properties"]
        prefix = f"PR #{pull_request['key']}"
        events.append(
            _event(
                event_type="pull_request_opened",
                occurred_at=props["created_at"],
                title=f'{prefix} opened: {props["title"]}',
                entity_ids=[pull_request["id"]],
                evidence_ids=pull_request["evidence_ids"],
            )
        )
        events.append(
            _event(
                event_type="pull_request_merged",
                occurred_at=props["merged_at"],
                title=f"{prefix} merged",
                entity_ids=[pull_request["id"]],
                evidence_ids=pull_request["evidence_ids"],
            )
        )
        all_references.update(pull_request["evidence_ids"])

        merged_as = next(
            (
                relation
                for relation in relations
                if relation["type"] == "MergedAs"
                and relation["from_id"] == pull_request["id"]
            ),
            None,
        )
        if merged_as:
            commit = entity_by_id.get(merged_as["to_id"])
            if commit is not None and commit["type"] == "Commit":
                case["commit_id"] = commit["id"]
                commit_props = commit["properties"]
                events.append(
                    _event(
                        event_type="commit_merged",
                        occurred_at=commit_props["committed_at"],
                        title=f"Commit {commit_props['sha'][:12]}: "
                        f"{_first_line(commit_props['message'])}",
                        entity_ids=[commit["id"]],
                        evidence_ids=[*commit["evidence_ids"], *merged_as["evidence_ids"]],
                        relation_ids=[merged_as["id"]],
                    )
                )
                all_references.update(commit["evidence_ids"])
                all_references.update(merged_as["evidence_ids"])
                paths_checked += 1

                touches = [
                    relation
                    for relation in relations
                    if relation["type"] == "Touches" and relation["from_id"] == commit["id"]
                ]
                function_examples = []
                for touch in touches:
                    file_entity = entity_by_id.get(touch["to_id"])
                    if file_entity is None:
                        continue
                    case["touched_paths"].append(file_entity["properties"]["path"])
                    defines = [
                        relation
                        for relation in relations
                        if relation["type"] == "Defines"
                        and relation["from_id"] == file_entity["id"]
                    ]
                    case["defined_function_count"] += len(defines)
                    for relation in defines:
                        function = entity_by_id.get(relation["to_id"])
                        if function and len(function_examples) < 6:
                            function_examples.append(
                                function["properties"]["qualified_name"]
                            )
                        all_references.update(relation["evidence_ids"])
                case["touched_paths"] = sorted(set(case["touched_paths"]))
                case["defined_function_examples"] = sorted(set(function_examples))

        about = [
            relation
            for relation in relations
            if relation["type"] == "ABOUT" and relation["to_id"] == pull_request["id"]
        ]
        case_decisions = []
        for relation in about:
            decision = decisions_by_id.get(relation["from_id"])
            if decision is None:
                continue
            case_decisions.append(
                {
                    "id": decision["id"],
                    "status": decision["status"],
                    "action": decision["action"],
                    "statement": decision["statement"],
                    "rationale": decision.get("rationale"),
                    "rationale_status": decision.get("rationale_status"),
                    "evidence_ids": sorted(
                        set(
                            [
                                *decision["statement_evidence_ids"],
                                *decision["rationale_evidence_ids"],
                                *relation["evidence_ids"],
                            ]
                        )
                    ),
                }
            )
            case["decision_ids"].append(decision["id"])
            all_references.update(case_decisions[-1]["evidence_ids"])
        case["decisions"] = sorted(
            case_decisions,
            key=lambda item: (item["status"], item["id"]),
        )
        cases.append(case)

    missing_evidence = sorted(all_references - evidence_by_id.keys())
    if missing_evidence:
        raise ValueError(f"timeline references missing evidence: {missing_evidence[:5]}")

    exact_spans = 0
    for evidence_id in sorted(all_references):
        item = evidence_by_id[evidence_id]
        source = source_by_id.get(item["source_id"])
        if source is None:
            raise ValueError(f"evidence has missing source: {evidence_id}")
        if source["text"][item["start"] : item["end"]] != item["quote"]:
            raise ValueError(f"evidence span mismatch: {evidence_id}")
        exact_spans += 1

    unique_entities = {
        entity_id for event in events for entity_id in event["entity_ids"]
    }
    event_times = [_parse_time(event["occurred_at"]) for event in events]
    if any(value is None for value in event_times):
        raise ValueError("timeline contains an invalid event timestamp")
    events.sort(key=lambda event: (_parse_time(event["occurred_at"]), event["title"]))

    return {
        "schema_version": "historykg_evolution_timeline_v1",
        "generated_from_dataset": manifest["dataset_id"],
        "repo": manifest.get("repo", "pallets/flask"),
        "selection_basis": (
            "Fixed public Issue/PR numbers plus all collected Release checkpoints; "
            "no test question, reference answer, or private material was read."
        ),
        "status": "ok_with_recorded_coverage_gaps",
        "event_count": len(events),
        "case_count": len(cases),
        "entity_type_counts": dict(
            sorted(
                Counter(
                    entity_by_id[entity_id]["type"] for entity_id in unique_entities
                ).items()
            )
        ),
        "cases": cases,
        "events": events,
        "checks": {
            "event_timestamps_valid": True,
            "evidence_references": len(all_references),
            "evidence_spans_exact": exact_spans,
            "pr_to_commit_paths_with_commit": paths_checked,
            "missing_evidence": 0,
        },
        "coverage_gaps": [
            "Release entities are version checkpoints; the current graph has no "
            "ReachableIn edge tying the selected merge commits to a later release.",
            "Issue closure timestamps are state changes. ClaimsToClose is not promoted "
            "to an official Closes fact without a matching GitHub closure event.",
            "Developer and Function nodes exist only in the separate P1+P3 merged "
            "acceptance dataset; this production timeline stops at File snapshots.",
            "The timeline is bounded by the profile's 3 releases and 4 code commits; "
            "it is not a complete project history.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = build_timeline(args.dataset)
    write_json(args.out, result)
    print(
        json.dumps(
            {
                "out": str(args.out),
                "event_count": result["event_count"],
                "case_count": result["case_count"],
                "evidence_spans_exact": result["checks"]["evidence_spans_exact"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
