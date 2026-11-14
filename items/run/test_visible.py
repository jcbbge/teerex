"""Public run-visible acceptance against disposable Rex only (Linux/Mac).

TEEREX_BIN may name the combined CLI or items/run/test_visible_cli.zig build.
REX_BIN must select the deliberately downloaded disposable test Rex.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

BIN = str(Path(os.environ.get("TEEREX_BIN", "zig-out/bin/teerex")).resolve())


def raw(node):
    return node["content"].encode() if node["encoding"] == "utf8" else base64.b64decode(node["content"], validate=True)


class VisibleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rex = str(Path(os.environ.get("REX_BIN") or shutil.which("rex") or "MISSING_REX").resolve())
        cls.temp = tempfile.TemporaryDirectory(prefix="tvisible-", dir="/tmp")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.socket = cls.root / "rex.sock"
        cls.base = [cls.rex, "--autostart=false", "--server", "unix://" + str(cls.socket), "--timeout", "3s"]
        cls.log = (cls.root / "server.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen([cls.rex, "server", "run", "--listen", "unix://" + str(cls.socket),
                                      "--restore=false", "--config", "/dev/null", "--state-dir", str(cls.root / "state")],
                                     stdout=cls.log, stderr=cls.log, env=dict(os.environ, HOME=str(cls.root)))
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            if cls.server.poll() is not None:
                raise RuntimeError((cls.root / "server.log").read_text())
            if cls.socket.exists():
                break
            time.sleep(.05)
        else:
            raise RuntimeError("disposable server startup failed")
        cls.version = cls.rpc("server.version", {})
        print("Real Rex:", cls.version, flush=True)

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    @classmethod
    def rpc(cls, method, params):
        return json.loads(subprocess.check_output(cls.base + ["api", "call", method, json.dumps(params)], timeout=10))

    def setUp(self):
        self.work = self.root / str(time.monotonic_ns())
        self.work.mkdir()
        self.envfile = self.work / "env.json"
        self.envfile.write_text(json.dumps({"PATH": "/usr/bin:/bin", "TEEREX_LITERAL": "a\n'α😀", "EMPTY": ""}))
        self.stdin = self.work / "stdin"
        self.stdin.write_bytes(b"input\x00\xff\n\n")
        self.session = self.rpc("session.create", {"label": "run-visible disposable"})["session_id"]
        self.addCleanup(lambda: self.rpc("session.destroy", {"session_id": self.session}))
        self.runtime_env = dict(os.environ, HOME=str(self.root), REX_SERVER="unix:///tmp/wrong.sock", REX_BLOCK="block:wrong",
                                PATH=str(Path(self.rex).parent) + os.pathsep + os.environ.get("PATH", ""))
        self.anchor = None

    def command(self, script="print('hello visible')", *, argv=None, extra=(), rex=None):
        return [BIN, "--rex", rex or self.rex, "run-visible", "--socket", str(self.socket), "--session", self.session,
                "--cwd", str(self.work), "--env-file", str(self.envfile), "--stdin-file", str(self.stdin),
                "--app", "teerex-test", "--title", "Visible α command", *extra,
                "--", *(argv if argv is not None else [sys.executable, "-c", script])]

    def invoke(self, *args, client_timeout=20, **kwargs):
        r = subprocess.run(self.command(*args, **kwargs), env=self.runtime_env, capture_output=True, text=True, timeout=client_timeout)
        self.assertTrue(r.stdout, r.stderr)
        v = json.loads(r.stdout)
        if v.get("storage_retained") and not v.get("full_output_requested"):
            self.addCleanup(shutil.rmtree, v["storage_dir"], True)
        return r, v

    def assert_good(self, r, v):
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertTrue(v["success"])
        self.assertEqual(v["outcome"], "exit_reported")
        self.assertFalse(v["retry_safe"])
        self.assertFalse(v["all_descendants_verified_gone"])
        self.assertEqual(v["source"]["api_revision"], 13)
        self.assertEqual(v["placement"]["receipt"]["actual"]["block_id"], v["created"]["block_id"])
        self.assertEqual(v["pane_identity_report"]["block_id"], v["created"]["block_id"])

    def blocks(self):
        return {b["block_id"] for b in self.rpc("session.list_blocks", {"session_id": self.session})["blocks"]}

    def anchor_pane(self):
        r = subprocess.run([BIN, "--rex", self.rex, "surfaces", "open", "--socket", str(self.socket),
                            "--session", self.session, "--layout", "tab", "--label", "unrelated sentinel",
                            "--", "/bin/sleep", "60"], capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.anchor = json.loads(r.stdout)["created"]["block_id"]
        return self.anchor

    def receipt(self, launch, wait=0):
        process = subprocess.run([BIN, "run-visible", "receipt", "--file", launch["receipt_path"], "--wait-ms", str(wait)],
                                 capture_output=True, text=True, env=self.runtime_env, timeout=max(10, wait / 1000 + 5))
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        return json.loads(process.stdout)

    def test_detach_keep_open_handoff_jobs_metadata_and_private_receipt(self):
        registry = self.work / "detach-jobs"
        registry.mkdir(mode=0o700)
        gate = self.work / "gate"
        script = f"from pathlib import Path;import time,sys\nwhile not Path({str(gate)!r}).exists():time.sleep(.02)\nprint('detached α');sys.stderr.write('separate stderr');sys.exit(7)"
        # Call directly: the detached receipt directory must outlive the launch client's exit.
        process = subprocess.run(self.command(script, extra=["--detach", "--keep-open", "--no-deadline", "--registry", str(registry),
                                                             "--owner", "rivet", "--purpose", "detached fixture"]),
                                 env=self.runtime_env, capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        launch = json.loads(process.stdout)
        self.addCleanup(shutil.rmtree, launch["storage_dir"], True)
        self.assertEqual(launch["kind"], "run_visible_launch")
        self.assertEqual(launch["outcome"], "launched")
        self.assertEqual(len(launch["launch_id"]), 32)
        self.assertFalse(gate.exists())
        self.assertIn(launch["created"]["block_id"], self.blocks())
        self.assertEqual(self.receipt(launch, 50)["outcome"], "pending")
        inspected = json.loads(subprocess.check_output([BIN, "--rex", self.rex, "jobs", "inspect", "--registry", str(registry),
                               "--socket", str(self.socket), "--session", self.session, "--block", launch["created"]["block_id"]], env=self.runtime_env))
        self.assertEqual(inspected["entry"]["receipt_path"], launch["receipt_path"])
        gate.touch()
        final = self.receipt(launch, 10000)
        self.assertEqual(final["kind"], "run_visible_result")
        self.assertEqual(final["exit_report"]["exit_code"], 7)
        self.assertFalse(final["success"])
        self.assertTrue(final["pane_retained_on_request"])
        self.assertFalse(final["cleanup"]["attempted"])
        self.assertEqual(raw(final["stdout"]), "detached α\n".encode())
        self.assertEqual(raw(final["stderr"]), b"separate stderr")
        self.assertEqual(final["jobs"]["forget_outcome"], "forgotten")
        self.assertEqual(json.loads(subprocess.check_output([BIN, "jobs", "list", "--registry", str(registry)]))["entries"], [])
        self.assertEqual(Path(launch["receipt_path"]).stat().st_mode & 0o777, 0o600)
        self.assertIn(launch["created"]["block_id"], self.blocks())
        # Reader is private, bounded, no-follow and independent of a Rex endpoint.
        for mode in (0o644,):
            Path(launch["receipt_path"]).chmod(mode)
            rejected = subprocess.run([BIN, "run-visible", "receipt", "--file", launch["receipt_path"]], capture_output=True, text=True)
            self.assertEqual(rejected.returncode, 1)
        Path(launch["receipt_path"]).chmod(0o600)
        link = self.work / "receipt-link"
        link.symlink_to(launch["receipt_path"])
        rejected = subprocess.run([BIN, "run-visible", "receipt", "--file", str(link)], capture_output=True, text=True)
        self.assertEqual(rejected.returncode, 1)

    def test_detach_success_failure_and_deadline_close_owned_pane(self):
        sentinel = self.anchor_pane()
        for code in (0, 7):
            with self.subTest(code=code):
                process = subprocess.run(self.command(f"import time,sys;time.sleep(.4);print('code {code}');sys.exit({code})", extra=["--detach"]),
                                         env=self.runtime_env, capture_output=True, text=True, timeout=10)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                launch = json.loads(process.stdout)
                self.addCleanup(shutil.rmtree, launch["storage_dir"], True)
                final = self.receipt(launch, 10000)
                self.assertEqual(final["exit_report"]["exit_code"], code)
                self.assertEqual(final["success"], code == 0)
                self.assertTrue(final["cleanup"]["block_absence_verified"])
                self.assertNotIn(launch["created"]["block_id"], self.blocks())
                self.assertIn(sentinel, self.blocks())
                self.assertEqual(json.loads(Path(launch["receipt_path"]).read_text()), final)
        process = subprocess.run(self.command("import time;time.sleep(60)", extra=["--detach", "--keep-open", "--timeout-ms", "150"]),
                                 env=self.runtime_env, capture_output=True, text=True, timeout=10)
        launch = json.loads(process.stdout)
        self.addCleanup(shutil.rmtree, launch["storage_dir"], True)
        final = self.receipt(launch, 10000)
        self.assertEqual(final["outcome"], "deadline_exceeded")
        self.assertIsNotNone(final["exit_report"]["signal"])
        self.assertTrue(final["cleanup"]["block_absence_verified"])
        self.assertFalse(final["pane_retained_on_request"])

    def test_detach_caller_loss_channel_jobs_and_binary_output_survive(self):
        channel = self.root / ("detach-channel-" + self.work.name)
        channel.mkdir(mode=0o700)
        registry = self.work / "jobs"
        registry.mkdir(mode=0o700)
        block, log = self.receiver()
        gate = self.work / "caller-lost-gate"
        script = f'''import os,subprocess,time,sys
from pathlib import Path
while not Path({str(gate)!r}).exists():time.sleep(.02)
p=subprocess.run([{BIN!r},'agents','channel','--handle',os.environ['AGENT_CHANNEL'],'--request-id','f'*32,'--operation','send','--to','report-to','--message-file','-'],input=b'caller is gone',capture_output=True)
assert p.returncode==0,(p.stdout,p.stderr)
os.write(1,b'\\x00\\xffdetached\\n');sys.exit(0)
'''
        command = self.command(script, extra=["--detach", "--no-deadline", "--registry", str(registry), "--owner", "rivet", "--purpose", "caller loss",
                                             *self.channel_options(channel, block)])
        wrapper = ("import subprocess,time,sys\n" + f"p=subprocess.run({command!r},capture_output=True,text=True)\n" +
                   "assert p.returncode==0,(p.stdout,p.stderr)\nprint(p.stdout,flush=True)\ntime.sleep(60)\n")
        caller = subprocess.Popen([sys.executable, "-c", wrapper], env=self.runtime_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        launch = None
        try:
            import select
            self.assertTrue(select.select([caller.stdout], [], [], 10)[0])
            launch = json.loads(caller.stdout.readline())
            self.addCleanup(shutil.rmtree, launch["storage_dir"], True)
            self.assertEqual(launch["kind"], "run_visible_launch")
            caller.kill()
            caller.communicate(timeout=5)
            self.assertEqual(self.receipt(launch)["outcome"], "pending")
            gate.touch()
            final = self.receipt(launch, 15000)
            self.assertTrue(final["success"], final)
            self.assertEqual(raw(final["stdout"]), b"\x00\xffdetached\n")
            self.assertTrue(final["cleanup"]["block_absence_verified"])
            self.assertEqual(final["jobs"]["forget_outcome"], "forgotten")
            self.assertEqual(final["channel"]["outcomes"], {"delivered": 1})
            self.assertEqual([json.loads(line) for line in log.read_text().splitlines()], ["FROM teerex-test: caller is gone"])
            self.assertEqual({p.name for p in channel.iterdir()}, {"receipts.jsonl"})
        finally:
            if caller.poll() is None:
                caller.kill();caller.communicate(timeout=5)
            gate.touch()

    def test_detach_close_publisher_loss_and_timeout_keep_exit_evidence(self):
        for mode in ("kill-publisher", "hang-close", "drop-close"):
            with self.subTest(mode=mode):
                wrapper, log = self.wrapper(mode)
                result = subprocess.run(self.command("print('exit evidence survives')", extra=["--detach"], rex=wrapper),
                                        env=self.runtime_env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                launch = json.loads(result.stdout)
                self.addCleanup(shutil.rmtree, launch["storage_dir"], True)
                started = time.monotonic()
                final = self.receipt(launch, 12000)
                self.assertLess(time.monotonic() - started, 12)
                self.assertEqual(final["exit_report"]["exit_code"], 0)
                self.assertEqual(raw(final["stdout"]), b"exit evidence survives\n")
                self.assertFalse(final["success"])
                self.assertFalse(final["cleanup"]["block_absence_verified"])
                self.assertEqual(final["cleanup"]["block_absence"], "unknown")
                self.assertEqual(log.read_text().splitlines().count("close"), 1)
                if mode == "hang-close":
                    self.assert_stopped(int(Path(str(log) + "-pid").read_text()))
                if mode == "drop-close":
                    self.assertNotIn(launch["created"]["block_id"], self.blocks())

    def channel_options(self, directory, block):
        return ["--channel-dir", str(directory), "--report-to-session", self.session, "--report-to-block", block]

    def receiver(self):
        log, ready = self.work / "receiver.jsonl", self.work / "receiver.ready"
        code = ("import os,tty,termios,json\nfrom pathlib import Path\n"
                "tty.setraw(0,termios.TCSANOW);os.write(1,b'\\x1b[?2004h')\n"
                f"Path({str(ready)!r}).touch()\nbuf=b''\n"
                "while True:\n"
                " part=os.read(0,65536)\n if not part: break\n buf+=part\n"
                " while b'\\x1b[201~\\r' in buf:\n"
                "  raw,buf=buf.split(b'\\x1b[201~\\r',1)\n"
                f"  with open({str(log)!r},'a') as f:f.write(json.dumps(raw.removeprefix(b'\\x1b[200~').decode())+'\\n')\n")
        command = [BIN, "--rex", self.rex, "surfaces", "open", "--socket", str(self.socket), "--session", self.session,
                   "--layout", "tab", "--label", "channel recipient", "--", sys.executable, "-c", code]
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        block = json.loads(result.stdout)["created"]["block_id"]
        for _ in range(100):
            if ready.exists():
                break
            time.sleep(.02)
        self.assertTrue(ready.exists())
        return block, log

    def channel_round_trip(self, fenced, detached=False):
        directory = self.root / ("channel-" + self.work.name)
        directory.mkdir(mode=0o700)
        registry = self.root / ("registry-" + self.work.name)
        registry.mkdir(mode=0o700)
        block, log = self.receiver()
        gate, sent = self.work / "gate", self.work / "sent"
        script = f'''import json,os,socket,subprocess,time
from pathlib import Path
handle=os.environ['AGENT_CHANNEL']
assert handle==os.environ['LC_AGENT_CHANNEL']=={str(directory / 'handle.json')!r}
assert Path(handle).with_name('receipts.jsonl').read_bytes()==b''
for i,body in enumerate(['first β\\n', 'second report']):
 p=subprocess.run([{BIN!r},'agents','channel','--handle',handle,'--request-id',str(i)*32,'--operation','send','--to','report-to','--message-file','-'],input=body,text=True,capture_output=True)
 assert p.returncode==0,(p.stdout,p.stderr)
Path('/work/sent' if {fenced!r} else {str(sent)!r}).touch()
while not Path('/work/gate' if {fenced!r} else {str(gate)!r}).exists():time.sleep(.02)
h=json.loads(Path(handle).read_text())
def request(event_id,**changes):
 r=dict(launch_id=h['launch_id'],token=h['token'],request_id=event_id,operation='send',to='report-to',body='refused body');r.update(changes)
 with socket.socket(socket.AF_UNIX) as s:
  s.settimeout(5);s.connect(h['socket']);s.sendall(json.dumps(r).encode()+b'\\n');data=b''
  while b'\\n' not in data:data+=s.recv(65536)
 assert json.loads(data)['code']==1,data
request('2'*32,to='arbitrary-pane')
request('3'*32,token='wrong')
request('0'*32)
request('4'*32,operation='ack',session={self.session!r},block={block!r})
if {fenced!r}:
 for path,kind in [({str(self.socket)!r},'rex'),({str(registry)!r},'registry'),(str(Path(handle).parent/'receipts.jsonl'),'receipt')]:
  try:
   if kind=='rex':socket.socket(socket.AF_UNIX).connect(path)
   else:os.open(path,os.O_WRONLY if kind=='receipt' else os.O_RDONLY)
  except OSError:pass
  else:raise AssertionError('fence exposed '+kind)
'''
        argv = [sys.executable, "-c", script]
        if fenced:
            command = [shutil.which("bwrap"), "--die-with-parent", "--unshare-net"]
            for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc"):
                if Path(path).exists():
                    command += ["--ro-bind", path, path]
            command += ["--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", "/run", "--tmpfs", "/var",
                        "--ro-bind", sys.prefix, sys.prefix, "--ro-bind", BIN, BIN,
                        "--bind", str(self.work), "/work", "--ro-bind", str(directory), str(directory), "--chdir", "/work", "--"]
            # A separate cwd mount must not expose the registry or Rex socket.
            argv = command + argv
        options = self.channel_options(directory, block) + ["--timeout-ms", "60000"]
        if fenced:
            options += ["--registry", str(registry), "--owner", "rivet", "--purpose", "fenced channel"]
        if detached:
            options += ["--detach"]
        process = subprocess.Popen(self.command(argv=argv, extra=options),
                                   env=self.runtime_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        launch = None
        try:
            if detached:
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stdout + stderr)
                launch = json.loads(stdout)
                self.addCleanup(shutil.rmtree, launch["storage_dir"], True)
            for _ in range(700):
                if sent.exists() or (not detached and process.poll() is not None):
                    break
                time.sleep(.02)
            self.assertTrue(sent.exists(), "child stopped before both sends")
            if not detached:
                self.assertIsNone(process.poll())
            receipts = directory / "receipts.jsonl"
            live = [json.loads(line) for line in receipts.read_text().splitlines()]
            self.assertEqual([line["body"] for line in live], ["first β\n", "second report"])
            self.assertEqual([line["outcome"] for line in live], ["delivered", "delivered"])
            self.assertEqual(stat.S_IMODE(receipts.stat().st_mode), 0o600)
            (directory / "caller-owned").write_text("keep")
            gate.touch()
            if detached:
                packet = self.receipt(launch, 15000)
                self.assertTrue(packet["success"], packet)
                self.assertTrue(packet["cleanup"]["block_absence_verified"])
            else:
                stdout, stderr = process.communicate(timeout=15)
                packet = json.loads(stdout)
                self.assertEqual(process.returncode, 0, stderr + stdout)
            if fenced:
                self.assertEqual(packet["jobs"]["track_outcome"], "tracked")
                self.assertEqual(packet["jobs"]["forget_outcome"], "forgotten")
            self.assertEqual(packet["channel"]["count"], 6)
            self.assertEqual(packet["channel"]["outcomes"], {"delivered": 2, "refused": 4})
            lines = [json.loads(line) for line in receipts.read_text().splitlines()]
            self.assertEqual([line["outcome"] for line in lines], ["delivered"] * 2 + ["refused"] * 4)
            self.assertIn("fixed_channel_destination", lines[2]["failure_reason"])
            self.assertIn("token_mismatch", lines[3]["failure_reason"])
            self.assertIn("already_attempted", lines[4]["failure_reason"])
            self.assertIn("not_granted", lines[5]["failure_reason"])
            self.assertTrue(all("token" not in line for line in lines))
            self.assertEqual([json.loads(line) for line in log.read_text().splitlines()],
                             ["FROM teerex-test: first β\n", "FROM teerex-test: second report"])
            self.assertTrue(directory.is_dir())
            self.assertEqual({p.name for p in directory.iterdir()}, {"receipts.jsonl", "caller-owned"})
        finally:
            gate.touch()
            if launch is not None:
                self.receipt(launch, 10000)
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=10)

    def test_optional_channel_live_receipts_and_refusals(self):
        self.channel_round_trip(False)

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_FENCE") == "1", "explicit real Linux bubblewrap acceptance gate")
    def test_channel_through_real_read_only_bubblewrap_bind(self):
        self.assertEqual(sys.platform, "linux")
        self.assertIsNotNone(shutil.which("bwrap"))
        self.channel_round_trip(True)

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_FENCE") == "1", "explicit real Linux bubblewrap acceptance gate")
    def test_detached_channel_through_real_read_only_bubblewrap_bind(self):
        self.assertEqual(sys.platform, "linux")
        self.assertIsNotNone(shutil.which("bwrap"))
        self.channel_round_trip(True, detached=True)

    def test_channel_continues_past_old_count_limit_and_cancellation_cleans_up(self):
        block = self.anchor_pane()
        directory = self.work / "capped"
        directory.mkdir(mode=0o700)
        script = """import json,os,socket
