"""QueryResult assembly around actual graph paths and P4's single answerer."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from pydantic import ValidationError

from historykg.contracts import QueryRequest_v1, QueryResult_v1
from historykg.graph.store import GraphStore, read_package, settings
from historykg.io import write_json

from .frozen_index import verify_index
from .retrieval import (
    METHOD_VERSION,
    context_candidates,
    enrich_evidence,
    graph_sources,
    resolve_seeds,
    retrieve,
    seed_from_sources,
)


def _request(request) -> QueryRequest_v1:
    value = request.model_dump() if hasattr(request, "model_dump") else request
    parsed = QueryRequest_v1.model_validate(value)
    if not parsed.dataset_id.strip() or not parsed.question.strip():
        raise ValueError("请提供dataset_id和非空自然语言问题")
    return parsed


def prepare_query(request, *, config: dict | None = None) -> dict:
    """No LLM call. Return the exact candidates and paths used by both A and B."""
    started = time.perf_counter()
    req, cfg = _request(request), settings(config)
    system = cfg.get("system", "B")
    if system not in {"A", "B"}:
        raise ValueError("system只支持A或B")
    with GraphStore(cfg) as store:
        package = store.snapshot(req.dataset_id)
        if package is None:
            raise ValueError("数据集尚未就绪或不存在")
        if cfg.get("dataset_dir"):
            current = read_package(cfg["dataset_dir"])
            if current["fingerprint"] != package["fingerprint"]:
                raise ValueError("输入目录与已冻结图库版本不一致")
        seeds, gaps = resolve_seeds(req.question, package, req.seed_ids)
        if not package.get("retrieval_index"):
            raise ValueError("数据集缺少冻结relore索引，请从冻结包重新load")
        scoped_url = verify_index(
            cfg.get("database_url"), package["retrieval_index"], req.dataset_id
        )
        retrieved = retrieve(req.question, package, database_url=scoped_url)
        retrieved["backend"]["frozen_index"] = package["retrieval_index"]
        # This resolution is shared by A/B and never uses a reference or task label.
        resolved_seeds = seeds[:]
        source_seeds = (
            seed_from_sources(package, retrieved["source_ids"])
            if cfg.get("graph_expand_seeds", True) else []
        )
        seeds = list(dict.fromkeys(seeds + source_seeds))[:8]
        kinds = {"dependencies": ["Imports"], "compare": ["ChangesTo"]}.get(
            req.kind, sorted({r["type"] for r in package["relations"]})
        )
        paths = (
            store.paths(
                req.dataset_id,
                seeds,
                depth=int(cfg.get("graph_depth", 3)),
                limit=int(cfg.get("graph_path_limit", 50)),
                kinds=kinds,
            )
            if system == "B"
            else []
        )
        supported = True
        if req.kind in {"dependencies", "compare"}:
            supporting = [r for r in package["relations"] if r["type"] in kinds]
            if not supporting or not seeds:
                supported = False
                gaps.append("缺少所问范围的同快照Imports或双侧ChangesTo记录，未追加采集")
            elif system == "B" and not paths:
                supported = False
                gaps.append("已采关系未连接问题主体，不能以其他文件的记录代答")
            if req.kind == "compare":
                files = {e["id"] for e in package["entities"] if e["type"] == "File"}
                compared = set(resolved_seeds) & files
                if len(compared) < 2 or not any(
                    r["from_id"] in compared and r["to_id"] in compared for r in supporting
                ):
                    supported = False
                    gaps.append("问题没有唯一确定已采且通过ChangesTo相连的两侧文件快照")
        if req.kind == "timeline" and not any(r.get("occurred_at") for r in package["relations"]):
            supported = False
            gaps.append("当前冻结窗口缺少可定位事件时间")
        expansion = graph_sources(package, paths)
        candidates = context_candidates(
            package, retrieved, expansion, question=req.question
        )
    relation_by_id = {r["id"]: r for r in package["relations"]}
    evidence_by_id = {e["evidence_id"]: e for e in package["evidence"]}
    source_by_id = {s["source_id"]: s for s in package["sources"]}
    path_evidence_ids = sorted({eid for p in paths for rid in p["relation_ids"]
                                for eid in relation_by_id[rid]["evidence_ids"]})
    path_evidence = [enrich_evidence(evidence_by_id[eid],
                                   source_by_id[evidence_by_id[eid]["source_id"]])
                     for eid in path_evidence_ids]
    for p in paths:
        p["evidence_ids"] = sorted({eid for rid in p["relation_ids"]
                                    for eid in relation_by_id[rid]["evidence_ids"]})
        p["relations"] = [relation_by_id[r] for r in p["relation_ids"]]
        entity_by_id = {e["id"]: e for e in package["entities"]}
        p["entities"] = [entity_by_id[identity] if identity in entity_by_id else {
            "id": identity, "dataset_id": req.dataset_id, "type": "SourceDocument",
            "properties": {"title": source_by_id[identity].get("title")
                           or source_by_id[identity]["kind"],
                           "url": source_by_id[identity]["url"]},
        } for identity in p["entity_ids"]]
    timeline = sorted((r for r in package["relations"] if r["occurred_at"]),
                      key=lambda r: (r["occurred_at"], r["id"])) if req.kind == "timeline" else []
    return dict(request=req.model_dump(), system=system, method_version=METHOD_VERSION,
                dataset_fingerprint=package["fingerprint"], seed_ids=seeds,
                status="ok" if supported else "unsupported", candidates=candidates,
                paths=paths, path_evidence=path_evidence, retrieval=retrieved,
                gaps=[*package["manifest"].get("gaps", []), *gaps], timeline=timeline,
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
            base.update(status="empty", gaps=[*base["gaps"], "共同来源池中未找到可用证据"])
        else:
            # Injected answerer is for deterministic tests; production always uses P4.
            answerer = cfg.get("answerer")
            if answerer is None:
                from historykg.llm import answer_question
                answerer = answer_question
            answer_cfg = dict(cfg.get("answer") or {})
            answer_cfg["context_characters"] = 12000
            answer = answerer(
                dataset_id=req.dataset_id,
                repo=next(iter(prepared["source_by_id"].values()))["repo"],
                question=req.question, context=prepared["candidates"], config=answer_cfg,
                budget=cfg.get("budget") or {},
                output_root=cfg.get("answer_output_root") or answer_cfg.get("output_root")
                or Path(prepared["dataset_dir"]) / "llm",
            )
            audit["answer"] = answer
            base["usage"] = answer.get("usage", {})
            base["model_run_id"] = answer.get("run_id")
            if answer["status"] not in {"ok", "empty"}:
                base.update(status="error", error={"code": "answer_failed",
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
                for claim in answer.get("claims", []):
                    if not claim.get("text") or not claim.get("evidence_ids") or any(
                        eid not in answer_evidence for eid in claim["evidence_ids"]
                    ):
                        raise ValueError("回答断言缺少可见证据")
                evidence.update(answer_evidence)
                base.update(status="ok" if answer.get("claims") else "empty",
                            claims=answer.get("claims", []), evidence=list(evidence.values()),
                            gaps=[*base["gaps"], *answer.get("gaps", [])])
                if not base["claims"] and not base["gaps"]:
                    base["gaps"] = ["现有证据不足以支持回答"]
        base["timings_ms"]["total"] = round((time.perf_counter() - started) * 1000, 3)
        base["run_id"] = run_id
        base["system"] = prepared["system"]
        base["timeline"] = prepared["timeline"]
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
                                                     "message": "图、检索或回答服务失败"})
    return QueryResult_v1(**base)
