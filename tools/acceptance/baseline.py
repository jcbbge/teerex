#!/usr/bin/env python3
"""C31 safe-subset controls and measured teerex/plain-Rex arms on private servers."""
import argparse
import base64
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import platform
import resource
import signal
import statistics
import subprocess
import sys
import tempfile
import time

from common import ROOT, EXCLUDED, Server, alive, controls, execute, observations, save, sha
from fail_fixture import ASSERTION, expected

FIXTURE = Path(__file__).with_name("fail_fixture.py")
MODES = ("F1", "F2", "F3", "F4", "F5", "F6")


def raw(node):
    return node["content"].encode() if node["encoding"] == "utf8" else base64.b64decode(node["content"], validate=True)


def fresh_metrics():
    return dict(calls=0, rex_client_launches=0, wall_ms=0, stdout_bytes=0, stderr_bytes=0,
                cpu_ms=0, maxrss_kib=0, output_dir_bytes=0, pane_side_cpu_ms=None,
                excluded=EXCLUDED, false_success=0, false_unknown=0)


def add(total, metric, rex=0):
    for key in ("calls", "stdout_bytes", "stderr_bytes", "wall_ms", "cpu_ms"):
        total[key] += metric[key]
    total["rex_client_launches"] += rex
    total["maxrss_kib"] = max(total["maxrss_kib"], metric["maxrss_kib"])


def invoke(argv, stats, env, rex=0, **kwargs):
    result, measurement = execute(argv, env, **kwargs)
    add(stats, measurement, rex)
    return result


def counted_rex(rex, root):
    # Count actual Rex execs, including nested surface/collector calls. The
    # wrapper records one byte then execs; it never stores command arguments.
    count = root / "rex-execs"
    count.touch(mode=0o600)
    shim = root / "bin"
    shim.mkdir(mode=0o700)
    wrapper = shim / "rex"
    save(wrapper, ("#!" + sys.executable + "\nimport os,sys\nf=os.open(" + repr(str(count)) + ",os.O_WRONLY|os.O_APPEND);os.write(f,b'x');os.close(f)\nos.execv(" + repr(str(rex)) + ",[" + repr(str(rex)) + "]+sys.argv[1:])\n").encode(), 0o700)
    return wrapper, count


