"""Regressions for default search, checked without a provider or a live dataset."""

import json
import os
from pathlib import Path

import pytest

from historykg.llm.answer import render_context
from historykg.pipeline import query_config
from historykg.query import query
from historykg.query.history_evidence import (
    ancestry_fragments,
    historical_passages,
    search_intent,
    targeted_paths,
)
from historykg.query.service import prepare_query


def test_colloquial_release_and_membership_questions():
    assert search_intent("2.0.1 是哪天出的？") == "release"
    assert search_intent("PR #372 最早进了哪个正式版？") == "membership"
    assert search_intent("PR #372 改了什么？") == "change"
    assert search_intent("2.0.1 的实现和架构是怎样的？") is None


def source(kind, data, url, index, command=None):
    return dict(
        kind=kind,
        text=json.dumps(data, ensure_ascii=False, indent=2),
        source_id=str(index),
        url=url,
        repo="demo/library",
        git_metadata={"command": command, "returncode": 0} if command else None,
    )


def test_default_release_reads_the_right_object_within_budget():
    url = "https://api.github.com/repos/demo/library/releases"
    rows = [
        dict(
            tag_name=tag,
            published_at="2020-01-02T00:00:00Z",
            draft=False,
            prerelease=False,
            body="long body " * 4000,
            html_url=f"https://github.com/demo/library/releases/tag/{tag}",
        )
        for tag in ["3.0.0", "3.0.1"]
    ]
    s = source("api_response", rows, url, 1)
    q = "请核实 3.0.1 正式版的发布日期"
    assert search_intent(q) == "release"
    context = historical_passages(
        {"manifest": {"repo": "demo/library"}, "sources": [s], "entities": []}, q, "release", []
    )
    final = render_context(context)
    assert final["characters"] <= 12000 and len(final["fragments"]) == 1
    f = final["fragments"][0]
    assert "3.0.1" in f["quote"] and "published_at" in f["quote"]
    assert f["quote"] == s["text"][f["start"] : f["end"]]


def test_issue_follows_recorded_claim_then_merge_and_change():
    def edge(kind, a, b):
        return dict(type=kind, from_id=a, to_id=b, id=f"{a}-{b}")

    package = {
        "entities": [
            dict(id=k, type=t)
            for k, t in [("i", "Issue"), ("p", "PullRequest"), ("c", "Commit"), ("f", "File")]
        ],
        "relations": [
            edge("Touches", "c", "f"),
            edge("MergedAs", "p", "c"),
            edge("ClaimsToClose", "p", "i"),
        ],
    }
    paths = targeted_paths(package, ["i"], "change", 3, 50)
    assert [p["entity_ids"] for p in paths] == [["i", "p"], ["i", "p", "c"], ["i", "p", "c", "f"]]
    assert paths[-1]["relation_ids"] == ["p-i", "p-c", "c-f"]
    assert len(targeted_paths(package, ["i"], "change", 1, 50)) == 1


def test_membership_checks_one_tag_at_a_time_and_marks_incomplete_history():
    tip, parent, other = "a" * 40, "b" * 40, "c" * 40
    cmd1 = ["git", "rev-parse", "--verify", "refs/tags/3.0^{commit}"]
    cmd2 = ["git", "rev-list", tip]

    def git(args, stdout, i):
        return source(
            "git_output",
            dict(command=args, returncode=0, stdout=stdout),
            "https://github.com/demo/library",
            i,
            args,
        )

    rows = [git(cmd1, tip + "\n", 1), git(cmd2, tip + "\n" + parent + "\n", 2)]
    releases = [({"tag_name": "3.0"},)]
    (hit,) = ancestry_fragments(rows, releases, parent)
    assert hit["quote"] == parent and "包含" in hit["title"]
    (missing,) = ancestry_fragments(rows, releases, other)
    assert "完整性未确认" in missing["title"]
    combined = git(["git", "rev-list", tip, other], tip + "\n" + other + "\n", 3)
    assert not list(ancestry_fragments([rows[0], combined], releases, other))


def test_numbered_claim_uses_original_offsets_and_rejects_unknown_passages():
    import pytest

    from historykg.llm.answer import PassageClaim, cited_spans

    text = {"source_id": "s", "start": 220, "end": 224, "quote": "abcd"}
    claim = PassageClaim(text="facts", passages=[1, 1])
    assert list(cited_spans(claim, [text])) == [(220, "abcd", text)]
    for index in (0, -1, 2):
        with pytest.raises(ValueError, match="片段编号"):
            list(cited_spans(PassageClaim(text="facts", passages=[index]), [text]))


