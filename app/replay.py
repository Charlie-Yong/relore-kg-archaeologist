"""Archive already-generated public responses; never starts work or calls a model."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

from historykg import pipeline
from historykg.contracts import BuildJob_v1, QueryResult_v1
from historykg.io import write_json


def archive(job, query_files, output):
    job = BuildJob_v1.model_validate(job).model_dump(mode="json")
    if job["status"] not in {"ready", "partial"} or not job["dataset_id"]:
        raise ValueError("尚未发布可查询数据，不能归档为完成态演示")
    if job["repo"].startswith("example/") or "toy" in job["dataset_id"]:
        raise ValueError("合成fixture不能归档为真实演示")
    responses, records = [], []
    for value in query_files:
        file = Path(value)
        raw = file.read_bytes()
        response = QueryResult_v1.model_validate(json.loads(raw)).model_dump(mode="json")
        if response["dataset_id"] != job["dataset_id"]:
            raise ValueError("查询响应与作业数据版本不一致")
        response.pop("artifacts", None)
        responses.append(response)
        records.append({"query_run_id": response.get("run_id"),
                        "model_run_id": response.get("model_run_id"),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "saved_at": dt.datetime.fromtimestamp(file.stat().st_mtime, dt.UTC)
                        .isoformat(timespec="seconds")})
    if not responses:
        raise ValueError("请提供至少一个已生成的公共查询响应")
    job["artifacts"] = {}
    bundle = {"mode": "real_public_query", "recorded_at": max(r["saved_at"] for r in records),
              "captured_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
              "job": job, "queries": responses, "provenance": {"query_files": records}}
    write_json(output, bundle)
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--query", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    job = pipeline.get_build(args.job_id, config=pipeline.load_config())
    archive(job, args.query, args.output)


if __name__ == "__main__":
    main()
