"""DeepSeek JSON requests, isolated caches and bounded, fully recorded retries."""

from __future__ import annotations

import contextlib
import copy
import datetime as dt
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from .budget import BudgetBlocked, BudgetLedger

TASKS = {"extract", "answer", "reference", "judge"}
RATES = {"deepseek-flash": (2, 8), "deepseek-v4-pro": (9, 27)}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=path.name + ".", delete=False
    ) as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _schema_check(value: Any, schema: dict, root: dict | None = None) -> None:
    """Check the JSON-schema subset used by task outputs (no silent repair)."""
    root = schema if root is None else root
    if "$ref" in schema:
        reference = schema["$ref"]
        if not reference.startswith("#/$defs/"):
            raise ValueError("Only local $defs output schema references are supported")
        return _schema_check(value, root["$defs"][reference.removeprefix("#/$defs/")], root)
    if "anyOf" in schema:
        for branch in schema["anyOf"]:
            try:
                _schema_check(value, branch, root)
                break
            except ValueError:
                continue
        else:
            raise ValueError("output_schema anyOf mismatch")
    kind = schema.get("type")
    types = {
        "object": dict,
        "array": list,
        "string": str,
        "null": type(None),
        "integer": int,
        "number": (int, float),
        "boolean": bool,
    }
    choices = kind if isinstance(kind, list) else [kind] if kind else []
    if choices and not any(
        isinstance(value, types[t])
        and (t not in {"integer", "number"} or not isinstance(value, bool))
        for t in choices
    ):
        raise ValueError("output_schema type mismatch")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("output_schema enum mismatch")
    if isinstance(value, dict):
        if set(schema.get("required", [])) - value.keys():
            raise ValueError("output_schema missing required fields")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False and value.keys() - props.keys():
            raise ValueError("output_schema unexpected fields")
        for key in value.keys() & props.keys():
            _schema_check(value[key], props[key], root)
    if isinstance(value, list) and "items" in schema:
        for item in value:
            _schema_check(item, schema["items"], root)
    if isinstance(value, list) and len(value) < schema.get("minItems", 0):
        raise ValueError("output_schema missing required array items")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        raise ValueError("output_schema empty string")


def prepare_request(
    *,
    task: str,
    dataset_id: str,
    payload: dict,
    config: dict,
    prompt: str,
    prompt_version: str,
    output_schema: dict,
    output_root: str | Path,
    repeat_index: int = 0,
) -> dict:
    if task not in TASKS or not dataset_id or repeat_index < 0:
        raise ValueError("非法模型任务、dataset_id或repeat_index。")
    root = Path(output_root).resolve()
    private = task in {"reference", "judge"}
    if private and "private_test" not in root.parts:
        raise ValueError("reference/judge必须显式写入P6控制的private_test路径。")
    if not private and "private_test" in root.parts:
        raise ValueError("生产任务不能读写P6 private_test缓存。")
    model = config.get("model_id", "deepseek-flash")
    if model not in RATES or config.get("provider", "deepseek") != "deepseek":
        raise ValueError("本通道仅支持已核价的DeepSeek型号。")
    thinking = config.get("thinking", "disabled")
    if thinking not in {"disabled", "enabled"}:
        raise ValueError("thinking必须显式为disabled/enabled。")
    max_tokens = config.get("max_output_tokens", 4096)
    retries = config.get("max_retries", 2)
    if not isinstance(max_tokens, int) or not 1 <= max_tokens <= 393216:
        raise ValueError("max_output_tokens超出支持范围。")
    if retries not in {0, 1, 2}:
        raise ValueError("正式重试最多2次。")
    messages = [
        {
            "role": "system",
            "content": prompt
            + "\nReturn only one JSON object matching this schema:\n"
            + canonical(output_schema),
        },
        {"role": "user", "content": canonical(payload)},
    ]
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "response_format": {"type": "json_object"},
        "thinking": {"type": thinking},
        "max_tokens": max_tokens,
        "temperature": config.get("temperature", 0),
    }
    if thinking == "enabled":
        body["reasoning_effort"] = config.get("reasoning_effort", "low")
    input_bytes = len(canonical(messages).encode("utf-8"))
    if input_bytes > config.get("max_input_bytes", 200_000):
        raise ValueError("模型输入超过已配置字节上限，禁止静默截断。")
    actual_config = {
        "provider": "deepseek",
        "model_id": model,
        "visible_version": config.get("visible_version", "unknown"),
        "thinking": thinking,
        "max_output_tokens": max_tokens,
        "max_output_field": "max_tokens",
        "max_retries": retries,
        "retry_validation_feedback": True,
        "max_input_bytes": config.get("max_input_bytes", 200_000),
        "timeout_seconds": config.get("timeout_seconds", 90),
        "parameters": {k: v for k, v in body.items() if k != "messages"},
    }
    identity = {
        "task": task,
        "dataset_id": dataset_id,
        "input": payload,
        "config": actual_config,
        "prompt": prompt,
        "prompt_version": prompt_version,
        "output_schema": output_schema,
        "repeat_index": repeat_index,
    }
    run_id = digest(identity)
    # Never use a caller-supplied dataset identifier as a path segment.
    directory = root / digest(dataset_id) / task / run_id
    request = {
        "run_id": run_id,
        "task": task,
        "dataset_id": dataset_id,
        "input_hash": digest(payload),
        "config": actual_config,
        "prompt_version": prompt_version,
        "output_schema": output_schema,
        "repeat_index": repeat_index,
        "body": body,
        "input_token_upper_bound": input_bytes + 4096,
        "output_directory": str(directory),
        "prepared_at": now(),
    }
    path = directory / "request.json"
    if not path.exists():
        save_json(path, request)
    return request


