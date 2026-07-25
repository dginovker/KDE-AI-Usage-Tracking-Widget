#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import datetime as dt
import fcntl
import json
import math
import os
import select
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from statistics import median
from typing import Any


CACHE = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "ai-usage"
CLAUDE_CACHE = CACHE / "claude-statusline.json"
HISTORY_CACHE = CACHE / "usage-history.json"
PROVIDERS = ("claude", "codex", "kimi")
WINDOWS = {"primary": 300, "five_hour": 300, "secondary": 10080, "seven_day": 10080}
TOKEN_WINDOWS = (("lifetime", "Lifetime", None), ("30d", "30d", 30 * 86400), ("7d", "7d", 7 * 86400), ("24h", "24h", 86400), ("1h", "1h", 3600))
COLORS = {"ok": "#27ae60", "near": "#fdbc4b", "under": "#3daee9"}
TARGET_USED = 80.0
FULL_USED = 99.5
HISTORY_LIMIT = 300
MIN_CURRENT_DELTA = 4.0
OPENAI_PRICES = {
    "gpt-5.6-sol": {"input": 5.0, "cached": 0.5, "output": 30.0},
    "gpt-5.6-terra": {"input": 2.5, "cached": 0.25, "output": 15.0},
    "gpt-5-codex": {"input": 1.25, "cached": 0.125, "output": 10.0},
    "gpt-5.5": {"input": 10.0, "cached": 1.0, "output": 45.0},
    "gpt-5.4-mini": {"input": 0.75, "cached": 0.075, "output": 4.5},
    "gpt-5.3-codex": {"input": 1.75, "cached": 0.175, "output": 14.0},
}
CLAUDE_PRICES = {
    "claude-fable-5": {"input": 10.0, "write5": 12.5, "write1h": 20.0, "read": 1.0, "output": 50.0},
    "claude-opus-5": {"input": 5.0, "write5": 6.25, "write1h": 10.0, "read": 0.5, "output": 25.0},
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
KIMI_PRICES = {
    "kimi-code/kimi-for-coding": {"input": 0.95, "cached": 0.19, "output": 4.0},
    "kimi-k2.7-code": {"input": 0.95, "cached": 0.19, "output": 4.0},
    "kimi-k2.7-code-highspeed": {"input": 1.9, "cached": 0.38, "output": 8.0},
}
KIMI_CLIENT_ID = "17e5f671-d194-4dfb-9706-5516cb48c098"
KIMI_BASE_URL = "https://api.kimi.com/coding/v1"
KIMI_AUTH_HOST = "https://auth.kimi.com"
CODEX_RESET_FORECAST_URL = "https://codex-reset.com/api/forecast"
CODEX_RESET_TIMELINE_URL = "https://codex-reset.com/api/timeline?group=reset"


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


def quota(limits: dict[str, Any] | None, name: str, event_time: dt.datetime | None) -> dict[str, Any]:
    payload = (limits or {}).get(name)
    if not isinstance(payload, dict):
        return blank_quota()

    reset = payload.get("resets_at", payload.get("resetsAt"))
    if reset is None and payload.get("resets_in_seconds") is not None and event_time is not None:
        reset = event_time.timestamp() + float(payload["resets_in_seconds"])
    used = percent(payload.get("used_percent", payload.get("used_percentage", payload.get("usedPercent"))))
    window = int(payload.get("window_minutes") or payload.get("windowDurationMins") or WINDOWS.get(name) or 0) or None
    return {"used": used, **reset_meta(reset), **quota_health(used, reset, window)}


def reset_epoch_from(raw: dict[str, Any]) -> float | None:
    for key in ("reset_at", "resetAt", "reset_time", "resetTime"):
        parsed = parse_time(raw.get(key))
        if parsed:
            return parsed.timestamp()
    for key in ("reset_in", "resetIn", "ttl"):
        seconds = as_float(raw.get(key))
        if seconds is not None and seconds > 0:
            return now().timestamp() + seconds
    return None


def ratio_quota(raw: dict[str, Any] | None, window_minutes: int | None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return blank_quota()
    used = as_float(raw.get("used"))
    limit = as_float(raw.get("limit"))
    remaining = as_float(raw.get("remaining"))
    if used is None and remaining is not None and limit is not None:
        used = limit - remaining
    used_percent = percent(None if used is None or not limit else used * 100.0 / limit)
    reset = reset_epoch_from(raw)
    return {"used": used_percent, **reset_meta(reset), **quota_health(used_percent, reset, window_minutes)}


def kimi_home() -> Path:
    return Path(os.environ.get("KIMI_CODE_HOME", "~/.kimi-code")).expanduser()


def kimi_version(home: Path) -> str:
    for path in (home / "updates" / "latest.json", home / "updates" / "install.json"):
        data = read_json(path) or {}
        for value in (data.get("latest"), data.get("version")):
            if isinstance(value, str) and value:
                return value
    return "0.23.1"


def kimi_device_headers(home: Path) -> dict[str, str]:
    headers = {"X-Msh-Platform": "kimi_code_cli", "X-Msh-Version": kimi_version(home)}
    try:
        device_id = (home / "device_id").read_text(encoding="utf-8").strip()
        if device_id:
            headers["X-Msh-Device-Id"] = device_id
    except OSError:
        pass
    return headers


def request_json(url: str, headers: dict[str, str], body: bytes | None = None, timeout: float = 8) -> dict[str, Any]:
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def save_kimi_credentials(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def refresh_kimi_token(home: Path, credentials: dict[str, Any]) -> str | None:
    refresh = credentials.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        return None
    body = urllib.parse.urlencode({
        "client_id": KIMI_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": refresh,
    }).encode("utf-8")
    payload = request_json(
        os.environ.get("KIMI_CODE_OAUTH_HOST", os.environ.get("KIMI_OAUTH_HOST", KIMI_AUTH_HOST)).rstrip("/") + "/api/oauth/token",
        {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded", **kimi_device_headers(home)},
        body,
    )
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        return None
    updated = {**credentials, **payload}
    expires_in = as_float(updated.get("expires_in"))
    if expires_in:
        updated["expires_at"] = int(now().timestamp() + expires_in)
    save_kimi_credentials(home / "credentials" / "kimi-code.json", updated)
    return token


def kimi_access_token(home: Path, force_refresh: bool = False) -> str | None:
    credentials = read_json(home / "credentials" / "kimi-code.json") or {}
    token = credentials.get("access_token")
    expires_at = as_float(credentials.get("expires_at"))
    if expires_at is not None and expires_at > 10**12:
        expires_at /= 1000.0
    if not force_refresh and isinstance(token, str) and token and (expires_at is None or expires_at - now().timestamp() > 60):
        return token
    try:
        return refresh_kimi_token(home, credentials)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return token if isinstance(token, str) and token else None


def kimi_payload(home: Path) -> dict[str, Any] | None:
    base_url = os.environ.get("KIMI_CODE_BASE_URL", KIMI_BASE_URL).rstrip("/")
    token = kimi_access_token(home)
    if not token:
        return None
    try:
        return request_json(base_url + "/usages", {"Authorization": f"Bearer {token}", "Accept": "application/json"})
    except urllib.error.HTTPError as error:
        if error.code != 401:
            raise
        token = kimi_access_token(home, True)
        if not token:
            return None
        return request_json(base_url + "/usages", {"Authorization": f"Bearer {token}", "Accept": "application/json"})


def kimi_window_minutes(raw: dict[str, Any]) -> int | None:
    duration_value = (raw.get("window") or {}).get("duration") if isinstance(raw.get("window"), dict) else raw.get("duration")
    duration = as_float(duration_value)
    if duration is None:
        return None
    unit = str((raw.get("window") or {}).get("timeUnit") if isinstance(raw.get("window"), dict) else raw.get("timeUnit")).upper()
    if "MINUTE" in unit:
        return int(duration)
    if "HOUR" in unit:
        return int(duration * 60)
    if "DAY" in unit:
        return int(duration * 1440)
    return int(duration / 60) if duration > 1000 else int(duration)


def kimi() -> dict[str, Any]:
    try:
        payload = kimi_payload(kimi_home()) or {}
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        payload = {}
    weekly_raw = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
    limits = payload.get("limits") if isinstance(payload.get("limits"), list) else []
    current_item = next((item for item in limits if isinstance(item, dict) and kimi_window_minutes(item) == 300), None)
    current_raw = (current_item or {}).get("detail") if isinstance((current_item or {}).get("detail"), dict) else current_item
    return {
        "available": bool(weekly_raw or current_raw),
        "current": ratio_quota(current_raw, kimi_window_minutes(current_item or {}) or 300),
        "weekly": ratio_quota(weekly_raw, 7 * 24 * 60),
    }


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


def codex_rpc(process: subprocess.Popen, request: dict[str, Any], timeout: float = 5) -> dict[str, Any] | None:
    if process.stdin is None or process.stdout is None:
        return None
    process.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
    process.stdin.flush()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([process.stdout], [], [], deadline - time.monotonic())
        if not ready:
            break
        line = process.stdout.readline()
        if not line:
            break
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message.get("id") == request.get("id"):
            result = message.get("result")
            return result if isinstance(result, dict) else None
    return None


def codex_window(limits: dict[str, Any] | None, minutes: int) -> dict[str, Any]:
    payload = next((window for window in (limits or {}).values()
                    if isinstance(window, dict) and round(as_float(window.get("windowDurationMins", window.get("window_minutes"))) or 0) == minutes), None)
    return quota({"window": payload}, "window", None)


def short_time(value: Any) -> str:
    stamp = as_float(value)
    try:
        moment = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).astimezone() if stamp is not None else parse_time(value if isinstance(value, str) else None)
    except (OSError, OverflowError, ValueError):
        moment = None
    if moment is None:
        return ""
    ref = now()
    if moment.date() == ref.date():
        return "today " + moment.strftime("%H:%M")
    if moment.date() == (ref + dt.timedelta(days=1)).date():
        return "tomorrow " + moment.strftime("%H:%M")
    if moment.date() == (ref - dt.timedelta(days=1)).date():
        return "yesterday " + moment.strftime("%H:%M")
    return moment.strftime("%a %H:%M") if abs((moment.date() - ref.date()).days) < 7 else moment.strftime("%b %-d %H:%M")


def codex_reset_info() -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": "KDE-AI-Usage-Widget/1"}
    result = {}
    try:
        timeline = request_json(CODEX_RESET_TIMELINE_URL, headers, timeout=3)
        events = timeline.get("events") if isinstance(timeline.get("events"), list) else []
        past = [short_time(item.get("announced_at")) for item in events if isinstance(item, dict)][:3]
        if past:
            result["past"] = " | ".join(label for label in past if label)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        pass
    try:
        payload = request_json(CODEX_RESET_FORECAST_URL, headers, timeout=3)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return result
    updated = parse_time(payload.get("updated_at"))
    if updated is None or abs((now() - updated).total_seconds()) > 2 * 3600:
        return result
    signal = payload.get("official_signal")
    if signal:
        window = signal.get("official_window", signal.get("window", {})) if isinstance(signal, dict) else {}
        label = window.get("label") if isinstance(window, dict) else None
        result["next"] = str(label).capitalize() + " (announced)" if label else "Announced"
    else:
        probabilities = payload.get("probabilities") or {}
        day = as_float(probabilities.get("rounded_24h"))
        two_days = as_float(probabilities.get("rounded_48h"))
        if day is not None and two_days is not None:
            result["next"] = f"24h ~{round(day)}%, 48h ~{round(two_days)}%"
    return result


def banked_resets(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    credits = payload.get("credits") if isinstance(payload.get("credits"), list) else []
    available = [item for item in credits if isinstance(item, dict) and item.get("status") == "available"]
    count_value = as_float(payload.get("availableCount"))
    count = int(count_value) if count_value is not None else len(available)
    expiries = sorted(stamp for item in available if (stamp := as_float(item.get("expiresAt"))) is not None and stamp > now().timestamp())
    if not expiries:
        return str(count)
    prefix = "expires" if count == 1 else "next expiry"
    return f"{count} | {prefix} {short_time(expiries[0])}"


def codex() -> dict[str, Any]:
    binary = os.environ.get("CODEX_BIN") or shutil.which("codex") or str(Path.home() / ".local/bin/codex")
    reset_info = codex_reset_info()
    process = None
    try:
        process = subprocess.Popen(
            [binary, "app-server", "--stdio"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
        initialized = codex_rpc(process, {
            "method": "initialize", "id": 1,
            "params": {"clientInfo": {"name": "kde_ai_usage", "title": "KDE AI Usage", "version": "1"}},
        })
        if initialized is None or process.stdin is None:
            return {"available": False, "current": blank_quota(), "weekly": blank_quota(), "global_resets": reset_info}
        process.stdin.write('{"method":"initialized"}\n')
        process.stdin.flush()
        result = codex_rpc(process, {"method": "account/rateLimits/read", "id": 2}) or {}
        limits = result.get("rateLimits")
        banked = banked_resets(result.get("rateLimitResetCredits"))
        if banked:
            reset_info["banked"] = banked
        return {
            "available": isinstance(limits, dict),
            "current": codex_window(limits, 300),
            "weekly": codex_window(limits, 10080),
            "global_resets": reset_info,
        }
    except (BrokenPipeError, OSError, subprocess.SubprocessError):
        return {"available": False, "current": blank_quota(), "weekly": blank_quota(), "global_resets": reset_info}
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()


def select_claude_window(candidates: Any, minutes: int, captured_at: float) -> dict[str, Any] | None:
    valid = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        reset = as_float(raw.get("resets_at"))
        used = percent(raw.get("used_percent", raw.get("used_percentage")))
        if reset is not None and used is not None and captured_at < reset <= captured_at + minutes * 60 + 300:
            valid.append((reset, used, raw))
    return max(valid, default=(None, None, None), key=lambda item: item[:2])[2]


def claude(history: dict[str, Any]) -> dict[str, Any]:
    cached = read_json(CLAUDE_CACHE) or {}
    limits = cached.get("rate_limits")
    limits = dict(limits) if isinstance(limits, dict) else {}
    samples = history.get("claude") if isinstance(history.get("claude"), list) else []
    captured_at = now().timestamp()
    for name, key, minutes in (("five_hour", "current", 300), ("seven_day", "weekly", 10080)):
        historical = ({"resets_at": item.get(f"{key}_reset"), "used_percentage": item.get(f"{key}_used")} for item in samples if isinstance(item, dict))
        limits[name] = select_claude_window([limits.get(name), *historical], minutes, captured_at)
    return {
        "available": any(isinstance(limits.get(name), dict) for name in ("five_hour", "seven_day")),
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


def aggregate_kimi_tokens() -> dict[str, dict[str, Any]]:
    root = kimi_home() / "sessions"
    windows = empty_token_windows()
    if not root.exists():
        return windows

    for path in root.rglob("wire.jsonl"):
        for obj in jsonl(path):
            usage = obj.get("usage") or {}
            if obj.get("type") != "usage.record" or obj.get("usageScope") != "turn" or not isinstance(usage, dict):
                continue
            values = {
                "input": as_int(usage.get("inputOther")) + as_int(usage.get("inputCacheCreation")),
                "cached": as_int(usage.get("inputCacheRead")),
                "output": as_int(usage.get("output")),
            }
            values["tokens"] = sum(values.values())
            event_time = as_float(obj.get("time"))
            when = dt.datetime.fromtimestamp(event_time / 1000, dt.timezone.utc).astimezone() if event_time else None
            add_tokens(windows, when, obj.get("model") or "unknown", values)
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


def kimi_cost(model: str, values: collections.Counter) -> float | None:
    rates = KIMI_PRICES.get(model)
    if rates is None:
        return None
    return (values["input"] * rates["input"] + values["cached"] * rates["cached"] + values["output"] * rates["output"]) / 1_000_000


def provider_cost(provider: str, model: str, values: collections.Counter) -> float | None:
    if provider == "codex":
        return codex_cost(model, values)
    if provider == "kimi":
        return kimi_cost(model, values)
    return claude_cost(model, values)


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


def window_token_rows(provider_tokens: dict[str, dict[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for key, label, _seconds in TOKEN_WINDOWS:
        row, providers, unknown = {"key": key, "label": label}, {}, []
        for provider, tokens in provider_tokens.items():
            total, unpriced = priced_total(provider, tokens[key]["models"])
            unknown.extend(unpriced)
            values = {"tokens": fmt_tokens(tokens[key]["total"]["tokens"]), "cost": fmt_money(total)}
            providers[provider] = values
            row[f"{provider}_tokens"] = values["tokens"]
            row[f"{provider}_cost"] = values["cost"]
        row["providers"] = providers
        row["unpriced"] = ", ".join(sorted(set(unknown)))
        rows.append(row)
    return rows


def token_stats() -> dict[str, Any]:
    windows = window_token_rows({
        "codex": aggregate_codex_tokens(),
        "claude": aggregate_claude_tokens(),
        "kimi": aggregate_kimi_tokens(),
    })
    unknown = sorted({row["unpriced"] for row in windows if row["unpriced"]})
    return {
        "windows": windows,
        "note": "Unpriced models excluded from cost: " + "; ".join(unknown) if unknown else "",
    }


def snapshot() -> int:
    history = read_json(HISTORY_CACHE) or {}
    data = {"codex": codex(), "claude": claude(history), "kimi": kimi(), "tokens": token_stats()}
    history = append_history(history, data)
    apply_history(data, history)
    save_history(history)
    print(json.dumps(data, separators=(",", ":")))
    return 0


def capture_claude_statusline() -> int:
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        return 0

    captured = dt.datetime.now(dt.timezone.utc)
    data["_captured_at"] = captured.isoformat(timespec="seconds").replace("+00:00", "Z")
    CACHE.mkdir(parents=True, exist_ok=True)
    with (CACHE / "claude-statusline.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = read_json(CLAUDE_CACHE) or {}
        old_limits = previous.get("rate_limits")
        new_limits = data.get("rate_limits")
        old_limits = old_limits if isinstance(old_limits, dict) else {}
        new_limits = new_limits if isinstance(new_limits, dict) else {}
        merged = {**old_limits, **new_limits}
        for name, minutes in (("five_hour", 300), ("seven_day", 10080)):
            selected = select_claude_window((old_limits.get(name), new_limits.get(name)), minutes, captured.timestamp())
            if selected:
                merged[name] = selected
            else:
                merged.pop(name, None)
        data["rate_limits"] = merged
        tmp = CLAUDE_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(CLAUDE_CACHE)
    model = (data.get("model") or {}).get("display_name") or (data.get("model") or {}).get("id") or "Claude"
    limits = data.get("rate_limits") or {}
    print(f"{model} | 5h used {(limits.get('five_hour') or {}).get('used_percentage', '--')}% | 7d used {(limits.get('seven_day') or {}).get('used_percentage', '--')}%")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-claude-statusline", action="store_true")
    parser.add_argument("--stamp", help=argparse.SUPPRESS)
    args = parser.parse_args()
    return capture_claude_statusline() if args.capture_claude_statusline else snapshot()


if __name__ == "__main__":
    raise SystemExit(main())