from pathlib import Path
h=json.loads(Path(os.environ['AGENT_CHANNEL']).read_text())
for i in range(260):
 r=dict(launch_id=h['launch_id'],token='wrong',request_id=format(i,'032x'),operation='send',to='report-to',body='never delivered')
 with socket.socket(socket.AF_UNIX) as s:
  s.settimeout(5);s.connect(h['socket']);s.sendall(json.dumps(r).encode()+b'\\n');data=b''
  while b'\\n' not in data:data+=s.recv(65536)
 assert json.loads(data)['code']==1
assert json.loads(data)['result']['failure_reason']=='channel_token_mismatch'
"""
        # More than the former 256-request cap: allow the command's own 60 s budget on slow hosted Macs.
        result, packet = self.invoke(script, extra=self.channel_options(directory, block) + ["--timeout-ms", "60000"],
                                     client_timeout=75)
        self.assert_good(result, packet)
        lines = [json.loads(line) for line in (directory / "receipts.jsonl").read_text().splitlines()]
        self.assertEqual(len(lines), 260)
        self.assertEqual(lines[-1]["failure_reason"], "channel_token_mismatch")
        self.assertEqual(packet["channel"]["count"], len(lines))
        self.assertEqual(packet["channel"]["outcomes"], {"refused": 260})
        self.assertEqual({p.name for p in directory.iterdir()}, {"receipts.jsonl"})
        directory = self.work / "cancelled-channel"
        directory.mkdir(mode=0o700)
        marker = self.work / "running"
        command = self.command(f"from pathlib import Path;import time;Path({str(marker)!r}).touch();time.sleep(60)",
                               extra=self.channel_options(directory, block) + ["--no-deadline"])
        process = subprocess.Popen(command, env=self.runtime_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            for _ in range(250):
                if marker.exists() or process.poll() is not None:
                    break
                time.sleep(.02)
            self.assertTrue(marker.exists())
            process.terminate()
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 143, stdout + stderr)
            self.assertEqual(json.loads(stdout)["channel"]["count"], 0)
            self.assertEqual({p.name for p in directory.iterdir()}, {"receipts.jsonl"})
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)

    def test_channel_refuses_invalid_directories_before_argv(self):
        block = self.anchor_pane()
        marker = self.work / "must-not-start"
        directory = self.work / "channel"
        directory.mkdir(mode=0o700)
        occupied = directory / "existing"
        occupied.write_text("leave me")
        for mode in ("occupied", "mode", "symlink"):
            path = directory
            if mode == "mode":
                occupied.unlink()
                directory.chmod(0o755)
            if mode == "symlink":
                directory.chmod(0o700)
                path = self.work / "link"
                path.symlink_to(directory)
            result, packet = self.invoke(f"from pathlib import Path;Path({str(marker)!r}).touch()", extra=self.channel_options(path, block))
            self.assertNotEqual(result.returncode, 0)
            self.assertIsNone(packet.get("created"))
            self.assertFalse(marker.exists())
        self.assertTrue(directory.is_dir())
        result = subprocess.run(self.command(extra=["--channel-dir", str(directory)]), capture_output=True, text=True, env=self.runtime_env)
        self.assertEqual(result.returncode, 2)

    def test_optional_jobs_track_during_run_and_forget_after(self):
        registry = self.work / "jobs"
        registry.mkdir(mode=0o700)
        gate, started = self.work / "gate", self.work / "started"
        script = (f"import pathlib,time;pathlib.Path({str(started)!r}).touch()\n"
                  f"while not pathlib.Path({str(gate)!r}).exists(): time.sleep(.02)")
        process = subprocess.Popen(self.command(script, extra=["--registry", str(registry), "--owner", "rivet", "--purpose", "item · step", "--no-deadline"]),
                                   env=self.runtime_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            for _ in range(250):
                if started.exists() or process.poll() is not None:
                    break
                time.sleep(.02)
            self.assertTrue(started.exists())
            listing = json.loads(subprocess.check_output([BIN, "jobs", "list", "--registry", str(registry)]))
            self.assertEqual(len(listing["entries"]), 1)
            entry = listing["entries"][0]
            self.assertEqual((entry["owner"], entry["purpose"], entry["kind"], entry["cleanup"]), ("rivet", "item · step", "command", "manual"))
            self.assertIn(entry["block_id"], self.blocks())
            self.assertGreater(entry["deadline_unix_ms"], int(time.time() * 1000) + 29 * 86400000)
            gate.touch()
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr + stdout)
            receipt = json.loads(stdout)
            self.assertEqual(receipt["jobs"]["track_outcome"], "tracked")
            self.assertEqual(receipt["jobs"]["generation"], entry["generation"])
            self.assertEqual(receipt["jobs"]["forget_outcome"], "forgotten")
            self.assertEqual(json.loads(subprocess.check_output([BIN, "jobs", "list", "--registry", str(registry)]))["entries"], [])
        finally:
            gate.touch()
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=10)

    def test_jobs_tracking_survives_native_queue_past_old_transport_budget(self):
        import fcntl
        registry = self.work / "queued-jobs"
        registry.mkdir(mode=0o700)
        lock_path = registry / "lock"
        lock_path.touch(mode=0o600)
        marker = self.work / "queued-started"
        command = self.command(f"from pathlib import Path;Path({str(marker)!r}).touch()", extra=[
            "--registry", str(registry), "--owner", "rivet", "--purpose", "queued runner", "--startup-ms", "30000"])
        process = None
        try:
            with lock_path.open("r+") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                process = subprocess.Popen(command, env=self.runtime_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                time.sleep(5.5)
                self.assertIsNone(process.poll(), "native jobs queue must outlive the former5s wrapper budget")
                self.assertFalse(marker.exists(), "queued tracking must not permit argv")
            stdout, stderr = process.communicate(timeout=20)
            packet = json.loads(stdout)
            self.assertEqual(process.returncode, 0, stdout + stderr)
            self.assertTrue(marker.exists())
            self.assertEqual(packet["jobs"]["track_outcome"], "tracked")
            self.assertEqual(packet["jobs"]["forget_outcome"], "forgotten")
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                process.communicate(timeout=25)

    def test_optional_jobs_partial_flags_track_failure_and_forget_failure(self):
        registry = self.work / "jobs"
        registry.mkdir(mode=0o700)
        for flags in (["--registry", str(registry)], ["--owner", "rivet"], ["--purpose", "step"],
                      ["--registry", str(registry), "--owner", "rivet"]):
            result = subprocess.run(self.command(extra=flags), env=self.runtime_env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertEqual(self.blocks(), set())
        marker = self.work / "must-not-run"
        r, v = self.invoke(f"import pathlib;pathlib.Path({str(marker)!r}).touch()", extra=[
                           "--registry", str(self.work / "missing"), "--owner", "rivet", "--purpose", "refuse"])
        self.assertEqual(r.returncode, 1)
        self.assertEqual(v["outcome"], "jobs_tracking_failed")
        self.assertIsNone(v["exit_report"])
        self.assertFalse(marker.exists())
        self.assertTrue(v["cleanup"]["block_absence_verified"])
        r, v = self.invoke(f"import os;os.chmod({str(registry)!r},0o755)", extra=[
                           "--registry", str(registry), "--owner", "rivet", "--purpose", "failed forget"])
        self.assert_good(r, v)
        self.assertEqual(v["exit_report"]["exit_code"], 0)
        self.assertEqual(v["jobs"]["forget_outcome"], "lookup_failed")
        registry.chmod(0o700)

    def test_no_deadline_exit_cancellation_and_conflicting_timeout(self):
        r, v = self.invoke("import time;time.sleep(10.2);print('past default')", extra=["--no-deadline"])
        self.assert_good(r, v)
        self.assertIsNone(v["limits"]["execution_ms"])
        self.assertGreater(v["exit_report"]["elapsed_ms"], 10000)
        marker = self.work / "started"
        script = f"import pathlib,time;pathlib.Path({str(marker)!r}).touch();time.sleep(60)"
        process = subprocess.Popen(self.command(script, extra=["--no-deadline"]), env=self.runtime_env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            for _ in range(200):
                if marker.exists() or process.poll() is not None:
                    break
                time.sleep(.02)
            self.assertTrue(marker.exists())
            process.terminate()
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 143, stderr + stdout)
            receipt = json.loads(stdout)
            self.assertIsNone(receipt["limits"]["execution_ms"])
            self.assertEqual(receipt["outcome"], "cancel_requested")
            self.assertTrue(receipt["cleanup"]["block_absence_verified"])
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
        result = subprocess.run(self.command(extra=["--no-deadline", "--timeout-ms", "1000"]),
                                env=self.runtime_env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.blocks(), set())

    def check_env_files(self, directory, secret, receipt):
        self.assertNotIn(secret, json.dumps(receipt, ensure_ascii=False))
        self.assertFalse((directory / "env.pipe").exists())
        for path in directory.rglob("*"):
            if path.is_file():
                data = path.read_bytes()
                self.assertNotIn(secret.encode(), data, str(path))
                self.assertNotIn(json.dumps(secret)[1:-1].encode(), data, str(path))
        requested = json.loads((directory / "request.json").read_text())
        self.assertNotIn("env", requested)
        expected = json.loads(self.envfile.read_text())
        encoded = json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        metadata = dict(keys=sorted(expected), sha256=hashlib.sha256(encoded).hexdigest(), transport="private_fifo")
        self.assertEqual(requested["environment"], metadata)
        self.assertEqual(receipt["environment"], metadata)
        self.assertEqual((directory / "stdin").read_bytes(), self.stdin.read_bytes())

    def env_privacy_run(self, detached):
        # This synthetic value never occurs in argv/stdin/output; compare in the child
        # against the caller's input file rather than printing a credential.
        secret = "synthetic-env-only-" + str(time.monotonic_ns()) + "-é\n'😀"
        expected = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "SECRET_VALUE": secret, "EMPTY": "",
                    "LARGE_VALUE": "large-" * 9000}
        self.envfile.write_text(json.dumps(expected, ensure_ascii=False))
        directory = self.work / "private-output"
        gate = self.work / "finish"
        script = """import json,os,sys,time
