"""One live bounded fetch, then replay the exact payloads on both real databases.

Run from the repository root after installation. Runtime captures stay under .local.
This script does not invoke model APIs, Neo4j, or any target-repository source code.
"""

import argparse
import hashlib
import json
import platform
import re
import sys
from pathlib import Path

from historykg.collector import collect_repo, doctor, replay_capture, search_history


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-url", default="https://github.com/pallets/flask")
    parser.add_argument("--postgres-url", required=True)
    parser.add_argument("--out", type=Path, default=Path(".local/collector/validation"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    sqlite = "sqlite:///" + (args.out.resolve() / "index.sqlite3").as_posix()
    collected = collect_repo(args.repo_url, database_url=sqlite, output_dir=args.out / "capture")
    assert collected["status"] == "ok", collected
    assert collected["indexed_threads"] == 2, collected
    capture_file = Path(collected["capture_path"])
    capture = json.loads(capture_file.read_text(encoding="utf-8"))
    title = capture["payloads"][0]["thread"]["title"]
    terms = re.findall(r"[A-Za-z][A-Za-z_]{2,}", title)
    query = " ".join(terms[:3])
    assert query, title
    results = {}
    for name, url in [("sqlite", sqlite), ("postgresql", args.postgres_url)]:
        first = replay_capture(capture_file, database_url=url)
        assert first["status"] == "ok", first
        second = replay_capture(capture_file, database_url=url)
        assert second["documents_written"] == 0, second
        assert first["counts"] == second["counts"], (first, second)
        searched = search_history(collected["repo"], query, database_url=url)
        assert searched["status"] == "ok" and searched["hits"], searched
        assert all(hit["repo"] == collected["repo"] for hit in searched["hits"])
        assert search_history("example/not-this-repo", query, database_url=url)["status"] == "empty"
        origin = doctor(url)
        assert origin["source"]["bundled"], origin
        results[name] = {
            "status": "passed",
            "counts": first["counts"],
            "repeat_documents_written": second["documents_written"],
            "query": query,
            "hits": len(searched["hits"]),
            "evidence": [
                {
                    "number": h["number"],
                    "url": h["url"],
                    "snippet_sha256": hashlib.sha256(h["snippet"].encode()).hexdigest(),
                }
                for h in searched["hits"]
            ],
        }
    assert results["sqlite"]["counts"] == results["postgresql"]["counts"]
    report = {
        "interface_version": "collector_v1",
        "repo": collected["repo"],
        "profile": collected["profile_version"],
        "platform": platform.system(),
        "python": platform.python_version(),
        "relore_version": "0.3.19",
        "relore_commit": capture["relore_commit"],
        "retrieved_at": capture["retrieved_at"],
        "github_requests": collected["github_requests"],
        "authenticated": collected["authenticated"],
        "capture_sha256": hashlib.sha256(capture_file.read_bytes()).hexdigest(),
        "selected": collected["selected"],
        "backends": results,
        "model_requests": 0,
    }
    (args.out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
