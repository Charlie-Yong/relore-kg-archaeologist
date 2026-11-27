"""QueryResult assembly around actual graph paths and P4's single answerer."""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

from pydantic import ValidationError

from historykg.contracts import QueryRequest_v1, QueryResult_v1
from historykg.graph.store import GraphStore, read_package, settings
from historykg.ingest.github import FULL_HISTORY
from historykg.io import write_json

from .frozen_index import (
    fetch_frozen_sources,
    fetch_git_diff_sources,
    frozen_source_ids,
    has_frozen_sources,
    verify_index,
)
from .history_evidence import (
    SNAPSHOT,
    decision_passages,
    decision_paths,
    historical_passages,
    search_intent,
    targeted_paths,
)
from .retrieval import (
    METHOD_VERSION,
    NUMBER_PATTERN,
    PATH_PATTERN,
    context_candidates,
    enrich_evidence,
    external_github_references,
    focused_history_context,
    github_object_references,
    graph_sources,
    history_scope_seeds,
    resolve_seeds,
    retrieve,
    seed_from_sources,
)

REPOSITORY_TIMELINE_PATTERN = re.compile(
    r"(?:全仓|全仓库|全项目|整个仓库|整个项目|全部仓库|全部项目|"
    r"repository[\s-]+(?:wide|timeline)|"
    r"(?:whole|entire|full)\s+(?:the\s+)?(?:repository|repo)"
    r"(?:\s+(?:history|timeline))?|"
    r"all\s+(?:the\s+)?(?:repository|repo)"
    r"(?:\s+(?:history|events|timeline))?|"
    r"(?:本仓库|这个仓库).{0,8}(?:完整|全部|所有).{0,4}(?:时间线|事件|历史))",
    re.IGNORECASE,
)


def _request(request) -> QueryRequest_v1:
    value = request.model_dump() if hasattr(request, "model_dump") else request
    parsed = QueryRequest_v1.model_validate(value)
    if not parsed.dataset_id.strip() or not parsed.question.strip():
        raise ValueError("请提供dataset_id和非空自然语言问题")
    return parsed


def _repository_wide_timeline_requested(question: str) -> bool:
    return bool(REPOSITORY_TIMELINE_PATTERN.search(question))


def _blocked_external_retrieval(references: list[dict]) -> dict:
    urls = [reference["url"] for reference in references]
    return {
        "source_ids": [],
        "scores": {},
        "origins": {},
        "raw_discussion": {
            "status": "skipped",
            "hits": [],
            "reason": "external_project",
            "references": urls,
        },
        "mapped_hits": [],
        "backend": {
            "discussion": "skipped_external_project",
            "adapter": "external_scope_block",
            "visible_source_ids": [],
        },
    }


def _timeline_relations(package: dict, subject_ids: set[str], paths: list[dict],
                        *, full_repository: bool) -> list[dict]:
    events = sorted((relation for relation in package["relations"]
                     if relation.get("occurred_at")),
                    key=lambda relation: (relation["occurred_at"], relation["id"]))
    if full_repository:
        return events
    path_relation_ids = {
        relation_id
        for path in paths
        for relation_id in path["relation_ids"]
    }
    return [
        relation for relation in events
        if relation["id"] in path_relation_ids
        or relation["from_id"] in subject_ids
        or relation["to_id"] in subject_ids
    ]


