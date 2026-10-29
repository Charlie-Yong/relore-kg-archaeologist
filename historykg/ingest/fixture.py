"""Generate the explicitly synthetic, reproducible C9 public fixture."""

from pathlib import Path

from historykg.contracts import CONTRACT_VERSION
from historykg.ids import decision_id, entity_id, relation_id, stable_id
from historykg.io import (
    build_subjects,
    freeze_api_source,
    make_evidence,
    make_source,
    write_jsonl,
    write_manifest,
)


def create_fixture(directory: str | Path) -> dict:
    root = Path(directory)
    repo, dataset = "example/toy", "toy_v1"
    now, old, new = "2026-10-30T00:00:00Z", "a" * 40, "b" * 40
    sources, evidence, entities, relations, units, decisions = [], [], [], [], [], []

    def source(kind, text, name):
        item = make_source(
            dataset_id=dataset,
            repo=repo,
            kind=kind,
            text=text,
            url="https://example.invalid/" + name,
            origin_key=name,
            retrieved_at=now,
            occurred_at=now,
            author="synthetic",
            trust_tier="reported",
        )
        sources.append(item)
        return item

    def cite(item, quote=None):
        item = make_evidence(item, quote or item["text"])
        evidence.append(item)
        return item["evidence_id"]

    def entity(kind, keys, props, ev):
        identity = entity_id(kind, repo, *keys)
        entities.append(
            dict(
                contract_version=CONTRACT_VERSION,
                dataset_id=dataset,
                id=identity,
                repo=repo,
                type=kind,
                key=keys[0] if len(keys) == 1 else list(keys) if keys else repo,
                properties=props,
                evidence_ids=ev,
            )
        )
        return identity

    def relation(kind, left, right, ev, method="text_rule", **props):
        relations.append(
            dict(
                contract_version=CONTRACT_VERSION,
                dataset_id=dataset,
                id=relation_id(repo, kind, left, right),
                type=kind,
                from_id=left,
                to_id=right,
                properties=props,
                evidence_ids=ev,
                method=method,
                extractor_version="toy_v1",
                occurred_at=now,
            )
        )

    issue_source = source(
        "issue_body", "Cache is slow. Please retain the public cache API.", "issues/1"
    )
    pr_source = source(
        "pr_body",
        "Fixes #1. Keep the cache API because downstream clients rely on it.\n"
        "Add cache timeout support.\nWe propose removing the legacy fallback.",
        "pull/2",
    )
    comment = source("comment", "Accepted: keep the cache API.", "comments/11")
    review = source("review", "Accepted: add cache timeout support.", "reviews/12")
    inline = source(
        "review_comment",
        "Proposal only; removing fallback has not been accepted.",
        "review-comments/13",
    )
    reply = source(
        "review_comment",
        "Reply to review comment 13: leave this as a proposal.",
        "review-comments/14",
    )
    code_old = source("code", "def cache():\n    return {}\n", "code/old.py")
    code_new = source("code", "def cache(timeout=None):\n    return {}\n", "code/new.py")
    notes = source("release_note", "Release v1.0 includes #2.", "releases/v1.0")
    git = source(
        "git_output",
        f"command: git merge-base --is-ancestor {new} refs/tags/v1.0\n"
        f"input_sha: {new}\nexit_code: 0\nstdout: \n",
        "git/reachable",
    )
    merged = freeze_api_source(
        dataset_id=dataset,
        repo=repo,
        endpoint="repos/example/toy/pulls/2",
        retrieved_at=now,
        payload={
            "number": 2,
            "html_url": "https://example.invalid/example/toy/pull/2",
            "merged": True,
            "merge_commit_sha": new,
        },
    )
    closed = freeze_api_source(
        dataset_id=dataset,
        repo=repo,
        endpoint="repos/example/toy/issues/1/timeline",
        retrieved_at=now,
        payload={
            "event": "closed",
            "issue": {"number": 1},
            "created_at": now,
            "source": {
                "issue": {"number": 2, "html_url": "https://example.invalid/example/toy/pull/2"}
            },
        },
    )
    # Explicitly synthetic URLs are retained even for API-shaped fixture records.
    for item in (merged, closed):
        item["url"] = item["url"].replace("api.github.com", "example.invalid")
        item["api_metadata"]["endpoint"] = item["url"]
        sources.append(item)
    project = entity("Project", [], {"display_name": repo}, [])
    issue = entity("Issue", [1], {"number": 1, "title": "Cache is slow"}, [cite(issue_source)])
    pr = entity(
        "PullRequest",
        [2],
        {"number": 2, "title": "Cache compatibility", "merged": True},
        [cite(pr_source)],
    )
    commit = entity("Commit", [new], {"sha": new}, [cite(merged)])
    file_old = entity(
        "File", [old, "toy/cache.py"], {"path": "toy/cache.py", "commit_sha": old}, [cite(code_old)]
    )
    file_new = entity(
        "File", [new, "toy/cache.py"], {"path": "toy/cache.py", "commit_sha": new}, [cite(code_new)]
    )
    release = entity(
        "Release",
        ["v1.0"],
        {"tag": "v1.0", "commit_sha": new, "published_at": now, "release_url": notes["url"]},
        [cite(notes)],
    )
    entity(
        "Release",
        ["V1.0"],
        {"tag": "V1.0", "commit_sha": new, "published_at": None, "release_url": None},
        [cite(notes)],
    )
    relation("ClaimsToClose", pr, issue, [cite(pr_source, "Fixes #1")])
    relation("Closes", pr, issue, [cite(closed)], method="github_api")
    relation("MergedAs", pr, commit, [cite(merged)], method="github_api")
    relation("Touches", commit, file_new, [cite(code_new)], method="git", change_type="modified")
    relation("ChangesTo", file_old, file_new, [cite(code_old), cite(code_new)], method="git")
    relation("HasRelease", project, release, [cite(notes)], method="github_api")
    relation("MentionsPR", release, pr, [cite(notes)])
    relation("ReachableIn", commit, release, [cite(git)], method="git")
    unit_id = stable_id("SourceUnit", repo, "pull/2")
    units.append(
        dict(
            unit_id=unit_id,
            dataset_id=dataset,
            topic_group="toy-cache",
            source_ids=[s["source_id"] for s in (pr_source, comment, review, inline, reply)],
            completeness="complete",
            missing_parts=[],
            origin_thread="pull/2",
        )
    )
    units.append(
        dict(
            unit_id=stable_id("SourceUnit", repo, "issues/1"),
            dataset_id=dataset,
            topic_group="toy-cache",
            source_ids=[issue_source["source_id"]],
            completeness="partial",
            missing_parts=["issue_comments:page=2"],
            origin_thread="issues/1",
        )
    )
    for action, status, statement, rationale, statement_source, quote in (
        (
            "keep",
            "accepted",
            "Keep the cache API.",
            "Downstream clients rely on it.",
            pr_source,
            "Keep the cache API because downstream clients rely on it.",
        ),
        (
            "add",
            "accepted",
            "Add cache timeout support.",
            None,
            review,
            "Accepted: add cache timeout support.",
        ),
        (
            "remove",
            "proposed",
            "Remove the legacy fallback.",
            None,
            pr_source,
            "We propose removing the legacy fallback.",
        ),
    ):
        ev = cite(statement_source, quote)
        props = dict(
            unit_id=unit_id,
            subject_id=pr,
            action=action,
            status=status,
            statement=statement,
            rationale=rationale,
            rationale_status="stated" if rationale else "not_stated",
            statement_evidence_ids=[ev],
            rationale_evidence_ids=[ev] if rationale else [],
            model_run_id="fixture:no-llm-call",
        )
        identity = decision_id(repo, unit_id, pr, action, status, statement)
        item = dict(
            contract_version=CONTRACT_VERSION,
            dataset_id=dataset,
            id=identity,
            repo=repo,
            type="Decision",
            key=identity,
            properties=props,
            evidence_ids=[ev],
        )
        entities.append(item)
        decisions.append(item)
        relation("ABOUT", identity, pr, [], method="llm")
        relation("EVIDENCED_BY", identity, statement_source["source_id"], [], method="llm")
    write_jsonl(root / "sources.jsonl", sources)
    write_jsonl(root / "source_units.jsonl", units)
    write_jsonl(root / "p1/entities.jsonl", [e for e in entities if e["type"] != "Decision"])
    write_jsonl(
        root / "p1/relations.jsonl",
        [r for r in relations if r["type"] not in {"ABOUT", "EVIDENCED_BY"}],
    )
    write_jsonl(root / "p1/evidence.jsonl", {e["evidence_id"]: e for e in evidence}.values())
    write_jsonl(root / "p4/entities.jsonl", decisions)
    write_jsonl(root / "p4/decisions.jsonl", decisions)
    write_jsonl(
        root / "p4/relations.jsonl",
        [r for r in relations if r["type"] in {"ABOUT", "EVIDENCED_BY"}],
    )
    write_jsonl(root / "p4/evidence.jsonl", [])
    build_subjects(root)
    return write_manifest(
        root,
        dataset_id=dataset,
        repo=repo,
        profile_version="toy_v1",
        synthetic=True,
        actual_llm_extraction=False,
        retrieved_at=now,
        license="Synthetic fixture authored for this project",
        coverage={"discussion_units": 2, "partial": 1},
        gaps=["Synthetic pagination gap"],
    )
