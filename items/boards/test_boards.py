"""Public boards/seat/decision contracts. Live tests use only an owned disposable Rex."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

BIN = str(Path(os.environ.get("TEEREX_BIN", "zig-out/bin/teerex")).resolve())
ROOT = Path(__file__).resolve().parents[2]
ZERO = "00000000-0000-0000-0000-000000000000"
OTHER = "11111111-1111-1111-1111-111111111111"


class BoardsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tboards-", dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / "store"
        self.store.mkdir(mode=0o700)
        self.target = dict(host="hive", socket=str(self.root / "rex.sock"), session="session:" + ZERO, block="block:" + ZERO)
        self.env = dict(os.environ)
        self.message = self.root / "message"
        self.message.write_text("first line\noperator input stays untouched · α")
        self.card = self.root / "card.json"
        self.decision = dict(id="deploy-7", title="Choose deployment timing", ask="Deploy the reviewed fix now?",
                             context="Tests passed; a restart interrupts current sessions.",
                             options=[dict(label="Deploy now", gain="Fix is available today", lose="Interrupt active sessions"),
                                      dict(label="Wait", gain="Keep active sessions intact", lose="Delay the fix")],
                             recommend="Wait until sessions finish; preserve current work.")
        self.card.write_text(json.dumps(self.decision))

    def argv(self, command, operation=None, target=True, **options):
        argv = [BIN, "boards", command]
        if operation is not None:
            argv.append(operation)
        opts = dict(store=self.store)
        if target:
            opts.update(self.target)
        opts.update(options)
        for k, v in opts.items():
            if v is True:
                argv.append("--" + k.replace("_", "-"))
            elif v is not None:
                argv.extend(["--" + k.replace("_", "-"), str(v)])
        return argv

    def invoke(self, command, operation=None, target=True, code=0, **options):
        r = subprocess.run(self.argv(command, operation, target, **options), capture_output=True, text=True, env=self.env, timeout=20)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        return json.loads(r.stdout) if r.stdout.startswith("{") else r.stdout

    def register(self):
        return self.invoke("seat", "register", owner="operator")

    def ask(self):
        return self.invoke("ask", sender=None, **{"from": "worker", "card_file": self.card})

    def append(self, **opts):
        return self.invoke("inbox", "append", **{"from": "worker", "message_file": self.message, **opts})

    def inspect(self):
        return self.invoke("state", "inspect", target=False)["state"]

    def test_complete_typed_decision_pinned_resolution_and_explicit_clear(self):
        self.register()
        self.ask()
        self.append()
        board = self.invoke("inbox", once=True, width=40)
        for value in ("DECISION", "Deploy the reviewed fix now?", "Gain:", "Loss:", "RECOMMENDATION", "RECENT ACTIVITY"):
            self.assertIn(value, board)
        self.assertLess(board.index("DECISION"), board.index("RECENT ACTIVITY"))
        generation = self.inspect()["generation"]
        self.invoke("inbox", "clear", generation=generation, reason="not until resolved", code=1)
        self.invoke("ask", **{"from": "operator", "resolve": "deploy-7", "answer": "Wait until tomorrow"})
        board = self.invoke("inbox", once=True)
        self.assertNotIn("DECISION ·", board)
        self.assertIn("Wait until tomorrow", board)
        self.assertIn("No open decisions recorded", board)
        self.invoke("inbox", "clear", generation=generation, reason="stale", code=1)
        generation = self.inspect()["generation"]
        self.invoke("inbox", "clear", generation=generation, reason="reviewed and exported")
        self.assertEqual(self.inspect()["seats"][0]["records"], [])
        self.invoke("seat", "clear", generation=generation + 1, reason="retire this seat")
        self.assertEqual(self.inspect()["seats"], [])

    def test_incomplete_duplicate_and_control_cards_never_saved(self):
        self.register()
        for broken in [dict(self.decision, context=" "), dict(self.decision, options=self.decision["options"][:1]),
                       dict(self.decision, recommend="\x1b[31muntrusted"), dict(self.decision, extra="unexpected")]:
            self.card.write_text(json.dumps(broken))
            self.invoke("ask", code=1, **{"from": "worker", "card_file": self.card})
        self.card.write_text(json.dumps(self.decision))
        self.ask()
        self.invoke("ask", code=1, **{"from": "worker", "card_file": self.card})
        self.invoke("ask", code=1, **{"from": "operator", "resolve": "missing", "answer": "no"})
        self.assertEqual(len(self.inspect()["seats"][0]["records"]), 1)
        self.message.write_text("DECISION-JSON:" + json.dumps(self.decision))
        self.append(code=1)

    def test_try_route_exact_tuple_and_fail_closed(self):
        opts = {"from": "worker", "message_file": self.message}
        p = self.invoke("try-route", code=3, **opts)
        self.assertEqual(p["outcome"], "not_registered")
        self.register()
        self.invoke("try-route", code=3, host="m5", **opts)
        self.invoke("try-route", code=3, socket=str(self.root / "other.sock"), **opts)
        self.invoke("try-route", code=3, session="session:" + OTHER, **opts)
        p = self.invoke("try-route", **opts)
        self.assertFalse(p["terminal_input_attempted"])
        self.assertEqual(p["application_consumption"], "not_assessed")
        self.assertEqual(self.inspect()["seats"][0]["records"][0]["body"], self.message.read_text())
        (self.store / "state.json").write_text("broken")
        p = self.invoke("try-route", code=1, **opts)
        self.assertNotEqual(p.get("outcome"), "not_registered")

    def test_private_files_symlinks_hardlinks_and_lock_contention(self):
        self.register()
        for name in ("lock", "state.json"):
            self.assertEqual((self.store / name).stat().st_mode & 0o777, 0o600)
        with (self.store / "lock").open("r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.invoke("seat", "inspect", code=1)
        self.store.chmod(0o755)
        self.invoke("seat", "inspect", code=1)
        self.store.chmod(0o700)
        os.link(self.store / "state.json", self.root / "alias")
        self.invoke("seat", "inspect", code=1)
        (self.root / "alias").unlink()
        os.rename(self.store / "state.json", self.root / "original")
        (self.store / "state.json").symlink_to(self.root / "original")
        self.invoke("seat", "inspect", code=1)

    def test_staged_crash_state_is_inspectable_but_never_promoted(self):
        self.register()
        before = (self.store / "state.json").read_bytes()
        (self.store / "state.next").write_text("private uncommitted intent")
        (self.store / "state.next").chmod(0o600)
        self.append(code=1)
        self.assertEqual((self.store / "state.json").read_bytes(), before)
        self.assertEqual((self.store / "state.next").read_text(), "private uncommitted intent")
        self.assertEqual(len(self.inspect()["seats"]), 1)

    def test_resolution_capacity_reserved_and_message_full_not_evicted(self):
        self.register()
        self.ask()
        # Public appends fill the bounded record count; one slot stays reserved for the decision's resolution.
        for _ in range(126):
            self.append()
        self.append(code=1)
        self.invoke("ask", **{"from": "operator", "resolve": "deploy-7", "answer": "Resolve at full capacity"})
        state = self.inspect()
        self.assertEqual(len(state["seats"][0]["records"]), 128)
        self.assertEqual(state["seats"][0]["records"][-1]["body"]["answer"], "Resolve at full capacity")

    def test_remap_preview_generation_collision_and_record_preservation(self):
        self.register()
        self.ask()
        old = self.inspect()["seats"][0]["target"]
        new = dict(old, block_id="block:" + OTHER, host="m1")
        mapping = self.root / "mapping.json"
        mapping.write_text(json.dumps([dict(old=old, new=new)]))
        p = self.invoke("state", "remap-preview", target=False, map_file=mapping)
        self.assertEqual(p["outcome"], "preview_only")
        self.assertEqual(self.inspect()["seats"][0]["target"], old)
        self.invoke("state", "remap-apply", target=False, map_file=mapping, generation=0, reason="stale", code=1)
        self.invoke("state", "remap-apply", target=False, map_file=mapping, generation=p["generation"], reason="surface verified separately")
        seat = self.inspect()["seats"][0]
        self.assertEqual(seat["target"], new)
        self.assertEqual(seat["records"][0]["body"], self.decision)
        self.invoke("try-route", code=3, **{"from": "worker", "message_file": self.message})
        self.invoke("seat", "register", owner="another")
        mapping.write_text(json.dumps([dict(old=new, new=old)]))
        self.invoke("state", "remap-preview", target=False, map_file=mapping, code=1)

    def test_input_stdin_limits_invalid_targets_and_duplicate_flags(self):
        self.register()
        argv = self.argv("inbox", "append", **{"from": "worker", "message_file": "-"})
        r = subprocess.run(argv, input="multiline\nα", text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.message.write_text("x" * 65537)
        self.append(code=1)
        self.invoke("seat", "inspect", block="block:abc", code=1)
        r = subprocess.run(self.argv("seat", "inspect") + ["--host", "m5"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("duplicate_option", r.stdout)


    def test_route_helper_preserves_unregistered_stdin_and_one_receipt(self):
        helper = os.environ.get("BOARDS_ROUTE_HELPER_BIN") or (BIN if Path(BIN).name == "boards-cli" else None)
        if helper is None:
            self.skipTest("BOARDS_ROUTE_HELPER_BIN selects standalone Zig ABI test bridge")
        argv = self.argv("route-then-copy-stdin", **{"from": "worker", "message_file": "-"})
        argv[0] = helper
        for payload in ("preserve bytes\nα", "", "a" * 65536):
            r = subprocess.run(argv, input=payload, text=True, capture_output=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(r.stdout, payload)  # No not_registered JSON and no consumed stdin.
        self.register()
        r = subprocess.run(argv, input="append once\nβ", text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["outcome"], "recorded")
        self.assertEqual(self.inspect()["seats"][0]["records"][0]["body"], "append once\nβ")
        (self.store / "state.json").write_text("bad state")
        r = subprocess.run(argv, input="NEVER FORWARD THIS", text=True, capture_output=True)
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("NEVER FORWARD THIS", r.stdout)

    def test_registered_stdin_deadline_and_signals_never_save_partial_bytes(self):
        self.register()
        command = self.argv("try-route", **{"from": "worker", "message_file": "-", "timeout_ms": 150})
        p = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        p.stdin.write("partial bytes with no EOF")
        p.stdin.flush()
        self.assertEqual(p.wait(timeout=3), 124)
        self.assertEqual(json.loads(p.stdout.read())["outcome"], "deadline_exceeded")
        p.stdin.close()
        p.stdout.close()
        p.stderr.close()
        self.assertEqual(self.inspect()["seats"][0]["records"], [])
        for sig in (signal.SIGINT, signal.SIGTERM):
            command[-1] = "2000"
            p = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            p.stdin.write("cancel before EOF")
            p.stdin.flush()
            time.sleep(.1)
            p.send_signal(sig)
            self.assertEqual(p.wait(timeout=3), 128 + sig)
            self.assertEqual(json.loads(p.stdout.read())["outcome"], "cancelled")
            p.stdin.close()
            p.stdout.close()
            p.stderr.close()
            self.assertEqual(self.inspect()["seats"][0]["records"], [])

    def test_named_host_partial_failures_never_omit_rows(self):
        config = self.root / "hosts.json"
        config.write_text("{}")
        # A contract fixture for root resolver/transport, not a claim of real SSH support.
        transport = self.root / "teerex-fixture"
        transport.write_text('#!' + sys.executable + '\n' + '''import json,sys
args=sys.argv[1:]
name=args[args.index('--host')+1]
if args[0]=='targets':
    if name=='m1': sys.exit(1)
    print(json.dumps({'schema_version':1,'host':{'host_id':name,'socket':'/tmp/'+name+'.sock'}}))
else:
    if name=='m5': sys.exit(4)
    print(json.dumps({'version':{'api_revision':13},'identity':{'host_id':'actual-hive','instance_id':'instance-test'},'rows':[]}))
''')
        transport.chmod(0o700)
        p = self.invoke("fleet", target=False, config=config, hosts="hive,m5,m1", teerex=transport, once=True, json=True, code=1)
        self.assertEqual(len(p["sources"]), 3)
        self.assertEqual([x["outcome"] for x in p["sources"]], ["observed", "unknown", "unknown"])
        self.assertEqual([x["configured_name"] for x in p["sources"]], ["hive", "m5", "m1"])
        self.assertEqual(p["rows"], [])


class RexBoardsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rex = os.environ.get("REX_BIN") or shutil.which("rex")
        if not cls.rex:
            raise unittest.SkipTest("REX_BIN required for disposable live tests")
        cls.tmp = tempfile.TemporaryDirectory(prefix="tboards-live-", dir="/tmp")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        cls.socket = cls.root / "rex.sock"
        cls.log = (cls.root / "server.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen([cls.rex, "server", "run", "--listen", "unix://" + str(cls.socket),
                                       "--restore=false", "--config", "/dev/null", "--state-dir", str(cls.root / "rex-state")],
                                      stdout=cls.log, stderr=cls.log)
        def stop():
            cls.server.terminate()
            try:
                cls.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.server.kill()
                cls.server.wait()
        cls.addClassCleanup(stop)
        for _ in range(100):
            if cls.socket.exists():
                break
            if cls.server.poll() is not None:
                raise RuntimeError((cls.root / "server.log").read_text())
            time.sleep(.05)
        cls.base = [cls.rex, "--autostart=false", "--server", "unix://" + str(cls.socket), "--timeout", "3s"]
        cls.version = json.loads(subprocess.check_output(cls.base + ["api", "call", "server.version"]))
        print("Disposable live Rex:", json.dumps(cls.version), flush=True)

    def test_real_terminal_enumeration_reports_and_offline_host_stay_unknown(self):
        tmp = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        store = root / "store"
        store.mkdir(mode=0o700)
        received = root / "received-input"
        code = ("import os,tty; tty.setraw(0); "
                f"f=open({str(received)!r},'ab',buffering=0); "
                "os.write(1,b'OPERATOR DRAFT: keep my words')\n"
                "while True: f.write(os.read(0,4096))")
        made = json.loads(subprocess.check_output(self.base + ["new", "--json", "--keep-open", "--shell=none", "--", sys.executable, "-c", code]))
        sid, bid = made["session_id"], made["initial_windows"][0]["block_ids"][0]
        for _ in range(100):
            if received.exists():
                break
            time.sleep(.02)
        targets = root / "targets.json"
        targets.write_text(json.dumps([dict(host="hive", server="unix://" + str(self.socket)),
                                       dict(host="m5", server="unix://" + str(root / "missing.sock"))]))
        env = dict(os.environ, PATH=str(Path(self.rex).parent) + os.pathsep + os.environ["PATH"],
                   REX_SERVER="unix:///poison.sock", REX_SESSION="session:poison")
        common = ["--store", str(store), "--host", "hive", "--socket", str(self.socket), "--session", sid, "--block", bid]
        subprocess.run([BIN, "boards", "fleet", "report"] + common + ["--owner", "worker", "--purpose", "live test", "--state", "working", "--detail", "hook_idle is not process death"], check=True, capture_output=True)
        view = subprocess.check_output(self.base + ["api", "call", "session.view", json.dumps(dict(session_id=sid))])
        r = subprocess.run([BIN, "boards", "fleet", "--store", str(store), "--targets-file", str(targets), "--once", "--json"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)  # one host unavailable, never an all-host success
        p = json.loads(r.stdout)
        self.assertEqual(len(p["sources"]), 2)
        self.assertEqual(p["sources"][1]["outcome"], "unknown")
        row = next(x for x in p["rows"] if x["target"]["block_id"] == bid)
        self.assertEqual(row["state"], "working")
        self.assertEqual(row["state_provenance"], "report")
        self.assertFalse(p["atomic_snapshot"])
        self.assertEqual(p["inference"], "none")
        if self.version["api_revision"] == 13:
            self.assertTrue(row["observation"]["present"], json.dumps(p))
        else:
            self.assertIsNone(row["observation"]["present"])
            self.assertEqual(p["sources"][0]["outcome"], "unknown")
        after = subprocess.check_output(self.base + ["api", "call", "session.view", json.dumps(dict(session_id=sid))])
        self.assertEqual(view, after)
        # Registering/appending to a real seat does not deliver terminal events or alter its structural view.
        subprocess.run([BIN, "boards", "seat", "register"] + common + ["--owner", "operator"], check=True, capture_output=True)
        message = root / "message"
        message.write_text("operator draft must stay untouched")
        subprocess.run([BIN, "boards", "try-route"] + common + ["--from", "worker", "--message-file", str(message)], check=True, capture_output=True)
        self.assertEqual(view, subprocess.check_output(self.base + ["api", "call", "session.view", json.dumps(dict(session_id=sid))]))
        capture = json.loads(subprocess.check_output(self.base + ["block", "call", "-s", sid, "-b", bid, "format", '{"format":"text"}']))
        self.assertIn("OPERATOR DRAFT: keep my words", capture["content"])
        self.assertNotIn("operator draft must", capture["content"])
        self.assertEqual(received.read_bytes(), b"")
        # Real visible foreground board refreshes after append and resolution; no daemon/TTY emulation.
        viewer = json.loads(subprocess.check_output(self.base + ["new", "--json", "--keep-open", "--shell=none", "--",
                            BIN, "boards", "inbox"] + common + ["--interval-ms", "500"]))
        viewer_sid, viewer_bid = viewer["session_id"], viewer["initial_windows"][0]["block_ids"][0]
        def wait_for(needle):
            last = ""
            for _ in range(100):
                capture = json.loads(subprocess.check_output(self.base + ["block", "call", "-s", viewer_sid, "-b", viewer_bid,
                                     "format", '{"format":"text","max_bytes":65536}']))
                last = capture["content"].split("TEEREX / INBOX")[-1]
                if needle in last:
                    return
                time.sleep(.05)
            self.fail("live renderer did not show " + needle + ": " + last)
        wait_for("0 waiting on you")
        decision = root / "live-card.json"
        decision.write_text(json.dumps(dict(id="live-test", title="Live decision", ask="Keep running?", context="Read-only refresh test",
                                           options=[dict(label="Go", gain="continue", lose="time"), dict(label="Wait", gain="review", lose="delay")], recommend="Review")))
        subprocess.run([BIN, "boards", "ask"] + common + ["--from", "worker", "--card-file", str(decision)], check=True, capture_output=True)
        wait_for("DECISION · Live decision")
        subprocess.run([BIN, "boards", "ask"] + common + ["--from", "operator", "--resolve", "live-test", "--answer", "Wait and review"], check=True, capture_output=True)
        wait_for("Wait and review")
        self.assertEqual(received.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
