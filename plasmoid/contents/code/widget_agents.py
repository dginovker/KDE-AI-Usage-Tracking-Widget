#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shlex
import sys
import time
from urllib.request import ProxyHandler, build_opener


PI_DASHBOARD_SESSIONS = "http://127.0.0.1:8040/api/sessions"


def pi_sessions(proc=Path("/proc")):
    # The dashboard observes Pi lifecycle directly; an Intercom disconnect is not an idle agent.
    with build_opener(ProxyHandler({})).open(PI_DASHBOARD_SESSIONS, timeout=3) as response:
        payload = json.load(response)
    if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("data"), list):
        raise ValueError("Invalid Pi dashboard sessions response")
    result = []
    for session in payload["data"]:
        if not isinstance(session, dict):
            raise ValueError("Invalid Pi dashboard session record")
        pid = session.get("pid")
        if session.get("status") == "ended" or type(pid) is not int or not konsole_agent(pid, proc):
            continue
        if (proc / str(pid) / "comm").read_text().strip() != "pi":
            continue
        status = session["status"]
        if status not in ("active", "idle", "streaming"):
            raise ValueError(f"Unknown Pi dashboard status for PID {pid}: {status!r}")
        if session.get("dataUnavailable") is not False:
            raise ValueError(f"Pi dashboard live data unavailable for PID {pid}")
        compacting = session.get("compacting", False)
        if type(compacting) is not bool:
            raise ValueError(f"Invalid Pi compaction state for PID {pid}")
        question = session.get("currentTool") in ("ask_user", "ask_user_question")
        working = compacting or (status == "streaming" and not question)
        result.append({"pid": pid, "id": session["id"], "status": "working" if working else "idle"})
    return result


PROVIDERS = ("pi", "claude", "codex")
CODEX_EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PermissionRequest", "Stop", "Interrupt", "SessionEnd")


def process_environment(process):
    return dict(entry.split("=", 1) for entry in (process / "environ").read_text().split("\0") if "=" in entry)


def codex_state_dir():
    return Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "ai-usage/agents/codex"


def konsole_agent(pid, proc=Path("/proc")):
    try:
        process = proc / str(pid)
        provider = (process / "comm").read_text().strip()
        if provider not in PROVIDERS:
            return False
        stat = (process / "stat").read_text().rsplit(")", 1)[1].split()
        if int(stat[4]) == 0 or stat[0] in ("Z", "X"):
            return False
        if not os.readlink(process / "fd/0").startswith("/dev/pts/"):
            return False
        args = (process / "cmdline").read_bytes().split(b"\0")
        headless = (b"--print", b"-p", b"--mode", b"--no-input", b"--agent-id") if provider != "codex" else (b"exec", b"e", b"review", b"app-server", b"agents")
        if any(arg in headless for arg in args):
            return False
        env = (process / "environ").read_bytes().split(b"\0")
        if any(entry.startswith((b"PI_SUBAGENT_RUN_ID=", b"PI_SUBAGENT_CHILD_AGENT=")) for entry in env):
            return False
        seen = set()
        while pid > 1 and pid not in seen:
            seen.add(pid)
            process = proc / str(pid)
            command = (process / "comm").read_text().strip()
            if command == "konsole":
                return True
            # A terminal inherited from a parent agent does not make a worker a main agent.
            if len(seen) > 1 and command in PROVIDERS:
                return False
            pid = int((process / "stat").read_text().rsplit(")", 1)[1].split()[1])
        return False
    except (FileNotFoundError, ProcessLookupError):
        return False


def count_agents(sessions, proc=Path("/proc")):
    working = idle = 0
    seen = set()
    for session in sessions:
        pid = session["pid"]
        if pid in seen or not konsole_agent(pid, proc):
            continue
        if "procStart" in session and str(session["procStart"]) != (proc / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19]:
            continue
        seen.add(pid)
        status = session.get("status", "").split(" · ", 1)[0]
        if status in ("idle", "waiting", "tool:ask_user", "tool:ask_user_question"):
            idle += 1
        elif status in ("thinking", "busy", "working", "shell") or status.startswith("tool:"):
            working += 1
        else:
            raise ValueError(f"Unknown agent status for {session['id']}: {status!r}")
    return {"working": working, "idle": idle}


