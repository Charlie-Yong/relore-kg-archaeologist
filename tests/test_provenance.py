"""Regression for stage-local zero counts and cached retry aggregation."""

from historykg.ids import canonical_json, text_hash
from historykg.io import write_json
from historykg.provenance import merge_stage_usage


def test_extract_attempts_survive_code_zero_and_cached_resume(tmp_path):
    dataset, run_id = "dataset:test", "a" * 64
    target = tmp_path / text_hash(canonical_json(dataset)) / "extract" / run_id
    write_json(target / "result.json", {"attempts": [
        {"attempt_id": "first", "usage": {"prompt_tokens": 10, "completion_tokens": 3},
         "charged_micro_cny": 50},
        {"attempt_id": "retry", "usage": {"prompt_tokens": 12, "completion_tokens": 4},
         "charged_micro_cny": 60},
    ]})
    job = {"dataset_id": dataset, "usage": {"github_requests": 182}}
    merge_stage_usage(job, "code", {"usage": {"model_requests": 0}}, output_root=tmp_path)
    merge_stage_usage(job, "extract", {
        "usage": {"new_model_requests": 2}, "model_run_ids": [run_id],
    }, output_root=tmp_path)
    assert job["usage"]["model_requests"] == 2
    assert job["usage"]["new_model_requests"] == 2
    assert job["usage"]["model_runs"]["completion_tokens"] == 7
    merge_stage_usage(job, "extract", {
        "usage": {"new_model_requests": 0}, "model_run_ids": [run_id],
    }, output_root=tmp_path)
    assert job["usage"]["model_requests"] == 2
    assert job["usage"]["new_model_requests"] == 2
    assert job["usage"]["github_requests"] == 182


def test_existing_cache_does_not_claim_new_requests(tmp_path):
    dataset, run_id = "dataset:cached", "b" * 64
    target = tmp_path / text_hash(canonical_json(dataset)) / "extract" / run_id
    write_json(target / "result.json", {"attempts": [{"attempt_id": "old", "usage": {}}]})
    job = {"dataset_id": dataset, "usage": {}}
    merge_stage_usage(job, "extract", {
        "usage": {"new_model_requests": 0}, "model_run_ids": [run_id],
    }, output_root=tmp_path)
    assert job["usage"]["model_requests"] == job["usage"]["reused_model_attempts"] == 1
    assert job["usage"]["new_model_requests"] == 0


def test_old_published_job_display_is_correct_without_rewriting(tmp_path):
    from historykg.pipeline import get_build

    job_dir = tmp_path / "jobs" / "abc123"
    job = {"dataset_id": "dataset:old", "usage": {"model_requests": 0},
           "completed_stages": ["code", "extract"], "artifacts": {}}
    write_json(job_dir / "job.json", job)
    write_json(job_dir / "config.json", {})
    write_json(job_dir / "checkpoint_code.json", {"result": {"usage": {"model_requests": 0}}})
    write_json(job_dir / "checkpoint_extract.json", {
        "result": {"usage": {"new_model_requests": 42}},
    })
    before = (job_dir / "job.json").read_bytes()
    displayed = get_build("abc123", config={"jobs_root": str(tmp_path / "jobs")})
    assert displayed["usage"]["model_requests"] == 42
    assert displayed["usage"]["new_model_requests"] == 42
    assert (job_dir / "job.json").read_bytes() == before