@contextlib.contextmanager
def _run_lock(directory: Path):
    """OS releases this per-run lock when a worker exits, including an abrupt exit."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "run.lock").open("a+b") as stream:
        if stream.seek(0, 2) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        acquired = False
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError:
            pass
        try:
            yield acquired
        finally:
            if acquired:
                if os.name == "nt":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def run_request(
    request: dict, *, budget: dict, transport: httpx.BaseTransport | None = None, validator=None
) -> dict:
    with _run_lock(Path(request["output_directory"])) as acquired:
        if not acquired:
            return {
                "status": "blocked",
                "run_id": request["run_id"],
                "new_requests": 0,
                "cache_hit": False,
                "error": "same_run_in_progress",
                "attempts": [],
            }
        return _run_locked(request, budget=budget, transport=transport, validator=validator)


def _run_locked(
    request: dict, *, budget: dict, transport: httpx.BaseTransport | None = None, validator=None
) -> dict:
    directory = Path(request["output_directory"])
    result_path = directory / "result.json"
    if result_path.exists():
        cached = json.loads(result_path.read_text(encoding="utf-8"))
        return {
            **cached,
            "cache_hit": True,
            "new_requests": 0,
            "usage": {**cached.get("usage", {}), "new_charge_upper_cny": 0},
        }
    if not os.environ.get("DEEPSEEK_API_KEY"):
        return {
            "status": "blocked",
            "run_id": request["run_id"],
            "cache_hit": False,
            "new_requests": 0,
            "error": "missing_deepseek_api_key",
            "attempts": [],
        }
    ledger = BudgetLedger(budget["ledger_path"], budget["approved_cny"])
    in_rate, out_rate = RATES[request["body"]["model"]]
    upper = request["input_token_upper_bound"] * in_rate + request["body"]["max_tokens"] * out_rate
    attempts = []
    current_charge = 0
    result = {
        "status": "failed",
        "run_id": request["run_id"],
        "cache_hit": False,
        "new_requests": 0,
        "attempts": attempts,
        "parsed": None,
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "known_usage_attempts": 0},
    }
    for index in range(request["config"]["max_retries"] + 1):
        attempt_id = request["run_id"] + f":{index}"
        attempt_dir = directory / "attempts" / str(index)
        previous = ledger.attempt(attempt_id)
        if previous is not None:
            record_path = attempt_dir / "record.json"
            if record_path.exists():
                record = json.loads(record_path.read_text(encoding="utf-8"))
            else:
                if previous["state"] == "reserved":
                    ledger.settle(attempt_id, None, previous["usage_json"] or "null")
                record = {
                    "attempt_id": attempt_id,
                    "status": "failed",
                    "error": "interrupted_before_attempt_record",
                    "usage": json.loads(previous["usage_json"] or "null"),
                    "charged_micro_cny": previous["charged"],
                    "finished_at": now(),
                }
                save_json(record_path, record)
            attempts.append(record)
            usage = record.get("usage") or {}
            if all(isinstance(usage.get(k), int) for k in ("prompt_tokens", "completion_tokens")):
                result["usage"]["known_usage_attempts"] += 1
                for key in ("prompt_tokens", "completion_tokens"):
                    result["usage"][key] += usage[key]
            if record["status"] == "ok":
                result.update(
                    status="ok",
                    parsed=json.loads((attempt_dir / "parsed.json").read_text(encoding="utf-8")),
                )
                break
            continue
        attempt_body = copy.deepcopy(request["body"])
        if attempts and attempts[-1].get("error") and attempts[-1].get("http_status") == 200:
            attempt_body["messages"].append(
                {
                    "role": "user",
                    "content": "The previous full JSON response failed validation: "
                    + attempts[-1]["error"]
                    + ". Return corrected full JSON. Use exact visible quotes; "
                    "disambiguate duplicate quotes using start or neighboring context. "
                    "Do not omit any candidate or reason.",
                }
            )
        added_bytes = max(
            0,
            len(canonical(attempt_body["messages"]).encode("utf-8"))
            - len(canonical(request["body"]["messages"]).encode("utf-8")),
        )
        attempt_upper = upper + added_bytes * in_rate
        try:
            ledger.reserve(attempt_id, request["task"], request["dataset_id"], attempt_upper)
        except BudgetBlocked as exc:
            result.update(status="blocked", error=str(exc))
            break
        record = {
            "attempt_id": attempt_id,
            "started_at": now(),
            "reserved_micro_cny": attempt_upper,
            "status": "failed",
            "usage": None,
            "finish_reason": None,
            "actual_model_id": None,
            "reasoning_tokens": None,
        }
        save_json(
            attempt_dir / "request.json",
            {**request, "body": attempt_body, "attempt_id": attempt_id},
        )
        actual_cost = None
        retryable = True
        result["new_requests"] += 1
        try:
            # The credential is used only as an in-memory header, never serialized.
            with httpx.Client(
                transport=transport, timeout=request["config"]["timeout_seconds"]
            ) as http:
                response = http.post(
                    "https://api.deepseek.com/chat/completions",
                    json=attempt_body,
                    headers={"Authorization": "Bearer " + os.environ["DEEPSEEK_API_KEY"]},
                )
            record["http_status"] = response.status_code
            record["provider_request_id"] = response.headers.get("x-request-id")
            # Do not retain request headers or exception messages containing credentials.
            save_json(
                attempt_dir / "response.json",
                {"status_code": response.status_code, "body": response.text},
            )
            if not response.is_success:
                retryable = response.status_code in {408, 429, 500, 502, 503, 504}
                record["error"] = f"http_{response.status_code}"
                retry_after = response.headers.get("retry-after", "0")
                wait = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 0
                if wait > 10:
                    retryable = False
                    result["status"] = "blocked"
                elif retryable and wait:
                    time.sleep(wait)
            else:
                raw = response.json()
                usage = raw.get("usage") or {}
                record["usage"] = usage
                record["actual_model_id"] = raw.get("model", "unknown")
                record["reasoning_tokens"] = (usage.get("completion_tokens_details") or {}).get(
                    "reasoning_tokens"
                )
                if all(
                    isinstance(usage.get(k), int) and usage[k] >= 0
                    for k in ("prompt_tokens", "completion_tokens")
                ):
                    # Always peak cache-miss rates, even if hit/idle pricing is cheaper.
                    actual_cost = (
                        usage["prompt_tokens"] * in_rate + usage["completion_tokens"] * out_rate
                    )
                    result["usage"]["known_usage_attempts"] += 1
                    for key in ("prompt_tokens", "completion_tokens"):
                        result["usage"][key] += usage[key]
                choice = raw["choices"][0]
                record["finish_reason"] = choice.get("finish_reason")
                if choice.get("finish_reason") != "stop":
                    raise ValueError("incomplete_finish_reason_" + str(choice.get("finish_reason")))
                content = choice["message"].get("content")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("empty_output")
                parsed = json.loads(content)
                _schema_check(parsed, request["output_schema"])
                if validator is not None:
                    validator(parsed)
                save_json(attempt_dir / "parsed.json", parsed)
                record["status"] = "ok"
                result.update(status="ok", parsed=parsed)
        except (httpx.TransportError, ValueError, KeyError, IndexError, TypeError) as exc:
            record["error"] = str(exc)[:500] if isinstance(exc, ValueError) else type(exc).__name__
        finally:
            record["finished_at"] = now()
            ledger.settle(attempt_id, actual_cost, canonical(record["usage"]))
            record["charged_micro_cny"] = attempt_upper if actual_cost is None else actual_cost
            current_charge += record["charged_micro_cny"]
            save_json(attempt_dir / "record.json", record)
            attempts.append(record)
        if result["status"] == "ok" or not retryable:
            break
    result["budget"] = ledger.snapshot()
    result["usage"]["charged_upper_cny"] = sum(a["charged_micro_cny"] for a in attempts) / 1_000_000
    result["usage"]["actual_requests"] = len(attempts)
    result["usage"]["new_charge_upper_cny"] = current_charge / 1_000_000
    # A budget block can clear when another in-flight request settles. Keep it
    # resumable, while successful/fully exhausted runs remain immutable caches.
    save_json(
        directory / ("blocked.json" if result["status"] == "blocked" else "result.json"), result
    )
    return result