def teerex_task(args, server, session, anchor, root, mode, keep=True, controller_signal=None, close_owned=True):
    root.mkdir(mode=0o700)
    began = time.monotonic_ns()
    wrapper, count = counted_rex(args.rex, root)
    args = copy.copy(args)
    args.rex = str(wrapper)
    server = copy.copy(server)
    server.env = dict(server.env, PATH=str(wrapper.parent) + os.pathsep + server.env["PATH"])
    server.base = [str(wrapper), *server.base[1:]]
    stats = fresh_metrics()
    def measured_command(*argv, **kwargs):
        return invoke([*server.base, *argv], stats, server.env, **kwargs)
    server.command = measured_command
    envfile = root / "env.json"
    gate = root / "release"
    save(envfile, dict(PATH=os.defpath, FIXTURE_DIR=str(root), FIXTURE_GATE=str(gate)))
    before = invoke(observations(args.teerex, server, session, anchor), stats, server.env, 1)
    save(root / "sentinel-before.json", before.stdout)
    output = root / "output"
    argv = [args.teerex, "--rex", args.rex, "run-visible", "--socket", str(server.socket), "--session", session,
            "--layout", "tiled", "--anchor", anchor, "--direction", "right", "--ratio", "0.3", "--cwd", str(root),
            "--env-file", str(envfile), "--stdin-file", "/dev/null", "--app", "c31", "--title", "c31 " + mode,
            "--timeout-ms", "2000" if mode == "F2" else "5000", "--max-bytes", "4096", "--output-dir", str(output)]
    if keep:
        argv.append("--keep-open")
    argv += ["--", sys.executable, str(FIXTURE), mode]
    # The waited controller and observer calls share accounting only after their
    # independent measurements finish; no cumulative RUSAGE samples overlap.
    # Consequently controller CPU/RSS uses wait4's child-local usage below.
    with ThreadPoolExecutor(max_workers=2) as workers:
        future = workers.submit(execute, argv, server.env, 15,
                                (1, controller_signal) if controller_signal else None)
        block = None
        end = time.monotonic() + 8
        watcher_future = None
        p0 = None
        while time.monotonic() < end and not future.done():
            try:
                state = json.loads((output / "controller.json").read_text())
                block = (state.get("created") or {}).get("block_id")
                if block and (output / "started.json").exists():
                    break
            except (FileNotFoundError, ValueError):
                pass
            time.sleep(.01)
        if block:
            p0_result = invoke(observations(args.teerex, server, session, block, 256), stats, server.env, 1)
            if not p0_result.returncode:
                p0 = json.loads(p0_result.stdout)
                save(root / "P0.json", p0)
                watch_argv = [args.teerex, "watch", "--socket", str(server.socket), "--session", session, "--block", block,
                              "--baseline", str(root / "P0.json"), "--status-state", "done", "--status-state", "error", "--timeout-ms", "8000"]
                watcher_future = workers.submit(execute, watch_argv, server.env, 12)
        # Every fixture waits for this controller-owned file, allowing P0/watch
        # to start before the first synthetic output/status report.
        time.sleep(.1)
        gate.touch()
        result, measured = future.result()
        add(stats, measured)
        value = json.loads(result.stdout)
        save(root / "receipt.json", value)
        watched = None
        if watcher_future:
            watcher, measured = watcher_future.result()
            add(stats, measured, 1)
            if watcher.stdout:
                watched = json.loads(watcher.stdout)
                save(root / "watch.json", watched)
        post = None
        comparison = None
        terminal_exit = None
        if block:
            blocks = server.rpc("session.list_blocks", dict(session_id=session))["blocks"]
            if any(b["block_id"] == block for b in blocks):
                terminal_exit = server.terminal(session, block, "process").get("last_exit")
                p1_result = invoke(observations(args.teerex, server, session, block, 256), stats, server.env, 1)
                if not p1_result.returncode:
                    post = json.loads(p1_result.stdout)
                    save(root / "P1.json", post)
                    if p0 is not None:
                        compared = invoke([args.teerex, "compare", "--before", str(root / "P0.json"), "--after", str(root / "P1.json")], stats, server.env)
                        if not compared.returncode:
                            comparison = json.loads(compared.stdout)
                            save(root / "comparison.json", comparison)
                if close_owned:
                    server.rpc("block.close", dict(session_id=session, block_id=block))
                    stats["rex_client_launches"] += 1
        try:
            pid = json.loads((output / "started.json").read_text())["pid"]
            if sys.platform == "darwin":
                sample = subprocess.run(["ps", "-o", "time=", "-p", str(pid)], capture_output=True, text=True)
                if sample.returncode == 0 and sample.stdout.strip():
                    minutes, seconds = sample.stdout.strip().split(":")[-2:]
                    stats["pane_side_cpu_ms"] = (int(minutes) * 60 + float(seconds)) * 1000
            else:
                fields = Path("/proc/%s/stat" % pid).read_text().rsplit(")", 1)[1].split()
                stats["pane_side_cpu_ms"] = (int(fields[11]) + int(fields[12])) * 1000 / os.sysconf("SC_CLK_TCK")
        except (OSError, ValueError, KeyError):
            pass
        stats["output_dir_bytes"] = sum(p.stat().st_size for p in output.rglob("*") if p.is_file()) if output.exists() else 0
        code = (value.get("exit_report") or {}).get("exit_code")
        stats["false_success"] = int(bool(value.get("success")) and (mode != "F4" or code != 0))
        stats["false_unknown"] = int(mode in ("F1", "F4", "F5", "F6") and code is None)
        stats["rex_client_launches"] = count.stat().st_size
        stats["wall_ms"] = (time.monotonic_ns() - began) / 1e6
        return dict(code=result.returncode, receipt=value, reported_status=watched,
                    direct_child_exit=value.get("exit_report"), terminal_program_exit=terminal_exit,
                    initial=p0, final=post, comparison=comparison, measurements=stats,
                    fixture_exit_not_substituted=True)


