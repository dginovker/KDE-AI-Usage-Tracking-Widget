#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "ai-usage"
CLAUDE_STATUSLINE_CACHE = DEFAULT_CACHE_DIR / "claude-statusline.json"


FRIENDLY_PLASMOIDS = {
    "org.kde.plasma.kickoff": "Application Launcher",
    "org.kde.plasma.quicklaunch": "Quick Launch",
    "org.kde.plasma.taskmanager": "Task Manager",
    "org.kde.plasma.marginsseparator": "Margins Separator",
    "org.kde.plasma.pager": "Pager",
    "org.kde.plasma.panelspacer": "Panel Spacer",
    "org.kde.plasma.systemmonitor": "System Monitor",
    "org.kde.plasma.systemmonitor.net": "Network Speed Monitor",
    "org.kde.plasma.systemtray": "System Tray",
    "org.kde.plasma.digitalclock": "Digital Clock",
    "org.kde.plasma.showdesktop": "Show Desktop",
    "org.kde.kscreen": "Display Configuration",
    "org.kde.plasma.keyboardlayout": "Keyboard Layout",
    "org.kde.plasma.keyboardindicator": "Keyboard Indicator",
    "org.kde.plasma.notifications": "Notifications",
    "org.kde.plasma.cameraindicator": "Camera Indicator",
    "org.kde.plasma.manage-inputmethod": "Input Method",
    "org.kde.plasma.volume": "Volume",
    "org.kde.plasma.devicenotifier": "Device Notifier",
    "org.kde.plasma.printmanager": "Print Manager",
    "org.kde.plasma.battery": "Battery",
    "org.kde.plasma.brightness": "Brightness",
    "org.kde.plasma.networkmanagement": "Network Management",
    "org.kde.plasma.mediacontroller": "Media Controller",
    "org.kde.plasma.bluetooth": "Bluetooth",
    "org.kde.plasma.clipboard": "Clipboard",
    "org.kde.plasma.weather": "Weather",
}

PLASMA_LOCATIONS = {
    "0": "floating/desktop",
    "1": "top",
    "2": "right",
    "3": "left",
    "4": "bottom",
}


def local_now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone()


def epoch_to_local(value: int | float | None) -> str | None:
    if value is None:
        return None
    return dt.datetime.fromtimestamp(float(value), tz=dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def human_int(value: Any) -> str:
    if value is None:
        return "unknown"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def percent_remaining(used: Any) -> float | None:
    try:
        return max(0.0, 100.0 - float(used))
    except (TypeError, ValueError):
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


def parse_plasma_config(path: Path) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current: str | None = None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return sections

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, {})
            continue
        if current and "=" in line:
            key, value = line.split("=", 1)
            sections[current][key] = value
    return sections


def section_parts(section: str) -> list[str]:
    return section.split("][")


def applet_config(sections: dict[str, dict[str, str]], containment_id: str, applet_id: str) -> dict[str, dict[str, str]]:
    prefix = f"Containments][{containment_id}][Applets][{applet_id}][Configuration"
    result: dict[str, dict[str, str]] = {}
    for section, values in sections.items():
        if section.startswith(prefix):
            suffix = section[len(prefix):].strip("[]") or "Configuration"
            result[suffix] = values
    return result


def describe_applet(plugin: str, config: dict[str, dict[str, str]]) -> str | None:
    if plugin == "org.kde.plasma.quicklaunch":
        launchers = config.get("General", {}).get("launcherUrls")
        return f"launchers={launchers}" if launchers else None
    if plugin == "org.kde.plasma.taskmanager":
        launchers = config.get("General", {}).get("launchers")
        if launchers:
            launchers = launchers.replace("\\n", ", ")
        return f"pinned={launchers}" if launchers else None
    if plugin in {"org.kde.plasma.systemmonitor", "org.kde.plasma.systemmonitor.net"}:
        sensors = config.get("Sensors", {}).get("highPrioritySensorIds") or config.get("Sensors", {}).get("totalSensors")
        title = config.get("Appearance", {}).get("title")
        parts = []
        if title:
            parts.append(f"title={title}")
        if sensors:
            parts.append(f"sensors={sensors}")
        return "; ".join(parts) if parts else None
    if plugin == "org.kde.plasma.systemtray":
        return None
    return None


