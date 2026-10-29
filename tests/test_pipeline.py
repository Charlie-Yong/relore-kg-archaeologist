"""Synthetic stage doubles verify job semantics without claiming real integration."""

import subprocess
import sys

from historykg import pipeline


def config(tmp_path):
    return {"jobs_root": str(tmp_path / "jobs"), "data_root": str(tmp_path / "data")}


def test_job_refresh_resume_and_final_readiness(tmp_path, monkeypatch):
    calls = []
    fail = [True]

    def stage(job, directory, settings):
        calls.append(job["stage"])
        if job["stage"] == "code" and fail[0]:
            return {"status": "blocked", "error": {"code": "test_dependency"}}
        if job["stage"] == "index_graph":
            return {
                "status": "ok",
                "dataset_id": job["dataset_id"],
                "graph_ready": True,
                "retrieval_ready": True,
            }
        return {
            "status": "ok",
            "counts": {"sources": 1},
            "usage": {"actual_llm_extraction": job["stage"] == "extract"},
        }

    monkeypatch.setattr(pipeline, "_stage", stage)
    settings = config(tmp_path)
    first = pipeline.start_build(
        {"repo_url": "https://github.com/example/toy"}, config=settings, background=False
    )
    assert first["status"] == "blocked"
    assert calls == ["discover", "collect", "code"]
    refresh = pipeline.start_build({"repo_url": "https://github.com/example/toy"}, config=settings)
    assert refresh["job_id"] == first["job_id"]
    assert calls == ["discover", "collect", "code"]
    fail[0] = False
    resumed = pipeline.resume_build(first["job_id"], config=settings, background=False)
    assert resumed["status"] == "ready"
    assert calls == ["discover", "collect", "code", "code", "extract", "validate", "index_graph"]
    assert resumed["dataset_id"] == first["dataset_id"]
    assert pipeline.get_build(first["job_id"], config=settings)["status"] == "ready"


def test_no_publish_without_both_backends_or_real_extraction(tmp_path, monkeypatch):
    def stage(job, directory, settings):
        if job["stage"] == "extract":
            return {"status": "ok", "usage": {"actual_llm_extraction": False}}
        return {"status": "ok", "counts": {"sources": 1}}

    monkeypatch.setattr(pipeline, "_stage", stage)
    result = pipeline.start_build(
        {"repo_url": "https://github.com/example/toy"}, config=config(tmp_path), background=False
    )
    assert result["status"] == "blocked"
    assert result["stage"] == "extract"
    assert "index_graph" not in result["completed_stages"]


def test_same_repo_new_build_gets_new_dataset(tmp_path, monkeypatch):
    def stage(job, directory, settings):
        return {
            "status": "ok",
            "counts": {"sources": 1},
            "dataset_id": job["dataset_id"],
            "graph_ready": True,
            "retrieval_ready": True,
            "actual_llm_extraction": True,
        }

    monkeypatch.setattr(pipeline, "_stage", stage)
    settings = config(tmp_path)
    one = pipeline.start_build(
        {"repo_url": "https://github.com/example/toy"}, config=settings, background=False
    )
    two = pipeline.start_build(
        {"repo_url": "https://github.com/example/toy"}, config=settings, background=False
    )
    assert one["dataset_id"] != two["dataset_id"]


def test_backend_failure_not_partial(tmp_path, monkeypatch):
    def stage(job, directory, settings):
        if job["stage"] == "index_graph":
            return {
                "status": "ok",
                "dataset_id": job["dataset_id"],
                "graph_ready": True,
                "retrieval_ready": False,
            }
        return {"status": "ok", "counts": {"sources": 1}, "actual_llm_extraction": True}

    monkeypatch.setattr(pipeline, "_stage", stage)
    result = pipeline.start_build(
        {"repo_url": "https://github.com/example/toy"}, config=config(tmp_path), background=False
    )
    assert result["status"] == "failed"


