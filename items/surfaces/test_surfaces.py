"""Public surface contract using only disposable Rex sockets, on Linux and macOS.

REX_BIN selects a real Rex; TEEREX_BIN selects the shared CLI or standalone test entry.
No personal/default server, config, pane or process is touched.
"""
import base64
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


class SurfacesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rex = str(Path(os.environ.get("REX_BIN") or shutil.which("rex") or "MISSING_REX").resolve())
        tmp = tempfile.TemporaryDirectory(prefix="tsurface-", dir="/tmp")
        cls.addClassCleanup(tmp.cleanup)
        cls.root = Path(tmp.name)
        cls.socket = cls.root / "rex.sock"
        cls.config = cls.root / "init.lua"
        cls.config.write_text("")
        cls.base = [cls.rex, "--autostart=false", "--server", "unix://" + str(cls.socket), "--timeout", "3s"]
        cls.log = (cls.root / "server.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen([cls.rex, "server", "run", "--listen", "unix://" + str(cls.socket),
                                      "--restore=false", "--config", str(cls.config), "--state-dir", str(cls.root / "state")],
                                     stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            if cls.server.poll() is not None:
                raise RuntimeError((cls.root / "server.log").read_text())
            if cls.socket.exists():
                break
            time.sleep(.05)
        else:
            raise RuntimeError("Disposable Rex did not start")
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
    def rpc(cls, method, args):
        return json.loads(subprocess.check_output(cls.base + ["api", "call", method, json.dumps(args)], timeout=10))

    def setUp(self):
        self.work = self.root / str(time.monotonic_ns())
        self.work.mkdir()
        self.env = dict(os.environ, PATH=str(Path(self.rex).parent) + os.pathsep + os.environ.get("PATH", ""),
                        REX_SERVER="unix:///tmp/poison.sock", REX_SESSION="session:poison",
                        REX_BLOCK="block:poison", REX_CLIENT="client:poison")
        self.session = self.rpc("session.create", {"label": "surfaces disposable"})["session_id"]
        self.anchor = self.open("tab")["actual"]["block_id"]
        self.addCleanup(lambda: self.rpc("session.destroy", {"session_id": self.session}))

    def view(self):
        return self.rpc("session.view", {"session_id": self.session})

    def command(self, layout, *argv, label="surface α", extra=()):
        command = [BIN, "surfaces", "open", "--socket", str(self.socket), "--session", self.session,
                   "--layout", layout, "--label", label]
        if layout != "tab":
            command += ["--anchor", self.anchor]
        return command + list(extra) + ["--", *(argv or ["/bin/sh", "-c", "printf 'visible surface\\n'; sleep 60"])]

    def run_json(self, command):
        r = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=10)
        self.assertTrue(r.stdout, r.stderr)
        return r, json.loads(r.stdout)

    def open(self, layout, *argv, **kw):
        r, value = self.run_json(self.command(layout, *argv, **kw))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(value["outcome"], "created_and_verified")
        self.assertTrue(value["requested_geometry_verified"])
        self.assertFalse(value["retry_safe"])
        self.assertFalse(value["focus_requested"])
        self.assertEqual(value["painted_visibility"], "not_assessed")
        return value

    def inspect(self, bid):
        r, v = self.run_json([BIN, "surfaces", "inspect", "--socket", str(self.socket), "--session", self.session, "--pane", bid])
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(v["outcome"], "inspected")
        return v["actual"]

    def rect(self, actual, expected):
        self.assertEqual(len(actual), 4)
        for n, e in zip(actual, expected):
            self.assertAlmostEqual(n, e, places=6)

    def test_four_asymmetric_directions_and_nested_readback(self):
        # Explicit independent rectangles catch confusing NEW share with BEFORE share.
        expected = {"right": [.77, 0, .23, 1], "left": [0, 0, .23, 1],
                    "up": [0, 0, 1, .23], "down": [0, .77, 1, .23]}
        initial = self.anchor
        for direction, rect in expected.items():
            with self.subTest(direction=direction):
                if direction != "right":
                    self.anchor = self.open("tab")["actual"]["block_id"]
                before = self.view()
                v = self.open("tiled", extra=["--direction", direction, "--ratio", ".23"])
                a = v["actual"]
                self.rect(a["rect"], rect)
                self.assertAlmostEqual(a["pane_share"], .23)
                self.assertEqual(self.view()["active_window_id"], before["active_window_id"])
                self.assertEqual(a["window_id"], self.inspect(self.anchor)["window_id"])
                self.assertEqual(a["host_id"], self.inspect(self.anchor)["host_id"])
                stable = self.view()
                self.assertEqual(self.inspect(a["block_id"])["rect"], a["rect"])
                self.assertEqual(stable, self.view(), "inspect must not change layout/focus")
        self.anchor = initial
        nested = self.open("tiled", extra=["--direction", "down", "--ratio", ".4"])["actual"]
        self.rect(nested["rect"], [0, .6, .77, .4])
        self.assertEqual(len(nested["split_path"]), 2)

    def test_explicit_focus_and_close_verify_only_the_requested_pane(self):
        tab = self.open("tab")["actual"]
        self.assertNotEqual(self.view()["active_window_id"], tab["window_id"])
        base = [BIN, "surfaces", "focus", "--socket", str(self.socket), "--session", self.session, "--pane", tab["block_id"]]
        r, v = self.run_json(base)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(v["outcome"], "focused_and_verified")
        self.assertTrue(v["focus_requested"])
        self.assertTrue(v["control_acknowledged"])
        self.assertFalse(v["creation_attempted"])
        self.assertEqual(self.view()["active_window_id"], tab["window_id"])
        self.assertEqual(self.inspect(tab["block_id"])["focused_block_id"], tab["block_id"])
        base[2] = "close"
        r, v = self.run_json(base)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(v["outcome"], "closed_and_absent")
        self.assertTrue(v["block_absence_verified"])
        self.assertTrue(v["close_requested"])
        self.assertFalse(v["automatic_close"])
        self.assertEqual(self.inspect(self.anchor)["block_id"], self.anchor)
        stable = self.view()
        r, v = self.run_json(base)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(v["outcome"], "refused")
        self.assertFalse(v["control_attempted"])
        self.assertEqual(self.view(), stable)
        base[base.index("--pane") + 1] = self.anchor
        r, v = self.run_json(base)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(v["outcome"], "closed_and_absent")
        self.assertFalse(self.view().get("windows"))

    def move_command(self, pane, *, direction="right", ratio=".27", focus="no"):
        return [BIN, "surfaces", "move", "--socket", str(self.socket), "--session", self.session,
                "--pane", pane, "--anchor", self.anchor, "--direction", direction, "--ratio", ratio, "--focus", focus]

    def test_existing_tab_move_preserves_identity_process_and_asymmetric_geometry(self):
        expected = {"right": [.73, 0, .27, 1], "left": [0, 0, .27, 1],
                    "up": [0, 0, 1, .27], "down": [0, .73, 1, .27]}
        for direction, rect in expected.items():
            self.anchor = self.open("tab")["actual"]["block_id"]
            pane = self.open("tab", "/bin/sh", "-c", "printf 'same terminal process\\n'; exec sleep 60")["actual"]
            before = self.view()
            blocks_before = {b["block_id"] for b in self.rpc("session.list_blocks", {"session_id": self.session})["blocks"]}
            process = self.rpc("com.superlogical.terminal.process", {"session_id": self.session, "block_id": pane["block_id"], "args": {}})
            r, refused = self.run_json(self.move_command(pane["block_id"], direction=direction))
            self.assertEqual(r.returncode, 1)
            self.assertEqual(refused["failure_reason"], "focused_source_move_requires_focus_yes")
            self.assertFalse(refused["control_attempted"])
            self.assertEqual(self.view(), before)
            r, moved = self.run_json(self.move_command(pane["block_id"], direction=direction, focus="yes"))
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            self.assertEqual(moved["outcome"], "moved_and_verified")
            self.assertFalse(moved["creation_attempted"])
            self.assertTrue(moved["control_acknowledged"])
            self.assertTrue(moved["focus_acknowledged"])
            self.assertIsNone(moved["created"])
            self.assertEqual(moved["actual"]["block_id"], pane["block_id"])
            self.assertEqual(moved["previous"]["window_id"], pane["window_id"])
            self.rect(moved["actual"]["rect"], rect)
            self.assertEqual(moved["actual"]["window_id"], self.inspect(self.anchor)["window_id"])
            self.assertEqual(moved["actual"]["focused_block_id"], pane["block_id"])
            self.assertEqual(len(self.view()["windows"]), len(before["windows"]) - 1)
            self.assertEqual({b["block_id"] for b in self.rpc("session.list_blocks", {"session_id": self.session})["blocks"]}, blocks_before)
            after_process = self.rpc("com.superlogical.terminal.process", {"session_id": self.session, "block_id": pane["block_id"], "args": {}})
            self.assertEqual(after_process["child"]["pid"], process["child"]["pid"])
            capture = self.rpc("com.superlogical.terminal.format", {"session_id": self.session, "block_id": pane["block_id"], "args": {"format": "text", "max_bytes": 2048}})
            self.assertIn("same terminal process", capture["content"])

    def test_existing_unfocused_pane_moves_without_changing_focus(self):
        pane = self.open("tiled", extra=["--ratio", ".21"])["actual"]
        self.anchor = self.open("tab")["actual"]["block_id"]
        before = self.view()
        r, moved = self.run_json(self.move_command(pane["block_id"], ratio=".31"))
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(moved["outcome"], "moved_and_verified")
        self.assertFalse(moved["focus_requested"])
        self.rect(moved["actual"]["rect"], [.69, 0, .31, 1])
        after = self.view()
        self.assertEqual(after["active_window_id"], before["active_window_id"])
        self.assertEqual({w["window_id"]: w.get("focused_block_id") for w in after["windows"]},
                         {w["window_id"]: w.get("focused_block_id") for w in before["windows"]})

    def test_lost_move_receipt_is_uncertain_without_recreate_or_retry(self):
        pane = self.open("tab")["actual"]
        before = self.view()
        self.shim("import json,subprocess,sys\n"
                  f"r=subprocess.run([{self.rex!r},*sys.argv[1:]],capture_output=True,check=True)\n"
                  "for line in r.stdout.splitlines():\n"
                  " if json.loads(line)['event']=='attempt':sys.stdout.buffer.write(line+b'\\n')\n"
                  "sys.stdout.flush();sys.exit(77)\n")
        r, result = self.run_json(self.move_command(pane["block_id"], focus="yes"))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(result["outcome"], "uncertain")
        self.assertFalse(result["creation_attempted"])
        self.assertTrue(result["control_attempted"])
        self.assertFalse(result["retry_safe"])
        self.assertIsNone(result["actual"])
        self.env["PATH"] = str(Path(self.rex).parent) + os.pathsep + os.environ["PATH"]
        actual = self.inspect(pane["block_id"])
        self.rect(actual["rect"], [.73, 0, .27, 1])
        self.assertEqual(len(self.view()["windows"]), len(before["windows"]) - 1)

    def test_floating_bounds_label_host_and_exact_argv_cwd(self):
        before = self.view()
        output = self.work / "args.json"
        cwd = self.work / "cwd ' α"
        cwd.mkdir()
        args = ["", "α\nnext", "'\"", "$(touch NEVER); >&2", "--"]
        code = f"import os,json,sys;from pathlib import Path;Path({str(output)!r}).write_text(json.dumps([os.getcwd(),sys.argv[1:]]));print('REAL TERMINAL CONTENT α',flush=True)"
        v = self.open("float", sys.executable, "-c", code, *args, label="inbox ' α",
                      extra=["--bounds", "[0.61,0.07,0.34,0.81]", "--cwd", str(cwd)])
        a = v["actual"]
        self.assertEqual(a["layer_kind"], "floating")
        self.assertEqual(a["label"], "inbox ' α")
        self.rect(a["layer_bounds"], [.61, .07, .34, .81])
        self.rect(a["rect"], [.61, .07, .34, .81])
        self.assertEqual(self.view()["active_window_id"], before["active_window_id"])
        for _ in range(100):
            if output.exists():
                break
            time.sleep(.02)
        self.assertEqual(json.loads(output.read_text()), [str(cwd.resolve()), args])
        capture = self.rpc("com.superlogical.terminal.format", {"session_id": self.session, "block_id": a["block_id"],
                           "args": {"format": "text", "max_bytes": 2048}})
        self.assertIn("REAL TERMINAL CONTENT α", capture["content"])
        self.assertEqual(self.inspect(a["block_id"])["rect"], a["rect"])

    def test_tab_empty_session_label_retention_and_no_focus_request(self):
        before = self.view()
        v = self.open("tab", "/bin/echo", "retained exit", label="new visible tab")
        a = v["actual"]
        self.rect(a["rect"], [0, 0, 1, 1])
        self.assertEqual(a["layer_kind"], "tiled")
        self.assertNotEqual(a["window_id"], before["windows"][0]["window_id"])
        after = self.view()
        self.assertEqual(after["active_window_id"], before["active_window_id"])
        self.assertEqual(next(w for w in after["windows"] if w["window_id"] == a["window_id"])["label"], "new visible tab")
        time.sleep(.1)
        self.assertEqual(self.inspect(a["block_id"])["block_id"], a["block_id"])

    def test_refusal_and_bad_geometry_do_not_create(self):
        before = self.view()
        unknown = "block:00000000-0000-0000-0000-000000000000"
        cmd = self.command("tiled")
        cmd[cmd.index("--anchor") + 1] = unknown
        r, v = self.run_json(cmd)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(v["outcome"], "refused")
        self.assertFalse(v["creation_attempted"])
        for extra in [["--ratio", "nan"], ["--ratio", "0"], ["--ratio", "1"], ["--bounds", "[0,0,.3,1]"], ["--direction", "north"]]:
            r = subprocess.run(self.command("tiled", extra=extra), env=dict(self.env, PATH="/missing"), capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, r.stderr + r.stdout)
        for bounds in ["[0,0,0,1]", "[0.8,0,0.3,1]", "[-0.1,0,0.3,1]", "[0,0,1]", "[0,0,1,1,1]"]:
            r = subprocess.run(self.command("float", extra=["--bounds", bounds]), capture_output=True, text=True, env=self.env)
            self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(self.view(), before)
        floating = self.open("float", extra=["--bounds", "[0.67,0,0.33,1]"])["actual"]
        self.anchor = floating["block_id"]
        stable = self.view()
        r, v = self.run_json(self.command("tiled"))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(v["failure_reason"], "anchor_not_tiled")
        self.assertEqual(self.view(), stable)
        self.rpc("session.set_layer_state", {"session_id": self.session, "layer_id": floating["layer_id"], "state": "minimized"})
        r, v = self.run_json(self.command("float", extra=["--bounds", "[0,0,0.2,1]"]))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(v["failure_reason"], "anchor_layer_not_normal")
        self.assertEqual(self.inspect(self.anchor)["layer_state"], "minimized")

    def test_palette_fragment_loaded_as_real_rex_action_no_overwrite(self):
        fragment = self.work / "palette.lua"
        marker = self.work / "palette-result"
        cmd = [BIN, "surfaces", "palette", "--file", str(fragment), "--name", "surface_test",
               "--title", "Open α ' inbox", "--label", "palette α", "--layout", "float", "--bounds", "[0.67,0,0.33,1]",
               "--", "/bin/sh", "-c", 'printf "%s" "$1" > "$2"; sleep 60', "sh", "α ' \"", str(marker)]
        r, v = self.run_json(cmd)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(v["registered_in_running_server"])
        self.assertEqual(fragment.stat().st_mode & 0o777, 0o600)
        original = fragment.read_bytes()
        r, v = self.run_json(cmd)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(fragment.read_bytes(), original)
        check = subprocess.run([self.rex, "config", "check", str(fragment), "--json"], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr + check.stdout)
        self.config.write_text("dofile(" + json.dumps(str(fragment)) + ")\n")
        self.rpc("server.config_reload", {})
        actions = subprocess.check_output(self.base + ["actions", "--json"], text=True)
        self.assertIn("surface_test", actions)
        response = json.loads(subprocess.check_output(self.base + ["do", "--session", self.session, "--block", self.anchor, "surface_test"], text=True))
        self.assertEqual(response["outcome"], "created_and_verified")
        self.assertEqual(response["actual"]["layer_kind"], "floating")
        self.rect(response["actual"]["rect"], [.67, 0, .33, 1])
        for _ in range(100):
            if marker.exists():
                break
            time.sleep(.02)
        self.assertEqual(marker.read_text(), "α ' \"")
        self.config.write_text("")
        self.rpc("server.config_reload", {})

    def prepare_install(self, name="managed_surface"):
        fragment = self.work / (name + ".lua")
        r, _ = self.run_json([BIN, "surfaces", "palette", "--file", str(fragment), "--name", name,
                             "--title", "Managed Surface", "--label", "managed", "--layout", "tab", "--", "/bin/echo", "managed palette program"])
        self.assertEqual(r.returncode, 0)
        cmd = [BIN, "surfaces", "palette", "install", "--socket", str(self.socket), "--init", str(self.config),
               "--file", str(fragment), "--plan", str(self.work / (name + ".plan.json"))]
        return fragment, cmd

    def reset_config(self):
        self.config.write_text("")
        self.rpc("server.config_reload", {})

    def test_palette_managed_plan_apply_preserves_config_and_verifies_action(self):
        self.config.write_text("-- Existing operator config α, preserved exactly.\n")
        self.addCleanup(self.reset_config)
        fragment, cmd = self.prepare_install()
        original = self.config.read_bytes()
        generation = self.rpc("client.keymap", {})["config"]["generation"]
        self.shim("import sys\nsys.exit(91)\n")
        self.env["TEEREX_REX"] = self.rex  # Embedded install must honor the shared explicit Rex pin.
        r, plan = self.run_json(cmd)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(plan["outcome"], "planned")
        self.assertFalse(plan["registered_in_running_server"])
        self.assertEqual(self.config.read_bytes(), original)
        r, applied = self.run_json(cmd + ["--apply", plan["plan_sha256"]])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(applied["outcome"], "registered_and_verified")
        self.assertTrue(applied["registered_in_running_server"])
        self.assertEqual(self.config.read_bytes(), original + plan["plan"]["append_exactly"].encode())
        self.assertEqual(applied["observed_config"]["generation"], generation + 1)
        self.assertEqual(applied["observed_action"]["name"], "managed_surface")
        result = json.loads(subprocess.check_output(self.base + ["do", "--session", self.session, "managed_surface"], text=True))
        self.assertEqual(result["outcome"], "created_and_verified")
        self.assertEqual(result["actual"]["label"], "managed")
        stable = self.config.read_bytes()
        r, _ = self.run_json(cmd + ["--apply", plan["plan_sha256"]])
        self.assertEqual(r.returncode, 1, "no duplicate append on repeated apply")
        self.assertEqual(self.config.read_bytes(), stable)

    def test_palette_plan_rejects_changed_source_init_plan_and_wrong_server_config(self):
        self.addCleanup(self.reset_config)
        for changed in ("source", "init", "plan"):
            self.reset_config()
            fragment, cmd = self.prepare_install("changed_" + changed)
            r, plan = self.run_json(cmd)
            self.assertEqual(r.returncode, 0, r.stdout)
            path = fragment if changed == "source" else self.config if changed == "init" else Path(cmd[-1])
            path.write_bytes(path.read_bytes() + b"\n")
            stable = self.config.read_bytes()
            generation = self.rpc("client.keymap", {})["config"]["generation"]
            r, refused = self.run_json(cmd + ["--apply", plan["plan_sha256"]])
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertFalse(refused["registered_in_running_server"])
            self.assertFalse(refused["config_updated"])
            self.assertEqual(self.config.read_bytes(), stable)
            self.assertEqual(self.rpc("client.keymap", {})["config"]["generation"], generation)
        fragment, cmd = self.prepare_install("wrong_config")
        other = self.work / "not-running-init.lua"
        other.write_text("-- not the running configuration\n")
        cmd[cmd.index("--init") + 1] = str(other)
        r, refused = self.run_json(cmd)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(refused["failure_reason"], "init_is_not_selected_servers_observed_config")
        self.assertEqual(other.read_text(), "-- not the running configuration\n")

    def test_palette_reload_lost_evidence_stays_unregistered_and_keeps_preserved_bytes(self):
        self.addCleanup(self.reset_config)
        fragment, cmd = self.prepare_install("missing_readback")
        original = self.config.read_bytes()
        r, plan = self.run_json(cmd)
        self.assertEqual(r.returncode, 0, r.stdout)
        # The actual selected server loads the real fragment, but its final action evidence is lost.
        self.shim("import json,subprocess,sys\n"
                  f"r=subprocess.run([{self.rex!r},*sys.argv[1:]],capture_output=True)\n"
                  "if r.returncode:sys.stderr.buffer.write(r.stderr);sys.exit(r.returncode)\n"
                  "v=json.loads(r.stdout)\n"
                  f"if 'client.keymap' in sys.argv and 'dofile' in open({str(self.config)!r}).read():v['actions']=[a for a in v.get('actions',[]) if a.get('name')!='missing_readback']\n"
                  "print(json.dumps(v))\n")
        r, result = self.run_json(cmd + ["--apply", plan["plan_sha256"]])
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(result["config_updated"])
        self.assertFalse(result["registered_in_running_server"])
        self.assertFalse(result["automatic_rollback"])
        self.assertEqual(result["failure_reason"], "registration_not_verified")
        self.assertEqual(self.config.read_bytes(), original + plan["plan"]["append_exactly"].encode())

    def shim(self, source):
        directory = self.work / "shim"
        directory.mkdir(exist_ok=True)
        path = directory / "rex"
        path.write_text(f"#!{sys.executable}\n" + source)
        path.chmod(0o755)
        self.env["PATH"] = str(directory) + os.pathsep + self.env["PATH"]

    def test_lost_receipt_is_uncertain_without_retry_or_close(self):
        before = self.view()
        self.shim("import json,subprocess,sys\n"
                  f"r=subprocess.run([{self.rex!r},*sys.argv[1:]],capture_output=True,check=True)\n"
                  "for line in r.stdout.splitlines():\n"
                  " if json.loads(line)['event']=='attempt':sys.stdout.buffer.write(line+b'\\n')\n"
                  "sys.stdout.flush();sys.stderr.buffer.write(b'\\xff\\x00');sys.exit(77)\n")
        r, v = self.run_json(self.command("tab"))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(v["outcome"], "uncertain")
        self.assertIsNone(v["created"])
        self.assertIsNone(v["actual"])
        self.assertFalse(v["retry_safe"])
        self.assertEqual(base64.b64decode(v["backend_stderr_base64"]), b"\xff\x00")
        self.assertEqual(len(self.view()["windows"]), len(before["windows"]) + 1)

    def test_actual_mismatch_and_missing_readback_never_claim_success(self):
        # Execute real creation, then alter/drop only the evidence at the transport boundary.
        for alteration, expected in [("v['result']['outcome']='geometry_mismatch';v['result']['requested_geometry_verified']=False", "geometry_mismatch"),
                                     ("v['result'].pop('actual',None);v['result']['outcome']='uncertain';v['result']['failure_reason']='created_geometry_unavailable'", "uncertain")]:
            self.shim("import json,subprocess,sys\n"
                      f"r=subprocess.run([{self.rex!r},*sys.argv[1:]],capture_output=True,check=True)\n"
                      "for line in r.stdout.splitlines():\n"
                      " v=json.loads(line)\n"
                      f" if v['event']=='result': {alteration}\n"
                      " print(json.dumps(v),flush=True)\n")
            r, v = self.run_json(self.command("tab"))
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertEqual(v["outcome"], expected)
            self.assertIsNotNone(v["created"])
            if expected == "uncertain":
                self.assertIsNone(v["actual"])

    def test_deadline_cancellation_missing_endpoint_and_help(self):
        ready = self.work / "ready"
        self.shim("import signal,time\nfrom pathlib import Path\n"
                  f"Path({str(ready)!r}).touch()\n"
                  "signal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(60)\n")
        for sig, expected in [(None, 124), (signal.SIGINT, 130), (signal.SIGTERM, 143)]:
            ready.unlink(missing_ok=True)
            p = subprocess.Popen(self.command("tab", extra=["--timeout-ms", "200" if sig is None else "5000"]),
                                 env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if sig is not None:
                for _ in range(100):
                    if ready.exists():
                        break
                    time.sleep(.01)
                self.assertTrue(ready.exists())
                p.send_signal(sig)
            out, err = p.communicate(timeout=4)
            self.assertEqual(p.returncode, expected, err)
            self.assertNotEqual(json.loads(out)["outcome"], "created_and_verified")
        self.env["PATH"] = str(Path(self.rex).parent) + os.pathsep + os.environ["PATH"]
        cmd = self.command("tab")
        cmd[cmd.index("--socket") + 1] = str(self.work / "missing.sock")
        r, v = self.run_json(cmd)
        self.assertEqual(r.returncode, 1)
        self.assertFalse((self.work / "missing.sock").exists())
        self.assertEqual(v["outcome"], "uncertain")
        for args in [["--help"], ["open", "--help"], ["inspect", "--help"], ["palette", "--help"]]:
            r = subprocess.run([BIN, "surfaces", *args], capture_output=True, text=True, env=self.env)
            self.assertEqual(r.returncode, 0)
            self.assertIn("NEW pane share", r.stdout)


if __name__ == "__main__":
    unittest.main()
