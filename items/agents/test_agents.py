"""Public lifecycle checks against disposable Rex; no personal endpoints or real paid agents.

TEEREX_BIN must dispatch agents/spawn/jobs/send. REX_BIN selects the fixture's exact executable.
"""
import errno
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

BIN = str(Path(os.environ.get("TEEREX_BIN", "zig-out/bin/teerex")).resolve())
REX = os.environ.get("REX_BIN")

# A synthetic interactive agent consumes exact PTY input; only it executes the explicit ACK command.
# No screen-scraped token, transport receipt or creation receipt stands in for the ACK.
FIXTURE = r'''
import json, os, shlex, signal, subprocess, sys, termios, time, tty
from pathlib import Path
out, behavior = Path(sys.argv[1]), sys.argv[2]
tty.setraw(0, termios.TCSANOW)
os.write(1,b'\x1b[?2004h')
args=sys.argv[3:]
protocol=args[-1] if args and "Messaging protocol (not a task brief):" in args[-1] else None
with out.open("a") as f:
    f.write(json.dumps({"event":"started", "pid":os.getpid(), "argv":args[:-1] if protocol else args,
                        "cwd":os.getcwd(), "stdin_tty":os.isatty(0),
                        "registry_present":Path(os.environ.get("AGENT_REGISTRY","/nonexistent")).exists(),
                        "env":{k:v for k,v in os.environ.items() if k.startswith(("AGENT_", "LC_"))}}) + "\n"); f.flush()
if protocol:
    with out.open("a") as f: f.write(json.dumps({"event":"protocol_argument","payload":protocol})+"\n")
    if behavior != "noack":
        line=protocol.split("Acknowledge this protocol now by running:\n",1)[1].split("\n",1)[0]
        if behavior == "remote-exit7":
            for key,value in (("--token","0"*64),("--block",os.environ['AGENT_STARTER'].split()[1])):
                wrong=shlex.split(line); wrong[wrong.index(key)+1]=value
                result=subprocess.run(wrong,capture_output=True,text=True)
                with out.open('a') as f: f.write(json.dumps({"event":"wrong-ack","code":result.returncode,"stdout":result.stdout})+'\n')
        if behavior == "lateack": time.sleep(1)
        result=subprocess.run(shlex.split(line),capture_output=True,text=True)
        with out.open("a") as f: f.write(json.dumps({"event":"ack","code":result.returncode,"stdout":result.stdout})+"\n")
        if behavior == "channel":
            client=shlex.split(line)
            client=client[:client.index("--request-id")]
            cmd=client+["--request-id","a"*32,"--operation","send","--to","report-to","--message-file","-"]
            for unused in range(2):
                result=subprocess.run(cmd,input="fenced β: quotes '\"\nlast line\n\n",capture_output=True,text=True)
                with out.open("a") as f: f.write(json.dumps({"event":"channel-result","code":result.returncode,"stdout":result.stdout})+"\n")
            hook=json.loads(args[args.index('--settings')+1])['hooks']['Stop'][0]['hooks'][0]['command']
            result=subprocess.run(hook,shell=True,
                                  input=json.dumps({"hook_event_name":"Stop","last_assistant_message":"fenced turn complete β"}),
                                  capture_output=True,text=True)
            with out.open("a") as f: f.write(json.dumps({"event":"channel-stop","code":result.returncode,"stdout":result.stdout})+"\n")
        if behavior == "remote-exit7":
            settings=json.loads(args[args.index("--settings")+1])
            transcript=Path('/work/transcript.jsonl')
            transcript.write_text(json.dumps({"type":"assistant","message":{"content":[{"type":"text","text":"remote transcript β '\""}]}})+'\n')
            for kind in ('Stop','StopFailure'):
                event={"hook_event_name":kind,"transcript_path":str(transcript),"error":"remote failure β"}
                command=settings['hooks'][kind][0]['hooks'][0]['command']
                result=subprocess.run(command,shell=True,input=json.dumps(event),capture_output=True,text=True)
                with out.open('a') as f: f.write(json.dumps({"event":"remote-hook","kind":kind,"code":result.returncode,"stdout":result.stdout})+'\n')
            report_line=protocol.split('Supply report bytes on stdin then EOF using:\n',1)[1].split('\n',1)[0]
            result=subprocess.run(shlex.split(report_line),input='remote direct reply β\n\n',capture_output=True,text=True)
            with out.open('a') as f: f.write(json.dumps({"event":"remote-reply","code":result.returncode,"stdout":result.stdout})+'\n')
buf=b""
while True:
    part=os.read(0,65536)
    if not part: break
    buf+=part
    while b"\x1b[201~\r" in buf:
        raw,buf=buf.split(b"\x1b[201~\r",1)
        payload=raw.removeprefix(b"\x1b[200~").decode()
        with out.open("a") as f: f.write(json.dumps({"event":"input","payload":payload})+"\n")
        if "TASK β asymmetric" in payload and behavior in ("exit7", "remote-exit7"):
            sys.exit(7)
'''


