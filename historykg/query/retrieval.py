"""Deterministic common-source retrieval; graph expansion never adds a new source pool."""

from __future__ import annotations

import re
from collections import defaultdict

from historykg import collector
from historykg.ids import evidence_id

METHOD_VERSION = "relore_common_rrf_graph_v1"
STOPWORDS = set("a an the is are was were to of for in on and or with what why how does did "
                "this that it which when where please tell explain".split())


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
    for subject in package["subjects"]:
        labels = [subject["display_name"], *subject.get("aliases", [])]
        labels = [str(s) for s in labels if s and not str(s).isdigit()]
        matches = [len(s) for s in labels if s.lower() in question.lower()]
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
                       limit: int = 40) -> list[dict]:
    scores = dict(retrieval["scores"])
    for rank, sid in enumerate(expansion, 1):
        scores[sid] = scores.get(sid, 0) + 1 / (60 + rank)
    sources = {s["source_id"]: s for s in package["sources"]}
    candidates = []
    for sid in sorted(scores, key=lambda s: (-scores[s], s))[:limit]:
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
