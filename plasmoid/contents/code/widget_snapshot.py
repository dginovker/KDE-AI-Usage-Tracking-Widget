#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import math
import os
import re
import sqlite3
import sys
from pathlib import Path
from statistics import median
from typing import Any


CACHE = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "ai-usage"
CLAUDE_CACHE = CACHE / "claude-statusline.json"
HISTORY_CACHE = CACHE / "usage-history.json"
PROVIDERS = ("claude", "codex")
WINDOWS = {"primary": 300, "five_hour": 300, "secondary": 10080, "seven_day": 10080}
TOKEN_WINDOWS = (("lifetime", "Lifetime", None), ("30d", "30d", 30 * 86400), ("7d", "7d", 7 * 86400), ("24h", "24h", 86400), ("1h", "1h", 3600))
COLORS = {"ok": "#27ae60", "near": "#fdbc4b", "under": "#3daee9", "limited": "#da4453"}
TARGET_USED = 80.0
FULL_USED = 99.5
HISTORY_LIMIT = 300
MIN_CURRENT_DELTA = 4.0
LIMIT_RETRY_RE = re.compile(r"try again at ([A-Z][a-z]+\.? \d{1,2}(?:st|nd|rd|th)?, \d{4} \d{1,2}:\d{2} [AP]M)", re.I)
OPENAI_PRICES = {
    "gpt-5-codex": {"input": 1.25, "cached": 0.125, "output": 10.0},
    "gpt-5.5": {"input": 10.0, "cached": 1.0, "output": 45.0},
    "gpt-5.4-mini": {"input": 0.75, "cached": 0.075, "output": 4.5},
    "gpt-5.3-codex": {"input": 1.75, "cached": 0.175, "output": 14.0},
}
CLAUDE_PRICES = {
    "claude-fable-5": {"input": 10.0, "write5": 12.5, "write1h": 20.0, "read": 1.0, "output": 50.0},
    "claude-opus-4-8": {"input": 5.0, "write5": 6.25, "write1h": 10.0, "read": 0.5, "output": 25.0},
    "claude-opus-4-7": {"input": 5.0, "write5": 6.25, "write1h": 10.0, "read": 0.5, "output": 25.0},
    "claude-opus-4-6": {"input": 5.0, "write5": 6.25, "write1h": 10.0, "read": 0.5, "output": 25.0},
    "claude-opus-4-5": {"input": 5.0, "write5": 6.25, "write1h": 10.0, "read": 0.5, "output": 25.0},
    "claude-opus-4-1": {"input": 15.0, "write5": 18.75, "write1h": 30.0, "read": 1.5, "output": 75.0},
    "claude-opus-4": {"input": 15.0, "write5": 18.75, "write1h": 30.0, "read": 1.5, "output": 75.0},
    "claude-sonnet-5": {"input": 2.0, "write5": 2.5, "write1h": 4.0, "read": 0.2, "output": 10.0},
    "claude-sonnet-4-6": {"input": 3.0, "write5": 3.75, "write1h": 6.0, "read": 0.3, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 1.0, "write5": 1.25, "write1h": 2.0, "read": 0.1, "output": 5.0},
}


def now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def parse_retry_time(text: str) -> dt.datetime | None:
    match = LIMIT_RETRY_RE.search(text)
    if not match:
        return None
    value = re.sub(r"(\d{1,2})(st|nd|rd|th)", r"\1", match.group(1), flags=re.I)
    for fmt in ("%b %d, %Y %I:%M %p", "%B %d, %Y %I:%M %p"):
        try:
            return dt.datetime.strptime(value, fmt).replace(tzinfo=now().tzinfo)
        except ValueError:
            pass
    return None


