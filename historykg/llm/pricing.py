"""Verified token prices; reservations still use peak cache-miss upper bounds."""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_CEILING, Decimal

PRICE_SOURCE = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"
PRICE_POLICY = "deepseek-2026-10-30-cache-and-beijing-period-v1"
# CNY / million tokens: cache hit, cache miss, output. Holidays deliberately
# retain weekday peak prices rather than assuming a holiday calendar.
PEAK_RATES = {
    "deepseek-flash": ("0.04", "2", "8"),
    "deepseek-v4-pro": ("0.30", "9", "27"),
}
BEIJING = dt.timezone(dt.timedelta(hours=8))


def _time(value: str | None) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def billing_period(started_at: str | None, finished_at: str | None) -> str:
    """Use idle only when the whole known request interval avoids peak hours."""
    start, end = _time(started_at), _time(finished_at)
    if start is None or end is None or end < start:
        return "peak"
    start, end = start.astimezone(BEIJING), end.astimezone(BEIJING)
    day = start.date()
    while day <= end.date():
        if day.weekday() < 5:
            for begin, finish in ((9, 12), (14, 18)):
                peak_start = dt.datetime.combine(day, dt.time(begin), BEIJING)
                peak_end = dt.datetime.combine(day, dt.time(finish), BEIJING)
                if start < peak_end and end >= peak_start:
                    return "peak"
        day += dt.timedelta(days=1)
    return "idle"


def quote_usage(
    model_id: str, usage: dict, *, started_at: str | None, finished_at: str | None
) -> dict | None:
    """Return rounded micro-CNY and the basis; incomplete usage stays conservative."""
    if model_id not in PEAK_RATES or not isinstance(usage, dict):
        return None
    if not all(
        type(usage.get(k)) is int and usage[k] >= 0 for k in ("prompt_tokens", "completion_tokens")
    ):
        return None
    prompt, output = usage["prompt_tokens"], usage["completion_tokens"]
    hit, miss = usage.get("prompt_cache_hit_tokens"), usage.get("prompt_cache_miss_tokens")
    cache_known = (
        type(hit) is int and type(miss) is int and hit >= 0 and miss >= 0 and hit + miss == prompt
    )
    if not cache_known:
        hit, miss = 0, prompt
    period = billing_period(started_at, finished_at)
    divisor = Decimal(2) if period == "idle" else Decimal(1)
    rates = [Decimal(r) / divisor for r in PEAK_RATES[model_id]]
    # CNY/million tokens multiplied by tokens is already in micro-CNY.
    micro = sum(Decimal(n) * rate for n, rate in zip((hit, miss, output), rates, strict=True))
    return {
        "charged_micro_cny": int(micro.to_integral_value(rounding=ROUND_CEILING)),
        "policy": PRICE_POLICY,
        "source": PRICE_SOURCE,
        "model_id": model_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "period": period,
        "cache_basis": "reported_hit_miss" if cache_known else "all_miss_fallback",
        "tokens": {"cache_hit": hit, "cache_miss": miss, "output": output},
        "rates_cny_per_million": [str(rate) for rate in rates],
    }
