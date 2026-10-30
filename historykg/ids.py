"""C5 stable identifiers. Dataset identity never depends on a content hash."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def normalize_repo(value: str, *, require_url: bool = False) -> str:
    pattern = r"([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)"
    match = re.fullmatch(r"https://github\.com/" + pattern + r"(?:\.git)?/?", value)
    if match is None and not require_url:
        match = re.fullmatch(pattern, value)
    if match is None or any(p in {".", ".."} for p in match.group(1).split("/")):
        raise ValueError("仅支持公开GitHub仓库地址 https://github.com/owner/repo")
    return match.group(1).lower()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_id(kind: str, repo: str, *keys: Any) -> str:
    return kind + ":" + text_hash(canonical_json([kind, normalize_repo(repo), *keys]))


def entity_id(entity_type: str, repo: str, *keys: Any) -> str:
    return stable_id(entity_type, repo, *keys)


def source_id(repo: str, origin_key: str, text_sha256: str) -> str:
    return stable_id("SourceDocument", repo, origin_key, text_sha256)


def evidence_id(repo: str, source: str, start: int, end: int, quote: str) -> str:
    return stable_id("Evidence", repo, source, start, end, quote)


def relation_id(repo: str, relation_type: str, from_id: str, to_id: str) -> str:
    return stable_id("Relation", repo, relation_type, from_id, to_id)


def decision_id(
    repo: str, unit_id: str, subject_id: str, action: str, status: str, statement: str
) -> str:
    return stable_id(
        "Decision", repo, unit_id, subject_id, action, status, " ".join(statement.split())
    )


def dataset_id(repo: str, profile_version: str, job_id: str) -> str:
    return stable_id("dataset", repo, profile_version, job_id)
