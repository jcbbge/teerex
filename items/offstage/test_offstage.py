"""Public offstage lifecycle on disposable macOS/Linux Rex; never a personal server."""
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

BIN = Path(os.environ.get("TEEREX_BIN", Path(__file__).resolve().parents[2] / "zig-out/bin/teerex"))

# Pass-through fault injection around real Rex. The embedded Lua is unchanged;
# only transport frames or the expected cleanup identity are perturbed.
FAULT_TRANSPORT = r'''
import json,os,subprocess,sys
from pathlib import Path
args=sys.argv[1:]
index=args.index('--args')+1
request=json.loads(args[index])
mode=os.environ['OFFSTAGE_FAULT']
if request['operation']=='close':
    if mode=='instance_changed':
        request['instance_id']='deliberately-different-instance'
        args[index]=json.dumps(request)
    if mode!='lost_close_receipt':
        os.execv(os.environ['OFFSTAGE_REAL_REX'],[os.environ['OFFSTAGE_REAL_REX'],*args])
    result=subprocess.run([os.environ['OFFSTAGE_REAL_REX'],*args],capture_output=True)
    sys.exit(1)
child=subprocess.Popen([os.environ['OFFSTAGE_REAL_REX'],*args],stdout=subprocess.PIPE)
try:
    for line in child.stdout:
        event=json.loads(line)
        if event['event']=='created':
            Path(os.environ['OFFSTAGE_CREATED']).write_text(event['block_id'])
        if mode=='lost_create_receipt' and event['event'] in ['creating','created']:
            if event['event']=='created':break
            continue
        sys.stdout.buffer.write(line);sys.stdout.buffer.flush()
        if mode=='malformed_after_create' and event['event']=='created':
            sys.stdout.buffer.write(b'{invalid-frame}\n');sys.stdout.buffer.flush();break
    else:
        sys.exit(child.wait())
finally:
    if child.poll() is None:
        child.terminate();child.wait(timeout=5)
sys.exit(1)
'''


