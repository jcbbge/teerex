#!/usr/bin/env python3
"""Install a real native catalog and reuse the existing offline public contracts.

Usage: python3 tools/cartridges/test_payloads.py --catalog /canonical/catalog
Only disposable HOME is modified. No Rex server is needed or started.
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
        mapping = {"filter": "filter", "maneuver-check": "maneuvers", "compare": "observe", "observe": "observe", "watch": "observe"}
        for verb, key in mapping.items():
            if key not in packages:
                continue
            prefix = " ".join(shlex.quote(s) for s in command + ["run", key, "--"])
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
            for key, class_name in (("filter", "FilterTest"), ("maneuvers", "ManeuverTest"), ("observe", "CompareTest")):
                if key not in packages:
                    continue
                spec = importlib.util.spec_from_file_location("cartridge_contract_" + key, REPO / "items" / key / ("test_" + key + ".py"))
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.BIN = adapter
                suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(getattr(module, class_name)))
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            assert result.wasSuccessful(), "installed standalone offline contract failed"
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
        print(json.dumps(dict(ok=True, native_cartridges=sorted(packages), offline_contract_tests=result.testsRun, checks=cases), indent=2))


if __name__ == "__main__":
    main()