def _hydrate_cypher_package(store, dataset_id: str, meta: dict, scoped_url: str | None, *,
                            question: str, intent: str | None, scope_kind: str,
                            req: QueryRequest_v1) -> dict:
    """Build a minimal in-memory view using only indexed Neo4j/SQLite lookups
    (never full snapshot)."""
    repo = meta["manifest"]["repo"]
    pkg = {
        "manifest": meta["manifest"],
        "subjects": meta["subjects"],
        "dataset_dir": meta["dataset_dir"],
        "fingerprint": meta["fingerprint"],
        "retrieval_index": meta.get("retrieval_index"),
        "entities": [],
        "relations": [],
        "evidence": [],
        "sources": None,
        "visible_source_ids": [],
    }
    entity_map = {}
    local_numbers = {int(a or b) for a, b in NUMBER_PATTERN.findall(question)}
    for ref in github_object_references(question):
        if ref["repo"] == repo.casefold():
            local_numbers.add(ref["number"])
    if local_numbers:
        for ent in store.fetch_entities(
            dataset_id, types=["Issue", "PullRequest"], numbers=sorted(local_numbers)
        ):
            entity_map[ent["id"]] = ent
    if scope_kind == "timeline" or intent in {"release", "membership"}:
        for ent in store.fetch_entities(dataset_id, types=["Release"]):
            entity_map[ent["id"]] = ent
        for ent in store.fetch_entities(dataset_id, types=["Project"]):
            entity_map[ent["id"]] = ent
    file_paths = sorted({p for p in PATH_PATTERN.findall(question)})
    if file_paths:
        for ent in store.fetch_entities(dataset_id, types=["File"], paths=file_paths):
            entity_map[ent["id"]] = ent
    elif scope_kind in {"dependencies", "compare"}:
        for ent in store.fetch_entities(dataset_id, types=["File"]):
            entity_map[ent["id"]] = ent
    ext_tokens = sorted(
        {t for t in re.findall(r"[a-z_][a-z_0-9.]*", question.lower()) if len(t) >= 2}
    )
    if ext_tokens and hasattr(store, "fetch_extended_subjects"):
        for ent in store.fetch_extended_subjects(dataset_id, ext_tokens):
            entity_map[ent["id"]] = ent
    if req.seed_ids:
        for ent in store.fetch_entities(dataset_id, ids=req.seed_ids):
            entity_map[ent["id"]] = ent
    pkg["entities"] = list(entity_map.values())
    if scoped_url is not None:
        all_sids = frozen_source_ids(scoped_url)
        pkg["visible_source_ids"] = all_sids
        if len(all_sids) <= 500:
            pkg["sources"] = fetch_frozen_sources(scoped_url)
    return pkg


def _sources_for_passages(scoped_url: str, repo: str, intent: str | None,
                          numbers: set[str], commit_shas: set[str],
                          extra_ids: set[str]) -> list[dict]:
    collected = {}
    if extra_ids:
        for s in fetch_frozen_sources(scoped_url, ids=sorted(extra_ids)):
            collected[s["source_id"]] = s
    if intent in {"release", "membership"}:
        for s in fetch_frozen_sources(
            scoped_url,
            url_prefixes=[f"https://api.github.com/repos/{repo}/releases"],
        ):
            collected[s["source_id"]] = s
    if intent == "membership":
        for s in fetch_frozen_sources(scoped_url, kinds=["git_output"]):
            collected[s["source_id"]] = s
    if intent == "code":
        for s in fetch_frozen_sources(
            scoped_url,
            url_prefixes=[f"https://api.github.com/repos/{repo}/git/ref/heads/"],
        ):
            collected[s["source_id"]] = s
        for s in fetch_frozen_sources(scoped_url, kinds=["code"]):
            collected[s["source_id"]] = s
    if intent in {"membership", "change", "decision"}:
        pr_nums = set(numbers)
        prefixes = [
            f"https://api.github.com/repos/{repo}/pulls/{n}" for n in sorted(pr_nums)
        ] + [
            f"https://api.github.com/repos/{repo}/issues/{n}" for n in sorted(pr_nums)
        ] + [
            f"https://github.com/{repo}/pull/{n}" for n in sorted(pr_nums)
        ] + [
            f"https://github.com/{repo}/issues/{n}" for n in sorted(pr_nums)
        ]
        if prefixes:
            for s in fetch_frozen_sources(scoped_url, url_prefixes=prefixes):
                collected[s["source_id"]] = s
        if intent in {"change", "decision"} and commit_shas:
            for s in fetch_git_diff_sources(scoped_url, sorted(commit_shas)):
                collected[s["source_id"]] = s
    return list(collected.values())


