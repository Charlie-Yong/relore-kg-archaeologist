"""Read an official bare git object cache without checkout or source execution."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}\Z")


class GitReadError(RuntimeError):
    pass


class GitReader:
    def __init__(
        self,
        repo: str,
        path: Path,
        record: Callable,
        before_network: Callable,
        *,
        local: bool = False,
        depth: int = 64,
    ):
        self.repo = repo
        self.path = path
        self.record = record
        self.before_network = before_network
        self.local = local
        self.depth = depth
        self.commands: list[dict] = []
        if not local and not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "--bare", str(path)], check=True, capture_output=True)

    def run(self, args: list[str], *, allow_failure: bool = False) -> tuple[str, dict]:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}
        command = ["git", "-c", "core.hooksPath=" + os.devnull, "-C", str(self.path), *args]
        try:
            result = subprocess.run(command, capture_output=True, timeout=90, env=env)
        except subprocess.TimeoutExpired as exc:
            raise GitReadError("git_timeout") from exc
        stdout = result.stdout.decode("utf-8", errors="strict").replace("\r\n", "\n")
        # The command stored in provenance is portable and contains no local path or token.
        entry = {"command": ["git", *args], "returncode": result.returncode, "stdout": stdout}
        self.commands.append(entry)
        # Operational cache probes and fetch progress are not evidence sources.
        evidential = args[0] not in {"fetch", "check-ref-format", "rev-parse"}
        source = self.record(entry) if evidential else None
        if result.returncode and not allow_failure:
            raise GitReadError(f"git_exit_{result.returncode}:{args[0]}")
        return stdout, source

    def ensure(self, revision: str, *, tag: bool = False) -> tuple[str, dict]:
        if tag:
            ref = "refs/tags/" + revision
            self.run(["check-ref-format", ref])
        else:
            if not SHA.fullmatch(revision):
                raise GitReadError("expected_full_sha")
            ref = revision
        existing, _ = self.run(["rev-parse", "--verify", ref + "^{commit}"], allow_failure=True)
        if not SHA.fullmatch(existing.strip()):
            if self.local:
                raise GitReadError("git_object_missing")
            self.before_network("git_fetch")
            self.run(
                [
                    "fetch",
                    "--no-tags",
                    f"--depth={self.depth}",
                    "https://github.com/" + self.repo + ".git",
                    ref + ":" + ref if tag else ref,
                ]
            )
        return self.resolve(ref)

    def resolve(self, revision: str) -> tuple[str, dict]:
        value, source = self.run(["rev-parse", "--verify", revision + "^{commit}"])
        if not SHA.fullmatch(value.strip()):
            raise GitReadError("unresolved_commit")
        return value.strip(), self.record(self.commands[-1])

    def default_sha(self, expected: str | None) -> tuple[str, dict]:
        if expected:
            return self.ensure(expected)
        if self.local:
            return self.resolve("HEAD")
        self.before_network("git_ls_remote")
        value, source = self.run(["ls-remote", "https://github.com/" + self.repo + ".git", "HEAD"])
        sha = value.split()[0] if value.split() else ""
        if not SHA.fullmatch(sha):
            raise GitReadError("default_sha_missing")
        self.ensure(sha)
        return sha, source

    def commit(self, sha: str) -> tuple[dict, dict]:
        value, source = self.run(["show", "-s", "--format=%H%n%P%n%cI%n%B", sha])
        lines = value.split("\n", 3)
        return {
            "sha": lines[0],
            "parents": lines[1].split(),
            "date": lines[2],
            "message": lines[3],
        }, source

    def tree(self, sha: str) -> list[str]:
        value, _ = self.run(["ls-tree", "-r", "--name-only", "-z", sha])
        return [p for p in value.split("\0") if p.endswith(".py")]

    def file(self, sha: str, path: str) -> tuple[str, dict]:
        value, source = self.run(["show", sha + ":" + path])
        return value, source

    def changes(self, parent: str, sha: str) -> tuple[list[dict], dict]:
        value, source = self.run(
            ["diff-tree", "--no-commit-id", "-r", "-M", "--name-status", "-z", parent, sha]
        )
        tokens = value.split("\0")
        changes = []
        i = 0
        while i + 1 < len(tokens):
            status, old_path = tokens[i : i + 2]
            i += 2
            new_path = old_path
            if status.startswith(("R", "C")):
                if i >= len(tokens):
                    raise GitReadError("malformed_diff")
                new_path = tokens[i]
                i += 1
            changes.append({"status": status, "old_path": old_path, "new_path": new_path})
        return changes, source

    def reachable(self, sha: str, release_sha: str) -> tuple[bool | None, dict]:
        _, source = self.run(["merge-base", "--is-ancestor", sha, release_sha], allow_failure=True)
        code = self.commands[-1]["returncode"]
        if code == 0:
            return True, source
        # A shallow boundary can make a negative result inconclusive; no negative edge is emitted.
        shallow, _ = self.run(["rev-parse", "--is-shallow-repository"])
        return (False if code == 1 and shallow.strip() == "false" else None), source
