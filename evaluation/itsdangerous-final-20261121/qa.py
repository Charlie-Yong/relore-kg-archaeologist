"""Run the preregistered final comparison using the prior experiment runners."""

import argparse
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = HERE.parent / "retrieval-followup-20261120"
LOCAL = ROOT / ".local" / "itsdangerous-final-20261121" / "qa"
PROTOCOL = json.loads((HERE / "qa-protocol.json").read_text())


def setup():
    sys.path.insert(0, str(PREVIOUS))
    import experiment

    LOCAL.mkdir(parents=True, exist_ok=True)
    baseline = LOCAL / "baseline"
    if not baseline.exists():
        baseline.symlink_to(ROOT / ".local" / "retrieval-followup" / "baseline", True)
    experiment.HERE = HERE
    experiment.LOCAL = LOCAL
    experiment.P = PROTOCOL
    return experiment


def cell(arm, number):
    experiment = setup()
    if arm in "DE":
        experiment.load_runner().runner(arm, number - 1)
    else:
        experiment.api(arm, number, live=True)


def run_all(arms):
    data = next((ROOT / ".local/full-history-itsdangerous/datasets").glob("*/sources.jsonl"))
    if hashlib.sha256(data.read_bytes()).hexdigest() != PROTOCOL["source_sha256"]:
        raise ValueError("Frozen corpus changed")
    LOCAL.mkdir(parents=True, exist_ok=True)
    baseline = LOCAL / "baseline"
    if not baseline.exists():
        baseline.symlink_to(ROOT / ".local" / "retrieval-followup" / "baseline", True)
    choices = PROTOCOL["codex_and_edges"]
    cells = [(arm, number) for arm in arms
             for number in (choices if arm in "CDE" else range(1, 13))]

    def execute(item):
        arm, number = item
        command = [sys.executable, str(Path(__file__).resolve()), "cell", arm, str(number)]
        return subprocess.run(command, cwd=ROOT, check=False).returncode

    with ThreadPoolExecutor(max_workers=3) as executor:
        statuses = list(executor.map(execute, cells))
    if any(statuses):
        raise ValueError(f"{sum(s != 0 for s in statuses)} cells failed to produce a record")


def grade(numbers):
    setup()
    import assessment

    with ThreadPoolExecutor(max_workers=3) as executor:
        list(executor.map(lambda n: assessment.grade(n, live=True), numbers))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "cell", "grade"))
    parser.add_argument("values", nargs="*")
    args = parser.parse_args()
    if args.mode == "cell":
        cell(args.values[0], int(args.values[1]))
    elif args.mode == "run":
        run_all(args.values[0] if args.values else "OABCDE")
    else:
        grade(list(map(int, args.values)) if args.values else range(1, 13))


if __name__ == "__main__":
    main()