def prepare_query(request, *, config: dict | None = None) -> dict:
    """Return exact candidates and paths via Cypher subgraph traversal (or snapshot fallback)."""
    started = time.perf_counter()
    req, cfg = _request(request), settings(config)
    system = cfg.get("system", "B")
    if system not in {"A", "B"}:
        raise ValueError("system只支持A或B")
    with GraphStore(cfg) as store:
        use_cypher = (
            cfg.get("query_mode", "cypher_subgraph") != "snapshot"
            and hasattr(store, "dataset_meta")
        )
        meta = store.dataset_meta(req.dataset_id) if use_cypher else None
        if meta is None:
            use_cypher = False
        if use_cypher:
            package_meta = meta
            full = package_meta["manifest"].get("profile_version") == FULL_HISTORY
            if cfg.get("dataset_dir"):
                current = read_package(cfg["dataset_dir"])
                if current["fingerprint"] != package_meta["fingerprint"]:
                    raise ValueError("输入目录与已冻结图库版本不一致")
            intent = search_intent(req.question) if full and req.kind == "search" else None
            question = SNAPSHOT.sub("", req.question) if intent else req.question
            scope_kind = "timeline" if intent == "release" else req.kind
            external_references = external_github_references(
                req.question, package_meta["manifest"]["repo"]
            )
            scoped_url = None
            if not external_references:
                if not package_meta.get("retrieval_index"):
                    raise ValueError("数据集缺少冻结讨论索引，请从冻结包重新导入（load）。")
                scoped_url = verify_index(
                    cfg.get("database_url"), package_meta["retrieval_index"], req.dataset_id
                )
                if not has_frozen_sources(scoped_url):
                    use_cypher = False
        if not use_cypher:
            package = store.snapshot(req.dataset_id)
            if package is None:
                raise ValueError("数据集尚未就绪或不存在")
            full = package["manifest"].get("profile_version") == FULL_HISTORY
            if cfg.get("dataset_dir"):
                current = read_package(cfg["dataset_dir"])
                if current["fingerprint"] != package["fingerprint"]:
                    raise ValueError("输入目录与已冻结图库版本不一致")
            intent = search_intent(req.question) if full and req.kind == "search" else None
            question = SNAPSHOT.sub("", req.question) if intent else req.question
            scope_kind = "timeline" if intent == "release" else req.kind
            external_references = external_github_references(
                req.question, package["manifest"]["repo"]
            )
            scoped_url = None
        else:
            package = _hydrate_cypher_package(
                store, req.dataset_id, package_meta, scoped_url,
                question=question, intent=intent, scope_kind=scope_kind, req=req,
            )

        scope_seeds = history_scope_seeds(question, scope_kind, package) if (
            full and not req.seed_ids
        ) else []
        seeds, gaps = (
            (scope_seeds, []) if scope_seeds else resolve_seeds(question, package, req.seed_ids)
        )
        resolved_seeds = seeds[:]
        retrieval_notices = []
        timeline_scope = None
        timeline_subject_ids = []
        if external_references:
            gaps = [
                gap for gap in gaps
                if not (isinstance(gap, dict) and gap.get("reason") == "external_project")
            ]
            gaps.append({
                "reason": "external_project",
                "message": "问题明确引用仓库外对象；已阻断本库检索和回答",
                "references": [reference["url"] for reference in external_references],
            })
            retrieved = _blocked_external_retrieval(external_references)
            paths, candidates, timeline = [], [], []
            supported = False
            if use_cypher:
                package["sources"] = package.get("sources") or []
        else:
            if not use_cypher:
                if not package.get("retrieval_index"):
                    raise ValueError("数据集缺少冻结讨论索引，请从冻结包重新导入（load）。")
                scoped_url = verify_index(
                    cfg.get("database_url"), package["retrieval_index"], req.dataset_id
                )
            retrieved = retrieve(
                question, package, database_url=scoped_url,
                scoped_url=scoped_url if use_cypher else None,
            )
            retrieved["backend"]["frozen_index"] = package["retrieval_index"]
            if cfg.get("graph_expand_seeds", True) and intent not in {"release", "code"}:
                if use_cypher and hasattr(store, "seed_entities_by_sources"):
                    source_seeds = store.seed_entities_by_sources(
                        req.dataset_id, retrieved["source_ids"]
                    )
                    if not source_seeds:
                        source_seeds = seed_from_sources(package, retrieved["source_ids"])
                else:
                    source_seeds = seed_from_sources(package, retrieved["source_ids"])
            else:
                source_seeds = []
            seeds = list(dict.fromkeys(seeds + source_seeds))[:8]
            timeline_subject_ids = (
                resolved_seeds if req.kind == "timeline" and resolved_seeds else seeds
            )
            default_kinds = (
                package_meta.get("relation_types")
                if use_cypher
                else sorted({r["type"] for r in package["relations"]})
            )
            kinds = {"dependencies": ["Imports"], "compare": ["ChangesTo"]}.get(
                req.kind, default_kinds
            )
            if full and req.kind == "timeline" and not use_cypher:
                kinds = sorted({r["type"] for r in package["relations"] if r.get("occurred_at")})
            path_limit = int(cfg.get("graph_path_limit", 50))
            graph_depth = int(cfg.get("graph_depth", 3))
            if req.kind == "timeline" and scope_seeds:
                graph_depth = 1
            if use_cypher and req.kind == "timeline" and full:
                tl_rels = store.fetch_relations(req.dataset_id, has_occurred_at=True)
                kinds = sorted({r["type"] for r in tl_rels})
            paths = (
                store.paths(
                    req.dataset_id,
                    timeline_subject_ids if req.kind == "timeline" else seeds,
                    depth=graph_depth,
                    limit=path_limit,
                    kinds=kinds,
                )
                if system == "B"
                else []
            )
            if full and system == "B" and req.kind == "trace" and resolved_seeds:
                if use_cypher:
                    seed_ents = store.fetch_entities(req.dataset_id, ids=resolved_seeds)
                else:
                    seed_ents = package["entities"]
                pr_ids = {e["id"] for e in seed_ents if e["type"] == "PullRequest"}
                chosen_prs = sorted(pr_ids.intersection(resolved_seeds))
                if chosen_prs:
                    direct = store.paths(
                        req.dataset_id, chosen_prs, depth=min(2, graph_depth),
                        limit=min(15, path_limit),
                        kinds=["MergedAs", "Touches", "Closes", "ClaimsToClose"],
                    )
                    distinct = {}
                    for path in [*direct, *paths]:
                        key = tuple(sorted(path["relation_ids"]))
                        distinct.setdefault(key, path)
                    paths = list(distinct.values())[:path_limit]
            targeted = []
            if intent == "decision" and system == "B":
                if use_cypher:
                    decs = store.fetch_entities(req.dataset_id, types=["Decision"])
                    subj_ids = sorted({
                        d["properties"]["subject_id"]
                        for d in decs if d["properties"].get("subject_id")
                    })
                    subjs = store.fetch_entities(req.dataset_id, ids=subj_ids)
                    light_rels = [
                        *store.fetch_relations(
                            req.dataset_id, types=["ClaimsToClose", "Closes", "MergedAs"],
                            from_ids=subj_ids,
                        ),
                        *store.fetch_relations(
                            req.dataset_id, types=["ClaimsToClose", "Closes", "MergedAs"],
                            to_ids=subj_ids,
                        ),
                    ]
                    dec_ids = [d["id"] for d in decs]
                    about_rels = store.fetch_relations(
                        req.dataset_id, types=["ABOUT", "EVIDENCED_BY"], from_ids=dec_ids
                    )
                    ev_ids = sorted({
                        eid
                        for d in decs
                        for eid in d["properties"].get("statement_evidence_ids", [])
                    })
                    dec_ev = store.fetch_evidence(req.dataset_id, ev_ids)
                    dec_pkg = {
                        "entities": [*decs, *subjs],
                        "relations": list(
                            {r["id"]: r for r in [*light_rels, *about_rels]}.values()
                        ),
                        "evidence": dec_ev,
                        "sources": fetch_frozen_sources(
                            scoped_url,
                            ids=sorted({e["source_id"] for e in dec_ev}),
                        ),
                    }
                    targeted = decision_paths(dec_pkg, question, include_change_paths=False)
                    chosen_subjs = sorted({
                        edge["to_id"]
                        for edge in about_rels
                        if edge["type"] == "ABOUT"
                        and edge["from_id"] in {p["entity_ids"][0] for p in targeted}
                    })
                    if chosen_subjs:
                        targeted = [
                            *targeted,
                            *store.targeted_cypher_paths(
                                req.dataset_id, chosen_subjs, "change", 3, 50
                            ),
                        ]
                else:
                    targeted = decision_paths(package, question)
                paths = [p for p in paths if not any(
                    n.startswith("Decision:") for n in p["entity_ids"]
                )]
                if not targeted:
                    notice = (
                        "冻结图谱未检索到匹配的 Decision 记录。"
                        "只有原文证明该事件存在时才可回答原因。"
                    )
                    retrieval_notices.append(notice)
                    gaps.append(notice)
                paths = [*targeted, *paths][:path_limit]
            if intent in {"release", "membership", "change"} and system == "B":
                if use_cypher:
                    targeted = store.targeted_cypher_paths(
                        req.dataset_id, resolved_seeds, intent, graph_depth, path_limit
                    )
                else:
                    targeted = targeted_paths(
                        package, resolved_seeds, intent, graph_depth, path_limit
                    )
                combined = {}
                for path in [*targeted, *paths]:
                    key = tuple(sorted(path["relation_ids"]))
                    combined.setdefault(key, path)
                paths = list(combined.values())[:path_limit]

            if use_cypher:
                # Hydrate ONLY the entities, relations, evidence and sources touched by
                # paths or supporting rules.
                if req.kind in {"dependencies", "compare"}:
                    supporting = store.fetch_relations(req.dataset_id, types=kinds)
                    package["relations"] = supporting
                else:
                    supporting = []
            else:
                supporting = (
                    [r for r in package["relations"] if r["type"] in kinds]
                    if req.kind in {"dependencies", "compare"}
                    else []
                )

            supported = True
            if req.kind in {"dependencies", "compare"}:
                if not supporting or not seeds:
                    supported = False
                    gaps.append(
                        "缺少所问范围的同快照Imports或双侧ChangesTo记录，"
                        "未追加采集"
                    )
                elif system == "B" and not paths:
                    supported = False
                    gaps.append(
                        "已采关系未连接问题主体，不能以其他文件的记录代答"
                    )
                if req.kind == "compare":
                    files = {e["id"] for e in package["entities"] if e["type"] == "File"}
                    compared = set(resolved_seeds) & files
                    if len(compared) < 2 or not any(
                        r["from_id"] in compared and r["to_id"] in compared for r in supporting
                    ):
                        supported = False
                        gaps.append(
                            "问题没有唯一确定已采且通过ChangesTo相连的"
                            "两侧文件快照"
                        )
            timeline = []
            if req.kind == "timeline":
                full_repository = _repository_wide_timeline_requested(req.question)
                timeline_scope = "repository" if full_repository else "related"
                if use_cypher:
                    events = sorted(
                        store.fetch_relations(req.dataset_id, has_occurred_at=True),
                        key=lambda r: (r["occurred_at"], r["id"]),
                    )
                    package["relations"] = events
                timeline = _timeline_relations(
                    package, set(timeline_subject_ids), paths,
                    full_repository=full_repository,
                )
                if not timeline:
                    supported = False
                    if (
                        any(r.get("occurred_at") for r in package["relations"])
                        if not use_cypher
                        else bool(store.fetch_relations(req.dataset_id, has_occurred_at=True))
                    ):
                        gaps.append(
                            "问题未确定时间线主体或相关路径；"
                            "如需全仓时间线，请明确要求全仓时间线"
                        )
                    else:
                        gaps.append("当前冻结窗口缺少可定位事件时间")

            if use_cypher:
                path_rids = sorted({rid for p in paths for rid in p["relation_ids"]})
                path_eids = sorted({eid for p in paths for eid in p["entity_ids"]})
                tl_eids = sorted({r[k] for r in timeline for k in ("from_id", "to_id")})
                all_rids = sorted(set(path_rids) | {r["id"] for r in timeline})
                all_ent_ids = sorted(
                    set(path_eids) | set(tl_eids) | set(resolved_seeds) | set(seeds)
                )
                rel_rows = store.fetch_relations(req.dataset_id, ids=all_rids)
                ent_rows = store.fetch_entities(req.dataset_id, ids=all_ent_ids)
                ev_ids = sorted({
                    *{eid for r in rel_rows for eid in r.get("evidence_ids", [])},
                    *{eid for e in ent_rows for eid in e.get("evidence_ids", [])},
                    *{
                        eid
                        for e in ent_rows
                        if e["type"] == "Decision"
                        for eid in (
                            e["properties"].get("statement_evidence_ids", [])
                            + e["properties"].get("rationale_evidence_ids", [])
                        )
                    },
                })
                ev_rows = store.fetch_evidence(req.dataset_id, ev_ids)
                needed_sids = {e["source_id"] for e in ev_rows}
                needed_sids.update(retrieved.get("source_ids", []))
                needed_sids.update(
                    eid for eid in path_eids if eid in set(package["visible_source_ids"])
                )
                nums = {
                    n
                    for p in paths
                    for n in p.get("entity_ids", [])
                    if n.startswith(("PullRequest:", "Issue:"))
                }
                pr_numbers = {
                    str(e["properties"].get("number", e["key"]))
                    for e in ent_rows
                    if e["id"] in nums or e["id"] in set(resolved_seeds)
                }
                for a, b in NUMBER_PATTERN.findall(question):
                    pr_numbers.add(a or b)
                commit_shas = {
                    e["properties"].get("sha", e["key"])
                    for e in ent_rows
                    if e["type"] == "Commit"
                }
                passage_sources = _sources_for_passages(
                    scoped_url,
                    package["manifest"]["repo"],
                    intent,
                    pr_numbers,
                    commit_shas,
                    needed_sids,
                )
                merged_sources = {s["source_id"]: s for s in (package["sources"] or [])}
                merged_sources.update(retrieved.get("matched_sources", {}))
                for s in passage_sources:
                    merged_sources[s["source_id"]] = s
                package["sources"] = list(merged_sources.values())
                package["entities"] = list(
                    {e["id"]: e for e in [*package["entities"], *ent_rows]}.values()
                )
                package["relations"] = list(
                    {r["id"]: r for r in [*package["relations"], *rel_rows]}.values()
                )
                package["evidence"] = ev_rows

            expansion = graph_sources(package, paths)
            candidates = context_candidates(
                package, retrieved, expansion, question=question
            )
            if intent == "decision":
                focal = decision_passages(package, question, targeted) if targeted else []
            else:
                focal = (
                    historical_passages(package, req.question, intent, targeted) if intent else []
                )
            if not focal and full and system == "B" and intent != "decision":
                focal = focused_history_context(
                    package, kind=req.kind, seeds=resolved_seeds, paths=paths, timeline=timeline,
                    question=req.question,
                )
            if focal:
                if intent == "release":
                    candidates = focal
                elif intent == "decision":
                    precise = {(c["source_id"], c["start"], c["end"]) for c in focal}
                    candidates = [*focal, *(c for c in candidates
                                   if (c["source_id"], c["start"], c["end"]) not in precise)]
                else:
                    prioritized = {item["source_id"] for item in focal}
                    candidates = [
                        *focal, *(c for c in candidates if c["source_id"] not in prioritized)
                    ]
    relation_by_id = {r["id"]: r for r in package["relations"]}
    evidence_by_id = {e["evidence_id"]: e for e in package["evidence"]}
    source_by_id = {s["source_id"]: s for s in (package["sources"] or [])}
    path_evidence_ids = {eid for p in paths for rid in p["relation_ids"]
                         for eid in relation_by_id[rid]["evidence_ids"]}
    timeline_evidence_ids = {
        eid for relation in timeline for eid in relation.get("evidence_ids", [])
    }
    event_evidence = [enrich_evidence(evidence_by_id[eid],
                                     source_by_id[evidence_by_id[eid]["source_id"]])
                      for eid in sorted(path_evidence_ids | timeline_evidence_ids)
                      if eid in evidence_by_id and evidence_by_id[eid]["source_id"] in source_by_id]
    entity_by_id = {e["id"]: e for e in package["entities"]}
    for p in paths:
        p["evidence_ids"] = sorted({eid for rid in p["relation_ids"]
                                    for eid in relation_by_id[rid]["evidence_ids"]})
        p["relations"] = [relation_by_id[r] for r in p["relation_ids"]]
        p["entities"] = [entity_by_id[identity] if identity in entity_by_id else {
            "id": identity, "dataset_id": req.dataset_id, "type": "SourceDocument",
            "properties": {"title": source_by_id.get(identity, {}).get("title")
                           or source_by_id.get(identity, {}).get("kind", "source"),
                           "url": source_by_id.get(identity, {}).get("url", "")},
        } for identity in p["entity_ids"]]
    timeline_entities = [
        {"id": identity, "type": entity_by_id[identity]["type"],
         "properties": {k: v for k, v in entity_by_id[identity]["properties"].items()
                        if k in {"display_name", "title", "path", "tag", "sha", "number",
                                 "login", "qualified_name"}}}
        for identity in sorted({r[k] for r in timeline for k in ("from_id", "to_id")})
        if identity in entity_by_id
    ]
    retrieved.pop("matched_sources", None)
    method_version = METHOD_VERSION + "_full_focal_v3" if full else METHOD_VERSION
    return dict(request=req.model_dump(), system=system, method_version=method_version,
                query_mode="cypher_subgraph" if use_cypher else "snapshot",
                repo=package["manifest"]["repo"],
                search_intent=intent, retrieval_notices=retrieval_notices,
                dataset_fingerprint=package["fingerprint"], seed_ids=seeds,
                status="ok" if supported else "unsupported", candidates=candidates,
                paths=paths, path_evidence=event_evidence, retrieval=retrieved,
                gaps=[*package["manifest"].get("gaps", []), *gaps], timeline=timeline,
                timeline_scope=timeline_scope, timeline_subject_ids=timeline_subject_ids,
                timeline_entities=timeline_entities,
                source_by_id=source_by_id, dataset_dir=package["dataset_dir"],
                timings_ms={"retrieve_graph": round((time.perf_counter() - started) * 1000, 3)})