def native_sessions(directory, provider, proc=Path("/proc")):
    result = []
    for path in directory.glob("*.json"):
        # Dead/headless presence files cannot poison counts with stale or malformed state.
        try:
            pid = int(path.stem)
            if not konsole_agent(pid, proc):
                continue
            session = json.loads(path.read_text())
        except (FileNotFoundError, ProcessLookupError):
            continue
        if session["pid"] != pid:
            raise ValueError(f"Presence PID mismatch in {path}")
        if provider == "claude" and session["kind"] != "interactive":
            continue
        if str(session["procStart"]) != (proc / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19]:
            continue
        result.append({**session, "id": session["sessionId"]})
    return result


def snapshot(proc=Path("/proc")):
    try:
        candidates = {int(path.name): (path / "comm").read_text().strip()
                      for path in proc.glob("[0-9]*") if konsole_agent(int(path.name), proc)}
        sessions = pi_sessions(proc) if "pi" in candidates.values() else []
        if "claude" in candidates.values():
            home = Path(os.environ.get("CLAUDE_CONFIG_DIR", "~/.claude")).expanduser()
            sessions += native_sessions(home / "sessions", "claude", proc)
        if "codex" in candidates.values():
            sessions += native_sessions(codex_state_dir(), "codex", proc)
        live = [session for session in sessions if session["pid"] in candidates]
        errors = []
        for pid, provider in candidates.items():
            if not any(session["pid"] == pid for session in live):
                detail = {"codex": "approve the AI Usage hook in /hooks and restart the session",
                          "pi": f"live presence missing from Pi dashboard at {PI_DASHBOARD_SESSIONS}",
                          "claude": "live presence missing"}[provider]
                errors.append(f"{provider} PID {pid}: {detail}")
        counts = count_agents(live, proc)
        if errors: counts["error"] = "Agent counts incomplete: " + "; ".join(errors)
        return counts
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, IndexError) as exc:
        return {"error": f"Agent counts unavailable: {exc}"}


def codex_hook(event, proc=Path("/proc"), pid=None):
    pid = os.getppid() if pid is None else pid
    while pid > 1:
        process = proc / str(pid)
        stat = (process / "stat").read_text().rsplit(")", 1)[1].split()
        if (process / "comm").read_text().strip() == "codex":
            break
        pid = int(stat[1])
    else:
        raise RuntimeError("Codex hook has no Codex ancestor")
    if not konsole_agent(pid, proc):
        return
    name = event["hook_event_name"]
    if name not in CODEX_EVENTS:
        raise ValueError(f"Unsupported Codex hook event: {name}")
    directory = codex_state_dir()
    path = directory / f"{pid}.json"
    if name == "SessionEnd":
        path.unlink(missing_ok=True)
        return
    question = name == "PreToolUse" and event.get("tool_name") in ("AskUserQuestion", "request_user_input")
    status = "idle" if question or name in ("SessionStart", "PermissionRequest", "Stop", "Interrupt") else "working"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    state = {"pid": pid, "procStart": stat[19], "sessionId": event["session_id"], "status": status, "event": name}
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state))
    temporary.chmod(0o600)
    temporary.replace(path)


def install_codex_hooks():
    home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    path = home / "hooks.json"
    config = json.loads(path.read_text()) if path.exists() else {}
    hooks = config.setdefault("hooks", {})
    command = "python3 " + shlex.quote(str(Path(__file__).resolve())) + " --codex-hook"
    changed = False
    for event in CODEX_EVENTS:
        groups = hooks.setdefault(event, [])
        if any(handler.get("command") == command for group in groups for handler in group["hooks"]):
            continue
        groups.append({"hooks": [{"type": "command", "command": command, "timeout": 3}]})
        changed = True
    if changed:
        home.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup = home / f"hooks.json.ai-usage-{time.time_ns()}.bak"
            backup.write_bytes(path.read_bytes())
            backup.chmod(0o600)
        temporary = path.with_suffix(".ai-usage.tmp")
        temporary.write_text(json.dumps(config, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.replace(path)
    print("AI Usage Codex hooks installed. Review and approve them in Codex /hooks, then restart existing Codex sessions.")


if __name__ == "__main__":
    if "--install-codex-hooks" in sys.argv:
        install_codex_hooks()
    elif "--codex-hook" in sys.argv:
        codex_hook(json.load(sys.stdin))
    else:
        result = snapshot()
        print(json.dumps(result, separators=(",", ":")))
        if "error" in result:
            print(result["error"], file=sys.stderr)
            sys.exit(1)