def test_issue_number_directly_followed_by_chinese():
    from historykg.query.retrieval import resolve_seeds

    package = {
        "entities": [{"id": "i", "type": "Issue", "key": 12, "properties": {}}],
        "manifest": {"repo": "demo/library"},
    }
    seeds, _ = resolve_seeds("Issue #12为什么提出修改？", package, [])
    assert seeds == ["i"]


def test_missing_release_reads_the_frozen_official_list():
    url = "https://api.github.com/repos/demo/library/releases"
    rows = [dict(tag_name=tag, published_at="2020-01-02T00:00:00Z",
                 draft=False, prerelease=tag.endswith("rc1")) for tag in ("3.0.0", "3.0.0rc1")]
    package = {"manifest": {"repo": "demo/library"}, "entities": [],
               "sources": [source("api_response", rows, url, 1)]}
    (found,) = historical_passages(package, "v3.0.0rc1 哪天出的？", "release", [])
    assert "prerelease=True" in found["title"]
    (missing,) = historical_passages(package, "3.0.1 何时发布？", "release", [])
    assert "共 1 条，结论限于该清单" in missing["title"] and "3.0.0rc1" not in missing["title"]
    assert missing["url"] == url


def test_named_methods_use_the_matching_frozen_python_snapshot():
    base = "https://github.com/demo/library/blob/"
    sha, other = "a" * 40, "b" * 40
    body = (
        "class Example:\n    def load(self):\n        return self.read('示例')\n\n"
        "class Unrelated:\n    def load(self):\n        return None\n"
    )
    package = {
        "manifest": {"repo": "demo/library"}, "entities": [],
        "sources": [
            source("api_response", {"object": {"sha": sha}},
                   "https://api.github.com/repos/demo/library/git/ref/heads/main", 1),
            dict(source("code", {}, f"{base}{other}/src/example.py", 2), text="intentionally old"),
            dict(source("code", {}, f"{base}{sha}/src/example.py", 3), text=body),
        ],
    }
    question = "src/example.py 中的 Example.load 做了什么？"
    assert search_intent(question) == "code"
    (item,) = historical_passages(package, question, "code", [])
    assert item["source_id"] == "3"
    assert item["quote"] == body[item["start"]:item["end"]]
    assert "'示例'" in item["quote"] and "Unrelated" not in item["quote"]
    assert item["detail_url"].endswith("src/example.py#L2-L3")


FINAL_RECORDS = Path(__file__).resolve().parents[1] / "evaluation/itsdangerous-final-20261121"
ROUTES = (
    "release release change change change change membership "
    "membership code code membership release"
).split()
TAGS = ("2.0.0", "2.0.1", "2.1.0", "2.1.1", "2.1.2", "2.2.0")
CASES = (
    "为什么改用标准库 JSON？早期有没有拒绝过类似提议，最终由哪个 PR 合并落地并改了哪些文件？",
    "项目历史上有哪些被拒绝的特性提案及理由？",
    "为什么移除了 simplejson？",
)


@pytest.fixture(scope="module")
def frozen_regression():
    path = os.environ.get("HISTORYKG_REGRESSION_CONFIG")
    if not path:
        pytest.skip("Requires the isolated frozen Neo4j and SQLite regression instance")
    project = json.loads(Path(path).read_text())
    dataset = Path(project["dataset_dir"])
    cfg = {**query_config(project), "query_output_root": dataset.parent / "test-queries"}
    return json.loads((dataset / "manifest.json").read_text())["dataset_id"], cfg


def _prepared(env, question, arm):
    dataset_id, cfg = env
    prepared = prepare_query(
        dict(dataset_id=dataset_id, question=question, kind="search"),
        config={**cfg, "system": arm},
    )
    visible = render_context(prepared["candidates"], max_characters=12000)["fragments"]
    for part in visible:
        text = prepared["source_by_id"][part["source_id"]]["text"]
        assert text[part["start"]:part["end"]] == part["quote"]
    return prepared, visible


@pytest.mark.parametrize(("arm", "number"), [(a, n) for a in "AB" for n in range(1, 13)],
                         ids=[f"{a}-Q{n:02d}" for a in "AB" for n in range(1, 13)])
