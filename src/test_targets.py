"""Public named-host/version checks; fixtures never contact a personal host."""
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import pty
import select
import time
import tty
import subprocess
import tarfile
import tempfile
import unittest

BIN = Path(os.environ.get("TEEREX_BIN", Path(__file__).resolve().parents[1] / "zig-out/bin/teerex"))


class TargetsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="teerex-targets-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.output = self.root / "observed.json"
        executable = self.root / "teerex fixture"
        executable.write_text("#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\n"
                              + "Path(" + repr(str(self.output)) + ").write_text(json.dumps(sys.argv[1:]))\nsys.exit(7)\n")
        executable.chmod(0o700)
        self.host = {"host_id": "fixture", "transport": "local", "home": str(self.root),
                     "platform": "linux-x86_64", "socket": str(self.root / "selected socket"),
                     "rex": str(self.root / "pinned rex"), "teerex": str(executable), "store": str(self.root / "private store")}
        self.config = self.root / "hosts.json"
        self.save()

    def save(self):
        self.config.write_text(json.dumps({"schema_version": 1, "hosts": {"hive": self.host}}))

    def call(self, *args):
        return subprocess.run([str(BIN), *args], capture_output=True, text=True, timeout=10,
                              env=dict(os.environ, REX_SERVER="unix:///poisoned", REX_SESSION="wrong"))

    def test_version_and_explicit_resolution(self):
        version = self.call("--version")
        self.assertEqual((version.returncode, version.stdout, version.stderr), (0, "teerex 0.1.0-alpha.5\n", ""))
        resolved = self.call("targets", "resolve", "--config", str(self.config), "--host", "hive")
        self.assertEqual(resolved.returncode, 0, resolved.stderr)
        result = json.loads(resolved.stdout)
        self.assertEqual(result["host"], dict(self.host, name="hive"))
        self.assertEqual(result["identity_basis"], "explicit_configuration_not_observed_identity")
        self.assertFalse(self.output.exists())

    def test_unknown_host_conflicting_target_and_duplicate_key_do_not_execute(self):
        for extra in (("--host", "absent", "observe"),
                      ("--host", "hive", "observe", "--socket", "/explicit")):
            result = self.call("--config", str(self.config), *extra)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(self.output.exists())
        self.config.write_text('{"schema_version":1,"schema_version":1,"hosts":{}}')
        result = self.call("targets", "resolve", "--config", str(self.config), "--host", "hive")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate config key", result.stderr)

    def test_selected_host_literal_argv_status_and_no_secret_receipt(self):
        secret = "literal ; touch " + str(self.root / "MUST_NOT_EXIST") + " $(false) α"
        result = self.call("--config", str(self.config), "--host", "hive", "spawn", "--session", "session:test", "--", "sh", "-c", secret)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(json.loads(self.output.read_text()), ["--rex", self.host["rex"], "spawn", "--socket", self.host["socket"], "--session", "session:test", "--", "sh", "-c", secret])
        self.assertFalse((self.root / "MUST_NOT_EXIST").exists())
        self.assertNotIn(secret, result.stderr)
        receipt = json.loads(result.stderr)
        self.assertEqual(receipt["host_id"], "fixture")
        self.assertIs(receipt["retry"], False)

    def test_visible_execution_routes_socket_without_parsing_literal_argv(self):
        command = ["run-visible", "--session", "session:12345678-1234-1234-1234-123456789abc",
                   "--cwd", str(self.root), "--env-file", str(self.root / "env.json"),
                   "--stdin-file", "/dev/null", "--app", "fixture", "--title", "Visible α",
                   "--", "/absolute/program", "--socket", "literal-not-a-selector", "--tty"]
        result = self.call("--config", str(self.config), "--host", "hive", *command)
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(json.loads(self.output.read_text()),
                         ["--rex", self.host["rex"], "run-visible", "--socket", self.host["socket"], *command[1:]])

    def test_named_surface_rename_routes_exact_target_and_literal_label(self):
        for target in (("--window", "window:12345678-1234-1234-1234-123456789abc"),
                       ("--pane", "block:abcdef12-1234-1234-1234-123456789abc")):
            command = ["surfaces", "rename", "--session", "session:12345678-1234-1234-1234-123456789abc",
                       *target, "--label", "seat α ' $(literal)"]
            result = self.call("--config", str(self.config), "--host", "hive", *command)
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(json.loads(self.output.read_text()),
                             ["--rex", self.host["rex"], "surfaces", "rename", "--socket", self.host["socket"], *command[2:]])

    def test_named_global_surface_selectors_preserve_create_session_and_label(self):
        for leaf, options in (("resolve", ["--pane", "seat α"]),
                              ("ensure", ["--label", "seat α", "--create-session", "project α", "--focus", "yes",
                                          "--", "/absolute/program", "--session", "literal"])):
            command = ["surfaces", leaf, "--session", "any", *options]
            result = self.call("--config", str(self.config), "--host", "hive", *command)
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(json.loads(self.output.read_text()),
                             ["--rex", self.host["rex"], "surfaces", leaf, "--socket", self.host["socket"], *command[2:]])

    def test_records_store_routing_override_and_default(self):
        self.host["records_store"] = str(self.root / "records")
        self.save()
        for op in ("init", "new", "park", "add", "attach", "set", "close", "show", "resume", "navigate", "list", "lint", "export", "forget"):
            args = ["records", op, "--id", "record-a"]
            r = self.call("--config", str(self.config), "--host", "hive", *args)
            self.assertEqual(r.returncode, 7, r.stderr)
            injected = ["--socket", self.host["socket"], "--host", "fixture"] if op in ("park", "resume", "navigate") else []
            self.assertEqual(json.loads(self.output.read_text()), ["--rex", self.host["rex"], "records", op, *injected, "--store", self.host["records_store"], "--id", "record-a"])
        r = self.call("--config", str(self.config), "--host", "hive", "records", "list", "--store", "/explicit")
        self.assertEqual(r.returncode, 7, r.stderr)
        observed = json.loads(self.output.read_text())
        self.assertEqual(observed.count("--store"), 1)
        self.assertEqual(observed[-1], "/explicit")
        del self.host["records_store"]
        self.save()
        r = self.call("--config", str(self.config), "--host", "hive", "records", "list")
        self.assertEqual(r.returncode, 7, r.stderr)
        self.assertEqual(json.loads(self.output.read_text())[-1], self.host["home"] + "/.local/state/teerex-records")

    def test_nested_leaves_receive_only_their_supported_selectors(self):
        socket = ["--socket", self.host["socket"]]
        store = ["--store", self.host["store"]]
        target = [*socket, "--host", "fixture", *store]
        cases = []
        for prefix in (("boards",), ()):
            cases += [([*prefix, "state", op], store) for op in ("inspect", "remap-preview", "remap-apply") if prefix]
            for verb, operations in (("seat", ("register", "inspect", "clear")),
                                     ("inbox", ("append", "inspect", "clear")), ("fleet", ("report", "forget"))):
                cases += [([*prefix, verb, op], target) for op in operations]
            cases += [([*prefix, "inbox"], target), ([*prefix, "fleet"], store), ([*prefix, "ask"], target)]
        cases += [(["boards", "probe"], socket), (["boards", "try-route"], target)]
        cases += [(["surfaces", op], socket) for op in ("open", "ensure", "resolve", "inspect", "rename", "move", "focus", "close")]
        cases += [(["surfaces", "session", "ensure"], socket)]
        cases += [(["surfaces", "palette"], []), (["surfaces", "palette", "install"], socket)]
        cases += [(["jobs", op], [] if op == "list" else socket)
                  for op in ("list", "track", "inspect", "adopt", "present", "forget")]
        cases += [(["recovery", op], [] if op == "inspect" else socket)
                  for op in ("inspect", "snapshot", "restore", "update")]
        cases += [([op], socket) for op in ("snapshot", "restore", "update")]
        cases += [(["clutch", op], socket) for op in ("take", "release", "status", "palette")]
        cases += [(["run-visible", "receipt"], [])]
        cases += [(["adapters", op], socket) for op in ("generate", "call")]
        cases += [(["agents", op], target if op == "launch" else []) for op in
                  ("launch", "profiles", "shell", "exec", "channel", "fence-probe", "ack", "exited", "deliver", "inspect", "present", "stop", "supervise")]
        for path, selectors in cases:
            with self.subTest(path=path):
                # Public argv fixture tests placement without running a mutation or using help to bypass injection.
                result = self.call("--config", str(self.config), "--host", "hive", *path, "--fixture", "literal α")
                self.assertEqual(result.returncode, 7, result.stderr)
                self.assertEqual(json.loads(self.output.read_text()),
                                 ["--rex", self.host["rex"], *path, *selectors, "--fixture", "literal α"])
        registry_args = ["--jobs-registry", "/command-host/jobs"]
        for path, selectors in ((["boards", "probe"], socket), (["boards", "fleet"], store)):
            result = self.call("--config", str(self.config), "--host", "hive", *path, *registry_args)
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(json.loads(self.output.read_text()), ["--rex", self.host["rex"], *path, *selectors, *registry_args])
        for command, expected in ((["boards", "state", "inspect", "--store=" + str(self.root)],
                                   ["boards", "state", "inspect", "--store=" + str(self.root)]),
                                  (["boards", "fleet", "--config", "/selected/board-config", "--hosts", "m5,m1"],
                                   ["boards", "fleet", *store, "--config", "/selected/board-config", "--hosts", "m5,m1"]),
                                  (["agents", "profiles", "--config", "/selected/profiles"],
                                   ["agents", "profiles", "--config", "/selected/profiles"]),
                                  (["surfaces", "open", "--help"], ["surfaces", "open", "--help"])):
            result = self.call("--config", str(self.config), "--host", "hive", *command)
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(json.loads(self.output.read_text()), ["--rex", self.host["rex"], *expected])
        self.output.unlink()
        for selector in ("--socket=/wrong", "--server=unix:///wrong", "--host=wrong", "--rex=/wrong"):
            result = self.call("--config", str(self.config), "--host", "hive", "boards", "seat", "inspect", selector)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(self.output.exists())

    def test_named_nested_board_state_and_offline_jobs_use_real_leaf_parsers(self):
        store = Path(self.host["store"])
        store.mkdir(mode=0o700)
        self.host["teerex"] = str(BIN.resolve())
        rex = self.root / "must not invoke Rex"
        rex.write_text("#!/bin/sh\nprintf called > '" + str(self.output) + "'\nexit 99\n")
        rex.chmod(0o700)
        self.host["rex"] = str(rex)
        self.save()
        ids = ["--session", "session:12345678-1234-1234-1234-123456789abc",
               "--block", "block:abcdef12-1234-1234-1234-123456789abc"]
        def invoke(*command, expected=0):
            p = self.call("--config", str(self.config), "--host", "hive", *command)
            self.assertEqual(p.returncode, expected, p.stderr + p.stdout)
            return json.loads(p.stdout)
        self.assertEqual(invoke("boards", "state", "inspect")["state"]["seats"], [])
        invoke("boards", "seat", "register", *ids, "--owner", "operator")
        self.assertTrue(invoke("boards", "seat", "inspect", *ids)["registered"])
        report = self.root / "report.txt"
        report.write_text("exact β\nlast line\n\n")
        invoke("boards", "inbox", "append", *ids, "--from", "worker", "--message-file", str(report))
        state = invoke("boards", "state", "inspect")["state"]
        self.assertEqual(state["seats"][0]["records"][0]["body"], report.read_text())
        invoke("boards", "inbox", "inspect", *ids)
        # Remap a supplied address without any live server or mutation of the original pane.
        old = state["seats"][0]["target"]
        new = dict(old, block_id="block:fedcba98-7654-3210-fedc-ba9876543210")
        mapping = self.root / "map.json"
        mapping.write_text(json.dumps([dict(old=old, new=new)]))
        preview = invoke("boards", "state", "remap-preview", "--map-file", str(mapping))
        self.assertEqual(preview["outcome"], "preview_only")
        applied = invoke("boards", "state", "remap-apply", "--map-file", str(mapping),
                         "--generation", str(state["generation"]), "--reason", "explicit fixture remap")
        self.assertEqual(applied["outcome"], "applied")
        remapped = [*ids[:2], "--block", new["block_id"]]
        invoke("boards", "inbox", "clear", *remapped, "--generation", str(applied["generation"]), "--reason", "reviewed")
        state = invoke("boards", "state", "inspect")["state"]
        invoke("boards", "seat", "clear", *remapped, "--generation", str(state["generation"]), "--reason", "reviewed")
        invoke("boards", "fleet", "report", *ids, "--owner", "worker", "--purpose", "fixture", "--state", "unknown", "--detail", "no liveness claim")
        state = invoke("boards", "state", "inspect")["state"]
        invoke("boards", "fleet", "forget", *ids, "--generation", str(state["generation"]), "--reason", "reviewed")
        self.assertEqual(invoke("boards", "state", "inspect")["state"]["fleet"], [])
        jobs = self.root / "jobs"
        jobs.mkdir(mode=0o700)
        invoke("jobs", "list", "--registry", str(jobs))
        self.assertFalse(self.output.exists(), "offline leaves must not invoke Rex")

    def test_named_seat_send_appends_once_and_corrupt_store_never_falls_back(self):
        store = Path(self.host["store"])
        store.mkdir(mode=0o700)
        self.host["teerex"] = str(BIN.resolve())
        self.save()
        target = ["--session", "session:12345678-1234-1234-1234-123456789abc",
                  "--block", "block:abcdef12-1234-1234-1234-123456789abc"]
        prefix = [str(BIN), "--config", str(self.config), "--host", "hive"]
        register = subprocess.run([*prefix, "seat", "register", *target, "--owner", "operator"], capture_output=True, text=True, timeout=5)
        self.assertEqual(register.returncode, 0, register.stderr)
        message = "exact α\noperator draft stays untouched\n\n"
        sent = subprocess.run([*prefix, "send", *target, "--from", "worker", "--message-file", "-", "--timeout-ms", "500"], input=message, capture_output=True, text=True, timeout=5)
        self.assertEqual(sent.returncode, 0, sent.stderr)
        receipt = json.loads(sent.stdout)
        self.assertEqual(receipt["outcome"], "recorded")
        self.assertIs(receipt["terminal_input_attempted"], False)
        state = json.loads((store / "state.json").read_text())
        self.assertEqual([r["body"] for r in state["seats"][0]["records"]], [message])
        (store / "state.json").write_text("corrupt")
        sent = subprocess.run([*prefix, "send", *target, "--from", "worker", "--message-file", "-"], input=message, capture_output=True, text=True, timeout=5)
        self.assertEqual(sent.returncode, 1, sent.stderr)
        self.assertNotIn("explicit Rex executable", sent.stdout)
        self.assertIs(json.loads(sent.stdout)["terminal_input_attempted"], False)
        self.assertEqual((store / "state.json").read_text(), "corrupt")

    def test_embedded_fleet_installs_exact_native_bytes_without_source_tree(self):
        # The installed CLI must carry its reviewed support files, not locate this checkout.
        mac = platform.system() == "Darwin"
        tag = "v0.1.0-alpha.5"
        archive_platform = "aarch64-macos" if mac else "x86_64-linux"
        assets = self.root / "assets"
        assets.mkdir()
        archive = assets / ("teerex-" + tag + "-" + archive_platform + ".tar.gz")
        with tarfile.open(archive, "w:gz", format=tarfile.USTAR_FORMAT) as tar:
            for name, data in (("teerex", BIN.read_bytes()), ("README.md", b"test release"), ("RIGHTS.md", b"test rights")):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o700 if name == "teerex" else 0o600
                tar.addfile(info, io.BytesIO(data))
        (assets / "SHA256SUMS").write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n")
        prefix = self.root / "managed"
        self.host.update(home=str(self.root), platform="macos-arm64" if mac else "linux-x86_64",
                         install={"prefix": str(prefix)})
        self.save()
        env = dict(os.environ, HOME=str(self.root))
        args = ["fleet", "install", "--config", str(self.config), "--host", "hive", "--version", tag, "--from", str(assets)]
        def invoke(binary, *extra):
            result = subprocess.run([str(binary), *args, *extra], cwd=self.root, env=env,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            return json.loads(result.stdout)
        self.assertFalse(invoke(BIN)["applied"])
        self.assertFalse(prefix.exists())
        applied = invoke(BIN, "--apply")
        self.assertTrue(applied["ok"])
        installed = prefix / "current/teerex"
        self.assertEqual(installed.read_bytes(), BIN.read_bytes())
        self.assertEqual(subprocess.check_output([str(installed), "--version"], text=True), "teerex 0.1.0-alpha.5\n")
        # Executed away from source, this re-plans using only its embedded support bytes.
        self.assertTrue(invoke(installed)["ok"])
        self.assertFalse((self.root / "MUST_NOT_RUN").exists())

    def test_socket_defaults_preserve_exec_pid_tty_and_explicit_output_bytes(self):
        observed = self.root / "exec-observed.json"
        runtime = self.root / "python3"
        raw = b'RAW {"socket_source":"unaltered"}\x00\xff\n'
        runtime.write_text(f"#!{os.sys.executable}\nimport json,os,sys\nfrom pathlib import Path\n"
                           + f"Path({str(observed)!r}).write_text(json.dumps(dict(pid=os.getpid(),tty=os.isatty(1),argv=sys.argv[1:],source=os.getenv('TEEREX_SOCKET_SOURCE'))))\n"
                           + f"os.write(1,{raw!r})\n")
        runtime.chmod(0o700)
        socket = str(self.root / "no server socket")
        env = dict(os.environ, PATH=str(self.root), HOME=str(self.root),
                   TEEREX_CALL_LOG_DIR=str(self.root / "calls"))
        env.pop("TEEREX_SOCKET_SOURCE", None)
        for explicit in (False, True):
            for terminal in (False, True):
                with self.subTest(explicit=explicit, terminal=terminal):
                    command = [str(BIN), "boards", "probe"]
                    if explicit: command += ["--socket", socket]
                    env["REX_SERVER"] = "invalid:ignored" if explicit else "unix://" + socket.replace(" ", "%20")
                    if terminal:
                        master, slave = pty.openpty()
                        tty.setraw(slave)
                        try:
                            proc = subprocess.Popen(command, env=env, stdout=slave, stderr=subprocess.PIPE)
                            # Darwin can discard unread queued PTY bytes when the
                            # last slave closes. Drain while our slave stays open.
                            output = b""
                            deadline = time.monotonic() + 5
                            while len(output) < len(raw):
                                ready, _, _ = select.select([master], [], [], max(0, deadline-time.monotonic()))
                                if not ready: break
                                chunk = os.read(master, 8192)
                                if not chunk: break
                                output += chunk
                            os.close(slave)
                            slave = None
                            _, error = proc.communicate(timeout=5)
                            self.assertEqual(proc.returncode, 0, error)
                        finally:
                            os.close(master)
                            if slave is not None: os.close(slave)
                    else:
                        proc = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        output, error = proc.communicate(timeout=5)
                        self.assertEqual(proc.returncode, 0, error)
                    actual = json.loads(observed.read_text())
                    self.assertEqual(actual["pid"], proc.pid)
                    self.assertEqual(actual["tty"], terminal)
                    self.assertEqual(actual["source"], None if explicit else "REX_SERVER")
                    self.assertEqual(actual["argv"][-5:], ["probe", "--socket", socket, "--teerex", str(BIN.resolve())])
                    self.assertEqual(output, raw)

    def test_explicit_rex_pin_ignores_poisoned_path_without_retry(self):
        poison = self.root / "rex"
        poison.write_text("#!/bin/sh\nprintf poisoned > " + str(self.root / "MUST_NOT_RUN") + "\nexit 0\n")
        poison.chmod(0o700)
        pinned = self.root / "custom rex"
        pinned.write_text("#!/bin/sh\nprintf 'PINNED_DIAGNOSTIC' >&2\nexit 7\n")
        pinned.chmod(0o700)
        command = [str(BIN), "--rex", str(pinned), "observe", "--socket", "/not-contacted.sock",
                   "--session", "session:12345678-1234-1234-1234-123456789abc",
                   "--block", "block:abcdef12-1234-1234-1234-123456789abc"]
        result = subprocess.run(command, env=dict(os.environ, PATH=str(self.root)), capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn("PINNED_DIAGNOSTIC", result.stderr)
        self.assertIn(str(pinned), result.stderr)
        self.assertFalse((self.root / "MUST_NOT_RUN").exists())

    def test_explicit_ssh_tty_preserves_trust_and_literal_command(self):
        ssh_output = self.root / "ssh-argv.json"
        ssh = self.root / "ssh"
        ssh.write_text("#!/usr/bin/env python3\nimport json,os,sys\nfrom pathlib import Path\n"
                       + "Path(" + repr(str(ssh_output)) + ").write_text(json.dumps(sys.argv[1:]))\n"
                       + "os.execv('/bin/sh', ['/bin/sh', '-c', sys.argv[-1]])\n")
        ssh.chmod(0o700)
        self.host.update(transport="ssh", address="operator@example.invalid", port=2223,
                         known_hosts=str(self.root / 'known % hosts "quoted"'),
                         identity_file=str(self.root / "identity with spaces"))
        self.save()
        literal = "α 'quoted' ; touch " + str(self.root / "MUST_NOT_EXIST") + "\n$(false)"
        command = ["agents", "exec", "--payload", literal, "--", "--tty"]
        for tty in (False, True):
            with self.subTest(tty=tty):
                result = subprocess.run([str(BIN), "targets", "exec", "--config", str(self.config),
                                         "--host", "hive", *(["--tty"] if tty else []), "--", *command],
                                        env=dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ["PATH"]),
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 7, result.stderr)
                actual = json.loads(ssh_output.read_text())
                self.assertEqual(actual[:3], ["-F", "/dev/null", "-tt" if tty else "-T"])
                self.assertEqual(actual.count("-tt"), int(tty))
                self.assertEqual(actual.count("-T"), int(not tty))
                options = [actual[i + 1] for i, value in enumerate(actual[:-1]) if value == "-o"]
                for required in ("BatchMode=yes", "StrictHostKeyChecking=yes", "GlobalKnownHostsFile=/dev/null",
                                 "UpdateHostKeys=no", "ControlMaster=no", "ControlPath=none", "IdentitiesOnly=yes",
                                 "ForwardAgent=no", "ClearAllForwardings=yes", "ConnectTimeout=10"):
                    self.assertIn(required, options)
                self.assertIn('UserKnownHostsFile="' + str(self.root) + r'/known %% hosts \"quoted\""', options)
                self.assertEqual(actual[-6:-1], ["-i", self.host["identity_file"], "-p", "2223", self.host["address"]])
                self.assertEqual(json.loads(self.output.read_text()), ["--rex", self.host["rex"], *command])
                self.assertFalse((self.root / "MUST_NOT_EXIST").exists())
                self.assertNotIn(literal, result.stderr)
                self.assertIs(json.loads(result.stderr)["retry"], False)

    def test_tty_on_local_transport_does_not_allocate_or_parse_program_options(self):
        result = self.call("targets", "exec", "--config", str(self.config), "--host", "hive", "--tty",
                           "--", "filter", "--", "--tty")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(json.loads(self.output.read_text()), ["--rex", self.host["rex"], "filter", "--", "--tty"])

    def test_ssh_requires_explicit_pretrusted_fields_before_launch(self):
        self.host.update(transport="ssh", address="-oProxyCommand=evil", port=22)
        self.save()
        result = self.call("--config", str(self.config), "--host", "hive", "observe")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("literal SSH destination", result.stderr)
        self.assertFalse(self.output.exists())
        self.host["address"] = "operator@example.invalid"
        self.save()
        result = self.call("targets", "resolve", "--config", str(self.config), "--host", "hive")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("known_hosts", result.stderr)


if __name__ == "__main__":
    unittest.main()