def test_development_stage_checkpoints_after_execution(tmp_path, monkeypatch):
    calls = []

    def stage(job, directory, settings):
        calls.append(job["stage"])
        return {"status": "blocked"}

    monkeypatch.setattr(pipeline, "_stage", stage)
    settings = config(tmp_path)
    first = pipeline.start_build(
        {"repo_url": "https://github.com/example/toy"}, config=settings, background=False
    )

    def success(job, directory, settings):
        calls.append(job["stage"])
        return {"status": "ok"}

    monkeypatch.setattr(pipeline, "_stage", success)
    result = pipeline.run_stage(first["job_id"], "collect", config=settings)
    assert result["completed_stages"] == ["discover", "collect"]
    assert result["stage"] == "code"


def test_index_stage_calls_the_shared_load_entry(tmp_path, monkeypatch):
    calls = []

    def call(module, function, path, **kwargs):
        calls.append((module, function, path, kwargs))
        return {"status": "ok", "graph_ready": True, "retrieval_ready": True}

    monkeypatch.setattr(pipeline, "_call", call)
    settings = pipeline.load_config(config(tmp_path))
    job = {"stage": "index_graph", "artifacts": {"dataset_dir": str(tmp_path)}}
    result = pipeline._stage(job, tmp_path, settings)
    assert result["graph_ready"]
    assert calls[0][:3] == ("historykg.graph", "load_dataset", tmp_path)
    assert "budget" in calls[0][3]["config"]


def test_coverage_notes_do_not_force_partial(tmp_path, monkeypatch):
    def stage(job, directory, settings):
        return {
            "status": "ok",
            "counts": {"sources": 1},
            "dataset_id": job["dataset_id"],
            "graph_ready": True,
            "retrieval_ready": True,
            "actual_llm_extraction": True,
            "gaps": [{"reason": "external_import", "severity": "coverage"}],
        }

    monkeypatch.setattr(pipeline, "_stage", stage)
    result = pipeline.start_build(
        {"repo_url": "https://github.com/example/toy"}, config=config(tmp_path), background=False
    )
    assert result["status"] == "ready"
    assert result["gaps"]


def test_actual_incomplete_stage_is_partial(tmp_path, monkeypatch):
    def stage(job, directory, settings):
        return {
            "status": "partial" if job["stage"] == "collect" else "ok",
            "counts": {"sources": 1},
            "dataset_id": job["dataset_id"],
            "graph_ready": True,
            "retrieval_ready": True,
            "actual_llm_extraction": True,
            "gaps": [{"reason": "unread_page"}] if job["stage"] == "collect" else [],
        }

    monkeypatch.setattr(pipeline, "_stage", stage)
    result = pipeline.start_build(
        {"repo_url": "https://github.com/example/toy"}, config=config(tmp_path), background=False
    )
    assert result["status"] == "partial"


def test_empty_lock_and_crashed_owner_recover(tmp_path):
    directory = tmp_path / "job"
    directory.mkdir()
    (tmp_path / "worker.lock").touch()
    first = pipeline._claim_worker(directory)
    assert first is not None
    assert pipeline._claim_worker(directory) is None
    first.close()
    crashed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import os,sys; from pathlib import Path; "
            "from historykg.pipeline import _claim_worker; "
            "lock = _claim_worker(Path(sys.argv[1])); os._exit(3 if lock else 4)",
            str(directory),
        ],
        check=False,
        timeout=10,
    )
    assert crashed.returncode == 3
    recovered = pipeline._claim_worker(directory)
    assert recovered is not None
    recovered.close()


def test_phase_counts_do_not_replace_dataset_totals(tmp_path, monkeypatch):
    def stage(job, directory, settings):
        return {
            "status": "ok",
            "counts": {"sources": 99},
            "dataset_id": job["dataset_id"],
            "coverage": {"sources": 1} if job["stage"] == "code" else {},
            "graph_ready": True,
            "retrieval_ready": True,
            "actual_llm_extraction": True,
        }

    monkeypatch.setattr(pipeline, "_stage", stage)
    result = pipeline.start_build(
        {"repo_url": "https://github.com/example/toy"}, config=config(tmp_path), background=False
    )
    assert result["counts"]["sources"] == result["coverage"]["sources"] == 1
    assert result["stage_counts"]["index_graph"]["sources"] == 99
