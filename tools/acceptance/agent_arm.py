"""Visible subscription-agent measurements; only owned panes are ever closed."""
import copy
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

from common import ROOT, Server, execute, save, sha


def run(args):
    if args.profiles is None or not args.profiles.is_absolute() or not 1 <= args.agent_runs <= 5:
        raise ValueError("absolute_profiles_and_agent_runs_1_to_5_required")
    original = json.loads(args.profiles.read_text())
    defaults = original["defaults"]
    socket, session = defaults["socket"], defaults["session"]
    profiles = args.agent_profiles.split(",")
    if set(profiles) - {"codex", "claude"} or any(not original["profiles"][p].get("hook_events") for p in profiles):
        raise ValueError("hook_enabled_codex_claude_profiles_required")
    args.out.mkdir(mode=0o700)
    report = dict(schema_version=1, kind="agent_baseline", task="synthetic_F1", runs=[],
        binaries=dict(teerex=sha(args.teerex), rex=sha(args.rex)),
        deviation="approved_owned_inert_notification_sink_beside_visible_agent_tab;task_panes_private_server",
        measured_processes=[dict(role="actual_subscription_agent", identified_by="managed launch registry and Stop hook", counted_in=["wall_s", "tool_round_trips", "interruptions", "misdirected_inputs"])],
        sampling_domain=dict(n=args.agent_runs, profiles=profiles, conditions=["with-teerex", "plain-rex"], warmups=0,
            excluded=["rex_server", "gui", "neighbour_panes", "whole_machine_energy"], interpretation="fixed synthetic task; not general productivity"))
    base = [args.teerex, "--rex", args.rex]
    def command(*argv, timeout=30):
        result, _ = execute([*base, *argv], timeout=timeout)
        if result.returncode:
            raise ValueError("agent_control_refused")
        return json.loads(result.stdout)
    def close(block):
        result = command("surfaces", "close", "--socket", socket, "--session", session, "--pane", block)
        return result.get("outcome") == "closed_and_absent" and result.get("block_absence_verified") is True
    sink = None
    try:
        sink_receipt = command("surfaces", "open", "--socket", socket, "--session", session, "--layout", "tab", "--label", "c32-inert-notification-sink", "--",
            sys.executable, "-c", "import sys,time;print('C32 inert notification sink; no commands execute',flush=True)\nwhile True:\n line=sys.stdin.readline()\n if not line:time.sleep(.1)")
        sink = sink_receipt["created"]["block_id"]
        for profile in profiles:
            for n in range(args.agent_runs):
                for condition in ("with-teerex", "plain-rex"):
                    work = Path(tempfile.mkdtemp(prefix="c32-", dir=ROOT.parent))
                    evidence = args.out / ("%s-%s-%s" % (profile, n, condition))
                    evidence.mkdir(mode=0o700)
                    registry = work / "registry"
                    registry.mkdir(mode=0o700)
                    shim = work / "bin"
                    shim.mkdir(mode=0o700)
                    config = dict(condition=condition, teerex=args.teerex, rex=args.rex, rex_shim=str(shim / "rex"),
                                  log=str(work / "tools.jsonl"), owned=str(work / "owned.jsonl"))
                    config_path = work / "shim.json"
                    save(config_path, config)
                    for tool in ("teerex", "rex", "agent-send"):
                        source = "#!" + sys.executable + "\nimport os,sys\nos.execv(" + repr(sys.executable) + ",[" + repr(sys.executable) + "," + repr(str(ROOT / "tools/acceptance/agent_shim.py")) + "," + repr(str(config_path)) + "," + repr(tool) + "]+sys.argv[1:])\n"
                        save(shim / tool, source.encode(), 0o700)
                    with tempfile.TemporaryDirectory(prefix="c32-task-", dir="/tmp") as directory:
                        private = Server(args.rex, Path(directory))
                        agent = None
                        try:
                            task_session, anchor = private.fixture("C32_PRIVATE_TASK_ANCHOR")
                            shutil.copyfile(ROOT / "tools/acceptance/fail_fixture.py", work / "fail_fixture.py")
                            os.chmod(work / "fail_fixture.py", 0o600)
                            brief = ("Run `python3 fail_fixture.py F1` visibly, find why it fails, and report the failing assertion and the exit code. Do not edit files.\n"
                                "This is an explicitly authorized acceptance measurement. Use only PATH teerex/rex tools for the task. "
                                "Task panes must be created only on the private socket " + str(private.socket) + " in session " + task_session + " anchored to " + anchor + ". "
                                "Use explicit cwd " + str(work) + ". The agent tab is on a different server; never send task input there. "
                                "Do not use tools to type messages or reports into other panes. Do not spawn agents. End with the assertion and numeric exit code in your final response; the managed Stop hook collects it. "
                                "Available condition: " + condition + ". PATH teerex is deliberately unavailable in plain-rex; use plain Rex native terminal creation/capture/process calls there. "
                                "The task fixture is synthetic and exits by itself. Do not change files, credentials, services, configuration or personal panes.\n")
                            save(work / "task.md", brief.encode())
                            selected = copy.deepcopy(original["profiles"][profile])
                            if selected.get("execution") or selected.get("delivery"):
                                raise ValueError("agent_measurement_requires_local_profile")
                            launcher = work / "harness"
                            argv = selected["argv"]
                            source = "#!" + sys.executable + "\nimport os,sys\ne=dict(os.environ,PATH=" + repr(str(shim) + os.pathsep + os.environ.get("PATH", os.defpath)) + ")\ne.pop('TEEREX_INTERNAL_REX',None)\ne.pop('TEEREX_REX',None)\nos.execve(" + repr(argv[0]) + "," + repr(argv) + "+sys.argv[1:],e)\n"
                            save(launcher, source.encode(), 0o700)
                            selected["argv"] = [str(launcher)]
                            cfg = dict(schema_version=1, profiles={profile: selected}, defaults=dict(defaults, registry=str(registry), cwd=str(ROOT.parent),
                                starter_session=session, starter_block=sink, report_to_session=session, report_to_block=sink, store=None, owner="c32-acceptance", purpose="bounded synthetic agent measurement"))
                            save(work / "profiles.json", cfg)
                            began = time.monotonic()
                            launched = command("agents", "launch", "--config", str(work / "profiles.json"), "--profile", profile,
                                "--name", "c32-%s-%s-%s" % (profile, n, condition), "--brief-file", str(work / "task.md"), "--ack-timeout-ms", "60000", timeout=95)
                            agent = launched["target"]["block_id"]
                            launch_id = launched["launch_id"]
                            correct = False
                            stopped = False
                            while time.monotonic() - began < 900:
                                command("agents", "inspect", "--registry", str(registry), "--launch-id", launch_id)
                                state = json.loads((registry / ("agents-" + launch_id + ".json")).read_text())
                                hook = state.get("last_hook", {})
                                # The initial protocol-only ACK also produces a Stop.
                                if hook.get("kind") == "Stop" and hook.get("at", 0) >= state.get("brief_attempted_at", state["created_at"]):
                                    text = hook.get("text", "")
                                    correct = "expected 4 got 5" in text and "3" in text
                                    if correct or time.monotonic() - began > 30 and "protocol" not in text.lower() and "acknowledg" not in text.lower():
                                        stopped = True
                                        break
                                time.sleep(1)
                            log = work / "tools.jsonl"
                            entries = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
                            owned_path = work / "owned.jsonl"
                            owned = set(json.loads(line) for line in owned_path.read_text().splitlines()) if owned_path.exists() else set()
                            misdirected = sum(1 for entry in entries if "send" in entry["verb"] and entry.get("target_block") not in owned)
                            result = dict(profile=profile, condition=condition, tool_round_trips=len(entries), interruptions=sum(bool(e.get("interruption")) for e in entries),
                                misdirected_inputs=misdirected, correct_report=correct, stop_observed=stopped, wall_s=time.monotonic() - began,
                                agent_pane_closed=False)
                            report["runs"].append(result)
                        finally:
                            if agent is None:
                                for state_path in registry.glob("agents-*.json"):
                                    try:
                                        saved = json.loads(state_path.read_text())
                                        agent = saved.get("target", {}).get("block_id")
                                    except (OSError, ValueError):
                                        pass
                            if agent:
                                capture, _ = execute([*base, "observe", "--socket", socket, "--session", session, "--block", agent, "--max-bytes", "65535"])
                                save(work / "agent-final-private.json", capture.stdout)
                                closed = close(agent)
                                if report["runs"]:
                                    report["runs"][-1]["agent_pane_closed"] = closed
                            private.close()
                            # Preserve private evidence, then remove the owned scratch cwd.
                            for name in ("registry", "tools.jsonl", "owned.jsonl", "agent-final-private.json"):
                                source = work / name
                                if source.exists():
                                    shutil.move(str(source), str(evidence / name))
                            shutil.rmtree(work)
    finally:
        report["notification_sink_closed"] = close(sink) if sink else False
        save(args.out / "report.json", report)
        lines = ["# Actual-agent synthetic F1 baseline", "", "No model output is published. Task panes used private servers. The approved visible inert notification sink was closed: " + str(report["notification_sink_closed"]) + ".", "", "| Condition | n | Tool calls median | Interruptions median | Misdirected inputs | Correct reports |", "| --- | --- | --- | --- | --- | --- |"]
        for condition in ("with-teerex", "plain-rex"):
            rows = [row for row in report["runs"] if row["condition"] == condition]
            if rows:
                lines.append("| %s | %s | %s | %s | %s | %s |" % (condition, len(rows), statistics.median(r["tool_round_trips"] for r in rows), statistics.median(r["interruptions"] for r in rows), sum(r["misdirected_inputs"] for r in rows), sum(r["correct_report"] for r in rows)))
        save(args.out / "summary.md", ("\n".join(lines) + "\n").encode())
    passed = len(report["runs"]) == len(profiles) * args.agent_runs * 2 and report["notification_sink_closed"] and all(r["correct_report"] and r["agent_pane_closed"] for r in report["runs"])
    print(json.dumps(dict(kind="agent_baseline_result", passed=passed, runs=len(report["runs"]))))
    return 0 if passed else 1
