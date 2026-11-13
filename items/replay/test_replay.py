"""Replay/live public-CLI acceptance. All integration runs use a private Rex."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from wire import Control
from facts import evaluate

BIN = str(Path(os.environ.get("TEEREX_BIN", "zig-out/bin/teerex")).resolve())
FAKE = str(Path(__file__).with_name("fake_tui.py").resolve())


class Replay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="replay-tests-", dir="/tmp")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.sock = cls.root / "rex.sock"
        cls.rex = os.environ.get("REX_BIN") or shutil.which("rex")
        if not cls.rex:
            raise RuntimeError("REX_BIN required")
        cls.log = (cls.root / "server.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen([cls.rex, "server", "run", "--listen", "unix://" + str(cls.sock),
            "--restore=false", "--config", "/dev/null", "--state-dir", str(cls.root / "state")], stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            if cls.sock.exists():
                break
            if cls.server.poll() is not None:
                raise RuntimeError("private Rex failed")
            time.sleep(.05)
        cls.control = Control(cls.sock)
        cls.addClassCleanup(cls.control.close)
        print("Replay Rex:", cls.control.call("server.version", {}), flush=True)

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    def setUp(self):
        self.work = self.root / str(time.monotonic_ns())
        self.work.mkdir()
        self.session = self.control.call("session.create", {"label": "private replay acceptance"})["session_id"]
        def destroy():
            self.control.call("session.attach", {"session_id": self.session})
            self.control.call("session.destroy", {"session_id": self.session})
        self.addCleanup(destroy)
        self.counter = 0

    def path(self, name):
        self.counter += 1
        return self.work / (str(self.counter) + "-" + name)

    def invoke(self, mode, options, argv=(), code=0):
        command = [BIN, "replay", mode, "--socket", str(self.sock), "--session", self.session, "--timeout-ms", "7000", *map(str, options)]
        if argv:
            command += ["--", *map(str, argv)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15,
             env=dict(os.environ, TEEREX_INTERNAL_REX=self.rex, PATH=str(Path(self.rex).parent) + os.pathsep + os.environ.get("PATH", "")))
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["mode"], mode)
        self.assertEqual(value["task_completion"], "not_assessed")
        if value["target"]["block_id"]:
            self.assertTrue(value["cleanup"]["block_absence_verified"], value)
        return value

    def fake(self, scene, behaviour="v1"):
        return [sys.executable, FAKE, "--scene", scene, "--behaviour", behaviour, "--workdir", str(self.work)]

    def record(self, scene):
        output = self.path("fixture")
        value = self.invoke("record", ["--layout", "offstage", "--out", output, "--id", scene, "--allow-sensitive-capture"], self.fake(scene))
        self.assertEqual(value["stream"]["end"], "child_exited")
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)
        self.assertEqual((output / "stream.bin").stat().st_mode & 0o777, 0o600)
        return output

    def play(self, fixture, facts, code=0, extra=()):
        path = self.path("facts.json")
        path.write_text(json.dumps(dict(schema_version=1, kind="teerex_display_facts", id="manual", authored_by="manual", at=facts)))
        return self.invoke("play", ["--fixture", fixture, "--facts", path, "--observations-out", self.path("observations"), *extra], code=code)

    def test_split_utf8_fidelity_and_corrupt_display(self):
        fixture = self.record("utf8-split")
        manifest = json.loads((fixture / "fixture.json").read_text())
        data = (fixture / "stream.bin").read_bytes()
        self.assertEqual(data, "naïve ✓ 日本\r\n".encode(), "record must contain program bytes only, without login banners")
        tick = data.index("✓".encode())
        self.assertIn(tick + 1, [offset + length for offset, length, _ in manifest["chunks"]])
        facts = {"end": [dict(id="tick", capture_contains="✓"), dict(id="valid", capture_not_contains="�")]}
        result = self.play(fixture, facts)
        self.assertTrue(result["stream_check"]["equal"])
        broken = self.path("corrupted")
        shutil.copytree(fixture, broken)
        raw = data[:tick + 1] + data[tick + 2:]
        manifest["stream"].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        manifest["chunks"] = [[0, len(raw), 0]]
        for event in manifest["events"]:
            if event["offset"] > tick:
                event["offset"] -= 1
        manifest["checkpoints"] = [dict(id="end", offset=len(raw))]
        (broken / "stream.bin").write_bytes(raw)
        (broken / "fixture.json").write_text(json.dumps(manifest))
        result = self.play(broken, facts, 3)
        self.assertTrue(result["stream_check"]["equal"])
        self.assertEqual(result["outcome"], "facts_failed")

    def test_error_done_does_not_mean_exit_zero(self):
        fixture = self.record("multiline-error")
        facts = {"end": [dict(id="lines", capture_lines_in_order=["error: config invalid", "  at line 3", '  expected "="']),
                         dict(id="exit", child_exit_code=2), dict(id="report", status_state="done")]}
        self.play(fixture, facts)
        facts["end"].append(dict(id="wrong", child_exit_code=0))
        self.assertEqual(self.play(fixture, facts, 3)["outcome"], "facts_failed")

    def test_foreign_apc_is_program_output(self):
        fixture = self.record("lookalike")
        self.assertIn(b"rex1;12345", (fixture / "stream.bin").read_bytes())
        manifest = json.loads((fixture / "fixture.json").read_text())
        self.assertEqual([e["exit_code"] for e in manifest["events"] if e["type"] == "child_exited"], [0])

    def test_replay_pass_never_satisfies_live(self):
        script = dict(schema_version=1, kind="teerex_live_script", id="confirm", model_turns=0, steps=[
            dict(expect=[dict(id="prompt", capture_contains="Delete 3 files? [y/N]")], within_ms=1000),
            dict(write="n"), dict(expect=[dict(id="aborted", capture_contains="Aborted."), dict(id="exit", child_exit_code=0)], within_ms=2000),
            dict(effect=dict(path_exists="victims/a.txt", relative_to="cwd"))])
        path = self.path("script.json")
        path.write_text(json.dumps(script))
        fixture = self.path("live-fixture")
        result = self.invoke("live", ["--script", path, "--observations-out", self.path("live-observations"), "--cwd", self.work,
                                      "--record-out", fixture, "--allow-sensitive-capture"], self.fake("confirm"))
        self.assertEqual(result["outcome"], "live_pass")
        self.play(fixture, {"end": [dict(id="prompt", capture_contains="[y/N]"), dict(id="aborted", capture_contains="Aborted.")]})
        result = self.invoke("live", ["--script", path, "--observations-out", self.path("v2-observations"), "--cwd", self.work], self.fake("confirm", "v2"), code=3)
        self.assertEqual(result["outcome"], "live_divergence")
        script["steps"] = [dict(expect=[dict(id="ready", capture_contains="Delete 3 files?")], within_ms=2000), dict(write="n"), dict(expect=[dict(id="exit", child_exit_code=0)], within_ms=2000), script["steps"][-1]]
        path.write_text(json.dumps(script))
        result = self.invoke("live", ["--script", path, "--observations-out", self.path("effect-observations"), "--cwd", self.work], self.fake("confirm", "v2"), code=3)
        self.assertFalse(result["steps"][-1]["facts"][0]["value"])

    def test_resize_prompt_checkpoint_and_live_resize(self):
        path = self.path("resize.json")
        path.write_text(json.dumps(dict(schema_version=1, kind="teerex_live_script", id="resize", model_turns=0, steps=[
            dict(expect=[dict(id="prompt", capture_contains="❯")], within_ms=2000),
            dict(resize=dict(columns=60, rows=20)),
            dict(expect=[dict(id="size", size=dict(columns=60, rows=20)), dict(id="prompt", capture_contains="❯")], within_ms=2000),
            dict(write="q"), dict(expect=[dict(id="exit", child_exit_code=0)], within_ms=2000)])))
        fixture = self.path("resize-fixture")
        self.invoke("live", ["--script", path, "--observations-out", self.path("resize-live"), "--record-out", fixture,
                             "--allow-sensitive-capture"], self.fake("resize-prompt"))
        result = self.play(fixture, {"end": [dict(id="size", size=dict(columns=60, rows=20)), dict(id="prompt", capture_contains="❯")]})
        self.assertTrue(result["stream_check"]["equal"])
        manifest = json.loads((fixture / "fixture.json").read_text())
        self.assertTrue(any(e["type"] == "resize" and e["columns"] == 60 for e in manifest["events"]))

    def test_bounded_prefix_unknown_and_full_capture(self):
        fixture = self.path("padding")
        self.invoke("record", ["--layout", "offstage", "--out", fixture, "--id", "padding", "--allow-sensitive-capture"],
                    [sys.executable, "-c", "print('prefix '*1000+'THE-END')"])
        facts = {"end": [dict(id="negative", capture_not_contains="not-present")]}
        result = self.play(fixture, facts, 3, ["--max-bytes", "256"])
        self.assertEqual(result["outcome"], "facts_unknown")
        self.play(fixture, facts, extra=["--max-bytes", "65536"])

    def test_usage_consent_and_needs_authoring(self):
        result = subprocess.run([BIN, "replay", "record", "--socket", str(self.sock), "--session", self.session,
                                  "--out", str(self.path("no-consent")), "--id", "unsafe", "--", "/bin/echo"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        path = self.path("unwritten.json")
        path.write_text(json.dumps(dict(schema_version=1, kind="teerex_live_script", id="unwritten", model_turns=0,
            steps=[dict(expect=[], within_ms=100, needs_authoring=True)])))
        result = self.invoke("live", ["--script", path, "--observations-out", self.path("unwritten-observations")],
                             ["/bin/sleep", "10"], code=3)
        self.assertEqual(result["outcome"], "steps_not_run")
        self.assertEqual(result["not_run"][0]["reason"], "needs_authoring")

    def test_live_foreign_client_refuses_before_creation(self):
        self.control.call("session.attach", {"session_id": self.session})
        path = self.path("empty.json")
        path.write_text(json.dumps(dict(schema_version=1, kind="teerex_live_script", id="empty", model_turns=0, steps=[])))
        value = self.invoke("live", ["--script", path, "--observations-out", self.path("foreign")], ["/bin/sleep", "10"], code=1)
        self.assertEqual(value["outcome"], "foreign_client_attached")
        self.assertIsNone(value["target"]["block_id"])

    def test_committed_fixtures_are_synthetic_and_regenerate(self):
        subprocess.run([sys.executable, str(Path(__file__).with_name("gen_fixtures.py")), "--check"], check=True, timeout=10)
        fixtures = Path(__file__).with_name("fixtures")
        for fixture in sorted(fixtures.iterdir()):
            with self.subTest(fixture=fixture.name):
                manifest = json.loads((fixture / "fixture.json").read_text())
                self.assertEqual(manifest["provenance"]["basis"], "synthetic")
                self.play(fixture, {})

    def test_progress_checkpoints_compare_and_filter_preserve_changes(self):
        fixture = Path(__file__).with_name("fixtures") / "progress"
        facts = {"part-0": [dict(id="first", capture_contains="25%")],
                 "part-1": [dict(id="second", capture_contains="50%")],
                 "part-2": [dict(id="third", capture_contains="100%")], "end": []}
        result = self.play(fixture, facts)
        observations = [x["observation_path"] for x in result["checkpoints"][:3]]
        compared = subprocess.run([BIN, "compare", "--before", observations[0], "--after", observations[1]], capture_output=True, text=True, timeout=5)
        self.assertEqual(compared.returncode, 0, compared.stderr)
        self.assertTrue(json.loads(compared.stdout)["capture"]["captured_text_changed"])
        command = [BIN, "filter"]
        for path in observations:
            command += ["--sample", path]
        filtered = subprocess.run(command, capture_output=True, text=True, timeout=5)
        self.assertEqual(filtered.returncode, 0, filtered.stderr)
        values = [json.loads(line) for line in filtered.stdout.splitlines()]
        self.assertNotIn("cosmetic", values[-1])
        self.assertEqual(values[-1]["observation_payloads_omitted"], 0)

    def test_sigterm_cleans_created_player(self):
        fixture = Path(__file__).with_name("fixtures") / "progress"
        # Recorded pacing leaves an observable cancellation window.
        command = [BIN, "replay", "play", "--socket", str(self.sock), "--session", self.session,
                   "--fixture", str(fixture.resolve()), "--observations-out", str(self.path("cancel")), "--pace", "recorded"]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.control.call("session.attach", {"session_id": self.session})
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                blocks = self.control.call("session.list_blocks", {"session_id": self.session})["blocks"]
                if blocks:
                    break
                time.sleep(.005)
            self.assertTrue(blocks, "player never created")
            process.terminate()
            stdout, stderr = process.communicate(timeout=8)
            self.assertEqual(process.returncode, 143, stdout + stderr)
            self.assertTrue(json.loads(stdout)["cleanup"]["block_absence_verified"])
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=3)

    def test_record_default_tab_and_cwd(self):
        fixture = self.path("tab-record")
        self.invoke("record", ["--out", fixture, "--id", "tab", "--allow-sensitive-capture", "--cwd", self.work],
                    [sys.executable, "-c", "import os; print(os.getcwd())"])
        self.assertEqual((str(self.work.resolve()) + "\r\n").encode(), (fixture / "stream.bin").read_bytes(), "tab launch must also be silent")

    def test_resize_owner_contention_refuses(self):
        fixture = self.path("contended-fixture")
        shutil.copytree(Path(__file__).with_name("fixtures") / "resize-prompt", fixture)
        manifest = json.loads((fixture / "fixture.json").read_text())
        manifest["chunks"][1][2] = 1000
        manifest["events"][1]["t_ms"] = 1000
        (fixture / "fixture.json").write_text(json.dumps(manifest))
        command = [BIN, "replay", "play", "--socket", str(self.sock), "--session", self.session,
                   "--fixture", str(fixture), "--observations-out", str(self.path("contended")), "--pace", "recorded"]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.control.call("session.attach", {"session_id": self.session})
            deadline = time.monotonic() + 5
            block = None
            while time.monotonic() < deadline:
                blocks = self.control.call("session.list_blocks", {"session_id": self.session})["blocks"]
                if blocks:
                    candidate = blocks[0]["block_id"]
                    packet = self.control.call("com.superlogical.terminal.format", dict(session_id=self.session, block_id=candidate, args=dict(format="text")))
                    if "❯" in packet.get("content", ""):
                        block = candidate
                        break
                time.sleep(.005)
            self.assertTrue(block, "first checkpoint did not render")
            self.control.call("session.own_block", dict(session_id=self.session, block_ids=[block], mode="take"))
            self.control.call("com.superlogical.terminal.resize", dict(session_id=self.session, block_id=block, args=dict(columns=80, rows=24)))
            stdout, stderr = process.communicate(timeout=8)
            self.assertEqual(process.returncode, 1, stdout + stderr)
            value = json.loads(stdout)
            self.assertEqual(value["outcome"], "resize_not_applied")
            self.assertTrue(value["cleanup"]["block_absence_verified"])
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=3)

    def test_not_blank_refuses_without_fixture(self):
        # Deliberately noisy gate exercises the real blank-start read, not a
        # fake format response. Only the gate changes; private wire/server stay real.
        directory = str(Path(__file__).parent.resolve())
        output = self.path("not-blank")
        script = """import sys,time
