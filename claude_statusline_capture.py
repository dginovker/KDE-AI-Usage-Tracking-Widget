#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path


CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "ai-usage"
CACHE_PATH = CACHE_DIR / "claude-statusline.json"


def pct(data: dict, path: tuple[str, ...]) -> str:
    cur = data
    for key in path:
        value = cur.get(key) if isinstance(cur, dict) else None
        if value is None:
            return "--"
        cur = value
    return str(cur)


def main() -> int:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return 0

    data["_captured_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(CACHE_PATH)

    model = (data.get("model") or {}).get("display_name") or (data.get("model") or {}).get("id") or "Claude"
    ctx = pct(data, ("context_window", "used_percentage"))
    five = pct(data, ("rate_limits", "five_hour", "used_percentage"))
    seven = pct(data, ("rate_limits", "seven_day", "used_percentage"))
    print(f"{model} | ctx {ctx}% | 5h {five}% | 7d {seven}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
