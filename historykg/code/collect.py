"""Automatic bounded code/release facts from the P1 discovery snapshot."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from historykg.ids import entity_id, relation_id
from historykg.io import (
    freeze_api_source,
    make_evidence,
    make_source,
    read_json,
    read_jsonl,
    write_json,
    write_jsonl,
)

from .ast_analysis import PARSER_VERSION, analyze_python
from .git_reader import GitReader, GitReadError

VERSION = "code_v2"
CONTRACT = "1.4.1"
EXTENSION_CONTRACT = "1.4.2"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _json_member(text: str, key: str) -> tuple[Any, int, int, str]:
    """Locate a top-level member in canonical frozen JSON without guessing offsets."""
    marker = f'\n  "{key}": '
    position = text.find(marker)
    if position < 0:
        raise ValueError(f"top-level JSON member missing: {key}")
    start = position + 3
    value_start = position + len(marker)
    value, end = json.JSONDecoder().raw_decode(text, value_start)
    return value, start, end, text[start:end]


class BudgetStopped(RuntimeError):
    pass


class CodeStage:
    def __init__(self, snapshot, dataset_dir, profile, budget, client, git_repo):
        self.snapshot = snapshot
        self.repo = snapshot["repo"].lower()
        if not re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", self.repo):
            raise ValueError("expected normalized GitHub owner/repo")
        self.dataset_id = snapshot["dataset_id"]
        self.directory = Path(dataset_dir) / "p3"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.profile = profile or snapshot.get("profile", {})
        self.budget = budget if budget is not None else {}
        self.budget.setdefault("max_requests", 300)
        self.budget.setdefault("github_requests", 0)
        if not 0 <= self.budget["github_requests"] <= self.budget["max_requests"] <= 300:
            raise ValueError("GitHub request budget must be within 0..300")
        self.started_requests = self.budget["github_requests"]
        self.git_network = 0
        self.api_requests = 0
        self.max_files = min(
            24,
            max(
                0,
                int(
                    self.profile.get("max_file_snapshots", self.profile.get("max_file_states", 24))
                ),
            ),
        )
        self.max_commits = min(40, max(0, int(self.profile.get("max_commits", 40))))
        self.max_releases = min(3, max(0, int(self.profile.get("max_releases", 3))))
        self.reserve = min(8, self.max_files // 3)
        self.sources: dict[str, dict] = {}
        self.upstream_sources = {
            s["source_id"]: s for s in snapshot.get("sources", []) if isinstance(s, dict)
        }
        self.entities: dict[str, dict] = {}
        self.relations: dict[str, dict] = {}
        self.evidence: dict[str, dict] = {}
        self.files: dict[tuple[str, str], dict] = {}
        self.trees: dict[str, list[str]] = {}
        self.gaps: list[dict] = []
        self.plan: dict = {
            "parser_version": PARSER_VERSION,
            "selection_rule": "changed_pairs_then_package_and_one_hop_imports_v1",
            "developer_rule": "frozen_pr_json_user_and_merged_by_v1",
            "function_rule": "top_level_function_def_and_async_function_def_v1",
            "limits": {
                "commits": self.max_commits,
                "file_snapshots": self.max_files,
                "releases": self.max_releases,
                "architecture_reserve": self.reserve,
            },
            "commits": [],
            "file_selections": [],
            "excluded": [],
            "releases": [],
        }
        self.client = client
        clone_root = Path(os.environ.get("HISTORYKG_CODE_CLONE_ROOT", ".local/code-git"))
        self.git = GitReader(
            self.repo,
            Path(git_repo) if git_repo else clone_root / (self.repo.replace("/", "__") + ".git"),
            self.git_source,
            self.before_network,
            local=git_repo is not None,
            depth=min(64, max(2, int(self.profile.get("git_depth", 64)))),
        )
        self.cache_path = self.directory / "api_cache.json"
        self.input_hash = _hash(
            {
                "snapshot": snapshot,
                "profile": self.profile,
                "implementation": {"version": VERSION, "parser": PARSER_VERSION},
            }
        )
        state_path = self.directory / "state.json"
        if state_path.exists() and read_json(state_path)["input_hash"] != self.input_hash:
            raise ValueError("frozen code-stage input changed; create a new dataset")
        self.api_cache = read_json(self.cache_path) if self.cache_path.exists() else {}
        self.retrieved_at = read_json(state_path)["retrieved_at"] if state_path.exists() else _now()
        write_json(state_path, {"input_hash": self.input_hash, "retrieved_at": self.retrieved_at})

    def gap(self, reason: str, *, severity: str = "warning", **fields):
        self.gaps.append({"reason": reason, "severity": severity, **fields})

    def source(self, kind, text, origin_key, url, **extra):
        source = make_source(
            dataset_id=self.dataset_id,
            repo=self.repo,
            kind=kind,
            text=text,
            origin_key=origin_key,
            url=url,
            retrieved_at=self.retrieved_at,
            trust_tier="authoritative",
            **extra,
        )
        source = self.reuse_source(source)
        return source

    def reuse_source(self, source):
        upstream = self.upstream_sources.get(source["source_id"])
        if upstream:
            if upstream["text"] != source["text"] or upstream["dataset_id"] != self.dataset_id:
                raise ValueError("upstream source identity conflict")
            source = upstream
        self.sources[source["source_id"]] = source
        return source

    def git_source(self, entry):
        text = json.dumps(entry, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        return self.source(
            "git_output",
            text,
            "git:" + _hash(entry["command"]),
            "https://github.com/" + self.repo,
            git_metadata={"command": entry["command"], "returncode": entry["returncode"]},
        )

    def ev(self, source, quote_text=None, *, start=None):
        text = source["text"] if quote_text is None else quote_text
        if not text:
            return None
        evidence = make_evidence(source, text, start=0 if quote_text is None else start)
        self.evidence[evidence["evidence_id"]] = evidence
        return evidence["evidence_id"]

    def entity(self, kind, keys, properties, evidence_ids, *, contract_version=CONTRACT):
        identity = entity_id(kind, self.repo, *keys)
        self.entities[identity] = {
            "contract_version": contract_version,
            "dataset_id": self.dataset_id,
            "id": identity,
            "repo": self.repo,
            "type": kind,
            "key": keys[0] if len(keys) == 1 else keys,
            "properties": properties,
            "evidence_ids": sorted(e for e in evidence_ids if e),
        }
        return identity

    def relation(
        self,
        kind,
        from_id,
        to_id,
        evidence_ids,
        *,
        method="git",
        occurred_at=None,
        contract_version=CONTRACT,
        **properties,
    ):
        identity = relation_id(self.repo, kind, from_id, to_id)
        self.relations[identity] = {
            "contract_version": contract_version,
            "dataset_id": self.dataset_id,
            "id": identity,
            "type": kind,
            "from_id": from_id,
            "to_id": to_id,
            "properties": properties,
            "evidence_ids": sorted(set(e for e in evidence_ids if e)),
            "method": method,
            "extractor_version": VERSION,
            "occurred_at": occurred_at,
        }

    def _pr_source(self, pr):
        number = pr.get("number")
        source = self.upstream_sources.get(pr.get("source_id"))
        if source is None:
            suffix = f"/pulls/{number}"
            for candidate in self.upstream_sources.values():
                if candidate.get("kind") != "api_response":
                    continue
                endpoint = (candidate.get("api_metadata") or {}).get(
                    "endpoint", candidate.get("url", "")
                )
                if endpoint.split("?", 1)[0].endswith(suffix):
                    source = candidate
                    break
        if source is None:
            self.gap("pr_source_missing", pr=number, source_id=pr.get("source_id"))
            return None, None
        if source.get("kind") != "api_response":
            self.gap("pr_source_not_api_response", pr=number, source_id=source["source_id"])
            return None, None
        self.reuse_source(source)
        try:
            payload = json.loads(source["text"])
        except (TypeError, ValueError) as exc:
            self.gap("pr_source_invalid_json", pr=number, error=type(exc).__name__)
            return None, None
        if not isinstance(payload, dict):
            self.gap("pr_source_not_object", pr=number)
            return None, None
        if payload.get("number") != number:
            self.gap(
                "pr_source_number_mismatch",
                pr=number,
                source_number=payload.get("number"),
            )
            return None, None
        return source, payload

    def developer(self, actor, evidence_id):
        login = actor.get("login")
        if not isinstance(login, str) or not login.strip():
            self.gap("pr_actor_login_missing", actor_id=actor.get("id"))
            return None
        github_id = actor.get("id")
        if isinstance(github_id, int) and not isinstance(github_id, bool):
            identity_key = f"github:{github_id}"
        else:
            identity_key = "login:" + login.casefold()
        identity = entity_id("Developer", self.repo, identity_key)
        existing = self.entities.get(identity)
        if existing is None:
            properties = {
                "display_name": login,
                "login": login,
                "logins": [login],
                "github_user_id": github_id
                if isinstance(github_id, int) and not isinstance(github_id, bool)
                else None,
                "profile_url": actor.get("html_url"),
            }
            self.entity(
                "Developer",
                [identity_key],
                properties,
                [evidence_id],
                contract_version=EXTENSION_CONTRACT,
            )
        else:
            existing["evidence_ids"] = sorted(
                set(existing["evidence_ids"]) | ({evidence_id} if evidence_id else set())
            )
            properties = existing["properties"]
            logins = sorted(set(properties.get("logins", [])) | {login}, key=str.casefold)
            properties["logins"] = logins
            properties["login"] = logins[0]
            properties["display_name"] = logins[0]
            if properties.get("profile_url") is None:
                properties["profile_url"] = actor.get("html_url")
        return identity

    def developers(self):
        """Create authors and mergers only from the frozen PullRequest API objects."""
        for pr in self.snapshot.get("selected_prs", []):
            try:
                number = int(pr["number"])
            except (KeyError, TypeError, ValueError):
                self.gap("pr_number_invalid", pr=pr.get("number"))
                continue
            source, payload = self._pr_source(pr)
            if source is None:
                continue
            pull_request_id = entity_id("PullRequest", self.repo, number)
            actor_summary = {"pr": number, "author": None, "merged_by": None}
            try:
                actor, start, _, quote = _json_member(source["text"], "user")
            except ValueError as exc:
                self.gap("pr_author_field_missing", pr=number, error=str(exc))
            else:
                if actor is None:
                    self.gap("pr_author_missing", pr=number, severity="coverage")
                elif not isinstance(actor, dict):
                    self.gap("pr_author_invalid", pr=number)
                else:
                    evidence_id = self.ev(source, quote, start=start)
                    developer_id = self.developer(actor, evidence_id)
                    if developer_id:
                        self.relation(
                            "Authored",
                            developer_id,
                            pull_request_id,
                            [evidence_id],
                            method="github_api",
                            contract_version=EXTENSION_CONTRACT,
                            pr_number=number,
                            source_field="user",
                        )
                        actor_summary["author"] = actor.get("login")

            merged = payload.get("merged") is True or bool(payload.get("merged_at"))
            try:
                merger, start, _, quote = _json_member(source["text"], "merged_by")
            except ValueError as exc:
                if merged:
                    self.gap("pr_merged_by_field_missing", pr=number, error=str(exc))
            else:
                if merger is None:
                    if merged:
                        self.gap("pr_merged_by_missing", pr=number, severity="coverage")
                elif not isinstance(merger, dict):
                    self.gap("pr_merged_by_invalid", pr=number)
                elif not merged:
                    self.gap("pr_merged_by_without_merge", pr=number)
                else:
                    evidence_id = self.ev(source, quote, start=start)
                    developer_id = self.developer(merger, evidence_id)
                    if developer_id:
                        self.relation(
                            "Merged",
                            developer_id,
                            pull_request_id,
                            [evidence_id],
                            method="github_api",
                            occurred_at=payload.get("merged_at"),
                            contract_version=EXTENSION_CONTRACT,
                            pr_number=number,
                            source_field="merged_by",
                        )
                        actor_summary["merged_by"] = merger.get("login")
            self.plan.setdefault("developers", []).append(actor_summary)

    def functions(self):
        """Create top-level Function entities and File-to-Function definitions."""
        for (sha, path), item in sorted(self.files.items()):
            for function in item["parsed"].get("functions", []):
                evidence_id = self.ev(
                    item["source"], function["quote"], start=function["start"]
                )
                identity = self.entity(
                    "Function",
                    [sha, path, function["qualified_name"], function["start_line"]],
                    {
                        "name": function["name"],
                        "qualified_name": function["qualified_name"],
                        "kind": function["kind"],
                        "start_line": function["start_line"],
                        "end_line": function["end_line"],
                        "signature": function["quote"],
                        "commit_sha": sha,
                        "path": path,
                        "source_id": item["source"]["source_id"],
                        "url": item["source"]["url"],
                    },
                    [evidence_id],
                    contract_version=EXTENSION_CONTRACT,
                )
                self.relation(
                    "Defines",
                    item["id"],
                    identity,
                    [evidence_id],
                    method="ast",
                    contract_version=EXTENSION_CONTRACT,
                    commit_sha=sha,
                    path=path,
                    line=function["start_line"],
                )
                self.plan.setdefault("functions", []).append(
                    {
                        "sha": sha,
                        "path": path,
                        "qualified_name": function["qualified_name"],
                        "kind": function["kind"],
                        "start_line": function["start_line"],
                    }
                )

    def before_network(self, kind):
        if self.budget["github_requests"] >= self.budget["max_requests"]:
            raise BudgetStopped("shared_github_request_budget_exhausted")
        self.budget["github_requests"] += 1
        if kind.startswith("git_"):
            self.git_network += 1
        else:
            self.api_requests += 1

    def api(self, endpoint, params=None):
        key = json.dumps([endpoint, params or {}], sort_keys=True)
        if key in self.api_cache:
            record = self.api_cache[key]
        else:
            self.before_network("api")
            response = self.client.get("https://api.github.com/" + endpoint, params=params)
            if response.status_code in {403, 429}:
                raise BudgetStopped("github_rate_limit_or_access_denied")
            response.raise_for_status()
            record = {"value": response.json(), "status": response.status_code}
            self.api_cache[key] = record
            write_json(self.cache_path, self.api_cache)
        source = freeze_api_source(
            dataset_id=self.dataset_id,
            repo=self.repo,
            endpoint=endpoint,
            payload=record["value"],
            retrieved_at=self.retrieved_at,
            params=params or {},
            response_status=record["status"],
        )
        source = self.reuse_source(source)
        return record["value"], source

    def tree(self, sha):
        if sha not in self.trees:
            self.trees[sha] = self.git.tree(sha)
        return self.trees[sha]

    def read_file(self, sha, path, reason):
        key = (sha, path)
        if key in self.files:
            return self.files[key]
        if len(self.files) >= self.max_files:
            self.plan["excluded"].append(
                {"sha": sha, "path": path, "reason": "file_snapshot_limit"}
            )
            return None
        if path not in self.tree(sha):
            self.gap("file_not_in_tree", sha=sha, path=path)
            return None
        try:
            text, git_source = self.git.file(sha, path)
        except (GitReadError, UnicodeDecodeError) as exc:
            self.gap("file_read_failed", sha=sha, path=path, error=str(exc))
            return None
        url = f"https://github.com/{self.repo}/blob/{sha}/" + quote(path, safe="/")
        source = self.source("code", text, f"code:{sha}:{path}", url)
        parsed = analyze_python(text, path, self.tree(sha))
        evidence = self.ev(source) or self.ev(git_source)
        identity = self.entity(
            "File",
            [sha, path],
            {
                "path": path,
                "commit_sha": sha,
                "source_id": source["source_id"],
                "parse_status": parsed["status"],
                "symbols": parsed["symbols"],
                "docstring": parsed.get("docstring"),
                "url": url,
                "aliases": sorted(set([path] + [s["name"] for s in parsed["symbols"]])),
            },
            [evidence],
        )
        item = {"id": identity, "source": source, "parsed": parsed, "sha": sha, "path": path}
        self.files[key] = item
        self.plan["file_selections"].append(
            {"sha": sha, "path": path, "reason": reason, "parse_status": parsed["status"]}
        )
        if parsed["status"] != "parsed":
            self.gap(
                "ast_parse_failed", sha=sha, path=path, error=parsed["error"], line=parsed["line"]
            )
        return item

    @staticmethod
    def priority(path):
        parts = path.split("/")
        is_test = any(p in {"tests", "test", "docs", "examples"} for p in parts) or parts[
            -1
        ].startswith("test_")
        return (is_test, not path.startswith("src/"), path)

    def commits(self):
        prs = self.snapshot.get("selected_prs", [])
        selected = []
        seen = set()
        for pr in prs:
            sha = pr.get("merge_commit_sha")
            merged = pr.get("merged") is True or bool(pr.get("merged_at"))
            if not merged or not sha:
                self.plan["excluded"].append(
                    {"pr": pr.get("number"), "reason": "not_confirmed_merged"}
                )
                continue
            if sha in seen:
                continue
            seen.add(sha)
            if len(selected) >= self.max_commits:
                self.plan["excluded"].append(
                    {"pr": pr.get("number"), "sha": sha, "reason": "commit_limit"}
                )
                continue
            selected.append((pr, sha))
        candidates = []
        for pr, sha in selected:
            try:
                actual, _ = self.git.ensure(sha)
                commit, commit_source = self.git.commit(actual)
                message = self.source(
                    "commit_message",
                    commit["message"],
                    "commit:" + actual,
                    f"https://github.com/{self.repo}/commit/{actual}",
                    occurred_at=commit["date"],
                )
                commit_id = self.entity(
                    "Commit",
                    [actual],
                    {
                        "sha": actual,
                        "parents": commit["parents"],
                        "message": commit["message"],
                        "committed_at": commit["date"],
                        "pr_numbers": [pr["number"]],
                    },
                    [self.ev(commit_source), self.ev(message)],
                )
                self.plan["commits"].append(
                    {"pr": pr["number"], "sha": actual, "parents": commit["parents"]}
                )
                if not commit["parents"]:
                    self.gap("commit_parent_unavailable", sha=actual)
                    continue
                parent = commit["parents"][0]
                changes, diff_source = self.git.changes(parent, actual)
                for change in changes:
                    if change["old_path"].endswith(".py") or change["new_path"].endswith(".py"):
                        candidates.append(
                            (
                                self.priority(change["new_path"]),
                                actual,
                                parent,
                                commit_id,
                                change,
                                diff_source,
                            )
                        )
            except (GitReadError, UnicodeDecodeError) as exc:
                self.gap("commit_read_failed", pr=pr["number"], sha=sha, error=str(exc))
        # Round-robin commits keeps one large PR from consuming every changed-file pair.
        candidates.sort(key=lambda x: (x[0], x[1]))
        rounds: dict[str, int] = {}
        ranked = []
        for item in candidates:
            rank = rounds.get(item[1], 0)
            rounds[item[1]] = rank + 1
            ranked.append((rank, item))
        for _, (_, sha, parent, commit_id, change, diff_source) in sorted(
            ranked, key=lambda x: (x[0], x[1][0], x[1][1])
        ):
            old, new = change["old_path"], change["new_path"]
            status = change["status"]
            wanted = int(not status.startswith("A") and old.endswith(".py")) + int(
                not status.startswith("D") and new.endswith(".py")
            )
            if len(self.files) + wanted > self.max_files - self.reserve:
                self.plan["excluded"].append(
                    {"sha": sha, **change, "reason": "changed_file_budget"}
                )
                continue
            before = (
                self.read_file(parent, old, "changed_parent")
                if not status.startswith("A") and old.endswith(".py")
                else None
            )
            after = (
                self.read_file(sha, new, "changed_commit")
                if not status.startswith("D") and new.endswith(".py")
                else None
            )
            ev = self.ev(diff_source)
            touched = before if status.startswith("D") else after
            if touched:
                self.relation(
                    "Touches",
                    commit_id,
                    touched["id"],
                    [ev],
                    change_type={
                        "A": "added",
                        "D": "deleted",
                        "M": "modified",
                        "R": "renamed",
                        "C": "copied",
                    }.get(status[0], status),
                    parent_sha=parent,
                    commit_sha=sha,
                    old_path=old,
                    path=new,
                )
            # Copies are distinct histories; ChangesTo requires same-path or explicit rename.
            if before and after and (old == new or status.startswith("R")):
                self.relation(
                    "ChangesTo",
                    before["id"],
                    after["id"],
                    [ev],
                    before_sha=parent,
                    after_sha=sha,
                    before_path=old,
                    after_path=new,
                    change_type=status,
                )

    def architecture(self):
        try:
            sha, _ = self.git.default_sha(self.snapshot.get("default_branch_sha"))
            self.plan["architecture_sha"] = sha
            paths = self.tree(sha)
            production = [p for p in paths if not self.priority(p)[0]]
            entries = sorted(
                [p for p in production if p.endswith("/__init__.py")],
                key=lambda p: (not p.startswith("src/"), p.count("/"), p),
            )
            anchor_path = (entries or sorted(production, key=self.priority) or sorted(paths))[:1]
            for path in anchor_path:
                anchor = self.read_file(sha, path, "architecture_package_entry")
                if not anchor:
                    continue
                targets = list(
                    dict.fromkeys(
                        i["target_path"] for i in anchor["parsed"]["imports"] if i["target_path"]
                    )
                )
                for target in targets:
                    self.read_file(sha, target, "architecture_one_hop_import")
        except (GitReadError, UnicodeDecodeError) as exc:
            self.gap("architecture_snapshot_unavailable", error=str(exc))

    def imports(self):
        for (sha, path), item in sorted(self.files.items()):
            for imported in item["parsed"]["imports"]:
                target = self.files.get((sha, imported["target_path"]))
                if target:
                    ev = self.ev(item["source"], imported["quote"], start=imported["start"])
                    self.relation(
                        "Imports",
                        item["id"],
                        target["id"],
                        [ev],
                        method="ast",
                        module=imported["module"],
                        line=imported["line"],
                        commit_sha=sha,
                    )
                else:
                    self.gap(
                        "import_target_not_collected"
                        if imported["target_path"]
                        else imported["reason"],
                        severity="coverage",
                        sha=sha,
                        path=path,
                        module=imported["module"],
                        target_path=imported["target_path"],
                        line=imported["line"],
                    )

    def releases(self):
        if not self.max_releases:
            return
        # Fixture/frozen snapshot releases are the same official objects P1 already read.
        releases = self.snapshot.get("releases")
        source = None
        release_sources = {}
        if releases is None:
            releases = []
            page = 1
            while True:
                records, source = self.api(
                    f"repos/{self.repo}/releases", {"per_page": 100, "page": page}
                )
                releases.extend(records)
                release_sources.update({r["tag_name"]: source for r in records})
                if len(records) < 100:
                    break
                page += 1
        else:
            source = freeze_api_source(
                dataset_id=self.dataset_id,
                repo=self.repo,
                endpoint=f"repos/{self.repo}/releases",
                payload=releases,
                retrieved_at=self.retrieved_at,
            )
            source = self.reuse_source(source)
            release_sources.update({r["tag_name"]: source for r in releases})
        releases = sorted(
            [r for r in releases if not r.get("draft")],
            key=lambda r: (r.get("published_at") or "", r.get("id", 0)),
            reverse=True,
        )
        if releases:
            chosen = [(r, "release") for r in releases[: self.max_releases]]
        else:
            tags = self.snapshot.get("tags")
            if tags is None:
                tags, source = self.api(
                    f"repos/{self.repo}/tags", {"per_page": self.max_releases, "page": 1}
                )
            else:
                source = freeze_api_source(
                    dataset_id=self.dataset_id,
                    repo=self.repo,
                    endpoint=f"repos/{self.repo}/tags",
                    payload=tags,
                    retrieved_at=self.retrieved_at,
                )
                source = self.reuse_source(source)
            chosen = [
                ({"tag_name": t["name"], "tag_sha": t.get("commit", {}).get("sha")}, "tag_fallback")
                for t in tags[: self.max_releases]
            ]
        if not chosen:
            self.gap("no_release_or_tag", severity="coverage")
        for release, origin in chosen:
            tag = release["tag_name"]
            try:
                sha, git_source = self.git.ensure(tag, tag=True)
                note = self.source(
                    "release_note",
                    release.get("body") or "",
                    "release_note:" + tag,
                    release.get("html_url")
                    or f"https://github.com/{self.repo}/releases/tag/" + quote(tag, safe=""),
                    occurred_at=release.get("published_at"),
                    author=(release.get("author") or {}).get("login"),
                )
                # One full API response is shared by all selected release objects.
                ev = self.ev(release_sources.get(tag, source))
                release_id = self.entity(
                    "Release",
                    [tag],
                    {
                        "tag": tag,
                        "commit_sha": sha,
                        "published_at": release.get("published_at"),
                        "release_url": note["url"],
                        "origin": origin,
                    },
                    [ev, self.ev(git_source)],
                )
                self.relation(
                    "HasRelease",
                    entity_id("Project", self.repo),
                    release_id,
                    [ev],
                    method="github_api",
                    origin=origin,
                )
                self.plan["releases"].append({"tag": tag, "commit_sha": sha, "origin": origin})
                for match in re.finditer(
                    r"(?<![\w/])#(\d+)\b|https://github\.com/"
                    + re.escape(self.repo)
                    + r"/pull/(\d+)\b",
                    note["text"],
                ):
                    number = int(match.group(1) or match.group(2))
                    if any(
                        p.get("number") == number for p in self.snapshot.get("selected_prs", [])
                    ):
                        self.relation(
                            "MentionsPR",
                            release_id,
                            entity_id("PullRequest", self.repo, number),
                            [self.ev(note, match.group(), start=match.start())],
                            method="text_rule",
                            meaning="release_notes_mention_only",
                        )
                for commit in self.plan["commits"]:
                    reachable, reach_source = self.git.reachable(commit["sha"], sha)
                    if reachable:
                        self.relation(
                            "ReachableIn",
                            entity_id("Commit", self.repo, commit["sha"]),
                            release_id,
                            [self.ev(reach_source)],
                            commit_sha=commit["sha"],
                            release_sha=sha,
                            tag=tag,
                        )
                    elif reachable is None:
                        self.gap(
                            "release_reachability_unknown",
                            severity="coverage",
                            sha=commit["sha"],
                            tag=tag,
                            reason_detail="bounded_git_history",
                        )
            except (GitReadError, UnicodeDecodeError) as exc:
                self.gap("release_tag_unresolved", tag=tag, error=str(exc))

    def save(self, stopped=None):
        self.functions()
        self.imports()
        for name, records in (
            ("sources", self.sources),
            ("entities", self.entities),
            ("relations", self.relations),
            ("evidence", self.evidence),
        ):
            write_jsonl(self.directory / (name + ".jsonl"), [records[k] for k in sorted(records)])
        write_json(self.directory / "plan.json", self.plan)
        write_json(self.directory / "gaps.json", self.gaps)
        counts = {
            "sources": len(self.sources),
            "entities": len(self.entities),
            "relations": len(self.relations),
            "evidence": len(self.evidence),
            "commits": len(self.plan["commits"]),
            "file_snapshots": len(self.files),
            "releases": len(self.plan["releases"]),
            "ast_parsed": sum(f["parsed"]["status"] == "parsed" for f in self.files.values()),
            "developers": sum(e["type"] == "Developer" for e in self.entities.values()),
            "functions": sum(e["type"] == "Function" for e in self.entities.values()),
        }
        for kind in (
            "Authored",
            "Merged",
            "Defines",
            "Touches",
            "ChangesTo",
            "Imports",
            "ReachableIn",
            "MentionsPR",
        ):
            counts[kind] = sum(r["type"] == kind for r in self.relations.values())
        artifacts = {
            name: str(self.directory / (name + ".jsonl"))
            for name in ("sources", "entities", "relations", "evidence")
        }
        artifacts.update(
            {"plan": str(self.directory / "plan.json"), "gaps": str(self.directory / "gaps.json")}
        )
        hashes = {
            name: hashlib.sha256(Path(path).read_bytes()).hexdigest()
            for name, path in artifacts.items()
        }
        warnings = any(g["severity"] == "warning" for g in self.gaps)
        status = (
            (
                "partial"
                if self.files or self.entities
                else ("blocked" if stopped["code"] == "blocked" else "error")
            )
            if stopped
            else ("partial" if warnings else "ok")
        )
        result = {
            "interface_version": VERSION,
            "contract_version": EXTENSION_CONTRACT,
            "dataset_id": self.dataset_id,
            "repo": self.repo,
            "status": status,
            "artifacts": artifacts,
            "counts": counts,
            "gaps": self.gaps,
            "usage": {
                "github_requests": self.budget["github_requests"] - self.started_requests,
                "github_requests_total": self.budget["github_requests"],
                "api_requests": self.api_requests,
                "git_network_operations": self.git_network,
                "model_requests": 0,
            },
            "input_hash": self.input_hash,
            "hashes": hashes,
            "parser_version": PARSER_VERSION,
            "python_version": platform.python_version(),
            "error": stopped,
        }
        write_json(
            self.directory / "manifest.json",
            {
                **result,
                "git_commands": self.git.commands,
                "api_json_format": (
                    "P1 freeze_api_source: UTF-8 LF, ensure_ascii=false, sort_keys=true, indent=2"
                ),
                "source_execution": False,
            },
        )
        return result


def collect_code(
    snapshot: dict,
    *,
    dataset_dir: str | Path,
    profile: dict | None = None,
    budget: dict | None = None,
    client=None,
    git_repo: str | Path | None = None,
) -> dict:
    """Consume one fixed P1 snapshot and write only the P3 dataset shard.

    ``budget`` is shared and mutated before every API attempt and git network
    operation. Returned usage.github_requests is this call's delta; total is also
    explicit. ``git_repo``/``client`` are injection seams for frozen/local tests.
    """
    owned = client is None
    if owned:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "historykg-code/1.4.1",
        }
        if token:
            headers["Authorization"] = "Bearer " + token
        client = httpx.Client(headers=headers, timeout=30)
    try:
        stage = CodeStage(snapshot, dataset_dir, profile, budget, client, git_repo)
        manifest_path = stage.directory / "manifest.json"
        if manifest_path.exists():
            cached = read_json(manifest_path)
            if cached.get("input_hash") == stage.input_hash and not cached.get("error"):
                valid = all(
                    Path(path).is_file()
                    and hashlib.sha256(Path(path).read_bytes()).hexdigest()
                    == cached["hashes"][name]
                    for name, path in cached["artifacts"].items()
                )
                if valid:
                    cached.pop("git_commands", None)
                    cached.pop("api_json_format", None)
                    cached.pop("source_execution", None)
                    cached["usage"] = {
                        "github_requests": 0,
                        "github_requests_total": stage.budget["github_requests"],
                        "api_requests": 0,
                        "git_network_operations": 0,
                        "model_requests": 0,
                    }
                    cached["replayed"] = True
                    return cached
        stopped = None
        try:
            stage.developers()
            stage.commits()
            stage.architecture()
            stage.releases()
        except BudgetStopped as exc:
            stopped = {"code": "blocked", "message": str(exc)}
            stage.gap("request_budget_or_rate_limit", message=str(exc))
        except (httpx.HTTPError, ValueError, OSError, GitReadError) as exc:
            stopped = {"code": "collection_failed", "type": type(exc).__name__}
            stage.gap("collection_failed", error_type=type(exc).__name__)
        return stage.save(stopped)
    finally:
        if owned:
            client.close()


def run_code_stage(
    snapshot_dir: str | Path, *, dataset_dir: str | Path, profile: dict, budget: dict
) -> dict:
    """P1 pipeline entry; snapshot_dir/snapshot.json is the immutable stage input."""
    snapshot = read_json(Path(snapshot_dir) / "snapshot.json")
    source_path = snapshot.get("paths", {}).get("sources")
    if source_path:
        # Validate that the provided C5 shard is readable; P1 retains its ownership.
        snapshot["sources"] = read_jsonl(source_path)
    return collect_code(snapshot, dataset_dir=dataset_dir, profile=profile, budget=budget)
