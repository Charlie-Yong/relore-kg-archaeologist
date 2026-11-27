"""Run from repository root: python -m streamlit run app/main.py."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from app import backend
from app.visuals import RELATION_NAMES, chain_chart, label, ordered_paths, path_evidence
from historykg.contracts import STAGES, BuildJob_v1, QueryResult_v1

STAGE_NAMES = dict(zip(STAGES, ["发现仓库", "采集讨论", "分析代码与版本", "抽取决定与理由",
                              "校验原文和关系", "建立检索与图谱"], strict=True))
STATUS_NAMES = {"queued": "等待构建", "running": "正在构建", "ready": "已就绪",
                "partial": "部分资料可查询", "failed": "构建失败", "unsupported": "暂不支持",
                "blocked": "构建暂停"}


def show_gaps(gaps, *, instance, full_history=False):
    if gaps:
        with st.expander(f"覆盖缺口与限制（{len(gaps)}）", expanded=True):
            reasons = Counter(g.get("reason", "其他记录") for g in gaps if isinstance(g, dict))
            names = {"explicit_reference_over_limit": "关联讨论超出本次采集上限",
                     "external_project": "涉及其他项目", "out_of_scope": "超出本次范围",
                     "issue_timeline_unread": "Issue事件记录未完整读取",
                     "release_reachability_unknown": "尚未确认提交可达的版本",
                     "external_or_unresolved": "外部依赖或尚未解析的导入",
                     "import_target_not_collected": "未采集的导入目标文件",
                     "unresolved_subject": "主体尚未唯一确定",
                     "ast_parse_failed": "历史源码未通过静态解析",
                     "explicit_reference_unavailable": "本次公开清单未包含引用编号"}
            if full_history:
                names["explicit_reference_over_limit"] = names["explicit_reference_unavailable"]
            for reason, count in reasons.items():
                st.write(f"{names.get(reason, reason)}：{count} 项")
            for gap in gaps:
                if isinstance(gap, str):
                    st.write(gap)
            if reasons:
                with st.expander("逐项缺口详情", key=f"{instance}gaps", on_change="rerun") as panel:
                    if panel.open:
                        details = [g for g in gaps if isinstance(g, dict)]
                        if len(details) > 50:
                            reason = st.selectbox(
                                "按原因筛选", [None, *sorted(reasons)],
                                format_func=lambda r: names.get(r, r) if r else "全部",
                                key=f"{instance}gap-filter",
                            )
                            visible = [g for g in details if reason is None
                                       or g.get("reason", "其他记录") == reason]
                            st.caption(f"显示前 {min(50, len(visible))} 项，共 {len(visible)} 项")
                            st.download_button(
                                "下载全部缺口记录", json.dumps(details, ensure_ascii=False),
                                file_name="historykg-gaps.json", mime="application/json",
                                key=f"{instance}gap-download", on_click="ignore",
                            )
                            details = visible[:50]
                        st.json(details, expanded=False)


def show_evidence(evidence, *, title="原文证据", anchor_prefix="", relevant=()):
    if not evidence:
        return
    st.subheader(title)
    rows = list(enumerate(evidence, 1))
    if len(rows) > 30:
        retained = set(relevant)
        other = [number for number, item in rows if item["evidence_id"] not in retained]
        extra = st.selectbox("查看其余证据", [None, *other],
                             format_func=lambda n: f"证据 {n}" if n else "请选择",
                             key=f"{anchor_prefix}extra-evidence") if other else None
        rows = [(number, item) for number, item in rows
                if item["evidence_id"] in retained or number == extra]
    relevant_set = set(relevant)
    expanded_count = 0
    for number, item in rows:
        expand_default = False
        if relevant_set:
            if item["evidence_id"] in relevant_set and expanded_count < 2:
                expand_default = True
                expanded_count += 1
        elif expanded_count < 1:
            expand_default = True
            expanded_count += 1
        st.markdown(f'<a id="{anchor_prefix}evidence-{number}"></a>', unsafe_allow_html=True)
        with st.expander(
            f"证据 {number} · {item.get('kind', '冻结原文')}", expanded=expand_default
        ):
            st.code(item["quote"], language=None, wrap_lines=True)
            if item.get("context_note"):
                st.caption(item["context_note"])
            if item.get("url"):
                st.link_button("打开原始来源", item["url"])
            if item.get("detail_url") and item["detail_url"] != item.get("url"):
                st.link_button("核对对应的版本或提交", item["detail_url"])
            st.caption(f"原文位置 [{item['start']}, {item['end']}) · Unicode 字符")
            if item.get("author") or item.get("time"):
                st.caption(f"作者：{item.get('author') or '未知'} · "
                           f"时间：{item.get('time') or '未知'}")
            st.caption(f"证据编号：{item['evidence_id']}")
            st.caption(f"来源编号：{item['source_id']}")
            st.caption(f"冻结数据版本：{item['dataset_id']}")


def evidence_links(ids, evidence_index, anchor_prefix):
    return "、".join(
        f"[证据 {evidence_index[eid]}](#{anchor_prefix}evidence-{evidence_index[eid]})"
        for eid in dict.fromkeys(ids) if eid in evidence_index
    )


def show_relation_card(value, evidence_index, anchor_prefix):
    kind = value["query"].get("kind")
    title = (
        "文件依赖图"
        if kind == "dependencies"
        else "版本变化关系"
        if kind == "compare"
        else "证据关系图"
    )
    st.subheader(title)
    paths = ordered_paths(value["paths"], value["claims"], value["evidence"])
    if not paths:
        st.caption("本次查询没有返回可展开的关系链。")
        return []
    st.caption(f"{len(paths)} 条可查看的关系链 · 箭头表示原始关系方向")
    index = 0
    if len(paths) > 1:
        index = st.selectbox("选择关系链", range(len(paths)),
                             format_func=lambda i: f"关系链 {i + 1} · "
                             f"{len(paths[i].get('relation_ids', []))} 条关系",
                             key=f"{anchor_prefix}path")
    path = paths[index]
    if value["claims"]:
        related = path_evidence(path)
        cited = {eid for claim in value["claims"] for eid in claim.get("evidence_ids", [])}
        by_id = {item["evidence_id"]: item["source_id"] for item in value["evidence"]}
        if related & cited:
            st.caption("这条链包含答案直接引用的证据。")
        elif {by_id[e] for e in related if e in by_id} & {by_id[e] for e in cited if e in by_id}:
            st.caption("这条链与答案引用了同一份原文，引用段落可能不同。")
        else:
            st.caption("这条链展示已知关联。答案依据请查看结论卡片的引用。")
    chart = chain_chart(path)
    if chart is not None:
        st.altair_chart(chart, width="stretch", theme=None,
                        key=f"{anchor_prefix}chain-{index}", alt="知识图谱关系链")
    entities = {entity["id"]: entity for entity in path.get("entities", [])}
    all_evidence = []
    for relation in path.get("relations", []):
        left, right = relation["from_id"], relation["to_id"]
        kind = relation["type"]
        st.write(f"{label(entities.get(left, {}), left)} → **{RELATION_NAMES.get(kind, kind)}**"
                 f" → {label(entities.get(right, {}), right)}")
        strength = {
            "Closes": "官方API",
            "MergedAs": "官方API",
            "HasRelease": "官方API",
            "Merged": "官方API",
            "Touches": "Git实证", "ReachableIn": "Git实证", "ChangesTo": "Git实证",
            "Defines": "AST静态", "Imports": "AST静态",
            "ClaimsToClose": "文本声称", "MentionsPR": "文本声称",
            "Authored": "元数据", "ABOUT": "LLM抽取", "EVIDENCED_BY": "LLM抽取",
        }.get(kind, "图谱关系")
        citations = evidence_links(relation.get("evidence_ids", []), evidence_index, anchor_prefix)
        st.markdown(
            f"`{kind}` · [{strength}] · {citations}" if citations else f"`{kind}` · [{strength}]"
        )
        all_evidence.extend(relation.get("evidence_ids", []))
    if not path.get("relations"):
        st.caption("这条旧记录仅提供实体顺序，未提供关系方向和名称。")
        st.write(" · ".join(label(entities.get(e, {}), e) for e in path.get("entity_ids", [])))
    return all_evidence


def show_timeline(value, evidence_index, anchor_prefix):
    timeline = sorted(value.get("timeline", []),
                      key=lambda event: (event.get("occurred_at") or "", event["id"]))
    if not timeline:
        return []
    st.subheader("项目演化时间线")
    st.caption(f"按事件时间排序 · {len(timeline)} 个事件")
    page_size = 12
    page = 0
    if len(timeline) > page_size:
        page = st.selectbox("事件区间", range((len(timeline) + page_size - 1) // page_size),
                            format_func=lambda p: f"{p * page_size + 1}–"
                            f"{min((p + 1) * page_size, len(timeline))} / {len(timeline)}",
                            key=f"{anchor_prefix}timeline-page")
    events = timeline[page * page_size:(page + 1) * page_size]
    entities = {e["id"]: e for path in value["paths"] for e in path.get("entities", [])}
    entities.update({e["id"]: e for e in value.get("timeline_entities", [])})
    rows = []
    ids = []
    for event in events:
        left, right = event["from_id"], event["to_id"]
        ids.extend(event["evidence_ids"])
        rows.append({
            "时间": event["occurred_at"], "事件类型": event["type"],
            "起点": label(entities.get(left, {}), left),
            "终点": label(entities.get(right, {}), right),
            "证据": "、".join(str(evidence_index[eid]) for eid in event["evidence_ids"]
                            if eid in evidence_index),
        })
    st.table(rows)
    links = evidence_links(ids, evidence_index, anchor_prefix)
    if links:
        st.markdown(links)
    return ids


def show_result(result, *, instance="live", full_history=False):
    value = QueryResult_v1.model_validate(result).model_dump(mode="json")
    anchor_prefix = hashlib.sha256(json.dumps(
        [instance, value["dataset_id"], value["query"], value.get("run_id")],
        sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16] + "-"
    status = value["status"]
    evidence = value["evidence"]
    evidence_index = {item["evidence_id"]: index for index, item in enumerate(evidence, 1)}
    citation_ids = []
    st.divider()
    st.caption("HISTORYKG  /  溯源工作台")
    with st.container(border=True):
        st.caption("你的问题")
        st.write(value["query"].get("question") or "查询结果")
        if value.get("paths") or value.get("timeline"):
            st.markdown(f"[跳到可视化](#{anchor_prefix}visual)")
    timings = value.get("timings_ms") or {}
    if timings.get("total"):
        mode_text = "Cypher 按需子图" if value.get("query_mode") != "snapshot" else "全图快照"
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("图谱子图检索", f"{timings.get('retrieve_graph', 0):.0f} ms")
        m2.metric("模型有据问答", f"{timings.get('answer_ms', 0):.0f} ms")
        m3.metric("证据路径数", len(value.get("paths", [])))
        m4.metric("核验原文数", len(evidence))
        st.caption(f"检索架构：{mode_text} · 总耗时 {timings['total']:.0f} ms")
    answer, visual = st.columns([5, 4], gap="medium")
    with answer:
        st.subheader("回答")
        {"ok": st.success, "empty": st.info, "unsupported": st.warning, "error": st.error}[status](
            {"ok": "查询已返回", "empty": "本次数据范围未返回可支持答案的记录",
             "unsupported": "当前资料或功能暂不支持这次请求", "error": "查询服务失败"}[status])
        if value["error"]:
            if value["error"].get("code") == "provider_balance_exhausted":
                st.warning("DeepSeek 余额不足。本次查询已暂停。")
            elif value["error"].get("code") in {"provider_auth_failed", "missing_deepseek_api_key"}:
                st.warning("DeepSeek 凭据不可用。更新本机配置后可重试。")
            else:
                st.caption("请稍后重试，或检查检索、图数据库和模型配置。")
        for n, claim in enumerate(value["claims"], 1):
            with st.container(border=True):
                st.caption(f"结论 {n:02d}")
                st.write(claim["text"])
                ids = claim.get("evidence_ids", [])
                citation_ids.extend(ids)
                st.markdown(
                    evidence_links(ids, evidence_index, anchor_prefix) or "未返回可定位证据"
                )
    with visual, st.container(border=True):
        if value.get("paths") or value.get("timeline"):
            st.markdown(f'<a id="{anchor_prefix}visual"></a>', unsafe_allow_html=True)
        if value.get("timeline"):
            citation_ids.extend(show_timeline(value, evidence_index, anchor_prefix))
            if value["paths"]:
                with st.expander("查看关联路径"):
                    citation_ids.extend(show_relation_card(value, evidence_index, anchor_prefix))
        else:
            citation_ids.extend(show_relation_card(value, evidence_index, anchor_prefix))
    show_evidence(evidence, anchor_prefix=anchor_prefix, relevant=citation_ids)
    show_gaps(value["gaps"], instance=anchor_prefix, full_history=full_history)
    with st.expander("本次查询详情", key=f"{anchor_prefix}details", on_change="rerun") as panel:
        if panel.open:
            st.download_button(
                "下载完整查询记录", json.dumps(value, ensure_ascii=False), mime="application/json",
                file_name="historykg-query.json", key=f"{anchor_prefix}query-download",
                on_click="ignore",
            )
            st.json({**value, "gaps": value["gaps"][:50]}, expanded=False)


def show_job(job):
    job = BuildJob_v1.model_validate(job).model_dump(mode="json")
    status, stage = job["status"], job["stage"]
    st.subheader(f"{job['repo']} · {STATUS_NAMES[status]}")
    st.write(f"当前阶段：{STAGE_NAMES[stage]}")
    completed = job.get("completed_stages", [])
    if completed:
        st.write("已完成：" + " → ".join(STAGE_NAMES[s] for s in completed))
    if status in {"ready", "partial"}:
        st.success("已有可查询数据。回答受下列已采范围限制。")
    elif status in {"failed", "blocked"}:
        st.error("尚未发布可查询数据。" if status == "failed"
                 else "当前任务暂停，尚未发布可查询数据。")
    elif status == "unsupported":
        st.warning("当前仅支持可读取的公开 GitHub Python 仓库。")
    else:
        st.info("任务仍在运行；页面只读取进度，刷新不会重新启动构建。")
    if job["coverage"]:
        st.markdown("**实际覆盖**")
        coverage = job["coverage"]
        labels = {"sources": "冻结来源", "complete_units": "完整讨论", "file_snapshots": "文件快照"}
        for column, (key, label) in zip(st.columns(3), labels.items(), strict=True):
            column.metric(label, coverage.get(key, "未汇总"))
        st.caption("覆盖本次自动限定的资料范围；同一文件的不同提交分别计为快照。")
        time_range = coverage.get("time_range", {})
        if time_range:
            st.caption(f"已采记录时间：{time_range.get('earliest') or '未知'} 至 "
                       f"{time_range.get('latest') or '未知'}")
        with st.expander("覆盖清单与采集上限"):
            st.json(coverage, expanded=False)
    if job["counts"]:
        with st.expander("阶段产出记录"):
            st.json(job["counts"], expanded=True)
    show_gaps(job["gaps"], instance=f"{job['job_id']}-",
              full_history=job["profile_version"] == "full_history_v1")
    if job["error"]:
        error = job["error"]
        st.error(error.get("message") or error.get("code") or "后端返回了构建错误。")
    with st.expander("任务详情（诊断）"):
        # Local paths and backend connection configuration are not sent to the UI.
        st.json({k: job[k] for k in ("job_id", "dataset_id", "profile_version", "status",
                 "stage", "created_at", "updated_at", "usage", "resume_from")}, expanded=False)
    return status in {"ready", "partial"} and bool(job["dataset_id"])


def question_form(job):
    quick_examples = [
        ("为什么去掉 simplejson？", "决策原因"),
        ("PR #372 改了哪些文件？哪个正式版包含？", "改动追溯"),
        ("2.0.1 是哪天出的？", "版本发布"),
        ("为什么移除了 OAuth token 认证？", "假前提拒答"),
    ]
    with st.form("question_form"):
        question = st.text_input("想了解这个项目的哪段历史？", placeholder="用自然语言提问")
        with st.expander("查看已有时间线、依赖或版本关系"):
            kind = st.selectbox("查询方式",
                                ["search", "trace", "timeline", "dependencies", "compare"],
                                format_func=lambda k: {"search": "问答", "trace": "关系追溯",
                                "timeline": "时间线", "dependencies": "文件依赖",
                                "compare": "已采版本比较"}[k])
            answer_mode = st.radio(
                "回答模式",
                ["fast", "deep"],
                format_func=lambda m: (
                    "快速实证（推荐 · 秒级）" if m == "fast" else "深度思考（慢速复杂推理）"
                ),
                horizontal=True,
            )
        submitted = st.form_submit_button("查询")
    chosen_question = None
    if submitted and question.strip():
        chosen_question = question.strip()
    elif job.get("repo") == "pallets/itsdangerous":
        st.caption("快速演示示例（点击直接提问）：")
        cols = st.columns(len(quick_examples))
        for idx, (col, (ex_q, tag)) in enumerate(zip(cols, quick_examples, strict=True)):
            if col.button(tag, key=f"demo-ex-{idx}", help=ex_q):
                chosen_question = ex_q
    if chosen_question:
        with st.spinner("检索当前已建数据并核对证据…"):
            try:
                if answer_mode == "fast":
                    result = backend.ask(job["dataset_id"], chosen_question, kind)
                else:
                    result = backend.ask(
                        job["dataset_id"], chosen_question, kind, answer_mode=answer_mode
                    )
                st.session_state["answer"] = (job["dataset_id"], result)
            except Exception:
                st.error("查询调用失败，请由安装者检查服务连接。")
                st.session_state.pop("answer", None)
    saved = st.session_state.get("answer")
    if saved and saved[0] == job["dataset_id"]:
        show_result(saved[1], full_history=job["profile_version"] == "full_history_v1")


def show_frozen_dataset(directory):
    try:
        manifest = json.loads((Path(directory) / "manifest.json").read_text(encoding="utf-8"))
        dataset = {key: manifest[key] for key in ("dataset_id", "profile_version", "repo")}
        repo = manifest["repo"]
        source_count = len(manifest["sources"])
    except (OSError, ValueError, KeyError, TypeError):
        st.error("无法读取冻结数据的清单。请检查演示数据的位置。")
        return
    st.subheader(repo)
    frozen_at = manifest.get("retrieved_at")
    scope = f"冻结于 {frozen_at[:10]} · {source_count:,} 条来源" if frozen_at else (
        f"{source_count:,} 条冻结来源"
    )
    st.caption(scope)
    question_form(dataset)


@st.fragment(run_every="3s")
def current_job():
    job_id = st.session_state.get("job_id")
    if not job_id:
        return
    try:
        job = backend.get(job_id)
    except Exception:
        st.error("无法读取当前构建任务。请由安装者检查任务目录与服务配置。")
        return
    ready = show_job(job)
    if job["status"] in {"blocked", "failed"}:
        if st.button("继续构建", help="从后端已保存的阶段继续，不重新采集已完成资料。"):
            try:
                backend.resume(job_id)
                st.rerun(scope="fragment")
            except Exception:
                st.error("恢复失败，请由安装者检查后端配置。")
    if ready:
        question_form(job)


def main():
    st.set_page_config(page_title="项目历史知识图谱", page_icon="🔎", layout="wide")
    st.caption("HISTORYKG  /  开源项目考古")
    st.title("项目历史知识图谱")
    st.write("提问，查看答案、关系和 GitHub 原文。")
    replay_path = os.environ.get("HISTORYKG_REPLAY_FILE")
    if replay_path:
        try:
            replay = json.loads(Path(replay_path).read_text(encoding="utf-8"))
            mode = ("冻结真实结果重放" if replay.get("mode") == "real_public_query"
                    else "开发示例重放")
            st.warning(f"{mode} · 原响应保存时间：{replay['recorded_at']}")
            st.caption("本页展示保存的原始响应；当前不启动构建或模型查询。")
            job = BuildJob_v1.model_validate(replay["job"]).model_dump(mode="json")
            if show_job(job):
                for index, response in enumerate(replay["queries"]):
                    if response["dataset_id"] != job["dataset_id"]:
                        raise ValueError("重放数据版本不一致")
                    show_result(response, instance=f"replay-{index}",
                                full_history=job["profile_version"] == "full_history_v1")
            with st.expander("冻结响应来源记录"):
                st.json(replay.get("provenance", {}), expanded=False)
        except (KeyError, ValueError, OSError, ValidationError):
            st.error("冻结结果文件无法核验，请由安装者检查备份。")
        return
    frozen_directory = os.environ.get("HISTORYKG_DEMO_DATASET_DIR")
    if frozen_directory:
        show_frozen_dataset(frozen_directory)
        return
    existing = st.query_params.get("job")
    if not existing and "job_id" not in st.session_state:
        existing = os.environ.get("HISTORYKG_DEMO_JOB_ID")
    if existing and existing != st.session_state.get("job_id"):
        st.session_state["job_id"] = existing
        st.session_state.pop("answer", None)
    with st.form("repository_form"):
        url = st.text_input("仓库链接", placeholder="https://github.com/owner/repository")
        submitted = st.form_submit_button("开始整理")
    if submitted:
        try:
            job = backend.start(url.strip())
            st.session_state["job_id"] = job["job_id"]
            st.query_params["job"] = job["job_id"]
            st.session_state.pop("answer", None)
        except (ValueError, ValidationError):
            st.warning("暂不支持此输入，请填写公开 GitHub Python 仓库链接。")
        except Exception:
            st.error("构建服务暂不可用，请由安装者检查配置。")
    current_job()


if __name__ == "__main__":
    main()
