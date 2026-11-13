"""Bounded, read-only screen interpretation. It reports evidence, never completion."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
PROMPT = re.compile(r"^[│┃|]?\s*([❯›>])(?:\s|$)")
SPINNER = r"[✻✽✶✳✢✷✸✹✺✼⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏•●*]"


def plain(value):
    value = re.sub(r"\x1b\[(\d*)C", lambda m: " " * min(65536, max(1, int(m[1] or 1))), value)
    value = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", value)
    return CSI.sub("", value).replace("\r", "").strip()


def classify(packet):
    capture, process = packet["capture"], packet["process"]
    complete = capture.get("id") is None and capture.get("eof", True)
    lines = [(n + 1, plain(line)) for n, line in enumerate(capture["content"].split("\n")) if plain(line)]
    recent = lines[-15:]
    evidence = []

    def add(source, text, line=None):
        entry = dict(source=source, line=line, text=text[:240])
        if entry not in evidence and len(evidence) < 10:
            evidence.append(entry)

    active = process.get("foreground") or process.get("child")
    name = Path(active.get("name", "")).name.lower() if active else ""
    process_harness = next((h for h in ("claude", "codex", "pi") if name == h or name.startswith(h + "-")), None)
    if name in ("bash", "zsh", "fish", "sh", "dash"):
        process_harness = "shell"
    if process_harness:
        add("process", "active process: " + name)
    screen_harness = set()
    for number, line in recent:
        if re.search(r"\bClaude Code\b", line, re.I) or re.match(r"^[│┃|]?\s*❯(?:\s|$)", line):
            screen_harness.add("claude")
        if re.match(r"^[│┃|]?\s*›(?:\s|$)", line) or re.search(r"\b(?:OpenAI Codex|Ask Codex to do anything)\b", line):
            screen_harness.add("codex")
        if re.match(r"^pi v?\d+\.\d+", line, re.I):
            screen_harness.add("pi")
    # Pi extension inputs can use ❯, so process identity resolves that shared marker.
    if process_harness == "pi":
        screen_harness.discard("claude")
    conflict = len(screen_harness) > 1 or bool(process_harness and screen_harness and process_harness not in screen_harness)
    harness = "unknown" if conflict else process_harness or next(iter(screen_harness), "unknown")
    result = dict(harness=harness, state="unknown", draft_present=None, evidence_lines=evidence,
                  state_basis="none", reason="insufficient_evidence", completion="not_inferred",
                  osc7501=packet["status"], capture_complete=bool(complete), freshness="unknown")
    if not process.get("child") and not process.get("foreground") and process.get("last_exit") is not None:
        result.update(state="exited", state_basis="process_report", reason="no_child_or_foreground_and_recorded_exit")
        add("process", "no child/foreground; last_exit=" + json.dumps(process["last_exit"]))
        return result
    if not complete or conflict:
        result["reason"] = "partial_capture" if not complete else "conflicting_harness_evidence"
        return result
    prompts = [(number, line) for number, line in recent if PROMPT.match(line)]
    last_prompt = prompts[-1][0] if prompts else None
    # Only the nearby UI suffix can justify screen state, never arbitrary scrollback.
    ui = [(n, line) for n, line in recent if last_prompt is None or n >= last_prompt - 5]
    if harness != "unknown":
        heading = next(((n, line) for n, line in ui if re.search(
            r"^(?:[│┃|]\s*)?(?:Do you (?:want|trust)|Would you like|Allow .+\?|Trust this|Project trust|Select (?:an? |one |a )?(?:option|model)|Choose (?:an? |one |a )?option)", line, re.I)), None)
        choice = next(((n, line) for n, line in ui if re.match(r"^(?:[❯›→]\s*)?(?:\d+[.)]\s+|(?:Yes|No|Allow|Deny|Trust)\b)", line, re.I)), None)
        keys = next(((n, line) for n, line in ui if re.search(r"(?:enter.*(?:confirm|select|save)|↑.*↓.*(?:navigate|select)|esc.*cancel)", line, re.I)), None)
        if heading and choice and keys:
            result.update(state="awaiting_choice", state_basis="screen_heuristic", reason="menu_heading_choices_and_keys")
            for n, line in (heading, choice, keys):
                add("screen", line, n)
        else:
            question = next(((n, line) for n, line in ui if re.match(r"^(?:Type (?:your |an? )?(?:answer|response)|Enter (?:your |an? )?(?:answer|response|API key)|Your answer:)" , line, re.I)), None)
            if question and keys:
                result.update(state="awaiting_text", state_basis="screen_heuristic", reason="text_request_and_submission_keys")
                add("screen", question[1], question[0]); add("screen", keys[1], keys[0])
            else:
                working = next(((n, line) for n, line in ui if (
                    re.match(r"^(?:" + SPINNER + r"\s*)?Working\s*\(.*esc.*interrupt", line, re.I)
                    or (re.match(r"^" + SPINNER, line) and re.search(r"\besc.*interrupt\b", line, re.I))
                    or (harness == "claude" and re.match(r"^[·✻✽✶✳✢✷✸✹✺✼]\s+[^\n]{1,80}…\s*\(\d+(?:h|m|s)\b.*\btokens\)", line))
                    or (harness == "pi" and re.match(r"^──\s*" + SPINNER + r"\s*(?:Working|Retrying|Compacting|Auto-compacting)\b", line))
                )), None)
                error = next(((n, line) for n, line in ui if re.match(r"^(?:■\s*|API Error:|Authentication error:|Error:)", line)), None)
                if working:
                    result.update(state="working", state_basis="screen_heuristic", reason="active_interrupt_or_pi_working_indicator")
                    add("screen", working[1], working[0])
                elif error and (not last_prompt or error[0] >= last_prompt - 2):
                    result.update(state="error", state_basis="screen_heuristic", reason="nearby_harness_error_line")
                    add("screen", error[1], error[0])
                elif prompts:
                    result.update(state="idle_prompt", state_basis="screen_heuristic", reason="recognized_prompt_without_busy_or_menu_evidence")
                elif harness == "pi" and packet.get("editor_draft_present") is not None:
                    result.update(state="idle_prompt", state_basis="screen_heuristic", reason="pi_process_and_bounded_editor")
                    add("screen", "Pi horizontal editor borders (contents omitted)")
                elif harness == "shell" and recent and re.search(r"[$#%]$", recent[-1][1]):
                    result.update(state="idle_prompt", state_basis="screen_heuristic", reason="shell_process_and_prompt_suffix")
                    add("screen", "shell prompt suffix (contents omitted)", recent[-1][0])
    if result["state"] in ("working", "idle_prompt") and harness in ("claude", "codex", "pi"):
        if prompts:
            result["draft_present"] = packet.get("draft_present")
            add("screen", PROMPT.match(prompts[-1][1])[1] + " [draft present]" if result["draft_present"] else PROMPT.match(prompts[-1][1])[1] + " [empty/suggestion prompt]", prompts[-1][0])
        elif harness == "pi":
            result["draft_present"] = packet.get("editor_draft_present")
    if result["state"] == "unknown":
        roots = [r for r in packet["status"].get("records", []) if not r.get("id")]
        if len(roots) == 1:
            report = roots[0]
            state = {"working": "working", "error": "error"}.get(report.get("state"))
            if report.get("state") == "blocked":
                state = {"permission": "awaiting_choice", "question": "awaiting_text"}.get(report.get("kind"))
            if state:
                result.update(state=state, state_basis="osc7501_report", reason="root_program_report_freshness_unknown")
                add("osc7501", "state=" + report["state"] + (" kind=" + report["kind"] if report.get("kind") else ""))
    return result


def main():
    draft_source, collect_source = sys.argv[1:3]
    parser = argparse.ArgumentParser(prog="teerex observe --state", description=__doc__)
    parser.add_argument("--state", action="count", required=True)
    for name in ("socket", "session", "block"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--max-bytes", type=int, default=65536)
    parser.add_argument("--timeout-ms", type=int, default=5000)
    args = parser.parse_args(sys.argv[3:])
    if args.state != 1:
        parser.error("--state must occur once")
    for value, prefix in ((args.session, "session"), (args.block, "block")):
        if not re.fullmatch(prefix + r":[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value):
            parser.error("canonical lowercase full target IDs required")
    if not os.path.isabs(args.socket) or not 256 <= args.max_bytes <= 65536 or not 100 <= args.timeout_ms <= 60000:
        parser.error("absolute socket, max-bytes256..65536 and timeout-ms100..60000 required")
    request = json.dumps(dict(session_id=args.session, block_id=args.block, max_bytes=args.max_bytes))
    command = [os.environ.get("TEEREX_INTERNAL_REX", "rex"), "--autostart=false", "--server", "unix://" + args.socket,
               "--timeout", "3s", "--color", "never", "do", "--session", args.session, "--block", args.block,
               "-e", draft_source + "\n" + collect_source, "--args", request]
    started = int(time.time() * 1000)
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=errors)
        try:
            child.wait(timeout=args.timeout_ms / 1000)
        except subprocess.TimeoutExpired:
            child.kill(); child.wait()
            print(json.dumps(dict(kind="agent_state", state="unknown", reason="collection_deadline", completion="not_inferred")))
            return 124
        output.seek(0); raw = output.read(262145)
        if child.returncode or len(raw) > 262144:
            print(json.dumps(dict(kind="agent_state", state="unknown", reason="collection_failed", completion="not_inferred")))
            return 1
    packet = json.loads(raw)
    result = classify(packet)
    result.update(schema_version=1, kind="agent_state", target=dict(server="unix://" + args.socket, session_id=args.session, block_id=args.block),
                  source=packet["version"], observation_started_at_unix_ms=started, observed_at_unix_ms=int(time.time() * 1000), atomic_snapshot=False, read_only=True)
    if os.environ.get("TEEREX_SOCKET_SOURCE"):
        result["socket_source"] = os.environ["TEEREX_SOCKET_SOURCE"]
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps(dict(kind="agent_state", state="unknown", reason="invalid_or_unavailable_evidence", completion="not_inferred")))
        raise SystemExit(1)
