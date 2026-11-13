#!/usr/bin/env python3
"""Execute cartridge readiness rows against installed bytes and private Rex only."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest

from common import ROOT, Server, alive, controls, execute, observations, save, sha
from records import ROWS, RUBRIC, contract, read_json, validate, verdict

MANAGER = ROOT / "tools/cartridges/cartridges.py"


def now():
    return datetime.now(timezone.utc).isoformat()


def suite_outcomes(binary, server, combined):
    """Reuse the whole public suite; record each method's actual pass/skip/failure."""
    path = ROOT / "items/observe/test_observe.py"
    spec = importlib.util.spec_from_file_location("readiness_observe_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.BIN = binary
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    class Result(unittest.TestResult):
        def __init__(self):
            super().__init__()
            self.outcomes = {}
        def name(self, test):
            return ".".join(test.id().split(".")[-2:])
        def startTest(self, test):
            super().startTest(test)
            root_only = self.name(test) in {"ObserveTest.test_default_socket_decoding_and_explicit_override", "ObserveTest.test_platform_socket_default_is_reported_without_contact"}
            module.BIN = Path(combined) if root_only else binary
        def addSuccess(self, test):
            super().addSuccess(test)
            self.outcomes[self.name(test)] = "pass"
        def addFailure(self, test, error):
            super().addFailure(test, error)
            self.outcomes[self.name(test)] = "fail"
        def addError(self, test, error):
            super().addError(test, error)
            self.outcomes[self.name(test)] = "error"
        def addSkip(self, test, reason):
            super().addSkip(test, reason)
            self.outcomes[self.name(test)] = "skip"
        def addSubTest(self, test, subtest, error):
            super().addSubTest(test, subtest, error)
            if error is not None:
                self.outcomes[self.name(test)] = "fail"
    result = Result()
    old = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(server.env, TEEREX_BIN=str(binary))
        # Raw assertion/capture details never enter the public readiness record.
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            suite.run(result)
    finally:
        os.environ.clear()
        os.environ.update(old)
    return result.outcomes, result.wasSuccessful(), result.testsRun


def run_one(args, payload, version, index):
    mapping = contract(args.item)
    started = now()
    rows = {row: dict(pass_=False, detail="not_executed") for row in ROWS}
    outcomes = {}
    identity = None
    with tempfile.TemporaryDirectory(prefix="readiness-", dir="/tmp") as directory:
        root = Path(directory).resolve()
        with_server = Server(args.rex, root)
        server = with_server
        sentinel = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(900)"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            identity = server.version
            package_root = server.home / "cartridges"
            manager = [sys.executable, str(MANAGER), "--root", str(package_root)]
            lifecycle = []
            def manage(*argv, expected=0):
                result, _ = execute([*manager, *argv], server.env, timeout=30)
                lifecycle.extend([result.stdout, result.stderr])
                if result.returncode != expected:
                    raise ValueError("managed_lifecycle_exit_" + str(result.returncode))
                return result
            manage("install", args.item, "--catalog", args.catalog, "--allow-experimental", "--apply")
            installed = package_root / "packages" / args.item / version / ("teerex-" + args.item)
            if sha(installed) != sha(payload):
                raise ValueError("installed_payload_hash_mismatch")
            marker = "TEEREX_SECRET_CANARY_" + os.urandom(16).hex()
            session, block = server.fixture(marker)
            packet_dir = root / "evidence"
            packet_dir.mkdir(mode=0o700)
            old_packet, new_packet = packet_dir / "old.json", packet_dir / "new.json"
            for path in (old_packet, new_packet, packet_dir / "unsupported.json"):
                save(path, {})
            observe = observations(installed, server, session, block)
            # Warm the CLI's schema cache before the file-listing controls.
            server.command("api", "list")
            # Seed persistent manager paths before measuring the N6 delta.
            manage("run", args.item, "--", "observe", "--help")
            (package_root / "retired" / args.item).mkdir(mode=0o700, parents=True, exist_ok=True)
            if args.teerex:
                inspect = [args.teerex, "--rex", args.rex, "surfaces", "inspect", "--socket", str(server.socket), "--session", session, "--pane", block]
                initial_inspect, _ = execute(inspect, server.env)
                initial_geometry = json.loads(initial_inspect.stdout) if initial_inspect.returncode == 0 else None
            else:
                initial_geometry = None
            before = controls(server, session, block, sentinel)
            def row(name, action):
                try:
                    detail = action()
                    rows[name] = dict(pass_=True, detail=detail)
                except Exception as error:
                    rows[name] = dict(pass_=False, detail="failed:" + type(error).__name__ + ":" + str(error).splitlines()[0][:160])
            def R1():
                nonlocal outcomes
                for verb, expected in mapping["help_options"].items():
                    result, _ = execute([installed, verb, "--help"], server.env)
                    found = sorted(set(re.findall(rb"--[a-z][a-z-]*", result.stdout)))
                    if result.returncode or found != [x.encode() for x in sorted(expected)]:
                        raise ValueError("help_options_mismatch_" + verb)
                outcomes, successful, count = suite_outcomes(installed, server, args.teerex)
                named = {name for claim in mapping["claims"] for name in claim["tests"]}
                if not mapping["claims"] or any(not claim["tests"] for claim in mapping["claims"]):
                    raise ValueError("empty_contract_claim")
                if not successful or any(outcomes.get(name) != "pass" for name in named):
                    failed = sorted(name for name in named if outcomes.get(name) != "pass")
                    raise ValueError("public_contract_failed:" + ",".join(failed)[:140])
                return "help_exact;root_only_controls=2;public_tests=" + str(count) + ";all_claim_tests_passed"
            row("R1", R1)
            revision = identity.get("api_revision")
            rows["R2"] = dict(pass_=type(revision) is int and 10 <= revision <= 13, detail="observed_api=" + str(revision))
            rows["R3"] = dict(pass_=True, detail="fresh_private_server_and_HOME;no_retry")
            def R4():
                previous, _ = execute(observations(args.previous_teerex, server, session, block), server.env)
                current, _ = execute(observe, server.env)
                if previous.returncode or current.returncode:
                    raise ValueError("compat_observe_failed")
                save(old_packet, previous.stdout)
                save(new_packet, current.stdout)
                comparison, _ = execute([installed, "compare", "--before", old_packet, "--after", new_packet], server.env)
                if comparison.returncode or json.loads(comparison.stdout).get("kind") != "observation_changes":
                    raise ValueError("old_packet_compare_refused")
                waited, _ = execute([installed, "watch", "--socket", server.socket, "--session", session, "--block", block, "--baseline", old_packet, "--timeout-ms", "500"], server.env)
                if waited.returncode not in (0, 124) or json.loads(waited.stdout).get("outcome") not in ("change_observed", "deadline_exceeded"):
                    raise ValueError("old_packet_watch_refused")
                corrupt = json.loads(previous.stdout)
                corrupt["source"]["api_revision"] = 9
                save(packet_dir / "unsupported.json", corrupt)
                rejected, _ = execute([installed, "compare", "--before", packet_dir / "unsupported.json", "--after", new_packet], server.env)
                if rejected.returncode != 1 or rejected.stdout:
                    raise ValueError("unsupported_revision_accepted")
                return "schema1_old_packet_compare_watch_pass;api9_refused"
            row("R4", R4)
            def R5():
                observed = manage("run", args.item, "--", "observe", "--socket", str(server.socket), "--session", session, "--block", block)
                value = json.loads(observed.stdout)
                if value.get("target") != dict(server="unix://" + str(server.socket), session_id=session, block_id=block) or "capture" not in value:
                    raise ValueError("managed_observe_target_mismatch")
                save(new_packet, observed.stdout)
                manage("run", args.item, "--", "compare", "--before", str(new_packet), "--after", str(new_packet))
                command = [*manager, "run", args.item, "--", "watch", "--socket", str(server.socket), "--session", session,
                           "--block", block, "--baseline", str(new_packet), "--status-state", "done", "--no-deadline"]
                watcher = subprocess.Popen(command, env=server.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    time.sleep(.3)
                    busy = manage("remove", args.item, "--version", version, "--deactivate", "--apply", expected=1)
                    if "in use" not in busy.stderr.decode():
                        raise ValueError("managed_in_use_refusal_missing")
                    watcher.terminate()
                    stdout, stderr = watcher.communicate(timeout=5)
                    lifecycle.extend([stderr])
                    if watcher.returncode != 143 or json.loads(stdout).get("outcome") != "cancel_requested":
                        raise ValueError("managed_cancel_not_reported")
                finally:
                    if watcher.poll() is None:
                        watcher.kill()
                        watcher.communicate(timeout=5)
                manage("remove", args.item, "--version", version, "--deactivate", "--apply")
                manage("restore", args.item, "--version", version, "--apply")
                manage("activate", args.item, "--version", version, "--apply")
                if json.loads(manage("list").stdout)["active"].get(args.item) != version:
                    raise ValueError("managed_activation_missing")
                return "managed_observe_compare_watch_cancel;in_use_refused;remove_restore_activate"
            row("R5", R5)
            def R7():
                unknown, _ = execute([installed, "unknown-subcommand"], server.env)
                missing, _ = execute([installed, "observe", "--socket", root / "absent.sock", "--session", session, "--block", block], server.env)
                if unknown.returncode != 2 or unknown.stdout or missing.returncode != 1 or missing.stdout:
                    raise ValueError("exit_discipline_failed")
                return "unknown_verb=2;missing_server=1;no_success_stdout"
            row("R7", R7)
            required = ["ObserveTest.test_missing_target_diagnostics_keep_requested_route_and_watch_unknown", "CompareTest.test_api_range_preserves_revision_and_refuses_outside_bounds", "CompareTest.test_file_limits_malformed_packets_and_arguments", "ObserveTest.test_watch_target_source_transport_and_usage_fail_closed"]
            rows["R8"] = dict(pass_=all(outcomes.get(name) == "pass" for name in required), detail="named_unknown_refusal_tests=" + str(len(required)))
            def R9():
                names = ["ObserveTest.test_bounded_utf8_capture_marks_partial_prefix", "ObserveTest.test_exact_encoded_string_boundary"]
                if not all(outcomes.get(name) == "pass" for name in names):
                    raise ValueError("capture_limit_tests_failed")
                if not args.long or index:
                    return "capture_limit_tests_passed;long_wait=" + ("once_in_invocation" if args.long else "not_requested")
                baseline, _ = execute(observations(installed, server, session, block, 65535), server.env)
                save(new_packet, baseline.stdout)
                watcher = subprocess.Popen([str(installed), "watch", "--socket", str(server.socket), "--session", session, "--block", block,
                    "--baseline", str(new_packet), "--timeout-ms", "60000", "--interval-ms", "50"], env=server.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                samples = []
                began = time.monotonic()
                try:
                    while watcher.poll() is None:
                        elapsed = time.monotonic() - began
                        if elapsed >= 5:
                            r = subprocess.run(["ps", "-o", "rss=", "-p", str(watcher.pid)], capture_output=True, text=True)
                            if r.returncode == 0 and r.stdout.strip():
                                samples.append((elapsed, int(r.stdout.strip())))
                        time.sleep(1)
                    stdout, stderr = watcher.communicate(timeout=5)
                    if watcher.returncode != 124 or len(samples) < 50:
                        raise ValueError("long_watch_exit_or_samples_failed")
                    first = next(rss for elapsed, rss in samples if elapsed >= 10)
                    growth = max(0, samples[-1][1] - first)
                    if growth > 256:
                        raise ValueError("rss_growth_kib=" + str(growth))
                    return "quiet_wait=60000ms;rss_growth_kib=" + str(growth)
                finally:
                    if watcher.poll() is None:
                        watcher.kill()
                        watcher.communicate(timeout=5)
            row("R9", R9)
            def R10():
                live, _ = execute(observe, server.env)
                save(new_packet, live.stdout)
                waited, _ = execute([installed, "watch", "--socket", server.socket, "--session", session, "--block", block, "--baseline", new_packet, "--timeout-ms", "100"], server.env)
                value, wait_value = json.loads(live.stdout), json.loads(waited.stdout)
                if value.get("atomic_snapshot") is not False or "complete" not in value.get("capture", {}):
                    raise ValueError("capture_limits_missing")
                for key in ("process", "reported_directory", "program_status"):
                    if value.get(key) is not None and value[key].get("freshness") != "unknown":
                        raise ValueError("freshness_not_unknown")
                if wait_value.get("interpretation") != "none" or wait_value.get("all_descendants_verified_gone") is not False:
                    raise ValueError("wait_limits_missing")
                return "non_atomic;unknown_freshness;interpretation_none;descendants_not_verified"
            row("R10", R10)
            def R11():
                # Managed observe output is an explicitly private packet, not a lifecycle log.
                for entry in lifecycle:
                    if marker.encode() in entry:
                        try:
                            value = json.loads(entry)
                        except ValueError:
                            raise ValueError("privacy_canary_in_lifecycle_log")
                        if "capture" not in value:
                            raise ValueError("privacy_canary_in_lifecycle_log")
                if any((p.stat().st_mode & 0o777) != 0o600 for p in packet_dir.iterdir()) or packet_dir.stat().st_mode & 0o777 != 0o700:
                    raise ValueError("evidence_modes_not_private")
                return "no_canary_in_lifecycle_logs;packets0600;directory0700"
            row("R11", R11)
            def R6():
                after = controls(server, session, block, sentinel)
                delta = sorted(k for k in before if before[k] != after[k])
                if args.teerex:
                    final_inspect, _ = execute(inspect, server.env)
                    final_geometry = json.loads(final_inspect.stdout) if final_inspect.returncode == 0 else None
                    if initial_geometry is None or final_geometry is None:
                        raise ValueError("surface_geometry_not_observed")
                    # Root receipts carry ephemeral client/collection metadata; compare actual geometry.
                    if initial_geometry.get("actual") != final_geometry.get("actual"):
                        delta.append("surface_geometry")
                else:
                    raise ValueError("surface_inspector_required")
                if delta:
                    raise ValueError("control_delta:" + ",".join(delta))
                return "N1_N6_unchanged;surface_geometry_unchanged"
            row("R6", R6)
            result = dict(executor=args.executor or "", independent_executor=bool(args.executor and (args.executor.startswith("ci:") or args.author_executor and args.executor != args.author_executor)),
                server_instance_sha256=hashlib.sha256(str(server.identity.get("instance_id", "")).encode()).hexdigest(),
                rex=dict(sha256=sha(args.rex), version=identity["rex_version"], commit=identity.get("commit", "unknown"), api_revision=identity["api_revision"]),
                os=platform.system() + " " + platform.release(), arch=platform.machine(), started_at=started, finished_at=now(),
                rows={name: {"pass": row["pass_"], "detail": row["detail"]} for name, row in rows.items()})
            return result
        finally:
            sentinel.terminate()
            sentinel.wait(timeout=5)
            with_server.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--item", choices=["observe"], required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--rex", required=True)
    parser.add_argument("--previous-teerex", required=True)
    parser.add_argument("--teerex", help="combined CLI for the required surfaces-inspect control")
    parser.add_argument("--executor", help="ci:https://RUN_URL or local:HOST:AGENT; missing stays not_ready")
    parser.add_argument("--author-executor", help="local code author identity; local executor must differ to satisfy R12")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--long", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--merge", type=Path)
    args = parser.parse_args(argv)
    if not 1 <= args.runs <= 20 or not args.catalog.is_absolute() or not args.out.is_absolute():
        parser.error("absolute catalog/output and runs 1..20 required")
    if args.out.exists() and not args.merge:
        parser.error("output exists; use an explicit --merge")
    try:
        catalog = read_json(args.catalog / "catalog.json")
        candidates = []
        for entry in catalog["packages"]:
            directory = args.catalog / entry["path"]
            value = read_json(directory / "manifest.json")
            if value["id"] == args.item:
                candidates.append((directory, value))
        if len(candidates) != 1:
            raise ValueError("catalog_must_select_one_item")
        directory, package = candidates[0]
        provenance = package["provenance"]
        if provenance.get("source_tree_dirty") is not False:
            raise ValueError("dirty_catalog_refused")
        payload = directory / package["entrypoint"][0]
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        if revision != provenance["source_commit"] or subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip():
            raise ValueError("runner_requires_matching_clean_source")
        record = dict(schema_version=1, kind="cartridge_readiness", id=args.item, platform=package["platform"],
            rubric=RUBRIC, rubric_sha256=sha(ROOT / RUBRIC), source_commit=revision, source_tree_dirty=False,
            covered_paths=contract(args.item)["covered_paths"], payload_sha256=sha(payload), runs=[])
        if args.merge:
            previous = validate(read_json(args.merge), args.item, package["platform"], record["covered_paths"])
            if any(previous[key] != record[key] for key in ("source_commit", "payload_sha256", "rubric_sha256")):
                raise ValueError("readiness_merge_identity_mismatch")
            record["runs"].extend(previous["runs"])
        for index in range(args.runs):
            record["runs"].append(run_one(args, payload, package["version"], index))
        record.update(verdict(record))
        validate(record, args.item, package["platform"], record["covered_paths"])
        args.out.parent.mkdir(parents=True, exist_ok=True)
        save(args.out, record, mode=0o644)
        print(json.dumps(dict(kind="readiness_result", verdict=record["verdict"], failed_rows=record["failed_rows"], evidenced_api_revisions=record["evidenced_api_revisions"])))
        return 0 if record["verdict"] == "ready" else 1
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(json.dumps(dict(kind="readiness_error", reason=str(error).splitlines()[0][:200])), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
