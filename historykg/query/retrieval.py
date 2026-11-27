"""Deterministic common-source retrieval; graph expansion never adds a new source pool."""

from __future__ import annotations

import json
import re
from collections import defaultdict

from historykg import collector
from historykg.ids import evidence_id
from historykg.ingest.github import discussion_mapping
from historykg.ingest.index import SEARCH_BACKEND, SEARCH_METHOD
from historykg.query.frozen_index import (
    fetch_frozen_sources,
    frozen_source_ids,
    lexical_candidate_sources,
)

METHOD_VERSION = "p2_query_v1.4.2_historykg_discussion_v1"
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
    r"(?:#\s*(\d+)|\b(?:issue|pull\s+request|pr)\s*#?\s*(\d+))(?![a-z0-9_])",
    re.IGNORECASE,
)
GITHUB_OBJECT_PATTERN = re.compile(
    r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/"
    r"(issues|pull)/([0-9]+)"
    r"(?=$|[/?#\s)\].,;:，。；：！？、（）【】《》\u3400-\u9fff])",
    re.IGNORECASE,
)
EXTENDED_SUBJECT_TYPES = {"Developer", "Function"}


def tokens(text: str) -> set[str]:
    words = set(re.findall(r"[a-z_][a-z_0-9.]*|\d+", text.lower())) - STOPWORDS
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        words.update(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    return words


DECISION_TOPIC_STOPWORDS = set(
    "project history decision decisions why remove removed removal rejected reject change "
    "changed proposal proposals feature features was did has have authentication auth token "
    "library standard module repository give find what some which reason reasons how pr "
    "issue".split()
)


def decision_terms(question: str) -> set[str]:
    """Normalize concrete topic words uniformly for all repositories without hardcoding."""
    raw = re.findall(r"[a-z_][a-z_0-9.-]*", question.lower())
    blocked = STOPWORDS | DECISION_TOPIC_STOPWORDS
    terms = set()
    for token in raw:
        cleaned = token.strip(".-")
        if len(cleaned) <= 1 or cleaned in blocked:
            continue
        terms.add(cleaned)
        stripped = cleaned.strip("_")
        if len(stripped) > 2 and stripped not in blocked:
            terms.add(stripped)
        if "." in cleaned or "-" in cleaned:
            for part in re.split(r"[.-]+", cleaned):
                part_stripped = part.strip("_")
                if len(part_stripped) > 1 and part_stripped not in blocked:
                    terms.add(part_stripped)
    return terms



def github_object_references(text: str) -> list[dict]:
    """Return explicit GitHub issue/PR references without treating bare numbers as URLs."""
    references, seen = [], set()
    for owner, name, kind, number in GITHUB_OBJECT_PATTERN.findall(text):
        repo = f"{owner}/{name}".casefold()
        identity = (repo, kind.casefold(), int(number))
        if identity in seen:
            continue
        seen.add(identity)
        references.append({
            "repo": repo,
            "kind": kind.casefold(),
            "number": int(number),
            "url": f"https://github.com/{owner}/{name}/{kind.lower()}/{int(number)}",
        })
    return references


def external_github_references(text: str, repo: str) -> list[dict]:
    expected = repo.casefold()
    return [reference for reference in github_object_references(text)
            if reference["repo"] != expected]


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
    local_numbers = {int(a or b) for a, b in NUMBER_PATTERN.findall(question)}
    for reference in github_object_references(question):
        if reference["repo"] == repo.casefold():
            local_numbers.add(reference["number"])
        else:
            gaps.append({
                "reason": "external_project",
                "message": (
                    "问题明确引用仓库外对象；"
                    "本数据集不包含该仓库的事实"
                ),
                "references": [reference["url"]],
            })
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
            gaps.append(
                "主体匹配多个已采记录，返回候选范围；"
                "未声称主体已唯一确定"
            )
    return sorted(seeds), gaps


def retrieve(question: str, package: dict, *, database_url: str | None,
             limit: int = 20, scoped_url: str | None = None) -> dict:
    raw = collector.search_history(package["manifest"]["repo"], question,
                                   database_url=database_url, limit=10)
    if raw["status"] not in {"ok", "empty"}:
        raise RuntimeError("讨论检索失败，不能当作成功空结果")
    if package.get("sources") is not None:
        sources = {s["source_id"]: s for s in package["sources"]}
        visible_source_ids = sorted(sources)
        candidate_sources = list(sources.values())
    elif scoped_url is not None:
        visible_source_ids = frozen_source_ids(scoped_url)
        candidate_list = lexical_candidate_sources(scoped_url, tokens(question))
        sources = {s["source_id"]: s for s in candidate_list}
        if raw.get("hits"):
            hit_origins = sorted({
                f"{package['manifest']['repo']}:{h['source_type']}:{h['source_id']}"
                for h in raw["hits"]
            })
            for s in fetch_frozen_sources(scoped_url, origin_keys=hit_origins):
                sources[s["source_id"]] = s
        candidate_sources = list(sources.values())
    else:
        sources = {}
        visible_source_ids = []
        candidate_sources = []

    mapping = defaultdict(list)
    for source in sources.values():
        m = discussion_mapping(source)
        if m:
            mapping[(int(m["number"]), m["source_type"], str(m["source_id"]))].append(
                source["source_id"]
            )
    ranks, origins = defaultdict(float), defaultdict(set)
    mapped_hits = []
    for rank, hit in enumerate(raw.get("hits", []), 1):
        if hit.get("repo") != package["manifest"]["repo"]:
            raise ValueError("讨论检索返回了跨仓库命中")
        kind = hit["source_type"]
        for sid in mapping.get((int(hit["number"]), kind, str(hit["source_id"])), []):
            ranks[sid] += 1 / (60 + rank)
            origins[sid].add("discussion_keywords")
            mapped_hits.append({"rank": rank, "source_id": sid, "hit": hit})
    lexical = sorted(
        ((lexical_score(question, s), s["source_id"]) for s in candidate_sources),
        key=lambda item: (-item[0], item[1]),
    )
    for rank, (_score, sid) in enumerate((item for item in lexical if item[0] > 0), 1):
        ranks[sid] += 1 / (60 + rank)
        origins[sid].add("common_source_lexical")
    ordered = sorted(ranks, key=lambda sid: (-ranks[sid], sid))[:limit]
    return {"source_ids": ordered, "scores": dict(ranks),
            "origins": {k: sorted(v) for k, v in origins.items()},
            "raw_discussion": raw, "mapped_hits": mapped_hits,
            "matched_sources": {sid: sources[sid] for sid in ordered if sid in sources},
            "backend": {"discussion": SEARCH_BACKEND, "discussion_method": SEARCH_METHOD,
                        "adapter": "fixed_lexical_rrf_v1",
                        "visible_source_ids": visible_source_ids}}


def seed_from_sources(package: dict, source_ids: list[str], *, limit: int = 8) -> list[str]:
    order = {sid: i for i, sid in enumerate(source_ids)}
    ranked = []
    if package.get("entities") and package.get("evidence"):
        evidence = {e["evidence_id"]: e for e in package["evidence"]}
        for entity in package["entities"]:
            source_ranks = [order[evidence[e]["source_id"]] for e in entity["evidence_ids"]
                            if e in evidence and evidence[e]["source_id"] in order]
            if source_ranks:
                ranked.append((min(source_ranks), entity["id"]))
        return [identity for _, identity in sorted(ranked)[:limit]]
    for subject in package.get("subjects", []):
        source_ranks = [order[sid] for sid in subject.get("source_ids", []) if sid in order]
        if source_ranks:
            ranked.append((min(source_ranks), subject["subject_id"]))
    return [identity for _, identity in sorted(ranked)[:limit]]


def graph_sources(package: dict, paths: list[dict]) -> list[str]:
    entities = {e["id"]: e for e in package["entities"]}
    relations = {r["id"]: r for r in package["relations"]}
    evidence = {e["evidence_id"]: e for e in package["evidence"]}
    if package.get("sources") is not None:
        sources = {s["source_id"] for s in package["sources"]}
    else:
        sources = set(package.get("visible_source_ids") or [])
    ordered = []
    for path in paths:
        for record in [*(relations[r] for r in path["relation_ids"] if r in relations),
                       *(entities[e] for e in path["entity_ids"] if e in entities)]:
            ordered.extend(
                evidence[e]["source_id"] for e in record["evidence_ids"] if e in evidence
            )
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
        (sid for sid in scores if sid in sources),
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


def history_scope_seeds(question: str, kind: str, package: dict) -> list[str]:
    """Resolve named release tags and exact file revisions in the full history."""
    entities = package["entities"]
    if kind == "timeline":
        hits = []
        for entity in entities:
            if entity["type"] != "Release":
                continue
            tag = entity["properties"].get("tag")
            if tag and re.search(r"\d", tag) and ("." in tag or tag.lower().startswith("v")):
                match = re.search(
                    rf"(?<![a-z0-9_.]){re.escape(tag)}(?![a-z0-9_.])", question, re.I,
                )
                if match:
                    hits.append((match.start(), entity["id"]))
        return [identity for _, identity in sorted(hits)]
    if kind not in {"dependencies", "compare"}:
        return []
    paths = {path.lower() for path in PATH_PATTERN.findall(question)}
    shas = {sha.lower() for sha in SHA_PATTERN.findall(question)}
    if not paths or not shas:
        return []
    scoped = sorted(
        e["id"] for e in entities if e["type"] == "File"
        and e["properties"].get("path", "").lower() in paths
        and any(e["properties"].get("commit_sha", "").lower().startswith(sha) for sha in shas)
    )
    if kind == "compare" and len(scoped) != 2:
        return []
    return scoped


def focused_history_context(package, *, kind, seeds, paths, timeline, question):
    """Lead large-repo queries with short, exact spans tied to the queried subjects."""
    if kind not in {"search", "trace", "timeline"}:
        return []
    entities = {e["id"]: e for e in package["entities"]}
    sources = {s["source_id"]: s for s in package["sources"]}
    evidence = {e["evidence_id"]: e for e in package["evidence"]}
    fragments, seen = [], set()

    def add(source, start, end):
        identity = (source["source_id"], start, end)
        if start >= end or identity in seen:
            return
        seen.add(identity)
        fragments.append({
            **{k: source.get(k) for k in ("source_id", "url", "author", "title")},
            "start": start, "end": end, "quote": source["text"][start:end],
            "time": source["occurred_at"],
        })

    # The original relationship binds these excerpts to the exact merge/Release.
    def add_relation(relation):
        for eid in relation["evidence_ids"]:
            e = evidence[eid]
            source = sources[e["source_id"]]
            start, end = e["start"], e["end"]
            if relation["type"] == "MergedAs" and source["kind"] == "api_response":
                needle = '\n  "merge_commit_sha":'
                hit = source["text"].find(needle, start, end)
                if hit != -1:
                    start, end = hit + 1, min(end, hit + 450)
            elif relation["type"] == "HasRelease" and source["kind"] == "api_response":
                tag = entities.get(relation["to_id"], {}).get("properties", {}).get("tag")
                if tag is not None:
                    needle = '"tag_name": ' + json.dumps(tag, ensure_ascii=False)
                    hit = source["text"].find(needle, start, end)
                    if hit != -1:
                        start = max(start, hit - 430)
                        end = min(end, hit + len(needle) + 1)
            add(source, start, min(end, start + 1150))

    if kind == "timeline":
        for relation in timeline[:6]:
            add_relation(relation)
        return fragments

    selected = {identity: entities[identity] for identity in seeds if identity in entities}
    if kind == "trace":
        wanted = {rid for path in paths for rid in path["relation_ids"]}
        relations = {r["id"]: r for r in package["relations"] if r["id"] in wanted}
        merges = [r for r in relations.values()
                  if r["type"] == "MergedAs" and r["from_id"] in selected]
        commits = {r["to_id"] for r in merges}
        changes = [r for r in relations.values()
                   if r["type"] == "Touches" and r["from_id"] in commits]
        for relation in (merges + changes)[:6]:
            add_relation(relation)

    threads = {e["properties"].get("number", e["key"]) for e in selected.values()
               if e["type"] in {"Issue", "PullRequest"}}
    if len(threads) == 1:
        pool = [s for s in sources.values() if s["kind"] in DISCUSSION_KINDS and s["text"]
                and (discussion_mapping(s) or {}).get("number") in threads]
        ranked = sorted(pool, key=lambda s: (
            s["trust_tier"] != "authoritative", -lexical_score(question, s), s["source_id"],
        ))
        for source in ranked[:4]:
            add(source, 0, min(len(source["text"]), 1800))
    return fragments


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
