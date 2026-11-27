"""Bounded, static Python facts. Imported target code is never loaded or executed."""

from __future__ import annotations

import ast
from pathlib import PurePosixPath
from typing import Any

PARSER_VERSION = "python_ast_v2"


def _line_offsets(text: str) -> tuple[list[str], list[int]]:
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    return lines, offsets


def _node_offset(lines: list[str], offsets: list[int], line: int, column: int) -> int:
    """Convert an AST UTF-8 byte column to a Unicode code-point offset."""
    prefix = lines[line - 1].encode("utf-8")[:column].decode("utf-8")
    return offsets[line - 1] + len(prefix)


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
            "functions": [],
            "parser_version": PARSER_VERSION,
        }
    index: dict[str, list[str]] = {}
    for candidate in sorted(available_paths):
        if candidate.endswith(".py"):
            index.setdefault(module_name(candidate), []).append(candidate)
    current = module_name(path).split(".")
    package = current if path.endswith("/__init__.py") else current[:-1]
    lines, offsets = _line_offsets(text)
    imports = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        start = _node_offset(lines, offsets, node.lineno, node.col_offset)
        end = _node_offset(lines, offsets, node.end_lineno, node.end_col_offset)
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
    symbols = []
    functions = []
    module = module_name(path)
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        symbols.append({"name": node.name, "kind": type(node).__name__, "line": node.lineno})
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start = _node_offset(lines, offsets, node.lineno, node.col_offset)
        body_start = _node_offset(
            lines, offsets, node.body[0].lineno, node.body[0].col_offset
        )
        quote = text[start:body_start].rstrip()
        end = start + len(quote)
        functions.append(
            {
                "name": node.name,
                "qualified_name": f"{module}.{node.name}" if module else node.name,
                "kind": "async_function"
                if isinstance(node, ast.AsyncFunctionDef)
                else "function",
                "start_line": node.lineno,
                "end_line": node.end_lineno,
                "start": start,
                "end": end,
                "quote": quote,
            }
        )
    return {
        "status": "parsed",
        "imports": sorted(imports, key=lambda item: (item["start"], item["module"])),
        "symbols": symbols,
        "functions": functions,
        "docstring": ast.get_docstring(tree, clean=False),
        "parser_version": PARSER_VERSION,
    }