def reference_task(args, server, session, anchor, root, mode):
    root.mkdir(mode=0o700)
    stats = fresh_metrics()
    began = time.monotonic_ns()
    wrapper, count = counted_rex(args.rex, root)
    base = [str(wrapper), *server.base[1:]]
    def rpc(method, payload):
        result = invoke([*base, "api", "call", method, json.dumps(payload)], stats, server.env, 1)
        if result.returncode:
            raise ValueError("reference_rpc_failed:" + method)
        return json.loads(result.stdout)
    # Same native tiled creation method/geometry used by surfaces open. The
    # reference executes the fixture itself, not run-visible's helper.
    command = [sys.executable, str(FIXTURE), mode]
    made = rpc("session.new_split", dict(session_id=session, anchor_id=anchor, direction="horizontal", side="after", ratio=.7,
        focus=False, layout=dict(block=dict(flavor="com.superlogical.terminal.shell", label="reference " + mode,
        options=dict(command=command, shell="none", login=False, interactive=False, cwd=str(root), exit=dict(on_completion=False))))))
    block = made["block_ids"][0]
    try:
        end = time.monotonic() + 8
        last_exit = None
        while time.monotonic() < end:
            rpc("com.superlogical.terminal.program_status", dict(session_id=session, block_id=block, args={}))
            process = rpc("com.superlogical.terminal.process", dict(session_id=session, block_id=block, args={}))
            rpc("com.superlogical.terminal.format", dict(session_id=session, block_id=block, args=dict(format="text", max_bytes=4094)))
            last_exit = process.get("last_exit")
            if last_exit is not None:
                break
            time.sleep(.25)
        final = rpc("com.superlogical.terminal.format", dict(session_id=session, block_id=block, args=dict(format="text")))
        code = last_exit.get("exit_code") if last_exit else None
        save(root / "reference.json", dict(terminal_program_exit=last_exit, capture=final))
        stats["false_success"] = int(code == 0 and mode == "F1")
        stats["false_unknown"] = int(code is None)
        stats["wall_ms"] = (time.monotonic_ns() - began) / 1e6
        return dict(code=code, measurements=stats)
    finally:
        rpc("block.close", dict(session_id=session, block_id=block))
        stats["rex_client_launches"] = count.stat().st_size
        stats["wall_ms"] = (time.monotonic_ns() - began) / 1e6


def check_rows(args, server, session, anchor, evidence):
    rows = {}
    results = {}
    def row(name, condition, detail):
        rows[name] = {"pass": bool(condition), "detail": detail}
    for mode in args.modes:
        results[mode] = teerex_task(args, server, session, anchor, evidence / mode, mode,
                                    controller_signal=signal.SIGTERM if mode == "F3" else None)
    f1, f4, f5 = results.get("F1"), results.get("F4"), results.get("F5")
    row("B1", f1 and f1["code"] == 1 and f1["direct_child_exit"]["exit_code"] == 3 and f1["direct_child_exit"]["signal"] is None and not f1["receipt"]["success"] and ASSERTION in Path(f1["receipt"]["stderr"]["full_path"]).read_bytes(), "F1 real exit3 and full assertion stderr")
    row("B2", f4 and f4["code"] == 0 and f4["receipt"]["success"] and f4["direct_child_exit"]["exit_code"] == 0, "F4 real exit0 differs from F1")
    row("B3", f5 and f5["direct_child_exit"]["exit_code"] == 1 and (f5["reported_status"] or {}).get("outcome") == "status_report_matched", "F5 status claim and child exit stored separately")
    row("X2", retained_done(args, server, session, anchor, evidence), "retained F4 done does not rematch; fresh F5 done is not its exit1")
    row("B4", f1 and f1["direct_child_exit"]["exit_code"] == 3 and f1["fixture_exit_not_substituted"], "terminal_program_exit is separate; never substituted")
    exact = True
    for mode in ("F1", "F4"):
        if mode not in results:
            exact = False
            continue
        value = results[mode]["receipt"]
        for stream, known in zip(("stdout", "stderr"), expected(mode)):
            node = value[stream]
            retained = raw(node)
            exact &= known.startswith(retained) and node["complete"] == (len(retained) == len(known))
            exact &= node["full_complete"] is True and Path(node["full_path"]).read_bytes() == known
    row("B5", exact, "known raw prefixes/full files and completeness flags")
    # X1 is a separate same-pane test: unlike raw prefix equality, compare's
    # same-target/source contract cannot compare two different fixture panes.
    save(evidence / "F1-F4-side-by-side.json", {mode: dict(stdout_prefix=results[mode]["receipt"]["stdout"], stderr_prefix=results[mode]["receipt"]["stderr"], direct_child_exit=results[mode]["direct_child_exit"]) for mode in ("F1", "F4") if mode in results})
    x1 = hidden_tail(args, server, session, anchor, evidence)
    row("B6", x1, "X1 same-pane equal captured prefix; full text unknown")
    f2 = results.get("F2")
    quiet = quiet_watch(args, server, session, anchor, evidence)
    row("B7", f2 and f2["code"] == 124 and f2["direct_child_exit"]["signal"] == 9 and f2["receipt"]["cleanup"]["block_absence_verified"] and raw(f2["receipt"]["stdout"]).startswith(b"starting") and quiet, "F2 deadline/KILL/partial output/absence; quiet sentinel watch deadline")
    f3 = results.get("F3")
    interrupted = teerex_task(args, server, session, anchor, evidence / "F3-int", "F3", controller_signal=signal.SIGINT)
    row("B8", f3 and f3["code"] == 143 and interrupted["code"] == 130 and all(v["receipt"]["cleanup"]["block_absence_verified"] and v["direct_child_exit"]["signal"] == 15 for v in (f3, interrupted)), "INT130 and TERM143 override keep-open and close owned panes")
    row("B9", refusals(args, server, session, anchor, evidence), "cwd/executable/env/FIFO/mismatched baseline refused")
    row("B10", unknown_tests(args, server), "existing run-visible lost-ack and controller-SIGKILL tests executed")
    f6 = results.get("F6")
    survivor = False
    same_gone = False
    if f6:
        detached = int((evidence / "F6/detached.pid").read_text())
        same = int((evidence / "F6/same-group.pid").read_text())
        survivor, same_gone = alive(detached), not alive(same)
        if survivor:
            os.kill(detached, signal.SIGKILL)
        f6["detached_survivor"] = survivor
    row("B11", survivor and same_gone and f6["receipt"].get("all_descendants_verified_gone") is False, "setsid survivor observed and only its PID killed; same group stopped")
    default = teerex_task(args, server, session, anchor, evidence / "F1-default-close", "F1", keep=False)
    results["F1-default-close"] = default
    row("default_close", default["receipt"]["cleanup"]["block_absence_verified"], "default close independently verified")
    return rows, results


