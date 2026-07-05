#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
from pathlib import Path
from typing import Any


CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "ai-usage"
CLAUDE_STATUSLINE_CACHE = CACHE_DIR / "claude-statusline.json"

HEALTH_COLORS = {
    "ok": "#27ae60",
    "warning": "#fdbc4b",
    "critical": "#da4453",
    "missing": "",
}


def local_now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except ValueError:
        return None


def epoch_to_local(value: int | float | None) -> dt.datetime | None:
    if value is None:
        return None
    try:
        return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc).astimezone()
    except (OSError, OverflowError, ValueError):
        return None


def reset_labels(value: int | float | None) -> dict[str, str | None]:
    reset = epoch_to_local(value)
    if reset is None:
        return {"at": None, "short": None, "relative": None, "days": None, "days_label": "--"}

    now = local_now()
    seconds = max(0, int((reset - now).total_seconds()))
    if reset.date() == now.date():
        short = reset.strftime("%H:%M")
    elif reset.date() == (now + dt.timedelta(days=1)).date():
        short = "Tomorrow " + reset.strftime("%H:%M")
    elif seconds < 7 * 86400:
        short = reset.strftime("%a %H:%M")
    else:
        short = reset.strftime("%b %-d %H:%M")

    if seconds < 60:
        relative = "now"
    elif seconds < 3600:
        relative = f"{seconds // 60}m"
    elif seconds < 86400:
        relative = f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    else:
        relative = f"{seconds // 86400}d {(seconds % 86400) // 3600}h"

    days = seconds // 86400
    return {
        "at": reset.isoformat(timespec="seconds"),
        "short": short,
        "relative": relative,
        "days": str(days),
        "days_label": str(days),
    }


def percent_remaining(used: Any) -> float | None:
    try:
        return max(0.0, 100.0 - float(used))
    except (TypeError, ValueError):
        return None


def inferred_window_minutes(key: str, value: dict[str, Any]) -> int | None:
    window = value.get("window_minutes")
    if window is not None:
        try:
            return int(window)
        except (TypeError, ValueError):
            pass
    if key in {"primary", "five_hour"}:
        return 300
    if key in {"secondary", "seven_day"}:
        return 10080
    return None


def quota_health(remaining: float | None, reset_epoch: Any, window_minutes: int | None) -> dict[str, Any]:
    if remaining is None:
        return {
            "expected_remaining_percent": None,
            "pace_delta_percent": None,
            "state": "missing",
            "color": HEALTH_COLORS["missing"],
        }

    expected: float | None = None
    if reset_epoch is not None and window_minutes:
        try:
            seconds_left = max(0.0, float(reset_epoch) - local_now().timestamp())
            expected = max(0.0, min(100.0, seconds_left / (window_minutes * 60) * 100))
        except (TypeError, ValueError):
            expected = None

    if remaining <= 0:
        state = "critical"
    elif expected is not None:
        if remaining >= expected * 0.9:
            state = "ok"
        elif remaining >= max(5.0, expected * 0.5):
            state = "warning"
        else:
            state = "critical"
    elif remaining < 15:
        state = "critical"
    elif remaining < 40:
        state = "warning"
    else:
        state = "ok"

    return {
        "expected_remaining_percent": round(expected, 1) if expected is not None else None,
        "pace_delta_percent": round(remaining - expected, 1) if expected is not None else None,
        "state": state,
        "color": HEALTH_COLORS[state],
    }


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_jsonl(path: Path):
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def sqlite_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def normalize_rate_limits(raw: dict[str, Any] | None, event_time: dt.datetime | None) -> dict[str, Any] | None:
    if not raw:
        return None
    normalized: dict[str, Any] = {
        "limit_id": raw.get("limit_id"),
        "plan_type": raw.get("plan_type"),
        "rate_limit_reached_type": raw.get("rate_limit_reached_type"),
    }
    for key in ("primary", "secondary", "five_hour", "seven_day"):
        value = raw.get(key)
        if not isinstance(value, dict):
            continue
        used = value.get("used_percent", value.get("used_percentage"))
        reset_epoch = value.get("resets_at")
        if reset_epoch is None and value.get("resets_in_seconds") is not None and event_time is not None:
            reset_epoch = event_time.timestamp() + float(value["resets_in_seconds"])
        labels = reset_labels(reset_epoch)
        remaining = percent_remaining(used)
        window = inferred_window_minutes(key, value)
        health = quota_health(remaining, reset_epoch, window)
        normalized[key] = {
            "used_percent": used,
            "remaining_percent": remaining,
            "window_minutes": window,
            "resets_at": reset_epoch,
            "resets_at_local": labels["at"],
            "reset_short": labels["short"],
            "reset_relative": labels["relative"],
            "reset_days": labels["days"],
            "reset_days_label": labels["days_label"],
            **health,
        }
    return normalized


