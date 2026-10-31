"""UI contract tests use explicit synthetic backend responses, never project answers."""

from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
APP = str(ROOT / "app/main.py")
JOB = dict(contract_version="1.4.1", job_id="a" * 32, repo="example/toy",
           profile_version="toy_v1", dataset_id="toy_v1", status="ready", stage="index_graph",
           created_at="2026-10-30T00:00:00Z", updated_at="2026-10-30T00:00:00Z",
           counts={"sources": 1}, coverage={"complete_units": 1}, gaps=[], usage={},
           artifacts={}, error=None, resume_from=None)
EVIDENCE = dict(evidence_id="toy-evidence", dataset_id="toy_v1", source_id="toy-source",
                start=0, end=12, quote="toy evidence", url="https://example.invalid/toy")


def result(status="ok", claims=None):
    return dict(contract_version="1.4.1", dataset_id="toy_v1",
                query={"question": "开发示例问题"}, status=status,
                claims=claims if claims is not None else [
                    {"text": "合成结论一", "evidence_ids": ["toy-evidence"]},
                    {"text": "合成结论二", "evidence_ids": ["toy-evidence"]}],
                evidence=[EVIDENCE], paths=[], gaps=["仅合成开发示例"], timings_ms={},
                error={"code": "synthetic_error"} if status == "error" else None)


def observed(job):
    test = AppTest.from_file(APP)
    test.session_state["job_id"] = job["job_id"]
    return test


@pytest.mark.parametrize("status", ["queued", "running", "blocked", "failed", "unsupported"])
def test_unready_job_does_not_offer_question(status):
    job = {**JOB, "status": status}
    with patch("app.backend.get", return_value=job), patch("app.backend.start") as start:
        test = observed(job).run()
        assert not test.exception
        assert [x.label for x in test.text_input] == ["仓库链接"]
        test.run()  # a page rerun only observes the persistent task
        start.assert_not_called()


@pytest.mark.parametrize("status", ["ready", "partial"])
def test_ready_and_partial_offer_question(status):
    job = {**JOB, "status": status}
    with patch("app.backend.get", return_value=job):
        test = observed(job).run()
        assert not test.exception
        assert len(test.text_input) == 2


def test_url_submit_and_refresh_use_same_task():
    with patch("app.backend.start", return_value=JOB) as start, \
         patch("app.backend.get", return_value=JOB) as get:
        test = AppTest.from_file(APP).run()
        test.text_input[0].set_value("https://github.com/example/toy")
        test.button[0].click().run()
        test.run()
        start.assert_called_once_with("https://github.com/example/toy")
        assert get.call_count >= 2
        assert test.query_params["job"] == JOB["job_id"]
        refreshed = AppTest.from_file(APP)
        refreshed.query_params["job"] = JOB["job_id"]
        refreshed.run()
        start.assert_called_once()


def test_resume_is_explicit_and_does_not_start():
    job = {**JOB, "status": "blocked"}
    with patch("app.backend.get", return_value=job), \
         patch("app.backend.resume", return_value=JOB) as resume, \
         patch("app.backend.start") as start:
        test = observed(job).run()
        next(b for b in test.button if b.label == "继续构建").click().run()
        resume.assert_called_once_with(job["job_id"])
        start.assert_not_called()


def test_task_link_switches_existing_session_and_clears_answer():
    other = {**JOB, "job_id": "b" * 32, "dataset_id": "other_dataset", "repo": "other/repo"}
    with patch("app.backend.get", side_effect=lambda jid: {JOB["job_id"]: JOB,
              other["job_id"]: other}[jid]) as get, patch("app.backend.start") as start:
        test = observed(JOB).run()
        test.session_state["answer"] = (JOB["dataset_id"], result())
        test.query_params["job"] = other["job_id"]
        test.run()
        assert not test.exception
        get.assert_called_with(other["job_id"])
        assert test.session_state["job_id"] == other["job_id"]
        assert "answer" not in test.session_state
        assert any(other["repo"] in x.value for x in test.subheader)
        assert not any("合成结论一" in x.value for x in test.markdown)
        start.assert_not_called()