def retained_done(args, server, session, anchor, evidence):
    kept = teerex_task(args, server, session, anchor, evidence / "X2-F4", "F4", close_owned=False)
    block = kept["receipt"]["created"]["block_id"]
    try:
        observed, _ = execute(observations(args.teerex, server, session, block), server.env)
        baseline = evidence / "X2-retained.json"
        save(baseline, observed.stdout)
        waited, _ = execute([args.teerex, "watch", "--socket", server.socket, "--session", session, "--block", block,
            "--baseline", baseline, "--timeout-ms", "1000", "--status-state", "done"], server.env)
        fresh = teerex_task(args, server, session, anchor, evidence / "X2-F5", "F5")
        again, _ = execute(observations(args.teerex, server, session, block), server.env)
        save(evidence / "X2-retained-after.json", again.stdout)
        return (waited.returncode == 124 and json.loads(waited.stdout)["outcome"] == "deadline_exceeded"
            and json.loads(observed.stdout)["program_status"] == json.loads(again.stdout)["program_status"]
            and fresh["direct_child_exit"]["exit_code"] == 1 and fresh["reported_status"]["outcome"] == "status_report_matched")
    finally:
        server.rpc("block.close", dict(session_id=session, block_id=block))


def quiet_watch(args, server, session, anchor, evidence):
    observed, _ = execute(observations(args.teerex, server, session, anchor), server.env)
    path = evidence / "quiet.json"
    save(path, observed.stdout)
    result, _ = execute([args.teerex, "watch", "--socket", server.socket, "--session", session, "--block", anchor,
        "--baseline", path, "--timeout-ms", "300", "--status-state", "done", "--status-state", "error"], server.env)
    return result.returncode == 124 and json.loads(result.stdout)["outcome"] == "deadline_exceeded"