def test_twelve_questions_offline_regression(frozen_regression, arm, number):
    record = json.loads((FINAL_RECORDS / "records" / f"live-{arm}{number}.json").read_text())
    prepared, visible = _prepared(frozen_regression, record["question"], arm)
    assert prepared["search_intent"] == ROUTES[number - 1] and visible
    quotes = "\n".join(row["quote"] for row in visible)
    if number == 2:
        assert '"prerelease": true' in quotes and "2021-04-16T14:54:13Z" in quotes
    if number == 3:
        assert any(row["url"].endswith("/pull/408") for row in visible)
        assert "b0410878" in quotes
        if arm == "B":
            assert ".github/workflows/publish.yaml" in quotes
    if number == 8:
        assert "4f269f6f" in quotes and '"tag_name": "2.2.0"' in quotes
        if arm == "B":
            for tag in TAGS:
                assert any((f.get("title") or "").startswith(f"{tag} → ")
                           and "冻结历史不包含" in f["title"] and "rev-list" in f["quote"]
                           for f in visible)
    if number == 9:
        assert all(s in quotes for s in ("def dumps(", "def loads(", ".sign(", ".unsign("))
    if number == 12:
        assert all(f'"tag_name": "{tag}"' in quotes for tag in TAGS)
        assert all(row["url"].startswith("https://api.github.com/repos/pallets/itsdangerous/releases")
                   for row in visible)
    if number == 5 and arm == "A":
        assert any(row["url"].endswith("/issues/146") for row in visible)
        assert any(row["url"].endswith("/pull/152") for row in visible)
    for old in record["evidence"]:
        # Q3 and Q8 deliberately changed from the old routing;
        # A-Q05 replaced Dependabot noise with PR #152.
        if number in {3, 8} or (number == 5 and arm == "A"):
            continue
        assert any(row["source_id"] == old["source_id"] and
                   row["start"] <= old["start"] < old["end"] <= row["end"] for row in visible)


def test_prerelease_end_to_end_citations_from_query_entry(frozen_regression):
    from historykg.ids import evidence_id

    def answerer(**kwargs):
        assert kwargs["config"]["citation_style"] == "passage_numbers"
        context = render_context(kwargs["context"])
        part = next(row for row in context["fragments"] if '"prerelease": true' in row["quote"])
        assert "2021-04-16T14:54:13Z" in part["quote"]
        eid = evidence_id(
            kwargs["repo"], part["source_id"], part["start"], part["end"], part["quote"]
        )
        return dict(status="ok", evidence=[{**part, "dataset_id": kwargs["dataset_id"],
                                            "evidence_id": eid}],
                    claims=[dict(text="候选版", evidence_ids=[eid]),
                            dict(text="发布日期 2021-04-16", evidence_ids=[eid])],
                    context=context)

    dataset, cfg = frozen_regression
    for question in ("2.0.0rc2 是正式版还是候选版？",
                     "2.0.0rc2 是正式版还是候选版？它在 GitHub 哪天发布？请附出处。"):
        res = query(dict(dataset_id=dataset, question=question),
                    config={**cfg, "system": "B", "answerer": answerer}).model_dump()
        assert res["status"] == "ok" and len(res["claims"]) == 2
        cited = {eid for claim in res["claims"] for eid in claim["evidence_ids"]}
        assert any(
            e["evidence_id"] in cited
            and '"prerelease": true' in e["quote"]
            and "2021-04-16T14:54:13Z" in e["quote"]
            and e.get("detail_url", "").endswith("/releases/tag/2.0.0rc2")
            for e in res["evidence"]
        )
    assert search_intent("2.1.0 正式版为什么这样改？") is None


def test_decision_distinguishes_rejected_and_accepted_with_execution_chain(frozen_regression):
    from app.visuals import chain_chart, chain_rows

    p, visible = _prepared(frozen_regression, CASES[0], "B")
    assert p["search_intent"] == "decision"
    by_url = {row["url"]: row["quote"] for row in visible}
    github = "https://github.com/pallets/itsdangerous"
    api = "https://api.github.com/repos/pallets/itsdangerous"
    assert '"merged": false' in by_url[api + "/pulls/63"]
    assert '"merged_at": null' in by_url[api + "/pulls/63"]
    assert '"merged": true' in by_url[api + "/pulls/152"]
    assert any(url.startswith(github + "/pull/63#") for url in by_url)
    assert github + "/issues/146" in by_url and github + "/pull/152" in by_url
    difference = next(
        row["quote"]
        for row in p["candidates"]
        if row.get("acquisition_source") == "git_diff_lookup" and "981ade6e" in row["quote"]
    )
    assert all(name in difference for name in (
        "CHANGES.rst", "docs/serializer.rst", "__init__.py", "_json.py", "jws.py", "serializer.py"
    ))
    decision_paths = [path for path in p["paths"] if path["entity_ids"][0].startswith("Decision:")]
    assert decision_paths
    assert all(
        len(chain_rows(path)[1]) == len(path["relation_ids"]) and chain_chart(path) is not None
        for path in decision_paths
    )