def test_timeline_events_are_visible_with_evidence_numbers():
    response = result()
    response["timeline"] = [{"id": "event", "occurred_at": "2026-10-30T00:00:00Z",
                             "type": "MergedAs", "from_id": "pr", "to_id": "commit",
                             "evidence_ids": ["toy-evidence"]}]
    with patch("app.backend.get", return_value=JOB), \
         patch("app.backend.ask", return_value=response):
        test = observed(JOB).run()
        test.text_input[1].set_value("项目演化")
        test.selectbox[0].set_value("timeline")
        next(b for b in test.button if b.label == "查询").click().run()
        assert not test.exception
        rows = test.table[0].value
        assert rows.iloc[0]["事件类型"] == "MergedAs"
        assert rows.iloc[0]["时间"] == "2026-10-30T00:00:00Z"
        assert rows.iloc[0]["证据"] == "1"


@pytest.mark.parametrize("status, message", [
    ("ok", "查询已返回"), ("empty", "本次数据范围未返回可支持答案的记录"),
    ("unsupported", "当前资料或功能暂不支持这次请求"), ("error", "查询服务失败")])
def test_query_states_all_claims_and_evidence(status, message):
    response = result(status, claims=None if status == "ok" else [])
    with patch("app.backend.get", return_value=JOB), \
         patch("app.backend.ask", return_value=response) as ask:
        test = observed(JOB).run()
        test.text_input[1].set_value("开发示例问题")
        next(b for b in test.button if b.label == "查询").click().run()
        assert not test.exception
        ask.assert_called_once_with("toy_v1", "开发示例问题", "search")
        rendered = "\n".join(x.value for x in test.markdown)
        notices = [x.value for category in [test.success, test.info, test.warning, test.error]
                   for x in category]
        assert message in notices
        if status == "ok":
            assert rendered.index("合成结论一") < rendered.index("合成结论二")
        assert any(x.value == "toy evidence" for x in test.code)
        assert any("toy_v1" in x.value for x in test.caption)
        test.run()
        ask.assert_called_once()  # rerun does not repeat the model call


def test_missing_decision_still_displays_real_chain():
    response = result("empty", [])
    response["paths"] = [{"entity_ids": ["p", "c"], "relation_ids": ["r"],
        "relations": [{"id": "r", "from_id": "p", "to_id": "c", "type": "MergedAs",
                       "method": "github_api", "evidence_ids": ["toy-evidence"]}]}]
    with patch("app.backend.get", return_value=JOB), \
         patch("app.backend.ask", return_value=response):
        test = observed(JOB).run()
        test.text_input[1].set_value("已有修改链")
        next(b for b in test.button if b.label == "查询").click().run()
        assert not test.exception
        assert any("MergedAs" in x.value for x in test.markdown)


def test_replay_never_invokes_online_services(tmp_path, monkeypatch):
    import json

    replay = tmp_path / "replay.json"
    replay.write_text(json.dumps({"recorded_at": "synthetic", "job": deepcopy(JOB),
                                  "queries": [result()]}), encoding="utf-8")
    monkeypatch.setenv("HISTORYKG_REPLAY_FILE", str(replay))
    with patch("app.backend.start") as start, patch("app.backend.ask") as ask:
        test = AppTest.from_file(APP).run()
        assert not test.exception
        assert any("重放" in x.value for x in test.warning)
        assert not test.text_input
        start.assert_not_called()
        ask.assert_not_called()


def test_replay_citations_target_their_own_response(tmp_path, monkeypatch):
    import json
    import re

    second = result()
    second["query"]["question"] = "另一个开发示例问题"
    replay = tmp_path / "two-responses.json"
    replay.write_text(json.dumps({"recorded_at": "synthetic", "job": JOB,
                                  "queries": [result(), second]}), encoding="utf-8")
    monkeypatch.setenv("HISTORYKG_REPLAY_FILE", str(replay))
    test = AppTest.from_file(APP).run()
    assert not test.exception
    rendered = "\n".join(x.value for x in test.markdown)
    anchors = re.findall(r'<a id="([^"]+)">', rendered)
    assert len(anchors) == len(set(anchors)) == 2
    assert all(f"](#{anchor})" in rendered for anchor in anchors)
