#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any


CACHE = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "ai-usage"
CLAUDE_CACHE = CACHE / "claude-statusline.json"
COLORS = {"ok": "#27ae60", "warning": "#fdbc4b", "critical": "#da4453", "missing": ""}


def now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
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


def remaining(used: Any) -> float | None:
    try:
        return max(0.0, 100.0 - float(used))
    except (TypeError, ValueError):
        return None


def window_minutes(name: str, payload: dict[str, Any]) -> int | None:
    if payload.get("window_minutes") is not None:
        return int(payload["window_minutes"])
    return {"primary": 300, "five_hour": 300, "secondary": 10080, "seven_day": 10080}.get(name)


def health(left: float | None, reset_epoch: Any, window: int | None) -> dict[str, Any]:
    if left is None:
        return {"expected_remaining_percent": None, "pace_delta_percent": None, "state": "missing", "color": ""}

    expected = None
    if reset_epoch is not None and window:
        expected = max(0.0, min(100.0, (float(reset_epoch) - now().timestamp()) / (window * 60) * 100))

    if left <= 0:
        state = "critical"
    elif expected is None:
        state = "critical" if left < 15 else "warning" if left < 40 else "ok"
    elif left >= expected * 0.9:
        state = "ok"
    elif left >= max(5.0, expected * 0.5):
        state = "warning"
    else:
        state = "critical"

    return {
        "expected_remaining_percent": round(expected, 1) if expected is not None else None,
        "pace_delta_percent": round(left - expected, 1) if expected is not None else None,
        "state": state,
        "color": COLORS[state],
    }


def blank_quota() -> dict[str, Any]:
    return {
        "used_percent": None,
        "remaining_percent": None,
        "window_minutes": None,
        "resets_at": None,
        **reset_info(None),
        **health(None, None, None),
    }


def quota(raw_limits: dict[str, Any] | None, name: str, event_time: dt.datetime | None) -> dict[str, Any]:
    payload = (raw_limits or {}).get(name)
    if not isinstance(payload, dict):
        return blank_quota()

    reset_epoch = payload.get("resets_at")
    if reset_epoch is None and payload.get("resets_in_seconds") is not None and event_time is not None:
        reset_epoch = event_time.timestamp() + float(payload["resets_in_seconds"])

    used = payload.get("used_percent", payload.get("used_percentage"))
    left = remaining(used)
    window = window_minutes(name, payload)
    return {
        "used_percent": used,
        "remaining_percent": left,
        "window_minutes": window,
        "resets_at": reset_epoch,
        **reset_info(reset_epoch),
        **health(left, reset_epoch, window),
    }


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


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

    payload, when = latest_token_event(codex_paths(home, thread_path, days))
    limits = (payload or {}).get("rate_limits")
    return {
        "available": bool(payload or thread_path),
        "current": quota(limits, "primary", when),
        "weekly": quota(limits, "secondary", when),
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
    print(json.dumps({"generated_at": now().isoformat(timespec="seconds"), "codex": codex(days), "claude": claude()}, separators=(",", ":")))
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
    print(f"{model} | 5h {five}% | 7d {week}%")
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