def alive(pid):
    r = subprocess.run(["/bin/ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return r.returncode == 0 and not r.stdout.strip().startswith("Z")


class OffstageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform not in ("darwin", "linux"):
            raise RuntimeError("Offstage integration requires macOS or Linux")
        cls.rex = os.environ.get("REX_BIN") or shutil.which("rex")
        if not cls.rex or not BIN.is_file():
            raise RuntimeError("Build teerex and put test Rex on PATH")
        cls.tmp = tempfile.TemporaryDirectory(prefix="toff-", dir="/tmp")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        cls.socket = cls.root / "rex.sock"
        cls.base = [cls.rex, "--autostart=false", "--server", "unix://" + str(cls.socket), "--timeout", "2s"]
        cls.log = (cls.root / "server.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen([cls.rex, "server", "run", "--listen", "unix://" + str(cls.socket),
                                       "--restore=false", "--config", "/dev/null", "--state-dir", str(cls.root / "state")],
                                      stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.stop_server)
        for _ in range(100):
            if cls.socket.exists():
                break
            time.sleep(.05)
        else:
            raise RuntimeError("Disposable server did not start")
        created = cls.rex_json("new", "--json", "--shell=none", "--keep-open", "--", "/bin/sleep", "120")
        cls.session = created["session_id"]
        cls.anchor = created["initial_windows"][0]["block_ids"][0]

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
        return json.loads(subprocess.check_output(cls.base + list(args), text=True, timeout=10))

    def api(self, method, **args):
        return self.rex_json("api", "call", method, json.dumps(args))

    def blocks(self):
        return self.api("session.list_blocks", session_id=self.session)["blocks"]

    def command(self, argv, timeout=3000, limit=4096, cwd=None, socket=None):
        return [str(BIN), "offstage", "--socket", str(socket or self.socket), "--session", self.session,
                "--cwd", str(cwd or self.root), "--purpose", "disposable lifecycle check", "--timeout-ms", str(timeout),
                "--max-bytes", str(limit), "--", *argv]

    def invoked(self, argv, **kw):
        r = subprocess.run(self.command(argv, **kw), capture_output=True, text=True, timeout=12)
        return r, [json.loads(x) for x in r.stdout.splitlines()]

    def start(self, argv, **kw):
        p = subprocess.Popen(self.command(argv, **kw), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.reap, p)
        self.assertTrue(select.select([p.stdout], [], [], 8)[0], "no started receipt")
        first = json.loads(p.stdout.readline())
        self.assertEqual(first["kind"], "offstage_started")
        return p, first

    @staticmethod
    def reap(p):
        if p.poll() is None:
            p.terminate()
            try:
                p.communicate(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()
                p.communicate()

    def test_detached_addressable_observation_preserves_layout_and_literal_argv(self):
        view = self.api("session.view", session_id=self.session)
        original = self.blocks()
        token = 'literal α " $(touch SHOULD_NOT_EXIST); end'
        p, first = self.start([sys.executable, "-c", "import os,sys,time;print(os.getcwd(),sys.argv[1],flush=True);time.sleep(1)", token])
        target = first["target"]
        self.assertEqual(target["session_id"], self.session)
        self.assertEqual(first["execution_location"], "selected_rex_terminal_host")
        block = self.api("session.describe_block", session_id=self.session, block_id=target["block_id"])["block"]
        self.assertEqual(block["placement"], "detached")
        self.assertEqual(self.api("session.view", session_id=self.session), view)
        observed = subprocess.run([str(BIN), "observe", "--socket", str(self.socket), "--session", self.session,
                                   "--block", target["block_id"]], capture_output=True, text=True, timeout=6)
        self.assertEqual(observed.returncode, 0, observed.stderr)
        packet = json.loads(observed.stdout)
        self.assertIn(token, packet["capture"]["content"])
        self.assertEqual(Path(packet["process"]["data"]["child"]["cwd"]), self.root.resolve())
        output, error = p.communicate(timeout=8)
        final = json.loads(output)
        self.assertEqual(p.returncode, 0, error)
        self.assertTrue(final["cleanup"]["block_absent"])
        self.assertTrue(final["success"])
        self.assertEqual(final["invocation_id"], first["invocation_id"])
        self.assertIn(token, final["capture"]["content"])
        self.assertFalse((self.root / "SHOULD_NOT_EXIST").exists())
        self.assertEqual(self.blocks(), original)
        self.assertEqual(self.api("session.view", session_id=self.session), view)

    def test_actual_exits_and_failed_cwd_never_become_success(self):
        for code in [0, 7]:
            with self.subTest(code=code):
                r, events = self.invoked([sys.executable, "-c", f"import sys;print('exit-evidence',flush=True);sys.exit({code})"])
                final = events[-1]
                self.assertEqual(r.returncode, 0 if code == 0 else 1, r.stderr)
                self.assertEqual(final["exit_code_reported"], code)
                self.assertEqual(final["success"], code == 0)
                self.assertEqual(final["task_completion"], "not_assessed")
                self.assertTrue(final["cleanup"]["block_absent"])
                self.assertFalse(final["cleanup"]["all_processes_verified_gone"])
        marker = self.root / "bad-cwd-ran"
        r, events = self.invoked([sys.executable, "-c", f"open({str(marker)!r},'w').write('BAD')"], cwd=self.root / "missing")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(events[-1]["exit_code_reported"], 125)
        self.assertFalse(marker.exists())
        self.assertTrue(events[-1]["cleanup"]["block_absent"])

    def test_deadline_closes_block_but_does_not_claim_resistant_descendant_stopped(self):
        pidfile = self.root / "survivor.pid"
        code = ("import os,signal,time,pathlib\nif os.fork()==0:\n "
                f"signal.signal(signal.SIGHUP,signal.SIG_IGN);signal.signal(signal.SIGTERM,signal.SIG_IGN);pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()));time.sleep(120)\n"
                "time.sleep(120)\n")
        r, events = self.invoked([sys.executable, "-c", code], timeout=700)
        pid = int(pidfile.read_text())
        try:
            final = events[-1]
            self.assertEqual(r.returncode, 124, r.stderr)
            self.assertEqual(final["outcome"], "deadline_exceeded")
            self.assertIsNone(final["exit_code_reported"])
            self.assertTrue(final["cleanup"]["close_acknowledged"])
            self.assertTrue(final["cleanup"]["block_absent"])
            self.assertFalse(final["cleanup"]["all_processes_verified_gone"])
            self.assertTrue(alive(pid), "control must demonstrate actual close limitation")
        finally:
            if alive(pid):
                os.kill(pid, signal.SIGKILL)

    def test_cancellation_and_owner_crash_have_distinct_lifetime_results(self):
        for sig in [signal.SIGINT, signal.SIGTERM]:
            with self.subTest(sig=sig):
                p, first = self.start(["/bin/sleep", "120"])
                p.send_signal(sig)
                output, error = p.communicate(timeout=8)
                final = json.loads(output)
                self.assertEqual(p.returncode, 128 + sig, error)
                self.assertEqual(final["outcome"], "cancel_requested")
                self.assertEqual(final["cancellation_signal"], sig)
                self.assertTrue(final["cleanup"]["block_absent"])
                self.assertFalse(final["success"])
        p, first = self.start(["/bin/sleep", "120"])
        bid = first["target"]["block_id"]
        for _ in range(100):
            process = self.api("com.superlogical.terminal.process", session_id=self.session, block_id=bid, args={})
            if process.get("child"):
                break
            time.sleep(.02)
        self.assertIsNotNone(process.get("child"))
        p.kill()
        p.communicate(timeout=3)
        try:
            self.assertIn(bid, [b["block_id"] for b in self.blocks()])
            process = self.api("com.superlogical.terminal.process", session_id=self.session, block_id=bid, args={})
            self.assertIsNotNone(process.get("child"))
        finally:
            self.api("block.close", session_id=self.session, block_id=bid)

    def test_bounded_prefix_and_fail_closed_selection(self):
        for limit in [256, 65536]:
            r, events = self.invoked([sys.executable, "-c", "print('α \\\"'*1800,flush=True)"], limit=limit)
            self.assertEqual(r.returncode, 0, r.stderr)
            capture = events[-1]["capture"]
            self.assertLessEqual(len(json.dumps(capture["content"], ensure_ascii=False).encode()), limit)
            self.assertEqual(capture["complete"], limit == 65536)
        r, events = self.invoked(["/usr/bin/true"], socket=self.root / "absent.sock")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(len(events), 1)
        self.assertFalse(events[-1]["creation_acknowledged"])
        self.assertFalse((self.root / "absent.sock").exists())
        for suffix in [[], ["--session", self.session], ["--timeout-ms", "99"], ["--purpose", ""]]:
            command = self.command(["/usr/bin/true"])
            if suffix:
                index = command.index("--")
                command[index:index] = suffix
            else:
                command = [str(BIN), "offstage"]
            r = subprocess.run(command, capture_output=True, text=True, timeout=5)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertEqual(r.stdout, "")

    def test_real_resource_survives_lost_create_acknowledgement_without_retry(self):
        original = {b["block_id"] for b in self.blocks()}
        r, events, bid = self.fault("lost_create_receipt", ["/bin/sleep", "120"])
        try:
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertEqual(len(events), 1)
            final = events[-1]
            self.assertFalse(final["creation_dispatch_observed"])
            self.assertIsNone(final["creation_request_may_have_run"])
            self.assertFalse(final["creation_acknowledged"])
            self.assertIsNone(final["target"]["block_id"])
            self.assertFalse(final["cleanup"]["attempted"])
            self.assertFalse(final["success"])
            self.assertEqual({b["block_id"] for b in self.blocks()} - original, {bid})
        finally:
            self.api("block.close", session_id=self.session, block_id=bid)

    def fault(self, mode, argv):
        with tempfile.TemporaryDirectory(prefix="fault-", dir=self.root) as root:
            root = Path(root)
            wrapper = root / "rex"
            wrapper.write_text(f"#!{sys.executable}\n" + FAULT_TRANSPORT)
            wrapper.chmod(0o700)
            created = root / "created"
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"],
                       OFFSTAGE_FAULT=mode, OFFSTAGE_REAL_REX=self.rex, OFFSTAGE_CREATED=str(created))
            r = subprocess.run(self.command(argv), capture_output=True, text=True, timeout=12, env=env)
            return r, [json.loads(line) for line in r.stdout.splitlines()], created.read_text()

    def test_errors_and_unknown_cleanup_never_become_success(self):
        for mode in ["malformed_after_create", "lost_close_receipt", "instance_changed"]:
            with self.subTest(mode=mode):
                r, events, bid = self.fault(mode, ["/usr/bin/true"])
                try:
                    self.assertEqual(r.returncode, 1, r.stderr)
                    final = events[-1]
                    self.assertTrue(final["creation_acknowledged"])
                    self.assertFalse(final["success"])
                    self.assertFalse(final["cleanup"]["all_processes_verified_gone"])
                    exists = bid in {b["block_id"] for b in self.blocks()}
                    if mode == "malformed_after_create":
                        self.assertEqual(final["outcome"], "observation_failed")
                        self.assertTrue(final["cleanup"]["block_absent"])
                        self.assertFalse(exists)
                    elif mode == "lost_close_receipt":
                        self.assertEqual(final["exit_code_reported"], 0)
                        self.assertIsNone(final["cleanup"]["block_absent"])
                        self.assertIsNotNone(final["cleanup"]["failure_reason"])
                        self.assertFalse(exists, "actual close succeeded but its receipt was lost")
                    else:
                        self.assertFalse(final["cleanup"]["server_instance_matched"])
                        self.assertIsNone(final["cleanup"]["block_absent"])
                        self.assertTrue(exists, "identity mismatch must not close the block")
                finally:
                    if bid in {b["block_id"] for b in self.blocks()}:
                        self.api("block.close", session_id=self.session, block_id=bid)


if __name__ == "__main__":
    unittest.main()