def kde_widgets() -> dict[str, Any]:
    path = Path("~/.config/plasma-org.kde.plasma.desktop-appletsrc").expanduser()
    sections = parse_plasma_config(path)
    panels = []

    for section, values in sections.items():
        parts = section_parts(section)
        if len(parts) == 2 and parts[0] == "Containments" and values.get("plugin") == "org.kde.panel":
            containment_id = parts[1]
            general = sections.get(f"Containments][{containment_id}][General", {})
            order = [item for item in general.get("AppletOrder", "").split(";") if item]
            direct_applets: dict[str, dict[str, Any]] = {}
            nested_applets: dict[str, list[dict[str, Any]]] = {}

            for applet_section, applet_values in sections.items():
                applet_parts = section_parts(applet_section)
                if (
                    len(applet_parts) == 4
                    and applet_parts[0] == "Containments"
                    and applet_parts[1] == containment_id
                    and applet_parts[2] == "Applets"
                    and "plugin" in applet_values
                ):
                    applet_id = applet_parts[3]
                    plugin = applet_values["plugin"]
                    config = applet_config(sections, containment_id, applet_id)
                    direct_applets[applet_id] = {
                        "id": applet_id,
                        "plugin": plugin,
                        "name": FRIENDLY_PLASMOIDS.get(plugin, plugin),
                        "details": describe_applet(plugin, config),
                    }
                elif (
                    len(applet_parts) == 6
                    and applet_parts[0] == "Containments"
                    and applet_parts[1] == containment_id
                    and applet_parts[2] == "Applets"
                    and applet_parts[4] == "Applets"
                    and "plugin" in applet_values
                ):
                    parent_id = applet_parts[3]
                    plugin = applet_values["plugin"]
                    nested_applets.setdefault(parent_id, []).append(
                        {
                            "id": applet_parts[5],
                            "plugin": plugin,
                            "name": FRIENDLY_PLASMOIDS.get(plugin, plugin),
                        }
                    )

            ordered = [direct_applets[item] for item in order if item in direct_applets]
            for applet_id, applet in direct_applets.items():
                if applet_id not in order:
                    ordered.append(applet)
            for applet in ordered:
                if applet["id"] in nested_applets:
                    applet["contained_applets"] = sorted(nested_applets[applet["id"]], key=lambda item: int(item["id"]))

            panels.append(
                {
                    "containment_id": containment_id,
                    "location": PLASMA_LOCATIONS.get(values.get("location", ""), values.get("location")),
                    "applets": ordered,
                }
            )

    return {"source": str(path), "panels": panels}