def reset_meta(epoch: Any) -> dict[str, Any]:
    reset_epoch = as_float(epoch)
    if reset_epoch is None:
        return {"reset": None, "reset_label": "--", "days": "?"}
    try:
        reset = dt.datetime.fromtimestamp(reset_epoch, dt.timezone.utc).astimezone()
    except (OSError, OverflowError, ValueError):
        return {"reset": None, "reset_label": "--", "days": "?"}

    ref = now()
    seconds = max(0, int((reset - ref).total_seconds()))
    if reset.date() == ref.date():
        label = reset.strftime("%H:%M")
    elif reset.date() == (ref + dt.timedelta(days=1)).date():
        label = "tomorrow " + reset.strftime("%H:%M")
    elif seconds < 7 * 86400:
        label = reset.strftime("%a %H:%M")
    else:
        label = reset.strftime("%b %-d %H:%M")
    return {"reset": reset_epoch, "reset_label": f"Resets {label}", "days": str(seconds // 86400)}


def percent(value: Any) -> float | None:
    used = as_float(value)
    return None if used is None else max(0.0, min(100.0, used))


def duration(seconds: float) -> str:
    minutes = max(1, int((seconds + 59) // 60))
    if minutes < 90:
        return f"{minutes}m"
    hours = int((minutes + 30) // 60)
    if hours < 36:
        return f"{hours}h"
    days, extra = divmod(hours, 24)
    return f"{days}d {extra}h" if extra and days < 3 else f"{days}d"


def quota_health(used: float | None, reset_epoch: Any, window: int | None) -> dict[str, str]:
    if used is None:
        return {"pace": "--", "color": ""}

    raw_projected = projected = limit_early = wait = None
    reset = as_float(reset_epoch)
    if reset is not None and window:
        seconds_left = max(0.0, reset - now().timestamp())
        window_seconds = window * 60
        left_fraction = max(0.0, min(1.0, seconds_left / window_seconds))
        elapsed = max(0.0, 1.0 - left_fraction)
        wait = max(0.0, (12 * 60 * 60 if window >= 7 * 24 * 60 else 30 * 60) - window_seconds * elapsed)
        raw_projected = used if elapsed <= 0 else used / elapsed
        projected = min(100.0, raw_projected)
        if raw_projected > 100.0 and used > 0:
            limit_early = seconds_left if used >= 100.0 else seconds_left - ((100.0 - used) * window_seconds * elapsed / used)

    if wait is None or wait > 0:
        pace = f"Forecast in {duration(wait)}" if wait is not None else "Forecast pending"
    elif limit_early is not None and limit_early > 0:
        pace = f"Limit {duration(limit_early)} early"
    else:
        pace = f"Expected {round(projected if projected is not None else used)}%"

    ready = wait == 0
    if ready and limit_early is not None and limit_early > 0:
        state = "near"
    elif ready and raw_projected is not None:
        state = "ok" if raw_projected >= TARGET_USED else "near" if raw_projected >= TARGET_USED * 0.8 else "under"
    else:
        state = "ok" if used >= TARGET_USED else "near" if used >= TARGET_USED * 0.8 else "under"
    return {"pace": pace, "color": COLORS[state]}


def blank_quota() -> dict[str, Any]:
    return {"used": None, **reset_meta(None), **quota_health(None, None, None)}


def limited_quota(reset_epoch: float, used: float | None = 100.0) -> dict[str, Any]:
    return {"used": used, **reset_meta(reset_epoch), "pace": "Limited", "color": COLORS["limited"]}


def quota(limits: dict[str, Any] | None, name: str, event_time: dt.datetime | None) -> dict[str, Any]:
    payload = (limits or {}).get(name)
    if not isinstance(payload, dict):
        return blank_quota()

    reset = payload.get("resets_at")
    if reset is None and payload.get("resets_in_seconds") is not None and event_time is not None:
        reset = event_time.timestamp() + float(payload["resets_in_seconds"])
    used = percent(payload.get("used_percent", payload.get("used_percentage")))
    window = int(payload.get("window_minutes") or WINDOWS.get(name) or 0) or None
    return {"used": used, **reset_meta(reset), **quota_health(used, reset, window)}


def history_record(data: dict[str, Any], provider: str) -> dict[str, Any] | None:
    current = (data.get(provider) or {}).get("current") or {}
    weekly = (data.get(provider) or {}).get("weekly") or {}
    values = {
        "current_used": as_float(current.get("used")),
        "current_reset": as_float(current.get("reset")),
        "weekly_used": as_float(weekly.get("used")),
        "weekly_reset": as_float(weekly.get("reset")),
    }
    return None if any(v is None for v in values.values()) else values


def append_history(history: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    for provider in PROVIDERS:
        record = history_record(data, provider)
        if not record:
            continue
        items = history.get(provider) if isinstance(history.get(provider), list) else []
        keys = ("current_used", "current_reset", "weekly_used", "weekly_reset")
        if not items or any(record[key] != items[-1].get(key) for key in keys):
            items.append(record)
        history[provider] = items[-HISTORY_LIMIT:]
    return history


def conversion_ratio(history: dict[str, Any], provider: str) -> tuple[float | None, int]:
    items = [i for i in history.get(provider, []) if isinstance(i, dict)]
    ratios = []
    start = end = None

    def add() -> None:
        if not start or not end:
            return
        current_delta = as_float(end.get("current_used")) - as_float(start.get("current_used"))
        weekly_delta = as_float(end.get("weekly_used")) - as_float(start.get("weekly_used"))
        if current_delta >= MIN_CURRENT_DELTA and weekly_delta > 0:
            ratio = weekly_delta / current_delta
            if 0 < ratio <= 1:
                ratios.append(ratio)

    for item in items:
        key = (item.get("current_reset"), item.get("weekly_reset"))
        if start is None:
            start = end = item
        elif key == (start.get("current_reset"), start.get("weekly_reset")):
            end = item
        else:
            add()
            start = end = item
    add()
    return (median(ratios[-20:]) if ratios else None), len(ratios)


def current_capacity(current: dict[str, Any], weekly: dict[str, Any]) -> float | None:
    current_used = as_float(current.get("used"))
    current_reset = as_float(current.get("reset"))
    weekly_reset = as_float(weekly.get("reset"))
    if None in (current_used, current_reset, weekly_reset) or current_reset <= now().timestamp() or weekly_reset <= now().timestamp():
        return None
    units = max(0.0, 100.0 - current_used)
    if current_reset < weekly_reset:
        units += math.ceil((weekly_reset - current_reset) / (5 * 60 * 60)) * 100.0
    return units


def apply_history(data: dict[str, Any], history: dict[str, Any]) -> None:
    for provider in PROVIDERS:
        ratio, _ = conversion_ratio(history, provider)
        provider_data = data.get(provider) or {}
        current = provider_data.get("current") or {}
        weekly = provider_data.get("weekly") or {}
        used = as_float(weekly.get("used"))
        capacity = current_capacity(current, weekly)
        if ratio is None or used is None or capacity is None:
            continue
        reachable = min(100.0, used + capacity * ratio)
        if reachable < FULL_USED:
            weekly.update(pace=f"Behind: max {round(reachable)}%", color=COLORS["under"])


def save_history(history: dict[str, Any]) -> None:
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = HISTORY_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(history, separators=(",", ":")), encoding="utf-8")
        tmp.replace(HISTORY_CACHE)
    except OSError:
        pass


def jsonl(path: Path):
    try:
        with path.open("r", encoding="utf-8", errors="replace") as lines:
            for line in lines:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    pass
    except OSError:
        return


def latest_token_event(paths: list[Path]) -> tuple[dict[str, Any] | None, dt.datetime | None]:
    latest, latest_time = None, dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    preferred, preferred_time = None, latest_time
    for path in paths:
        for obj in jsonl(path):
            payload = obj.get("payload") or {}
            when = parse_time(obj.get("timestamp"))
            if obj.get("type") == "event_msg" and payload.get("type") == "token_count" and when and when > latest_time:
                latest, latest_time = payload, when
            if obj.get("type") == "event_msg" and payload.get("type") == "token_count" and when and when > preferred_time:
                if (payload.get("rate_limits") or {}).get("limit_id") == "codex":
                    preferred, preferred_time = payload, when
    return (preferred, preferred_time) if preferred else (latest, latest_time if latest else None)


def latest_limit_event(paths: list[Path]) -> tuple[float | None, dt.datetime | None]:
    latest_reset, latest_time = None, dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    for path in paths:
        for obj in jsonl(path):
            when = parse_time(obj.get("timestamp"))
            if not when or when <= latest_time:
                continue
            text = json.dumps(obj.get("payload") or {}, ensure_ascii=False)
            if "usage limit" not in text.lower() and "try again at" not in text.lower():
                continue
            retry = parse_retry_time(text)
            if retry and retry > now():
                latest_reset, latest_time = retry.timestamp(), when
    return latest_reset, latest_time if latest_reset else None


def codex_paths(home: Path, thread_path: Path | None, days: int) -> list[Path]:
    if thread_path and thread_path.exists():
        return [thread_path]
    root = home / "sessions"
    if not root.exists():
        return []
    cutoff = now().timestamp() - days * 86400
    return [p for p in root.rglob("*.jsonl") if p.stat().st_mtime >= cutoff]


def codex(days: int) -> dict[str, Any]:
    home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    thread_path = None
    db = home / "state_5.sqlite"
    if db.exists():
        try:
            with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
                row = conn.execute("select rollout_path from threads order by updated_at_ms desc limit 1").fetchone()
                thread_path = Path(row[0]) if row and row[0] else None
        except sqlite3.Error:
            pass

    all_paths = codex_paths(home, None, days)
    payload, when = latest_token_event(all_paths)
    limit_reset, limit_when = latest_limit_event(all_paths)
    limited = limit_reset is not None and (when is None or (limit_when is not None and limit_when > when))
    current = quota((payload or {}).get("rate_limits"), "primary", when)
    weekly = quota((payload or {}).get("rate_limits"), "secondary", when)
    if limited:
        current, weekly = limited_quota(limit_reset, None), limited_quota(limit_reset)
    return {"available": bool(payload or thread_path or limited), "current": current, "weekly": weekly}


def claude() -> dict[str, Any]:
    cached = read_json(CLAUDE_CACHE) or {}
    limits = cached.get("rate_limits")
    return {
        "available": isinstance(limits, dict),
        "current": quota(limits, "five_hour", parse_time(cached.get("_captured_at"))),
        "weekly": quota(limits, "seven_day", parse_time(cached.get("_captured_at"))),
    }


def as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def fmt_tokens(value: int) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)


def fmt_money(value: float | None) -> str:
    if value is None:
        return "unpriced"
    if value >= 100:
        return f"${value:,.0f}"
    return f"${value:,.2f}"


def token_window_ids(when: dt.datetime | None) -> list[str]:
    if when is None:
        return []
    age = (now() - when).total_seconds()
    return [key for key, _label, seconds in TOKEN_WINDOWS if seconds is None or age <= seconds]


def empty_token_windows() -> dict[str, dict[str, Any]]:
    return {key: {"total": collections.Counter(), "models": collections.defaultdict(collections.Counter)} for key, _label, _seconds in TOKEN_WINDOWS}


def add_tokens(windows: dict[str, dict[str, Any]], when: dt.datetime | None, model: str, values: dict[str, int]) -> None:
    for key in token_window_ids(when):
        windows[key]["total"].update(values)
        windows[key]["models"][model].update(values)


def codex_model_map(home: Path) -> dict[str, str]:
    db = home / "state_5.sqlite"
    if not db.exists():
        return {}
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            return {str(Path(path)): model or "unknown" for path, model in conn.execute("select rollout_path, model from threads") if path}
    except sqlite3.Error:
        return {}


def aggregate_codex_tokens() -> dict[str, dict[str, Any]]:
    home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    root = home / "sessions"
    windows = empty_token_windows()
    models = codex_model_map(home)
    if not root.exists():
        return windows

    for path in root.rglob("*.jsonl"):
        model = models.get(str(path), "unknown")
        previous = {key: 0 for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens")}
        for obj in jsonl(path):
            payload = obj.get("payload") or {}
            if isinstance(payload.get("model"), str):
                model = payload["model"]
            else:
                collaboration = payload.get("collaboration_mode")
                mode = (collaboration.get("settings") if isinstance(collaboration, dict) else None) or {}
                model = mode.get("model") if isinstance(mode.get("model"), str) else model

            if obj.get("type") != "event_msg" or payload.get("type") != "token_count":
                continue
            total = ((payload.get("info") or {}).get("total_token_usage") or {})
            if not total:
                continue
            current = {key: as_int(total.get(key)) for key in previous}
            delta = {key: max(0, current[key] - previous[key]) for key in previous}
            previous = current
            add_tokens(windows, parse_time(obj.get("timestamp")), model, {
                "input": delta["input_tokens"],
                "cached": delta["cached_input_tokens"],
                "output": delta["output_tokens"],
                "reasoning": delta["reasoning_output_tokens"],
                "tokens": delta["total_tokens"],
            })
    return windows


def aggregate_claude_tokens() -> dict[str, dict[str, Any]]:
    root = Path(os.environ.get("CLAUDE_HOME", "~/.claude")).expanduser() / "projects"
    windows = empty_token_windows()
    seen = set()
    if not root.exists():
        return windows

    for path in root.rglob("*.jsonl"):
        for obj in jsonl(path):
            message = obj.get("message") or {}
            usage = message.get("usage") or {}
            if obj.get("type") != "assistant" or not isinstance(usage, dict):
                continue
            event_id = message.get("id") or obj.get("requestId") or obj.get("uuid") or (str(path), obj.get("timestamp"))
            if event_id in seen:
                continue
            seen.add(event_id)
            cache = usage.get("cache_creation") or {}
            write5 = as_int(cache.get("ephemeral_5m_input_tokens"))
            write1h = as_int(cache.get("ephemeral_1h_input_tokens"))
            write_total = as_int(usage.get("cache_creation_input_tokens"))
            values = {
                "input": as_int(usage.get("input_tokens")),
                "write5": write5,
                "write1h": write1h,
                "write_unknown": max(0, write_total - write5 - write1h),
                "read": as_int(usage.get("cache_read_input_tokens")),
                "output": as_int(usage.get("output_tokens")),
            }
            values["tokens"] = sum(values.values())
            add_tokens(windows, parse_time(obj.get("timestamp")), message.get("model") or "unknown", values)
    return windows


def codex_cost(model: str, values: collections.Counter) -> float | None:
    rates = OPENAI_PRICES.get(model)
    if rates is None:
        return None
    uncached = max(0, values["input"] - values["cached"])
    return (uncached * rates["input"] + values["cached"] * rates["cached"] + values["output"] * rates["output"]) / 1_000_000


def claude_cost(model: str, values: collections.Counter) -> float | None:
    rates = CLAUDE_PRICES.get(model)
    if rates is None:
        return None
    return (
        values["input"] * rates["input"]
        + values["write5"] * rates["write5"]
        + values["write1h"] * rates["write1h"]
        + values["write_unknown"] * rates["write5"]
        + values["read"] * rates["read"]
        + values["output"] * rates["output"]
    ) / 1_000_000


def provider_cost(provider: str, model: str, values: collections.Counter) -> float | None:
    return codex_cost(model, values) if provider == "codex" else claude_cost(model, values)


def priced_total(provider: str, models: dict[str, collections.Counter]) -> tuple[float, list[str]]:
    total, unknown = 0.0, []
    for model, values in models.items():
        if values["tokens"] <= 0:
            continue
        cost = provider_cost(provider, model, values)
        if cost is None:
            unknown.append(model)
        else:
            total += cost
    return total, unknown


def window_token_rows(codex_tokens: dict[str, dict[str, Any]], claude_tokens: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    rows = []
    for key, label, _seconds in TOKEN_WINDOWS:
        codex_total, codex_unknown = priced_total("codex", codex_tokens[key]["models"])
        claude_total, claude_unknown = priced_total("claude", claude_tokens[key]["models"])
        codex_token_count = codex_tokens[key]["total"]["tokens"]
        claude_token_count = claude_tokens[key]["total"]["tokens"]
        rows.append({
            "key": key,
            "label": label,
            "codex_tokens": fmt_tokens(codex_token_count),
            "codex_cost": fmt_money(codex_total),
            "claude_tokens": fmt_tokens(claude_token_count),
            "claude_cost": fmt_money(claude_total),
            "unpriced": ", ".join(sorted(set(codex_unknown + claude_unknown))),
        })
    return rows


def token_stats() -> dict[str, Any]:
    codex_tokens = aggregate_codex_tokens()
    claude_tokens = aggregate_claude_tokens()
    windows = window_token_rows(codex_tokens, claude_tokens)
    unknown = sorted({row["unpriced"] for row in windows if row["unpriced"]})
    return {
        "windows": windows,
        "note": "Unpriced models excluded from cost: " + "; ".join(unknown) if unknown else "",
    }


def snapshot(days: int) -> int:
    data = {"codex": codex(days), "claude": claude(), "tokens": token_stats()}
    history = append_history(read_json(HISTORY_CACHE) or {}, data)
    apply_history(data, history)
    save_history(history)
    print(json.dumps(data, separators=(",", ":")))
    return 0


def capture_claude_statusline() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        return 0
    data["_captured_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = CLAUDE_CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(CLAUDE_CACHE)
    model = (data.get("model") or {}).get("display_name") or (data.get("model") or {}).get("id") or "Claude"
    limits = data.get("rate_limits") or {}
    print(f"{model} | 5h used {(limits.get('five_hour') or {}).get('used_percentage', '--')}% | 7d used {(limits.get('seven_day') or {}).get('used_percentage', '--')}%")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days-scan", type=int, default=14)
    parser.add_argument("--capture-claude-statusline", action="store_true")
    parser.add_argument("--stamp", help=argparse.SUPPRESS)
    args = parser.parse_args()
    return capture_claude_statusline() if args.capture_claude_statusline else snapshot(args.days_scan)


if __name__ == "__main__":
    raise SystemExit(main())