sys.path.insert(0,sys.argv[1])
import replay,wire
replay.Control=wire.Control
replay.data_resume=wire.data_resume
replay.GATE="print('NOISY GATE',flush=True)\\n"+replay.GATE
def after_noise(control,path,session,block):
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        result=control.call('com.superlogical.terminal.format',dict(session_id=session,block_id=block,args=dict(format='text')))
        if 'NOISY GATE' in result.get('content',''):
            return wire.data_connect(control,path,session,block)
        time.sleep(.01)
    raise RuntimeError('noisy fixture did not print')
replay.data_connect=after_noise
sys.exit(replay.main(sys.argv[3:],sys.argv[2],''))
"""
        command = [sys.executable, "-c", script, directory, BIN, "record", "--socket", str(self.sock),
                   "--session", self.session, "--layout", "offstage", "--out", str(output), "--id", "noisy", "--allow-sensitive-capture", "--", "/bin/echo", "never"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["outcome"], "not_blank")
        self.assertTrue(value["cleanup"]["block_absence_verified"])
        self.assertFalse(output.exists())

    def test_fifo_input_is_bounded_and_refused_before_creation(self):
        path = self.path("fifo")
        os.mkfifo(path)
        value = self.invoke("live", ["--script", path, "--observations-out", self.path("unused-fifo")], ["/bin/echo"], code=1)
        self.assertEqual(value["outcome"], "input_size_or_type_limit")
        self.assertIsNone(value["target"]["block_id"])

    def test_malformed_scripts_refuse_before_creation(self):
        bad_steps = [dict(checkpoint="../escape"), dict(resize=[]), dict(key=5),
                     dict(write="x", local_only=True), dict(effect=dict(file_sha256="file", relative_to="cwd"))]
        documents = [[], *[dict(schema_version=1, kind="teerex_live_script", id="bad", model_turns=0, steps=[step]) for step in bad_steps]]
        for document in documents:
            with self.subTest(document=document):
                path = self.path("malformed.json")
                path.write_text(json.dumps(document))
                result = self.invoke("live", ["--script", path, "--observations-out", self.path("bad-observations")], ["/bin/echo"], code=1)
                self.assertIsNone(result["target"]["block_id"])

    def test_forced_loss_wrong_resume_publishes_incomplete_fixture(self):
        directory = str(Path(__file__).parent.resolve())
        output = self.path("stream-lost")
        script = """import sys,socket
