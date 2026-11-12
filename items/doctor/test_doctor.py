"""Public doctor contract. Runtime checks use only disposable macOS Rex servers.

TEEREX_BIN selects the combined executable. TEEREX_OFFLINE_ONLY=1 runs native
argument/baseline/platform controls without Rex. No personal/default server is used.
"""

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


BIN = Path(os.environ.get("TEEREX_BIN", Path(__file__).resolve().parents[2] / "zig-out/bin/teerex"))
METHODS = ["server.version", *["com.superlogical.terminal." + x for x in ("format", "process", "pwd", "program_status")]]


class OfflineTest(unittest.TestCase):
    def invoke(self, *args):
        return subprocess.run([str(BIN), "doctor", *args], capture_output=True, text=True, timeout=5,
                              env=dict(os.environ, PATH="/no-rex-here"))

    def test_help_and_invalid_arguments_without_rex(self):
        result = self.invoke("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Discovery is not permission", result.stdout)
        for args in [[], ["--socket"], ["--socket", "relative"], ["--socket", "/tmp/x", "--socket", "/tmp/y"],
                     ["--socket", "/tmp/x", "--timeout-ms", "99"], ["--socket", "/tmp/x", "--timeout-ms", "60001"],
                     ["--socket", "/tmp/x", "--timeout-ms", "oops"], ["--socket", "/tmp/x", "--fix", "yes"]]:
            with self.subTest(args=args):
                result = self.invoke(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_invalid_baselines_rejected_before_rex(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "baseline.json"
            cases = ["{", "{}", "x" * (128 * 1024 + 1),
                     json.dumps({"schema_version": 1, "kind": "run_result", "adapter_identity": "a" * 64}),
                     json.dumps({"schema_version": 1, "kind": "rex_compatibility_doctor", "adapter_identity": None}),
                     json.dumps({"schema_version": 1, "kind": "rex_compatibility_doctor", "adapter_identity": "z" * 64})]
            for data in cases:
                path.write_text(data)
                result = self.invoke("--socket", "/tmp/not-used.sock", "--baseline", str(path))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")

    @unittest.skipIf(sys.platform == "darwin", "native non-Mac guard")
    def test_other_platforms_reject_without_launching_rex(self):
        result = self.invoke("--socket", "/tmp/not-used.sock")
        self.assertEqual(result.returncode, 1)
        self.assertIn("DoctorRequiresMacOS", result.stderr)
        self.assertEqual(result.stdout, "")


# Controlled faults wrap actual Rex discovery. No vendor descriptions/schema
# fixtures are copied into source. This wrapper is never shipped by the CLI.
SHIM = r'''
import json,os,signal,subprocess,sys,time
from pathlib import Path
args=sys.argv[1:]
with open(os.environ['DOCTOR_AUDIT'],'a') as f:f.write(json.dumps([args,{k:os.getenv(k) for k in ['REX_SERVER','REX_SESSION','REX_BLOCK','REX_CLIENT']}])+'\n')
mode=os.getenv('DOCTOR_FAULT','')
if mode=='hang':
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    child=subprocess.Popen([sys.executable,'-c','import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)'])
    Path(os.environ['DOCTOR_PIDS']).write_text(f'{os.getpid()} {child.pid}')
    os.close(1);os.close(2);time.sleep(60);sys.exit(99)
r=subprocess.run([os.environ['DOCTOR_REAL_REX'],*args],capture_output=True)
if r.returncode:sys.stdout.buffer.write(r.stdout);sys.stderr.buffer.write(r.stderr);sys.exit(r.returncode)
data=json.loads(r.stdout)
is_cli='version' in args and '--json' in args
is_server='call' in args and 'server.version' in args
is_format='describe' in args and 'com.superlogical.terminal.format' in args
if mode=='cli_revision' and is_cli:data['api_revision']=14
if mode=='server_revision' and is_server:data['api_revision']=9
if mode=='legacy_revision' and is_server:data.pop('api_revision',None)
if mode=='nonoverlap' and is_server:data['api_min_revision']=14
if mode.startswith('accepted_') and (is_server or is_cli):data['api_revision']=int(mode.split('_')[1]);data['rex_version']='injected-numeric-control'
if mode=='server_build' and is_server:data['rex_version']='different-build'
if mode=='required_arg' and is_format:data['args_schema']['required']=['unknown_required_arg']
if mode=='wrong_type' and is_format:data['output_schema']['properties']['content']['type']='integer'
if mode=='descriptor_prose' and is_format:data['description']='changed advertised prose'
if mode=='wrong_method' and is_format:data['invoke']['method']='session.close'
if mode=='missing_method' and is_format:sys.exit(1)
if mode=='malformed' and is_format:sys.stdout.write('{');sys.exit(0)
if mode=='oversize' and is_format:sys.stdout.write('x'*140000);sys.exit(0)
if mode=='no_exec_binding' and 'do' in args:data['exec_start']='nil'
if mode=='no_sleep_binding' and 'do' in args:data['sleep']='nil'
sys.stdout.write(json.dumps(data))
'''


@unittest.skipIf(os.environ.get("TEEREX_OFFLINE_ONLY") == "1", "explicit offline-only run")
class RuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != "darwin":
            raise RuntimeError("Runtime validation requires a disposable Mac, not Linux/VPS support")
        cls.rex = shutil.which("rex")
        if not cls.rex or not BIN.is_file():
            raise RuntimeError("Build teerex and put the explicitly selected test Rex on PATH")
        tmp = tempfile.TemporaryDirectory(prefix="tdoc-", dir="/tmp")
        cls.addClassCleanup(tmp.cleanup)
        cls.root = Path(tmp.name)
        cls.socket = cls.root / "rex.sock"
        cls.base = [cls.rex, "--autostart=false", "--server", "unix://" + str(cls.socket), "--timeout", "2s"]
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
            raise RuntimeError("Disposable Rex did not start")
        cls.shim_dir = cls.root / "shim"
        cls.shim_dir.mkdir()
        shim = cls.shim_dir / "rex"
        shim.write_text(f"#!{sys.executable}\n" + SHIM)
        shim.chmod(0o755)

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    def env(self, mode=""):
        audit = self.root / (self.id().split(".")[-1] + ".audit")
        return dict(os.environ, PATH=str(self.shim_dir) + os.pathsep + os.environ["PATH"],
                    DOCTOR_REAL_REX=self.rex, DOCTOR_AUDIT=str(audit), DOCTOR_FAULT=mode,
                    DOCTOR_PIDS=str(self.root / "hung.pids"), REX_SERVER="unix:///tmp/poison.sock",
                    REX_SESSION="session:poison", REX_BLOCK="block:poison", REX_CLIENT="client:poison")

    def command(self, *extra, socket=None):
        return [str(BIN), "doctor", "--socket", str(socket or self.socket), *extra]

    def invoke(self, mode="", *extra, **kwargs):
        result = subprocess.run(self.command(*extra, **kwargs), capture_output=True, text=True, env=self.env(mode), timeout=8)
        self.assertTrue(result.stdout, result.stderr)
        return result, json.loads(result.stdout)

    def test_real_discovery_is_narrow_read_only_and_not_behavior_certification(self):
        before = subprocess.check_output(self.base + ["session", "ls", "--json"])
        # Also exercise raw, unwrapped CLI responses rather than only shim JSON.
        direct = subprocess.run(self.command(), capture_output=True, text=True, timeout=8,
                                env=dict(os.environ, REX_SERVER="unix:///tmp/poison.sock", REX_BLOCK="block:poison"))
        self.assertEqual(direct.returncode, 0, direct.stderr)
        raw_packet = json.loads(direct.stdout)
        self.assertTrue(raw_packet["advertised_requirements_met"])
        self.assertFalse(raw_packet["behavior_certified"])
        self.assertEqual(raw_packet["server"], "unix://" + str(self.socket))
        result, packet = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(packet["diagnostics"], [])
        self.assertTrue(packet["cli_server_same_build"])
        self.assertTrue(packet["advertised_requirements_met"])
        self.assertFalse(packet["behavior_certified"])
        version = json.loads(subprocess.check_output(self.base + ["api", "call", "server.version"], text=True))
        self.assertEqual(packet["source"]["api_revision"], version["api_revision"])
        self.assertEqual(packet["accepted_api_revisions"], {"min": 10, "max": 13})
        self.assertIsNone(packet["api_revision_refusal"])
        self.assertEqual(packet["operation_advertised_requirements_met"], {"observe": True, "watch": True, "run": True})
        self.assertEqual(packet["server"], "unix://" + str(self.socket))
        self.assertEqual([x["method"] for x in packet["methods"]], METHODS)
        self.assertEqual([x["behavior_tested"] for x in packet["methods"]], [True, False, False, False, False])
        self.assertEqual(packet["run_behavior"], "not_tested_no_program_started")
        self.assertEqual(packet["offstage"], "not_assessed_contract_not_included")
        self.assertEqual(len(bytes.fromhex(packet["adapter_identity"])), 32)
        self.assertEqual(json.loads(before), json.loads(subprocess.check_output(self.base + ["session", "ls", "--json"])))
        audit = Path(self.env()["DOCTOR_AUDIT"])
        calls = [json.loads(line) for line in audit.read_text().splitlines()]
        self.assertEqual(len(calls), 8)
        for args, hints in calls:
            self.assertEqual(args[:7], ["--autostart=false", "--server", packet["server"], "--timeout", "2s", "--color", "never"])
            self.assertEqual(set(hints.values()), {None})
            tail = args[7:]
            allowed = [["version", "--json"], ["api", "call", "server.version"],
                       *[["api", "describe", m, "--json"] for m in METHODS]]
            if tail not in allowed:
                self.assertEqual(tail[:2], ["do", "-e"])
                self.assertEqual(len(tail), 3)
                self.assertNotIn("rex.call(", tail[2])
                self.assertNotIn("rex.exec.start(", tail[2])

    def test_baseline_unchanged_and_identity_invalidation(self):
        result, first = self.invoke()
        self.assertEqual(result.returncode, 0)
        baseline = self.root / "baseline.json"
        baseline.write_text(json.dumps(first))
        contents = baseline.read_bytes()
        result, same = self.invoke("", "--baseline", str(baseline))
        self.assertEqual(result.returncode, 0)
        self.assertEqual(same["identity_status"], "unchanged")
        self.assertFalse(same["adapter_revalidation_required"])
        for mode in ["server_build", "descriptor_prose"]:
            with self.subTest(mode=mode):
                result, changed = self.invoke(mode, "--baseline", str(baseline))
                self.assertEqual(result.returncode, 1)
                self.assertTrue(changed["advertised_requirements_met"])
                self.assertTrue(changed["adapter_revalidation_required"])
                self.assertEqual(changed["identity_status"], "changed_or_unknown")
                self.assertNotEqual(changed["adapter_identity"], first["adapter_identity"])
        self.assertEqual(baseline.read_bytes(), contents)

    def test_unsupported_cli_server_and_legacy_revisions_fail_closed(self):
        for mode, found in [("cli_revision", 14), ("server_revision", 9), ("legacy_revision", 0), ("nonoverlap", 14)]:
            with self.subTest(mode=mode):
                result, packet = self.invoke(mode)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(packet["api_revision_matches"])
                self.assertFalse(packet["advertised_requirements_met"])
                self.assertIsNone(packet["adapter_identity"])
                self.assertIn(str(found), packet["api_revision_refusal"])
                self.assertIn("10..13", packet["api_revision_refusal"])
                self.assertEqual({x["schema_status"] for x in packet["methods"]}, {"not_checked"})
                self.assertEqual([x["behavior_tested"] for x in packet["methods"]], [True, False, False, False, False])

    def test_numeric_acceptance_is_not_behavior_certification(self):
        # Injected identities exercise the range boundary only. They are NOT
        # substitute evidence for an actual old build (especially untested API11).
        for revision in [10, 11, 12, 13]:
            with self.subTest(revision=revision):
                result, packet = self.invoke(f"accepted_{revision}")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(packet["source"]["api_revision"], revision)
                self.assertEqual(packet["cli"]["api_revision"], revision)
                self.assertFalse(packet["behavior_certified"])
                self.assertIn("not_inferred_from_revision", packet["recorded_build_behavior"])

    def test_required_field_type_method_and_binding_faults_are_not_compatibility(self):
        for mode in ["required_arg", "wrong_type", "wrong_method", "missing_method", "malformed", "oversize", "no_exec_binding", "no_sleep_binding"]:
            with self.subTest(mode=mode):
                result, packet = self.invoke(mode)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(packet["advertised_requirements_met"])
                self.assertIsNone(packet["adapter_identity"])
                self.assertTrue(packet["adapter_revalidation_required"])
                if mode in ["required_arg", "wrong_type"]:
                    self.assertEqual(packet["methods"][1]["schema_status"], "selected_shape_mismatch")
                    self.assertTrue(packet["methods"][1]["advertised"])
                elif mode in ["no_exec_binding", "no_sleep_binding"]:
                    self.assertEqual(packet["lua_bindings"], "shape_mismatch")
                else:
                    self.assertEqual(packet["methods"][1]["schema_status"], "unknown")
                    self.assertIsNone(packet["methods"][1]["advertised"])
                    self.assertTrue(packet["diagnostics"])
                if mode == "no_exec_binding":
                    self.assertEqual(packet["operation_advertised_requirements_met"], {"observe": True, "watch": True, "run": False})
                elif mode == "no_sleep_binding":
                    self.assertEqual(packet["operation_advertised_requirements_met"], {"observe": True, "watch": False, "run": True})
                else:
                    self.assertEqual(packet["operation_advertised_requirements_met"], {"observe": False, "watch": False, "run": True})

    def test_missing_server_and_executable_do_not_autostart(self):
        missing = self.root / "missing.sock"
        result, packet = self.invoke(socket=missing)
        self.assertEqual(result.returncode, 1)
        self.assertIsNotNone(packet["cli"])
        self.assertIsNone(packet["source"])
        self.assertFalse(missing.exists())
        result = subprocess.run(self.command(), capture_output=True, text=True, timeout=5,
                                env=dict(os.environ, PATH="/no-rex-here"))
        self.assertEqual(result.returncode, 1)
        packet = json.loads(result.stdout)
        self.assertIsNone(packet["cli"])
        self.assertIsNone(packet["source"])
        self.assertFalse(packet["advertised_requirements_met"])

    def test_deadline_and_cancellation_stop_owned_hung_transport_group(self):
        for sig, expected in [(None, 124), (signal.SIGINT, 130), (signal.SIGTERM, 143)]:
            with self.subTest(sig=sig):
                env = self.env("hang")
                pids = Path(env["DOCTOR_PIDS"])
                pids.unlink(missing_ok=True)
                started = time.monotonic()
                proc = subprocess.Popen(self.command("--timeout-ms", "400" if sig is None else "5000"),
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                self.addCleanup(lambda p=proc: p.poll() is None and p.kill())
                for _ in range(200):
                    if pids.exists():
                        break
                    time.sleep(.005)
                self.assertTrue(pids.exists())
                owned = [int(x) for x in pids.read_text().split()]
                if sig is not None:
                    proc.send_signal(sig)
                out, err = proc.communicate(timeout=4)
                self.assertEqual(proc.returncode, expected, err)
                self.assertLess(time.monotonic() - started, 3)
                packet = json.loads(out)
                self.assertEqual(packet["outcome"], "deadline_exceeded" if sig is None else "cancel_requested")
                self.assertFalse(packet["advertised_requirements_met"])
                for pid in owned:
                    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
                    self.assertTrue(not state or state.startswith("Z"), f"Owned fixture {pid} still executing: {state}")


if __name__ == "__main__":
    unittest.main()