def hidden_tail(args, server, session, anchor, evidence):
    gate = evidence / "hidden-release"
    script = "import pathlib,sys,time;print('PREFIX '*1000,flush=True);print('tail-A',flush=True);p=pathlib.Path(sys.argv[1]);\nwhile not p.exists():time.sleep(.01)\nprint('tail-B',flush=True);time.sleep(30)"
    made = server.rpc("session.new_split", dict(session_id=session, anchor_id=anchor, direction="horizontal", side="after", ratio=.7, focus=False,
        layout=dict(block=dict(flavor="com.superlogical.terminal.shell", options=dict(shell="none", login=False, interactive=False,
            command=[sys.executable, "-c", script, str(gate)], exit=dict(on_completion=False))))))
    block = made["block_ids"][0]
    try:
        end = time.monotonic() + 5
        while "tail-A" not in server.terminal(session, block, "format", dict(format="text", max_bytes=65534)).get("content", ""):
            if time.monotonic() > end:
                return False
            time.sleep(.02)
        before, _ = execute(observations(args.teerex, server, session, block, 256), server.env)
        gate.touch()
        while "tail-B" not in server.terminal(session, block, "format", dict(format="text", max_bytes=65534)).get("content", ""):
            if time.monotonic() > end:
                return False
            time.sleep(.02)
        after, _ = execute(observations(args.teerex, server, session, block, 256), server.env)
        first, second = json.loads(before.stdout), json.loads(after.stdout)
        save(evidence / "X1-before.json", first)
        save(evidence / "X1-after.json", second)
        result, _ = execute([args.teerex, "compare", "--before", evidence / "X1-before.json", "--after", evidence / "X1-after.json"], server.env)
        comparison = json.loads(result.stdout)
        save(evidence / "X1-comparison.json", comparison)
        return result.returncode == 0 and not first["capture"]["complete"] and not second["capture"]["complete"] and comparison["capture"]["captured_text_changed"] is False and comparison["capture"]["full_text_changed"] is None
    finally:
        server.rpc("block.close", dict(session_id=session, block_id=block))


def refusals(args, server, session, anchor, evidence):
    root = evidence / "refusals"
    root.mkdir(mode=0o700)
    env = root / "env.json"
    save(env, dict(PATH=os.defpath))
    fifo = root / "stdin.fifo"
    os.mkfifo(fifo, 0o600)
    before = sorted(b["block_id"] for b in server.rpc("session.list_blocks", dict(session_id=session))["blocks"])
    base = [args.teerex, "--rex", args.rex, "run-visible", "--socket", str(server.socket), "--session", session,
            "--cwd", str(root), "--env-file", str(env), "--stdin-file", "/dev/null", "--app", "c31-refusal", "--title", "c31 refusal"]
    cases = [("--cwd", str(root / "absent"), ["/bin/true"]), (None, None, [str(root / "missing-executable")]),
             ("--stdin-file", str(fifo), ["/bin/true"])]
    valid = True
    for key, value, argv in cases:
        command = list(base)
        if key:
            command[command.index(key) + 1] = value
        output = root / ("case-" + str(len(list(root.glob('case-*')))))
        result, _ = execute([*command, "--output-dir", output, "--", *argv], server.env)
        packet = json.loads(result.stdout) if result.stdout else {}
        save(root / (output.name + "-refusal.json"), dict(exit=result.returncode, stdout=result.stdout.decode(errors="replace"), stderr=result.stderr.decode(errors="replace")))
        valid &= result.returncode == 1 and bool(packet.get("failure_reason") or result.stderr) and not (output / "started.json").exists()
    save(env, dict(PATH=os.defpath, REX_SESSION="forbidden"))
    result, _ = execute([*base, "--", "/bin/true"], server.env)
    save(root / "env-refusal.json", dict(exit=result.returncode, stdout=result.stdout.decode(errors="replace"), stderr=result.stderr.decode(errors="replace")))
    valid &= result.returncode == 2 and not result.stdout and bool(result.stderr)
    observed, _ = execute(observations(args.teerex, server, session, anchor), server.env)
    save(root / "baseline.json", observed.stdout)
    result, _ = execute([args.teerex, "watch", "--socket", server.socket, "--session", session,
        "--block", "block:00000000-0000-0000-0000-000000000001", "--baseline", root / "baseline.json", "--timeout-ms", "100"], server.env)
    valid &= result.returncode == 1
    after = sorted(b["block_id"] for b in server.rpc("session.list_blocks", dict(session_id=session))["blocks"])
    return valid and before == after


def unknown_tests(args, server):
    home = Path(tempfile.mkdtemp(prefix="c31-fault-home-", dir="/tmp"))
    environment = dict(server.env, HOME=str(home), TEEREX_BIN=args.teerex, REX_BIN=args.rex)
    try:
        result, _ = execute([sys.executable, str(ROOT / "items/run/test_visible.py"),
            "VisibleTest.test_lost_creation_and_close_acks_are_not_retried",
            "VisibleTest.test_controller_sigkill_retains_known_ids_and_helper_own_deadline", "-v"], environment, timeout=45)
        return result.returncode == 0
    finally:
        __import__("shutil").rmtree(home)


