#!/usr/bin/env python3
import collections, concurrent.futures, datetime as dt, fcntl, itertools, json, math, os, select, shutil, sqlite3, subprocess, sys, time
from pathlib import Path
from statistics import median
from urllib import error, parse, request
CACHE = Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "ai-usage"
CLAUDE_CACHE, HISTORY_CACHE, ERROR_CACHE, TOKEN_CACHE = (CACHE / name for name in ("claude-statusline.json", "usage-history.json", "error-history.json", "token-stats.json"))
PROVIDERS = ("claude", "codex", "kimi", "grok")
TOKEN_WINDOWS = (("lifetime", None), ("30d", 30 * 86400), ("7d", 7 * 86400), ("24h", 86400), ("1h", 3600))
COLORS = {"ok": "#27ae60", "near": "#fdbc4b", "under": "#3daee9"}
TARGET_USED, FULL_USED = 80.0, 99.5
NETWORK_ERRORS = (OSError, error.URLError, TimeoutError, json.JSONDecodeError)
OPENAI_PRICES = {
    "gpt-5.6-sol": (5.0, 0.5, 30.0), "gpt-5.6-terra": (2.5, 0.25, 15.0), "gpt-5.6-luna": (1.0, 0.1, 6.0),
    "gpt-5-codex": (1.25, 0.125, 10.0), "gpt-5.5": (10.0, 1.0, 45.0),
    "gpt-5.4-mini": (0.75, 0.075, 4.5), "gpt-5.3-codex": (1.75, 0.175, 14.0),
}
CLAUDE_PRICES = {
    **dict.fromkeys(("claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-opus-4-5"), (5.0, 6.25, 10.0, 0.5, 25.0)),
    "claude-opus-4-1": (15.0, 18.75, 30.0, 1.5, 75.0), "claude-opus-4": (15.0, 18.75, 30.0, 1.5, 75.0),
    "claude-fable-5": (10.0, 12.5, 20.0, 1.0, 50.0), "claude-sonnet-5": (2.0, 2.5, 4.0, 0.2, 10.0),
    "claude-sonnet-4-6": (3.0, 3.75, 6.0, 0.3, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 1.25, 2.0, 0.1, 5.0),
}
KIMI_PRICES = {"kimi-code/kimi-for-coding": (0.95, 0.19, 4.0), "kimi-k2.7-code": (0.95, 0.19, 4.0), "kimi-k2.7-code-highspeed": (1.9, 0.38, 8.0)}
KIMI_CLIENT_ID, KIMI_BASE_URL, KIMI_AUTH_HOST = "17e5f671-d194-4dfb-9706-5516cb48c098", "https://api.kimi.com/coding/v1", "https://auth.kimi.com"
GROK_BASE_URL = "https://cli-chat-proxy.grok.com/v1"
RESET_API = "https://codex-reset.com/api/"
def now(): return dt.datetime.now().astimezone()
def notice(provider, reason): return f"{now():%H:%M} - {provider}: {reason}"
def failure(provider, value):
    code, text = getattr(value, "code", None), str(value).lower()
    reason = "unauthorized (401)" if code == 401 or "401" in text else "forbidden (403)" if code == 403 or "403" in text else "usage lookup timed out" if isinstance(value, TimeoutError) or "timed out" in text else "network unavailable" if any(word in text for word in ("network", "connect", "resolve", "route", "dns")) else "usage lookup failed"
    return notice(provider, reason)
def number(value, integer=False):
    try: return int(value or 0) if integer else float(value)
    except (TypeError, ValueError): return 0 if integer else None
def load(path):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {}
def save(path, data, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700 if mode else 0o777)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    if mode: os.chmod(tmp, mode)
    tmp.replace(path)
def moment(value):
    stamp = number(value)
    try:
        if stamp is not None:
            stamp = stamp / 1000 if stamp > 10**12 else stamp
            return dt.datetime.fromtimestamp(stamp, dt.timezone.utc).astimezone()
        if isinstance(value, str): return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone()
    except (OSError, OverflowError, ValueError): pass
    return None