def query(request, *, config: dict | None = None) -> QueryResult_v1:
    """Answer through P4 or return an explicit empty/unsupported/error result."""
    started, cfg = time.perf_counter(), settings(config)
    original = request.model_dump() if hasattr(request, "model_dump") else request
    dataset = original.get("dataset_id", "") if isinstance(original, dict) else ""
    base = dict(dataset_id=dataset, query=original, status="error", claims=[], evidence=[],
                paths=[], gaps=[], timings_ms={}, error=None)
    try:
        try:
            req = _request(request)
        except (ValueError, ValidationError, TypeError) as exc:
            base.update(status="unsupported", gaps=[str(exc)])
            return QueryResult_v1(**base)
        prepared = prepare_query(req, config=cfg)
        base.update(paths=prepared["paths"], evidence=prepared["path_evidence"],
                    gaps=prepared["gaps"], timings_ms=prepared["timings_ms"])
        audit = {k: v for k, v in prepared.items() if k not in {"source_by_id", "dataset_dir"}}
        run_id = "query-" + uuid.uuid4().hex
        output = Path(cfg.get("query_output_root") or
                      Path(prepared["dataset_dir"]) / "exports" / "queries") / run_id
        if prepared["status"] == "unsupported":
            base["status"] = "unsupported"
        elif not prepared["candidates"]:
            if prepared["timeline"]:
                base["status"] = "ok"
            else:
                base.update(
                    status="empty",
                    gaps=[*base["gaps"], "共同来源池中未找到可用证据"],
                )
        else:
            # Injected answerer is for deterministic tests; production always uses P4.
            answerer = cfg.get("answerer")
            if answerer is None:
                from historykg.llm import answer_question
                answerer = answer_question
            answer_cfg = dict(cfg.get("answer") or {})
            answer_mode = (req.filters or {}).get("answer_mode")
            if answer_mode == "fast":
                answer_cfg["citation_style"] = "passage_numbers"
            elif answer_mode == "deep":
                answer_cfg["thinking"] = "enabled"
                answer_cfg.setdefault("reasoning_effort", "max")
            if prepared.get("search_intent") in {"release", "membership", "code"}:
                answer_cfg.setdefault("citation_style", "passage_numbers")
            answer_cfg["context_characters"] = 12000
            if prepared.get("retrieval_notices"):
                answer_cfg["retrieval_notices"] = prepared["retrieval_notices"]
            answer = answerer(
                dataset_id=req.dataset_id,
                repo=prepared.get("repo") or next(iter(prepared["source_by_id"].values()))["repo"],
                question=req.question, context=prepared["candidates"], config=answer_cfg,
                budget=cfg.get("budget") or {},
                output_root=cfg.get("answer_output_root") or answer_cfg.get("output_root")
                or Path(prepared["dataset_dir"]) / "llm",
            )
            audit["answer"] = answer
            base["usage"] = answer.get("usage", {})
            base["model_run_id"] = answer.get("run_id")
            if answer["status"] not in {"ok", "empty"}:
                reason = answer.get("error")
                code = reason if reason in {
                    "provider_balance_exhausted", "provider_auth_failed",
                    "missing_deepseek_api_key",
                } else "answer_failed"
                base.update(status="error", error={"code": code,
                                                  "run_id": answer.get("run_id")})
            else:
                evidence = {e["evidence_id"]: e for e in base["evidence"]}
                # Claims may cite only evidence actually visible to the answerer.
                visible = answer.get("context", {}).get("fragments", prepared["candidates"])
                answer_evidence = {}
                for item in answer.get("evidence", []):
                    source = prepared["source_by_id"].get(item["source_id"])
                    if source is None or item["dataset_id"] != req.dataset_id or not (
                        0 <= item["start"] < item["end"] <= len(source["text"])
                        and source["text"][item["start"]:item["end"]] == item["quote"]
                    ):
                        raise ValueError("回答器返回无效来源/引文")
                    if not any(v["source_id"] == item["source_id"]
                               and v["start"] <= item["start"] < item["end"] <= v["end"]
                               for v in visible):
                        raise ValueError("回答器引用了最终上下文不可见的证据")
                    answer_evidence[item["evidence_id"]] = enrich_evidence(item, source)
                    passage = next((
                        c for c in prepared["candidates"] if c.get("detail_url")
                        and c["source_id"] == item["source_id"]
                        and c["start"] <= item["start"] < item["end"] <= c["end"]
                    ), None)
                    if passage:
                        answer_evidence[item["evidence_id"]].update(
                            detail_url=passage["detail_url"], context_note=passage["title"],
                        )
                for claim in answer.get("claims", []):
                    if not claim.get("text") or not claim.get("evidence_ids") or any(
                        eid not in answer_evidence for eid in claim["evidence_ids"]
                    ):
                        raise ValueError("回答断言缺少可见证据")
                evidence.update(answer_evidence)
                displayed = answer.get("claims") or prepared.get("timeline")
                base.update(status="ok" if displayed else "empty",
                            claims=answer.get("claims", []), evidence=list(evidence.values()),
                            gaps=[*base["gaps"], *answer.get("gaps", [])])
                if not base["claims"] and not base["gaps"]:
                    base["gaps"] = ["现有证据不足以支持回答"]
        base["timings_ms"]["total"] = round((time.perf_counter() - started) * 1000, 3)
        if "retrieve_graph" in base["timings_ms"]:
            base["timings_ms"]["answer_ms"] = round(
                max(0.0, base["timings_ms"]["total"] - base["timings_ms"]["retrieve_graph"]), 3
            )
        base["query_mode"] = prepared.get("query_mode", "snapshot")
        base["run_id"] = run_id
        base["system"] = prepared["system"]
        base["timeline"] = prepared["timeline"]
        base["timeline_scope"] = prepared["timeline_scope"]
        base["timeline_subject_ids"] = prepared["timeline_subject_ids"]
        base["timeline_entities"] = prepared.get("timeline_entities", [])
        write_json(output / "retrieval.json", audit)
        write_json(output / "result.json", base)
        base["artifacts"] = {"query_run": str(output)}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        base.update(status="error", claims=[], error={"code": "query_validation_or_io",
                                                     "type": type(exc).__name__,
                                                     "message": str(exc)})
    except Exception as exc:
        base.update(status="error", claims=[], error={"code": "query_service",
                                                     "type": type(exc).__name__,
                                                     "message": (
                                                         "图、检索或回答服务失败"
                                                     )})
    return QueryResult_v1(**base)