def summarize(report):
    for arm in report["measurements"].values():
        for measurement in arm.values():
            if not measurement.get("measured_processes") or not measurement.get("sampling_domain"):
                raise ValueError("measurement_domain_required")
    lines = ["# Safe-subset failing-CLI baseline", "", "Readiness and task completion are separate. Hidden full text remains unknown.", "", "| Row | Pass | Detail |", "| --- | --- | --- |"]
    lines += ["| %s | %s | %s |" % (name, str(row["pass"]).lower(), row["detail"]) for name, row in sorted(report["rows"].items())]
    lines += ["", "Ratios below name the measured quantity; lower is smaller. They are workload-specific, not productivity claims."]
    lines += ["", "Waited-exec CPU includes reaped descendants; RSS is the largest single waited child, not a sum. Wall uses monotonic task time. Rex execs are counted by an argument-free wrapper; wrapper overhead is included. Pane-side CPU is sampled from the started child at exit when readable. Server, GUI, neighbours and energy are excluded.", "", "| Arm | Fixture | n | Calls | Rex execs | stdout bytes | stderr bytes | output-dir bytes | CPU ms | max RSS KiB | Wall cold / median / p95 ms |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for arm, modes in report["measurements"].items():
        for mode, metric in modes.items():
            wall = metric["wall_ms"]
            lines.append("| %s | %s | %s | %g | %g | %g | %g | %g | %.3f | %.1f | %.3f / %.3f / %.3f |" % (arm, mode, metric["sampling_domain"]["n"], metric["calls"], metric["rex_client_launches"], metric["stdout_bytes"], metric["stderr_bytes"], metric["output_dir_bytes"], metric["cpu_ms"], metric["maxrss_kib"], wall["cold"], wall["warm_median"], wall["warm_p95"]))
    both = report["measurements"]
    if "teerex" in both and "reference" in both:
        for mode in sorted(set(both["teerex"]) & set(both["reference"])):
            first, second = both["teerex"][mode], both["reference"][mode]
            lines += ["", "- %s: n=%s; excluded=%s" % (mode, first["sampling_domain"]["n"], ", ".join(first["excluded"]))]
            for quantity in ("cold", "warm_median", "warm_p95"):
                denominator = second["wall_ms"][quantity]
                ratio = first["wall_ms"][quantity] / denominator if denominator else None
                lines.append("  - wall_ms.%s teerex/reference: %s" % (quantity, "unknown" if ratio is None else "%.4f" % ratio))
            for key in ("calls", "rex_client_launches", "stdout_bytes", "stderr_bytes", "cpu_ms", "maxrss_kib"):
                ratio = first[key] / second[key] if second[key] else None
                lines.append("  - %s teerex/reference: %s" % (key, "unknown (zero reference)" if ratio is None else "%.4f" % ratio))
    lines += ["", "No improvement claim is made unless every B row passed. Pane-side CPU is null when exit-time process evidence was unreadable."]
    return "\n".join(lines) + "\n"


def measurement_domain(n, warmups):
    return dict(measured_processes=[dict(role="teerex_cli_or_reference_rex_cli", identified_by="waited child of runner", counted_in=["wall_ms", "cpu_ms", "maxrss_kib"]),
        dict(role="rex_cli_children", identified_by="descendants reaped by waited child", counted_in=["cpu_ms", "maxrss_kib"]),
        dict(role="pane_side", identified_by="started.json pid", counted_in=["pane_side_cpu_ms"])],
        sampling_domain=dict(clock="time.monotonic_ns around each waited exec", cpu="wait4 child-local ru_utime+ru_stime; includes waited descendants",
            rss="wait4 ru_maxrss: largest single waited child, not a sum", pane_side="/proc/<pid>/stat utime+stime (Linux), ps -o cputime (macOS); null if unreadable at exit", n=n, warmups=warmups))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teerex", required=True)
    parser.add_argument("--rex", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--arms", default="teerex,reference")
    parser.add_argument("--modes", default=",".join(MODES))
    parser.add_argument("--warm-runs", type=int, default=40)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--agent-arm", action="store_true")
    parser.add_argument("--profiles", type=Path)
    parser.add_argument("--agent-profiles", default="codex,claude")
    parser.add_argument("--agent-runs", type=int, default=5)
    args = parser.parse_args(argv)
    if not args.out.is_absolute() or args.out.exists() or not 1 <= args.warm_runs <= 100 or not 0 <= args.warmups <= 10:
        parser.error("new absolute output and bounded repetitions required")
    args.arms = args.arms.split(",")
    args.modes = args.modes.split(",")
    if set(args.arms) - {"teerex", "reference"} or set(args.modes) - set(MODES):
        parser.error("unknown arm or mode")
    if args.agent_arm:
        from agent_arm import run
        return run(args)
    args.out.mkdir(mode=0o700)
    evidence = args.out / "evidence"
    evidence.mkdir(mode=0o700)
    report = dict(schema_version=1, kind="safe_subset_baseline", host=dict(os=platform.system(), arch=platform.machine()),
                  binaries=dict(teerex=sha(args.teerex), rex=sha(args.rex)), rows={}, results={}, measurements={})
    try:
        with tempfile.TemporaryDirectory(prefix="c31-", dir="/tmp") as directory:
            server = Server(args.rex, Path(directory))
            sentinel = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(900)"])
            try:
                session, anchor = server.fixture()
                report["rex"] = server.version
                server.command("api", "list")
                execute(observations(args.teerex, server, session, anchor), server.env)
                before = controls(server, session, anchor, sentinel)
                save(evidence / "controls-before.json", before)
                rows, results = check_rows(args, server, session, anchor, evidence)
                after = controls(server, session, anchor, sentinel)
                save(evidence / "controls-after.json", after)
                rows["B12"] = {"pass": before == after, "detail": "N1_N6 exact controls; delta=" + ",".join(k for k in before if before[k] != after[k])}
                report["rows"], report["results"] = rows, results
                for arm in args.arms:
                    report["measurements"][arm] = {}
                # Cold execution first, then excluded warmups, then alternating
                # arms for every measured repetition, all on the same host/build.
                for mode in ("F1", "F4"):
                    samples = {arm: [] for arm in args.arms}
                    cold = {}
                    for iteration in range(-1 - args.warmups, args.warm_runs):
                        order = args.arms if iteration % 2 == 0 else list(reversed(args.arms))
                        for arm in order:
                            root = evidence / ("measure-%s-%s-%s" % (mode, arm, iteration))
                            if iteration == -1 - args.warmups:
                                with tempfile.TemporaryDirectory(prefix="c31-cold-", dir="/tmp") as cold_directory:
                                    cold_server = Server(args.rex, Path(cold_directory))
                                    try:
                                        cold_session, cold_anchor = cold_server.fixture()
                                        task = teerex_task if arm == "teerex" else reference_task
                                        result = task(args, cold_server, cold_session, cold_anchor, root, mode)
                                    finally:
                                        cold_server.close()
                            else:
                                result = teerex_task(args, server, session, anchor, root, mode) if arm == "teerex" else reference_task(args, server, session, anchor, root, mode)
                            metric = result["measurements"]
                            if iteration == -1 - args.warmups:
                                cold[arm] = metric
                            elif iteration >= 0:
                                samples[arm].append(metric)
                    for arm, values in samples.items():
                        combined = {key: statistics.median(v[key] for v in values) if values[0][key] is not None else None for key in values[0] if key not in ("excluded",)}
                        timings = sorted(v["wall_ms"] for v in values)
                        combined["wall_ms"] = dict(cold=cold[arm]["wall_ms"], warm_median=statistics.median(timings), warm_p95=timings[max(0, int(len(timings) * .95 + .999) - 1)])
                        combined["excluded"] = EXCLUDED
                        combined.update(measurement_domain(args.warm_runs, args.warmups))
                        combined["false_success"] = sum(v["false_success"] for v in values)
                        combined["false_unknown"] = sum(v["false_unknown"] for v in values)
                        report["measurements"][arm][mode] = combined
            finally:
                sentinel.terminate()
                sentinel.wait(timeout=5)
                server.close()
        save(args.out / "report.json", report)
        summary = summarize(report)
        save(args.out / "summary.md", summary.encode())
        print(json.dumps(dict(kind="baseline_result", passed=all(row["pass"] for row in report["rows"].values()), rows=report["rows"])))
        return 0 if all(row["pass"] for row in report["rows"].values()) else 1
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
        report["operational_error"] = type(error).__name__ + ":" + str(error).splitlines()[0][:160]
        save(args.out / "report.json", report)
        print(json.dumps(dict(kind="baseline_error", reason=report["operational_error"])), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
