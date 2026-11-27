"""Import a portable frozen dataset and open the live question page."""

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy.engine import make_url

from historykg.collector import initialize_database
from historykg.graph import load_dataset
from historykg.pipeline import load_config, query_config

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--port", type=int, default=8517)
    args = parser.parse_args()
    if args.config:
        os.environ["HISTORYKG_PROJECT_CONFIG"] = str(args.config.resolve(strict=True))
    dataset = args.dataset.resolve(strict=True)
    config = query_config(load_config())
    if database_url := config.get("database_url"):
        url = make_url(database_url)
        if url.get_backend_name() == "sqlite":
            if url.database and url.database != ":memory:":
                Path(url.database).parent.mkdir(parents=True, exist_ok=True)
            if initialize_database(database_url=database_url)["status"] != "ok":
                parser.exit(1, "无法初始化本机讨论索引。\n")
    result = load_dataset(dataset, config=config)
    if result["status"] != "ok" or not result["graph_ready"] or not result["retrieval_ready"]:
        error = result.get("error") or {}
        parser.exit(1, f"无法载入冻结数据：{error.get('message') or error.get('code')}\n")
    os.environ.pop("HISTORYKG_REPLAY_FILE", None)
    os.environ["HISTORYKG_DEMO_DATASET_DIR"] = str(dataset)
    os.execv(sys.executable, [
        sys.executable, "-m", "streamlit", "run", str(ROOT / "app/main.py"),
        "--server.address", "127.0.0.1", "--server.port", str(args.port),
        "--server.headless", "true", "--browser.gatherUsageStats", "false",
    ])


if __name__ == "__main__":
    main()
