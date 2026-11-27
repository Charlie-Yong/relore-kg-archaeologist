"""Clipping keeps the longest complete boundary without scanning every prefix."""

import json
import math
import re

import pytest

import historykg.llm.answer as answer
from historykg.llm.gateway import canonical


@pytest.mark.parametrize("limit", [2, 90, 130, 180, 300, 12000])
def test_longest_boundary_retains_escaping_offsets_metadata_and_gaps(limit):
    quote = 'Start 🙂. Next "quoted" line!\n中文句子。 More \\ text? End.'
    item = {
        "source_id": "s",
        "start": 991,
        "end": 991 + len(quote),
        "quote": quote,
        "title": "A title",
        "url": "https://example.org",
        "author": None,
        "time": None,
    }
    fragment = dict(item)
    expected = None
    if len(canonical([fragment])) <= limit:
        expected = fragment
    else:
        for boundary in reversed([m.end() for m in re.finditer(r"[.!?。！？\n](?:\s|$)", quote)]):
            candidate = {**fragment, "quote": quote[:boundary], "end": item["start"] + boundary}
            if len(canonical([candidate])) <= limit:
                expected = candidate
                break
    result = answer.render_context([item, item], max_characters=limit)
    assert result["fragments"] == ([expected] if expected else [])
    assert result["rendered"] == canonical(result["fragments"])
    assert result["characters"] == len(result["rendered"]) <= limit
    if expected == fragment:
        assert result["gaps"] == []
    else:
        assert result["gaps"] == [
            {
                "reason": "context_budget",
                "source_id": "s",
                "candidate_start": item["start"],
                "candidate_end": item["end"],
                "visible_end": expected["end"] if expected else None,
            }
        ]


def test_large_json_uses_logarithmic_number_of_serializations(monkeypatch):
    text = json.dumps(
        {"items": [{"number": n, "body": 'Unicode 中文 and "escapes".'} for n in range(5000)]},
        ensure_ascii=False,
        indent=2,
    )
    item = {"source_id": "api", "start": 0, "end": len(text), "quote": text}
    calls = []

    def counted(value):
        calls.append(1)
        return canonical(value)

    monkeypatch.setattr(answer, "canonical", counted)
    result = answer.render_context([item])
    boundaries = [m.end() for m in re.finditer(r"[.!?。！？\n](?:\s|$)", text)]
    assert len(calls) <= math.ceil(math.log2(len(boundaries) + 1)) + 2
    visible = result["fragments"][0]
    assert result["characters"] <= 12000
    assert visible["end"] == len(visible["quote"])
    assert visible["quote"] == text[: visible["end"]]
    next_end = next(end for end in boundaries if end > visible["end"])
    assert len(canonical([{**item, "quote": text[:next_end], "end": next_end}])) > 12000


def test_conflicting_quotes_for_same_source_span_are_rejected():
    first = {"source_id": "s", "start": 10, "end": 15, "quote": "alpha"}
    second = {"source_id": "s", "start": 10, "end": 15, "quote": "bravo"}
    with pytest.raises(ValueError, match="相同来源和偏移.*不一致引文"):
        answer.render_context([first, second])


def test_new_entity_and_relation_types_in_path_metadata_are_safe():
    quote = "Developer @maintainer authored close()."
    path = {
        "entity_ids": ["dev-1", "fn-1", "pr-1"],
        "entities": [
            {
                "id": "dev-1",
                "type": "Developer",
                "properties": {"display_name": "@maintainer"},
            },
            {
                "id": "fn-1",
                "type": "Function",
                "properties": {"display_name": "close()"},
            },
            {
                "id": "pr-1",
                "type": "PullRequest",
                "properties": {"display_name": "PR 1"},
            },
        ],
        "relations": [
            {"type": "Authored", "from_id": "dev-1", "to_id": "pr-1"},
            {"type": "Defines", "from_id": "fn-1", "to_id": "pr-1"},
        ],
    }
    item = {
        "source_id": "s",
        "start": 7,
        "end": 7 + len(quote),
        "quote": quote,
        "title": "PR discussion",
        "url": "https://example.invalid/pr/1",
        "entity_type": "Developer",
        "relation_type": "Authored",
        "path": path,
    }
    result = answer.render_context([item])
    assert result["fragments"] == [
        {
            "source_id": "s",
            "start": 7,
            "end": 7 + len(quote),
            "quote": quote,
            "title": "PR discussion",
            "url": "https://example.invalid/pr/1",
        }
    ]
    assert result["characters"] == len(canonical(result["fragments"]))
    assert [entity["type"] for entity in path["entities"]] == [
        "Developer",
        "Function",
        "PullRequest",
    ]
    assert [relation["type"] for relation in path["relations"]] == ["Authored", "Defines"]
