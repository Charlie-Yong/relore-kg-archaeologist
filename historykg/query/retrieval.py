"""Deterministic common-source retrieval; graph expansion never adds a new source pool."""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import defaultdict

from historykg import collector
from historykg.ids import evidence_id

METHOD_VERSION = "relore_common_rrf_graph_v2"
STOPWORDS = set("a an the is are was were to of for in on and or with what why how does did "
                "this that it which when where please tell explain".split())
CODE_KINDS = {"code"}
DISCUSSION_KINDS = {
    "comment", "issue_body", "pr_body", "review", "review_comment"
}
PATH_PATTERN = re.compile(
    r"(?<![\w/])(?:[\w.-]+/)+[\w.-]+\.(?:py|pyi|js|jsx|ts|tsx|go|rs|java|kt|rb|php|c|h|"
    r"cc|cpp|hpp|md|rst|toml|ya?ml|json)(?![\w.])",
    re.IGNORECASE,
)
SHA_PATTERN = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)
NUMBER_PATTERN = re.compile(
    r"(?:#\s*(\d+)\b|\b(?:issue|pull\s+request|pr)\s*#?\s*(\d+)\b)",
    re.IGNORECASE,
)
EXTENDED_SUBJECT_TYPES = {"Developer", "Function"}


def tokens(text: str) -> set[str]:
    words = set(re.findall(r"[a-z_][a-z_0-9.]*|\d+", text.lower())) - STOPWORDS
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        words.update(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    return words


def lexical_score(question: str, source: dict) -> float:
    terms = tokens(question)
    text = source["text"].lower()
    title = str(source.get("title", "")).lower()
    origin = source["origin_key"].lower()
    return sum(1 + min(text.count(t), 3) + 2 * (t in title) + (t in origin)
               for t in terms if t in text or t in title or t in origin)


def direct_affinity(question: str, source: dict) -> int:
    """Rank the source type that can directly answer an explicitly scoped question."""
    terms = tokens(question)
    title = str(source.get("title", "")).lower()
    origin = source["origin_key"].lower()
    text = source["text"].lower()
    matched = sum(term in text or term in title or term in origin for term in terms)
    score = min(matched, 8) * 2
    kind = source["kind"]
    paths = [value.lower() for value in PATH_PATTERN.findall(question)]
    shas = [value.lower() for value in SHA_PATTERN.findall(question)]
    numbers = {
        first or second for first, second in NUMBER_PATTERN.findall(question)
    }
    if paths or shas:
        if kind in CODE_KINDS:
            score += 20
        elif kind in DISCUSSION_KINDS:
            score -= 4
    else:
        if kind in DISCUSSION_KINDS:
            score += 16
        elif kind == "api_response":
            score -= 12
        elif kind in CODE_KINDS:
            score -= 6
    if numbers and any(
        re.search(rf"(?<!\d){re.escape(number)}(?!\d)", origin)
        for number in numbers
    ):
        score += 20
    if any(path in origin for path in paths):
        score += 40
    if any(sha in origin for sha in shas):
        score += 40
    return score


def subject_records(package: dict) -> list[dict]:
    """Include additive subjects even before P1 materializes subjects.jsonl."""
    subjects = [dict(subject) for subject in package.get("subjects", [])]
    seen = {subject["subject_id"] for subject in subjects}
    evidence = {item["evidence_id"]: item for item in package.get("evidence", [])}
    for entity in package.get("entities", []):
        if entity["type"] not in EXTENDED_SUBJECT_TYPES or entity["id"] in seen:
            continue
        props = entity["properties"]
        if entity["type"] == "Developer":
            display = props.get("display_name") or props.get("name") or props.get("login")
            logins = props.get("logins")
            aliases = [
                props.get("login"),
                props.get("display_name"),
                props.get("name"),
                props.get("github_user_id"),
                props.get("github_id"),
                *(logins if isinstance(logins, list) else []),
            ]
        else:
            qualified_name = props.get("qualified_name")
            name = props.get("name")
            display = qualified_name or name or props.get("path")
            aliases = [
                qualified_name,
                name,
                props.get("path"),
                f"{props.get('path')}::{qualified_name}"
                if props.get("path") and qualified_name else None,
            ]
        subjects.append(
            {
                "subject_id": entity["id"],
                "repo": entity["repo"],
                "entity_type": entity["type"],
                "display_name": str(display or entity["id"]),
                "aliases": sorted({
                    str(value) for value in aliases
                    if isinstance(value, (str, int)) and not isinstance(value, bool) and value
                }),
                "source_ids": sorted(
                    {
                        evidence[eid]["source_id"]
                        for eid in entity.get("evidence_ids", [])
                        if eid in evidence
                    }
                ),
            }
        )
    return subjects


def resolve_seeds(question: str, package: dict, supplied: list[str]) -> tuple[list[str], list]:
    entities = {e["id"]: e for e in package["entities"]}
    if any(seed not in entities for seed in supplied):
        raise ValueError("seed_ids包含本数据集不存在的实体")
    if supplied:
        return sorted(set(supplied)), []
    repo = package["manifest"]["repo"]
    gaps, seeds = [], set()
    local_numbers = {int(n) for n in re.findall(r"(?<![\w/])#(\d+)\b", question)}
    for owner, name, number in re.findall(
        r"https://github\.com/([^/\s]+)/([^/\s]+)/(?:issues|pull)/(\d+)", question
    ):
        if (owner + "/" + name).lower() == repo:
            local_numbers.add(int(number))
        else:
            gaps.append("问题提及仓库外对象，本数据集不包含该仓库的事实")
    for entity in entities.values():
        if entity["type"] in {"Issue", "PullRequest"} and int(
            entity["properties"].get("number", entity["key"])
        ) in local_numbers:
            seeds.add(entity["id"])
    ranked = []
    for subject in subject_records(package):
        labels = [subject["display_name"], *subject.get("aliases", [])]
        labels = [str(s) for s in labels if s and not str(s).isdigit()]
        matches = [len(s) for s in labels if s.casefold() in question.casefold()]
        score = max(matches, default=0)
        if score:
            ranked.append((score, subject["subject_id"]))
    if ranked:
        best = max(score for score, _ in ranked)
        matched = sorted(identity for score, identity in ranked if score == best)
        seeds.update(matched[:8])
        if len(matched) > 1:
            gaps.append("主体匹配多个已采记录，返回候选范围；未声称主体已唯一确定")
    return sorted(seeds), gaps


def retrieve(question: str, package: dict, *, database_url: str | None,
             limit: int = 20) -> dict:
    sources = {s["source_id"]: s for s in package["sources"]}
    raw = collector.search_history(package["manifest"]["repo"], question,
                                   database_url=database_url, limit=10)
    # Public collector hits retain datetime values; audits use explicit ISO strings.
    def json_date(value):
        if isinstance(value, (dt.datetime, dt.date)):
            return value.isoformat()
        raise TypeError(type(value).__name__)
    raw = json.loads(json.dumps(raw, ensure_ascii=False, default=json_date))
    if raw["status"] not in {"ok", "empty"}:
        raise RuntimeError("relore检索失败，不能当作成功空结果")
    mapping = defaultdict(list)
    for source in sources.values():
        m = source.get("relore_mapping")
        if m:
            mapping[(int(m["number"]), m["source_type"], str(m["source_id"]))].append(
                source["source_id"]
            )
    ranks, origins = defaultdict(float), defaultdict(set)
    mapped_hits = []
    for rank, hit in enumerate(raw.get("hits", []), 1):
        if hit.get("repo") != package["manifest"]["repo"]:
            raise ValueError("relore返回了跨仓库命中")
        kind = hit["source_type"]
        # Titles are visible metadata of the frozen body, not separately invented evidence.
        kind = "body" if kind == "title" else kind
        for sid in mapping.get((int(hit["number"]), kind, str(hit["source_id"])), []):
            ranks[sid] += 1 / (60 + rank)
            origins[sid].add("relore")
            mapped_hits.append({"rank": rank, "source_id": sid, "hit": hit})
    lexical = sorted(
        ((lexical_score(question, s), sid) for sid, s in sources.items()),
        key=lambda item: (-item[0], item[1]),
    )
    for rank, (_score, sid) in enumerate((item for item in lexical if item[0] > 0), 1):
        ranks[sid] += 1 / (60 + rank)
        origins[sid].add("common_source_lexical")
    ordered = sorted(ranks, key=lambda sid: (-ranks[sid], sid))[:limit]
    return {"source_ids": ordered, "scores": dict(ranks),
            "origins": {k: sorted(v) for k, v in origins.items()},
            "raw_relore": raw, "mapped_hits": mapped_hits,
            "backend": {"discussion": "relore.search_history", "adapter": "fixed_lexical_rrf_v1",
                        "visible_source_ids": sorted(sources)}}


def seed_from_sources(package: dict, source_ids: list[str], *, limit: int = 8) -> list[str]:
    evidence = {e["evidence_id"]: e for e in package["evidence"]}
    order = {sid: i for i, sid in enumerate(source_ids)}
    ranked = []
    for entity in package["entities"]:
        source_ranks = [order[evidence[e]["source_id"]] for e in entity["evidence_ids"]
                        if e in evidence and evidence[e]["source_id"] in order]
        if source_ranks:
            ranked.append((min(source_ranks), entity["id"]))
    return [identity for _, identity in sorted(ranked)[:limit]]


def graph_sources(package: dict, paths: list[dict]) -> list[str]:
    entities = {e["id"]: e for e in package["entities"]}
    relations = {r["id"]: r for r in package["relations"]}
    evidence = {e["evidence_id"]: e for e in package["evidence"]}
    sources = {s["source_id"] for s in package["sources"]}
    ordered = []
    for path in paths:
        for record in [*(relations[r] for r in path["relation_ids"]),
                       *(entities[e] for e in path["entity_ids"] if e in entities)]:
            ordered.extend(evidence[e]["source_id"] for e in record["evidence_ids"])
        ordered.extend(s for s in path["entity_ids"] if s in sources)
    return list(dict.fromkeys(ordered))


def context_candidates(package: dict, retrieval: dict, expansion: list[str], *,
                       question: str = "", limit: int = 40) -> list[dict]:
    scores = dict(retrieval["scores"])
    for rank, sid in enumerate(expansion, 1):
        scores[sid] = scores.get(sid, 0) + 1 / (60 + rank)
    sources = {s["source_id"]: s for s in package["sources"]}
    candidates = []
    # A/B share this direct relevance ordering; graph expansion changes only the
    # second key and can add a source, rather than promote generic API/code noise.
    ordered = sorted(
        scores,
        key=lambda sid: (
            -direct_affinity(question, sources[sid]),
            -scores[sid],
            sid,
        ),
    )
    for sid in ordered[:limit]:
        source = sources[sid]
        if not source["text"]:
            continue
        # Full frozen text is a candidate. P4's common renderer owns final clipping.
        candidate = {k: source.get(k) for k in ("source_id", "url", "author", "title")}
        candidate.update(start=0, end=len(source["text"]), quote=source["text"],
                         time=source["occurred_at"])
        candidates.append(candidate)
    return candidates


def enrich_evidence(item: dict, source: dict) -> dict:
    return {**item, "url": source["url"], "author": source["author"],
            "time": source["occurred_at"], "text_sha256": source["text_sha256"]}


def context_evidence(fragment: dict, dataset: str, source: dict) -> dict:
    return enrich_evidence({
        **{k: fragment[k] for k in ("source_id", "start", "end", "quote")},
        "dataset_id": dataset,
        "evidence_id": evidence_id(source["repo"], fragment["source_id"], fragment["start"],
                                   fragment["end"], fragment["quote"]),
    }, source)
