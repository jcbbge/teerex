"""Public boards/seat/decision contracts. Live tests use only an owned disposable Rex."""
import fcntl
import json
import runpy
import re
import os
import pty
import select
import struct
import termios
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


def prepared_decision():
    return dict(id="cleanup-1", title="Remove superseded staging branch",
                ask="Delete the old staging branch now that its content has landed on main?",
                context="Branch was created by another owner; no open review references it.",
                options=[dict(label="Delete now", gain="Tidy branch list", lose="Unrecoverable if the owner still needs it", irreversible=True),
                         dict(label="Leave and notify owner", gain="Owner decides", lose="Stale branch stays a while")],
                recommend="Leave and notify owner; it is not ours to remove.",
                prepared=dict(checked="Content present on main by diff; no review or worktree uses the branch.",
                              if_no_answer="Branch stays; nothing is deleted.", default=None,
                              continuing="Writing the release notes, which do not depend on this.",
                              evidence=["main@abc1234 diff vs staging: empty", "~/rivet/work/<item>/notes.md#branches"]))


class BoardsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tboards-", dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / "store"
        self.store.mkdir(mode=0o700)
        self.target = dict(host="hive", socket=str(self.root / "rex.sock"), session="session:" + ZERO, block="block:" + ZERO)
        self.env = dict(os.environ, TEEREX_CLUTCH_DIR=str(self.root / "clutch"))
        self.message = self.root / "message"
        self.message.write_text("first line\noperator input stays untouched · α")
        self.card = self.root / "card.json"
        self.decision = dict(id="deploy-7", title="Choose deployment timing", ask="Deploy the reviewed fix now?",
                             context="Tests passed; a restart interrupts current sessions.",
                             options=[dict(label="Deploy now", gain="Fix is available today", lose="Interrupt active sessions"),
                                      dict(label="Wait", gain="Keep active sessions intact", lose="Delay the fix")],
                             recommend="Wait until sessions finish; preserve current work.")
        self.card.write_text(json.dumps(self.decision))
        self.native = self.root / "native-fixture"
        self.sent = self.root / "sent.txt"
        self.native.write_text("#!/usr/bin/env python3\nimport sys,json\nfrom pathlib import Path\n"
                               + "Path(" + repr(str(self.sent)) + ").write_text(sys.stdin.read())\n"
                               + "print(json.dumps(dict(outcome='events_acknowledged',terminal_input_attempted=True)))\n")
        self.native.chmod(0o700)

    def argv(self, command, operation=None, target=True, **options):
        argv = [BIN, "boards", command]
        if operation is not None:
            argv.append(operation)
        opts = dict(store=self.store)
        if command == "ask":
            opts["teerex"] = self.native
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
            # Held throughout: the bounded wait ends in a named, retry-safe busy refusal.
            busy = self.invoke("seat", "inspect", code=1)
            self.assertIn("board_store_busy", json.dumps(busy))
            # Released mid-wait: the overlapping caller proceeds instead of failing with EAGAIN.
            import threading
            threading.Timer(1.0, lambda: fcntl.flock(lock, fcntl.LOCK_UN)).start()
            self.invoke("seat", "inspect")
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

    def test_rotation_retains_history_and_open_decisions(self):
        self.register()
        self.ask()
        self.assertIn("Recommendation:", self.sent.read_text())
        for i in range(140):
            self.message.write_text("message-%03d" % i)
            self.append()
        state = self.inspect()
        self.assertEqual(len(state["seats"][0]["records"]), 108)
        self.assertEqual(state["seats"][0]["records"][0]["kind"], "decision")
        history = self.invoke("inbox", "inspect", archive=True, limit=128)["records"]
        self.assertEqual(len(history), 33)
        self.assertEqual({r["record"]["body"] for r in history}, {"message-%03d" % i for i in range(33)})
        self.invoke("ask", **{"from": "operator", "resolve": "deploy-7", "answer": "Resolve after rotation"})
        self.assertLessEqual(len(self.inspect()["seats"][0]["records"]), 128)
        for path in self.store.glob("archive-*.json"):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_ask_without_history_and_failure_does_not_record(self):
        args = self.argv("ask", store=None, **{"from": "worker", "card_file": self.card})
        r = subprocess.run(args, capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("DECISION [deploy-7]:", self.sent.read_text())
        self.assertFalse((self.store / "state.json").exists())
        self.register()
        self.native.write_text("#!/usr/bin/env python3\nimport json\nprint(json.dumps(dict(outcome='uncertain')))\nraise SystemExit(1)\n")
        self.invoke("ask", code=1, **{"from": "worker", "card_file": self.card})
        self.assertEqual(self.inspect()["seats"][0]["records"], [])

    def test_inline_card_fields_share_validation_and_return_id(self):
        command = self.argv("ask", store=None, **{"from": "worker", "title": "Inline", "ask": "Go?",
                                                "context": "Context", "recommend": "Wait", "id": "inline-7"})
        command += ["--option", "Go :: available :: interruption", "--option", "Wait :: preserve :: delay"]
        result = subprocess.run(command, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["decision_id"], "inline-7")
        self.assertIn("1. Go\n   Gain: available\n   Lose: interruption", self.sent.read_text())
        self.assertNotEqual(subprocess.run(command[:-2], env=self.env, capture_output=True).returncode, 0)

    def prepared_ask(self, value, code=0, history=False):
        self.card.write_text(json.dumps(value, ensure_ascii=False))
        result = self.invoke("ask", code=code, store=self.store if history else None,
                             deliver="paste", **{"from": "worker", "card_file": self.card})
        if code:
            self.assertFalse(result["terminal_input_attempted"])
            self.assertFalse(self.sent.exists(), "refusal must not invoke native send")
        return result

    def test_prepared_hold_card_exact_paste_and_inbox_sections(self):
        self.register()
        value = prepared_decision()
        self.prepared_ask(value, history=True)
        self.assertEqual(self.sent.read_text(), """DECISION [cleanup-1]: Remove superseded staging branch
Ask: Delete the old staging branch now that its content has landed on main?
Context: Branch was created by another owner; no open review references it.
Checked: Content present on main by diff; no review or worktree uses the branch.
If no answer: Branch stays; nothing is deleted. (default: hold)
Continuing: Writing the release notes, which do not depend on this.
Evidence: main@abc1234 diff vs staging: empty; ~/rivet/work/<item>/notes.md#branches
1. Delete now [irreversible]
   Gain: Tidy branch list
   Lose: Unrecoverable if the owner still needs it
2. Leave and notify owner
   Gain: Owner decides
   Lose: Stale branch stays a while
Recommendation: Leave and notify owner; it is not ours to remove.""")
        board = self.invoke("inbox", once=True, width=160)
        sections = ("CONTEXT", "CHECKED", "IF NO ANSWER", "CONTINUING", "EVIDENCE", "OPTIONS")
        self.assertEqual([board.index(k) for k in sections], sorted(board.index(k) for k in sections))
        for expected in (value["prepared"]["checked"], "(default: hold)", "1. Delete now [irreversible]",
                         "; ".join(value["prepared"]["evidence"])):
            self.assertIn(expected, board)
        self.assertEqual(self.inspect()["seats"][0]["records"][0]["body"], value)

    def test_prepared_irreversible_default_refused_before_delivery(self):
        value = prepared_decision()
        value["prepared"]["default"] = "Delete now"
        self.assertEqual(self.prepared_ask(value, 1)["reason"], "silent_default_irreversible")

    def test_prepared_reversible_default_and_empty_evidence(self):
        value = prepared_decision()
        value["prepared"]["default"] = "Leave and notify owner"
        value["prepared"]["evidence"] = []
        self.prepared_ask(value)
        self.assertIn("(default: Leave and notify owner)", self.sent.read_text())
        self.assertNotIn("Evidence:", self.sent.read_text())
        del value["prepared"]["evidence"]
        self.prepared_ask(value)
        self.assertNotIn("Evidence:", self.sent.read_text())

    def test_prepared_unknown_default_refused(self):
        for default in ("Wait", False, [], {}):
            with self.subTest(default=default):
                value = prepared_decision()
                value["prepared"]["default"] = default
                self.assertEqual(self.prepared_ask(value, 1)["reason"], "unknown_default_option")

    def test_prepared_irreversible_requires_json_boolean(self):
        for flag in ("yes", 1, 0, None, []):
            with self.subTest(flag=flag):
                value = prepared_decision()
                value["options"][0]["irreversible"] = flag
                self.assertEqual(self.prepared_ask(value, 1)["reason"], "invalid_irreversible_flag")
        value = prepared_decision()
        value["options"][0]["irreversible"] = False
        value["prepared"]["default"] = "Delete now"
        self.prepared_ask(value)
        self.assertNotIn("[irreversible]", self.sent.read_text())

    def test_prepared_evidence_must_be_bounded_single_line_references(self):
        for evidence in (["line\nbreak"], ["tab\tcharacter"], ["control\x7f"], ["é" * 513],
                         ["ref"] * 17, [""], [False], "ref"):
            with self.subTest(evidence=evidence):
                value = prepared_decision()
                value["prepared"]["evidence"] = evidence
                self.assertEqual(self.prepared_ask(value, 1)["reason"], "evidence_must_be_reference")
        value = prepared_decision()
        value["prepared"]["evidence"] = ["é" * 512] * 16
        self.prepared_ask(value)

    def test_prepared_optional_on_legacy_ask(self):
        self.register()
        self.ask()
        self.assertEqual(self.inspect()["seats"][0]["records"][0]["body"], self.decision)
        self.assertNotIn("Checked:", self.sent.read_text())

    def test_prepared_required_for_explicit_paste(self):
        self.assertEqual(self.prepared_ask(self.decision, 1)["reason"], "prepared_fields_required")

    def test_prepared_schema_and_text_refused(self):
        for field in ("checked", "if_no_answer", "default", "continuing"):
            value = prepared_decision()
            del value["prepared"][field]
            self.assertEqual(self.prepared_ask(value, 1)["reason"], "unexpected_schema_fields")
        for location, key in (("prepared", "urgency"), (None, "extra"), ("option", "extra")):
            value = prepared_decision()
            node = value["options"][0] if location == "option" else value[location] if location else value
            node[key] = "unexpected"
            self.assertEqual(self.prepared_ask(value, 1)["reason"], "unexpected_schema_fields")
        for field in ("checked", "if_no_answer", "continuing"):
            for invalid in (" ", "é" * 2049, "escape\x1b"):
                value = prepared_decision()
                value["prepared"][field] = invalid
                self.prepared_ask(value, 1)

    def test_prepared_retained_six_field_card_loads_renders_and_resolves(self):
        self.register()
        self.ask()
        retained = self.inspect()["seats"][0]["records"][0]["body"]
        self.assertEqual(set(retained), {"id", "title", "ask", "context", "options", "recommend"})
        board = self.invoke("inbox", once=True)
        self.assertIn("DECISION · Choose deployment timing", board)
        self.assertNotIn("CHECKED", board)
        self.invoke("ask", deliver="paste", **{"from": "operator", "resolve": "deploy-7", "answer": "Wait"})
        self.assertIn("No open decisions recorded", self.invoke("inbox", once=True))

    def test_prepared_rendered_card_bound_before_native_send(self):
        command = self.argv("ask", store=None, **{"from": "worker", "title": "title", "ask": "ask",
                                                "context": "context", "recommend": "recommend"})
        for number in range(8):
            command += ["--option", f"{number}" + "a" * 4095 + " :: " + "b" * 4096 + " :: " + "c" * 4096]
        result = subprocess.run(command, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["reason"], "rendered_card_too_large")
        self.assertFalse(self.sent.exists())

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
            command[-1] = "10000"
            reader, writer = os.pipe()
            with os.fdopen(reader, "rb") as source, os.fdopen(writer, "wb") as producer:
                with subprocess.Popen(command, stdin=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as p:
                    producer.write(b"cancel before EOF")
                    producer.flush()
                    # Consumption proves the helper reached its guarded stdin loop;
                    # a fixed sleep can signal Python before its handlers exist.
                    deadline = time.monotonic() + 3
                    while struct.unpack("I", fcntl.ioctl(source, termios.FIONREAD, struct.pack("I", 0)))[0]:
                        self.assertIsNone(p.poll(), "helper exited before reading partial stdin")
                        self.assertLess(time.monotonic(), deadline, "helper never consumed partial stdin")
                        time.sleep(.01)
                    p.send_signal(sig)
                    out, err = p.communicate(timeout=3)
                    self.assertEqual(p.returncode, 128 + sig, out + err)
                    self.assertEqual(json.loads(out)["outcome"], "cancelled")
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
    if '--jobs-registry' in args:
        assert args[args.index('--jobs-registry')+1]=='/command-host/'+name+'/jobs'
    if name=='m5': sys.exit(4)
    print(json.dumps({'version':{'api_revision':13},'identity':{'host_id':'actual-hive','instance_id':'instance-test'},'rows':[], 'registrations':[]}))
''')
        transport.chmod(0o700)
        p = self.invoke("fleet", target=False, config=config, hosts="hive,m5,m1", teerex=transport, once=True, json=True, code=1)
        self.assertEqual(len(p["sources"]), 3)
        self.assertEqual([x["outcome"] for x in p["sources"]], ["observed", "unknown", "unknown"])
        self.assertEqual([x["configured_name"] for x in p["sources"]], ["hive", "m5", "m1"])
        self.assertEqual(p["rows"], [])
        # These paths deliberately do not exist locally: each belongs to its selected command host.
        command = self.argv("fleet", target=False, config=config, hosts="hive,m5,m1", teerex=transport, once=True, json=True)
        result = subprocess.run(command + ["--jobs-registry", "hive=/command-host/hive/jobs",
                                          "--jobs-registry", "m5=/command-host/m5/jobs"],
                                env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual([x["outcome"] for x in json.loads(result.stdout)["sources"]], ["observed", "unknown", "unknown"])

class CallsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tcalls-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.log = self.root / "calls"
        self.env = dict(os.environ, TEEREX_CLUTCH_DIR=str(self.root / "clutch"), TEEREX_CALL_LOG_DIR=str(self.log))

    def call(self, *args, **kw):
        return subprocess.run([BIN, *args], env=self.env, capture_output=True, text=True, timeout=15, **kw)

    def test_provider_credentials_in_caller_metadata_never_persist(self):
        enabled = self.call("boards", "friction", "enable", "--log-dir", str(self.log), "--for-days", "1", "--scope", "all")
        self.assertEqual(enabled.returncode, 0, enabled.stdout + enabled.stderr)
        for prefix in ("sk-", "ghp_", "github_pat_", "xoxb-"):
            token = prefix + "a" * 28
            self.env.update(TEEREX_CALLER=token, AGENT_NAME=token)
            self.assertEqual(self.call("--version").returncode, 0)
            for segment in self.log.glob("*.jsonl"):
                self.assertNotIn(token, segment.read_text())
        self.assertTrue(all(r["caller"]["agent_name"] is None for r in self.records() if r["phase"] == "start" and r["verb"] == "--version"))

    def records(self):
        return [json.loads(line) for line in (self.log / "calls.jsonl").read_text().splitlines()]

    def test_success_usage_refusal_and_uncertain_metadata_never_store_payload(self):
        self.assertEqual(self.call("--version").returncode, 0)
        self.assertNotEqual(self.call("ask", "--SECRET_PAYLOAD").returncode, 0)
        rex = self.root / "rex"
        rex.write_text("#!" + sys.executable + "\nimport json,time\n"
                       "def emit(v): print(json.dumps(v),flush=True)\n"
                       "emit({'event':'source','source':{'rex_version':'injected','platform':'test','api_revision':13}})\n"
                       "emit({'event':'attempt','stage':'paste'})\n"
                       "emit({'event':'ack','stage':'paste'})\n"
                       "emit({'event':'attempt','stage':'enter'})\n"
                       "emit({'event':'failed','reason':'enter_call_failed'})\n")
        rex.chmod(0o700)
        message = self.root / "message"
        message.write_text("SECRET_BODY")
        send = ["--rex", str(rex), "send", "--socket", str(self.root / "fixture.sock"),
                "--session", "session:" + ZERO, "--block", "block:" + ZERO, "--from", "worker",
                "--message-file", str(message)]
        result = self.call(*send)
        self.assertEqual(json.loads(result.stdout)["outcome"], "uncertain", result.stdout + result.stderr)
        records = self.records()
        self.assertEqual(len(records), 6)
        starts = [r for r in records if r["phase"] == "start"]
        ends = [r for r in records if r["phase"] == "end"]
        self.assertEqual(len(starts), 3)
        self.assertEqual(ends[-1]["exit"], 1)
        self.assertIn("block:" + ZERO, starts[-1]["ids"])
        self.assertIn("--message-file", starts[-1]["flags"])
        self.assertTrue(all(type(r["elapsed_ms"]) is int for r in ends))
        self.assertEqual({(r["pid"], r["start_at"]) for r in starts}, {(r["pid"], r["start_at"]) for r in ends})
        raw = (self.log / "calls.jsonl").read_text()
        for secret in ("SECRET_BODY", "SECRET_PAYLOAD", "fixture.sock"):
            self.assertNotIn(secret, raw)
        self.assertEqual(self.log.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.log / "calls.jsonl").stat().st_mode & 0o777, 0o600)
        board = self.call("boards", "calls", "--once", "--json", "--limit", "2")
        self.assertEqual(board.returncode, 0, board.stderr)
        self.assertEqual(len(json.loads(board.stdout)["calls"]), 2)

    def test_rotation_and_private_file_refusal(self):
        self.call("--version")
        record = dict(self.records()[0], padding="x" * 1000)
        # Seed a valid full segment rather than running thousands of commands.
        raw = (json.dumps(record) + "\n").encode()
        path = self.log / "calls.jsonl"
        prefix = raw * ((1048576 - 8192) // len(raw))
        filler = dict(record, padding="")
        filler["padding"] = "x" * (1048576 - len(prefix) - len((json.dumps(filler) + "\n").encode()))
        before = prefix + (json.dumps(filler) + "\n").encode()
        self.assertEqual(len(before), 1048576)
        path.write_bytes(before)
        self.call("--version")
        archive = list(self.log.glob("calls-*.jsonl"))
        self.assertEqual(len(archive), 1)
        self.assertTrue(archive[0].read_bytes().startswith(before))
        self.assertLessEqual(path.stat().st_size, 1048576)
        path.chmod(0o644)
        result = self.call("--version")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def foreign_target(self, program):
        executable = self.root / "foreign"
        executable.write_text("#!" + sys.executable + " -I\n" + program)
        executable.chmod(0o700)
        config = self.root / "hosts.json"
        config.write_text(json.dumps(dict(schema_version=1, hosts=dict(fixture=dict(
            host_id="fixture", transport="local", home=str(self.root), platform="linux-x86_64",
            socket=str(self.root / "rex.sock"), rex="/bin/false", teerex=str(executable), store=str(self.root / "store"))))))
        return ["--config", str(config), "--host", "fixture", "observe"]

    def test_exec_pid_preserved_and_foreign_exit_remains_unknown(self):
        command = self.foreign_target("import os,json\nprint(json.dumps(dict(pid=os.getpid())),flush=True)\nraise SystemExit(23)\n")
        proc = subprocess.Popen([BIN, *command], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        output, error = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 23, error)
        self.assertEqual(json.loads(output)["pid"], proc.pid)
        self.assertEqual(len(self.records()), 1)
        board = self.call("boards", "calls", "--once", "--json")
        rows = json.loads(board.stdout)["calls"]
        row = next(r for r in rows if r["pid"] == proc.pid)
        self.assertEqual(row["outcome"], "unknown")
        self.assertIsNone(row["exit"])

    def test_signal_passthrough_keeps_foreign_pid_output_and_exit(self):
        command = self.foreign_target("import os,signal,json\nsignal.signal(signal.SIGTERM,lambda *_:exit(23))\nprint(json.dumps(dict(pid=os.getpid())),flush=True)\nsignal.pause()\n")
        proc = subprocess.Popen([BIN, *command], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            ready = proc.stdout.readline()
            self.assertEqual(json.loads(ready)["pid"], proc.pid)
            proc.send_signal(signal.SIGTERM)
            output, error = proc.communicate(timeout=10)
            self.assertEqual(proc.returncode, 23, error)
            self.assertEqual(output, "")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            proc.stdout.close()
            proc.stderr.close()

    def test_native_logging_needs_no_python_and_helper_imports_are_isolated(self):
        self.env["PATH"] = str(self.root / "no-python")
        result = self.call("--version")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual([r["phase"] for r in self.records()], ["start", "end"])
        self.env["PATH"] = os.environ["PATH"]
        sentinel = self.root / "POISON_RAN"
        (self.root / "json.py").write_text("from pathlib import Path\nPath(" + repr(str(sentinel)) + ").touch()\nraise RuntimeError('poison')\n")
        result = self.call("targets", "resolve", "--config", str(self.root / "missing-config"), "--host", "fixture", cwd=self.root)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(sentinel.exists())

    def test_numeric_range_help_and_errors_stay_compact(self):
        cases = [
            (["boards", "calls"], "--limit", 1, 128),
            (["boards", "calls"], "--interval-ms", 500, 60000),
            (["boards", "inbox", "inspect"], "--limit", 1, 1024),
            (["boards", "try-route"], "--draft-wait-ms", 0, 55000),
            (["boards", "try-route"], "--timeout-ms", 100, 115000),
            (["ask"], "--draft-wait-ms", 0, 55000),
            (["boards", "inbox"], "--width", 32, 160),
            (["boards", "inbox"], "--interval-ms", 500, 60000),
            (["boards", "fleet"], "--width", 32, 160),
            (["boards", "fleet"], "--interval-ms", 500, 60000),
        ]
        for command, flag, lower, upper in cases:
            with self.subTest(command=command, flag=flag):
                help_text = self.call(*command, "--help")
                self.assertEqual(help_text.returncode, 0, help_text.stderr)
                self.assertIn(flag + " " + str(lower) + ".." + str(upper), help_text.stdout)
                self.assertLess(len(help_text.stdout.encode()), 8192)
                for value in (str(lower), str(upper)):
                    accepted = self.call(*command, flag, value, "--help")
                    self.assertEqual(accepted.returncode, 0, accepted.stderr)
                for value in (str(lower - 1), str(upper + 1), "not-an-integer"):
                    refused = self.call(*command, flag, value, "--help")
                    self.assertEqual(refused.returncode, 2, refused.stderr)
                    self.assertIn("expected integer in " + str(lower) + ".." + str(upper), refused.stderr)
                    self.assertLess(len(refused.stderr.encode()), 8192)

    def test_cross_host_calls_show_unavailable_sources(self):
        fixture = self.root / "remote"
        fixture.write_text("#!" + sys.executable + "\nimport json,sys\n"
                           "host=sys.argv[sys.argv.index('--host')+1]\n"
                           "if host=='m1': raise SystemExit(1)\n"
                           "print(json.dumps(dict(calls=[dict(at=1,host=host,verb='send',subverb=None,outcome='uncertain',elapsed_ms=2,exit=1)])))\n")
        fixture.chmod(0o700)
        result = self.call("boards", "calls", "--once", "--json", "--config", str(self.root / "config"),
                           "--hosts", "hive,m5,m1", "--teerex", str(fixture))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual([s["outcome"] for s in payload["sources"]], ["observed", "observed", "unknown"])
        self.assertEqual({r["command_host"] for r in payload["calls"]}, {"hive", "m5"})


class CompactFleetTest(unittest.TestCase):
    def test_state_order_and_history(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('dashboard', ROOT / 'items/boards/dashboard.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        def row(state, present=True):
            return dict(target=dict(block_id=state, host="hive"), observation=dict(present=present, label=state),
                        program_status=dict(records=[dict(state=state, age_ms=0)]))
        rows = [row('idle'), row('working'), row('error'), row('blocked'), row('done'), row('idle', False)]
        snapshot = dict(rows=rows)
        self.assertEqual([module.summary(r, 0)['state'] for r in module.fleet_rows(snapshot, 0)], ['blocked', 'error', 'working', 'idle'])
        self.assertEqual(len(module.fleet_rows(snapshot, 0, True)), 6)
        busy = row('idle')
        busy['agent_state'] = dict(state='working')
        self.assertEqual(module.summary(busy, 0)['state'], 'working')
        self.assertIn('working [screen]', module.cells(busy, 0))
        busy['report'] = dict(state='completed', at=1)
        self.assertEqual(module.fleet_rows(dict(rows=[busy]), 0), [busy])


class StatusTest(unittest.TestCase):
    def test_rex_timestamp_fractional_precision_on_python39(self):
        status = runpy.run_path(str(ROOT / "items/boards/boards.py"))["status_evidence"]
        status.__globals__["stamp"] = lambda: 946684802000  # 2000-01-01T00:00:02Z
        for digits in range(10):
            fraction = "." + "123456789"[:digits] if digits else ""
            for clock, zone in (("00", "Z"), ("00", "+00:00"), ("18", "-06:00")):
                day = "1999-12-31" if clock == "18" else "2000-01-01"
                timestamp = day + "T" + clock + ":00:00" + fraction + zone
                with self.subTest(timestamp=timestamp):
                    record = status(dict(records=[dict(state="done", updated_at=timestamp)]))["records"][0]
                    millis = int(("123456789"[:digits] + "000")[:3]) if digits else 0
                    self.assertEqual(record["age_ms"], 2000 - millis)
        self.assertIsNone(status(dict(records=[dict(state="done", updated_at="unknown")]))["records"][0]["age_ms"])


class RexBoardsTest(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        private = self.root / ("clutch-" + str(time.monotonic_ns()))
        override = patch.dict(os.environ, TEEREX_CLUTCH_DIR=str(private))
        override.start()
        self.addCleanup(override.stop)

    @classmethod
    def setUpClass(cls):
        cls.rex = os.environ.get("REX_BIN") or shutil.which("rex")
        if not cls.rex:
            raise unittest.SkipTest("REX_BIN required for disposable live tests")
        cls.tmp = tempfile.TemporaryDirectory(prefix="tboards-live-", dir="/tmp")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        cls.socket = cls.root / "rex.sock"
        cls.bin = cls.root / "bin"
        cls.bin.mkdir()
        leaf = cls.bin / "leaf"
        leaf.write_text("#!" + sys.executable + "\nimport sys,time\nfrom pathlib import Path\nPath(sys.argv[-1]).parent.joinpath('leaf-argv').write_text(repr(sys.argv[1:]))\ntime.sleep(120)\n")
        leaf.chmod(0o700)
        cls.log = (cls.root / "server.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen([cls.rex, "server", "run", "--listen", "unix://" + str(cls.socket),
                                       "--restore=false", "--config", "/dev/null", "--state-dir", str(cls.root / "rex-state")],
                                      stdout=cls.log, stderr=cls.log,
                                      env=dict(os.environ, TEEREX_CLUTCH_DIR=str(cls.root / "server-clutch"), PATH=str(cls.bin) + os.pathsep + os.environ["PATH"]))
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

    def test_prepared_paste_live_acks_and_refusal_leaves_cat_unchanged(self):
        root = self.root / ("prepared-" + str(time.monotonic_ns()))
        root.mkdir()
        env = dict(os.environ, PATH=str(Path(self.rex).parent) + os.pathsep + os.environ["PATH"])
        sid = json.loads(subprocess.check_output(self.base + ["api", "call", "session.create", "{}"]))["session_id"]
        self.addCleanup(subprocess.run, self.base + ["api", "call", "session.destroy", json.dumps(dict(session_id=sid))],
                        capture_output=True)
        def cli(*args, code=0):
            result = subprocess.run([BIN, *args], env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, code, result.stdout + result.stderr)
            return json.loads(result.stdout)
        made = cli("surfaces", "open", "--socket", str(self.socket), "--session", sid,
                   "--layout", "tab", "--label", "prepared decision cat", "--", "/bin/sh", "-c",
                   "stty -echo && printf 'CAT READY\\n' && exec /bin/cat")
        bid = made["actual"]["block_id"]
        def capture():
            return cli("observe", "--socket", str(self.socket), "--session", sid, "--block", bid,
                       "--max-bytes", "65536")
        # Observe readiness only after stty disables echo; otherwise the tty's echo
        # can satisfy the baseline before cat writes its second copy after Enter.
        for _ in range(100):
            if "CAT READY" in capture()["capture"]["content"]:
                break
            time.sleep(.02)
        else:
            self.fail("non-echoing cat did not become ready")
        decision = root / "card.json"
        value = prepared_decision()
        decision.write_text(json.dumps(value))
        command = ["ask", "--host", "hive", "--socket", str(self.socket), "--session", sid,
                   "--block", bid, "--from", "worker", "--card-file", str(decision), "--deliver", "paste"]
        receipt = cli(*command)
        self.assertEqual(receipt["outcome"], "events_acknowledged")
        self.assertTrue(receipt["paste"]["acknowledged"])
        self.assertTrue(receipt["enter"]["acknowledged"])
        # Read through observe until cat has emitted the complete final field.
        complete = "".join(("Recommendation: " + value["recommend"]).split())
        for _ in range(100):
            before = capture()
            rendered = json.dumps(before, ensure_ascii=False)
            if complete in "".join(before["capture"]["content"].split()) and "[irreversible]" in rendered:
                break
            time.sleep(.02)
        else:
            self.fail(rendered)
        self.assertEqual(before["capture"]["content"].count("FROM worker: DECISION [cleanup-1]"), 1)
        for expected in ("Checked:", "If no answer:", "(default: hold)", "Continuing:", "Evidence:"):
            self.assertIn(expected, rendered)
        value["prepared"]["default"] = "Delete now"
        decision.write_text(json.dumps(value))
        refused = cli(*command, code=1)
        self.assertEqual(refused["reason"], "silent_default_irreversible")
        self.assertFalse(refused["terminal_input_attempted"])
        # Terminal text is stable even though observe includes fresh collection metadata.
        after = capture()
        self.assertEqual(after["capture"]["content"], before["capture"]["content"])
        closed = cli("surfaces", "close", "--socket", str(self.socket), "--session", sid, "--pane", bid)
        self.assertEqual(closed["outcome"], "closed_and_absent")

    def dashboard_fixture(self, named=False, busy=False):
        root = self.root / ("dashboard-" + str(time.monotonic_ns()))
        root.mkdir()
        for directory in ("store", "jobs", "agents", "bin"):
            (root / directory).mkdir(mode=0o700)
        env = dict(os.environ, TEEREX_CLUTCH_DIR=str(root / "clutch"), PATH=str(root / "bin") + os.pathsep + str(Path(self.rex).parent) + os.pathsep + os.environ["PATH"],
                   TEEREX_CALL_LOG_DIR=str(root / "calls"), REX_SERVER="unix:///poison.sock", REX_SESSION="session:poison", REX_BLOCK="block:poison")
        def invoke(*args):
            result = subprocess.run([BIN, *args], env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)
        session = json.loads(subprocess.check_output(self.base + ["api", "call", "session.create", '{"label":"dashboard fixture"}']))["session_id"]
        self.addCleanup(lambda: subprocess.run(self.base + ["api", "call", "session.destroy", json.dumps(dict(session_id=session))], capture_output=True))
        def pane(label, osc=False):
            script = ("print('\\x1b]7501;state=working:app=fixture\\x1b\\\\',flush=True); " if osc else "") + "import time; time.sleep(120)"
            if busy and label == 'dash-agent-alpha':
                script = "print('Claude Code\\n● Running 1 shell command…\\n✽ Galloping… (10s)\\n\\x1b[38;2;153;153;153m❯\\xa0\\x1b[0m',flush=True); " + script
            return invoke("surfaces", "open", "--socket", str(self.socket), "--session", session,
                          "--layout", "tab", "--label", label, "--", sys.executable, "-c", script)["actual"]["block_id"]
        anchor, alpha, beta = pane("dashboard-anchor"), pane("dash-agent-alpha"), pane("dash-agent-beta", True)
        document = root / "brief.txt"
        document.write_text("private brief for the selected agent")
        for number, block in enumerate((alpha, beta), 1):
            invoke("jobs", "track", "--registry", str(root / "jobs"), "--socket", str(self.socket),
                   "--session", session, "--block", block, "--owner", "operator", "--kind", "agent", "--purpose", "dashboard acceptance",
                   "--deadline-unix-ms", str(int(time.time()*1000)+120000), "--cleanup", "manual")
            record = dict(schema_version=1, launch_id=str(number)*32, token="NEVER_SHOW_THIS_TOKEN", name="dash-agent-" + ("alpha" if number == 1 else "beta"),
                          owner="operator", purpose="dashboard acceptance", phase="brief_submitted", created_at=int(time.time()*1000),
                          target=dict(host="hive", server="unix://"+str(self.socket), session_id=session, block_id=block), brief_file=str(document))
            path = root / "agents" / ("agents-" + record["launch_id"] + ".json")
            path.write_text(json.dumps(record))
            path.chmod(0o600)
        targets = root / "targets.json"
        targets.write_text(json.dumps([dict(host="hive", server="unix://" + str(self.socket))]))
        args = [BIN, "boards", "fleet", "--store", str(root / "store"), "--jobs-registry", str(root / "jobs"),
                "--agents-registry", str(root / "agents"), "--dashboard-session", session, "--dashboard-block", anchor,
                "--dashboard-host", "hive", "--interval-ms", "500", "--detail"]
        if named:
            config = root / "hosts.json"
            config.write_text(json.dumps(dict(schema_version=1, hosts=dict(hive=dict(host_id="hive", transport="local", home=str(root),
                platform="linux-x86_64", socket=str(self.socket), rex=self.rex, teerex=BIN, store=str(root / "store"))))))
            args += ["--config", str(config), "--hosts", "hive"]
        else:
            args += ["--targets-file", str(targets)]
        def view():
            return json.loads(subprocess.check_output(self.base + ["api", "call", "session.view", json.dumps(dict(session_id=session))]))
        return root, env, args, session, anchor, alpha, beta, view

    def keyboard_dashboard(self, args, env, width=160):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 30, width, 0, 0))
        before = termios.tcgetattr(slave)
        process = subprocess.Popen(args, env=env, stdin=slave, stdout=slave, stderr=slave)
        output = bytearray()
        def stop():
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            os.close(master)
            os.close(slave)
        self.addCleanup(stop)
        def wait_for(needle, timeout=12, *, selected=None):
            end = time.monotonic()+timeout
            while time.monotonic() < end:
                screen = bytes(output).rsplit(b"\x1b[2J\x1b[H", 1)[-1]
                selection = selected is None or ("Selected: " + selected + " | ").encode() in screen
                if needle.encode() in screen and selection and screen.endswith(b"\x1b[J"):
                    return screen.decode(errors="replace")
                if select.select([master], [], [], .1)[0]:
                    try:
                        output.extend(os.read(master, 65536))
                    except OSError:
                        break
                if process.poll() is not None:
                    break
            self.fail("dashboard did not show " + needle + ": " + bytes(output)[-6000:].decode(errors="replace"))
        return process, master, slave, before, output, wait_for

    def finish_dashboard(self, process, master, slave, saved, output, expected=0):
        # macOS PTYs have a small output queue: keep consuming redraws while
        # waiting, just as a terminal emulator does, so exit cannot block in write.
        deadline = time.monotonic() + 10
        while process.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], .1)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
        self.assertEqual(process.wait(timeout=1), expected)
        restored = termios.tcgetattr(slave)
        # Darwin marks canonical input pending for reprocessing when cbreak is
        # restored. This kernel-maintained bit is not a changed terminal setting.
        pending = getattr(termios, "PENDIN", 0) if sys.platform == "darwin" else 0
        restored[3] &= ~pending
        saved = list(saved)
        saved[3] &= ~pending
        self.assertEqual(restored, saved)

    def test_detached_fleet_marks_placement_and_presents_from_its_session(self):
        root, env, args, session, anchor, alpha, beta, view = self.dashboard_fixture()
        args.remove('--detail')
        env['HOME'] = str(root)
        pad = root / '.local/state/teerex/scratch' / session / (beta + '.md')
        pad.parent.mkdir(parents=True)
        pad.write_text('# beta\nPurpose: detached work\nIntent: verify\nUpdated: 2026-11-13T00:00:00Z\n## Now\n- [ ] Check detached scratchpad\n## Done\n- [x] Launch\n')
        target = dict(session_id=session, block_id=beta)
        self.api_detach = subprocess.check_output(self.base + ['api', 'call', 'session.detach_block', json.dumps(target)])
        before = view()
        child = json.loads(subprocess.check_output(self.base + ['block', 'call', '-s', session, '-b', beta, 'process', '{}']))['child']
        process, master, slave, saved, output, wait_for = self.keyboard_dashboard(args, env, 60)
        wait_for('[detached]')
        wait_for('Check detached scratchpad')
        wait_for('1/2')
        os.write(master, b'/dash-agent-beta\rp')
        wait_for('Action finished')
        described = json.loads(subprocess.check_output(self.base + ['api', 'call', 'session.describe_block', json.dumps(target)]))['block']
        self.assertEqual(described['placement'], 'placed')
        current = json.loads(subprocess.check_output(self.base + ['block', 'call', '-s', session, '-b', beta, 'process', '{}']))['child']
        self.assertEqual(current, child)
        self.assertEqual(len(view()['windows']), len(before['windows']))
        os.write(master, b'q')
        self.finish_dashboard(process, master, slave, saved, output)

    def test_compact_fleet_busy_claude_without_scratchpad_is_working(self):
        root, env, args, session, anchor, alpha, beta, view = self.dashboard_fixture(busy=True)
        args.remove('--detail')
        process, master, slave, saved, output, wait_for = self.keyboard_dashboard(args, env, 60)
        wait_for('2 agents working')
        os.write(master, b'/dash-agent-alpha\ri')
        wait_for('"working", "draft_present"')
        os.write(master, b'q')
        self.finish_dashboard(process, master, slave, saved, output)

    def test_compact_fleet_wrap_scratchpad_history_and_inspect(self):
        for width in (60, 120):
            root, env, args, session, anchor, alpha, beta, view = self.dashboard_fixture()
            args.remove('--detail')
            env['HOME'] = str(root)
            directory = root / '.local/state/teerex/scratch' / session
            directory.mkdir(parents=True)
            work = 'Verify every character of this current task survives wrapping in a narrow sixty column side pane'
            (directory / (alpha + '.md')).write_text('# alpha\nPurpose: SECRET_PURPOSE\nIntent: finish\nUpdated: 2026-11-13T00:00:00Z\n\n## Now\n- [ ] ' + work + '\n## To-do\n- [ ] Later task\n## Done\n- [x] Finished task\n')
            record = json.loads((root / 'agents' / ('agents-' + '1'*32 + '.json')).read_text())
            record.update(launch_id='3'*32, name='history-agent', target=dict(record['target'], block_id='block:'+ZERO))
            path = root / 'agents' / ('agents-' + '3'*32 + '.json')
            path.write_text(json.dumps(record))
            path.chmod(0o600)
            process, master, slave, saved, output, wait_for = self.keyboard_dashboard(args, env, width)
            screen = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', wait_for('1/3'))
            plain = ' '.join(screen.split())
            self.assertIn(work, plain)
            self.assertNotIn('history-agent', screen)
            for forbidden in ('session:', 'block:', 'OWNER', 'SECRET_PURPOSE', 'OSC', 'Receipt:', 'brief_submitted', 'report', 'operator'):
                self.assertNotIn(forbidden, screen)
            for line in screen.splitlines()[1:-1]:
                self.assertLessEqual(len(line), width)
            os.write(master, b'/dash-agent-alpha\r ')
            wait_for('Later task')
            os.write(master, b'i')
            wait_for('session:')
            os.write(master, b'i/a\r')
            os.write(master, b'/\ra')
            wait_for('history-agent')
            os.write(master, b'q')
            self.finish_dashboard(process, master, slave, saved, output)

    def test_keyboard_dashboard_focus_present_document_and_json_compatibility(self):
        root, env, args, session, anchor, alpha, beta, view = self.dashboard_fixture(named=True)
        initial = view()
        registry_before = {p.name: p.read_bytes() for p in (root / "agents").iterdir()}
        once = subprocess.run(args + ["--once", "--json"], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(once.returncode, 0, once.stderr)
        payload = json.loads(once.stdout)
        self.assertEqual(set(payload), {"schema_version", "kind", "evaluated_at", "sources", "rows", "inference", "completion", "atomic_snapshot", "scope"})
        self.assertTrue(all("dashboard" not in r for r in payload["rows"]))
        process, master, slave, saved, output, wait_for = self.keyboard_dashboard(args, env)
        wait_for("LAST CALL")
        # Require the committed exact-name filter and selection in the same frame.
        # An earlier screen can already contain a name before its input is consumed.
        os.write(master, b"/dash-agent-alpha\r")
        wait_for("Filter: dash-agent-alpha", selected="dash-agent-alpha")
        os.write(master, b"/dash-agent-beta\r")
        selected_screen = wait_for("Filter: dash-agent-beta", selected="dash-agent-beta")
        # Clock-derived OSC age may be unknown; that is a documented display value.
        self.assertRegex(selected_screen, r"dash-agent-beta[^\r\n]+working \[OSC\]\s+(?:\d+s|\?)\s+\d{2}:\d{2}:\d{2}")
        self.assertEqual(initial, view(), "selection/filtering must not focus or move any pane")
        os.write(master, b"\r")
        wait_for("focus exit=0")
        focused = view()
        self.assertTrue(any(w["window_id"] == focused["active_window_id"] and w.get("focused_block_id") == beta for w in focused["windows"]))
        os.write(master, b"p")
        wait_for("present exit=0")
        presented = view()
        def window_of(snapshot, block):
            return next(w["window_id"] for w in snapshot["windows"] for layer in w["layers"] for b in layer["blocks"] if b["block_id"] == block)
        self.assertEqual(window_of(presented, anchor), window_of(presented, beta))
        os.write(master, b"o")
        wait_for("surfaces open exit=0")
        end = time.monotonic()+5
        while not (root / "leaf-argv").exists() and time.monotonic() < end:
            time.sleep(.02)
        self.assertEqual((root / "leaf-argv").read_text(), repr(["open", str(root / "brief.txt")]))
        opened = view()
        self.assertEqual(sum(len(layer["blocks"]) for w in opened["windows"] for layer in w["layers"]), 4)
        self.assertTrue(any(b.get("label") == "fleet document" for w in opened["windows"] for layer in w["layers"] for b in layer["blocks"]))
        os.write(master, b"rq")
        self.finish_dashboard(process, master, slave, saved, output)
        self.assertEqual(view(), opened, "quitting the dashboard must leave all panes alone")
        self.assertNotIn(b"NEVER_SHOW_THIS_TOKEN", output)
        self.assertIn(b"working [OSC]", output)
        self.assertEqual(registry_before, {p.name: p.read_bytes() for p in (root / "agents").iterdir()})

    def test_keyboard_dashboard_refuses_cross_session_and_handles_empty_filter(self):
        root, env, args, session, anchor, alpha, beta, view = self.dashboard_fixture()
        other = json.loads(subprocess.check_output(self.base + ["new", "--json", "--keep-open", "--shell=none", "--", sys.executable, "-c", "import time; time.sleep(120)"]))
        other_session, other_block = other["session_id"], other["initial_windows"][0]["block_ids"][0]
        self.addCleanup(lambda: subprocess.run(self.base + ["api", "call", "session.destroy", json.dumps(dict(session_id=other_session))], capture_output=True))
        args[args.index("--dashboard-session")+1] = other_session
        args[args.index("--dashboard-block")+1] = other_block
        before = view()
        process, master, slave, saved, output, wait_for = self.keyboard_dashboard(args, env)
        wait_for("LAST CALL")
        os.write(master, b"/dash-agent-beta\rp")
        wait_for("present_requires_dashboard_on_same_server_and_session")
        self.assertEqual(view(), before)
        os.write(master, b"/no-such-agent\r\r")
        wait_for("no selected row")
        os.write(master, b"/\rq")
        self.finish_dashboard(process, master, slave, saved, output)

    def test_keyboard_dashboard_missing_metadata_refuses_actions_and_restores_on_signal(self):
        root, env, args, session, anchor, alpha, beta, view = self.dashboard_fixture()
        for flag in ("--jobs-registry", "--agents-registry"):
            at = args.index(flag)
            del args[at:at+2]
        before = view()
        process, master, slave, saved, output, wait_for = self.keyboard_dashboard(args, env)
        wait_for("LAST CALL")
        os.write(master, b"/dash-agent-beta\rp")
        wait_for("present_requires_matching_jobs_registration")
        os.write(master, b"o")
        wait_for("selected_record_has_no_report_or_brief_document")
        self.assertEqual(view(), before)
        process.send_signal(signal.SIGINT)
        self.finish_dashboard(process, master, slave, saved, output, expected=130)
        self.assertEqual(view(), before)

    def test_dashboard_metadata_redaction_absent_lifecycle_and_corrupt_source(self):
        root, env, args, session, anchor, alpha, beta, view = self.dashboard_fixture()
        record = json.loads((root / "agents" / ("agents-" + "1"*32 + ".json")).read_text())
        record.update(launch_id="3"*32, name="dash-agent-absent", target=dict(record["target"], block_id="block:"+ZERO))
        path = root / "agents" / ("agents-" + "3"*32 + ".json")
        path.write_text(json.dumps(record))
        path.chmod(0o600)
        before = view()
        process, master, slave, saved, output, wait_for = self.keyboard_dashboard(args, env)
        wait_for("LAST CALL")
        os.write(master, b"/dash-agent-absent\r\r")
        wait_for("selected_pane_presence_unknown")
        self.assertIn(b"dash-agent-absent", output)
        self.assertNotIn(b"NEVER_SHOW_THIS_TOKEN", output)
        os.write(master, b"q")
        self.finish_dashboard(process, master, slave, saved, output)
        self.assertEqual(before, view())
        # Corrupt lifecycle metadata must not turn a successful live presence read into success for that metadata.
        path.write_text("[]")
        result = subprocess.run([BIN, "boards", "probe", "--dashboard", "--agents-registry", str(root / "agents"),
                                 "--socket", str(self.socket)], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["rows"])
        self.assertEqual(payload["dashboard"]["lifecycles"], [])
        self.assertTrue(any(e.startswith("lifecycles:") for e in payload["dashboard"]["errors"]))
        self.assertNotIn("NEVER_SHOW_THIS_TOKEN", result.stdout)

    def test_jobs_registration_live_status_and_vanished_pane(self):
        root = self.root / ("jobs-" + str(time.monotonic_ns()))
        root.mkdir()
        registry, store = root / "jobs", root / "boards"
        registry.mkdir(mode=0o700)
        store.mkdir(mode=0o700)
        env = dict(os.environ, PATH=str(Path(self.rex).parent) + os.pathsep + os.environ["PATH"])
        def make(report=False):
            script = "import time; " + ("print('\\x1b]7501;state=done:app=rivet:title=RmluaXNoZWQ=\\x1b\\\\', flush=True); " if report else "") + "time.sleep(120)"
            made = json.loads(subprocess.check_output(self.base + ["new", "--json", "--keep-open", "--shell=none", "--", sys.executable, "-c", script]))
            return made["session_id"], made["initial_windows"][0]["block_ids"][0]
        worker, untracked, vanished = make(True), make(), make()
        for _ in range(100):
            status = json.loads(subprocess.check_output(self.base + ["block", "call", "-s", worker[0], "-b", worker[1], "program_status", "{}"]))
            if any(r["state"] == "done" for r in status["records"]):
                break
            time.sleep(.02)
        else:
            self.fail("fixture did not emit done")
        for sid, bid in (worker, vanished):
            subprocess.run([BIN, "jobs", "track", "--registry", str(registry), "--socket", str(self.socket),
                            "--session", sid, "--block", bid, "--owner", "rivet", "--kind", "command",
                            "--purpose", "item · step", "--deadline-unix-ms", str(int(time.time() * 1000) + 60000),
                            "--cleanup", "manual"], env=env, check=True, capture_output=True)
        subprocess.run([BIN, "surfaces", "close", "--socket", str(self.socket), "--session", vanished[0], "--pane", vanished[1]],
                       env=env, check=True, capture_output=True)
        before = {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in registry.iterdir()}
        targets = root / "targets.json"
        targets.write_text(json.dumps([dict(host="hive", server="unix://" + str(self.socket))]))
        command = [BIN, "boards", "fleet", "--store", str(store), "--targets-file", str(targets), "--once"]
        def snapshot(extra):
            result = subprocess.run(command + ["--json"] + extra, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            return json.loads(result.stdout)
        legacy = snapshot([])
        row = next(r for r in legacy["rows"] if r["target"]["block_id"] == worker[1])
        self.assertEqual(row["agent_classification"], "unknown_terminal")
        for key in ("registration", "program_status", "presence"):
            self.assertNotIn(key, row)
        subprocess.run([BIN, "boards", "fleet", "report", "--store", str(store), "--host", "hive",
                        "--socket", str(self.socket), "--session", worker[0], "--block", worker[1],
                        "--owner", "board-author", "--purpose", "saved report", "--state", "working", "--detail", "separate claim"],
                       env=env, check=True, capture_output=True)
        enriched = snapshot(["--jobs-registry", str(registry)])
        rows = {r["target"]["block_id"]: r for r in enriched["rows"]}
        row = rows[worker[1]]
        self.assertEqual(row["registration"]["owner"], "rivet")
        self.assertEqual(row["registration"]["purpose"], "item · step")
        self.assertEqual(row["program_status"]["records"][0]["state"], "done")
        self.assertEqual(row["program_status"]["records"][0]["app"], "rivet")
        self.assertIsNotNone(row["program_status"]["records"][0]["age_ms"], row["program_status"]["records"][0])
        self.assertTrue(row["presence"]["present"])
        self.assertEqual(row["report"]["state"], "working")
        self.assertEqual(row["state"], "working")
        self.assertTrue(row["registration_matches_presence"])
        self.assertIsNone(rows[untracked[1]]["registration"])
        self.assertEqual(rows[untracked[1]]["agent_classification"], "unknown_terminal")
        self.assertFalse(rows[vanished[1]]["presence"]["present"])
        self.assertEqual(rows[vanished[1]]["presence"]["reason"], "registered_pane_absent")
        rendered = subprocess.check_output(command + ["--detail", "--jobs-registry", "hive=" + str(registry)], env=env, text=True)
        for text in ("REGISTRATION [jobs] rivet", "item · step", "PROGRAM_STATUS [terminal report]", "done", "registered_pane_absent"):
            self.assertIn(text, rendered)
        self.assertEqual(before, {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in registry.iterdir()})
        for selectors in ([str(registry), str(registry)], ["absent=" + str(registry)], ["relative"],
                          [str(registry), "hive=" + str(registry)]):
            result = subprocess.run(command + [v for selector in selectors for v in ("--jobs-registry", selector)],
                                    env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        stale = json.loads((registry / "state.json").read_text())
        stale["entries"][0]["source"]["instance_id"] = "old-server-instance"
        (registry / "state.json").write_text(json.dumps(stale))
        rows = snapshot(["--jobs-registry", str(registry)])["rows"]
        row = next(r for r in rows if r["target"]["block_id"] == worker[1])
        self.assertTrue(row["presence"]["present"])
        self.assertFalse(row["registration_matches_presence"])
        (registry / "state.json").write_text("{}")
        (registry / "state.json").chmod(0o600)
        failed = subprocess.run(command + ["--jobs-registry", str(registry), "--json"], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(failed.returncode, 1)
        self.assertEqual(json.loads(failed.stdout)["sources"][0]["outcome"], "unknown")

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
        received_text = received.read_bytes().decode()
        self.assertIn("FROM worker: DECISION [live-test]: Live decision", received_text)
        self.assertIn("Recommendation: Review", received_text)
        self.assertIn("FROM operator: DECISION RESOLVED [live-test]", received_text)
        self.assertIn("Answer: Wait and review", received_text)


if __name__ == "__main__":
    unittest.main()
