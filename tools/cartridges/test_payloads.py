#!/usr/bin/env python3
"""Install a real native catalog and reuse the existing offline public contracts.

Usage: python3 tools/cartridges/test_payloads.py --catalog /canonical/catalog
Only disposable HOME is modified. Default acceptance needs no Rex. --with-rex
also runs runtime suites against fresh fixtures with explicitly selected API13 Rex.
The temporary test adapter translates the existing combined-CLI test argv into
separate installed executables; it is not a shipped cartridge or runtime shim.
"""
import argparse
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--with-rex", action="store_true", help="also run public runtime suites against explicitly selected disposable API13 Rex")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="teerex-real-cartridges-") as temporary:
        home = Path(temporary).resolve()
        root = home / "cartridges"
        env = dict(os.environ, HOME=str(home))
        command = [sys.executable, str(HERE / "cartridges.py"), "--root", str(root)]

        def call(*argv):
            result = subprocess.run(command + list(argv), env=env, capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stdout + result.stderr
            return json.loads(result.stdout)

        receipt = call("install", "--catalog", str(args.catalog.resolve()), "--all", "--allow-experimental", "--apply")
        packages = {m["id"]: m for m in receipt["packages"]}
        assert packages, "catalog contains no native packages"
        cases = []
        for key, item in packages.items():
            result = subprocess.run(command + ["run", key, "--", "--help"], env=env, capture_output=True, text=True, timeout=10)
            assert result.returncode == 0, result.stderr
            assert "Usage:" in result.stdout, result.stdout
            assert item["kind"] == "program" and item["status"] == "experimental"
            if key == "observe":
                assert "teerex spawn" not in result.stdout and "teerex run" not in result.stdout
            (root / "data" / key / "user-notes").write_text("retain this")
            # An individual leaf cannot dispatch another cartridge's command.
            result = subprocess.run(command + ["run", key, "--", "send" if key != "send" else "filter", "--help"], env=env, capture_output=True, text=True, timeout=10)
            assert result.returncode != 0, "unexpected cross-cartridge dispatch: " + key
            cases.append("native help and independent dispatch: " + key)
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
            invocation = [str(Path(packages[key]["code"]) / ("teerex-" + key))] if args.with_rex else command + ["run", key, "--"]
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
    main()
