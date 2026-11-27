"""Serve the real frozen job with the classroom answer configuration."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    from app.main import main

    trial = ROOT / ".local/full-history-itsdangerous"
    manifest = next((trial / "datasets").glob("*/manifest.json"))
    os.environ["HISTORYKG_PROJECT_CONFIG"] = str(trial / "project.json")
    os.environ["HISTORYKG_DEMO_JOB_ID"] = json.loads(manifest.read_text())["job_id"]
    os.environ.pop("HISTORYKG_REPLAY_FILE", None)
    main()