def wait_for(fn, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(.03)
    raise AssertionError("fixture condition not met")


def events(path):
    return [json.loads(v) for v in path.read_text().splitlines()] if path.exists() else []


class AgentsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not REX:
            raise RuntimeError("Select the disposable test Rex with REX_BIN")
        cls.temp = tempfile.TemporaryDirectory(prefix="tagents-", dir="/tmp")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.socket = cls.root / "rex.sock"
        cls.base = [REX, "--autostart=false", "--server", "unix://" + str(cls.socket), "--timeout", "3s"]
        cls.log = (cls.root / "server.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen([REX, "server", "run", "--listen", "unix://" + str(cls.socket),
                                       "--restore=false", "--config", "/dev/null", "--state-dir", str(cls.root / "state")],
                                      stdout=cls.log, stderr=cls.log,
                                      env=dict(os.environ, PATH=str(Path(REX).parent) + os.pathsep + os.environ.get("PATH", "")))
        cls.addClassCleanup(cls.stop_server)
        wait_for(lambda: cls.socket.exists())
        cls.version = cls.rpc("server.version", {})
        print("Real Rex:", json.dumps(cls.version), flush=True)

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
        self.registry = self.work / "registry"
        self.registry.mkdir(mode=0o700)
        self.worker_log = self.work / "worker.jsonl"
        self.starter_log = self.work / "starter.jsonl"
        self.fixture = self.work / "fixture.py"
        self.fixture.write_text(FIXTURE)
        target = json.loads(subprocess.check_output(self.base + ["new", "--json", "--keep-open", "--shell=none", "--",
                                                                 sys.executable, str(self.fixture), str(self.starter_log), "noack"], timeout=10))
        self.session = target["session_id"]
        self.starter = target["initial_windows"][0]["block_ids"][0]
        wait_for(lambda: events(self.starter_log))
        self.env = dict(os.environ, PATH=str(Path(REX).parent) + os.pathsep + os.environ.get("PATH", ""),
                        REX_SERVER="unix:///tmp/poison.sock", REX_SESSION="session:poison", REX_BLOCK="block:poison")
        self.config = self.work / "profiles.json"
        self.settings = dict(schema_version=1, defaults=dict(registry=str(self.registry), socket=str(self.socket),
                             session=self.session, cwd=str(self.work), starter_session=self.session, starter_block=self.starter,
                             host="disposable", owner="operator", purpose="asymmetric lifecycle regression", review_after_ms=60000),
                             profiles=dict(probe=dict(argv=[sys.executable, str(self.fixture), str(self.worker_log), "ack"],
                                                      harness="synthetic", protocol_mode="argument", standing_flags=["--explicit-standing-flag"])))
        self.config.write_text(json.dumps(self.settings))
        self.brief = self.work / "brief.txt"
        self.brief.write_text("TASK β asymmetric\nPreserve quotes '\" and final newline.\n")

    def run_cli(self, *args, timeout=15, **kwargs):
        p = subprocess.run([BIN, "agents", *args], text=True, capture_output=True, env=self.env, timeout=timeout, **kwargs)
        return p, json.loads(p.stdout) if p.stdout.strip().startswith("{") else None

    def launch(self, behavior="ack", ack_timeout=2000):
        self.settings["profiles"]["probe"]["argv"][-1] = behavior
        self.config.write_text(json.dumps(self.settings))
        return self.run_cli("launch", "--config", str(self.config), "--profile", "probe", "--brief-file", str(self.brief),
                            "--ack-timeout-ms", str(ack_timeout))

    def record(self, launch_id):
        return json.loads((self.registry / ("agents-" + launch_id + ".json")).read_text())

    def test_protocol_before_brief_exact_metadata_and_jobs(self):
        self.settings["profiles"]["probe"]["standing_flags"] *= 2
        p, packet = self.launch()
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual(packet["outcome"], "brief_submitted")
        self.assertEqual(packet["agent_readiness"], "not_assessed")
        self.assertFalse(packet["exclusive_input_lease"])
        self.assertNotIn("token", packet)
        state = self.record(packet["launch_id"])
        worker = wait_for(lambda: events(self.worker_log) if len(events(self.worker_log)) >= 4 else None)
        inputs = [v["payload"] for v in worker if v["event"] in ("protocol_argument", "input")]
        self.assertEqual(len(inputs), 2)
        self.assertIn("Messaging protocol (not a task brief):", inputs[0])
        self.assertNotIn("TASK β", inputs[0])
        self.assertEqual(inputs[1], "FROM probe: " + self.brief.read_text())
        self.assertEqual([v["code"] for v in worker if v["event"] == "ack"], [0])
        env = worker[0]["env"]
        expected = dict(AGENT_SESSION=self.session, AGENT_PANE=state["target"]["block_id"], AGENT_NAME="probe",
                        AGENT_STARTER=self.session + " " + self.starter, AGENT_REPORT_TO=self.session + " " + self.starter)
        for k, v in expected.items():
            self.assertEqual(env[k], v)
            self.assertEqual(env["LC_" + k], v)
        self.assertEqual(worker[0]["argv"], ["--explicit-standing-flag"])
        jobs = json.loads(subprocess.check_output([BIN, "jobs", "list", "--registry", str(self.registry)], env=self.env))
        self.assertEqual(len(jobs["entries"]), 1)
        self.assertEqual(jobs["entries"][0]["block_id"], state["target"]["block_id"])
        self.assertEqual(jobs["entries"][0]["owner"], "operator")
        self.assertEqual(jobs["entries"][0]["deadline_unix_ms"], state["review_at"])
        view = self.rpc("session.view", {"session_id": self.session})
        self.assertEqual(len(view["windows"]), 2)
        self.assertTrue(any(b["block_id"] == state["target"]["block_id"] for w in view["windows"]
                            for layer in w["layers"] for b in layer["blocks"]))
        p, again = self.run_cli("deliver", "--registry", str(self.registry), "--launch-id", state["launch_id"])
        self.assertEqual(p.returncode, 1)
        self.assertIn("brief_already_attempted", again["failure_reason"])

    def test_timeout_never_sends_brief_wrong_token_address_and_explicit_continue(self):
        p, packet = self.launch("noack", ack_timeout=250)
        self.assertEqual(p.returncode, 124, p.stderr + p.stdout)
        self.assertEqual(packet["outcome"], "protocol_ack_timeout")
        state = self.record(packet["launch_id"])
        self.assertFalse(state["brief_attempted"])
        def acknowledge(token, block):
            return self.run_cli("ack", "--registry", str(self.registry), "--launch-id", state["launch_id"],
                                "--token", token, "--session", self.session, "--block", block)
        p, failure = acknowledge("0" * 64, state["target"]["block_id"])
        self.assertEqual(p.returncode, 1)
        self.assertIn("token_mismatch", failure["failure_reason"])
        p, failure = acknowledge(state["token"], self.starter)
        self.assertEqual(p.returncode, 1)
        self.assertIn("address_mismatch", failure["failure_reason"])
        self.assertEqual(len([v for v in events(self.worker_log) if v["event"] == "input"]), 0)
        p, _ = self.run_cli("deliver", "--registry", str(self.registry), "--launch-id", state["launch_id"])
        self.assertEqual(p.returncode, 1)
        p, acked = acknowledge(state["token"], state["target"]["block_id"])
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual(acked["outcome"], "protocol_acknowledged")
        p, _ = self.run_cli("deliver", "--registry", str(self.registry), "--launch-id", state["launch_id"])
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        wait_for(lambda: len([v for v in events(self.worker_log) if v["event"] == "input"]) == 1)

    def test_idle_error_hooks_and_real_exit_are_different(self):
        p, packet = self.launch()
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        launch_id = packet["launch_id"]
        transcript = self.work / "transcript.jsonl"
        transcript.write_text("not json\n" + json.dumps(dict(type="assistant", message=dict(content=[
            dict(type="text", text="Result β: one changed edge.")]))) + "\n")
        hook = json.dumps(dict(hook_event_name="Stop", transcript_path=str(transcript)))
        p, report = self.run_cli("stop", "--registry", str(self.registry), "--launch-id", launch_id, "--event-file", "-", "--event-id", "1" * 32, input=hook)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        state = self.record(launch_id)
        self.assertIsNone(state["immediate_child_term"])
        self.assertEqual(state["last_hook"]["kind"], "Stop")
        self.assertEqual(state["last_hook"]["text"], "Result β: one changed edge.")
        wait_for(lambda: any("IDLE (harness turn-stop report)" in v.get("payload", "") for v in events(self.starter_log)))
        p, duplicate = self.run_cli("stop", "--registry", str(self.registry), "--launch-id", launch_id, "--event-file", "-", "--event-id", "1" * 32, input=hook)
        self.assertEqual(p.returncode, 1)
        self.assertIn("notification_already_attempted", duplicate["failure_reason"])
        hook = json.dumps(dict(hook_event_name="StopFailure", error="synthetic failure, process still alive"))
        p, _ = self.run_cli("stop", "--registry", str(self.registry), "--launch-id", launch_id, "--event-file", "-", "--event-id", "2" * 32, input=hook)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertIsNone(self.record(launch_id)["immediate_child_term"])
        pid = events(self.worker_log)[0]["pid"]
        os.kill(pid, signal.SIGTERM)  # only this disposable fixture's independently recorded actual child PID
        state = wait_for(lambda: self.record(launch_id) if self.record(launch_id)["immediate_child_term"] else None)
        self.assertEqual(state["immediate_child_term"], {"Signal": signal.SIGTERM})
        wait_for(lambda: any("PROCESS EXIT:" in v.get("payload", "") for v in events(self.starter_log)))
        notices = [v["payload"] for v in events(self.starter_log) if v["event"] == "input"]
        self.assertEqual(len(notices), 3)
        self.assertIn("death not verified", notices[1])
        self.assertIn("Descendants are not verified gone", notices[2])

    def test_distinct_starter_and_report_to_export_and_notify_both(self):
        report_log = self.work / "report-to.jsonl"
        target = self.rpc("session.new_window", dict(session_id=self.session, focus=False, layout=dict(block=dict(
            flavor="com.superlogical.terminal.shell", options=dict(command=[sys.executable, str(self.fixture), str(report_log), "noack"],
                                                                  exit=dict(on_completion=False))))))
        report_session = self.session
        report_block = target["block_ids"][0]
        wait_for(lambda: events(report_log))
        self.settings["defaults"].update(report_to_session=report_session, report_to_block=report_block)
        p, packet = self.launch("exit7")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        state = wait_for(lambda: self.record(packet["launch_id"]) if self.record(packet["launch_id"])[
            "notifications"].get("child-exit", {}).get("outcome") == "transport_acknowledged" else None)
        self.assertEqual(len(state["notifications"]["child-exit"]["results"]), 2)
        env = events(self.worker_log)[0]["env"]
        for prefix in ("", "LC_"):
            self.assertEqual(env[prefix + "AGENT_STARTER"], self.session + " " + self.starter)
            self.assertEqual(env[prefix + "AGENT_REPORT_TO"], report_session + " " + report_block)
        for log in (self.starter_log, report_log):
            reports = wait_for(lambda: [v for v in events(log) if v["event"] == "input"])
            self.assertEqual(len(reports), 1)
            self.assertIn("PROCESS EXIT:", reports[0]["payload"])

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_CROSS_SESSION") == "1", "separate-session shared spawn regression gate")
    def test_cross_session_report_target_independently_visible_then_managed_launch(self):
        report_log = self.work / "cross-session-report.jsonl"
        target = json.loads(subprocess.check_output(self.base + ["new", "--json", "--keep-open", "--shell=none", "--",
                                                                sys.executable, str(self.fixture), str(report_log), "noack"], timeout=10))
        report_session = target["session_id"]
        report_block = target["initial_windows"][0]["block_ids"][0]
        wait_for(lambda: events(report_log))
        view = self.rpc("session.view", dict(session_id=report_session))
        self.assertTrue(any(b["block_id"] == report_block for w in view["windows"] for layer in w["layers"] for b in layer["blocks"]))
        self.settings["defaults"].update(report_to_session=report_session, report_to_block=report_block)
        p, packet = self.launch("exit7")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout + "\n" + json.dumps(self.record(packet["launch_id"])["spawn_receipt"]))
        state = wait_for(lambda: self.record(packet["launch_id"]) if self.record(packet["launch_id"])[
            "notifications"].get("child-exit", {}).get("outcome") == "transport_acknowledged" else None)
        self.assertEqual(len(state["notifications"]["child-exit"]["results"]), 2)
        wait_for(lambda: [v for v in events(report_log) if v["event"] == "input"])

    def test_immediate_exit7_alert_with_retained_visible_pane(self):
        p, packet = self.launch("exit7")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        launch_id = packet["launch_id"]
        state = wait_for(lambda: self.record(launch_id) if self.record(launch_id)["immediate_child_term"] else None)
        self.assertEqual(state["immediate_child_term"], {"Exited": 7})
        wait_for(lambda: any('"Exited": 7' in v.get("payload", "") for v in events(self.starter_log)))
        self.assertFalse(packet["all_processes_verified_gone"])
        view = self.rpc("session.view", {"session_id": self.session})
        self.assertEqual(len(view["windows"]), 2)

    def shim(self, drop):
        directory = self.work / "shim"
        directory.mkdir()
        path = directory / "rex"
        path.write_text(f"#!{sys.executable}\n" +
                        "import json,subprocess,sys\n"
                        f"r=subprocess.run([{REX!r},*sys.argv[1:]],capture_output=True)\n"
                        "a=json.loads(sys.argv[sys.argv.index('--args')+1]) if '--args' in sys.argv else {}\n"
                        f"drop={drop}\n"
                        "sys.stderr.buffer.write(r.stderr)\n"
                        "if not drop: sys.stdout.buffer.write(r.stdout)\n"
                        "sys.exit(r.returncode)\n")
        path.chmod(0o755)
        self.env["PATH"] = str(directory) + os.pathsep + self.env["PATH"]

    def test_cancellation_cleans_owned_client_without_stopping_server(self):
        before = self.rpc("session.view", dict(session_id=self.session))
        for sig in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=sig):
                directory = self.work / ("hang-" + str(sig))
                directory.mkdir()
                ready = directory / "pid"
                shim = directory / "rex"
                shim.write_text(f"#!{sys.executable}\nimport os,signal,time\nfrom pathlib import Path\n"
                                f"Path({str(ready)!r}).write_text(str(os.getpid()))\n"
                                "signal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(60)\n")
                shim.chmod(0o755)
                env = dict(self.env, PATH=str(directory) + os.pathsep + self.env["PATH"])
                p = subprocess.Popen([BIN, "agents", "launch", "--config", str(self.config), "--profile", "probe"],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                client_pid = None
                try:
                    wait_for(lambda: ready.exists())
                    client_pid = int(ready.read_text())
                    p.send_signal(sig)
                    out, err = p.communicate(timeout=4)
                    self.assertEqual(p.returncode, 128 + sig, err + out)
                    self.assertEqual(json.loads(out)["outcome"], "cancelled_uncertain")
                    # This is the controlled transport's own PID, not a user/server/agent process.
                    try:
                        os.kill(client_pid, 0)
                        alive = True
                    except ProcessLookupError:
                        alive = False
                    self.assertFalse(alive, "owned Rex transport survived launcher cancellation")
                finally:
                    if p.poll() is None:
                        p.kill()
                        p.wait()
                    if client_pid is not None:
                        try:
                            os.killpg(client_pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
        self.assertEqual(self.rpc("session.view", dict(session_id=self.session)), before)

    def test_lost_real_brief_ack_has_one_consumption_and_no_retry(self):
        self.shim("'TASK β asymmetric' in a.get('text','')")
        p, packet = self.launch()
        self.assertEqual(p.returncode, 1, p.stderr + p.stdout)
        self.assertEqual(packet["outcome"], "brief_uncertain")
        self.assertTrue(packet["brief_attempted"])
        wait_for(lambda: any(v["event"] == "input" for v in events(self.worker_log)))
        state = self.record(packet["launch_id"])
        self.assertTrue(state["protocol_acknowledged"])
        self.assertNotEqual(state["brief_receipt"]["outcome"], "events_acknowledged")
        p, refusal = self.run_cli("deliver", "--registry", str(self.registry), "--launch-id", state["launch_id"])
        self.assertEqual(p.returncode, 1)
        self.assertIn("already_attempted", refusal["failure_reason"])
        self.assertEqual(len([v for v in events(self.worker_log) if v["event"] == "input"]), 1)
        self.assertEqual(len(self.rpc("session.view", {"session_id": self.session})["windows"]), 2)

    def test_lost_real_creation_ack_preserves_intent_without_hidden_launch_or_retry(self):
        self.shim("'argv' in a")
        p, packet = self.launch()
        self.assertEqual(p.returncode, 1, p.stderr + p.stdout)
        self.assertEqual(packet["outcome"], "creation_uncertain")
        self.assertFalse(packet["tracked"])
        self.assertFalse(packet["brief_attempted"])
        self.assertEqual(len(self.rpc("session.view", {"session_id": self.session})["windows"]), 2)
        self.assertFalse(self.worker_log.exists())
        self.assertIsNone(self.record(packet["launch_id"])["target"]["block_id"])
        jobs = json.loads(subprocess.check_output([BIN, "jobs", "list", "--registry", str(self.registry)], env=self.env))
        self.assertEqual(jobs["entries"], [])

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_INTEGRATION") == "1", "requires combined root boards/targets/jobs relocation")
    def test_integrated_named_local_profile_fleet_seat_and_finished_presentation(self):
        store = self.work / "boards"
        store.mkdir(mode=0o700)
        target = ["--store", str(store), "--host", "disposable", "--socket", str(self.socket),
                  "--session", self.session, "--block", self.starter]
        def root(*args):
            result = subprocess.run([BIN, *args], capture_output=True, text=True, env=self.env, timeout=15)
            return result, json.loads(result.stdout)
        p, _ = root("seat", "register", *target, "--owner", "operator")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.settings["profiles"]["probe"]["argv"][-1] = "exit7"
        self.config.write_text(json.dumps(self.settings))
        # A named local route must retain its exact Rex pin through the in-pane supervisor's notification.
        poison = self.work / "poison"
        poison.mkdir()
        touched = self.work / "wrong-rex-used"
        wrong = poison / "rex"
        wrong.write_text("#!/bin/sh\ntouch " + shlex.quote(str(touched)) + "\nexit 99\n")
        wrong.chmod(0o755)
        self.env["PATH"] = str(poison) + os.pathsep + self.env["PATH"]
        targets = self.work / "targets.json"
        targets.write_text(json.dumps(dict(schema_version=1, hosts=dict(local=dict(
            host_id="disposable", transport="local", home=str(Path.home()),
            platform="macos-arm64" if sys.platform == "darwin" else "linux-x86_64", socket=str(self.socket),
            rex=str(Path(REX).resolve()), teerex=BIN, store=str(store))))))
        p, packet = root("--config", str(targets), "--host", "local", "spawn", "--profile", "probe", "--profiles",
                         str(self.config), "--brief-file", str(self.brief), "--ack-timeout-ms", "2000")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        launch_id = packet["launch_id"]
        state = wait_for(lambda: self.record(launch_id) if self.record(launch_id).get("fleet_reports", {}).get(
            "child-exit", {}).get("outcome") == "reported" else None)
        self.assertEqual(state["immediate_child_term"], {"Exited": 7})
        self.assertEqual(state["rex_executable"], str(Path(REX).resolve()))
        self.assertFalse(touched.exists())
        self.assertEqual([v for v in events(self.starter_log) if v["event"] == "input"], [])
        p, inbox = root("inbox", "inspect", *target)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual(len(inbox["seat"]["records"]), 1)
        self.assertIn('"Exited": 7', inbox["seat"]["records"][0]["body"])
        p, board = root("boards", "state", "inspect", "--store", str(store))
        fleet = board["state"]["fleet"]
        self.assertEqual(len(fleet), 1)
        self.assertEqual(fleet[0]["owner"], "operator")
        self.assertEqual(fleet[0]["purpose"], "asymmetric lifecycle regression")
        self.assertEqual(fleet[0]["state"], "unknown")
        self.assertIn("PROCESS EXIT", fleet[0]["detail"])
        before = self.rpc("session.view", {"session_id": self.session})
        self.assertEqual(len(before["windows"]), 2)
        def present(focus):
            _, jobs = root("jobs", "list", "--registry", str(self.registry))
            generation = jobs["entries"][0]["generation"]
            return self.run_cli("present", "--registry", str(self.registry), "--launch-id", launch_id, "--owner", "operator",
                                "--generation", str(generation), "--reason", "review retained result", "--anchor", self.starter,
                                "--focus", focus)
        p, refused = present("no")
        self.assertEqual(p.returncode, 1, p.stderr + p.stdout)
        self.assertEqual(refused["presentation"]["receipt"]["failure_reason"], "relocating_focused_source_requires_explicit_focus")
        self.assertEqual(self.rpc("session.view", {"session_id": self.session}), before)
        p, moved = present("yes")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual(moved["outcome"], "presentation_verified")
        after = self.rpc("session.view", {"session_id": self.session})
        self.assertEqual(len(after["windows"]), 1)
        block_ids = [b["block_id"] for layer in after["windows"][0]["layers"] for b in layer["blocks"]]
        self.assertEqual(set(block_ids), {self.starter, state["target"]["block_id"]})
        self.assertEqual(after["windows"][0]["focused_block_id"], state["target"]["block_id"])

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_INTEGRATION") == "1", "requires combined boards store")
    def test_integrated_failed_fleet_store_never_starts_harness_or_submits_brief(self):
        store = self.work / "not-private-boards"
        store.mkdir(mode=0o755)
        self.settings["defaults"]["store"] = str(store)
        p, packet = self.launch()
        self.assertEqual(p.returncode, 1, p.stderr + p.stdout)
        self.assertEqual(packet["outcome"], "fleet_report_uncertain")
        self.assertTrue(packet["tracked"])
        self.assertFalse(packet["brief_attempted"])
        self.assertFalse(self.worker_log.exists())
        self.assertEqual(len(self.rpc("session.view", {"session_id": self.session})["windows"]), 2)
        self.assertEqual([v for v in events(self.starter_log) if v["event"] == "input"], [])

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_SSH") == "1", "explicit isolated Linux SSH compute acceptance gate")
    def test_isolated_ssh_compute_ack_protocol_hooks_and_measured_exit(self):
        self.assertEqual(sys.platform, "linux")
        for executable in ("/usr/sbin/sshd", "/usr/bin/bwrap", "/usr/bin/ssh-keygen"):
            self.assertTrue(Path(executable).exists(), executable)
        import getpass
        compute = self.work / "compute"
        compute.mkdir(mode=0o700)
        (self.work / "boards").mkdir(mode=0o700)
        # Two actual SSH endpoints: compute runs in a separate mount namespace; registry remains outside it.
        key = self.work / "client-key"
        host_key = self.work / "host-key"
        for path in (key, host_key):
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)], check=True)
        authorized = self.work / "authorized_keys"
        authorized.write_text(key.with_suffix(".pub").read_text())
        authorized.chmod(0o600)
        ports = []
        for unused in range(2):
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                ports.append(s.getsockname()[1])
        force = self.work / "compute-shell"
        force.write_text("#!/usr/bin/python3\nimport os\nfrom pathlib import Path\n" +
                         "cmd=['bwrap','--die-with-parent']\n" +
                         "for p in ['/usr','/bin','/sbin','/lib','/lib64','/etc']:\n" +
                         " if Path(p).exists(): cmd+=['--ro-bind',p,p]\n" +
                         "cmd+=['--dev','/dev','--proc','/proc','--tmpfs','/tmp','--tmpfs','/run','--tmpfs','/var']\n" +
                         f"cmd+=['--ro-bind',{sys.prefix!r},{sys.prefix!r}]\n" +
                         f"cmd+=['--ro-bind',{BIN!r},\"/opt/teerex cli's\",'--bind',{str(compute)!r},'/work']\n" +
                         "os.execvp('bwrap',cmd+['--chdir','/work','--','/bin/sh','-c',os.environ['SSH_ORIGINAL_COMMAND']])\n")
        force.chmod(0o700)
        logs = []
        for i, port in enumerate(ports):
            ssh_config = self.work / ("sshd-" + str(i))
            ssh_config.write_text(f"Port {port}\nListenAddress 127.0.0.1\nHostKey {host_key}\n"
                                  f"AuthorizedKeysFile {authorized}\nPidFile {self.work / ('sshd-'+str(i)+'.pid')}\n"
                                  "StrictModes no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nUsePAM no\n"
                                  f"AllowUsers {getpass.getuser()}\nAllowTcpForwarding no\nAllowStreamLocalForwarding no\n"
                                  + (f"ForceCommand {force}\n" if i == 0 else ""))
            log = (self.work / ("sshd-" + str(i) + ".log")).open("w+")
            self.addCleanup(log.close)
            logs.append(log)
            server = subprocess.Popen(["/usr/sbin/sshd", "-D", "-e", "-f", str(ssh_config)], stdout=log, stderr=log)
            self.addCleanup(lambda p=server: (p.terminate(), p.wait(timeout=5)) if p.poll() is None else None)
            def ready():
                if server.poll() is not None:
                    log.seek(0)
                    self.fail(log.read())
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=.1):
                        return True
                except OSError:
                    return False
            wait_for(ready)
        known = self.work / "known-hosts"
        public = " ".join(host_key.with_suffix(".pub").read_text().split()[:2])
        known.write_text("".join(f"[127.0.0.1]:{p} {public}\n" for p in ports))
        shutil.copy(key, compute / "identity")
        shutil.copy(known, compute / "known-hosts")
        (compute / "fixture.py").write_text(FIXTURE)
        def host(port, binary, socket_path, config_key, known_path):
            return dict(host_id="disposable", transport="ssh", address=getpass.getuser()+"@127.0.0.1", port=port,
                        known_hosts=known_path, identity_file=config_key, home="/work", platform="linux-x86_64",
                        socket=socket_path, rex=str(Path(REX).resolve()), teerex=binary, store=str(self.work / "boards"))
        targets = self.work / "compute-targets.json"
        targets.write_text(json.dumps(dict(schema_version=1, hosts=dict(compute=host(ports[0], "/opt/teerex cli's",
                                            "/run/absent-rex.sock", str(key), str(known))))))
        (compute / "callbacks route.json").write_text(json.dumps(dict(schema_version=1, hosts=dict(registry=host(
            ports[1], BIN, str(self.socket), "/work/identity", "/work/known-hosts")))))
        report_log = self.work / "remote-report-to.jsonl"
        target = self.rpc("session.new_window", dict(session_id=self.session, focus=False, layout=dict(block=dict(
            flavor="com.superlogical.terminal.shell", options=dict(command=[sys.executable, str(self.fixture), str(report_log), "noack"],
                                                                  exit=dict(on_completion=False))))))
        report_block = target["block_ids"][0]
        wait_for(lambda: events(report_log))
        self.settings["defaults"].update(report_to_session=self.session, report_to_block=report_block)
        literal_args = ["", "two words", "line\nbreak", "'$;`\" β"]
        self.settings["profiles"]["probe"].update(argv=[sys.executable, "/work/fixture.py", "/work/worker.jsonl", "remote-exit7", *literal_args],
            harness="claude", hook_events=True, execution=dict(config=str(targets), host="compute", cwd="/work"),
            callbacks=dict(config="/work/callbacks route.json", host="registry"))
        self.enable_channel()
        self.config.write_text(json.dumps(self.settings))
        before = self.rpc("session.view", dict(session_id=self.session))
        p, refusal = self.run_cli("launch", "--config", str(self.config), "--profile", "probe")
        self.assertEqual(p.returncode, 1)
        self.assertIn("remote_fenced_delivery_not_yet_supported", refusal["failure_reason"])
        self.assertEqual(self.rpc("session.view", dict(session_id=self.session)), before)
        self.settings["profiles"]["probe"].pop("delivery")
        self.config.write_text(json.dumps(self.settings))
        p, packet = self.run_cli("launch", "--config", str(self.config), "--profile", "probe", "--brief-file", str(self.brief),
                                 "--ack-timeout-ms", "6000")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        launch_id = packet["launch_id"]
        worker = compute / "worker.jsonl"
        wait_for(lambda: len([v for v in events(worker) if v["event"] == "remote-hook"]) == 2)
        started = events(worker)[0]
        self.assertFalse(started["registry_present"], "compute accidentally shares the pane-host registry")
        self.assertTrue(started["stdin_tty"])
        self.assertEqual(started["cwd"], "/work")
        self.assertEqual(started["argv"][:len(literal_args)], literal_args)
        self.assertEqual([v["code"] for v in events(worker) if v["event"] == "wrong-ack"], [1, 1])
        self.assertEqual([v["code"] for v in events(worker) if v["event"] == "ack"], [0])
        self.assertEqual([v["code"] for v in events(worker) if v["event"] == "remote-hook"], [0, 0])
        wait_for(lambda: [v for v in events(worker) if v["event"] == "remote-reply"])
        self.assertEqual([v["code"] for v in events(worker) if v["event"] == "remote-reply"], [0])
        self.assertEqual([v["payload"] for v in events(worker) if v["event"] == "input"], ["FROM probe: " + self.brief.read_text()])
        state = wait_for(lambda: self.record(launch_id) if self.record(launch_id).get("notifications", {}).get(
            "child-exit", {}).get("outcome") == "transport_acknowledged" else None)
        self.assertEqual(state["remote_child_term"], {"Exited": 7})
        self.assertEqual(state["immediate_child_term"], {"Exited": 7})
        self.assertEqual(state["last_hook"]["kind"], "StopFailure")
        for destination_log in (self.starter_log, report_log):
            count = 3 if destination_log == self.starter_log else 4
            notices = wait_for(lambda: [v["payload"] for v in events(destination_log) if v["event"] == "input"]
                               if len([v for v in events(destination_log) if v["event"] == "input"]) == count else None)
            self.assertIn("remote transcript β '\"", notices[0])
            self.assertIn("remote failure β", notices[1])
            self.assertIn('Remote child: {"Exited": 7}', notices[-1])
            self.assertIn("SSH transport:", notices[-1])
            if destination_log == report_log:
                self.assertEqual(notices[2], "FROM probe: remote direct reply β\n\n")
        # Stored protocol and compute protocol differ only in their explicitly routed command lines.
        protocol = [v["payload"] for v in events(worker) if v["event"] == "protocol_argument"][0]
        saved = Path(state["protocol_file"]).read_text()
        def without_routes(value):
            for marker in ("Acknowledge this protocol now by running:\n", "Supply report bytes on stdin then EOF using:\n"):
                before, after = value.split(marker)
                value = before + marker + "ROUTING_COMMAND\n" + after.split("\n", 1)[1]
            return value
        self.assertEqual(without_routes(protocol), without_routes(saved))
        self.assertIn("--config '/work/callbacks route.json' --host registry agents ack", protocol)
        # A later explicit ACK can continue once; timeout never submits the brief by itself.
        profile = self.settings["profiles"]["probe"]
        profile["argv"] = [sys.executable, "/work/fixture.py", "/work/late.jsonl", "lateack"]
        profile["hook_events"] = False
        self.config.write_text(json.dumps(self.settings))
        p, late = self.run_cli("launch", "--config", str(self.config), "--profile", "probe", "--brief-file", str(self.brief),
                               "--ack-timeout-ms", "200")
        self.assertEqual(p.returncode, 124, p.stderr + p.stdout)
        self.assertFalse(late["brief_attempted"])
        wait_for(lambda: self.record(late["launch_id"])["protocol_acknowledged"])
        self.assertEqual([v for v in events(compute / "late.jsonl") if v["event"] == "input"], [])
        p, result = self.run_cli("deliver", "--registry", str(self.registry), "--launch-id", late["launch_id"])
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        wait_for(lambda: [v for v in events(compute / "late.jsonl") if v["event"] == "input"])
        p, result = self.run_cli("deliver", "--registry", str(self.registry), "--launch-id", late["launch_id"])
        self.assertEqual(p.returncode, 1)
        self.assertEqual(len([v for v in events(compute / "late.jsonl") if v["event"] == "input"]), 1)
        # Lose the measured-exit callback: even a terminating SSH result must leave remote evidence unknown.
        (compute / "known-hosts").write_text("")
        os.kill(events(compute / "late.jsonl")[0]["pid"], signal.SIGTERM)
        state = wait_for(lambda: self.record(late["launch_id"]) if self.record(late["launch_id"])[
            "notifications"].get("child-exit", {}).get("outcome") == "transport_acknowledged" else None)
        self.assertIsNone(state["remote_child_term"])
        self.assertEqual(state["immediate_child_term"], {"Exited": 143})
        last_notice = [v["payload"] for v in events(self.starter_log) if v["event"] == "input"][-1]
        self.assertIn("Remote child: unknown; no measured exit callback", last_notice)
        # A refused new compute connection cannot ACK or submit a brief, and is not remote-death evidence.
        route = json.loads(targets.read_text())
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            route["hosts"]["compute"]["port"] = s.getsockname()[1]
        targets.write_text(json.dumps(route))
        p, failure = self.run_cli("launch", "--config", str(self.config), "--profile", "probe", "--brief-file", str(self.brief),
                                  "--ack-timeout-ms", "3000")
        self.assertEqual(p.returncode, 1, p.stderr + p.stdout)
        self.assertEqual(failure["outcome"], "child_exited_before_ack")
        self.assertFalse(failure["brief_attempted"])
        self.assertIsNone(failure["remote_child_term"])
        self.assertEqual(failure["immediate_child_term"], {"Exited": 255})

    def enable_channel(self, count=32, lifetime=60000):
        self.delivery = self.work / "delivery"
        self.delivery.mkdir(mode=0o700)
        self.settings["profiles"]["probe"]["delivery"] = dict(directory=str(self.delivery), grants=["send", "ack", "stop"],
                                                                  max_requests=count, lifetime_ms=lifetime)

    def channel_cli(self, launch_id, *args, request_id="c" * 32, **kwargs):
        return self.run_cli("channel", "--handle", str(self.delivery / launch_id / "handle.json"),
                            "--request-id", request_id, *args, **kwargs)

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_FENCE") == "1", "explicit real Linux bubblewrap acceptance gate")
    def test_real_fence_denies_rex_and_registry_but_scoped_ack_send_stop_work(self):
        self.assertEqual(sys.platform, "linux")
        self.assertIsNotNone(shutil.which("bwrap"))
        self.enable_channel()
        fenced = self.work / "fenced"
        fenced.mkdir()
        self.worker_log = fenced / "worker.jsonl"
        wrapper = self.work / "fence.py"
        # Rivet's bwrap adapter mounts only toolchain/cwd/declared extra paths; /tmp and /run are masked.
        # Match that contract, with ONLY this launch's channel mounted, never registry/store/Rex socket.
        denial_probe = ("import os,socket,json\nfrom pathlib import Path\n"
                        f"paths={dict(rex=str(self.socket), registry=str(self.registry))!r}\nresults={{}}\n"
                        "for k,p in paths.items():\n"
                        " try:\n"
                        "  socket.socket(socket.AF_UNIX).connect(p) if k=='rex' else os.open(p,os.O_RDONLY)\n"
                        "  results[k]=False\n"
                        " except OSError: results[k]=True\n"
                        "Path('/work/denial.json').write_text(json.dumps(results))\n")
        wrapper.write_text("import json,os,subprocess,sys\nfrom pathlib import Path\n" +
                           "cmd=['bwrap','--die-with-parent']\n" +
                           "for p in ['/usr','/bin','/sbin','/lib','/lib64','/etc']:\n" +
                           " if Path(p).exists(): cmd+=['--ro-bind',p,p]\n" +
                           "cmd+=['--dev','/dev','--proc','/proc','--tmpfs','/tmp','--tmpfs','/run','--tmpfs','/var']\n" +
                           f"cmd+=['--ro-bind',{sys.prefix!r},{sys.prefix!r}]\n" +
                           f"cmd+=['--ro-bind',{BIN!r},{BIN!r},'--bind',{str(fenced)!r},'/work']\n" +
                           "channel=str(Path(os.environ['AGENT_CHANNEL']).parent)\ncmd+=['--ro-bind',channel,channel]\n" +
                           f"probe={denial_probe!r}\n" +
                           f"code=probe+{FIXTURE!r}\n" +
                           f"os.execvp('bwrap',cmd+['--chdir','/work','--',{sys.executable!r},'-c',code,'/work/worker.jsonl','channel',*sys.argv[2:]])\n")
        self.settings["profiles"]["probe"].update(argv=[sys.executable, str(wrapper), "channel"], standing_flags=[],
                                                   harness="claude", hook_events=True)
        p, packet = self.launch("channel", ack_timeout=4000)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout + "\n" + str(packet))
        launch_id = packet["launch_id"]
        results = wait_for(lambda: [v for v in events(self.worker_log) if v["event"] == "channel-result"]
                           if len([v for v in events(self.worker_log) if v["event"] == "channel-result"]) == 2 else None)
        self.assertEqual(json.loads((fenced / "denial.json").read_text()), dict(rex=True, registry=True))
        self.assertEqual([v["code"] for v in results], [0, 1])
        self.assertIn("already_attempted", json.loads(results[1]["stdout"])["failure_reason"])
        wait_for(lambda: [v for v in events(self.worker_log) if v["event"] == "channel-stop"])
        self.assertEqual([v["code"] for v in events(self.worker_log) if v["event"] == "channel-stop"], [0])
        env = [v for v in events(self.worker_log) if v["event"] == "started"][0]["env"]
        self.assertNotIn("AGENT_REGISTRY", env)
        self.assertNotIn("LC_AGENT_REGISTRY", env)
        self.assertEqual(env["AGENT_LAUNCH_ID"], launch_id)
        notices = wait_for(lambda: [v["payload"] for v in events(self.starter_log) if v["event"] == "input"]
                           if len([v for v in events(self.starter_log) if v["event"] == "input"]) == 2 else None)
        self.assertEqual(notices[0], "FROM probe: fenced β: quotes '\"\nlast line\n\n")
        self.assertIn("fenced turn complete β", notices[1])
        # The brief still traverses the original ACK-before-one-brief gate and keeps trailing bytes.
        inputs = wait_for(lambda: [v["payload"] for v in events(self.worker_log) if v["event"] == "input"])
        self.assertEqual(inputs, ["FROM probe: " + self.brief.read_text()])
        os.kill(events(self.worker_log)[0]["pid"], signal.SIGTERM)
        wait_for(lambda: self.record(launch_id)["immediate_child_term"])
        wait_for(lambda: not (self.delivery / launch_id).exists())
        p, result = self.channel_cli(launch_id, "--operation", "send", "--to", "starter", "--message-file", str(self.brief))
        self.assertEqual(p.returncode, 1)
        self.assertFalse(result["retry_safe"])

    def test_channel_fixed_grants_framing_lease_and_no_retry(self):
        self.enable_channel()
        p, packet = self.launch()
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        launch_id = packet["launch_id"]
        handle_path = self.delivery / launch_id / "handle.json"
        handle = json.loads(handle_path.read_text())
        def raw_request(**changes):
            request = dict(launch_id=launch_id, token=handle["token"], request_id="d" * 32,
                           operation="send", to="starter", body="one exact β\n\n")
            request.update(changes)
            if request["operation"] == "stop":
                request.pop("to")
                request.pop("body")
            with socket.socket(socket.AF_UNIX) as c:
                c.settimeout(5)
                c.connect(handle["socket"])
                c.sendall(json.dumps(request).encode() + b"\n")
                data = b""
                while not data.endswith(b"\n"):
                    data += c.recv(65536)
                return json.loads(data)
        for changes, reason in ((dict(token="0" * 64), "token_mismatch"),
                                (dict(launch_id="0" * 32), "launch_mismatch"),
                                (dict(to=self.starter), "fixed_channel_destination"),
                                (dict(operation="exec"), "not_granted"),
                                (dict(body="bad\x1bcontrol"), "invalid_or_oversized"),
                                (dict(body="x" * 32769), "invalid_or_oversized"),
                                (dict(socket=str(self.socket)), "unknown_channel_field"),
                                (dict(operation="stop", event={"hook_event_name":"Stop", "transcript_path":"/etc/passwd"}),
                                 "channel_transcript_path_forbidden")):
            with self.subTest(changes=list(changes)):
                result = raw_request(**changes)
                self.assertEqual(result["code"], 1)
                self.assertIn(reason, result["result"]["failure_reason"])
        self.assertEqual([v for v in events(self.starter_log) if v["event"] == "input"], [])
        p, bad = self.channel_cli(launch_id, "--operation", "ack", "--session", self.session, "--block", self.starter,
                                  "--to", "starter")
        self.assertEqual(p.returncode, 1)
        self.assertIn("irrelevant_channel_argument", bad["failure_reason"])
        for raw, reason in ((b'{"operation":"send","operation":"ack"}\n', "duplicate_channel_field"),
                            (b'{}\n{}\n', "one_channel_frame_required"), (b'{', "incomplete_channel_frame"),
                            (b'x' * 49153, "channel_frame_too_large"),
                            (b'[' * 20000 + b']' * 20000 + b'\n', None)):
            with socket.socket(socket.AF_UNIX) as c:
                c.settimeout(2)
                c.connect(handle["socket"])
                c.sendall(raw)
                try:
                    c.shutdown(socket.SHUT_WR)
                except OSError as error:
                    # macOS can report ENOTCONN after the server already sent its refusal and closed.
                    if error.errno != errno.ENOTCONN:
                        raise
                response = b""
                while not response.endswith(b"\n"):
                    part = c.recv(65536)
                    self.assertTrue(part)
                    response += part
            result = json.loads(response)
            self.assertEqual(result["code"], 1)
            if reason is not None:  # Deep JSON can refuse at parser depth or at the required object envelope.
                self.assertIn(reason, result["result"]["failure_reason"])
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            simultaneous = list(pool.map(lambda unused: raw_request(), range(2)))
        self.assertEqual(sorted(v["code"] for v in simultaneous), [0, 1])
        self.assertTrue(all(not v["result"]["retry_safe"] for v in simultaneous))
        refusal = [v for v in simultaneous if v["code"] == 1][0]
        self.assertIn("already_attempted", refusal["result"]["failure_reason"])
        wait_for(lambda: len([v for v in events(self.starter_log) if v["event"] == "input"]) == 1)
        # Dropping the response after submission still leaves durable intent and refuses a resend.
        request = dict(launch_id=launch_id, token=handle["token"], request_id="e" * 32, operation="send", to="starter", body="lost receipt β")
        with socket.socket(socket.AF_UNIX) as c:
            c.connect(handle["socket"])
            c.sendall(json.dumps(request).encode() + b"\n")
        wait_for(lambda: self.record(launch_id).get("channel_requests", {}).get("e" * 32))
        result = raw_request(request_id="e" * 32, body="lost receipt β")
        self.assertEqual(result["code"], 1)
        self.assertIn("already_attempted", result["result"]["failure_reason"])
        wait_for(lambda: len([v for v in events(self.starter_log) if v["event"] == "input"]) == 2)
        stalled = subprocess.Popen([BIN, "agents", "channel", "--handle", str(handle_path), "--request-id", "f" * 32,
                                    "--operation", "send", "--to", "starter", "--message-file", "-"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
        try:
            self.assertEqual(stalled.wait(timeout=4), 1)
            self.assertIn("input_eof_deadline_2s", json.loads(stalled.stdout.read())["failure_reason"])
        finally:
            if stalled.poll() is None:
                stalled.kill()
                stalled.wait()
            stalled.stdin.close()
            stalled.stdout.close()
            stalled.stderr.close()
        self.assertEqual(len([v for v in events(self.starter_log) if v["event"] == "input"]), 2)
        # Final-component symlinks are not accepted as capability files.
        alias = self.work / "handle-link"
        alias.symlink_to(handle_path)
        p, result = self.run_cli("channel", "--handle", str(alias), "--request-id", "f" * 32,
                                 "--operation", "send", "--to", "starter", "--message-file", str(self.brief))
        self.assertEqual(p.returncode, 1)
        os.kill(events(self.worker_log)[0]["pid"], signal.SIGTERM)
        wait_for(lambda: not handle_path.exists())

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_INTEGRATION") == "1", "requires combined boards routing")
    def test_channel_registered_seat_and_store_refusal_never_paste(self):
        self.enable_channel()
        store = self.work / "boards"
        store.mkdir(mode=0o700)
        self.settings["defaults"]["store"] = str(store)
        target = ["--store", str(store), "--host", "disposable", "--socket", str(self.socket),
                  "--session", self.session, "--block", self.starter]
        result = subprocess.run([BIN, "seat", "register", *target, "--owner", "operator"], capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        p, packet = self.launch()
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        launch_id = packet["launch_id"]
        p, result = self.channel_cli(launch_id, "--operation", "send", "--to", "starter", "--message-file", str(self.brief))
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual(result["receipt"]["outcome"], "recorded")
        inbox = json.loads(subprocess.check_output([BIN, "inbox", "inspect", *target], env=self.env))
        self.assertEqual([r["body"] for r in inbox["seat"]["records"]], [self.brief.read_text()])
        self.assertEqual([v for v in events(self.starter_log) if v["event"] == "input"], [])
        store.chmod(0o755)
        try:
            p, result = self.channel_cli(launch_id, "--operation", "send", "--to", "starter", "--message-file", str(self.brief),
                                         request_id="f" * 32)
            self.assertEqual(p.returncode, 1)
            self.assertEqual(result["outcome"], "uncertain")
            self.assertNotEqual(result["receipt"]["outcome"], "events_acknowledged")
            self.assertEqual([v for v in events(self.starter_log) if v["event"] == "input"], [])
        finally:
            store.chmod(0o700)

    def test_channel_expiry_count_and_cancel_revoke_without_stopping_other_panes(self):
        self.enable_channel(count=2, lifetime=1000)
        p, packet = self.launch()
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        launch_id = packet["launch_id"]
        p, result = self.channel_cli(launch_id, "--operation", "send", "--to", "starter", "--message-file", str(self.brief))
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        wait_for(lambda: not (self.delivery / launch_id).exists())
        self.assertIsNone(self.record(launch_id)["immediate_child_term"])
        self.assertEqual(self.record(launch_id)["channel_status"], "revoked")
        self.assertEqual(len(self.rpc("session.view", dict(session_id=self.session))["windows"]), 2)
        # A separate launch expires even when it has unused requests, with its child still alive.
        self.settings["profiles"]["probe"]["delivery"]["max_requests"] = 32
        self.worker_log = self.work / "expiring-worker.jsonl"
        self.settings["profiles"]["probe"]["argv"][2] = str(self.worker_log)
        p, packet = self.launch()
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        expired_grant = json.loads((self.delivery / packet["launch_id"] / "handle.json").read_text())
        wait_for(lambda: not (self.delivery / packet["launch_id"]).exists())
        self.assertIsNone(self.record(packet["launch_id"])["immediate_child_term"])
        # Signal the actual recorded visible supervisor: its channel revokes and its own child is reaped.
        self.settings["profiles"]["probe"]["delivery"]["lifetime_ms"] = 60000
        for sig in (signal.SIGINT, signal.SIGTERM):
            self.worker_log = self.work / ("cancelled-worker-" + str(sig) + ".jsonl")
            self.settings["profiles"]["probe"]["argv"][2] = str(self.worker_log)
            p, packet = self.launch()
            self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
            state = self.record(packet["launch_id"])
            active_grant = json.loads((self.delivery / packet["launch_id"] / "handle.json").read_text())
            for claimed_launch, reason in ((expired_grant["launch_id"], "launch_mismatch"),
                                           (active_grant["launch_id"], "token_mismatch")):
                with socket.socket(socket.AF_UNIX) as c:
                    c.settimeout(3)
                    c.connect(active_grant["socket"])
                    c.sendall(json.dumps(dict(launch_id=claimed_launch, token=expired_grant["token"], request_id="9" * 32,
                                             operation="send", to="starter", body="must not cross launch")).encode() + b"\n")
                    response = b""
                    while not response.endswith(b"\n"):
                        part = c.recv(65536)
                        self.assertTrue(part)
                        response += part
                result = json.loads(response)
                self.assertEqual(result["code"], 1)
                self.assertIn(reason, result["result"]["failure_reason"])
            os.kill(state["supervisor_pid"], sig)
            wait_for(lambda: not (self.delivery / packet["launch_id"]).exists())
            wait_for(lambda: self.record(packet["launch_id"])["immediate_child_term"])
            # SIGINT in Python is reported as KeyboardInterrupt/exit130 rather than an OS signal.
            self.assertIn(self.record(packet["launch_id"])["immediate_child_term"],
                          ({"Signal": sig}, {"Exited": 128 + sig}))
            os.kill(events(self.starter_log)[0]["pid"], 0)

    def test_profiles_shell_and_refusals_leave_personal_settings_untouched(self):
        self.settings["profiles"]["claude"] = dict(argv=["/not/installed/claude"], harness="claude",
                                                       standing_flags=["--dangerously-skip-permissions"])
        self.settings["profiles"]["codex"] = dict(argv=["/not/installed/codex"], harness="codex",
                                                      standing_flags=["--dangerously-bypass-approvals-and-sandbox"])
        self.config.write_text(json.dumps(self.settings))
        p, profiles = self.run_cli("profiles", "--config", str(self.config))
        self.assertEqual(p.returncode, 0)
        self.assertEqual(profiles["profiles"]["codex"]["standing_flags"], ["--dangerously-bypass-approvals-and-sandbox"])
        self.assertFalse(profiles["security_settings_changed"])
        p, _ = self.run_cli("shell", "--config", str(self.config))
        self.assertEqual(p.returncode, 0)
        self.assertIn("claude() {", p.stdout)
        self.assertIn(shlex.quote(str(self.config)), p.stdout)
        preserved = subprocess.run(["/bin/bash", "-c", "claude() { printf 'original-function'; };\n" + p.stdout + "\nclaude"],
                                   capture_output=True, text=True, timeout=5)
        self.assertEqual(preserved.returncode, 0, preserved.stderr)
        self.assertEqual(preserved.stdout, "original-function")
        self.assertIn("preserved existing claude function", preserved.stderr)
        # No launcher/shell config is sourced or modified by these commands.
        self.assertEqual(sorted(p.name for p in self.work.iterdir()),
                         ["brief.txt", "fixture.py", "profiles.json", "registry", "starter.jsonl"])
        self.registry.chmod(0o755)
        p, refusal = self.launch()
        self.assertEqual(p.returncode, 1)
        self.assertIn("private_owned_registry", refusal["failure_reason"])
        self.assertEqual(len(self.rpc("session.view", {"session_id": self.session})["windows"]), 1)


if __name__ == "__main__":
    unittest.main()
