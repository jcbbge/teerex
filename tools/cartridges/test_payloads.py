#!/usr/bin/env python3
"""Install a real native catalog and reuse the existing offline public contracts.

Usage: python3 tools/cartridges/test_payloads.py --catalog /canonical/catalog
Only disposable HOME is modified. Default acceptance needs no Rex. --with-rex
also runs runtime suites against fresh fixtures with explicitly selected API13 Rex.
The temporary test adapter translates the existing combined-CLI test argv into
separate installed executables; it is not a shipped cartridge or runtime shim.
"""
import argparse
import hashlib
import platform
import fcntl
import selectors
import shutil
import signal
import time
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


class ManagedRuntime(unittest.TestCase):
    """M1–M7 with stable disposable HOME; direct calls are labelled counterexamples."""
    def setUp(self):
        from test_cartridges import Lifecycle
        self.factory = Lifecycle()
        self.factory.setUp()
        self.addCleanup(self.factory.doCleanups)
        self.home, self.root = self.factory.home, self.factory.root
        logs = tempfile.TemporaryDirectory(prefix='managed-call-log-'); self.addCleanup(logs.cleanup)
        self.env = dict(self.factory.env, TEEREX_CALL_LOG_DIR=logs.name, TEEREX_CLUTCH_DIR=str(self.home / 'clutch'))
        self.command = [str(self.binary), 'cartridges', '--root', str(self.root)]
        receipt = self.call('install', '--all', '--catalog', str(self.native_catalog), '--allow-experimental', '--apply')
        self.packages = {p['id']: p for p in receipt['packages']}
        self.assertTrue(self.packages)
        self.assertTrue(all(p['kind'] == 'program' for p in self.packages.values()))
        self.processes = []
        self.addCleanup(self.stop_processes)

    def stop_processes(self):
        for p in self.processes:
            if p.poll() is None:
                p.terminate()
            p.communicate(timeout=10)

    def call(self, *argv, code=0):
        result = subprocess.run(self.command + list(argv), env=self.env, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return json.loads(result.stdout if code == 0 else result.stderr)

    def run_payload(self, key, args, managed=True):
        argv = self.command + ['run', key, '--', *args] if managed else [str(Path(self.packages[key]['code']) / ('teerex-' + key)), *args]
        p = subprocess.Popen(argv, env=self.env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.processes.append(p)
        return p

    def filter_args(self):
        spec = importlib.util.spec_from_file_location('filter_fixture', REPO / 'items/filter/test_filter.py')
        fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
        args = []
        for i in range(4):
            packet = fixture.observation()
            packet['observation_id'] = 'large-' + str(i)
            packet['capture'].update(max_bytes=65536, content=str(i) + 'x' * 60000)
            path = self.home / ('sample-' + str(i) + '.json')
            path.write_text(json.dumps(packet))
            args += ['--sample', str(path)]
        return args

    def blocked_filter(self, managed=True):
        p = self.run_payload('filter', self.filter_args(), managed)
        with selectors.DefaultSelector() as ready:
            ready.register(p.stdout, selectors.EVENT_READ)
            self.assertTrue(ready.select(10), 'native filter did not produce its first payload')
        # One full event proves native dispatch. Remaining output exceeds pipe
        # capacity, keeping this real native payload alive without a fake sleep.
        first = p.stdout.readline()
        self.assertEqual(json.loads(first)['kind'], 'rex_evidence_filter_sample')
        self.assertIsNone(p.poll())
        return p

    def remove(self, key, code=0):
        return self.call('remove', key, '--version', self.packages[key]['version'], '--deactivate', '--apply', code=code)

    def assert_refused_unchanged(self, argv, reason='in use or concurrent lifecycle operation'):
        before = self.factory.snapshot()
        start = time.monotonic()
        receipt = self.call(*argv, code=1)
        self.assertIn(reason, receipt['error'])
        self.assertLess(time.monotonic() - start, 1)
        self.assertEqual(self.factory.snapshot(), before)

    def test_M1_real_native_parity_and_environment(self):
        for key in sorted(self.packages):
            managed = subprocess.run(self.command + ['run', key, '--', '--help'], env=self.env, capture_output=True, timeout=10)
            direct = subprocess.run([str(Path(self.packages[key]['code']) / ('teerex-' + key)), '--help'], env=self.env, capture_output=True, timeout=10)
            self.assertEqual((managed.returncode, managed.stdout, managed.stderr), (direct.returncode, direct.stdout, direct.stderr))
        args = ['--sample', str(self.home / 'absent')]
        a = subprocess.run(self.command + ['run', 'filter', '--', *args], env=self.env, capture_output=True)
        b = subprocess.run([str(Path(self.packages['filter']['code']) / 'teerex-filter'), *args], env=self.env, capture_output=True)
        self.assertEqual(a.returncode, 2)
        self.assertEqual((a.returncode, a.stdout, a.stderr), (b.returncode, b.stdout, b.stderr))
        self.factory.package('env', code='#!/bin/sh\nprintf "%s\\n" "$TEEREX_CARTRIDGE_DATA" "$TEEREX_CARTRIDGE_DEPENDENCIES"\n')
        self.call('install', 'env', '--catalog', str(self.factory.catalog), '--apply')
        p = self.run_payload('env', [])
        out, err = p.communicate(timeout=10)
        self.assertEqual(p.returncode, 0, err)
        self.assertEqual(out.decode().splitlines(), [str(self.root / 'data/env'), '{}'])

    def test_M2_real_native_lease_upgrade_and_unrelated_removal(self):
        p = self.blocked_filter()
        self.assert_refused_unchanged(['remove', 'filter', '--version', self.packages['filter']['version'], '--deactivate', '--apply'])
        source = Path(self.packages['filter']['code'])
        destination = self.factory.catalog / 'filter/999.0.0'
        shutil.copytree(source, destination)
        manifest = json.loads((destination / 'manifest.json').read_text())
        manifest['version'] = '999.0.0'
        (destination / 'manifest.json').write_text(json.dumps(manifest))
        from test_cartridges import sha
        self.factory.entries = [dict(path='filter/999.0.0', manifest_sha256=sha(destination / 'manifest.json'))]
        self.factory.write_catalog()
        self.assert_refused_unchanged(['install', 'filter', '--catalog', str(self.factory.catalog), '--allow-experimental', '--apply'])
        self.remove('adapters')
        self.assertIsNone(p.poll())

    def test_M2_real_managed_watch(self):
        if not self.rex:
            self.skipTest('real watch requires --with-rex and REX_BIN; native filter lease still tested')
        fixture = tempfile.TemporaryDirectory(prefix='managed-watch-'); self.addCleanup(fixture.cleanup)
        fixture_root = Path(fixture.name).resolve()
        socket = fixture_root / 'rex.sock'
        base = [self.rex, '--autostart=false', '--server', 'unix://' + str(socket), '--timeout', '3s']
        log = (fixture_root / 'server.log').open('wb'); self.addCleanup(log.close)
        server = subprocess.Popen([self.rex, 'server', 'run', '--listen', 'unix://' + str(socket), '--restore=false', '--config', '/dev/null', '--state-dir', str(fixture_root / 'rex-state')], stdout=log, stderr=log, env=self.env)
        self.addCleanup(lambda: (server.terminate(), server.wait(timeout=10)))
        for _ in range(200):
            if socket.exists(): break
            self.assertIsNone(server.poll())
            time.sleep(.025)
        made = json.loads(subprocess.check_output(base + ['new', '--json', '--keep-open', '--shell=none', '--', '/bin/cat'], env=self.env))
        sid, bid = made['session_id'], made['initial_windows'][0]['block_ids'][0]
        self.env['TEEREX_INTERNAL_REX'] = self.rex
        baseline = self.home / 'baseline.json'
        observed = subprocess.run(self.command + ['run', 'observe', '--', 'observe', '--socket', str(socket), '--session', sid, '--block', bid], env=self.env, capture_output=True, timeout=10)
        self.assertEqual(observed.returncode, 0, observed.stderr)
        baseline.write_bytes(observed.stdout)
        p = self.run_payload('observe', ['watch', '--socket', str(socket), '--session', sid, '--block', bid, '--baseline', str(baseline), '--timeout-ms', '60000'])
        lease = self.root / 'leases/observe' / self.packages['observe']['version']
        # Observe the cooperative lease itself, not a timing-only sleep.
        for _ in range(200):
            if lease.exists():
                with lease.open('rb') as fd:
                    try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError: break
            self.assertIsNone(p.poll()); time.sleep(.025)
        else: self.fail('native watch did not hold its lease')
        self.assert_refused_unchanged(['remove', 'observe', '--version', self.packages['observe']['version'], '--deactivate', '--apply'])
        p.send_signal(signal.SIGTERM)
        out, err = p.communicate(timeout=10)
        self.assertEqual(p.returncode, 143, out + err)
        self.remove('observe')

    def test_M3_dependency_lease(self):
        self.factory.package('alpha')
        self.factory.package('beta', deps={'alpha': '1.0.0'}, code='#!/bin/sh\nprintf "%s\\n" "$TEEREX_CARTRIDGE_DEPENDENCIES"\nread answer\n')
        self.call('install', 'beta', '--catalog', str(self.factory.catalog), '--apply')
        p = self.run_payload('beta', [])
        self.assertEqual(json.loads(p.stdout.readline()), {'alpha': str(self.root / 'packages/alpha/1.0.0')})
        with (self.root / 'leases/alpha/1.0.0').open('rb') as lease:
            with self.assertRaises(BlockingIOError): fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assert_refused_unchanged(['remove', 'alpha', '--version', '1.0.0', '--deactivate', '--apply'], 'active dependent blocks removal')
        # Removing the dependent after release then succeeds, without deleting data.
        p.communicate(b'release\n', timeout=10)
        self.call('remove', 'beta', '--version', '1.0.0', '--deactivate', '--apply')
        self.call('remove', 'alpha', '--version', '1.0.0', '--deactivate', '--apply')

    def test_M4_immediate_registry_contention(self):
        with (self.root / '.lock').open('r+') as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for argv in (['run', 'filter', '--', '--help'], ['install', 'filter', '--catalog', str(self.native_catalog), '--allow-experimental', '--apply'], ['remove', 'filter', '--version', self.packages['filter']['version'], '--deactivate', '--apply']):
                self.assert_refused_unchanged(argv, 'in use or concurrent lifecycle operation: .lock')

    def test_M5_exit_releases_lease_and_retains_data(self):
        p = self.blocked_filter()
        data = self.root / 'data/filter/keep'
        data.write_bytes(b'private synthetic data')
        out, err = p.communicate(timeout=10)
        self.assertEqual(p.returncode, 0, err)
        self.assertIsNotNone(p.poll())
        with self.assertRaises(ProcessLookupError): os.kill(p.pid, 0)
        self.remove('filter')
        lease = self.root / 'leases/filter' / self.packages['filter']['version']
        self.assertEqual(lease.stat().st_size, 0)
        self.assertEqual(data.read_bytes(), b'private synthetic data')

    def test_M6_home_change_is_another_root(self):
        other = self.home / 'other'; other.mkdir(mode=0o700)
        env = dict(self.env, HOME=str(other))
        prefix = [str(self.binary), 'cartridges']
        listed = subprocess.run(prefix + ['list'], env=env, capture_output=True)
        self.assertEqual(json.loads(listed.stdout)['active'], {})
        run = subprocess.run(prefix + ['run', 'filter'], env=env, capture_output=True)
        self.assertEqual(run.returncode, 1)
        self.assertIn(b'cartridge root does not exist', run.stderr)

    def test_M7_direct_native_counterexample_has_no_lease(self):
        p = self.blocked_filter(managed=False)
        self.remove('filter')
        self.assertIsNone(p.poll())
        out, err = p.communicate(timeout=10)
        self.assertEqual(p.returncode, 0, err)


def managed_runtime(args):
    binary = Path(os.environ.get('TEEREX_BIN', REPO / 'zig-out/bin/teerex')).resolve()
    ManagedRuntime.binary = binary
    ManagedRuntime.native_catalog = args.catalog.resolve()
    ManagedRuntime.rex = (os.environ.get('REX_BIN') or shutil.which('rex')) if args.with_rex else None
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ManagedRuntime))
    index = json.loads((args.catalog / 'catalog.json').read_text())
    manifests = [json.loads((args.catalog / item['path'] / 'manifest.json').read_text()) for item in index['packages']]
    print(json.dumps(dict(ok=result.wasSuccessful(), contract_tests=result.testsRun, skipped=len(result.skipped), suite_invocation='managed_runtime', machine=platform.machine(), system=platform.system(), python=platform.python_version(), core_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), catalog_sha256=hashlib.sha256((args.catalog / 'catalog.json').read_bytes()).hexdigest(), native_cartridges=sorted(m['id'] for m in manifests), catalog_provenance=[{'id':m['id'],'version':m['version'],'provenance':m['provenance']} for m in manifests], boundaries='M1 parity and M7 direct calls are deliberate counterexamples; all other payload runtime calls use teerex cartridges run')))
    return 0 if result.wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--with-rex", action="store_true", help="also run public runtime suites against explicitly selected disposable API13 Rex")
    parser.add_argument("--managed-runtime", action="store_true", help="M1–M7 supported managed runtime with stable disposable HOME, native payloads and cooperative leases; excludes incompatible direct-suite assumptions")
    args = parser.parse_args()
    if args.managed_runtime:
        return managed_runtime(args)
    with tempfile.TemporaryDirectory(prefix="teerex-real-cartridges-") as temporary:
        home = Path(temporary).resolve()
        root = home / "cartridges"
        env = dict(os.environ, HOME=str(home))
        prefix = [str(Path(os.environ["TEEREX_BIN"]).resolve()), "cartridges"] if os.environ.get("TEEREX_BIN") else [sys.executable, str(HERE / "cartridges.py")]
        command = prefix + ["--root", str(root)]

        def call(*argv):
            result = subprocess.run(command + list(argv), env=env, capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stdout + result.stderr
            return json.loads(result.stdout)

        receipt = call("install", "--catalog", str(args.catalog.resolve()), "--all", "--allow-experimental", "--apply")
        packages = {m["id"]: m for m in receipt["packages"]}
        assert packages, "catalog contains no native packages"
        cases = []
        ready_plan = call("install", "--all", "--catalog", str(args.catalog.resolve()))
        assert sorted(item["id"] for item in ready_plan["packages"]) == sorted(key for key, item in packages.items() if item["status"] == "ready")
        for key, item in packages.items():
            result = subprocess.run(command + ["run", key, "--", "--help"], env=env, capture_output=True, text=True, timeout=10)
            assert result.returncode == 0, result.stderr
            assert "Usage:" in result.stdout, result.stdout
            assert item["kind"] == "program" and item["status"] in ("experimental", "ready")
            if item["status"] == "ready":
                evidence = item["compatibility"]["readiness"]
                assert evidence["covered_inputs_sha256"] and evidence["evidenced_api_revisions"] == item["compatibility"]["rex_api_revisions"]
            if key == "observe":
                assert "teerex spawn" not in result.stdout and "teerex run" not in result.stdout
            (root / "data" / key / "user-notes").write_text("retain this")
            # An individual leaf cannot dispatch another cartridge's command.
            result = subprocess.run(command + ["run", key, "--", "send" if key != "send" else "filter", "--help"], env=env, capture_output=True, text=True, timeout=10)
            assert result.returncode != 0, "unexpected cross-cartridge dispatch: " + key
            cases.append("native help and independent dispatch: " + key)
        # The core entry needs python3 on PATH. Public offline suites below
        # intentionally remove PATH, so retain their absolute-interpreter adapter.
        if "filter" in packages:
            arguments = ["--sample", str(home / "missing-sample")]
            managed = subprocess.run(command + ["run", "filter", "--", *arguments], env=env, capture_output=True)
            direct = subprocess.run([str(Path(packages["filter"]["code"]) / "teerex-filter"), *arguments], env=env, capture_output=True)
            assert managed.returncode != 0
            assert (managed.returncode, managed.stdout, managed.stderr) == (direct.returncode, direct.stdout, direct.stderr)
        adapter = home / "combined-test-interface"
        script = "#!/bin/sh\ncase \"$1\" in\n"
        mapping = {"filter": "filter", "maneuver-check": "maneuvers", "compare": "observe", "observe": "observe", "watch": "observe",
                   "jobs": "jobs", "adapters": "adapters", "spawn": "spawn", "send": "send", "run": "run", "offstage": "offstage", "doctor": "doctor"}
        for verb, key in mapping.items():
            if key not in packages:
                continue
            # Runtime suites deliberately change HOME and launch concurrent senders.
            # Exercise their installed payloads directly, without imposing the
            # manager's HOME-bound root and short nonblocking lifecycle mutex.
            # Manager help/dispatch above, offline mode, and lifecycle tests still
            # exercise the managed launcher and its separate lease contract.
            invocation = [str(Path(packages[key]["code"]) / ("teerex-" + key))] if args.with_rex else [sys.executable, str(HERE / "cartridges.py"), "--root", str(root), "run", key, "--"]
            prefix = " ".join(shlex.quote(s) for s in invocation)
            if key != "observe":
                script += f"{verb}) shift; exec {prefix} \"$@\" ;;\n"
            else:
                script += f"{verb}) exec {prefix} \"$@\" ;;\n"
        script += "*) exit 2 ;;\nesac\n"
        adapter.write_text(script)
        adapter.chmod(0o700)
        # HOME is embedded by the manager command only through process env;
        # original tests deliberately poison PATH/REX selectors, not HOME.
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(home)
        try:
            suite = unittest.TestSuite()
            contracts = [("filter", "test_filter.py", "FilterTest"), ("filter", "test_cache.py", "CacheTest"),
                         ("maneuvers", "test_maneuvers.py", None), ("observe", "test_observe.py", None if args.with_rex else "CompareTest"),
                         ("adapters", "test_adapters.py", None if args.with_rex else "OfflineTest")]
            if args.with_rex:
                contracts.extend((key, "test_" + key + ".py", None) for key in ("jobs", "send", "spawn", "run", "doctor", "offstage"))
            for key, filename, class_name in contracts:
                if key not in packages:
                    continue
                # Cache tests reuse the public filter fixture from their sibling module.
                sys.path.insert(0, str(REPO / "items" / key))
                try:
                    spec = importlib.util.spec_from_file_location("cartridge_contract_" + key + filename, REPO / "items" / key / filename)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                finally:
                    sys.path.pop(0)
                module.BIN = adapter
                if key == "observe": module.ROOT_SOCKET_DEFAULTS = False
                suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(getattr(module, class_name)) if class_name else unittest.defaultTestLoader.loadTestsFromModule(module))
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            assert result.wasSuccessful(), "installed standalone contract failed"
        finally:
            if old_home is None:
                del os.environ["HOME"]
            else:
                os.environ["HOME"] = old_home
        for key, item in packages.items():
            call("remove", key, "--version", item["version"], "--deactivate", "--apply")
            assert not Path(item["code"]).exists()
            assert (root / "data" / key / "user-notes").read_text() == "retain this"
            call("restore", key, "--version", item["version"], "--apply")
            assert key not in call("list")["active"], "restore must not auto-activate"
            cases.append("remove, retain data, restore inactive: " + key)
        print(json.dumps(dict(ok=True, native_cartridges=sorted(packages), contract_tests=result.testsRun, runtime_selected=args.with_rex,
                              suite_invocation="direct_installed_payload" if args.with_rex else "manager", checks=cases), indent=2))


if __name__ == "__main__":
    sys.exit(main())
