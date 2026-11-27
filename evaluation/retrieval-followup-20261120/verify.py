"""Check every saved span against frozen text and verify each scored tag independently with Git."""

import hashlib
import json
import subprocess

from experiment import HERE, LOCAL, P, save
from freeze import DATA


def verify():
    pool = {s["source_id"]: s for line in DATA.open() if (s := json.loads(line))}
    ref = json.loads((HERE / "reference.json").read_text())

    def git(*args):
        return subprocess.run(
            ["git", "--git-dir", str(DATA.parent / "p3/history.git"), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    assert git("rev-parse", "--is-shallow-repository").stdout.strip() == "false"
    proofs = []
    for row in ref[4:]:
        for tag in row["tags"]:
            tip = git("rev-parse", "--verify", f"refs/tags/{tag['tag']}^{{commit}}")
            match = git("merge-base", "--is-ancestor", row["sha"], tag["tip"])
            assert tip.returncode == 0 and tip.stdout.strip() == tag["tip"]
            assert match.returncode in (0, 1) and (match.returncode == 0) == tag["contains"]
            proofs.append(
                dict(sha=row["sha"], tag=tag["tag"], tip=tag["tip"], returncode=match.returncode)
            )
    spans = {}
    active_requests = {}
    for f in sorted((HERE / "records").glob("*.json")):
        j = json.loads(f.read_text())
        if "context_sha256" not in j:
            continue
        visible = json.loads((LOCAL / f.stem / "visible.json").read_text())
        for v in [*visible, *j["evidence"]]:
            assert v["quote"] == pool[v["source_id"]]["text"][v["start"] : v["end"]]
        for e in j["evidence"]:
            assert any(
                v["source_id"] == e["source_id"] and v["start"] <= e["start"] < e["end"] <= v["end"]
                for v in visible
            )
        assert j["context_characters"] <= 12000
        spans[f.stem] = dict(fragments=len(visible), checked_claim_citations=len(j["evidence"]))
        if f.stem.startswith("live-"):
            requests = sorted((LOCAL / f.stem / "answers").glob("**/attempts/*/request.json"))
            assert requests
            for path in requests:
                sent = json.loads(path.read_text())
                body = sent["body"]
                assert body["model"] == P["route"] and body["max_tokens"] == 32768
                assert body["reasoning_effort"] == "max" and body["enable_thinking"] is True
                assert sent["config"]["timeout_seconds"] == 240
            active_requests[f.stem] = len(requests)
    for n in P["codex_and_edges"]:
        b, c = [json.loads((HERE / "records" / f"{a}{n}.json").read_text()) for a in "BC"]
        assert b["context_sha256"] == c["context_sha256"]
    assert P["source_sha256"] == hashlib.sha256(DATA.read_bytes()).hexdigest()
    expected = {
        "protocol": "ad2dd504af787d3263894b4c7e7fecf7692f880562f752f09c081d2903f6b1a0",
        "reference": "716521073f33a8b97f50b44ea865f4bd9cde28e6e0e659e257a8615d88f6377f",
    }
    for name, sha in expected.items():
        assert hashlib.sha256((HERE / (name + ".json")).read_bytes()).hexdigest() == sha
    coverage = {}
    for n, row in enumerate(ref, 1):
        visible = json.loads((LOCAL / f"B{n}" / "visible.json").read_text())
        raw = "\n".join(v["quote"] for v in visible)
        if n <= 2:
            direct = [
                row["utc"] in raw,
                any(
                    row["tag"] in v["quote"]
                    and row["utc"] in v["quote"]
                    and v["url"].endswith("/releases")
                    for v in visible
                ),
            ]
        elif n <= 4:
            paths = row["changes"][1::2]
            if n == 4:
                paths = [path for path in paths if path.startswith("tests/")]
            direct = [
                any(
                    v["url"] == row["issue"]
                    and row["motive"].replace("\r\n", "\n").strip() in v["quote"]
                    for v in visible
                ),
                any(
                    v["url"] == row["pr"] and row["pr_body"].strip() in v["quote"] for v in visible
                ),
                any(row["sha"] in v["quote"] and "merged_at" in v["quote"] for v in visible),
                any(
                    "diff-tree" in v["quote"]
                    and row["sha"] in v["quote"]
                    and any(path in v["quote"] for path in paths)
                    for v in visible
                ),
            ]
        else:
            flags = []
            for tag in row["tags"]:
                label = f"{tag['tag']} → {tag['tip']}"
                verdict = "；包含 " if tag["contains"] else "；冻结历史不包含"
                flags.append(
                    any(
                        (v.get("title") or "").startswith(label)
                        and verdict in v["title"]
                        and row["sha"] in v["title"]
                        for v in visible
                    )
                )
            direct = [
                any(row["sha"] in v["quote"] and row["merged"] in v["quote"] for v in visible),
                all(
                    any(
                        tag["published"] in v["quote"] and tag["url"] in (v.get("title") or "")
                        for v in visible
                    )
                    for tag in row["tags"]
                ),
                all(flags),
                all(flags),
            ]
        coverage[n] = dict(criteria=P["rubric"][n - 1], evidence_present=direct)
    save(HERE / "first-pass-coverage.json", coverage)
    supplementary = []
    locked = HERE / "citation-check-protocol.json"
    assert hashlib.sha256(locked.read_bytes()).hexdigest() == (
        "71456e35f3031f81a5bbc36d747fa1cef417e50b650e938f8314d4282a28b024"
    )
    for n, row in enumerate(json.loads(locked.read_text()), 7):
        checked = {}
        for tag, expected_match in row["membership"].items():
            ret = git("merge-base", "--is-ancestor", row["sha"], f"refs/tags/{tag}^{{commit}}")
            assert ret.returncode in (0, 1) and (ret.returncode == 0) == expected_match
            checked[tag] = ret.returncode == 0
        supplementary.append(dict(q=n, tags=checked, first=row["first"]))
    for n in P["codex_and_edges"]:
        left = HERE / "records" / f"live-B{n}.json"
        right = HERE / "records" / f"live-C{n}.json"
        if left.exists() and right.exists():
            assert (
                json.loads(left.read_text())["context_sha256"]
                == json.loads(right.read_text())["context_sha256"]
            )
    save(
        HERE / "verification.json",
        dict(
            frozen_files=expected,
            source_count=len(pool),
            spans=spans,
            identical_BC_contexts=P["codex_and_edges"],
            verified_tag_ancestry=proofs,
            live_requests_32768=active_requests,
            extra_tag_checks=supplementary,
        ),
    )
    print("verified", len(spans), "answer contexts", len(proofs), "tag checks")


if __name__ == "__main__":
    verify()