sys.path.insert(0,sys.argv[1])
import replay,wire
replay.Control=wire.Control
replay.data_connect=wire.data_connect
replay.data_resume=wire.data_resume
original=replay.Stream.pump
def fault(self,wait=.1):
    original(self,wait)
    if self.data and not self.end and not getattr(self,'injected',False):
        self.injected=True
        self.received_bytes+=1
        self.ws.sock.shutdown(socket.SHUT_RDWR)
replay.Stream.pump=fault
sys.exit(replay.main(sys.argv[3:],sys.argv[2],''))
"""
        command = [sys.executable, "-c", script, directory, BIN, "record", "--socket", str(self.sock),
                   "--session", self.session, "--layout", "offstage", "--out", str(output), "--id", "loss", "--allow-sensitive-capture", "--",
                   sys.executable, "-c", "import time;print('before loss',flush=True);time.sleep(10)"]
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["stream"]["end"], "stream_lost")
        self.assertFalse(value["stream"]["complete"])
        self.assertTrue(value["cleanup"]["block_absence_verified"])
        self.assertEqual(self.play(output, {}, 1)["outcome"], "fixture_incomplete")

    def test_model_guard_before_creation(self):
        path = self.path("unsafe.json")
        path.write_text(json.dumps(dict(schema_version=1, kind="teerex_live_script", id="unsafe", model_turns=0, steps=[dict(write="hi\r")])))
        result = self.invoke("live", ["--script", path, "--observations-out", self.path("unused")], self.fake("confirm"), code=1)
        self.assertEqual(result["outcome"], "script_submits_without_local_only")
        self.assertIsNone(result["target"]["block_id"])

    def test_incomplete_hash_and_existing_output_refuse(self):
        fixture = self.record("utf8-split")
        manifest = json.loads((fixture / "fixture.json").read_text())
        manifest["stream"]["complete"] = False
        (fixture / "fixture.json").write_text(json.dumps(manifest))
        self.assertEqual(self.play(fixture, {}, 1)["outcome"], "fixture_incomplete")
        manifest["stream"]["complete"] = True
        (fixture / "fixture.json").write_text(json.dumps(manifest))
        (fixture / "stream.bin").write_bytes(b"tampered")
        self.assertEqual(self.play(fixture, {}, 1)["outcome"], "fixture_hash_mismatch")
        result = self.invoke("record", ["--out", fixture, "--id", "exists", "--allow-sensitive-capture"], self.fake("utf8-split"), code=1)
        self.assertEqual(result["outcome"], "output_exists")


class RealTuiLive(unittest.TestCase):
    setUpClass = classmethod(Replay.setUpClass.__func__)
    stop_server = classmethod(Replay.stop_server.__func__)
    setUp = Replay.setUp
    path = Replay.path
    invoke = Replay.invoke
    # Explicitly select this class; ordinary synthetic CI never starts real harnesses.
    def test_local_only_startup(self):
        selected = [x for x in os.environ.get("TEEREX_REPLAY_REAL", "").split(",") if x]
        if not selected:
            self.skipTest("set TEEREX_REPLAY_REAL=claude,codex,pi to opt in")
        for name in selected:
            if name not in {"claude", "codex", "pi"}:
                self.fail("unknown real TUI selector")
            executable = shutil.which(name)
            self.assertTrue(executable, name + " is not installed")
            fresh = self.path(name + "-cwd")
            fresh.mkdir()
            with self.subTest(application=name):
                script = Path(__file__).with_name("scripts") / (name + ".json")
                result = self.invoke("live", ["--script", script.resolve(), "--cwd", fresh,
                    "--observations-out", self.path(name + "-private-observations"), "--timeout-ms", "13000"], [executable], code=3)
                # The program may diverge on a login/trust screen. Never count that as readiness.
                print("Real TUI", name, "outcome", result["outcome"], "facts", [x["facts"] for x in result["steps"]], flush=True)
                self.assertIn(result["outcome"], {"steps_not_run", "live_divergence"})
                if name == "claude":
                    decline = Path(__file__).with_name("scripts") / "claude-trust-decline.json"
                    declined = self.invoke("live", ["--script", decline.resolve(), "--cwd", fresh,
                        "--observations-out", self.path("claude-decline"), "--timeout-ms", "13000"], [executable])
                    print("Real TUI claude trust-decline outcome", declined["outcome"], flush=True)


class FactContract(unittest.TestCase):
    def test_hidden_tail_and_missing_records_are_unknown(self):
        packet = dict(capture=dict(content="prefix", complete=False))
        result = evaluate([dict(id="present", capture_contains="prefix"), dict(id="hidden", capture_contains="tail"),
                           dict(id="absent", capture_not_contains="tail"), dict(id="process", process_running=False),
                           dict(id="status", status_state="done"), dict(id="exit", child_exit_code=0)], packet)
        self.assertEqual([r["value"] for r in result], [True, "unknown", "unknown", "unknown", "unknown", "unknown"])


if __name__ == "__main__":
    unittest.main()