from pathlib import Path
expected=json.loads(Path(sys.argv[1]).read_text())
actual=dict(os.environ)
# Apple Python mutates its environment during startup; this key is not added by the runner.
if sys.platform=='darwin' and '__CF_USER_TEXT_ENCODING' not in expected:
 actual.pop('__CF_USER_TEXT_ENCODING',None)
assert actual.pop('REX_SESSION').startswith('session:')
assert actual.pop('REX_BLOCK').startswith('block:')
assert actual==expected,'environment was not delivered exactly'
if sys.argv[2]=='detached':
 while not Path(sys.argv[3]).exists():time.sleep(.02)
print('exact environment received')
"""
        args = [sys.executable, "-c", script, str(self.envfile), "detached" if detached else "attached", str(gate)]
        result, packet = self.invoke(argv=args, extra=["--output-dir", str(directory)] + (["--detach"] if detached else []))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if detached:
            self.assertEqual(packet["kind"], "run_visible_launch")
            self.check_env_files(directory, secret, packet)
            gate.touch()
            packet = self.receipt(packet, 10000)
            self.assertEqual(packet["receipt_state"], "final")
            self.assertEqual(packet["exit_report"]["exit_code"], 0)
        else:
            self.assert_good(result, packet)
        self.assertEqual(raw(packet["stdout"]), b"exact environment received\n")
        self.check_env_files(directory, secret, packet)
        # The large value forces multiple FIFO reads/writes, and must not persist either.
        for path in directory.rglob("*"):
            if path.is_file():
                self.assertNotIn(expected["LARGE_VALUE"].encode(), path.read_bytes(), str(path))

    def test_attached_env_values_not_retained_and_exact_child_environment(self):
        self.env_privacy_run(False)

    def test_detached_env_values_not_retained_at_launch_or_exit(self):
        self.env_privacy_run(True)

    def test_native_child_receives_exact_env_including_apple_runtime_key(self):
        # Native env observes the exec map without Apple's Python startup mutation.
        expected = json.loads(self.envfile.read_text())
        expected["__CF_USER_TEXT_ENCODING"] = "0x0:0:0"
        self.envfile.write_text(json.dumps(expected))
        for detached in (False, True):
            with self.subTest(detached=detached):
                result, packet = self.invoke(argv=["/usr/bin/env", "-0"], extra=["--detach"] if detached else [])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                if detached:
                    packet = self.receipt(packet, 10000)
                    self.assertEqual(packet["exit_report"]["exit_code"], 0)
                else:
                    self.assert_good(result, packet)
                actual = dict(item.decode().split("=", 1) for item in raw(packet["stdout"]).split(b"\0") if item)
                self.assertEqual(actual.pop("REX_SESSION"), self.session)
                self.assertEqual(actual.pop("REX_BLOCK"), packet["created"]["block_id"])
                self.assertEqual(actual, expected)

    def test_exact_argv_cwd_env_binary_stdin_and_owned_close(self):
        anchor = self.anchor_pane()
        before = self.rpc("session.view", {"session_id": self.session})
        arguments = ["", "a'b\"", "a\nb", "α😀", "$(touch SHOULD_NOT_EXIST)", "semi;colon"]
        script = "import os,sys,json;print(json.dumps([sys.argv[1:],os.getcwd(),os.environ['TEEREX_LITERAL'],os.environ['EMPTY'],sys.stdin.buffer.read().hex(),os.environ['REX_SESSION'],os.environ['REX_BLOCK'],os.getenv('REX_SERVER')]))"
        r, v = self.invoke(argv=[sys.executable, "-c", script, *arguments])
        self.assert_good(r, v)
        self.assertEqual(v["limits"]["execution_ms"], 10000)
        self.assertNotIn("jobs", v)
        self.assertNotIn("channel", v)
        self.assertEqual(json.loads(raw(v["stdout"])), [arguments, str(self.work.resolve()), "a\n'α😀", "", self.stdin.read_bytes().hex(), self.session, v["created"]["block_id"], None])
        self.assertFalse((self.work / "SHOULD_NOT_EXIST").exists())
        self.assertTrue(v["cleanup"]["block_absence_verified"])
        self.assertEqual(self.blocks(), {anchor})
        after = self.rpc("session.view", {"session_id": self.session})
        self.assertEqual(after["active_window_id"], before["active_window_id"])
        self.assertEqual(after["windows"][0]["focused_block_id"], before["windows"][0]["focused_block_id"])

    def test_anchored_placement_and_keep_open_actual_exit(self):
        anchor = self.anchor_pane()
        r, v = self.invoke("print('retained terminal')", extra=["--layout", "tiled", "--anchor", anchor, "--direction", "right", "--ratio", ".23", "--keep-open"])
        self.assert_good(r, v)
        self.assertEqual(self.blocks(), {anchor, v["created"]["block_id"]})
        self.assertAlmostEqual(v["placement"]["receipt"]["actual"]["pane_share"], .23)
        self.assertTrue(v["pane_retained_on_request"])
        self.assertFalse(v["cleanup"]["attempted"])
        self.assertEqual(v["exit_report"]["exit_code"], 0)
        status = self.rpc("com.superlogical.terminal.program_status", {"session_id": self.session, "block_id": v["created"]["block_id"], "args": {}})
        self.assertEqual(status["records"][0]["state"], "done")
        self.assertEqual(status["records"][0]["app"], "teerex-test")
        self.assertEqual(status["records"][0]["title"], "Visible α command")

    def test_exit7_signal_and_silent_wait(self):
        for script, code, sig in [("import sys;sys.exit(7)", 7, None),
                                  ("import os,signal;os.kill(os.getpid(),signal.SIGTERM)", None, 15)]:
            r, v = self.invoke(script)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertEqual(v["exit_report"]["exit_code"], code)
            self.assertEqual(v["exit_report"]["signal"], sig)
            self.assertEqual(v["outcome"], "exit_reported")
            self.assertTrue(v["cleanup"]["block_absence_verified"])
        r, v = self.invoke("import time;time.sleep(3.2);print('late bytes')", extra=["--timeout-ms", "5000"])
        self.assert_good(r, v)
        self.assertGreaterEqual(v["exit_report"]["elapsed_ms"], 3200)
        self.assertEqual(raw(v["stdout"]), b"late bytes\n")

    def test_split_utf8_binary_trailing_bytes_and_large_output(self):
        script = "import os,time;os.write(1,b'head\\xf0\\x9f');time.sleep(.05);os.write(1,b'\\x98\\x80tail\\n\\n\\0');os.write(2,b'\\xff\\x80bad')"
        r, v = self.invoke(script)
        self.assert_good(r, v)
        self.assertEqual(raw(v["stdout"]), "head😀tail\n\n\0".encode())
        self.assertEqual(raw(v["stderr"]), b"\xff\x80bad")
        self.assertTrue(v["stdout"]["complete"])
        self.assertTrue(v["stderr"]["complete"])
        r, v = self.invoke("import os;os.write(1,b'A'*3000000);os.write(2,b'B'*2000000)", extra=["--max-bytes", "257"])
        self.assert_good(r, v)
        self.assertEqual(v["stdout"]["bytes_seen"], 3000000)
        self.assertEqual(v["stderr"]["bytes_seen"], 2000000)
        self.assertEqual(sum(v[s]["retained_bytes"] for s in ("stdout", "stderr")), 257)
        for stream, byte in [("stdout", b"A"), ("stderr", b"B")]:
            self.assertEqual(raw(v[stream]), byte * v[stream]["retained_bytes"])
            self.assertFalse(v[stream]["complete"])
        r, v = self.invoke("import os;os.write(1,b'abc\\xf0\\x9f\\x98\\x80')", extra=["--max-bytes", "4"])
        self.assert_good(r, v)
        self.assertEqual(v["stdout"]["encoding"], "base64")
        self.assertEqual(raw(v["stdout"]), b"abc\xf0")

    def test_full_output_lifetime_privacy_and_disk_bound(self):
        output = self.work / "full-output"
        r, v = self.invoke("import os;os.write(1,b'A'*100000);os.write(2,b'B'*70000)", extra=["--output-dir", str(output), "--max-bytes", "7"])
        self.assert_good(r, v)
        self.assertTrue(v["storage_retained"])
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
        for stream, byte, count in [("stdout", b"A", 100000), ("stderr", b"B", 70000)]:
            self.assertEqual(Path(v[stream]["full_path"]).read_bytes(), byte * count)
            self.assertTrue(v[stream]["full_complete"])
            self.assertEqual(stat.S_IMODE(Path(v[stream]["full_path"]).stat().st_mode), 0o600)
        r, v = self.invoke("import os;os.write(1,b'x'*(65*1024*1024))", extra=["--output-dir", str(self.work / "too-large")])
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(v["outcome"], "full_output_limit_exceeded")
        self.assertEqual(sum(Path(v[s]["full_path"]).stat().st_size for s in ("stdout", "stderr")), 64 * 1024 * 1024)
        self.assertFalse(v["stdout"]["full_complete"])
        self.assertTrue(v["cleanup"]["block_absence_verified"])

    def long_command(self):
        pidfile = self.work / "pid"
        script = ("import os,pathlib,signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                  f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()));"
                  "print('before stop',flush=True);time.sleep(60)")
        return pidfile, script

    def assert_stopped(self, pid):
        for _ in range(100):
            status = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
            if not status or status.startswith("Z"):
                return
            time.sleep(.02)
        self.fail(f"fixture still running: {pid}")

    def test_deadline_and_cancel_int_term_override_keep_open(self):
        pidfile, script = self.long_command()
        r, v = self.invoke(script, extra=["--timeout-ms", "400", "--keep-open"])
        self.assertEqual(r.returncode, 124, r.stdout + r.stderr)
        self.assertEqual(v["exit_report"]["signal"], 9)
        self.assertEqual(v["outcome"], "deadline_exceeded")
        self.assertTrue(v["cleanup"]["block_absence_verified"])
        self.assert_stopped(int(pidfile.read_text()))
        for sig in (signal.SIGINT, signal.SIGTERM):
            pidfile.unlink()
            p = subprocess.Popen(self.command(script, extra=["--keep-open"]), env=self.runtime_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                for _ in range(200):
                    if pidfile.exists() or p.poll() is not None:
                        break
                    time.sleep(.02)
                self.assertTrue(pidfile.exists())
                # The still-running child must have an actual working report, not just a final done/error.
                output_blocks = self.blocks()
                self.assertEqual(len(output_blocks), 1)
                status = self.rpc("com.superlogical.terminal.program_status", {"session_id": self.session,
                    "block_id": next(iter(output_blocks)), "args": {}})
                self.assertEqual(status["records"][0]["state"], "working")
                self.assertEqual(status["records"][0]["app"], "teerex-test")
                self.assertEqual(status["records"][0]["title"], "Visible α command")
                p.send_signal(sig)
                out, err = p.communicate(timeout=10)
                v = json.loads(out)
                self.assertEqual(p.returncode, 128 + sig, out + err)
                self.assertEqual(v["outcome"], "cancel_requested")
                self.assertTrue(v["cleanup"]["block_absence_verified"])
                self.assertIn(b"before stop", raw(v["stdout"]))
                self.assert_stopped(int(pidfile.read_text()))
            finally:
                if p.poll() is None:
                    p.kill()
                    p.wait()

    def test_pipe_eof_is_not_exit_and_child_group_scope_is_honest(self):
        r, v = self.invoke("import os,time;os.close(1);os.close(2);time.sleep(60)", extra=["--timeout-ms", "400"])
        self.assertEqual(r.returncode, 124, r.stdout + r.stderr)
        self.assertGreaterEqual(v["exit_report"]["elapsed_ms"], 400)
        self.assertEqual(v["exit_report"]["signal"], 15)
        sentinel = self.anchor_pane()
        for detached in (False, True):
            pidfile = self.work / ("detached" if detached else "same-group")
            grand = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"
            script = ("import subprocess,sys,pathlib,time;"
                      f"p=subprocess.Popen([sys.executable,'-c',{grand!r}],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session={detached});"
                      f"pathlib.Path({str(pidfile)!r}).write_text(str(p.pid));time.sleep(.1)")
            try:
                r, v = self.invoke(script)
                self.assert_good(r, v)
                pid = int(pidfile.read_text())
                if detached:
                    os.kill(pid, 0)
                else:
                    self.assert_stopped(pid)
                self.assertIn(sentinel, self.blocks())
                self.assertFalse(v["all_descendants_verified_gone"])
            finally:
                if pidfile.exists():
                    with __import__('contextlib').suppress(ProcessLookupError):
                        os.kill(int(pidfile.read_text()), signal.SIGKILL)

    def test_bad_cwd_env_stdin_refuse_before_creation(self):
        before = self.blocks()
        r, v = self.invoke(argv=["/teerex-test-nonexistent-executable"])
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(v["outcome"], "launch_error")
        self.assertIsNone(v["exit_report"]["exit_code"])
        self.assertIsNone(v["exit_report"]["signal"])
        self.assertTrue(v["cleanup"]["block_absence_verified"])
        self.assertEqual(self.blocks(), before)
        command = self.command()
        command[command.index("--cwd") + 1] = str(self.work / "missing")
        r = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 1)
        self.assertIn("cwd_not_directory", r.stdout)
        self.assertEqual(self.blocks(), before)
        self.envfile.write_text('{"REX_BLOCK":"spoof"}')
        r = subprocess.run(self.command(), capture_output=True, text=True, timeout=10)
        self.assertEqual(r.returncode, 2)
        self.assertIn("reserved", r.stderr)
        self.envfile.write_text('{}')
        self.stdin.unlink()
        os.mkfifo(self.stdin)
        r, v = self.invoke()
        self.assertEqual(r.returncode, 1)
        self.assertIn("regular_file_required", v["failure_reason"])
        self.assertEqual(self.blocks(), before)

    def test_observed_api_gate_precedes_creation(self):
        before = self.blocks()
        if self.version["api_revision"] == 13:
            wrapper, log = self.wrapper("old-api")
        else:
            wrapper, log = self.rex, None
        r, v = self.invoke(rex=wrapper)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("requires_observed_api13", v["failure_reason"])
        if log is not None:
            self.assertFalse(log.exists(), "old API refusal must precede surfaces mutation")
        self.assertEqual(self.blocks(), before)

    def wrapper(self, mode):
        wrapper = self.work / (mode + "-rex")
        log = self.work / (mode + "-calls")
        wrapper.write_text(f"#!{sys.executable}\n" +
            "import json,os,subprocess,sys\n" +
            f"real={self.rex!r}; mode={mode!r}; log={str(log)!r}\n" +
            "a=sys.argv[1:]\n"
            "operation=None\n"
            "if '--args' in a:\n"
            " try: operation=json.loads(a[a.index('--args')+1]).get('operation')\n"
            " except (ValueError,IndexError): pass\n"
            "if operation:\n"
            " with open(log,'a') as f:f.write(operation+'\\n')\n"
            "if mode=='kill-publisher' and operation=='close': os.kill(os.getppid(),9);sys.exit(0)\n"
            "if mode=='hang-close' and operation=='close':\n"
            " import time\n"
            " from pathlib import Path\n"
            " Path(log+'-pid').write_text(str(os.getpid()));time.sleep(60)\n"
            "p=subprocess.run([real,*a],capture_output=True)\n"
            "out=p.stdout\n"
            "if mode=='old-api' and 'server.version' in a: out=json.dumps({'api_revision':12}).encode()\n"
            "if mode=='foreign-identity' and operation=='open':\n"
            " from pathlib import Path\n"
            " import time\n"
            " root=Path(json.loads(a[a.index('--args')+1])['argv'][-1]); ready=root/'ready.json'\n"
            " for unused in range(100):\n"
            "  if ready.exists(): break\n"
            "  time.sleep(.02)\n"
            " value=json.loads(ready.read_text());value['machine']='different-observed-kernel';ready.write_text(json.dumps(value))\n"
            "if (mode=='drop-create' and operation=='open') or (mode=='drop-close' and operation=='close'): out=b''\n"
            "if mode=='drop-create-final' and operation=='open': out=b'\\n'.join(l for l in out.splitlines() if b'\"event\":\"result\"' not in l)+b'\\n'\n"
            "sys.stdout.buffer.write(out);sys.stderr.buffer.write(p.stderr);sys.exit(p.returncode)\n")
        wrapper.chmod(0o700)
        return str(wrapper), log

    def test_lost_creation_and_close_acks_are_not_retried(self):
        sentinel = self.anchor_pane()
        for mode in ("drop-create", "drop-create-final", "drop-close"):
            wrapper, log = self.wrapper(mode)
            marker = self.work / (mode + "-ran")
            r, v = self.invoke(f"from pathlib import Path;Path({str(marker)!r}).write_text('ran')", rex=wrapper)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertFalse(v["success"])
            calls = log.read_text().splitlines()
            self.assertEqual(calls.count("open"), 1)
            self.assertEqual(v["cleanup"]["block_absence_verified"], mode == "drop-create-final")
            self.assertTrue(v["storage_retained"])
            if mode == "drop-create-final":
                self.assertIsNotNone(v["created"])
                self.assertEqual(v["outcome"], "creation_or_placement_uncertain")
                self.assertFalse(marker.exists())
                self.assertEqual(calls.count("close"), 1)
                self.assertNotIn(v["created"]["block_id"], self.blocks())
            elif mode == "drop-create":
                self.assertIsNone(v["created"])
                self.assertEqual(v["outcome"], "creation_or_placement_uncertain")
                self.assertFalse(marker.exists(), "unacknowledged creation must not execute argv")
                self.assertEqual(calls.count("close"), 0)
                self.assertEqual(len(self.blocks()), 2)
            else:
                self.assertIsNotNone(v["created"])
                self.assertTrue(marker.exists())
                self.assertEqual(calls.count("close"), 1)
                self.assertNotIn(v["created"]["block_id"], self.blocks())
            self.assertIn(sentinel, self.blocks())

    def test_observed_foreign_identity_refuses_without_executing_argv(self):
        wrapper, log = self.wrapper("foreign-identity")
        marker = self.work / "must-not-run"
        r, v = self.invoke(f"from pathlib import Path;Path({str(marker)!r}).touch()", rex=wrapper)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(v["outcome"], "foreign_pane_host_or_identity_refused")
        self.assertFalse(marker.exists())
        self.assertTrue(v["cleanup"]["block_absence_verified"])
        self.assertEqual(log.read_text().splitlines(), ["open", "close"])
        self.assertFalse((Path(v["storage_dir"]) / "permit.json").exists())

    def test_supervisor_loss_leaves_actual_exit_unknown_not_pane_death(self):
        output = self.work / "supervisor-loss"
        pidfile = self.work / "survivor"
        script = ("import os,pathlib,signal,time;"
                  f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()));"
                  "os.kill(os.getppid(),signal.SIGKILL);time.sleep(60)")
        try:
            r, v = self.invoke(script, extra=["--timeout-ms", "200", "--output-dir", str(output)])
            self.assertEqual(r.returncode, 124, r.stdout + r.stderr)
            self.assertIsNone(v["exit_report"])
            self.assertFalse(v["success"])
            self.assertTrue(v["cleanup"]["block_absence_verified"])
            self.assertFalse(v["all_descendants_verified_gone"])
            pid = int(pidfile.read_text())
            os.kill(pid, 0)  # Closing the pane did NOT prove this child died.
            record = json.loads((output / "controller.json").read_text())
            self.assertEqual(record["created"], v["created"])
        finally:
            if pidfile.exists():
                with __import__('contextlib').suppress(ProcessLookupError):
                    os.kill(int(pidfile.read_text()), signal.SIGKILL)

    def test_controller_sigkill_retains_known_ids_and_helper_own_deadline(self):
        output = self.work / "controller-loss"
        pidfile, script = self.long_command()
        p = subprocess.Popen(self.command(script, extra=["--timeout-ms", "700", "--output-dir", str(output)]),
                             env=self.runtime_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            for _ in range(200):
                if pidfile.exists() or p.poll() is not None:
                    break
                time.sleep(.02)
            self.assertTrue(pidfile.exists())
            p.kill()
            out, err = p.communicate(timeout=5)
            self.assertEqual(p.returncode, -signal.SIGKILL)
            self.assertEqual(out, "")
            for _ in range(200):
                if (output / "result.json").exists():
                    break
                time.sleep(.02)
            result = json.loads((output / "result.json").read_text())
            self.assertEqual(result["stop_reason"], "deadline_exceeded")
            self.assertEqual(result["signal"], 9)
            self.assert_stopped(int(pidfile.read_text()))
            record = json.loads((output / "controller.json").read_text())
            self.assertFalse(record["cleanup"]["attempted"])
            self.assertIn(record["created"]["block_id"], self.blocks())
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()


if __name__ == "__main__":
    unittest.main()
