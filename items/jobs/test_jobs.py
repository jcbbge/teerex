"""Public jobs CLI contracts against an explicit disposable Rex API13 server.

Select TEEREX_BIN (combined CLI or test_cli bridge) and REX_BIN. No personal endpoint.
"""
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

BIN = str(Path(os.environ.get("TEEREX_BIN", Path(__file__).resolve().parents[2] / "zig-out/bin/teerex")).resolve())
ZERO = "00000000-0000-0000-0000-000000000000"


class JobsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rex = os.environ.get("REX_BIN") or shutil.which("rex")
        if not cls.rex:
            raise RuntimeError("Select test REX_BIN")
        tmp = tempfile.TemporaryDirectory(prefix="tjobs-", dir="/tmp")
        cls.addClassCleanup(tmp.cleanup)
        cls.root = Path(tmp.name)
        cls.socket = cls.root / "rex.sock"
        cls.base = [cls.rex, "--autostart=false", "--server", "unix://" + str(cls.socket), "--timeout", "3s"]
        cls.log = (cls.root / "server.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen([cls.rex, "server", "run", "--listen", "unix://" + str(cls.socket),
                                       "--restore=false", "--config", "/dev/null", "--state-dir", str(cls.root / "state")],
                                      stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            if cls.server.poll() is not None:
                raise RuntimeError((cls.root / "server.log").read_text())
            if cls.socket.exists():
                break
            time.sleep(.05)
        else:
            raise RuntimeError("Disposable server did not start")
        cls.source = cls.rpc("server.version")
        print("Real Rex:", json.dumps(cls.source), flush=True)
        if cls.source["api_revision"] != 13:
            raise RuntimeError("Jobs integration requires actual API13")

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    @classmethod
    def rpc(cls, method, **args):
        return json.loads(subprocess.check_output(cls.base + ["api", "call", method, json.dumps(args)], timeout=10))

    def setUp(self):
        self.work = self.root / str(time.monotonic_ns())
        self.work.mkdir()
        self.registry = self.work / "registry"
        self.registry.mkdir(mode=0o700)
        self.env = dict(os.environ, PATH=str(Path(self.rex).parent) + os.pathsep + os.environ.get("PATH", ""),
                        REX_SERVER="unix:///tmp/poison.sock", REX_SESSION="session:poison", REX_BLOCK="block:poison", REX_CLIENT="client:poison")
        made = json.loads(subprocess.check_output(self.base + ["new", "--json", "--keep-open", "--shell=none", "--", "/bin/sleep", "120"], timeout=10))
        self.session = made["session_id"]
        self.anchor = made["initial_windows"][0]["block_ids"][0]
        self.block = self.anchor

    def command(self, operation, **options):
        args = [BIN, "jobs", operation, "--registry", str(options.pop("registry", self.registry))]
        if operation != "list":
            target = dict(socket=str(self.socket), session=self.session, block=self.block)
            target.update(options)
            options = target
        for key, value in options.items():
            args += ["--" + key.replace("_", "-"), str(value)]
        return args

    def invoke(self, operation, **options):
        r = subprocess.run(self.command(operation, **options), capture_output=True, text=True, env=self.env, timeout=10)
        return r, json.loads(r.stdout) if r.stdout else None

    def track(self, **options):
        values = dict(owner="operator α", kind="command", purpose="explicit test responsibility", deadline_unix_ms=int(time.time() * 1000) + 60000, cleanup="manual")
        values.update(options)
        r, p = self.invoke("track", **values)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return p

    def view(self):
        return self.rpc("session.view", session_id=self.session)

    def detached(self, argv=None):
        p = self.rpc("session.new_block", session_id=self.session, flavor="com.superlogical.terminal.shell", label="explicit detached command",
                     options=dict(shell="none", login=False, interactive=False, command=argv or ["/bin/sleep", "120"], exit=dict(on_completion=False)))
        self.block = p["block_id"]
        return self.block

    def test_tracking_persists_without_owning_process_and_offline_list_is_stale(self):
        before = self.view()
        p = self.track(kind="agent", purpose="visible agent accounting only")
        self.assertEqual(p["entry"]["generation"], 1)
        self.assertFalse(p["recorded_owner_is_process_owner"])
        self.assertFalse(p["exclusive_control"])
        self.assertEqual(p["owner_liveness"], "not_checked")
        self.assertEqual(p["task_completion"], "not_assessed")
        self.assertEqual(self.view(), before)
        for name in ["lock", "state.json"]:
            self.assertEqual((self.registry / name).stat().st_mode & 0o777, 0o600)
        self.env["PATH"] = "/no-rex-here"
        r, listing = self.invoke("list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(listing["entries"][0], p["entry"])
        self.assertEqual(listing["live_state"], "not_checked")
        self.assertFalse(listing["deadline_enforced"])
        r, duplicate = self.invoke("track", owner="someone else", kind="command", purpose="no takeover", deadline_unix_ms=int(time.time()*1000)+60000, cleanup="manual")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(duplicate["failure_reason"], "TargetAlreadyTracked")
        self.assertEqual(self.view(), before)

    def test_adoption_requires_recorded_owner_generation_and_live_identity(self):
        self.detached()
        self.track()
        before = self.view()
        fields = dict(from_owner="wrong", owner="successor", generation=1, reason="explicit handoff", deadline_unix_ms=int(time.time()*1000)+120000)
        r, p = self.invoke("adopt", **fields)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(p["failure_reason"], "RecordedOwnerMismatch")
        fields.update(from_owner="operator α", generation=2)
        r, p = self.invoke("adopt", **fields)
        self.assertEqual(p["failure_reason"], "GenerationConflict")
        fields["generation"] = 1
        r, p = self.invoke("adopt", **fields)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(p["entry"]["owner"], "successor")
        self.assertEqual(p["entry"]["generation"], 2)
        self.assertEqual(p["entry"]["last_action"]["reason"], "explicit handoff")
        self.assertEqual(self.view(), before)
        r, p = self.invoke("forget", owner="operator α", generation=2, reason="old owner must not remove")
        self.assertEqual(p["failure_reason"], "RecordedOwnerMismatch")
        r, p = self.invoke("forget", owner="successor", generation=1, reason="stale generation")
        self.assertEqual(p["failure_reason"], "GenerationConflict")
        r, p = self.invoke("forget", owner="successor", generation=2, reason="stop tracking, keep program")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertFalse(p["resource_closed"])
        self.assertEqual(self.view(), before)
        self.assertEqual(self.invoke("list")[1]["entries"], [])
        # Re-registering the same address must not recycle an old generation (ABA).
        p = self.track()
        self.assertEqual(p["entry"]["generation"], 3)
        r, p = self.invoke("forget", owner="operator α", generation=1, reason="stale request from before forget")
        self.assertEqual(p["failure_reason"], "GenerationConflict")

    def test_detached_command_presentation_is_explicit_nonfocusing_and_labelled(self):
        self.detached()
        self.track()
        before = self.view()
        label = "requested α ' $(not-shell)"
        r, p = self.invoke("present", owner="operator α", generation=1, reason="review command evidence now", anchor=self.anchor, focus="no", label=label)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(p["outcome"], "verified")
        self.assertTrue(p["mutation_attempt_frame_seen"])
        self.assertFalse(p["retry_safe"])
        self.assertEqual(p["entry"]["last_action"]["reason"], "review command evidence now")
        after = self.view()
        self.assertEqual(after["active_window_id"], before["active_window_id"])
        self.assertEqual(len(after["windows"]), len(before["windows"]))
        self.assertEqual(after["windows"][0]["focused_block_id"], self.anchor)
        desc = self.rpc("session.describe_block", session_id=self.session, block_id=self.block)["block"]
        self.assertEqual(desc["placement"], "placed")
        self.assertEqual(desc["label"], label)
        layout = after["windows"][0]["layers"][0]["layout"]["split"]
        self.assertEqual(layout["before"]["block_id"], self.anchor)
        self.assertEqual(layout["after"]["block_id"], self.block)
        self.assertEqual(layout["direction"], "horizontal")
        self.assertEqual(layout["ratio"], .5)
        r, p = self.invoke("present", owner="operator α", generation=2, reason="explicitly focus existing pane", anchor=self.anchor, focus="yes")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.view()["windows"][0]["focused_block_id"], self.block)
        self.assertEqual(self.view()["windows"][0]["layers"], after["windows"][0]["layers"])

    def test_agent_detached_or_minimized_refuses_and_placed_panes_never_move(self):
        self.detached()
        args = dict(owner="operator α", kind="agent", purpose="must not hide workers", deadline_unix_ms=int(time.time()*1000)+60000, cleanup="manual")
        r, p = self.invoke("track", **args)
        self.assertEqual(r.returncode, 1, r.stderr + r.stdout)
        self.assertEqual(p["failure_reason"], "agent_not_visible_in_view")
        self.assertEqual(self.invoke("list")[1]["entries"], [])
        self.track()
        other = self.rpc("session.new_window", session_id=self.session, focus=False, layout=dict(block=dict(flavor="com.superlogical.terminal.shell", options=dict(command=["/bin/sleep", "120"]))))
        other_anchor = other["block_ids"][0]
        self.rpc("session.move_block", session_id=self.session, block_id=self.block, anchor_block_id=self.anchor)
        before = self.view()
        r, p = self.invoke("present", owner="operator α", generation=1, reason="must not rearrange", anchor=other_anchor, focus="no")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(p["failure_reason"], "placed_target_not_visible_in_destination")
        self.assertFalse(p["mutation_attempt_frame_seen"])
        self.assertEqual(self.view(), before)

    def test_native_ownership_and_hidden_agent_never_allow_takeover(self):
        # `rex new` retains a real native terminal owner, unlike our detached fixture.
        self.assertIsNotNone(self.rpc("session.describe_block", session_id=self.session, block_id=self.block)["block"].get("owner"))
        self.track()
        before = self.view()
        r, p = self.invoke("adopt", from_owner="operator α", owner="successor", generation=1, reason="no forced native takeover", deadline_unix_ms=int(time.time()*1000)+60000)
        self.assertEqual(p["failure_reason"], "resource_has_native_owner")
        self.assertEqual(self.view(), before)
        other = self.detached()
        self.rpc("session.move_block", session_id=self.session, block_id=other, anchor_block_id=self.anchor)
        self.track(kind="agent")
        self.rpc("session.detach_block", session_id=self.session, block_id=other)
        hidden_view = self.view()
        r, p = self.invoke("present", owner="operator α", generation=2, reason="must not rescue a hidden agent implicitly", anchor=self.anchor, focus="no")
        self.assertEqual(p["failure_reason"], "agent_not_visible_in_view")
        self.assertFalse(p["mutation_attempt_frame_seen"])
        self.assertEqual(self.view(), hidden_view)
        # A minimized floating layer is attached, but is not visible agent presentation.
        self.rpc("session.move_block", session_id=self.session, block_id=other, anchor_block_id=self.anchor)
        self.rpc("session.float_block", session_id=self.session, block_id=other, bounds=[.1,.1,.5,.5])
        layer = next(l for l in self.view()["windows"][0]["layers"] if l["kind"] == "floating")
        self.rpc("session.set_layer_state", session_id=self.session, layer_id=layer["layer_id"], state="minimized", focus=False)
        r, p = self.invoke("inspect")
        self.assertEqual(p["failure_reason"], "agent_not_visible_in_view")
        self.assertFalse(p["observation"]["visible_in_view"])

    def test_expired_deadline_and_actual_last_exit_do_not_mean_task_completion(self):
        self.detached(["/bin/sh", "-c", "exit 7"])
        self.track(deadline_unix_ms=int(time.time()*1000)+250)
        time.sleep(.3)
        r, p = self.invoke("inspect")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertTrue(p["deadline_passed"])
        self.assertFalse(p["deadline_enforced"])
        self.assertEqual(p["observation"]["last_exit_code_reported"], 7)
        self.assertEqual(p["task_completion"], "not_assessed")
        self.assertFalse(p["all_processes_verified_gone"])
        self.assertEqual(self.rpc("session.describe_block", session_id=self.session, block_id=self.block)["block"]["placement"], "detached")
        saved = (self.registry / "state.json").read_text()
        self.assertNotIn("last_exit_code_reported", saved)
        self.assertNotIn("capture", saved)

    def test_missing_and_stale_targets_never_adopt_or_mutate(self):
        self.detached()
        self.track()
        raw = json.loads((self.registry / "state.json").read_text())
        raw["entries"][0]["source"]["instance_id"] = "injected-different-instance"
        (self.registry / "state.json").write_text(json.dumps(raw))
        before = self.view()
        r, p = self.invoke("inspect")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(p["failure_reason"], "stale_server_identity")
        self.assertIsNone(p["observation"])
        r, p = self.invoke("adopt", from_owner="operator α", owner="successor", generation=1, reason="not a rebind", deadline_unix_ms=int(time.time()*1000)+60000)
        self.assertEqual(p["failure_reason"], "stale_server_identity")
        self.assertEqual(self.invoke("list")[1]["entries"][0]["owner"], "operator α")
        self.assertEqual(self.view(), before)
        raw["entries"][0]["source"]["instance_id"] = self.rpc("server.status")["instance_id"]
        (self.registry / "state.json").write_text(json.dumps(raw))
        self.rpc("block.close", session_id=self.session, block_id=self.block)
        r, p = self.invoke("inspect")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(p["outcome"], "refused")
        self.assertEqual(p["failure_reason"], "target_absent_at_observation")
        self.assertEqual(p["task_completion"], "not_assessed")
        self.assertEqual(len(self.invoke("list")[1]["entries"]), 1)

    def shim(self, body):
        folder = self.work / "shim"
        folder.mkdir(exist_ok=True)
        path = folder / "rex"
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(0o755)
        self.env["PATH"] = str(folder) + os.pathsep + self.env["PATH"]

    def test_lost_presentation_receipt_is_durably_uncertain_without_rollback(self):
        self.detached()
        self.track()
        self.shim("import subprocess,sys\n"
                  f"r=subprocess.run([{self.rex!r},*sys.argv[1:]],capture_output=True)\n"
                  "sys.exit(77)\n")
        r, p = self.invoke("present", owner="operator α", generation=1, reason="test dropped receipt", anchor=self.anchor, focus="no")
        self.assertEqual(r.returncode, 1, r.stderr + r.stdout)
        self.assertEqual(p["outcome"], "uncertain")
        self.assertFalse(p["mutation_attempt_frame_seen"])
        listing = self.invoke("list")[1]
        e = listing["entries"][0]
        self.assertEqual(e["last_action"]["outcome"], "uncertain")
        self.assertEqual(e["generation"], 2)
        self.assertEqual(self.rpc("session.describe_block", session_id=self.session, block_id=self.block)["block"]["placement"], "placed")
        r, p = self.invoke("present", owner="operator α", generation=1, reason="old generation cannot retry", anchor=self.anchor, focus="no")
        self.assertEqual(p["failure_reason"], "GenerationConflict")

    def test_socket_aliases_do_not_duplicate_responsibility_and_inactive_destination_preserves_focus(self):
        self.detached()
        self.track()
        alias = self.work / "alias.sock"
        alias.symlink_to(self.socket)
        r, p = self.invoke("track", socket=alias, owner="other", kind="command", purpose="same server resource", deadline_unix_ms=int(time.time()*1000)+60000, cleanup="manual")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(p["failure_reason"], "TargetAlreadyTrackedThroughAnotherEndpoint")
        self.assertEqual(len(self.invoke("list")[1]["entries"]), 1)
        destination = self.rpc("session.new_window", session_id=self.session, focus=False,
                               layout=dict(block=dict(flavor="com.superlogical.terminal.shell", options=dict(command=["/bin/sleep", "120"]))))
        anchor = destination["block_ids"][0]
        before = self.view()
        r, p = self.invoke("present", owner="operator α", generation=1, reason="present without switching tabs", anchor=anchor, focus="no")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        after = self.view()
        self.assertEqual(after["active_window_id"], before["active_window_id"])
        self.assertEqual([w["focused_block_id"] for w in after["windows"]], [w["focused_block_id"] for w in before["windows"]])
        self.assertEqual(self.rpc("session.describe_block", session_id=self.session, block_id=self.block)["block"]["window_id"], destination["window_id"])

    def test_registry_lock_and_private_regular_files_fail_closed(self):
        self.track()
        before = self.view()
        with (self.registry / "lock").open("r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            r, p = self.invoke("list")
            self.assertEqual(r.returncode, 1)
            self.assertEqual(p["failure_reason"], "WouldBlock")
        self.registry.chmod(0o755)
        r, p = self.invoke("list")
        self.assertEqual(p["failure_reason"], "RegistryNotPrivateOwnedRegular")
        self.registry.chmod(0o700)
        state = self.registry / "state.json"
        state.chmod(0o644)
        self.assertEqual(self.invoke("list")[1]["failure_reason"], "RegistryNotPrivateOwnedRegular")
        state.chmod(0o600)
        saved = self.work / "private-state"
        state.rename(saved)
        state.symlink_to(saved)
        self.assertEqual(self.invoke("list")[0].returncode, 1)
        state.unlink()
        os.link(saved, state)
        self.assertEqual(self.invoke("list")[1]["failure_reason"], "RegistryNotPrivateOwnedRegular")
        state.unlink()
        saved.rename(state)
        link = self.work / "registry-link"
        link.symlink_to(self.registry, target_is_directory=True)
        self.assertEqual(self.invoke("list", registry=link)[0].returncode, 1)
        self.assertEqual(self.view(), before)

    def test_capacity_corruption_and_crash_staging_never_drop_entries(self):
        self.track()
        state = self.registry / "state.json"
        good = state.read_text()
        raw = json.loads(good)
        for n in range(1, 32):
            entry = dict(raw["entries"][0], block_id=f"block:{n:08x}-0000-0000-0000-000000000000")
            raw["entries"].append(entry)
        state.write_text(json.dumps(raw))
        old_block = self.block
        self.detached()
        r, p = self.invoke("track", owner="operator α", kind="command", purpose="capacity", deadline_unix_ms=int(time.time()*1000)+60000, cleanup="manual")
        self.assertEqual(p["failure_reason"], "RegistryFull")
        self.assertEqual(len(self.invoke("list")[1]["entries"]), 32)
        state.write_text(good)
        self.block = old_block
        (self.registry / "state.next").write_text("retained crash intent")
        r, p = self.invoke("forget", owner="operator α", generation=1, reason="must not overwrite crash evidence")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(state.read_text(), good)
        self.assertEqual((self.registry / "state.next").read_text(), "retained crash intent")
        state.write_text("{" * 262145)
        self.assertEqual(self.invoke("list")[0].returncode, 1)
        state.write_text('{"schema_version":2,"next_generation":1,"entries":[]}')
        self.assertEqual(self.invoke("list")[1]["failure_reason"], "InvalidRegistry")

    def test_deadline_cancel_and_owner_crash_leave_resource_and_persist_intent(self):
        self.detached()
        self.track()
        ready = self.work / "ready"
        self.shim(f"import os,signal,time\nfrom pathlib import Path\nPath({str(ready)!r}).write_text(str(os.getpid()))\n"
                  "signal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(60)\n")
        gen = 1
        for sig, code in [(None, 124), (signal.SIGINT, 130), (signal.SIGTERM, 143), (signal.SIGKILL, -signal.SIGKILL)]:
            ready.unlink(missing_ok=True)
            proc = subprocess.Popen(self.command("present", owner="operator α", generation=gen, reason="bounded transport lifetime", anchor=self.anchor,
                                                 focus="no", timeout_ms=200 if sig is None else 5000),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env, start_new_session=True)
            try:
                for _ in range(100):
                    if ready.exists():
                        break
                    time.sleep(.01)
                self.assertTrue(ready.exists())
                if sig is not None:
                    proc.send_signal(sig)
                out, err = proc.communicate(timeout=5)
                self.assertEqual(proc.returncode, code, err + out)
                if sig != signal.SIGKILL:
                    packet = json.loads(out)
                    self.assertEqual(packet["outcome"], "deadline_exceeded" if sig is None else "cancel_requested")
                listing = self.invoke("list")[1]
                gen += 1
                self.assertEqual(listing["entries"][0]["generation"], gen)
                self.assertEqual(self.rpc("session.describe_block", session_id=self.session, block_id=self.block)["block"]["placement"], "detached")
            finally:
                if proc.poll() is None:
                    proc.kill(); proc.wait(timeout=5)
                # SIGKILL bypasses the foreground supervisor. The shim PID reserves its own group.
                if sig == signal.SIGKILL and ready.exists():
                    try:
                        os.killpg(int(ready.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        self.assertEqual(listing["entries"][0]["last_action"]["outcome"], "uncertain")

    def test_usage_and_missing_endpoint_never_autostart(self):
        self.env["PATH"] = "/no-rex-here"
        for options in [dict(), dict(owner="a", kind="command", purpose="p", deadline_unix_ms=0, cleanup="manual"),
                        dict(owner="a", kind="worker", purpose="p", deadline_unix_ms=int(time.time()*1000)+60000, cleanup="manual")]:
            r, p = self.invoke("track", **options)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIsNone(p)
        for operation, extra in [("list", ["--owner", "a"]), ("inspect", ["--timeout-ms", "99"]), ("list", ["--registry", str(self.registry)])]:
            r = subprocess.run(self.command(operation) + extra, env=self.env, capture_output=True, text=True, timeout=5)
            self.assertEqual(r.returncode, 2, r.stderr)
        self.env["PATH"] = str(Path(self.rex).parent) + os.pathsep + os.environ.get("PATH", "")
        missing = self.work / "absent.sock"
        command = self.command("track", owner="a", kind="command", purpose="p", deadline_unix_ms=int(time.time()*1000)+60000, cleanup="manual")
        command[command.index("--socket") + 1] = str(missing)
        r = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(r.returncode, 1, r.stderr + r.stdout)
        self.assertFalse(missing.exists())
        self.assertEqual(self.invoke("list")[1]["entries"], [])


if __name__ == "__main__":
    unittest.main()
