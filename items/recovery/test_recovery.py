"""Recovery's public CLI, real surfaces and private disposable Rex only.

REX_BIN and TEEREX_BIN must select the tested binaries. No personal endpoint,
agent harness, credential directory, server updater or default Rex is contacted.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

BIN = str(Path(os.environ.get("TEEREX_BIN", "zig-out/bin/teerex")).resolve())
SOURCE = Path(__file__).with_name("recovery.py").resolve()


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.rex = os.environ.get("REX_BIN") or shutil.which("rex")
        if not self.rex:
            raise RuntimeError("Select disposable test Rex with REX_BIN")
        self.tmp = tempfile.TemporaryDirectory(prefix="trec-", dir="/tmp")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / "snapshot"
        self.store.mkdir(mode=0o700)
        self.socket = self.root / "rex.sock"
        self.base = [self.rex, "--autostart=false", "--server", "unix://" + str(self.socket), "--timeout", "3s"]
        self.env = dict(os.environ, TEEREX_CLUTCH_DIR=str(self.root / "clutch"), PATH=str(Path(self.rex).parent) + os.pathsep + os.environ.get("PATH", ""),
                        REX_SERVER="unix:///tmp/poison.sock", REX_SESSION="poison", REX_BLOCK="poison", REX_CLIENT="poison")
        self.server = None
        self.log = (self.root / "server.log").open("w")
        self.addCleanup(self.log.close)
        self.addCleanup(self.stop)
        self.start()
        self.version = self.rpc("server.version")
        if self.version["api_revision"] != 13 and self._testMethodName != "test_update_preview_and_snapshot_never_restarts_or_closes":
            self.skipTest("snapshot/restore truthfully require API13; only update inventory accepts older APIs")
        print("Recovery real Rex:", json.dumps(self.version), flush=True)

    def start(self):
        self.server = subprocess.Popen([self.rex, "server", "run", "--listen", "unix://" + str(self.socket),
                                        "--restore=false", "--config", "/dev/null", "--state-dir", str(self.root / "state")],
                                       stdout=self.log, stderr=self.log, env=self.env)
        for _ in range(100):
            if self.server.poll() is not None:
                raise RuntimeError((self.root / "server.log").read_text())
            if self.socket.exists():
                try:
                    self.rpc("server.version")
                    return
                except subprocess.CalledProcessError:
                    pass
            time.sleep(.03)
        self.fail("Disposable test server did not start")

    def stop(self):
        if self.server and self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait(timeout=5)
        self.server = None

    def restart(self):
        self.stop()
        self.start()
        self.assertFalse(self.rpc("session.list").get("sessions"))

    def rpc(self, method, args=None):
        return json.loads(subprocess.check_output(self.base + ["api", "call", method, json.dumps(args or {})], timeout=10, env=self.env))

    def invoke(self, op, *args, code=0, directory=True):
        command = [BIN, "recovery", op]
        if op != "inspect":
            command += ["--socket", str(self.socket)]
        if directory:
            command += ["--directory", str(self.store)]
        result = subprocess.run(command + list(args), capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def fixture(self, nested=False):
        block = lambda label: {"block": {"flavor": "com.superlogical.terminal.shell", "label": label,
                                         "options": {"shell": "none", "cwd": str(self.root), "command": ["/bin/sh", "-c", "sleep 90"], "exit": {"on_completion": False}}}}
        layout = block("seat α")
        if nested:
            layout = {"split": {"direction": "horizontal", "ratio": .31, "before": block("seat α"),
                                "after": {"split": {"direction": "vertical", "ratio": .67,
                                                     "before": block("right top"), "after": block("right bottom")}}}}
        made = self.rpc("session.create", {"label": "recovery fixture", "initial_windows": [{"window_label": "work α", "layout": layout}]})
        self.sid = made["session_id"]
        if nested:
            self.rpc("session.new_layer", {"session_id": self.sid, "window_id": made["initial_windows"][0]["window_id"],
                                            "bounds": [.61, .12, .27, .73], "layout": block("inbox float"), "focus": False})
        self.view = self.rpc("session.view", {"session_id": self.sid})
        self.blocks = self.rpc("session.list_blocks", {"session_id": self.sid})["blocks"]
        return self.blocks

    def target(self, block):
        return {"host": "disposable", "server": "unix://" + str(self.socket), "session_id": self.sid, "block_id": block}

    def metadata(self, agent=False):
        entries = []
        for i, b in enumerate(self.blocks):
            destination = self.root / (str(i) + ".json")
            code = ("import os,json,sys;from pathlib import Path;"
                    f"Path({str(destination)!r}).write_text(json.dumps(dict(argv=sys.argv[1:],cwd=os.getcwd(),"
                    "report=os.getenv('AGENT_REPORT_TO'),inbox=os.getenv('TEEREX_INBOX'),starter=os.getenv('AGENT_STARTER'),"
                    "session=os.getenv('AGENT_SESSION'),pane=os.getenv('AGENT_PANE'))))")
            entry = {"schema_version": 1, "launch_id": "controlled-" + str(i), "name": "restored α " + str(i),
                     "target": self.target(b["block_id"]), "starter": self.target(self.blocks[-1 if i else 0]["block_id"]),
                     "report_to": self.target(self.blocks[0]["block_id"]), "inbox": self.target(self.blocks[0]["block_id"]),
                     "argv": [sys.executable, "-c", code, "", "quote ' \"", "α\nline", "$(never); &"],
                     "cwd": str(self.root), "harness": "claude" if agent else None,
                     "resume_session_id": "fixture-resume-opaque" if agent else None, "seat": i == 0,
                     "protocol_acknowledged": True, "token": "MUST_NOT_SNAPSHOT_TOKEN", "brief": "MUST_NOT_SNAPSHOT_BRIEF"}
            entries.append(entry)
        path = self.root / "metadata.json"
        path.write_text(json.dumps({"schema_version": 1, "entries": entries}))
        path.chmod(0o600)
        return path

    def test_snapshot_private_layout_metadata_and_no_draft_guess(self):
        self.fixture(nested=True)
        metadata = self.metadata(agent=True)
        # Fake prompt text is terminal OUTPUT, even if it resembles a typed draft.
        # No recovery call may promote this, or grey suggestions, into draft evidence.
        printed = self.rpc("session.new_window", {"session_id": self.sid, "window_label": "screen-only",
                  "layout": {"block": {"flavor": "com.superlogical.terminal.shell", "label": "not a seat",
                  "options": {"shell": "none", "command": ["/bin/sh", "-c", "printf '\\033[2m❯ grey suggestion\\033[0m\\n❯ looks like real draft\\n'; IFS= read -r held; sleep 90"]}}}})
        draft_block = printed["block_ids"][0]
        draft = "CONTROLLED_SECRET_UNSENT_INPUT"
        self.rpc("com.superlogical.terminal.write", {"session_id": self.sid, "block_id": draft_block, "args": {"data": draft}})
        mode = self.rpc("com.superlogical.terminal.input_mode", {"session_id": self.sid, "block_id": draft_block, "args": {}})
        self.assertTrue(mode["canonical"])
        for _ in range(100):
            screen = self.rpc("com.superlogical.terminal.format", {"session_id": self.sid, "block_id": draft_block, "args": {"format": "vt", "max_bytes": 4096}})
            if draft in screen["content"]:
                break
            time.sleep(.02)
        self.assertIn(draft, screen["content"])
        result = self.invoke("snapshot", "--metadata", str(metadata))
        self.assertEqual(result["panes"], 5)
        self.assertFalse(result["drafts_captured"])
        saved = json.loads((self.store / "snapshot.json").read_text())
        self.assertEqual(saved["sessions"][0]["view"], self.rpc("session.view", {"session_id": self.sid}))
        raw = (self.store / "snapshot.json").read_text()
        self.assertNotIn("MUST_NOT_SNAPSHOT", raw)
        self.assertNotIn("grey suggestion", raw)
        self.assertNotIn("looks like real draft", raw)
        self.assertNotIn(draft, raw)
        panes = saved["sessions"][0]["panes"]
        self.assertEqual(sum(p["launch"] is not None for p in panes), 4)
        self.assertEqual(panes[0]["launch"]["resume_session_id"], "fixture-resume-opaque")
        self.assertEqual(panes[-1]["command_support"], "unknown_no_argv_API")
        self.assertEqual((self.store / "snapshot.json").stat().st_mode & 0o777, 0o600)
        before = (self.store / "snapshot.json").read_bytes()
        self.invoke("snapshot", "--metadata", str(metadata), code=1)
        self.assertEqual((self.store / "snapshot.json").read_bytes(), before)
        self.assertEqual(self.invoke("inspect")["panes"], 5)

    def test_restart_restore_nested_layout_exact_argv_and_report_inbox_remap(self):
        self.fixture(nested=True)
        metadata = self.metadata()
        empty_boards = self.root / "empty-boards"
        empty_boards.mkdir(mode=0o700)
        self.invoke("snapshot", "--metadata", str(metadata), "--board-store", str(empty_boards))
        source_instance = json.loads((self.store / "snapshot.json").read_text())["source"]["instance_id"]
        self.restart()
        plan = self.invoke("restore")
        self.assertTrue(plan["can_apply"])
        self.assertNotEqual(plan["context"]["target"]["instance_id"], source_instance)
        self.assertFalse(self.rpc("session.list").get("sessions"))
        self.invoke("restore", "--apply", "--confirm", "incorrect", code=1)
        self.assertFalse(self.rpc("session.list").get("sessions"))
        result = self.invoke("restore", "--apply", "--confirm", plan["confirmation"], "--board-store", str(empty_boards))
        self.assertEqual(result["mapped_panes"], 4)
        receipt = json.loads((self.store / "remap.json").read_text())
        self.assertFalse(receipt["board_state_applied"])
        self.assertEqual(receipt["agent_readiness"], "not_assessed")
        mapped = {m["old"]["block_id"]: m["new"] for m in receipt["mappings"]}
        new_seat = mapped[self.blocks[0]["block_id"]]
        self.assertNotEqual(new_seat["block_id"], self.blocks[0]["block_id"])
        for i, old in enumerate(self.blocks):
            path = self.root / (str(i) + ".json")
            for _ in range(100):
                if path.exists():
                    break
                time.sleep(.03)
            actual = json.loads(path.read_text())
            self.assertEqual(actual["argv"], ["", "quote ' \"", "α\nline", "$(never); &"])
            self.assertEqual(actual["cwd"], str(self.root.resolve()))
            self.assertEqual(actual["report"], new_seat["session_id"] + " " + new_seat["block_id"])
            self.assertEqual(actual["inbox"], actual["report"])
            starter = mapped[self.blocks[-1 if i else 0]["block_id"]]
            self.assertEqual(actual["starter"], starter["session_id"] + " " + starter["block_id"])
            self.assertEqual(actual["pane"], mapped[old["block_id"]]["block_id"])
        new_view = self.rpc("session.view", {"session_id": new_seat["session_id"]})
        self.assertEqual(new_view["windows"][0]["label"], "work α")
        tiled = new_view["windows"][0]["layers"][0]["layout"]["split"]
        self.assertAlmostEqual(tiled["ratio"], .31)
        self.assertAlmostEqual(tiled["after"]["split"]["ratio"], .67)
        floating = new_view["windows"][0]["layers"][1]
        self.assertEqual(floating["bounds"], [.61, .12, .27, .73])
        self.assertEqual([p["report_to"] for p in receipt["launches"]], [new_seat] * 4)
        before = self.rpc("session.list")
        self.invoke("restore", "--apply", "--confirm", plan["confirmation"], code=1)
        self.assertEqual(self.rpc("session.list"), before)

    def test_agent_resume_withheld_and_explicit_partial_holding_shell(self):
        self.fixture()
        metadata = self.metadata(agent=True)
        self.invoke("snapshot", "--metadata", str(metadata))
        self.restart()
        plan = self.invoke("restore")
        self.assertFalse(plan["can_apply"])
        self.assertIn("protocol_gate", plan["omissions"][0]["reason"])
        self.invoke("restore", "--apply", "--confirm", plan["confirmation"], code=1)
        accepted = self.invoke("restore", "--accept-omissions")
        self.assertTrue(accepted["can_apply"])
        self.assertNotEqual(plan["confirmation"], accepted["confirmation"])
        self.invoke("restore", "--accept-omissions", "--apply", "--confirm", accepted["confirmation"], code=3)
        self.assertFalse((self.root / "0.json").exists())
        receipt = json.loads((self.store / "remap.json").read_text())
        self.assertTrue(receipt["mappings"][0]["holding_shell"])
        self.assertEqual(receipt["launches"][0]["resume_session_id"], "fixture-resume-opaque")

    def test_private_ownership_permissions_links_and_bounds(self):
        self.fixture()
        self.store.chmod(0o755)
        self.invoke("snapshot", code=1)
        self.store.chmod(0o700)
        metadata = self.metadata()
        metadata.chmod(0o644)
        self.invoke("snapshot", "--metadata", str(metadata), code=1)
        metadata.chmod(0o600)
        link = self.root / "linked.json"
        link.symlink_to(metadata)
        self.invoke("snapshot", "--metadata", str(link), code=1)
        link.unlink()
        os.link(metadata, link)
        self.invoke("snapshot", "--metadata", str(metadata), code=1)
        link.unlink()
        metadata.write_bytes(b" " * (1024 * 1024 + 1))
        self.invoke("snapshot", "--metadata", str(metadata), code=1)
        self.assertFalse((self.store / "snapshot.json").exists())

    def test_update_preview_and_snapshot_never_restarts_or_closes(self):
        self.fixture(nested=True)
        before = self.rpc("session.view", {"session_id": self.sid})
        identity = self.rpc("server.status")["instance_id"]
        result = self.invoke("update", directory=False)
        self.assertEqual(len(result["panes_at_risk"]), 4)
        self.assertFalse(result["update_performed"])
        self.assertFalse(result["restart_performed"])
        self.assertFalse(result["build_differs"])
        self.assertIn("command_host", result["installed_comparison_scope"])
        # Controlled installed-vs-running mismatch: public RPCs still hit the real
        # disposable server, while only the selected CLI's local version differs.
        alternate = self.root / "selected-rex"
        changed = dict(self.version, commit="f" * 40, api_revision=99)
        alternate.write_text("#!" + sys.executable + "\nimport os,sys,json\nif sys.argv[1:]==['version','--json']:\n print(" + repr(json.dumps(changed)) + ")\nelse:\n os.execv(" + repr(self.rex) + ",[" + repr(self.rex) + "]+sys.argv[1:])\n")
        alternate.chmod(0o700)
        p = subprocess.run([sys.executable, str(SOURCE), "update", "--socket", str(self.socket)], capture_output=True, text=True,
                           env=dict(self.env, TEEREX_INTERNAL_REX=str(alternate)), timeout=20)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        mismatch = json.loads(p.stdout)
        self.assertTrue(mismatch["build_differs"])
        self.assertTrue(mismatch["api_differs"])
        self.assertEqual(mismatch["running"]["instance_id"], identity)
        if self.version["api_revision"] == 13:
            saved = self.invoke("update", "--snapshot")
            self.assertEqual(saved["snapshot"]["panes"], 4)
        else:
            saved = self.invoke("update", "--snapshot", code=1)
            self.assertFalse(saved["snapshot"]["written"])
            self.assertIn("unsupported", saved["snapshot_support"])
            self.assertFalse((self.store / "snapshot.json").exists())
        self.assertEqual(self.rpc("server.status")["instance_id"], identity)
        self.assertEqual(self.rpc("session.view", {"session_id": self.sid}), before)

    def test_boards_snapshot_references_preview_and_explicit_remap_preserve_cards(self):
        self.fixture(nested=True)
        metadata = self.metadata()
        board_store = self.root / "boards"
        board_store.mkdir(mode=0o700)
        seat = self.target(self.blocks[0]["block_id"])
        def boards(*args):
            p = subprocess.run([BIN, "boards", *args], capture_output=True, text=True, env=self.env, timeout=20)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            return json.loads(p.stdout)
        target_args = ["--host", seat["host"], "--socket", str(self.socket), "--session", self.sid, "--block", seat["block_id"]]
        boards("seat", "register", "--store", str(board_store), *target_args, "--owner", "operator")
        message = self.root / "message.txt"
        message.write_text("PRIVATE_PINNED_CONTENT_NOT_IN_SNAPSHOT")
        boards("inbox", "append", "--store", str(board_store), *target_args, "--from", "worker", "--message-file", str(message))
        card = self.root / "decision.json"
        card.write_text(json.dumps(dict(id="restart-decision", title="PRIVATE_CARD_NOT_IN_SNAPSHOT", ask="Restart the disposable server?",
                                        context="The fixture has private inbox state.", options=[dict(label="Restart", gain="New build", lose="Lose unsent inputs"),
                                        dict(label="Wait", gain="Keep inputs", lose="Delay update")], recommend="Wait until snapshot review.")))
        boards("ask", "--store", str(board_store), *target_args, "--from", "worker", "--card-file", str(card))
        before = boards("state", "inspect", "--store", str(board_store))["state"]
        self.invoke("snapshot", "--metadata", str(metadata), "--board-store", str(board_store))
        saved = json.loads((self.store / "snapshot.json").read_text())
        self.assertEqual(saved["boards"]["seats"], [seat])
        self.assertFalse(saved["boards"]["messages_copied"])
        self.assertNotIn(message.read_text(), (self.store / "snapshot.json").read_text())
        self.assertNotIn("PRIVATE_CARD_NOT_IN_SNAPSHOT", (self.store / "snapshot.json").read_text())
        self.restart()
        plan = self.invoke("restore")
        self.invoke("restore", "--board-store", str(board_store), "--apply", "--confirm", plan["confirmation"])
        remap = json.loads((self.store / "remap.json").read_text())
        handoff = remap["board_handoff"]
        self.assertEqual(handoff["preview"]["outcome"], "preview_only")
        self.assertEqual(boards("state", "inspect", "--store", str(board_store))["state"], before)
        mapping = json.loads((self.store / "board-map.json").read_text())
        self.assertEqual(len(mapping), 1)
        self.assertEqual(mapping[0]["old"], seat)
        boards("state", "remap-apply", "--store", str(board_store), "--map-file", handoff["map_file"],
               "--generation", str(handoff["preview"]["generation"]), "--reason", "disposable restored surfaces verified")
        after = boards("state", "inspect", "--store", str(board_store))["state"]
        self.assertEqual(after["seats"][0]["target"], mapping[0]["new"])
        self.assertEqual(after["seats"][0]["records"], before["seats"][0]["records"])

    def test_stale_board_reference_is_inspectable_but_blocks_restore(self):
        self.fixture()
        board_store = self.root / "boards"
        board_store.mkdir(mode=0o700)
        missing = "block:00000000-0000-0000-0000-000000000002"
        p = subprocess.run([BIN, "boards", "seat", "register", "--store", str(board_store),
                            "--host", "disposable", "--socket", str(self.socket), "--session", self.sid,
                            "--block", missing, "--owner", "historical-owner"],
                           capture_output=True, text=True, env=self.env, timeout=20)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.invoke("snapshot", "--metadata", str(self.metadata()), "--board-store", str(board_store))
        self.assertEqual(self.invoke("inspect")["panes"], 1)
        saved = json.loads((self.store / "snapshot.json").read_text())
        self.assertEqual(saved["boards"]["targets"][0]["block_id"], missing)
        self.restart()
        plan = self.invoke("restore", "--accept-omissions")
        self.assertFalse(plan["can_apply"])
        self.assertIn("unmapped_board_reference:" + missing, plan["hard_blockers"])
        self.invoke("restore", "--accept-omissions", "--apply", "--confirm", plan["confirmation"], code=1)
        self.assertFalse(self.rpc("session.list").get("sessions"))
        self.assertFalse((self.store / "restore.jsonl").exists())

    def test_agents_registry_sanitized_under_nonblocking_shared_lock(self):
        import fcntl
        self.fixture()
        metadata = json.loads(self.metadata(agent=True).read_text())["entries"][0]
        metadata.update(protocol_file="SECRET_PROTOCOL_FILE_NOT_READ", token="SECRET_TOKEN_NOT_COPIED", protocol_outcome="argument_supplied")
        registry = self.root / "registry"
        registry.mkdir(mode=0o700)
        lock = registry / "agents.lock"
        lock.touch(mode=0o600)
        record = registry / ("agents-" + "a" * 32 + ".json")
        record.write_text(json.dumps(metadata))
        record.chmod(0o600)
        with lock.open("r+") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.invoke("snapshot", "--registry", str(registry), code=1)
        self.invoke("snapshot", "--registry", str(registry))
        saved = json.loads((self.store / "snapshot.json").read_text())
        launch = saved["sessions"][0]["panes"][0]["launch"]
        self.assertEqual(launch["protocol_outcome"], "argument_supplied")
        self.assertNotIn("SECRET_", (self.store / "snapshot.json").read_text())

    def test_transport_uncertainty_keeps_journal_and_never_retries_or_closes(self):
        self.fixture()
        self.invoke("snapshot", "--metadata", str(self.metadata()))
        self.restart()
        plan = self.invoke("restore")
        marker = self.root / "attempts"
        shim = self.root / "uncertain-surface"
        shim.write_text("#!" + sys.executable + "\nfrom pathlib import Path\nimport sys\np=Path(" + repr(str(marker)) + ")\np.write_text(p.read_text()+'attempt\\n' if p.exists() else 'attempt\\n')\nsys.exit(1)\n")
        shim.chmod(0o700)
        env = dict(self.env, TEEREX_RECOVERY_EXECUTABLE=str(shim))
        command = [sys.executable, str(SOURCE), "restore", "--socket", str(self.socket), "--directory", str(self.store), "--apply", "--confirm", plan["confirmation"]]
        p = subprocess.run(command, capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(marker.read_text(), "attempt\n")
        journal = [json.loads(line) for line in (self.store / "restore.jsonl").read_text().splitlines()]
        self.assertEqual(journal[-1]["outcome"], "partial_or_uncertain_inspect_journal_before_any_action")
        self.assertEqual(sum(r["event"] == "surface_attempt" for r in journal), 1)
        self.assertEqual(len(self.rpc("session.list")["sessions"]), 1)  # No automatic cleanup closes the new session.
        p = subprocess.run(command, capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(p.returncode, 1)
        self.assertEqual(marker.read_text(), "attempt\n")
        # Even after an operator makes the disposable target empty again, retained
        # intent interlocks a new apply before its first mutation.
        self.restart()
        plan = self.invoke("restore")
        self.invoke("restore", "--apply", "--confirm", plan["confirmation"], code=1)
        self.assertFalse(self.rpc("session.list").get("sessions"))
        self.assertEqual(marker.read_text(), "attempt\n")

    def test_attached_remote_host_restore_is_explicitly_blocked(self):
        self.fixture(nested=True)
        self.invoke("snapshot", "--metadata", str(self.metadata()))
        self.restart()
        path = self.store / "snapshot.json"
        saved = json.loads(path.read_text())
        saved["sessions"][0]["panes"][0]["block"]["host_id"] = "attached-other-host"
        path.write_text(json.dumps(saved))
        plan = self.invoke("restore")
        self.assertFalse(plan["can_apply"])
        self.assertTrue(any("attached_remote_host" in reason for reason in plan["hard_blockers"]))
        self.invoke("restore", "--apply", "--confirm", plan["confirmation"], code=1)
        self.assertFalse(self.rpc("session.list").get("sessions"))

    def test_host_mismatch_and_nonempty_target_refuse_before_mutation(self):
        self.fixture()
        self.invoke("snapshot", "--metadata", str(self.metadata()))
        plan = self.invoke("restore")
        self.assertFalse(plan["can_apply"])
        before = self.rpc("session.list")
        self.invoke("restore", "--apply", "--confirm", plan["confirmation"], code=1)
        self.assertEqual(self.rpc("session.list"), before)
        self.restart()
        path = self.store / "snapshot.json"
        saved = json.loads(path.read_text())
        saved["source"]["host_id"] = "unrelated-host"
        path.write_text(json.dumps(saved))
        result = self.invoke("restore", code=1)
        self.assertIn("host_mismatch", result["reason"])
        self.assertFalse(self.rpc("session.list").get("sessions"))


if __name__ == "__main__":
    unittest.main()