def sqlite_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def codex_thread_from_db(codex_home: Path, thread_id: str | None) -> dict[str, Any] | None:
    db = codex_home / "state_5.sqlite"
    if not db.exists():
        return None

    query = """
        select id, rollout_path, created_at_ms, updated_at_ms, source, model_provider,
               model, cwd, title, tokens_used
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

    if row is None:
        return None
    return dict(row)


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
        window = value.get("window_minutes")
        normalized[key] = {
            "used_percent": used,
            "remaining_percent": percent_remaining(used),
            "window_minutes": window,
            "resets_at": reset_epoch,
            "resets_at_local": epoch_to_local(reset_epoch),
        }
    return normalized


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
        last_usage = info.get("last_token_usage") or {}
        yield {
            "timestamp": timestamp,
            "path": str(path),
            "total_tokens": total_usage.get("total_tokens"),
            "total_token_usage": total_usage or None,
            "last_token_usage": last_usage or None,
            "model_context_window": info.get("model_context_window"),
            "rate_limits": normalize_rate_limits(payload.get("rate_limits"), timestamp),
        }


def latest_codex_event(path: Path | None = None, codex_home: Path | None = None, days: int = 14) -> dict[str, Any] | None:
    paths: list[Path]
    if path and path.exists():
        paths = [path]
    else:
        root = (codex_home or Path("~/.codex").expanduser()) / "sessions"
        if not root.exists():
            return None
        cutoff = local_now().timestamp() - (days * 86400)
        paths = [candidate for candidate in root.rglob("*.jsonl") if candidate.stat().st_mtime >= cutoff]

    latest: dict[str, Any] | None = None
    for candidate in paths:
        for event in codex_token_events(candidate):
            if latest is None or ((event["timestamp"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc)) > (latest["timestamp"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc))):
                latest = event
    return latest


def codex_tokens_since(codex_home: Path, since: dt.datetime, days_scan: int) -> int:
    root = codex_home / "sessions"
    if not root.exists():
        return 0
    cutoff_mtime = since.timestamp() - 86400
    total = 0
    for path in root.rglob("*.jsonl"):
        try:
            if path.stat().st_mtime < cutoff_mtime and days_scan > 0:
                continue
        except OSError:
            continue
        previous: int | None = None
        for event in codex_token_events(path):
            current = event.get("total_tokens")
            if current is None:
                continue
            current = int(current)
            timestamp = event.get("timestamp")
            if timestamp and timestamp >= since:
                total += max(0, current - (previous or 0))
            previous = current
    return total


def codex_report(days: int) -> dict[str, Any]:
    codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    thread_id = os.environ.get("CODEX_THREAD_ID")
    thread = codex_thread_from_db(codex_home, thread_id)
    rollout_path = Path(thread["rollout_path"]) if thread and thread.get("rollout_path") else None
    current_event = latest_codex_event(rollout_path, codex_home, days=days)
    latest_event = latest_codex_event(None, codex_home, days=days)
    since = local_now() - dt.timedelta(days=7)

    return {
        "source": {
            "state_db": str(codex_home / "state_5.sqlite"),
            "sessions_dir": str(codex_home / "sessions"),
        },
        "thread": thread,
        "current_session": {
            "thread_id": thread.get("id") if thread else thread_id,
            "rollout_path": str(rollout_path) if rollout_path else None,
            "tokens": (current_event or {}).get("total_tokens") or (thread or {}).get("tokens_used"),
            "token_usage": (current_event or {}).get("total_token_usage"),
            "model_context_window": (current_event or {}).get("model_context_window"),
            "rate_limits": (current_event or {}).get("rate_limits"),
        },
        "last_7_days": {
            "window_start": since.isoformat(timespec="seconds"),
            "local_token_delta": codex_tokens_since(codex_home, since, days),
            "account_rate_limits": (latest_event or {}).get("rate_limits"),
        },
    }


def claude_auth_status() -> dict[str, Any] | None:
    try:
        proc = subprocess.run(
            ["claude", "auth", "status", "--json"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return {
        "loggedIn": data.get("loggedIn"),
        "authMethod": data.get("authMethod"),
        "apiProvider": data.get("apiProvider"),
        "subscriptionType": data.get("subscriptionType"),
    }


def latest_claude_session_id(claude_home: Path) -> tuple[str | None, str | None]:
    cached = read_claude_statusline_cache()
    if cached and cached.get("session_id"):
        return cached.get("session_id"), "statusline"

    projects = claude_home / "projects"
    if not projects.exists():
        return None, None
    latest_path: Path | None = None
    latest_mtime = -1.0
    uuid_pattern = re.compile(r"^[0-9a-fA-F-]{36}\.jsonl$")
    for path in projects.rglob("*.jsonl"):
        if not uuid_pattern.match(path.name):
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest_path = path
    return (latest_path.stem, "latest_log") if latest_path else (None, None)


def claude_usage_rows(claude_home: Path, since: dt.datetime | None, session_id: str | None = None):
    projects = claude_home / "projects"
    if not projects.exists():
        return []

    min_mtime = (since.timestamp() - 86400) if since else 0
    best_by_message: dict[str, dict[str, Any]] = {}

    for path in projects.rglob("*.jsonl"):
        try:
            if since is not None and path.stat().st_mtime < min_mtime:
                continue
        except OSError:
            continue
        for obj in read_jsonl(path):
            if obj.get("type") != "assistant":
                continue
            if session_id and obj.get("sessionId") != session_id:
                continue
            timestamp = parse_iso(obj.get("timestamp"))
            if since is not None and timestamp is not None and timestamp < since:
                continue
            message = obj.get("message") or {}
            usage = message.get("usage") or {}
            if not usage:
                continue
            key = message.get("id") or obj.get("requestId") or obj.get("uuid") or f"{path}:{obj.get('timestamp')}"
            components = {
                "input_tokens": int(usage.get("input_tokens") or 0),
                "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens") or 0),
                "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
            }
            total = sum(components.values())
            existing = best_by_message.get(key)
            if existing is None or total >= existing["total_tokens"]:
                best_by_message[key] = {
                    "timestamp": timestamp,
                    "session_id": obj.get("sessionId"),
                    "model": message.get("model"),
                    "total_tokens": total,
                    "components": components,
                    "path": str(path),
                }
    return list(best_by_message.values())


def sum_claude_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, int] = {}
    components = {
        "input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 0,
    }
    total = 0
    for row in rows:
        total += row["total_tokens"]
        by_model[row.get("model") or "unknown"] = by_model.get(row.get("model") or "unknown", 0) + row["total_tokens"]
        for key in components:
            components[key] += row["components"].get(key, 0)
    return {"total_tokens": total, "components": components, "by_model": by_model, "messages_counted": len(rows)}


def read_claude_statusline_cache() -> dict[str, Any] | None:
    try:
        data = json.loads(CLAUDE_STATUSLINE_CACHE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data


def claude_rate_limits_from_cache() -> dict[str, Any] | None:
    cached = read_claude_statusline_cache()
    if not cached:
        return None
    raw = cached.get("rate_limits")
    captured_at = parse_iso(cached.get("_captured_at"))
    normalized = normalize_rate_limits(raw, captured_at)
    if normalized:
        normalized["captured_at"] = cached.get("_captured_at")
    return normalized


def claude_report(days: int, session_id: str | None) -> dict[str, Any]:
    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")).expanduser()
    since = local_now() - dt.timedelta(days=7)
    env_session = os.environ.get("CLAUDE_SESSION_ID")
    if session_id:
        current_session_id = session_id
        session_source = "argument"
    elif env_session:
        current_session_id = env_session
        session_source = "environment"
    else:
        current_session_id, session_source = latest_claude_session_id(claude_home)
    weekly_rows = claude_usage_rows(claude_home, since)
    current_rows = claude_usage_rows(claude_home, None, current_session_id) if current_session_id else []
    rate_limits = claude_rate_limits_from_cache()

    return {
        "source": {
            "projects_dir": str(claude_home / "projects"),
            "statusline_cache": str(CLAUDE_STATUSLINE_CACHE),
        },
        "auth": claude_auth_status(),
        "current_session": {
            "session_id": current_session_id,
            "source": session_source,
            "usage": sum_claude_rows(current_rows),
        },
        "last_7_days": {
            "window_start": since.isoformat(timespec="seconds"),
            "usage": sum_claude_rows(weekly_rows),
            "rate_limits": rate_limits,
            "rate_limit_note": (
                "Enable claude_statusline_capture.py as Claude Code statusLine to capture "
                "five_hour and seven_day remaining percentages."
                if rate_limits is None
                else None
            ),
        },
    }


def print_rate_limits(title: str, rate_limits: dict[str, Any] | None) -> None:
    print(title)
    if not rate_limits:
        print("  no rate-limit payload captured")
        return
    for key, label in (("primary", "primary"), ("secondary", "secondary"), ("five_hour", "5h"), ("seven_day", "7d")):
        item = rate_limits.get(key)
        if not item:
            continue
        used = item.get("used_percent")
        remaining = item.get("remaining_percent")
        reset = item.get("resets_at_local")
        window = item.get("window_minutes")
        print(f"  {label}: used={used}% remaining={remaining}% window={window}m reset={reset}")
    if rate_limits.get("plan_type"):
        print(f"  plan_type: {rate_limits['plan_type']}")
    if rate_limits.get("captured_at"):
        print(f"  captured_at: {rate_limits['captured_at']}")


def print_human(report: dict[str, Any]) -> None:
    print("KDE widgets")
    for panel in report["kde"]["panels"]:
        print(f"  panel {panel['containment_id']} ({panel['location']})")
        for applet in panel["applets"]:
            detail = f" - {applet['details']}" if applet.get("details") else ""
            print(f"    {applet['id']}: {applet['name']} ({applet['plugin']}){detail}")
            for child in applet.get("contained_applets", []):
                print(f"      tray {child['id']}: {child['name']} ({child['plugin']})")

    codex = report["codex"]
    thread = codex.get("thread") or {}
    print("\nCodex")
    print(f"  current thread: {codex['current_session'].get('thread_id')}")
    print(f"  model: {thread.get('model')}")
    print(f"  current session tokens: {human_int(codex['current_session'].get('tokens'))}")
    print(f"  last 7d local token delta: {human_int(codex['last_7_days'].get('local_token_delta'))}")
    print_rate_limits("  current/account rate limits:", codex["current_session"].get("rate_limits") or codex["last_7_days"].get("account_rate_limits"))

    claude = report["claude"]
    print("\nClaude Code")
    auth = claude.get("auth") or {}
    print(f"  auth: {auth.get('authMethod')} / {auth.get('subscriptionType')}")
    source = claude["current_session"].get("source")
    label = "latest logged session" if source == "latest_log" else "current session"
    print(f"  {label}: {claude['current_session'].get('session_id')} ({source or 'unknown'})")
    print(f"  {label} tokens: {human_int(claude['current_session']['usage'].get('total_tokens'))}")
    print(f"  last 7d local tokens: {human_int(claude['last_7_days']['usage'].get('total_tokens'))}")
    print_rate_limits("  captured status-line rate limits:", claude["last_7_days"].get("rate_limits"))
    if claude["last_7_days"].get("rate_limit_note"):
        print(f"  note: {claude['last_7_days']['rate_limit_note']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Report KDE panel widgets and local Codex/Claude Code usage.")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--days-scan", type=int, default=14, help="days of recent Codex session files to scan")
    parser.add_argument("--claude-session", help="Claude Code session UUID to treat as current")
    args = parser.parse_args()

    report = {
        "generated_at": local_now().isoformat(timespec="seconds"),
        "kde": kde_widgets(),
        "codex": codex_report(args.days_scan),
        "claude": claude_report(args.days_scan, args.claude_session),
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
