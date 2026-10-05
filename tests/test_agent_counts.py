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
        (path / "stat").write_text(f"{pid} ({command}) {state} {parent} {pid} {pid} {tty} 0")
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
            with self.assertRaisesRegex(ValueError, "Unknown Pi status"):
                agents.count_agents([self.session(status=status)], self.proc)

    def test_broker_failure_does_not_invent_zero_counts(self):
        with patch.object(agents, "intercom_sessions", side_effect=OSError("broker unavailable")):
            self.assertEqual(agents.snapshot(), {"error": "Pi agent counts unavailable: broker unavailable"})

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
