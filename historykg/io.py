"""UTF-8 frozen records, span location and dataset-wide C5/C6 validation."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError

from .contracts import (
    CONTRACT_VERSION,
    RELATION_ENDPOINTS,
    Entity,
    Evidence,
    Relation,
    SourceDocument,
    SourceUnit,
    Subject,
)
from .ids import (
    canonical_json,
    decision_id,
    entity_id,
    evidence_id,
    normalize_repo,
    relation_id,
    source_id,
    text_hash,
)


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, value: Any) -> None:
    _atomic_text(Path(path), json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def write_jsonl(path: str | Path, records: Any) -> None:
    _atomic_text(
        Path(path),
        "".join(
            canonical_json(r.model_dump(mode="json") if isinstance(r, BaseModel) else r) + "\n"
            for r in records
        ),
    )


def read_jsonl(path: str | Path, model: type[BaseModel] | None = None) -> list[dict]:
    records = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("JSONL记录必须为对象")
            if model:
                value = model.model_validate(value).model_dump(mode="json")
            records.append(value)
        except (ValueError, ValidationError) as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
    return records


def make_source(
    *,
    dataset_id: str,
    repo: str,
    kind: str,
    url: str,
    text: str,
    origin_key: str,
    retrieved_at: str,
    occurred_at: str | None = None,
    author: str | None = None,
    trust_tier: str = "unknown",
    api_metadata: dict | None = None,
    **extra: Any,
) -> dict:
    repo = normalize_repo(repo)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    digest = text_hash(text)
    record = dict(
        contract_version=CONTRACT_VERSION,
        dataset_id=dataset_id,
        repo=repo,
        source_id=source_id(repo, origin_key, digest),
        kind=kind,
        url=url,
        text=text,
        text_sha256=digest,
        origin_key=origin_key,
        retrieved_at=retrieved_at,
        occurred_at=occurred_at,
        author=author,
        trust_tier=trust_tier,
        **extra,
    )
    if api_metadata is not None:
        record["api_metadata"] = api_metadata
    SourceDocument.model_validate(record)
    return record


def freeze_api_source(
    *,
    dataset_id: str,
    repo: str,
    endpoint: str,
    payload: Any,
    retrieved_at: str,
    params: dict | None = None,
    response_status: int = 200,
    origin_key: str | None = None,
) -> dict:
    """Canonical JSON representation, explicitly not the original HTTP bytes."""
    url = endpoint if endpoint.startswith("https://") else "https://api.github.com/" + endpoint
    return make_source(
        dataset_id=dataset_id,
        repo=repo,
        kind="api_response",
        url=url,
        text=json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        origin_key=origin_key or url + "?" + canonical_json(params or {}),
        retrieved_at=retrieved_at,
        trust_tier="authoritative",
        api_metadata={
            "method": "GET",
            "endpoint": url,
            "params": params or {},
            "response_status": response_status,
        },
    )


def locate_evidence(
    source: dict,
    quote: str,
    *,
    start: int | None = None,
    before: str | None = None,
    after: str | None = None,
) -> tuple[int, int]:
    if not quote:
        raise ValueError("证据quote不能为空")
    text = source["text"]
    if start is not None:
        if start < 0 or text[start : start + len(quote)] != quote:
            raise ValueError("证据偏移与原文不一致")
        candidates = [start]
    else:
        candidates, offset = [], 0
        while (found := text.find(quote, offset)) >= 0:
            candidates.append(found)
            offset = found + 1
    if before is not None:
        candidates = [p for p in candidates if text[:p].endswith(before)]
    if after is not None:
        candidates = [p for p in candidates if text[p + len(quote) :].startswith(after)]
    if len(candidates) != 1:
        raise ValueError("引文未找到或重复，须提供准确start或邻近before/after消歧")
    return candidates[0], candidates[0] + len(quote)


def make_evidence(
    source: dict,
    quote: str,
    *,
    start: int | None = None,
    before: str | None = None,
    after: str | None = None,
) -> dict:
    start, end = locate_evidence(source, quote, start=start, before=before, after=after)
    return dict(
        evidence_id=evidence_id(source["repo"], source["source_id"], start, end, quote),
        dataset_id=source["dataset_id"],
        source_id=source["source_id"],
        start=start,
        end=end,
        quote=quote,
    )


def merge_records(records: list[dict], key: str) -> list[dict]:
    unique = {}
    for record in records:
        identity = (record["dataset_id"], record[key])
        if identity in unique and unique[identity] != record:
            raise ValueError(f"相同ID内容冲突: {record[key]}")
        unique[identity] = record
    return sorted(unique.values(), key=lambda r: r[key])


def collect_records(root: str | Path, name: str, *, shards: bool = True) -> list[dict]:
    root = Path(root)
    paths = [root / name]
    if shards:
        paths.extend(root / role / name for role in ("p1", "p3", "p4"))
    return [record for path in paths if path.is_file() for record in read_jsonl(path)]


def merge_sources(root: str | Path) -> list[dict]:
    root = Path(root)
    records = merge_records(collect_records(root, "sources.jsonl"), "source_id")
    write_jsonl(root / "sources.jsonl", records)
    return records


def build_subjects(root: str | Path) -> list[dict]:
    root = Path(root)
    evidence = {r["evidence_id"]: r for r in collect_records(root, "evidence.jsonl")}
    subjects = []
    for entity in merge_records(collect_records(root, "entities.jsonl"), "id"):
        if entity["type"] not in {"Project", "Issue", "PullRequest", "File"}:
            continue
        props = entity["properties"]
        label = (
            props.get("display_name")
            or props.get("title")
            or props.get("path")
            or str(entity["key"])
        )
        subjects.append(
            dict(
                subject_id=entity["id"],
                repo=entity["repo"],
                entity_type=entity["type"],
                display_name=label,
                aliases=sorted(set(props.get("aliases", []) + [str(entity["key"])])),
                source_ids=sorted(
                    {evidence[e]["source_id"] for e in entity["evidence_ids"] if e in evidence}
                ),
            )
        )
    write_jsonl(root / "subjects.jsonl", subjects)
    return subjects


def expected_entity_id(entity: dict) -> str:
    kind, repo, props, key = entity["type"], entity["repo"], entity["properties"], entity["key"]
    if kind == "Project":
        return entity_id(kind, repo)
    if kind == "File":
        return entity_id(kind, repo, props["commit_sha"], props["path"])
    if kind == "Release":
        return entity_id(kind, repo, props["tag"])
    if kind == "Commit":
        return entity_id(kind, repo, props.get("sha", props.get("commit_sha", key)))
    if kind in {"Issue", "PullRequest"}:
        return entity_id(kind, repo, int(props.get("number", key)))
    return decision_id(
        repo,
        props["unit_id"],
        props["subject_id"],
        props["action"],
        props["status"],
        props["statement"],
    )


def api_closer_matches(closer: dict, repo: str, number: int) -> bool:
    """A bare PR number or typename is insufficient across repository boundaries."""
    if not isinstance(closer, dict) or closer.get("number") != number:
        return False
    for key in ("html_url", "url"):
        value = closer.get(key)
        if not isinstance(value, str):
            continue
        parts = urlsplit(value)
        expected = f"/{repo}/pull/{number}"
        api_expected = f"/repos/{repo}/pulls/{number}"
        if parts.netloc.lower() == "github.com" and parts.path.lower().rstrip("/") == expected:
            return True
        if (
            parts.netloc.lower() == "api.github.com"
            and parts.path.lower().rstrip("/") == api_expected
        ):
            return True
        if repo == "example/toy" and parts.netloc == "example.invalid" and parts.path == expected:
            return True
    repository = closer.get("repository") or {}
    return (
        closer.get("__typename") == "PullRequest"
        and isinstance(repository, dict)
        and str(repository.get("nameWithOwner", "")).lower() == repo
    )


def _api_relation_supported(kind, left, right, refs, sources):
    """Bind official event/merge evidence to its actual endpoints, not isolated tokens."""
    if not left or not right:
        return False
    try:
        pr_number = int(left["properties"].get("number", left["key"]))
    except (ValueError, TypeError):
        return False
    for ev in refs:
        source = sources.get(ev["source_id"], {})
        if source.get("kind") != "api_response":
            continue
        try:
            # API evidence must preserve the complete object carrying the facts.
            payload = json.loads(ev["quote"])
        except (ValueError, TypeError):
            continue
        objects = payload if isinstance(payload, list) else [payload]
        endpoint = source.get("api_metadata", {}).get("endpoint", source.get("url", ""))
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            if kind == "MergedAs":
                sha = right["properties"].get(
                    "sha", right["properties"].get("commit_sha", right["key"])
                )
                if (
                    obj.get("number") == pr_number
                    and obj.get("merged") is True
                    and obj.get("merge_commit_sha") == sha
                ):
                    return True
            else:
                try:
                    issue = int(right["properties"].get("number", right["key"]))
                except (ValueError, TypeError):
                    return False
                issue_match = (obj.get("issue") or {}).get("number") == issue or bool(
                    re.search(
                        rf"/repos/{re.escape(left['repo'])}/issues/{issue}/(?:timeline|events)(?:\?|$)",
                        endpoint,
                    )
                )
                closer = obj.get("closer") or (obj.get("source") or {}).get("issue") or {}
                closer_match = api_closer_matches(closer, left["repo"], pr_number)
                merge_sha = left["properties"].get("merge_commit_sha")
                commit_match = bool(
                    merge_sha
                    and left["properties"].get("merged") is True
                    and obj.get("commit_id") == merge_sha
                )
                if obj.get("event") == "closed" and issue_match and (closer_match or commit_match):
                    return True
    return False


def validate_dataset(root: str | Path, *, check_manifest: bool = True) -> dict:
    """Return all actionable record errors; never drop bad records to make a batch pass."""
    root = Path(root)
    errors = []
    pools = {}
    try:
        manifest = read_json(root / "manifest.json")
        if not isinstance(manifest, dict):
            raise ValueError("manifest必须为对象")
    except (OSError, ValueError) as exc:
        manifest = {}
        errors.append(f"manifest: 缺失或损坏({type(exc).__name__})")
    required_manifest = {"dataset_id", "repo"}
    if manifest.get("frozen"):
        required_manifest |= {"contract_version", "profile_version", "files"}
    if not required_manifest <= manifest.keys():
        errors.append("manifest: 缺必填字段")
    dataset = manifest.get("dataset_id")
    repo = manifest.get("repo")
    for name, model, key in (
        ("sources", SourceDocument, "source_id"),
        ("source_units", SourceUnit, "unit_id"),
        ("evidence", Evidence, "evidence_id"),
        ("entities", Entity, "id"),
        ("relations", Relation, "id"),
        ("subjects", Subject, "subject_id"),
    ):
        try:
            record_paths = [root / (name + ".jsonl")]
            if name not in {"sources", "subjects", "source_units"}:
                record_paths += [root / role / (name + ".jsonl") for role in ("p1", "p3", "p4")]
            for path in record_paths:
                if path.is_file():
                    per_file = read_jsonl(path)
                    if len({r.get(key) for r in per_file}) != len(per_file):
                        errors.append(f"{path.relative_to(root)}: 重复ID")
            records = collect_records(
                root, name + ".jsonl", shards=name not in {"sources", "subjects", "source_units"}
            )
            merged = merge_records(records, key) if name != "subjects" else records
            pools[name] = {}
            if len({r[key] for r in merged}) != len(merged):
                errors.append(f"{name}: 重复ID")
            for record in merged:
                try:
                    model.model_validate(record)
                    if name != "subjects" and dataset and record["dataset_id"] != dataset:
                        raise ValueError("跨数据集记录")
                    if "repo" in record and repo and record["repo"] != repo:
                        raise ValueError("跨仓库记录")
                    pools[name][record[key]] = record
                except (ValueError, ValidationError) as exc:
                    errors.append(f"{name}:{record.get(key)}: {exc}")
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(f"{name}: {exc}")
            pools[name] = {}
    sources, evidence, entities = (pools[n] for n in ("sources", "evidence", "entities"))
    for eid, item in evidence.items():
        source = sources.get(item["source_id"])
        if source is None:
            errors.append(f"evidence:{eid}: 缺来源")
        elif (
            item["dataset_id"] != source["dataset_id"]
            or item["end"] <= item["start"]
            or source["text"][item["start"] : item["end"]] != item["quote"]
            or item["end"] > len(source["text"])
            or item["start"] < 0
        ):
            errors.append(f"evidence:{eid}: 偏移/引文/数据集不匹配")
        elif eid != evidence_id(
            source["repo"], item["source_id"], item["start"], item["end"], item["quote"]
        ):
            errors.append(f"evidence:{eid}: 稳定ID不匹配")
    for name in ("entities", "relations"):
        for identity, record in pools[name].items():
            for eid in record.get("evidence_ids", []):
                if eid not in evidence:
                    errors.append(f"{name}:{identity}: 缺证据{eid}")
            if name == "entities":
                try:
                    if identity != expected_entity_id(record):
                        raise ValueError("稳定ID不匹配")
                    props = record["properties"]
                    if record["type"] in {"Commit", "File", "Release"}:
                        sha = props.get("commit_sha", props.get("sha", record["key"]))
                        if (
                            not isinstance(sha, str)
                            or len(sha) != 40
                            or any(c not in "0123456789abcdef" for c in sha)
                        ):
                            raise ValueError("commit_sha必须完整40位小写SHA")
                    if record["type"] == "Decision":
                        if props["subject_id"] not in pools["subjects"]:
                            raise ValueError("Decision主体不在本数据集subjects")
                        if props["rationale_status"] == "stated" and (
                            not props.get("rationale") or not props.get("rationale_evidence_ids")
                        ):
                            raise ValueError("stated理由缺正文或证据")
                        if (
                            props["rationale_status"] != "stated"
                            and props.get("rationale") is not None
                        ):
                            raise ValueError("非stated理由必须为null")
                        for eid in props.get("statement_evidence_ids", []) + props.get(
                            "rationale_evidence_ids", []
                        ):
                            if eid not in evidence:
                                raise ValueError("Decision引用缺证据")
                except (KeyError, ValueError, TypeError) as exc:
                    errors.append(f"entities:{identity}: {exc}")
            else:
                kind = record["type"]
                left = entities.get(record["from_id"])
                right = entities.get(record["to_id"]) or sources.get(record["to_id"])
                allowed = RELATION_ENDPOINTS.get(kind)
                right_type = right.get("type", "SourceDocument") if right else None
                if (
                    not left
                    or not right
                    or not allowed
                    or left["type"] not in allowed[0]
                    or right_type not in allowed[1]
                ):
                    errors.append(f"relations:{identity}: 缺端点或类型/方向错误")
                if repo and identity != relation_id(repo, kind, record["from_id"], record["to_id"]):
                    errors.append(f"relations:{identity}: 稳定ID不匹配")
                if kind not in {"ABOUT", "EVIDENCED_BY"} and not record["evidence_ids"]:
                    errors.append(f"relations:{identity}: 事实关系缺证据")
                if kind in {"Closes", "MergedAs"}:
                    refs = [evidence[e] for e in record["evidence_ids"] if e in evidence]
                    try:
                        supported = _api_relation_supported(kind, left, right, refs, sources)
                    except (ValueError, TypeError, AttributeError):
                        supported = False
                    if not supported:
                        errors.append(f"relations:{identity}: 缺可识别对象及合并/关闭事件API上下文")
                if (
                    kind == "Imports"
                    and left
                    and right
                    and left["properties"].get("commit_sha")
                    != right["properties"].get("commit_sha")
                ):
                    errors.append(f"relations:{identity}: Imports必须同SHA")
    for unit in pools["source_units"].values():
        if any(s not in sources for s in unit["source_ids"]):
            errors.append(f"source_units:{unit['unit_id']}: 缺来源")
    for subject in pools["subjects"].values():
        if subject["subject_id"] not in entities or any(
            s not in sources for s in subject["source_ids"]
        ):
            errors.append(f"subjects:{subject['subject_id']}: 缺主体或来源")
    if check_manifest:
        for name, digest in manifest.get("files", {}).items():
            path = root / name
            if not path.is_file() or text_hash(path.read_text(encoding="utf-8")) != digest:
                errors.append(f"manifest: 文件缺失或哈希不匹配{name}")
    return {
        "status": "ok" if not errors else "error",
        "dataset_id": dataset,
        "counts": {name: len(pool) for name, pool in pools.items()},
        "errors": errors,
    }


def write_manifest(root: str | Path, **metadata: Any) -> dict:
    root = Path(root)
    manifest = {
        "contract_version": CONTRACT_VERSION,
        "api_json_format": (
            "UTF-8/LF; json.dumps ensure_ascii=False sort_keys=True indent=2; "
            "canonical representation, not HTTP bytes"
        ),
        **metadata,
    }
    manifest["files"] = {
        p.relative_to(root).as_posix(): text_hash(p.read_text(encoding="utf-8"))
        for p in sorted(root.rglob("*.jsonl"))
    }
    manifest["sources"] = [
        {k: s[k] for k in ("source_id", "kind", "url", "text_sha256", "origin_key")}
        for s in collect_records(root, "sources.jsonl", shards=False)
    ]
    write_json(root / "manifest.json", manifest)
    return manifest