def http(url, headers=None, body=None, timeout=8):
    req = request.Request(url, data=body, headers=headers or {})
    with request.urlopen(req, timeout=timeout) as response:
        value = json.loads(response.read().decode())
    return value if isinstance(value, dict) else {}
def duration(seconds):
    minutes = max(1, math.ceil(seconds / 60))
    if minutes < 90: return f"{minutes}m"
    hours = (minutes + 30) // 60
    if hours < 36: return f"{hours}h"
    days, extra = divmod(hours, 24)
    return f"{days}d {extra}h" if extra and days < 3 else f"{days}d"
def reset_fields(epoch):
    reset = moment(epoch)
    if not reset: return {"reset": None, "reset_label": "--", "days": "?"}
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
    return {"reset": reset.timestamp(), "reset_label": f"Resets {label}", "days": str(seconds // 86400)}
def quota_health(used, reset, minutes):
    if used is None: return {"pace": "--", "color": ""}
    projected = raw_projected = early = None
    if reset is not None and minutes:
        left = max(0.0, reset - now().timestamp())
        window = minutes * 60
        elapsed = max(0.0, 1.0 - min(1.0, left / window))
        raw_projected = used if elapsed <= 0 else used / elapsed
        projected = min(100.0, raw_projected)
        if raw_projected > 100 and used > 0: early = left if used >= 100 else left - (100 - used) * window * elapsed / used
    if raw_projected is None:
        pace = "Forecast pending"
    elif early is not None and early > 0:
        pace = f"Limit {duration(early)} early"
    else:
        pace = f"Expected {round(projected if projected is not None else used)}%"
    if early is not None and early > 0:
        state = "near"
    elif raw_projected is not None:
        state = "ok" if raw_projected >= TARGET_USED else "near" if raw_projected >= TARGET_USED * 0.8 else "under"
    else:
        state = "ok" if used >= TARGET_USED else "near" if used >= TARGET_USED * 0.8 else "under"
    return {"pace": pace, "color": COLORS[state]}
def quota(raw=None, minutes=None, captured=None):
    if not isinstance(raw, dict): raw = {}
    used = next((number(raw.get(key)) for key in ("used_percent", "used_percentage", "usedPercent") if raw.get(key) is not None), None)
    limit, absolute = number(raw.get("limit")), number(raw.get("used"))
    remaining = number(raw.get("remaining"))
    if absolute is None and limit is not None and remaining is not None: absolute = limit - remaining
    if used is None and absolute is not None and limit: used = absolute * 100 / limit
    used = None if used is None else min(100.0, max(0.0, used))
    reset = next((raw.get(key) for key in ("resets_at", "resetsAt", "reset_at", "resetAt", "reset_time", "resetTime") if raw.get(key) is not None), None)
    reset = moment(reset)
    if not reset:
        relative = next((number(raw.get(key)) for key in ("resets_in_seconds", "reset_in", "resetIn", "ttl") if raw.get(key) is not None), None)
        if relative is not None: reset = (captured or now()) + dt.timedelta(seconds=relative)
    if minutes is None: minutes = number(raw.get("window_minutes", raw.get("windowDurationMins")), True) or None
    epoch = reset.timestamp() if reset else None
    return {"used": used, **reset_fields(epoch), **quota_health(used, epoch, minutes)}
def window_minutes(raw):
    if not isinstance(raw, dict): return None
    window = raw.get("window") if isinstance(raw.get("window"), dict) else raw
    value = number(window.get("duration"))
    unit = str(window.get("timeUnit", "")).upper()
    if value is None: return None
    if "MINUTE" in unit: return round(value)
    if "HOUR" in unit: return round(value * 60)
    if "DAY" in unit: return round(value * 1440)
    return round(value / 60 if value > 1000 else value)
def blank_provider(extra=None):
    data = {"available": False, "current": quota(), "weekly": quota()}
    if extra:
        data.update(extra)
    return data
def kimi_home(): return Path(os.environ.get("KIMI_CODE_HOME", "~/.kimi-code")).expanduser()
def kimi_headers(home):
    version = "0.27.0"
    for path in (home / "updates/latest.json", home / "updates/install.json"):
        data = load(path)
        version = data.get("latest") or data.get("version") or version
    headers = {"X-Msh-Platform": "kimi_code_cli", "X-Msh-Version": version}
    try:
        device = (home / "device_id").read_text().strip()
        if device: headers["X-Msh-Device-Id"] = device
    except OSError: pass
    return headers
def kimi_token(home, refresh=False):
    path = home / "credentials/kimi-code.json"
    credentials = load(path)
    token = credentials.get("access_token")
    expires = number(credentials.get("expires_at"))
    expires = expires / 1000 if expires and expires > 10**12 else expires
    if not refresh and token and (expires is None or expires - now().timestamp() > 60): return token
    refresh_token = credentials.get("refresh_token")
    if not refresh_token: return token
    body = parse.urlencode({"client_id": KIMI_CLIENT_ID, "grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
    try:
        payload = http(
            os.environ.get("KIMI_CODE_OAUTH_HOST", os.environ.get("KIMI_OAUTH_HOST", KIMI_AUTH_HOST)).rstrip("/") + "/api/oauth/token",
            {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded", **kimi_headers(home)}, body,
        )
    except NETWORK_ERRORS: return token
    token = payload.get("access_token")
    if not token: return None
    credentials.update(payload)
    if number(payload.get("expires_in")): credentials["expires_at"] = int(now().timestamp() + number(payload["expires_in"]))
    save(path, credentials, 0o600)
    return token
def kimi():
    home = kimi_home()
    try: token = kimi_token(home)
    except NETWORK_ERRORS: return blank_provider()
    if not token: return blank_provider()
    url = os.environ.get("KIMI_CODE_BASE_URL", KIMI_BASE_URL).rstrip("/") + "/usages"
    try:
        try:
            payload = http(url, {"Authorization": f"Bearer {token}", "Accept": "application/json"})
        except error.HTTPError as exc:
            if exc.code != 401 or not (token := kimi_token(home, True)):
                raise
            payload = http(url, {"Authorization": f"Bearer {token}", "Accept": "application/json"})
    except NETWORK_ERRORS: return blank_provider()
    weekly = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
    limits = payload.get("limits") if isinstance(payload.get("limits"), list) else []
    item = next((item for item in limits if window_minutes(item) == 300), None)
    current = item.get("detail") if isinstance(item, dict) and isinstance(item.get("detail"), dict) else item
    return {"available": bool(current or weekly), "current": quota(current, window_minutes(item) or 300), "weekly": quota(weekly, 10080)}
def grok_home(): return Path(os.environ.get("GROK_HOME", "~/.grok")).expanduser()
def grok_credentials(auth):
    return next(((scope, value) for scope, value in auth.items() if isinstance(value, dict) and (value.get("key") or value.get("refresh_token"))), (None, {}))
def grok_token(home, refresh=False):
    path = home / "auth.json"
    auth = load(path); scope, credentials = grok_credentials(auth)
    token, expires = credentials.get("key"), moment(credentials.get("expires_at"))
    if not refresh and token and (not expires or (expires - now()).total_seconds() > 60): return token
    if not scope or not credentials.get("refresh_token") or not credentials.get("oidc_client_id"): return token
    with Path(str(path) + ".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        auth = load(path); scope, credentials = grok_credentials(auth)
        token, expires = credentials.get("key"), moment(credentials.get("expires_at"))
        if not refresh and token and (not expires or (expires - now()).total_seconds() > 60): return token
        if not scope or not credentials.get("refresh_token") or not credentials.get("oidc_client_id"): return token
        body = parse.urlencode({"client_id": credentials["oidc_client_id"], "grant_type": "refresh_token", "refresh_token": credentials["refresh_token"]}).encode()
        payload = http(credentials.get("oidc_issuer", "https://auth.x.ai").rstrip("/") + "/oauth2/token", {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}, body)
        token = payload.get("access_token")
        if not token: return None
        credentials.update({"key": token, "refresh_token": payload.get("refresh_token", credentials["refresh_token"])})
        if number(payload.get("expires_in")): credentials["expires_at"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=number(payload["expires_in"]))).isoformat().replace("+00:00", "Z")
        auth[scope] = credentials; save(path, auth, 0o600)
    return token
def grok():
    home = grok_home()
    try:
        token = grok_token(home)
        if not token: return blank_provider({"error": notice("Grok", "sign in required")})
        url = os.environ.get("CLI_CHAT_PROXY_BASE_URL", GROK_BASE_URL).rstrip("/") + "/billing?format=credits"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "x-grok-client-mode": "interactive"}
        try: payload = http(url, headers)
        except error.HTTPError as exc:
            if exc.code != 401 or not (token := grok_token(home, True)): raise
            headers["Authorization"] = f"Bearer {token}"; payload = http(url, headers)
    except NETWORK_ERRORS as exc: return blank_provider({"error": failure("Grok", exc)})
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    period = config.get("currentPeriod") if isinstance(config.get("currentPeriod"), dict) else {}
    reset = period.get("end") or config.get("billingPeriodEnd")
    data = {"available": bool(reset), "current": quota(), "weekly": quota({"used_percent": config.get("creditUsagePercent", 0), "resets_at": reset}, 10080)}
    if not reset: data["error"] = notice("Grok", "usage data missing")
    return data
def rpc(process, payload, timeout=5):
    if not process.stdin or not process.stdout: return None
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and select.select([process.stdout], [], [], deadline - time.monotonic())[0]:
        line = process.stdout.readline()
        if not line: break
        try:
            response = json.loads(line)
        except json.JSONDecodeError: continue
        if response.get("id") == payload.get("id"):
            if response.get("error"): raise RuntimeError(json.dumps(response["error"]))
            result = response.get("result")
            return result if isinstance(result, dict) else None
    raise TimeoutError(f"{payload.get('method', 'request')} timed out after {timeout}s")
def short_time(value):
    value, ref = moment(value), now()
    if not value: return ""
    delta = (value.date() - ref.date()).days
    if delta == 0: return "today " + value.strftime("%H:%M")
    if delta == 1: return "tomorrow " + value.strftime("%H:%M")
    if delta == -1: return "yesterday " + value.strftime("%H:%M")
    return value.strftime("%a %H:%M") if abs(delta) < 7 else value.strftime("%b %-d %H:%M")
def reset_info():
    headers = {"Accept": "application/json", "User-Agent": "KDE-AI-Usage-Widget/1"}
    result = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        timeline = pool.submit(http, RESET_API + "timeline?group=reset", headers, None, 3)
        prediction = pool.submit(http, RESET_API + "forecast", headers, None, 3)
    try:
        events = timeline.result().get("events", [])
        events = events if isinstance(events, list) else []
        labels = [short_time(item.get("announced_at")) for item in events if isinstance(item, dict)][:3]
        if labels: result["past"] = " | ".join(filter(None, labels))
    except NETWORK_ERRORS: pass
    try:
        forecast = prediction.result()
        updated = moment(forecast.get("updated_at"))
        if not updated or abs((now() - updated).total_seconds()) > 7200: return result
        signal = forecast.get("official_signal")
        if signal:
            window = signal.get("official_window", signal.get("window", {})) if isinstance(signal, dict) else {}
            label = window.get("label") if isinstance(window, dict) else None
            result["next"] = str(label).capitalize() + " (announced)" if label else "Announced"
        else:
            odds = forecast.get("probabilities", {})
            day, two_days = number(odds.get("rounded_24h")), number(odds.get("rounded_48h"))
            if day is not None and two_days is not None: result["next"] = f"24h ~{round(day)}%, 48h ~{round(two_days)}%"
    except NETWORK_ERRORS: pass
    return result
def banked(payload):
    if not isinstance(payload, dict): return ""
    raw_credits = payload.get("credits")
    credits = [item for item in raw_credits if isinstance(item, dict) and item.get("status") == "available"] if isinstance(raw_credits, list) else []
    count = number(payload.get("availableCount"))
    count = round(count) if count is not None else len(credits)
    expiries = sorted(value for item in credits if (value := number(item.get("expiresAt"))) and value > now().timestamp())
    return f"{count} | {'expires' if count == 1 else 'next expiry'} {short_time(expiries[0])}" if expiries else str(count)
def codex_usage():
    binary = os.environ.get("CODEX_BIN") or shutil.which("codex") or str(Path.home() / ".local/bin/codex")
    process = None
    try:
        process = subprocess.Popen([binary, "app-server", "--stdio"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        initialized = rpc(process, {"method": "initialize", "id": 1, "params": {"clientInfo": {"name": "kde_ai_usage", "title": "KDE AI Usage", "version": "1"}}})
        if initialized is None or not process.stdin: return blank_provider({"error": notice("Codex", "app server unavailable")})
        process.stdin.write('{"method":"initialized"}\n')
        process.stdin.flush()
        result = rpc(process, {"method": "account/rateLimits/read", "id": 2}, timeout=10) or {}
        limits = result.get("rateLimits") if isinstance(result.get("rateLimits"), dict) else {}
        credit = banked(result.get("rateLimitResetCredits"))
        windows = {round(number(item.get("windowDurationMins", item.get("window_minutes"))) or 0): item for item in limits.values() if isinstance(item, dict)}
        data = {"available": bool(limits), "current": quota(windows.get(300), 300), "weekly": quota(windows.get(10080), 10080)}
        if credit: data["_banked"] = credit
        if 10080 not in windows: data["error"] = notice("Codex", "usage data missing" if not limits else "weekly window missing")
        return data
    except TimeoutError as exc: return blank_provider({"error": notice("Codex", str(exc))})
    except (BrokenPipeError, OSError, subprocess.SubprocessError, RuntimeError) as exc: return blank_provider({"error": failure("Codex", exc)})
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired: process.kill()
def codex():
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        usage, resets = pool.submit(codex_usage), pool.submit(reset_info)
        data, resets = usage.result(), resets.result()
    credit = data.pop("_banked", "")
    if credit: resets["banked"] = credit
    data["global_resets"] = resets
    return data
def select_claude_window(items, minutes, captured):
    valid = []
    for item in items:
        if not isinstance(item, dict): continue
        reset = number(item.get("resets_at"))
        used = number(item.get("used_percent", item.get("used_percentage")))
        if reset is not None and used is not None and captured < reset <= captured + minutes * 60 + 300: valid.append((reset, used, item))
    return max(valid, default=(None, None, None), key=lambda value: value[:2])[2]
def claude(history):
    cached = load(CLAUDE_CACHE)
    limits = cached.get("rate_limits") if isinstance(cached.get("rate_limits"), dict) else {}
    limits = dict(limits)
    samples, captured = history.get("claude", []), now().timestamp()
    samples = samples if isinstance(samples, list) else []
    for source, target, minutes in (("five_hour", "current", 300), ("seven_day", "weekly", 10080)):
        old = ({"resets_at": item.get(f"{target}_reset"), "used_percentage": item.get(f"{target}_used")} for item in samples if isinstance(item, dict))
        limits[source] = select_claude_window([limits.get(source), *old], minutes, captured)
    captured_at = moment(cached.get("_captured_at"))
    data = {
        "available": any(isinstance(limits.get(key), dict) for key in ("five_hour", "seven_day")),
        "current": quota(limits.get("five_hour"), 300, captured_at),
        "weekly": quota(limits.get("seven_day"), 10080, captured_at),
    }
    missing = [label for key, label in (("five_hour", "5h"), ("seven_day", "weekly")) if not isinstance(limits.get(key), dict)]
    if missing: data["error"] = notice("Claude", f"{' and '.join(missing)} window missing from status line")
    return data
def conversion_ratio(items):
    ratios = []
    key = lambda item: (item.get("current_reset"), item.get("weekly_reset"))
    for _, run in itertools.groupby((item for item in items if isinstance(item, dict)), key):
        run = list(run)
        current = number(run[-1].get("current_used")) - number(run[0].get("current_used"))
        weekly = number(run[-1].get("weekly_used")) - number(run[0].get("weekly_used"))
        if current >= 4 and 0 < weekly <= current: ratios.append(weekly / current)
    return median(ratios[-20:]) if ratios else None
def update_history(data, history):
    for name in PROVIDERS:
        if name not in data: continue
        provider = data[name]
        values = {
            "current_used": number(provider["current"].get("used")), "current_reset": number(provider["current"].get("reset")),
            "weekly_used": number(provider["weekly"].get("used")), "weekly_reset": number(provider["weekly"].get("reset")),
        }
        items = history.get(name) if isinstance(history.get(name), list) else []
        if all(value is not None for value in values.values()) and (not items or values != items[-1]):
            items = (items + [values])[-300:]
            history[name] = items
        ratio, current, weekly = conversion_ratio(items), provider["current"], provider["weekly"]
        current_used, current_reset, weekly_used, weekly_reset = map(number, (current.get("used"), current.get("reset"), weekly.get("used"), weekly.get("reset")))
        if None in (ratio, current_used, current_reset, weekly_used, weekly_reset) or current_reset <= now().timestamp() or weekly_reset <= now().timestamp():
            continue
        capacity = 100 - current_used
        if current_reset < weekly_reset: capacity += math.ceil((weekly_reset - current_reset) / 18000) * 100
        reachable = min(100.0, weekly_used + capacity * ratio)
        if reachable < FULL_USED: weekly.update(pace=f"Behind: max {round(reachable)}%", color=COLORS["under"])
    try:
        save(HISTORY_CACHE, history)
    except OSError: pass
def jsonl(path):
    try:
        with path.open(encoding="utf-8", errors="replace") as lines:
            for line in lines:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError: pass
    except OSError: return
def token_windows(): return {key: collections.defaultdict(collections.Counter) for key, _ in TOKEN_WINDOWS}
def add_tokens(windows, when, model, values):
    if not when: return
    age = (now() - when).total_seconds()
    for key, seconds in TOKEN_WINDOWS:
        if seconds is None or age <= seconds: windows[key][model].update(values)
def codex_tokens():
    home, windows = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser(), token_windows()
    models, db = {}, home / "state_5.sqlite"
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
            models = {str(Path(path)): model or "unknown" for path, model in connection.execute("select rollout_path, model from threads") if path}
    except sqlite3.Error: pass
    for path in (home / "sessions").rglob("*.jsonl") if (home / "sessions").exists() else []:
        model, previous = models.get(str(path), "unknown"), collections.Counter()
        for item in jsonl(path):
            payload = item.get("payload") or {}
            mode = ((payload.get("collaboration_mode") or {}).get("settings", {}) or {}) if isinstance(payload.get("collaboration_mode"), dict) else {}
            candidate = payload.get("model") if isinstance(payload.get("model"), str) else mode.get("model")
            if isinstance(candidate, str): model = candidate
            if item.get("type") != "event_msg" or payload.get("type") != "token_count": continue
            total = ((payload.get("info") or {}).get("total_token_usage") or {})
            if not total: continue
            current = collections.Counter({key: number(total.get(key), True) for key in ("input_tokens", "cached_input_tokens", "output_tokens", "total_tokens")})
            delta, previous = current - previous, current
            add_tokens(windows, moment(item.get("timestamp")), model, {"input": delta["input_tokens"], "cached": delta["cached_input_tokens"], "output": delta["output_tokens"], "tokens": delta["total_tokens"]})
    return windows
def claude_tokens():
    root, windows, seen = Path(os.environ.get("CLAUDE_HOME", "~/.claude")).expanduser() / "projects", token_windows(), set()
    for path in root.rglob("*.jsonl") if root.exists() else []:
        for item in jsonl(path):
            message = item.get("message") or {}
            usage = message.get("usage") or {}
            event_id = message.get("id") or item.get("requestId") or item.get("uuid") or (str(path), item.get("timestamp"))
            if item.get("type") != "assistant" or not isinstance(usage, dict) or event_id in seen: continue
            seen.add(event_id)
            creation = usage.get("cache_creation") or {}
            write5, write1h = number(creation.get("ephemeral_5m_input_tokens"), True), number(creation.get("ephemeral_1h_input_tokens"), True)
            values = {"input": number(usage.get("input_tokens"), True), "write5": write5, "write1h": write1h, "read": number(usage.get("cache_read_input_tokens"), True), "output": number(usage.get("output_tokens"), True)}
            values["write_unknown"] = max(0, number(usage.get("cache_creation_input_tokens"), True) - write5 - write1h)
            values["tokens"] = sum(values.values())
            add_tokens(windows, moment(item.get("timestamp")), message.get("model") or "unknown", values)
    return windows
def kimi_tokens():
    root, windows = kimi_home() / "sessions", token_windows()
    for path in root.rglob("wire.jsonl") if root.exists() else []:
        for item in jsonl(path):
            usage = item.get("usage") or {}
            if item.get("type") != "usage.record" or item.get("usageScope") != "turn" or not isinstance(usage, dict): continue
            values = {"input": number(usage.get("inputOther"), True) + number(usage.get("inputCacheCreation"), True), "cached": number(usage.get("inputCacheRead"), True), "output": number(usage.get("output"), True)}
            values["tokens"] = sum(values.values())
            add_tokens(windows, moment(item.get("time")), item.get("model") or "unknown", values)
    return windows
def model_cost(provider, model, values):
    rates = {"codex": OPENAI_PRICES, "claude": CLAUDE_PRICES, "kimi": KIMI_PRICES}[provider].get(model)
    if not rates: return None
    if provider == "claude":
        usage = (values["input"], values["write5"] + values["write_unknown"], values["write1h"], values["read"], values["output"])
    elif provider == "codex":
        usage = (max(0, values["input"] - values["cached"]), values["cached"], values["output"])
    else:
        usage = (values["input"], values["cached"], values["output"])
    return sum(tokens * rate for tokens, rate in zip(usage, rates)) / 1_000_000
def compact(value):
    if value >= 1_000_000_000: return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000: return f"{value / 1_000_000:.1f}M"
    if value >= 1_000: return f"{value / 1_000:.1f}K"
    return str(value)
def money(value): return f"${value:,.0f}"
def error_history(data):
    stored = load(ERROR_CACHE); items, active = stored.get("items", []), stored.get("active", {})
    items = items if isinstance(items, list) else []; active = active if isinstance(active, dict) else {}
    current = {name: data[name].get("error", "") for name in PROVIDERS if name in data}
    for name, text in current.items():
        if text and active.get(name) != text.split(" - ", 1)[-1]: items.append(text)
    try: save(ERROR_CACHE, {"items": items[-20:], "active": {name: text.split(" - ", 1)[-1] for name, text in current.items() if text}})
    except OSError: pass
    return list(reversed(items[-3:]))
def scan_token_usage():
    providers = {"codex": codex_tokens(), "claude": claude_tokens(), "kimi": kimi_tokens()}
    return {provider: {key: {model: dict(values) for model, values in windows[key].items()} for key, _ in TOKEN_WINDOWS} for provider, windows in providers.items()}
def summarize_tokens(providers):
    rows, unpriced = [], set()
    for key, _ in TOKEN_WINDOWS:
        row = {"key": key, "providers": {}}
        for provider, windows in providers.items():
            total, cost, models = 0, 0.0, []
            for model, values in windows[key].items():
                total += values["tokens"]
                estimate = model_cost(provider, model, values)
                if estimate is None and values["tokens"] > 0: unpriced.add(model)
                elif estimate is not None:
                    cost += estimate
                    if values["tokens"] > 0: models.append((model, estimate))
            models.sort(key=lambda item: (-item[1], item[0]))
            row["providers"][provider] = {"tokens": compact(total), "cost": money(cost), "models": [{"name": model, "cost": money(estimate)} for model, estimate in models]}
        rows.append(row)
    note = "Unpriced models excluded from cost: " + ", ".join(sorted(unpriced)) if unpriced else ""
    return {"windows": rows, "note": note}
def refresh_tokens():
    CACHE.mkdir(parents=True, exist_ok=True)
    with (CACHE / "token-stats.lock").open("w") as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return 0
        save(TOKEN_CACHE, scan_token_usage())
    return 0
def token_stats():
    data = load(TOKEN_CACHE)
    if all(isinstance(data.get(provider), dict) for provider in ("codex", "claude", "kimi")):
        if time.time() - TOKEN_CACHE.stat().st_mtime > 600:
            subprocess.Popen([sys.executable, __file__, "--refresh-tokens"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    else:
        data = scan_token_usage(); save(TOKEN_CACHE, data)
    return summarize_tokens(data)
def selected_providers():
    value = next((arg.partition("=")[2] for arg in sys.argv if arg.startswith("--providers=")), "")
    selected = tuple(name for name in value.split(",") if name in PROVIDERS)
    return selected or PROVIDERS
def snapshot():
    history = load(HISTORY_CACHE)
    jobs = {"claude": lambda: claude(history), "codex": codex, "kimi": kimi, "grok": grok}
    selected = selected_providers()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(selected)) as pool:
        futures = {name: pool.submit(jobs[name]) for name in selected}
        data = {name: future.result() for name, future in futures.items()}
    data["tokens"] = token_stats()
    data["errors"] = error_history(data)
    update_history(data, history)
    print(json.dumps(data, separators=(",", ":")))
    return 0
def capture_claude():
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError: return 0
    captured = dt.datetime.now(dt.timezone.utc)
    data["_captured_at"] = captured.isoformat(timespec="seconds").replace("+00:00", "Z")
    CACHE.mkdir(parents=True, exist_ok=True)
    with (CACHE / "claude-statusline.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        old = load(CLAUDE_CACHE).get("rate_limits", {})
        new = data.get("rate_limits", {})
        old = old if isinstance(old, dict) else {}
        new = new if isinstance(new, dict) else {}
        merged = {**old, **new}
        for name, minutes in (("five_hour", 300), ("seven_day", 10080)):
            selected = select_claude_window((old.get(name), new.get(name)), minutes, captured.timestamp())
            if selected: merged[name] = selected
            else: merged.pop(name, None)
        data["rate_limits"] = merged
        save(CLAUDE_CACHE, data)
    model = (data.get("model") or {}).get("display_name") or (data.get("model") or {}).get("id") or "Claude"
    limits = data.get("rate_limits") or {}
    print(f"{model} | 5h used {(limits.get('five_hour') or {}).get('used_percentage', '--')}% | 7d used {(limits.get('seven_day') or {}).get('used_percentage', '--')}%")
    return 0
if __name__ == "__main__":
    raise SystemExit(refresh_tokens() if "--refresh-tokens" in sys.argv else capture_claude() if "--capture-claude-statusline" in sys.argv else snapshot())