def quota_item(rate_limits: dict[str, Any] | None, key: str) -> dict[str, Any]:
    item = (rate_limits or {}).get(key)
    if not isinstance(item, dict):
        return {
            "used_percent": None,
            "remaining_percent": None,
            "window_minutes": None,
            "resets_at_local": None,
            "reset_short": None,
            "reset_relative": None,
            "reset_days": None,
            "reset_days_label": "--",
            "expected_remaining_percent": None,
            "pace_delta_percent": None,
            "state": "missing",
            "color": HEALTH_COLORS["missing"],
        }
    return item


def codex_thread(codex_home: Path) -> dict[str, Any] | None:
    db = codex_home / "state_5.sqlite"
    if not db.exists():
        return None
    thread_id = os.environ.get("CODEX_THREAD_ID")
    query = """
        select id, rollout_path, created_at_ms, updated_at_ms, model, cwd, title, tokens_used
        from threads
    """
    params: tuple[Any, ...] = ()
    if thread_id:
        query += " where id = ?"
        params = (thread_id,)
    query += " order by updated_at_ms desc limit 1"
    try:
        with sqlite_ro(db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(query, params).fetchone()
    except sqlite3.Error:
        return None
    return dict(row) if row else None


def codex_token_events(path: Path):
    for obj in read_jsonl(path):
        if obj.get("type") != "event_msg":
            continue
        payload = obj.get("payload") or {}
        if payload.get("type") != "token_count":
            continue
        timestamp = parse_iso(obj.get("timestamp"))
        info = payload.get("info") or {}
        total_usage = info.get("total_token_usage") or {}
        yield {
            "timestamp": timestamp,
            "total_tokens": total_usage.get("total_tokens"),
            "token_usage": total_usage or None,
            "model_context_window": info.get("model_context_window"),
            "rate_limits": normalize_rate_limits(payload.get("rate_limits"), timestamp),
        }


def latest_codex_event(path: Path | None, codex_home: Path, days: int) -> dict[str, Any] | None:
    if path and path.exists():
        paths = [path]
    else:
        root = codex_home / "sessions"
        if not root.exists():
            return None
        cutoff = local_now().timestamp() - days * 86400
        paths = [candidate for candidate in root.rglob("*.jsonl") if candidate.stat().st_mtime >= cutoff]

    latest: dict[str, Any] | None = None
    min_time = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    for candidate in paths:
        for event in codex_token_events(candidate):
            if (event["timestamp"] or min_time) > ((latest or {}).get("timestamp") or min_time):
                latest = event
    return latest


def codex_snapshot(days: int) -> dict[str, Any]:
    codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    thread = codex_thread(codex_home)
    rollout_path = Path(thread["rollout_path"]) if thread and thread.get("rollout_path") else None
    current_event = latest_codex_event(rollout_path, codex_home, days)
    latest_event = latest_codex_event(None, codex_home, days)
    limits = (current_event or {}).get("rate_limits") or (latest_event or {}).get("rate_limits")
    return {
        "available": thread is not None or current_event is not None or latest_event is not None,
        "current": quota_item(limits, "primary"),
        "weekly": quota_item(limits, "secondary"),
        "plan_type": (limits or {}).get("plan_type"),
        "source": "codex rollout",
    }


def claude_snapshot() -> dict[str, Any]:
    cached = read_json(CLAUDE_STATUSLINE_CACHE)
    captured_at = parse_iso((cached or {}).get("_captured_at"))
    limits = normalize_rate_limits((cached or {}).get("rate_limits"), captured_at)
    return {
        "available": limits is not None,
        "current": quota_item(limits, "five_hour"),
        "weekly": quota_item(limits, "seven_day"),
        "captured_at": (cached or {}).get("_captured_at"),
        "source": "claude statusline" if limits else "missing statusline",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days-scan", type=int, default=14)
    parser.add_argument("--stamp", help=argparse.SUPPRESS)
    args = parser.parse_args()

    codex = codex_snapshot(args.days_scan)
    claude = claude_snapshot()
    report = {
        "generated_at": local_now().isoformat(timespec="seconds"),
        "codex": codex,
        "claude": claude,
    }
    print(json.dumps(report, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
