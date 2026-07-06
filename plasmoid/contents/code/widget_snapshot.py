#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any


CACHE = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "ai-usage"
CLAUDE_CACHE = CACHE / "claude-statusline.json"
HISTORY_CACHE = CACHE / "usage-history.json"
COLORS = {"ok": "#27ae60", "near": "#fdbc4b", "under": "#3daee9", "missing": ""}
TARGET_USED = 80.0
FULL_USED = 99.5
HISTORY_LIMIT = 300
MIN_CURRENT_DELTA = 4.0
LIMIT_RETRY_RE = re.compile(r"try again at ([A-Z][a-z]+\.? \d{1,2}(?:st|nd|rd|th)?, \d{4} \d{1,2}:\d{2} [AP]M)", re.I)


def now() -> dt.datetime:
    return dt.datetime.now().astimezone()


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


def local_epoch(epoch: Any) -> dt.datetime | None:
    try:
        return dt.datetime.fromtimestamp(float(epoch), dt.timezone.utc).astimezone()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def reset_info(epoch: Any) -> dict[str, Any]:
    reset = local_epoch(epoch)
    if reset is None:
        return {"resets_at_local": None, "reset_short": None, "reset_days_label": "?"}

    seconds = max(0, int((reset - now()).total_seconds()))
    if reset.date() == now().date():
        short = reset.strftime("%H:%M")
    elif reset.date() == (now() + dt.timedelta(days=1)).date():
        short = "Tomorrow " + reset.strftime("%H:%M")
    elif seconds < 7 * 86400:
        short = reset.strftime("%a %H:%M")
    else:
        short = reset.strftime("%b %-d %H:%M")

    return {
        "resets_at_local": reset.isoformat(timespec="seconds"),
        "reset_short": short,
        "reset_days_label": str(seconds // 86400),
    }


def used_value(used: Any) -> float | None:
    try:
        return max(0.0, min(100.0, float(used)))
    except (TypeError, ValueError):
        return None


def compact_duration(seconds: float) -> str:
    minutes = max(1, int((seconds + 59) // 60))
    if minutes < 90:
        return f"{minutes}m"

    hours = int((minutes + 30) // 60)
    if hours < 36:
        return f"{hours}h"

    days = hours // 24
    extra = hours % 24
    return f"{days}d {extra}h" if extra and days < 3 else f"{days}d"


def window_minutes(name: str, payload: dict[str, Any]) -> int | None:
    if payload.get("window_minutes") is not None:
        return int(payload["window_minutes"])
    return {"primary": 300, "five_hour": 300, "secondary": 10080, "seven_day": 10080}.get(name)


def pace_ready(window: int | None, elapsed_seconds: float | None) -> bool:
    if window is None or elapsed_seconds is None:
        return False
    minimum = 12 * 60 * 60 if window >= 7 * 24 * 60 else 30 * 60
    return elapsed_seconds >= minimum


def health(used: float | None, reset_epoch: Any, window: int | None) -> dict[str, Any]:
    if used is None:
        return {"target_used_percent": None, "projected_used_percent": None, "max_used_percent": None, "pace_delta_percent": None, "pace_label": "--", "state": "missing", "color": ""}

    target_now = projected = raw_projected = max_used = limit_early = None
    ready = False
    if reset_epoch is not None and window:
        seconds_left = max(0.0, float(reset_epoch) - now().timestamp())
        window_seconds = window * 60
        left_fraction = max(0.0, min(1.0, seconds_left / window_seconds))
        elapsed = max(0.0, 1.0 - left_fraction)
        elapsed_seconds = window_seconds * elapsed
        ready = pace_ready(window, elapsed_seconds)
        target_now = TARGET_USED * elapsed
        raw_projected = used if elapsed <= 0 else used / elapsed
        projected = min(100.0, raw_projected)
        max_used = min(100.0, used + 100.0 * left_fraction)
        if raw_projected > 100.0:
            limit_early = seconds_left if used >= 100.0 else seconds_left - ((100.0 - used) * window_seconds * elapsed / used)

    expected = projected if projected is not None else used
    if not ready:
        pace_label = "Collecting pace"
    elif limit_early is not None and limit_early > 0:
        pace_label = f"Limit {compact_duration(limit_early)} early"
    else:
        pace_label = f"Expected {round(expected)}%"

    if limit_early is not None and limit_early > 0 and ready:
        state = "near"
    elif raw_projected is not None and ready:
        if raw_projected >= TARGET_USED:
            state = "ok"
        elif raw_projected >= TARGET_USED * 0.8:
            state = "near"
        else:
            state = "under"
    elif used >= TARGET_USED:
        state = "ok"
    elif used >= TARGET_USED * 0.8:
        state = "near"
    else:
        state = "under"

    return {
        "target_used_percent": round(target_now, 1) if target_now is not None else TARGET_USED,
        "projected_used_percent": round(projected, 1) if projected is not None else None,
        "max_used_percent": round(max_used, 1) if max_used is not None else None,
        "pace_delta_percent": round(used - target_now, 1) if target_now is not None else None,
        "pace_label": pace_label,
        "state": state,
        "color": COLORS[state],
    }


def blank_quota() -> dict[str, Any]:
    return {
        "used_percent": None,
        "window_minutes": None,
        "resets_at": None,
        **reset_info(None),
        **health(None, None, None),
    }


def limited_quota(reset_epoch: float, used: float | None = 100.0) -> dict[str, Any]:
    return {
        "used_percent": used,
        "window_minutes": None,
        "resets_at": reset_epoch,
        **reset_info(reset_epoch),
        "target_used_percent": None,
        "projected_used_percent": None,
        "max_used_percent": None,
        "pace_delta_percent": None,
        "pace_label": "Limited",
        "rate_limited": True,
        "state": "limited",
        "color": "#da4453",
    }


def quota(raw_limits: dict[str, Any] | None, name: str, event_time: dt.datetime | None) -> dict[str, Any]:
    payload = (raw_limits or {}).get(name)
    if not isinstance(payload, dict):
        return blank_quota()

    reset_epoch = payload.get("resets_at")
    if reset_epoch is None and payload.get("resets_in_seconds") is not None and event_time is not None:
        reset_epoch = event_time.timestamp() + float(payload["resets_in_seconds"])

    used = payload.get("used_percent", payload.get("used_percentage"))
    used = used_value(used)
    window = window_minutes(name, payload)
    return {
        "used_percent": used,
        "window_minutes": window,
        "resets_at": reset_epoch,
        **reset_info(reset_epoch),
        **health(used, reset_epoch, window),
    }


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def history_record(data: dict[str, Any], provider: str) -> dict[str, Any] | None:
    provider_data = data.get(provider) or {}
    current = provider_data.get("current") or {}
    weekly = provider_data.get("weekly") or {}
    current_used = safe_float(current.get("used_percent"))
    weekly_used = safe_float(weekly.get("used_percent"))
    current_reset = safe_float(current.get("resets_at"))
    weekly_reset = safe_float(weekly.get("resets_at"))
    if None in (current_used, weekly_used, current_reset, weekly_reset):
        return None
    return {
        "at": data["generated_at"],
        "current_used": current_used,
        "current_reset": current_reset,
        "weekly_used": weekly_used,
        "weekly_reset": weekly_reset,
    }


def append_history(history: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    for provider in ("claude", "codex"):
        record = history_record(data, provider)
        if not record:
            continue
        items = history.get(provider)
        if not isinstance(items, list):
            items = []
        if not items or any(record.get(key) != items[-1].get(key) for key in ("current_used", "current_reset", "weekly_used", "weekly_reset")):
            items.append(record)
        history[provider] = items[-HISTORY_LIMIT:]
    return history


def conversion_ratio(history: dict[str, Any], provider: str) -> tuple[float | None, int]:
    items = history.get(provider)
    if not isinstance(items, list):
        return None, 0

    ratios = []
    for prev, current in zip(items, items[1:]):
        if prev.get("current_reset") != current.get("current_reset") or prev.get("weekly_reset") != current.get("weekly_reset"):
            continue
        current_used = safe_float(current.get("current_used"))
        prev_current_used = safe_float(prev.get("current_used"))
        weekly_used = safe_float(current.get("weekly_used"))
        prev_weekly_used = safe_float(prev.get("weekly_used"))
        if None in (current_used, prev_current_used, weekly_used, prev_weekly_used):
            continue
        current_delta = current_used - prev_current_used
        weekly_delta = weekly_used - prev_weekly_used
        if current_delta >= MIN_CURRENT_DELTA and weekly_delta > 0:
            ratio = weekly_delta / current_delta
            if 0 < ratio <= 1:
                ratios.append(ratio)

    return median(ratios[-20:]), len(ratios)


def current_capacity_units(current: dict[str, Any], weekly: dict[str, Any]) -> float | None:
    current_used = safe_float(current.get("used_percent"))
    current_reset = safe_float(current.get("resets_at"))
    weekly_reset = safe_float(weekly.get("resets_at"))
    if None in (current_used, current_reset, weekly_reset) or weekly_reset <= now().timestamp() or current_reset <= now().timestamp():
        return None

    units = max(0.0, 100.0 - current_used)
    if current_reset < weekly_reset:
        units += math.ceil((weekly_reset - current_reset) / (5 * 60 * 60)) * 100.0
    return units


def apply_history_verdicts(data: dict[str, Any], history: dict[str, Any]) -> None:
    for provider in ("claude", "codex"):
        ratio, samples = conversion_ratio(history, provider)
        provider_data = data.get(provider) or {}
        current = provider_data.get("current") or {}
        weekly = provider_data.get("weekly") or {}
        weekly["conversion_samples"] = samples
        if ratio is None or safe_float(weekly.get("used_percent")) is None:
            continue

        weekly["weekly_per_current_percent"] = round(ratio, 4)
        capacity = current_capacity_units(current, weekly)
        if capacity is None:
            continue

        reachable = min(100.0, safe_float(weekly["used_percent"]) + capacity * ratio)
        weekly["max_reachable_percent"] = round(reachable, 1)
        if reachable < FULL_USED:
            weekly["pace_label"] = f"Behind: max {round(reachable)}%"
            weekly["state"] = "under"
            weekly["color"] = COLORS["under"]


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
    for path in paths:
        for obj in jsonl(path):
            payload = obj.get("payload") or {}
            when = parse_time(obj.get("timestamp"))
            if obj.get("type") == "event_msg" and payload.get("type") == "token_count" and when and when > latest_time:
                latest, latest_time = payload, when
    return latest, latest_time if latest else None


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
    cutoff = now().timestamp() - days * 86400
    return [p for p in root.rglob("*.jsonl") if root.exists() and p.stat().st_mtime >= cutoff]


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
    payload, when = latest_token_event(codex_paths(home, thread_path, days))
    if payload is None:
        payload, when = latest_token_event(all_paths)
    limit_reset, limit_when = latest_limit_event(all_paths)
    limits = (payload or {}).get("rate_limits")
    limited = limit_reset is not None and (when is None or (limit_when is not None and limit_when > when))
    current = quota(limits, "primary", when)
    weekly = quota(limits, "secondary", when)
    if limited:
        current = limited_quota(limit_reset, None)
        weekly = limited_quota(limit_reset)
    return {
        "available": bool(payload or thread_path or limited),
        "current": current,
        "weekly": weekly,
    }


def claude() -> dict[str, Any]:
    cached = read_json(CLAUDE_CACHE) or {}
    when = parse_time(cached.get("_captured_at"))
    limits = cached.get("rate_limits")
    return {
        "available": isinstance(limits, dict),
        "current": quota(limits, "five_hour", when),
        "weekly": quota(limits, "seven_day", when),
    }


def snapshot(days: int) -> int:
    data = {"generated_at": now().isoformat(timespec="seconds"), "codex": codex(days), "claude": claude()}
    history = append_history(read_json(HISTORY_CACHE) or {}, data)
    apply_history_verdicts(data, history)
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
    five = (limits.get("five_hour") or {}).get("used_percentage", "--")
    week = (limits.get("seven_day") or {}).get("used_percentage", "--")
    print(f"{model} | 5h used {five}% | 7d used {week}%")
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
