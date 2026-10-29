import json

import pytest

from app.replay import archive


def job(status="ready"):
    return dict(contract_version="1.4.1", job_id="a" * 32, repo="test/project",
                profile_version="course_small_v1", dataset_id="dataset:test", status=status,
                stage="index_graph", created_at="2026-10-30T00:00:00Z",
                updated_at="2026-10-30T00:00:00Z", artifacts={"dataset_dir": "/local/private/path"})


def query_file(tmp_path, dataset="dataset:test"):
    file = tmp_path / "result.json"
    file.write_text(json.dumps(dict(dataset_id=dataset, query={"question": "example"},
                                   status="empty", claims=[], evidence=[], paths=[],
                                   gaps=["no evidence"], timings_ms={}, error=None,
                                   run_id="query-example")), encoding="utf-8")
    return file


def test_archive_records_exact_response_hash_and_removes_local_paths(tmp_path):
    out = tmp_path / "replay.json"
    result = archive(job(), [query_file(tmp_path)], out)
    assert result["job"]["artifacts"] == {}
    assert len(result["provenance"]["query_files"][0]["sha256"]) == 64
    assert result["queries"][0]["run_id"] == "query-example"
    assert "/local/private" not in out.read_text()


def test_archive_rejects_cross_dataset_response(tmp_path):
    with pytest.raises(ValueError, match="数据版本不一致"):
        archive(job(), [query_file(tmp_path, "dataset:another")], tmp_path / "out.json")


@pytest.mark.parametrize("status", ["blocked", "failed", "running"])
def test_archive_rejects_unready_job(tmp_path, status):
    with pytest.raises(ValueError, match="尚未发布"):
        archive(job(status), [query_file(tmp_path)], tmp_path / "out.json")
