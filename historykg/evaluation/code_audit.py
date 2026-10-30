"""Independent static checks on frozen single-file snapshots; no target execution."""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from historykg.io import read_jsonl, write_json

from .reference import private_root


def audit_code(freeze, output_root):
    root, dataset = private_root(output_root), Path(freeze["dataset_dir"])
    sources = {s["source_id"]: s for s in read_jsonl(dataset / "sources.jsonl")}
    independent = []
    for sample in freeze["code_selection"]:
        source = sources[sample["source_id"]]
        try:
            tree = ast.parse(source["text"], filename=sample["path"])
        except SyntaxError as exc:
            independent.append({**sample, "status": "parse_failed", "error": str(exc)})
            continue
        independent.append(
            {
                **sample,
                "status": "parsed",
                "text_sha256": source["text_sha256"],
                "symbols": [
                    {"name": node.name, "line": node.lineno, "kind": type(node).__name__}
                    for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                ],
                "docstring": ast.get_docstring(tree, clean=False),
                "import_statements": [
                    ast.get_source_segment(source["text"], node)
                    for node in ast.walk(tree)
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                ],
            }
        )
    # Save the source-derived reference before consuming P3's predicted properties.
    write_json(root / "code" / "independent_reference.json", independent)
    entities = {e["id"]: e for e in read_jsonl(dataset / "p3/entities.jsonl")}
    relations = read_jsonl(dataset / "p3/relations.jsonl")
    evidence = {e["evidence_id"]: e for e in read_jsonl(dataset / "p3/evidence.jsonl")}
    results = []
    for ref in independent:
        if ref["status"] != "parsed":
            results.append({**ref, "outcome": "parse_failed"})
            continue
        props, failures = entities[ref["file_id"]]["properties"], []
        for key in ("symbols", "docstring", "path", "commit_sha"):
            if props.get(key) != ref[key]:
                failures.append(key)
        if props.get("parse_status") != "parsed":
            failures.append("parse_status")
        checked_edges = 0
        for edge in relations:
            if edge["type"] != "Imports" or edge["from_id"] != ref["file_id"]:
                continue
            target = entities[edge["to_id"]]
            if target["properties"]["commit_sha"] != ref["commit_sha"]:
                failures.append("Imports crosses SHA")
            quotes = [evidence[eid] for eid in edge["evidence_ids"]]
            if not any(
                e["source_id"] == ref["source_id"]
                and any(e["quote"] == statement for statement in ref["import_statements"])
                for e in quotes
            ):
                failures.append("Imports evidence is not a complete source import")
            checked_edges += 1
        results.append(
            {
                "file_id": ref["file_id"],
                "split": ref["split"],
                "path": ref["path"],
                "commit_sha": ref["commit_sha"],
                "outcome": "incorrect" if failures else "correct",
                "failures": failures,
                "imports_checked": checked_edges,
            }
        )
    summary = {
        "samples": len(results),
        "outcomes": dict(Counter(r["outcome"] for r in results)),
        "splits": {
            s: dict(Counter(r["outcome"] for r in results if r["split"] == s))
            for s in ("dev", "test")
        },
        "results": results,
        "scope": "single-file parse/top-level symbols/docstring; emitted Imports quote/SHA checks; "
        "no event recall or uncollected-import completeness claim",
    }
    write_json(root / "code" / "audit.json", summary)
    return summary
