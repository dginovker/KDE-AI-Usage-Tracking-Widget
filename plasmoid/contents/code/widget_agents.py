#!/usr/bin/env python3
import json
import os
from pathlib import Path
import socket
import sys
import time


def intercom_sessions():
    agent_dir = Path(os.environ.get("PI_CODING_AGENT_DIR", "~/.pi/agent")).expanduser()
    deadline = time.monotonic() + 3
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(3)
        connection.connect(str(agent_dir / "intercom/broker.sock"))

        def send(message):
            payload = json.dumps(message).encode()
            connection.sendall(len(payload).to_bytes(4, "big") + payload)

        def receive():
            def exact(size):
                data = bytearray()
                while len(data) < size:
                    connection.settimeout(max(0.001, deadline - time.monotonic()))
                    chunk = connection.recv(size - len(data))
                    if not chunk:
                        raise RuntimeError("Intercom connection closed before responding")
                    data.extend(chunk)
                return data
            size = int.from_bytes(exact(4), "big")
            if not 0 < size <= 1024 * 1024:
                raise ValueError(f"Invalid intercom frame size: {size}")
            message = json.loads(exact(size))
            if message.get("type") == "error":
                raise RuntimeError(message["error"])
            return message

        stamp = int(time.time() * 1000)
        # The broker requires registration even for a read-only roster request.
        send({"type": "register", "session": {"name": "kde-ai-usage-observer", "cwd": str(Path.cwd()),
              "model": "widget-observer", "pid": os.getpid(), "startedAt": stamp, "lastActivity": stamp, "status": "idle"}})
        while receive().get("type") != "registered":
            pass
        send({"type": "list", "requestId": "agents"})
        while True:
            message = receive()
            if message.get("type") == "sessions" and message.get("requestId") == "agents":
                send({"type": "unregister"})
                return message["sessions"]


def konsole_agent(pid, proc=Path("/proc")):
    try:
        process = proc / str(pid)
        if (process / "comm").read_text().strip() != "pi":
            return False
        stat = (process / "stat").read_text().rsplit(")", 1)[1].split()
        if int(stat[4]) == 0 or stat[0] in ("Z", "X"):
            return False
        if not os.readlink(process / "fd/0").startswith("/dev/pts/"):
            return False
        args = (process / "cmdline").read_bytes().split(b"\0")
        if any(arg in (b"--print", b"-p", b"--mode", b"--no-input") for arg in args):
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
            if len(seen) > 1 and command == "pi":
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
        seen.add(pid)
        status = session.get("status", "").split(" · ", 1)[0]
        if status in ("idle", "tool:ask_user", "tool:ask_user_question"):
            idle += 1
        elif status == "thinking" or status.startswith("tool:"):
            working += 1
        else:
            raise ValueError(f"Unknown Pi status for {session['id']}: {status!r}")
    return {"working": working, "idle": idle}


def snapshot():
    try:
        return count_agents(intercom_sessions())
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        return {"error": f"Pi agent counts unavailable: {exc}"}


if __name__ == "__main__":
    result = snapshot()
    print(json.dumps(result, separators=(",", ":")))
    if "error" in result:
        print(result["error"], file=sys.stderr)
        sys.exit(1)