@pytest.mark.parametrize("question", ["为什么移除了 GraphQL？", "为什么移除了 OAuth token 认证？"])
def test_decision_gap_both_zero_hit_and_common_word_counterexamples(frozen_regression, question):
    p, _ = _prepared(frozen_regression, question, "B")
    assert p["retrieval_notices"]
    assert all(not n.startswith("Decision:") for path in p["paths"] for n in path["entity_ids"])
    def answerer(**kwargs):
        assert kwargs["config"]["retrieval_notices"] == p["retrieval_notices"]
        return dict(status="empty", evidence=[], claims=[], gaps=["没有找到该移除事件的原文证据"])
    dataset, cfg = frozen_regression
    result = query(dict(dataset_id=dataset, question=question),
                   config={**cfg, "system": "B", "answerer": answerer})
    assert result.status == "empty" and not result.claims
    assert all(notice in result.gaps for notice in p["retrieval_notices"])
    if p["candidates"]:
        assert "没有找到该移除事件的原文证据" in result.gaps


def test_no_repo_specific_hardcoding_in_historykg():
    from pathlib import Path

    pkg = Path(__file__).resolve().parents[1] / "historykg"
    hits = [
        str(p)
        for p in pkg.rglob("*.py")
        if "simplejson" in p.read_text(encoding="utf-8")
    ]
    assert not hits, f"Found repo-specific literal in: {hits}"


def test_general_decision_paths_idf_and_1hop_expansion():
    from historykg.ids import entity_id
    from historykg.query.history_evidence import decision_paths

    repo = "example/synth"
    issue_id = entity_id("Issue", repo, 15)
    pr_id = entity_id("PullRequest", repo, 20)
    commit_id = entity_id("Commit", repo, "a" * 40)
    file_id = entity_id("File", repo, "a" * 40, "synth/codec.py")
    d1 = "Decision:" + "1" * 32
    d2 = "Decision:" + "2" * 32
    pkg = {
        "entities": [
            {
                "id": issue_id,
                "type": "Issue",
                "properties": {"number": 15, "title": "Drop msgpack fallback"},
            },
            {
                "id": pr_id,
                "type": "PullRequest",
                "properties": {"number": 20, "title": "Remove msgpack shim"},
            },
            {"id": commit_id, "type": "Commit", "properties": {"sha": "a" * 40}},
            {
                "id": file_id,
                "type": "File",
                "properties": {"path": "synth/codec.py", "commit_sha": "a" * 40},
            },
            {
                "id": d1, "type": "Decision",
                "properties": {
                    "subject_id": issue_id, "status": "proposed", "action": "remove",
                    "statement": "Propose dropping msgpack legacy serializer.",
                    "rationale": "Maintainers want fewer optional dependencies.",
                    "rationale_status": "stated", "statement_evidence_ids": ["e1"],
                },
            },
            {
                "id": d2, "type": "Decision",
                "properties": {
                    "subject_id": pr_id, "status": "accepted", "action": "remove",
                    "statement": "Remove serializer codec shim in release 2.0.",
                    "rationale": "Matches maintainer plan.",
                    "rationale_status": "stated", "statement_evidence_ids": ["e2"],
                },
            },
        ],
        "relations": [
            {
                "id": "r_close",
                "type": "Closes",
                "from_id": pr_id,
                "to_id": issue_id,
                "evidence_ids": ["e2"],
            },
            {
                "id": "r_merge",
                "type": "MergedAs",
                "from_id": pr_id,
                "to_id": commit_id,
                "evidence_ids": ["e2"],
            },
            {
                "id": "r_touch",
                "type": "Touches",
                "from_id": commit_id,
                "to_id": file_id,
                "evidence_ids": ["e2"],
            },
            {
                "id": "r_a1",
                "type": "ABOUT",
                "from_id": d1,
                "to_id": issue_id,
                "evidence_ids": ["e1"],
            },
            {
                "id": "r_a2",
                "type": "ABOUT",
                "from_id": d2,
                "to_id": pr_id,
                "evidence_ids": ["e2"],
            },
        ],
        "evidence": [
            {"evidence_id": "e1", "source_id": "s1"},
            {"evidence_id": "e2", "source_id": "s2"},
        ],
        "sources": [
            {"source_id": "s1", "occurred_at": "2020-01-01T00:00:00Z"},
            {"source_id": "s2", "occurred_at": "2020-02-01T00:00:00Z"},
        ],
    }
    no_change = decision_paths(pkg, "Why drop msgpack?", include_change_paths=False)
    node_ids = {eid for p in no_change for eid in p["entity_ids"]}
    assert d1 in node_ids and d2 in node_ids
    assert file_id not in node_ids
    with_change = decision_paths(pkg, "Why drop msgpack?", include_change_paths=True)
    assert file_id in {eid for p in with_change for eid in p["entity_ids"]}


