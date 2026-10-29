"""Bounded, static Python facts. Imported target code is never loaded or executed."""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import Any

PARSER_VERSION = "python_ast_v1"


def module_name(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[0] in {"src", "lib"}:
        parts.pop(0)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def analyze_python(text: str, path: str, available_paths: list[str]) -> dict[str, Any]:
    """Return lexical imports with exact Unicode offsets and candidate file paths.

    Resolution is limited to an unambiguous module in the recorded git tree. A
    resolved candidate is not an Imports relation until its same-SHA file is read.
    """
    try:
        tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError) as exc:
        return {
            "status": "parse_failed",
            "error": type(exc).__name__,
            "line": getattr(exc, "lineno", None),
            "imports": [],
            "symbols": [],
            "parser_version": PARSER_VERSION,
        }
    index: dict[str, list[str]] = {}
    for candidate in sorted(available_paths):
        if candidate.endswith(".py"):
            index.setdefault(module_name(candidate), []).append(candidate)
    current = module_name(path).split(".")
    package = current if path.endswith("/__init__.py") else current[:-1]
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    imports = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        # AST columns are UTF-8 byte offsets; evidence offsets are Unicode points.
        start = offsets[node.lineno - 1] + len(
            lines[node.lineno - 1].encode("utf-8")[: node.col_offset].decode("utf-8")
        )
        end = offsets[node.end_lineno - 1] + len(
            lines[node.end_lineno - 1].encode("utf-8")[: node.end_col_offset].decode("utf-8")
        )
        if isinstance(node, ast.Import):
            requested = [(alias.name, None) for alias in node.names]
        else:
            base = node.module or ""
            if node.level:
                if node.level > len(package):
                    imports.append(
                        {
                            "module": "." * node.level + base,
                            "target_path": None,
                            "reason": "relative_import_beyond_package",
                            "line": node.lineno,
                            "start": start,
                            "end": end,
                            "quote": text[start:end],
                        }
                    )
                    continue
                else:
                    base = ".".join(
                        package[: len(package) - node.level + 1] + ([base] if base else [])
                    )
            requested = [
                ((base + "." + alias.name).strip("."), base or None)
                if alias.name != "*"
                else (base, None)
                for alias in node.names
            ]
        for requested_module, fallback in requested:
            matches = index.get(requested_module, []) or index.get(fallback or "", [])
            target = matches[0] if len(matches) == 1 else None
            imports.append(
                {
                    "module": requested_module,
                    "target_path": target,
                    "reason": None
                    if target
                    else ("ambiguous_module" if matches else "external_or_unresolved"),
                    "line": node.lineno,
                    "start": start,
                    "end": end,
                    "quote": text[start:end],
                }
            )
    symbols = [
        {"name": node.name, "kind": type(node).__name__, "line": node.lineno}
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    return {
        "status": "parsed",
        "imports": sorted(imports, key=lambda item: (item["start"], item["module"])),
        "symbols": symbols,
        "docstring": ast.get_docstring(tree, clean=False),
        "parser_version": PARSER_VERSION,
    }
