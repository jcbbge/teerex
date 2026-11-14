"""Public send CLI tests. Real disposable Rex terminals, never a personal server.

TEEREX_BIN selects the integrated executable; REX_BIN optionally selects a Rex build.
Fault-injected transport tests are explicitly separate from real Rex checks.
"""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import signal
import select
import subprocess
import sys
import tempfile
import time
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/acceptance'))
import pane_authority


BIN = str(Path(os.environ.get("TEEREX_BIN", Path(__file__).resolve().parents[2] / "zig-out/bin/teerex")).resolve())


class SendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rex = os.environ.get("REX_BIN") or shutil.which("rex")
        if not cls.rex:
            raise unittest.SkipTest("Rex executable required")
        cls.tmp = tempfile.TemporaryDirectory(prefix="teerex-send-")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        cls.socket = cls.root / "rex.sock"
        cls.endpoint = "unix://" + str(cls.socket)
        cls.base = [cls.rex, "--autostart=false", "--server", cls.endpoint, "--timeout", "3s"]
        cls.config = cls.root / "init.lua"
        cls.config.write_text("")
        cls.log = (cls.root / "server.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen([
            cls.rex, "server", "run", "--listen", cls.endpoint, "--restore=false",
            "--config", str(cls.config), "--state-dir", str(cls.root / "state"),
        ], stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            if cls.server.poll() is not None:
                raise RuntimeError((cls.root / "server.log").read_text())
            if cls.socket.exists():
                break
            time.sleep(.05)
        else:
            raise RuntimeError("Disposable server did not become ready")
        cls.source = cls.rpc("server.version", {})
        print("Real Rex:", json.dumps(cls.source), flush=True)

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    @classmethod
    def rex_json(cls, *args):
        result = subprocess.run(cls.base + list(args), capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise RuntimeError(result.stderr)
        return json.loads(result.stdout)

    @classmethod
    def rpc(cls, method, args):
        return cls.rex_json("api", "call", method, json.dumps(args))

    def setUp(self):
        self.work = self.root / str(time.monotonic_ns())
        self.work.mkdir()
        (self.work / "inbox").mkdir()
        # Exact same TMPDIR lock namespace as agent-send; no test lock in /tmp root.
        self.env = dict(os.environ, TEEREX_ASK_STATE_DIR=str(self.work / "asks"), TEEREX_CLUTCH_DIR=str(self.work / "clutch"), TMPDIR=str(self.work), AGENT_INBOX_DIR=str(self.work / "inbox"),
                        REX_SERVER="unix:///tmp/never-this-server.sock", REX_BLOCK="block:wrong",
                        REX_SESSION="session:wrong", REX_CLIENT="client:wrong",
                        PATH=str(Path(self.rex).parent) + os.pathsep + os.environ.get("PATH", ""))
        pane_authority.caller(self, self.rpc, self.env, self.work)

    def fixture(self, redirect_stdout=False, status=""):
        raw = self.work / ("received-" + str(time.monotonic_ns()))
        # Raw, no echo/canonical line limits. Bracketed paste brackets distinguish each
        # event, independently of the controller's ACK receipt or terminal capture.
        code = ("import os,tty; tty.setraw(0); "
                "os.write(1," + repr(("\x1b[?2004h" + status + "READY").encode()) + "); "
                + ("os.dup2(os.open('/dev/null',os.O_WRONLY),1); " if redirect_stdout else "")
                + f"f=open({str(raw)!r},'ab',buffering=0)\n"
                "while True:\n b=os.read(0,65536)\n if not b: break\n f.write(b)\n")
        v = self.rex_json("new", "--json", "--keep-open", "--shell=none", "--", sys.executable, "-c", code)
        target = v["session_id"], v["initial_windows"][0]["block_ids"][0]
        for _ in range(100):
            v = self.rpc("com.superlogical.terminal.format", {
                "session_id": target[0], "block_id": target[1], "args": {"format": "text", "max_bytes": 256}})
            if "READY" in v["content"]:
                return target, raw
            time.sleep(.02)
        self.fail("Raw input fixture not ready")

    def command(self, target, message=b"hello", sender="worker", timeout=10000):
        path = self.work / ("message-" + str(time.monotonic_ns()))
        path.write_bytes(message)
        return [BIN, "send", "--socket", str(self.socket), "--session", target[0], "--block", target[1],
                "--from", sender, "--message-file", str(path), "--timeout-ms", str(timeout)]

    def send(self, target, message=b"hello", sender="worker", timeout=10000):
        r = subprocess.run(self.command(target, message, sender, timeout), env=self.env,
                           capture_output=True, text=True, timeout=timeout / 1000 + 5)
        return r, json.loads(r.stdout) if r.stdout else None

    def lock(self, target):
        return self.work / ("agent-send." + target[1].split(":")[1] + ".lock")

    def received(self, raw, expected):
        for _ in range(100):
            actual = raw.read_bytes()
            if len(actual) >= len(expected):
                self.assertEqual(actual, expected)
                return
            time.sleep(.02)
        self.assertEqual(raw.read_bytes(), expected)

    @staticmethod
    def pasted(message, sender="worker"):
        return b"\x1b[200~FROM " + sender.encode() + b": " + message + b"\x1b[201~\r"

    def prompt(self, suggestion="suggestion", ignore_clear=False, mode="clear"):
        log = self.work / ("prompt-" + str(time.monotonic_ns()))
        fixture = Path(__file__).with_name("prompt_fixture.py")
        made = self.rex_json("new", "--json", "--keep-open", "--shell=none", "--", sys.executable, str(fixture), str(log), suggestion, "ignore-clear" if ignore_clear else mode)
        target = made["session_id"], made["initial_windows"][0]["block_ids"][0]
        for _ in range(100):
            if log.exists():
                return target, log
            time.sleep(.02)
        self.fail("prompt did not start")

    def type_draft(self, target, text):
        self.rpc("com.superlogical.terminal.write", {"session_id": target[0], "block_id": target[1], "args": {"data": text}})

    def prompt_text(self, target):
        return self.rpc("com.superlogical.terminal.format", {"session_id": target[0], "block_id": target[1],
                        "args": {"format": "text", "max_bytes": 65536}})["content"]

    def test_attention_three_sends_ask_and_refusal(self):
        target, raw = self.fixture()
        self.env['TEEREX_ATTENTION_DIR'] = str(self.work / 'attention')
        self.rpc('session.set_block_label', dict(session_id=target[0], block_id=target[1], label='seat'))
        expected = b''
        for _ in range(3):
            message = 'hello\u00a0world three'.encode()
            result, packet = self.send(target, message, sender='attention-worker')
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            expected += self.pasted(message, 'attention-worker')
        self.received(raw, expected)
        def snapshot():
            result = subprocess.run([BIN, 'boards', 'attention', '--json', '--since', 'today',
                                     '--profiles', str(self.work / 'no-profiles'),
                                     '--agents-registry', str(self.work / 'no-agents')],
                                    env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            return json.loads(result.stdout)
        counts = snapshot()
        self.assertEqual((counts['messages'], counts['words']), (3, 9))
        self.assertEqual(counts['senders'][0]['sender'], 'attention-worker')
        result = subprocess.run([BIN, 'ask', '--socket', str(self.socket), '--host', 'test',
                                 '--session', target[0], '--block', target[1], '--from', 'attention-worker',
                                 '--title', 'Fixture question', '--ask', 'Choose one?', '--context', 'Test only',
                                 '--option', 'One :: gain :: loss', '--option', 'Two :: gain :: loss',
                                 '--recommend', 'One', '--draft', 'ignore'],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(snapshot()['messages'], 4, 'ask child send counts once')
        # Failed sends never enter attention accounting.
        result, _ = self.send((target[0], 'block:00000000-0000-0000-0000-000000000000'), sender='attention-worker')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(snapshot()['messages'], 4)
        # Count failure is visible but cannot change acknowledged input or encourage replay.
        (self.work / 'attention/deliveries.jsonl').chmod(0o644)
        result, packet = self.send(target, b'count failure', sender='attention-worker')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(packet['status_record'], 'attention_unavailable')
        (self.work / 'attention/deliveries.jsonl').chmod(0o600)
        # Explicit registration, without the native seat label, covers custom stores.
        self.rpc('session.set_block_label', dict(session_id=target[0], block_id=target[1], label='fixture'))
        store = self.work / 'boards'
        store.mkdir(mode=0o700)
        common = ['--store', str(store), '--host', 'test', '--socket', str(self.socket),
                  '--session', target[0], '--block', target[1]]
        result = subprocess.run([BIN, 'boards', 'seat', 'register', *common, '--owner', 'fixture'],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        for _ in range(3):
            result = subprocess.run(self.command(target, b'legacy route', sender='attention-worker') + ['--store', str(store), '--host', 'test'],
                                    env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(json.loads(result.stdout)['attention_count'], 'written')
        self.assertEqual(snapshot()['messages'], 7)
        result = subprocess.run([BIN, 'ask', *common, '--from', 'attention-worker',
                                 '--title', 'Registered question', '--ask', 'Choose one?', '--context', 'Test only',
                                 '--option', 'One :: gain :: loss', '--option', 'Two :: gain :: loss',
                                 '--recommend', 'One', '--draft', 'ignore'],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(snapshot()['messages'], 8, 'custom registered ask counted once')

    def test_harness_app_records_keep_managed_send_bookkeeping(self):
        for app, identifier in (("codex", "teerex/tint"), ("claude", "teerex"), ("teerex-agent", "legacy")):
            with self.subTest(app=app):
                target, raw = self.fixture(status="\x1b]7501;state=idle:id=" + identifier + ":app=" + app + "\x07")
                result, packet = self.send(target)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(packet["outcome"], "events_acknowledged")
                self.assertEqual(packet["status_record"], "written" if identifier == "teerex/tint" else "agent_turn_start_recorded")
                self.received(raw, self.pasted(b"hello"))

    def test_status_failure_does_not_fail_or_repeat_delivered_message(self):
        target, raw = self.fixture()
        helpers = self.work / 'helpers'
        helpers.mkdir()
        helper = helpers / 'python3'
        helper.write_text('#!/bin/sh\nexit 44\n')
        helper.chmod(0o700)
        self.env['PATH'] = str(helpers) + os.pathsep + self.env['PATH']
        subprocess.check_call(self.base + ["block", "rename", "-s", target[0], target[1], "seat"])
        r, packet = self.send(target)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(packet["outcome"], "events_acknowledged")
        self.assertEqual(packet["status_record"], "failed")
        self.received(raw, self.pasted(b"hello"))

    def test_status_uses_input_fd_or_controlling_tty_when_stdout_redirected(self):
        target, raw = self.fixture(redirect_stdout=True)
        self.rpc('session.set_block_label', dict(session_id=target[0], block_id=target[1], label='seat'))
        result, packet = self.send(target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(packet['status_record'], 'written')
        self.received(raw, self.pasted(b'hello'))
        status = self.rpc('com.superlogical.terminal.program_status', dict(session_id=target[0], block_id=target[1], args={}))
        self.assertTrue(any(r.get('id') == 'msg/worker' for r in status['records']))
        # Keep the slave open so Rex's PTY reader stays live after stdio redirection.
        code = "import os,time; print('REDIRECT_READY',flush=True); keep=os.dup(0); fd=os.open('/dev/null',os.O_RDWR); [os.dup2(fd,n) for n in (0,1,2)]; time.sleep(120)"
        made = self.rex_json('new', '--json', '--keep-open', '--shell=none', '--', sys.executable, '-c', code)
        redirected = made['session_id'], made['initial_windows'][0]['block_ids'][0]
        self.rpc('session.set_block_label', dict(session_id=redirected[0], block_id=redirected[1], label='seat'))
        for _ in range(100):
            if 'REDIRECT_READY' in self.prompt_text(redirected):
                break
            time.sleep(.02)
        result, packet = self.send(redirected)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(packet['status_record'], 'written')
        process = self.rpc('com.superlogical.terminal.process', dict(session_id=redirected[0], block_id=redirected[1], args={}))
        pid = process['child']['pid']
        import importlib.util
        spec = importlib.util.spec_from_file_location('seat_status_tty', Path(__file__).parents[1] / 'boards/seat_status.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.write_status(pid, 'TTY_CONTROL_PROBE'), 'written')
        for _ in range(100):
            if 'TTY_CONTROL_PROBE' in self.prompt_text(redirected):
                break
            time.sleep(.02)
        self.assertIn('TTY_CONTROL_PROBE', self.prompt_text(redirected))
        records = self.rpc('com.superlogical.terminal.program_status', dict(session_id=redirected[0], block_id=redirected[1], args={}))['records']
        self.assertTrue(any(r.get('id') == 'msg/worker' for r in records), records)

    def test_seat_status_message_and_decision_resolution(self):
        target, raw = self.fixture()
        subprocess.check_call(self.base + ["block", "rename", "-s", target[0], target[1], "seat"])
        r, packet = self.send(target, ("first\tline " + "β" * 190 + "\nignored").encode())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(packet["status_record"], "written")
        def records():
            return self.rex_json("block", "call", "-s", target[0], "-b", target[1], "program_status", "{}")["records"]
        record = next(r for r in records() if r.get("id") == "msg/worker")
        self.assertEqual(record["state"], "done")
        self.assertEqual(record["title"], "FROM worker")
        self.assertEqual(record["msg"], ("firstline " + "β" * 190)[:180])
        if Path(BIN).name != "teerex":
            return  # ask cards are a combined-CLI verb; a standalone send cartridge proves the message record only.
        card = dict(id="card-1", title="Choose", ask="Continue now?", context="Disposable test",
                    options=[dict(label="Yes", gain="Continue", lose="Time"), dict(label="No", gain="Time", lose="Delay")],
                    recommend="Yes")
        path = self.work / "card.json"
        path.write_text(json.dumps(card))
        common = [BIN, "ask", "--socket", str(self.socket), "--session", target[0], "--block", target[1],
                  "--host", "test", "--from", "worker", "--draft", "ignore"]
        r = subprocess.run(common + ["--card-file", str(path)], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        record = next(r for r in records() if r.get("id") == "ask/card-1")
        self.assertEqual((record["state"], record["kind"], record["msg"]), ("blocked", "question", "Continue now?"))
        r = subprocess.run(common + ["--resolve", "card-1", "--answer", "Yes"], env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(any(r.get("id") == "ask/card-1" for r in records()))
        subprocess.check_call(self.base + ["block", "rename", "-s", target[0], target[1], "worker"])
        r, packet = self.send(target)
        self.assertEqual(packet["status_record"], "not_requested")

    def test_ask_resolve_reply_paths_never_paste_into_resolver(self):
        if Path(BIN).name != "teerex":
            self.skipTest("ask is a combined-CLI verb; the standalone send cartridge has no ask")
        seat, seat_raw = self.fixture()
        asker, asker_raw = self.fixture()
        for target, label in ((seat, 'seat'), (asker, 'asker')):
            self.rpc('session.set_block_label', dict(session_id=target[0], block_id=target[1], label=label))
        seat_env = dict(self.env, REX_SESSION=seat[0], REX_BLOCK=seat[1])
        asker_env = dict(self.env, REX_SESSION=asker[0], REX_BLOCK=asker[1])
        common = [BIN, 'ask', '--socket', str(self.socket), '--host', 'test', '--session', seat[0], '--block', seat[1], '--from', 'asker', '--draft', 'ignore']
        def records():
            return self.rpc('com.superlogical.terminal.program_status', dict(session_id=seat[0], block_id=seat[1], args={}))['records']
        def run(command, env):
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)
        for index, route in enumerate(('resolve', 'self_resolve', 'send', 'answer', 'clear_only')):
            card_id = 'reply-' + str(index)
            path = self.work / (card_id + '.json')
            path.write_text(json.dumps(dict(id=card_id, title='Choose', ask='Proceed?', context='fixture',
                options=[dict(label='Yes', gain='Go', lose='Time'), dict(label='No', gain='Wait', lose='Delay')], recommend='Yes')))
            run(common + ['--card-file', str(path)], asker_env)
            self.assertTrue(any(r.get('id') == 'ask/' + card_id for r in records()))
            before_seat, before_asker = seat_raw.read_bytes(), asker_raw.read_bytes()
            if route in ('resolve', 'self_resolve', 'clear_only'):
                command = common + ['--resolve', card_id]
                if route != 'clear_only':
                    command += ['--answer', 'Yes']
                packet = run(command, asker_env if route == 'self_resolve' else seat_env)
                self.assertEqual(packet['terminal_input_attempted'], route == 'resolve')
            elif route == 'send':
                command = self.command(asker, b'Yes', sender='seat')
                run(command, seat_env)
            else:
                command = [BIN, 'ask', '--socket', str(self.socket), '--host', 'test', '--session', asker[0], '--block', asker[1],
                           '--from', 'seat', '--answer', 'Yes', '--draft', 'ignore']
                run(command, seat_env)
            self.assertFalse(any(r.get('id') == 'ask/' + card_id for r in records()), route)
            self.assertEqual(seat_raw.read_bytes(), before_seat, 'resolution must never paste into the seat resolver')
            if route in ('self_resolve', 'clear_only'):
                self.assertEqual(asker_raw.read_bytes(), before_asker, 'resolver must never type into itself')
            else:
                self.assertIn(b'Yes', asker_raw.read_bytes()[len(before_asker):])

    def test_ask_fallback_expiry_clears_only_old_question_records(self):
        import importlib.util
        from unittest.mock import patch
        seat, raw = self.fixture()
        self.rpc('session.set_block_label', dict(session_id=seat[0], block_id=seat[1], label='seat'))
        command = self.command(seat, b'Question', sender='worker') + ['--status-id', 'ask/expire', '--status-state', 'blocked']
        sent = subprocess.run(command, env=self.env, capture_output=True, text=True)
        self.assertEqual(sent.returncode, 0, sent.stdout + sent.stderr)
        records = self.rpc('com.superlogical.terminal.program_status', dict(session_id=seat[0], block_id=seat[1], args={}))
        spec = importlib.util.spec_from_file_location('seat_status', Path(__file__).parents[1] / 'boards/seat_status.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        real_now = time.time()
        rows = [dict(session=seat[0], block=seat[1], program_status=records)]
        with patch.dict(os.environ, dict(TEEREX_INTERNAL_REX=self.rex, TEEREX_ASK_STATE_DIR=self.env['TEEREX_ASK_STATE_DIR'])):
            self.assertEqual(module.expire(str(self.socket), rows), 0)
            with patch.object(module.time, 'time', return_value=real_now + 1801):
                self.assertEqual(module.expire(str(self.socket), rows), 1, rows)
        current = self.rpc('com.superlogical.terminal.program_status', dict(session_id=seat[0], block_id=seat[1], args={}))['records']
        self.assertFalse(any(r.get('id') == 'ask/expire' for r in current))

    def test_draft_guard_reference_parser_fixtures(self):
        fixtures = [("│ ❯ │", ""), ("│ ❯ \x1b[2msuggest\x1b[0m │", ""),
                    ("│ ❯ \x1b[90msuggest\x1b[0m │", ""), ("│ ❯ fix the tests │", "fix the tests"),
                    ("│ ❯ fix\x1b[38;5;245m suggestion\x1b[0m │", "fix"),
                    ("│ ❯ \x1b[38;2;100;100;100msuggest\x1b[0m │", ""),
                    ("┃ > α😀\x1b[22m kept ┃", "α😀 kept"),
                    ("| > \x1b[38;5;239mreal\x1b[39m |", "real"),
                    ("❯\xa0a\x1b[1Cb\x1b[2Cc\x1b[1Cdd", "a b  c dd"),
                    ("❯\xa0a\x1b[Cb", "a b"),
                    ("❯\xa0a\x1b[0Cb", "a b"),
                    ("❯\xa0a\x1b[2C\x1b[90msuggest\x1b[3Cgrey\x1b[0m", "a"),
                    ("❯\xa0a\x1b[90msuggest\x1b[3Cgrey\x1b[0m\x1b[2Cb", "a  b"),
                    ("❯\xa0\x1b[2msuggest\x1b[Cgrey\x1b[0m", ""),
                    ("> old\n" + "other\n" * 15, ""), ("> first\n> last", "last")]
        fixtures += [
            ("\x1b[0m\x1b[1m\x1b[48;2;41;44;49m›\x1b[0m\x1b[48;2;41;44;49m \x1b[0m\x1b[2m\x1b[48;2;41;44;49mAsk Codex to do anything\x1b[0m\x1b[48;2;41;44;49m\x1b[54X\x1b[54C\x1b[0m", ""),
            ("› \x1b[48;2;41;44;49mreal typed β\x1b[0m", "real typed β"),
            ("› \x1b[48;5;2mAsk Codex to do anything\x1b[0m", "Ask Codex to do anything"),
            ("> \x1b[7m\x1b[2mT\x1b[22m\x1b[27m\x1b[2mype a message\x1b[22m", ""),
            ("> \x1b[48;2;2;2;2mtyped\x1b[0m", "typed"),
            # Busy Claude Code greys the marker itself; the human's text after the reset is the draft.
            ("\x1b[0m\x1b[38;2;153;153;153m❯\xa0\x1b[0mqqbusy\r", "qqbusy"),
            ("\x1b[0m\x1b[38;2;153;153;153m❯\xa0\x1b[0mseat\x1b[1Ctyping\r", "seat typing"),
            ("\x1b[0m\x1b[38;2;153;153;153m❯\xa0\x1b[0m\x1b[38;2;153;153;153mPress up to edit queued messages\x1b[0m", ""),
        ]
        lua = Path(__file__).with_name("draft.lua").read_text() + "\nlocal out={} for _,v in ipairs(rex.args.cases) do table.insert(out,draft_from_vt(v)) end io.write(rex.json.encode(out))"
        target, _ = self.fixture()
        result = self.rex_json("do", "--session", target[0], "--block", target[1], "-e", lua, "--args", json.dumps(dict(cases=[f[0] for f in fixtures])))
        self.assertEqual(result, [f[1] for f in fixtures])

    def test_codex_dim_placeholder_does_not_clear_and_real_text_is_restored(self):
        target, log = self.prompt("Ask Codex to do anything", mode="codex-ignore-clear")
        result, packet = self.send(target, b"placeholder regression")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(packet["draft"]["detected"])
        self.assertIsNone(packet["draft"]["cleared"])
        for _ in range(100):
            if log.read_text():
                break
            time.sleep(.02)
        self.assertEqual([json.loads(line) for line in log.read_text().splitlines()], ["FROM worker: placeholder regression"])
        typed, typed_log = self.prompt("Ask Codex to do anything", mode="codex")
        self.type_draft(typed, "Ask Codex to do anything")
        result, packet = self.send(typed, b"typed draft regression")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(packet["draft"]["detected"])
        self.assertTrue(packet["draft"]["cleared"] and packet["draft"]["restore_verified"])
        self.assertIn("Ask Codex to do anything", self.prompt_text(typed))
        self.assertEqual([json.loads(line) for line in typed_log.read_text().splitlines()], ["FROM worker: typed draft regression"])

    def test_detached_terminal_keeps_draft_guard_and_process(self):
        if Path(BIN).name != "teerex":
            self.skipTest("clutch is a combined-CLI verb; the standalone send cartridge has no clutch")
        target, log = self.prompt(mode='busy')
        self.type_draft(target, 'PRIVATE_DETACHED_DRAFT')
        child = self.rpc('com.superlogical.terminal.process', dict(session_id=target[0], block_id=target[1], args={}))['child']
        self.rpc('session.detach_block', dict(session_id=target[0], block_id=target[1]))
        clutch = [BIN, 'clutch', 'take', '--socket', str(self.socket), '--session', target[0], '--pane', target[1], '--reason', 'human reviewing detached agent']
        held = subprocess.run(clutch, env=self.env, capture_output=True, text=True)
        self.assertEqual(held.returncode, 0, held.stdout + held.stderr)
        blocked = subprocess.run(self.command(target) + ['--no-queue', '--draft-wait-ms', '0'], env=self.env, capture_output=True, text=True)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertEqual(json.loads(blocked.stdout)['failure_reason'], 'pane_held_by_human')
        self.assertEqual(log.read_text(), '')
        clutch[2] = 'release'
        released = subprocess.run(clutch, env=self.env, capture_output=True, text=True)
        self.assertEqual(released.returncode, 0, released.stdout + released.stderr)
        result, packet = self.send(target)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(packet['draft']['detected'])
        self.assertTrue(packet['draft']['restored'] and packet['draft']['restore_verified'])
        self.assertEqual([json.loads(line) for line in log.read_text().splitlines()], ['FROM worker: hello'])
        self.assertIn('PRIVATE_DETACHED_DRAFT', self.prompt_text(target))
        self.assertNotIn('PRIVATE_DETACHED_DRAFT', result.stdout + result.stderr)
        self.assertEqual(self.rpc('com.superlogical.terminal.process', dict(session_id=target[0], block_id=target[1], args={}))['child'], child)
        blocks = self.rpc('session.list_blocks', dict(session_id=target[0]))['blocks']
        self.assertEqual(next(b for b in blocks if b['block_id'] == target[1])['placement'], 'detached')

    def test_guard_restores_existing_unicode_draft_without_submitting_it(self):
        for text in ("OPERATOR_PRIVATE_DRAFT", "α😀 private café"):
            target, log = self.prompt()
            self.type_draft(target, text)
            r, packet = self.send(target)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            self.assertEqual([json.loads(line) for line in log.read_text().splitlines()], ["FROM worker: hello"])
            self.assertIn("❯\xa0" + text, self.prompt_text(target))
            draft = packet["draft"]
            self.assertEqual(draft["mode"], "guard")
            self.assertTrue(draft["detected"])
            self.assertEqual(draft["chars"], len(text))
            self.assertGreaterEqual(draft["waited_ms"], 1400)
            self.assertFalse(draft["bound_reached"])
            self.assertTrue(draft["cleared"] and draft["restored"] and draft["restore_verified"])
            self.assertNotIn(text, r.stdout + r.stderr)

    def test_guard_preserves_cursor_forward_spaces_with_nbsp_prompt(self):
        target, log = self.prompt()
        text = "a b  c dd"
        self.type_draft(target, text)
        result = subprocess.run(self.command(target) + ["--draft-wait-ms", "0"],
                                env=self.env, capture_output=True, text=True, timeout=6)
        packet = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(packet["draft"]["restore_verified"])
        self.assertEqual(packet["draft"]["chars"], len(text))
        self.assertIsNone(packet["draft_warning"])
        self.assertIn("❯\xa0" + text, self.prompt_text(target))
        self.assertEqual([json.loads(line) for line in log.read_text().splitlines()], ["FROM worker: hello"])
        self.assertNotIn(text, result.stdout + result.stderr)

    def test_guard_waits_for_typing_and_restores_in_order(self):
        target, log = self.prompt()
        text = "typingPRIVATE123"
        self.type_draft(target, text[0])
        def type_more():
            for char in text[1:]:
                time.sleep(.2)
                self.type_draft(target, char)
        writer = threading.Thread(target=type_more)
        writer.start()
        try:
            r, packet = self.send(target)
        finally:
            writer.join()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertGreater(packet["draft"]["waited_ms"], 3500)
        self.assertEqual([json.loads(line) for line in log.read_text().splitlines()], ["FROM worker: hello"])
        self.assertIn("❯\xa0" + text, self.prompt_text(target))
        self.assertNotIn(text, r.stdout + r.stderr)

    def test_busy_grey_marker_draft_is_cleared_sent_alone_and_restored(self):
        # Josh's interruption: a busy Claude greys its marker, the guard saw no draft and pasted onto it.
        target, log = self.prompt(mode="busy")
        text = "seat typing"
        self.type_draft(target, text[0])
        def type_more():
            for char in text[1:]:
                time.sleep(.2)
                self.type_draft(target, char)
        writer = threading.Thread(target=type_more)
        writer.start()
        try:
            r, packet = self.send(target)
        finally:
            writer.join()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(packet["draft"]["detected"])
        self.assertEqual([json.loads(line) for line in log.read_text().splitlines()], ["FROM worker: hello"])
        self.assertIn(text, self.prompt_text(target).splitlines()[-1])

    def test_restore_late_redraw_and_dropped_paste_preserve_send_ack(self):
        for mode, verified in (("late-redraw", True), ("drop-restore", False)):
            with self.subTest(mode=mode):
                target, log = self.prompt(mode=mode)
                text = "PRIVATE_RESTORE_DRAFT_α"
                self.type_draft(target, text)
                result = subprocess.run(self.command(target) + ["--draft-wait-ms", "0"],
                                        env=self.env, capture_output=True, text=True, timeout=6)
                packet = json.loads(result.stdout)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(packet["outcome"], "events_acknowledged")
                self.assertIsNone(packet["failure_reason"])
                self.assertEqual(packet["draft"]["restored"], verified)
                self.assertEqual(packet["draft"]["restore_verified"], verified)
                self.assertEqual(packet["draft_warning"], None if verified else "draft_restore_unverified")
                self.assertEqual([json.loads(line) for line in log.read_text().splitlines()], ["FROM worker: hello"])
                self.assertNotIn(text, result.stdout + result.stderr)
                if verified:
                    self.assertIn("❯\xa0" + text, self.prompt_text(target))
                else:
                    self.assertNotIn(text, self.prompt_text(target))

    def test_guard_refuses_uncleared_draft_and_validates_limits(self):
        target, log = self.prompt(ignore_clear=True)
        text = "PRIVATE_UNCLEARABLE_DRAFT"
        self.type_draft(target, text)
        command = self.command(target)
        del command[-2:]  # Exercise the new default overall timeout.
        result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=5)
        packet = json.loads(result.stdout)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(packet["timeout_ms"], 40000)
        self.assertEqual(packet["failure_reason"], "draft_not_cleared")
        self.assertFalse(packet["draft"]["cleared"])
        self.assertFalse(packet["paste"]["attempted"])
        self.assertEqual(log.read_text(), "")
        self.assertIn(text, self.prompt_text(target))
        self.assertNotIn(text, result.stdout + result.stderr)
        for flags in (["--draft", "bad"], ["--draft-wait-ms", "55001"], ["--draft-wait-ms", "-1"]):
            result = subprocess.run(command + flags, env=self.env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2)
        target, _ = self.prompt("")
        command = self.command(target)
        del command[-2:]
        result = subprocess.run(command + ["--draft-wait-ms", "55000", "--timeout-ms", "115000"],
                                env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_guard_suggestions_empty_bound_and_ignore(self):
        for suggestion in ("grey suggestion", ""):
            target, log = self.prompt(suggestion)
            r, packet = self.send(target)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            self.assertFalse(packet["draft"]["detected"])
            self.assertLess(packet["draft"]["waited_ms"], 250)
            self.assertEqual([json.loads(line) for line in log.read_text().splitlines()], ["FROM worker: hello"])
        target, log = self.prompt()
        self.type_draft(target, "savedPRIVATE")
        r = subprocess.run(self.command(target) + ["--draft-wait-ms", "0"], env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertTrue(json.loads(r.stdout)["draft"]["bound_reached"])
        self.assertIn("❯\xa0savedPRIVATE", self.prompt_text(target))
        r = subprocess.run(self.command(target) + ["--draft", "ignore"], env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(json.loads(log.read_text().splitlines()[-1]), "savedPRIVATEFROM worker: hello")
        self.assertEqual(json.loads(r.stdout)["draft"]["mode"], "ignore")

    def test_exact_unicode_multiline_target_and_existing_draft(self):
        target, raw = self.fixture()
        other, untouched = self.fixture()
        self.rpc("com.superlogical.terminal.write", {
            "session_id": target[0], "block_id": target[1], "args": {"data": "EXISTING"}})
        message = 'α "quotes" \\ $(touch NEVER)\nsecond\tline\n'.encode()
        r, packet = self.send(target, message, "source α")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(packet["outcome"], "events_acknowledged")
        self.assertEqual(packet["source"], {k: self.source[k] for k in ("rex_version", "platform", "api_revision")})
        self.assertEqual(packet["target"], {"server": self.endpoint, "session_id": target[0], "block_id": target[1]})
        self.assertEqual(packet["paste"], {"attempted": True, "acknowledged": True})
        self.assertEqual(packet["enter"], {"attempted": True, "acknowledged": True})
        self.assertFalse(packet["server_enforced_atomic_delivery"])
        self.assertFalse(packet["exclusive_input_lease"])
        self.assertEqual(packet["prompt_safety"], "not_assessed")
        self.assertEqual(packet["application_consumption"], "not_assessed")
        self.received(raw, b"EXISTING" + self.pasted(message, "source α"))
        self.assertEqual(untouched.read_bytes(), b"")
        self.assertFalse(self.lock(target).exists())

    def test_stdin_exact_bytes_validation_deadline_and_cancellation_before_dispatch(self):
        target, raw = self.fixture()
        command = self.command(target, timeout=500)
        command[command.index("--message-file") + 1] = "-"
        message = 'α "literal"\nlast\tline\n\n'.encode()
        result = subprocess.run(command, input=message, env=self.env, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.received(raw, self.pasted(message))
        for invalid in (b"", b"\xff", b"a\rb", b"a" * 65537):
            result = subprocess.run(command, input=invalid, env=self.env, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2, result.stderr)
        for sig in (None, signal.SIGINT, signal.SIGTERM):
            proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env)
            proc.stdin.write(b"partial, not EOF")
            proc.stdin.flush()
            if sig is not None:
                time.sleep(.05)
                proc.send_signal(sig)
            proc.wait(timeout=3)  # Keep writer open: EOF would hide a broken wait budget.
            packet = json.loads(proc.stdout.read())
            proc.stdin.close()
            proc.stdout.close()
            proc.stderr.close()
            self.assertEqual(proc.returncode, 124 if sig is None else 128 + sig)
            self.assertFalse(packet["paste"]["attempted"])
            self.assertFalse(packet["backend_invoked"])
            self.assertFalse(packet["cooperative_lock"]["acquired"])
        self.assertEqual(raw.read_bytes(), self.pasted(message))

    def test_encoded_boundary_printable_unicode_lf_and_escaping(self):
        target, raw = self.fixture()
        def rpc_bytes(message):
            params = {"session_id": target[0], "block_id": target[1],
                      "event": {"type": "paste", "payload": {"text": "FROM worker: " + message}}}
            # Independent Go-compatible JSON sizing, including HTML/line-separator escaping.
            encoded = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "block.event", "params": params},
                                 ensure_ascii=False, separators=(",", ":"))
            for char, escaped in [("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                                  ("\u2028", "\\u2028"), ("\u2029", "\\u2029")]:
                encoded = encoded.replace(char, escaped)
            return len(encoded.encode())
        overhead = rpc_bytes("")
        accepted = b""
        for char, cost in [("a", 1), ("α", 2), ("\n", 2), ('"', 2), ("<", 6)]:
            n = (60000 - overhead) // cost
            text = char * n + "x" * ((60000 - overhead) % cost)
            with self.subTest(kind=repr(char), boundary="accepted"):
                r, p = self.send(target, text.encode())
                self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
                self.assertEqual(p["encoded_rpc_bytes"], rpc_bytes(text))
                self.assertEqual(p["encoded_rpc_bytes"], 60000)
                accepted += self.pasted(text.encode())
                self.received(raw, accepted)
            with self.subTest(kind=repr(char), boundary="refused"):
                r, p = self.send(target, (text + "x").encode())
                self.assertEqual(r.returncode, 1, r.stderr + r.stdout)
                self.assertEqual(p["encoded_rpc_bytes"], 60001)
                self.assertEqual(p["failure_reason"], "encoded_paste_exceeds_limit")
                self.assertFalse(p["paste"]["attempted"])
                self.assertFalse(p["enter"]["attempted"])
                self.assertEqual(raw.read_bytes(), accepted)
        for message in [b"a" * 65536, "α".encode() * 32768, b"\n" * 65536]:
            r, p = self.send(target, message)
            self.assertEqual(r.returncode, 1, r.stderr + r.stdout)
            self.assertEqual(p["failure_reason"], "encoded_paste_exceeds_limit")
            self.assertFalse(p["paste"]["attempted"])
        self.assertEqual(raw.read_bytes(), accepted)

    def test_cooperating_senders_and_bridge_lock(self):
        target, raw = self.fixture()
        lock = self.lock(target)
        lock.mkdir()  # Same atomic mkdir used by agent-core agent-send.
        r, p = self.send(target, timeout=120)
        self.assertEqual(r.returncode, 124, r.stdout + r.stderr)
        self.assertFalse(p["cooperative_lock"]["acquired"])
        self.assertFalse(p["backend_invoked"])
        self.assertTrue(lock.exists())
        self.assertEqual(raw.read_bytes(), b"")
        lock.rmdir()
        messages = [((f"msg-{i}: " + "α" * 700 + "\nlast").encode()) for i in range(8)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda m: self.send(target, m), messages))
        for r, p in results:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(p["cooperative_lock"]["acquired"])
        for _ in range(100):
            data = raw.read_bytes()
            if len(data) == sum(len(self.pasted(m)) for m in messages):
                break
            time.sleep(.02)
        parts = data.split(b"\x1b[200~")[1:]
        self.assertCountEqual(parts, [self.pasted(m)[6:] for m in messages])
        self.assertFalse(lock.exists())

    def test_lock_is_not_server_enforced_exclusion(self):
        target, raw = self.fixture()
        self.lock(target).mkdir()
        self.rpc("com.superlogical.terminal.write", {
            "session_id": target[0], "block_id": target[1], "args": {"data": "BYPASS"}})
        self.received(raw, b"BYPASS")
        self.lock(target).rmdir()

    def test_inbox_marker_custom_and_home_default(self):
        target, raw = self.fixture()
        marker = self.work / "inbox" / (target[1].split(":")[1] + ".inbox")
        marker.write_text("hive\n")
        r, p = self.send(target)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(p["outcome"], "inbox_refused")
        self.assertFalse(p["backend_invoked"])
        marker.unlink()
        self.env["AGENT_INBOX_DIR"] = ""  # Bash ${AGENT_INBOX_DIR:-...} semantics.
        self.env["HOME"] = str(self.work)
        marker = self.work / ".local/state/agent-inbox" / marker.name
        marker.parent.mkdir(parents=True)
        marker.touch()
        r, p = self.send(target)
        self.assertEqual(p["outcome"], "inbox_refused")
        self.assertEqual(raw.read_bytes(), b"")

    def test_cancel_lock_wait_leaves_other_lock(self):
        target, raw = self.fixture()
        lock = self.lock(target)
        for sig in [signal.SIGINT, signal.SIGTERM]:
            lock.mkdir()
            # A full pipe write requires the sender to consume stdin, after Signals.init.
            # This proves readiness without creating a clutch record as a side effect.
            command = self.command(target)
            command[command.index("--message-file") + 1] = "-"
            proc = subprocess.Popen(command, env=self.env, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            proc.stdin.write("x" * 65536)
            proc.stdin.flush()
            self.assertTrue(select.select([], [proc.stdin], [], 5)[1], "sender did not consume stdin")
            proc.stdin.close()
            proc.stdin = None
            proc.send_signal(sig)
            out, err = proc.communicate(timeout=3)
            self.assertEqual(proc.returncode, 128 + sig, out + err)
            p = json.loads(out)
            self.assertEqual(p["outcome"], "cancel_requested")
            self.assertFalse(p["backend_invoked"])
            self.assertTrue(lock.exists())
            lock.rmdir()
        self.assertEqual(raw.read_bytes(), b"")

    def test_invalid_input_and_nonregular_file_fail_before_lock(self):
        target, raw = self.fixture()
        for message in [b"", b"\xff", b"\x00", b"\x1b[201~", b"a\rb", b"\x7f", b"a" * 65537]:
            r, p = self.send(target, message)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIsNone(p)
        command = self.command(target)
        path = Path(command[command.index("--message-file") + 1])
        path.unlink()
        os.mkfifo(path)
        r = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=3)
        self.assertEqual(r.returncode, 2, r.stderr)
        for flag, value in [("--socket", "relative"), ("--session", "label"), ("--block", "block:123"),
                            ("--block", target[1].upper()), ("--from", "bad\nlabel"), ("--timeout-ms", "99")]:
            command = self.command(target)
            command[command.index(flag) + 1] = value
            r = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=3)
            self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(raw.read_bytes(), b"")
        self.assertFalse(self.lock(target).exists())

    def test_mismatched_target_and_missing_server_fail_closed(self):
        target, raw = self.fixture()
        other, untouched = self.fixture()
        r, p = self.send((target[0], other[1]))
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(p["paste"]["acknowledged"])
        command = self.command(target)
        command[command.index("--socket") + 1] = str(self.work / "absent.sock")
        r = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(json.loads(r.stdout)["enter"]["acknowledged"])
        self.assertEqual(raw.read_bytes(), b"")
        self.assertEqual(untouched.read_bytes(), b"")
        self.assertFalse(self.lock(target).exists())

    def test_fault_injected_partial_ack_deadline_and_malformed_transport(self):
        target, raw = self.fixture()
        fake = self.work / "fake"
        fake.mkdir()
        self.env["PATH"] = str(fake)
        prefix = (f"#!{sys.executable}\nimport json,time\n"
                  "def emit(v): print(json.dumps(v),flush=True)\n"
                  "emit({'event':'source','source':{'rex_version':'injected','platform':'test','api_revision':13}})\n"
                  "time.sleep(.03)\n"
                  "emit({'event':'attempt','stage':'paste'})\n"
                  "emit({'event':'ack','stage':'paste'})\n"
                  "emit({'event':'attempt','stage':'enter'})\n")
        for tail, expected, code in [
            ("emit({'event':'failed','reason':'enter_call_failed'})\n", "uncertain", 1),
            ("time.sleep(30)\n", "deadline_exceeded", 124),
            ("print('invalid',flush=True)\ntime.sleep(30)\n", "uncertain", 1),
        ]:
            script = fake / "rex"
            script.write_text(prefix + tail)
            script.chmod(0o755)
            r, p = self.send(target, timeout=250)
            self.assertEqual(r.returncode, code, r.stdout + r.stderr)
            self.assertEqual(p["outcome"], expected)
            self.assertEqual(p["source"], {"rex_version": "injected", "platform": "test", "api_revision": 13})
            self.assertEqual(p["paste"], {"attempted": True, "acknowledged": True})
            self.assertEqual(p["enter"], {"attempted": True, "acknowledged": False})
            self.assertFalse(self.lock(target).exists())
        self.assertEqual(raw.read_bytes(), b"")  # Fault backend never touched actual Rex.


if __name__ == "__main__":
    unittest.main(verbosity=2)