def test_graphql_closes_collection_and_validation(tmp_path):
    # Mutation must be rejected even on https://api.github.com/graphql
    import pytest

    from historykg import collector
    from historykg.contracts import SourceDocument_v1
    from historykg.ids import entity_id
    from historykg.ingest.capture import finalize_relations, map_capture
    from historykg.io import make_source, read_json, read_jsonl, validate_dataset, write_manifest

    with pytest.raises(ValueError, match="GraphQL"):
        SourceDocument_v1.model_validate(
            make_source(
                dataset_id="d1", repo="example/toy", kind="api_response",
                url="https://api.github.com/graphql", origin_key="gql:bad",
                text='[{"number": 1}]', retrieved_at="2026-11-26T00:00:00Z",
                api_metadata={
                    "endpoint": "https://api.github.com/graphql",
                    "method": "POST",
                    "params": {"query": "mutation { closeIssue }"},
                    "response_status": 200,
                },
            )
        )

    gql_body = {
        "data": {
            "repository": {
                "i7": {
                    "__typename": "Issue",
                    "number": 7,
                    "closed": True,
                    "closedAt": "2024-03-01T10:00:00Z",
                    "repository": {"nameWithOwner": "example/toy"},
                    "closedByPullRequestsReferences": {
                        "nodes": [
                            {
                                "__typename": "PullRequest",
                                "number": 8,
                                "merged": True,
                                "mergedAt": "2024-03-01T10:00:00Z",
                                "repository": {"nameWithOwner": "example/toy"},
                            }
                        ]
                    },
                }
            }
        }
    }
    capture = {
        "format": collector.CAPTURE,
        "repo": "example/toy",
        "retrieved_at": "2026-11-26T00:00:00Z",
        "collector_version": collector.VERSION,
        "result": {"status": "ok", "gaps": []},
        "http_responses": [
            {
                "url": "https://api.github.com/graphql",
                "method": "POST",
                "status": 200,
                "headers": {},
                "query": "query($n0: Int!) { ... }",
                "body": json.dumps(gql_body),
            }
        ],
        "payloads": [
            {
                "repo": "example/toy", "number": 7, "thread_type": "issue",
                "thread": {
                    "id": 1007, "number": 7, "title": "Bug", "body": "Fix me", "state": "closed",
                    "html_url": "https://github.com/example/toy/issues/7",
                    "user": {"login": "alice"},
                    "created_at": "2024-02-01T00:00:00Z", "updated_at": "2024-03-01T10:00:00Z",
                },
                "unread": [],
            },
            {
                "repo": "example/toy", "number": 8, "thread_type": "pr",
                "thread": {
                    "id": 1008,
                    "number": 8,
                    "title": "Fix #7",
                    "body": "Squash fix",
                    "state": "closed",
                    "html_url": "https://github.com/example/toy/pull/8",
                    "user": {"login": "bob"},
                    "created_at": "2024-02-15T00:00:00Z", "updated_at": "2024-03-01T10:00:00Z",
                },
                "unread": [],
            },
        ],
    }
    cap_path = tmp_path / "capture.json"
    cap_path.write_text(json.dumps(capture), encoding="utf-8")
    root = tmp_path / "ds"
    map_capture(cap_path, dataset_dir=root, dataset_id="d_gql")
    finalize_relations(root)
    meta = read_json(root / "manifest.json")
    write_manifest(root, **{k: v for k, v in meta.items() if k not in {"files", "sources"}})
    relations = read_jsonl(root / "p1/relations.jsonl")
    assert any(
        r["type"] == "Closes"
        and r["from_id"] == entity_id("PullRequest", "example/toy", 8)
        and r["to_id"] == entity_id("Issue", "example/toy", 7)
        and r["method"] == "github_api"
        for r in relations
    )
    val = validate_dataset(root)
    assert val["status"] == "ok", val
