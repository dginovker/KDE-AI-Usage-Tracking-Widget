import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("widget_agents", Path(__file__).resolve().parents[1] / "plasmoid/contents/code/widget_agents.py")
agents = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agents)


class AgentCountsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.proc = Path(self.directory.name)
        self.process(10, 1, "konsole", tty=0)
        self.process(20, 10, "zsh")
        self.process(30, 20, "pi")

    def process(self, pid, parent, command, tty=34816, args=b"pi\0", env=b"", state="S"):
        path = self.proc / str(pid)
        (path / "fd").mkdir(parents=True, exist_ok=True)
        (path / "stat").write_text(f"{pid} ({command}) {state} {parent} {pid} {pid} {tty} " + "0 " * 14 + str(pid * 100))
        (path / "comm").write_text(command)
        (path / "cmdline").write_bytes(args)
        (path / "environ").write_bytes(env)
        (path / "fd/0").symlink_to("/dev/pts/1" if tty else "/dev/null")

    def session(self, pid=30, status="thinking", name="main"):
        return {"id": name, "name": name, "pid": pid, "status": status}

    def test_main_konsole_agent_and_runtime_chat_alias_count(self):
        self.assertTrue(agents.konsole_agent(30, self.proc))
        self.assertEqual(agents.count_agents([self.session(name="subagent-chat-123")], self.proc), {"working": 1, "idle": 0})

    def test_idle_and_user_questions_are_idle(self):
        for status in ("idle", "tool:ask_user", "tool:ask_user_question", "idle · custom label"):
            with self.subTest(status=status):
                self.assertEqual(agents.count_agents([self.session(status=status)], self.proc), {"working": 0, "idle": 1})

    def test_thinking_and_non_question_tools_are_working(self):
        for status in ("thinking", "tool:bash", "thinking · custom label"):
            self.assertEqual(agents.count_agents([self.session(status=status)], self.proc), {"working": 1, "idle": 0})

    def test_excludes_headless_orphan_dead_and_non_pi_processes(self):
        self.process(31, 20, "pi", tty=0)
        self.process(32, 1, "pi")
        self.process(33, 20, "node")
        self.process(34, 20, "pi", state="Z")
        self.process(35, 20, "pi", args=b"pi\0--mode\0rpc\0")
        self.assertEqual(agents.count_agents([self.session(pid) for pid in range(31, 37)], self.proc), {"working": 0, "idle": 0})

    def test_excludes_workers_even_with_inherited_terminal(self):
        self.process(31, 20, "pi", env=b"PI_SUBAGENT_RUN_ID=123\0")
        self.process(32, 30, "bash")
        self.process(33, 32, "pi")
        self.assertFalse(agents.konsole_agent(31, self.proc))
        self.assertFalse(agents.konsole_agent(33, self.proc))

    def test_excludes_dashboard_terminal_not_in_konsole(self):
        self.process(40, 1, "tmux: server", tty=0)
        self.process(41, 40, "pi")
        self.assertFalse(agents.konsole_agent(41, self.proc))

    def test_repeated_roster_entries_count_once(self):
        self.assertEqual(agents.count_agents([self.session(), self.session()], self.proc), {"working": 1, "idle": 0})

    def test_unknown_or_missing_status_fails_visibly(self):
        for status in ("", "unknown"):
            with self.assertRaisesRegex(ValueError, "Unknown agent status"):
                agents.count_agents([self.session(status=status)], self.proc)

    def test_broker_failure_does_not_invent_zero_counts(self):
        with patch.object(agents, "intercom_sessions", side_effect=OSError("broker unavailable")):
            self.assertEqual(agents.snapshot(self.proc), {"error": "Agent counts unavailable: broker unavailable"})

    def test_native_claude_busy_idle_waiting_and_shell_states(self):
        self.process(31, 20, "claude")
        for status, working in (("busy", 1), ("idle", 0), ("waiting", 0), ("shell", 1)):
            with self.subTest(status=status):
                self.assertEqual(agents.count_agents([self.session(31, status)], self.proc), {"working": working, "idle": 1 - working})

    def test_codex_profile_is_not_headless(self):
        self.process(31, 20, "codex", args=b"codex\0-p\0coding\0")
        self.assertTrue(agents.konsole_agent(31, self.proc))

    def test_native_headless_workers_and_daemons_are_excluded(self):
        for pid, command, args, parent in (
            (31, "claude", b"claude\0-p\0hello\0", 20),
            (32, "codex", b"codex\0exec\0hello\0", 20),
            (33, "codex", b"codex\0app-server\0", 20),
            (34, "claude", b"claude\0", 30),
            (35, "codex", b"codex\0", 30),
            (36, "claude", b"claude\0--agent-id\0worker\0", 20),
        ):
            self.process(pid, parent, command, args=args)
            self.assertFalse(agents.konsole_agent(pid, self.proc))

    def test_codex_hook_lifecycle_and_metadata_only(self):
        self.process(31, 20, "codex")
        state_dir = self.proc / "codex-state"
        with patch.object(agents, "codex_state_dir", return_value=state_dir):
            for event, tool, working in (
                ("SessionStart", None, 0), ("UserPromptSubmit", None, 1),
                ("PreToolUse", "Bash", 1), ("PermissionRequest", "Bash", 0),
                ("PostToolUse", "Bash", 1), ("PreToolUse", "request_user_input", 0),
                ("PreToolUse", "AskUserQuestion", 0), ("PostToolUse", "request_user_input", 1),
                ("Interrupt", None, 0), ("Stop", None, 0),
            ):
                with self.subTest(event=event, tool=tool):
                    agents.codex_hook({"hook_event_name": event, "session_id": "test", "tool_name": tool,
                                       "prompt": "DO NOT STORE", "tool_input": {"secret": "DO NOT STORE"}}, self.proc, 31)
                    raw = (state_dir / "31.json").read_text()
                    self.assertNotIn("DO NOT STORE", raw)
                    records = agents.native_sessions(state_dir, "codex", self.proc)
                    self.assertEqual(agents.count_agents(records, self.proc), {"working": working, "idle": 1 - working})
            agents.codex_hook({"hook_event_name": "SessionEnd"}, self.proc, 31)
            self.assertFalse((state_dir / "31.json").exists())

    def test_hook_resolves_main_parent_and_ignores_workers(self):
        self.process(31, 20, "codex")
        self.process(32, 31, "sh")
        self.process(33, 32, "python3")
        state_dir = self.proc / "codex-state"
        with patch.object(agents, "codex_state_dir", return_value=state_dir):
            agents.codex_hook({"hook_event_name": "SessionStart", "session_id": "test"}, self.proc, 33)
            self.assertTrue((state_dir / "31.json").exists())
            self.process(34, 31, "codex", args=b"codex\0exec\0hi\0")
            agents.codex_hook({"hook_event_name": "Stop", "session_id": "worker"}, self.proc, 34)
            self.assertFalse((state_dir / "34.json").exists())
            self.assertEqual(json.loads((state_dir / "31.json").read_text())["sessionId"], "test")

    def test_stale_pid_presence_cannot_count_reused_process(self):
        self.process(31, 20, "codex")
        record = {**self.session(31), "procStart": "old"}
        self.assertEqual(agents.count_agents([record], self.proc), {"working": 0, "idle": 0})

    def test_snapshot_combines_three_providers(self):
        self.process(31, 20, "claude")
        self.process(32, 20, "codex")
        claude_home = self.proc / "claude-home"
        (claude_home / "sessions").mkdir(parents=True)
        (claude_home / "sessions/31.json").write_text(json.dumps({"pid": 31, "sessionId": "claude-test", "kind": "interactive", "status": "waiting", "procStart": "3100"}))
        state_dir = self.proc / "codex-state"
        with patch.object(agents, "codex_state_dir", return_value=state_dir), patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(claude_home)}), patch.object(agents, "intercom_sessions", return_value=[self.session()]):
            agents.codex_hook({"hook_event_name": "UserPromptSubmit", "session_id": "codex-test"}, self.proc, 32)
            self.assertEqual(agents.snapshot(self.proc), {"working": 2, "idle": 1})

    def test_missing_native_state_is_explicit_not_idle(self):
        self.process(31, 20, "codex")
        with patch.object(agents, "codex_state_dir", return_value=self.proc / "absent"), patch.object(agents, "intercom_sessions", return_value=[self.session()]):
            self.assertIn("approve the AI Usage hook", agents.snapshot(self.proc)["error"])

    def test_install_preserves_existing_hooks_and_is_idempotent(self):
        home = self.proc / "codex-home"
        home.mkdir()
        path = home / "hooks.json"
        original = {"description": "existing", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "existing command"}]}]}}
        path.write_text(json.dumps(original))
        with patch.dict(os.environ, {"CODEX_HOME": str(home)}):
            agents.install_codex_hooks()
            installed = path.read_text()
            agents.install_codex_hooks()
            self.assertEqual(path.read_text(), installed)
        value = json.loads(installed)
        self.assertEqual(value["description"], "existing")
        self.assertEqual(value["hooks"]["Stop"][0], original["hooks"]["Stop"][0])
        self.assertEqual(set(value["hooks"]), set(agents.CODEX_EVENTS))
        backups = list(home.glob("*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text()), original)

    def test_socket_protocol_handles_fragmented_frames_and_presence_events(self):
        runtime = self.proc / "intercom"
        runtime.mkdir()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(runtime / "broker.sock"))
            server.listen()
            received = []
            failures = []

            def serve():
                try:
                    with server.accept()[0] as client:
                        client.settimeout(3)
                        reader = client.makefile("rb")

                        def read():
                            value = json.loads(reader.read(int.from_bytes(reader.read(4), "big")))
                            received.append(value)
                            return value

                        def send(value):
                            payload = json.dumps(value).encode()
                            frame = len(payload).to_bytes(4, "big") + payload
                            for byte in frame:
                                client.sendall(bytes([byte]))

                        read()
                        send({"type": "registered", "sessionId": "observer"})
                        read()
                        send({"type": "presence_update"})
                        send({"type": "sessions", "requestId": "agents", "sessions": [self.session()]})
                        read()
                except Exception as exc:
                    failures.append(exc)

            thread = threading.Thread(target=serve)
            thread.start()
            try:
                with patch.dict(os.environ, {"PI_CODING_AGENT_DIR": str(self.proc)}):
                    self.assertEqual(agents.intercom_sessions(), [self.session()])
            finally:
                thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failures, [])
            self.assertEqual([message["type"] for message in received], ["register", "list", "unregister"])


if __name__ == "__main__":
    unittest.main()
