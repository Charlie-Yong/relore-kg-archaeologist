"""Run from repository root: python -m streamlit run app/main.py."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

import streamlit as st
from pydantic import ValidationError

from app import backend
from historykg.contracts import STAGES, BuildJob_v1, QueryResult_v1

STAGE_NAMES = dict(zip(STAGES, ["发现仓库", "采集讨论", "分析代码与版本", "抽取决定与理由",
                              "校验原文和关系", "建立检索与图谱"], strict=True))
STATUS_NAMES = {"queued": "等待构建", "running": "正在构建", "ready": "已就绪",
                "partial": "部分资料可查询", "failed": "构建失败", "unsupported": "暂不支持",
                "blocked": "构建暂停"}


def show_gaps(gaps):
    if gaps:
        with st.expander(f"覆盖缺口与限制（{len(gaps)}）", expanded=True):
            reasons = Counter(g.get("reason", "其他记录") for g in gaps if isinstance(g, dict))
            names = {"explicit_reference_over_limit": "关联讨论超出本次采集上限",
                     "external_project": "涉及其他项目", "out_of_scope": "超出本次范围",
                     "issue_timeline_unread": "Issue事件记录未完整读取",
                     "release_reachability_unknown": "尚未确认提交可达的版本",
                     "external_or_unresolved": "外部依赖或尚未解析的导入",
                     "import_target_not_collected": "未采集的导入目标文件",
                     "unresolved_subject": "主体尚未唯一确定"}
            for reason, count in reasons.items():
                st.write(f"{names.get(reason, reason)}：{count} 项")
            for gap in gaps:
                if isinstance(gap, str):
                    st.write(gap)
            if reasons:
                with st.expander("逐项缺口详情"):
                    st.json([g for g in gaps if isinstance(g, dict)], expanded=False)


def show_evidence(evidence, *, title="原文证据"):
    if not evidence:
        return
    st.subheader(title)
    for number, item in enumerate(evidence, 1):
        st.markdown(f'<a id="evidence-{number}"></a>', unsafe_allow_html=True)
        with st.expander(f"证据 {number} · {item.get('kind', '冻结原文')}", expanded=False):
            st.code(item["quote"], language=None, wrap_lines=True)
            if item.get("url"):
                st.link_button("打开原始来源", item["url"])
            st.caption(f"原文位置 [{item['start']}, {item['end']}) · Unicode 字符")
            if item.get("author") or item.get("time"):
                st.caption(f"作者：{item.get('author') or '未知'} · "
                           f"时间：{item.get('time') or '未知'}")
            st.caption(f"证据编号：{item['evidence_id']}")
            st.caption(f"来源编号：{item['source_id']}")
            st.caption(f"冻结数据版本：{item['dataset_id']}")


def show_paths(paths, evidence):
    if not paths:
        return
    st.subheader("已有关系链")
    st.caption("关系链呈现当前数据中的关联；每种关系保留各自含义。")
    evidence_by_id = {e["evidence_id"]: e for e in evidence}
    for index, path in enumerate(paths, 1):
        with st.expander(f"关系链 {index} · {len(path.get('relation_ids', []))} 条关系"):
            entities = {e["id"]: e for e in path.get("entities", [])}

            def label(identity, entities=entities):
                entity = entities.get(identity, {})
                props = entity.get("properties", {})
                return (entity.get("display_name") or props.get("display_name")
                        or props.get("title") or props.get("path")
                        or (f"{entity['type']} {entity.get('key', '')}" if entity else identity))

            relations = path.get("relations", [])
            if relations:
                for relation in relations:
                    st.write(f"{label(relation['from_id'])} → **{relation['type']}** → "
                             f"{label(relation['to_id'])}")
                    st.caption(f"依据方法：{relation.get('method', '未提供')} · "
                               f"事件时间：{relation.get('occurred_at') or '未知'}")
                    for eid in relation.get("evidence_ids", []):
                        item = evidence_by_id.get(eid)
                        if item and item.get("url"):
                            st.markdown(f"[关系原文]({item['url']}) · {item['quote']}")
            else:
                st.write(" → ".join(map(label, path.get("entity_ids", []))))
                st.caption("后端未提供关系标签；详细标识保留在响应中。")
            with st.expander("关系数据详情"):
                st.json(path, expanded=False)


def show_result(result):
    value = QueryResult_v1.model_validate(result).model_dump(mode="json")
    status = value["status"]
    {"ok": st.success, "empty": st.info, "unsupported": st.warning, "error": st.error}[status](
        {"ok": "查询已返回", "empty": "本次数据范围未返回可支持答案的记录",
         "unsupported": "当前资料或功能暂不支持这次请求", "error": "查询服务失败"}[status])
    evidence_index = {item["evidence_id"]: index
                      for index, item in enumerate(value["evidence"], 1)}
    # The answer body is exactly every claim, in order. No additional summary.
    for claim in value["claims"]:
        st.write(claim["text"])
        citations = [f"[证据 {evidence_index[e]}](#evidence-{evidence_index[e]})"
                     if e in evidence_index else f"未返回：{e}"
                     for e in claim.get("evidence_ids", [])]
        st.markdown("对应证据：" + ("、".join(citations) or "未提供"))
    show_gaps(value["gaps"])
    if value["error"]:
        st.write("请稍后重试，或由安装者检查检索、图数据库和模型配置。")
    show_evidence(value["evidence"])
    show_paths(value["paths"], value["evidence"])
    with st.expander("本次查询详情"):
        st.json(value, expanded=False)


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
    show_gaps(job["gaps"])
    if job["error"]:
        error = job["error"]
        st.error(error.get("message") or error.get("code") or "后端返回了构建错误。")
    with st.expander("任务详情（诊断）"):
        # Local paths and backend connection configuration are not sent to the UI.
        st.json({k: job[k] for k in ("job_id", "dataset_id", "profile_version", "status",
                 "stage", "created_at", "updated_at", "usage", "resume_from")}, expanded=False)
    return status in {"ready", "partial"} and bool(job["dataset_id"])


def question_form(job):
    with st.form("question_form"):
        question = st.text_input("想了解这个项目的哪段历史？", placeholder="用自然语言提问")
        with st.expander("查看已有时间线、依赖或版本关系"):
            kind = st.selectbox("查询方式",
                                ["search", "trace", "timeline", "dependencies", "compare"],
                                format_func=lambda k: {"search": "问答", "trace": "关系追溯",
                                "timeline": "时间线", "dependencies": "文件依赖",
                                "compare": "已采版本比较"}[k])
        submitted = st.form_submit_button("查询")
    if submitted and question.strip():
        with st.spinner("检索当前已建数据并核对证据…"):
            try:
                result = backend.ask(job["dataset_id"], question.strip(), kind)
                st.session_state["answer"] = (job["dataset_id"], result)
            except Exception:
                st.error("查询调用失败，请由安装者检查服务连接。")
                st.session_state.pop("answer", None)
    saved = st.session_state.get("answer")
    if saved and saved[0] == job["dataset_id"]:
        show_result(saved[1])


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
    st.title("项目历史知识图谱")
    st.write("输入公开 GitHub Python 仓库链接，自动整理有限历史资料，再通过原文和关系链回答问题。")
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
                for response in replay["queries"]:
                    if response["dataset_id"] != job["dataset_id"]:
                        raise ValueError("重放数据版本不一致")
                    st.markdown(f"**问题：{response['query']['question']}**")
                    show_result(response)
            with st.expander("冻结响应来源记录"):
                st.json(replay.get("provenance", {}), expanded=False)
        except (KeyError, ValueError, OSError, ValidationError):
            st.error("冻结结果文件无法核验，请由安装者检查备份。")
        return
    if "job_id" not in st.session_state:
        existing = st.query_params.get("job") or os.environ.get("HISTORYKG_DEMO_JOB_ID")
        if existing:
            st.session_state["job_id"] = existing
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
