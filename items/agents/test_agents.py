"""Public lifecycle checks against disposable Rex; no personal endpoints or real paid agents.

TEEREX_BIN must dispatch agents/spawn/jobs/send. REX_BIN selects the fixture's exact executable.
"""
import errno
import fcntl
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import threading
import unittest

BIN = str(Path(os.environ.get("TEEREX_BIN", "zig-out/bin/teerex")).resolve())
REX = os.environ.get("REX_BIN")

CONTRACT_REFUSAL = 'Turn not ended: declare one — finished: every step checked off, To-do empty (teerex scratch done) | blocked: teerex scratch flag "what is stuck; what you tried; what you need" | waiting: teerex scratch now STEP --waiting "on what" --check 10m'
CONTRACT_PROTOCOL = 'Contract: write your steps first; every turn after the brief ends declared — finished (every step checked off, To-do empty), blocked (teerex scratch flag "what is stuck; what you tried; what you need"; never check off steps you could not do), or waiting (teerex scratch now STEP --waiting "on what" --check 10m). teerex tells your starter each step and each declaration.'

# A synthetic interactive agent consumes exact PTY input; only it executes the explicit ACK command.
# No screen-scraped token, transport receipt or creation receipt stands in for the ACK.
FIXTURE = r'''
import json, os, shlex, signal, subprocess, sys, termios, time, tty
from pathlib import Path
out, behavior = Path(sys.argv[1]), sys.argv[2]
tty.setraw(0, termios.TCSANOW)
signal.signal(signal.SIGUSR1, lambda *_: os.write(1,b'\x1b]11;?\x1b\\'))
os.write(1,b'\x1b[?2004h\x1b]7501;state=working:app=synthetic\x07')
args=sys.argv[3:]
protocol=args[-1] if args and "Messaging protocol (not a task brief):" in args[-1] else None
with out.open("a") as f:
    f.write(json.dumps({"event":"started", "pid":os.getpid(), "argv":args[:-1] if protocol else args,
                        "cwd":os.getcwd(), "stdin_tty":os.isatty(0),
                        "registry_present":Path(os.environ.get("AGENT_REGISTRY","/nonexistent")).exists(),
                        "env":{k:v for k,v in os.environ.items() if k.startswith(("AGENT_", "LC_"))}}) + "\n"); f.flush()
if protocol:
    with out.open("a") as f: f.write(json.dumps({"event":"protocol_argument","payload":protocol})+"\n")
    if behavior != "noack":
        line=protocol.split("Acknowledge this protocol now by running:\n",1)[1].split("\n",1)[0]
        if behavior == "remote-exit7":
            for key,value in (("--token","0"*64),("--block",os.environ['AGENT_STARTER'].split()[1])):
                wrong=shlex.split(line); wrong[wrong.index(key)+1]=value
                result=subprocess.run(wrong,capture_output=True,text=True)
                with out.open('a') as f: f.write(json.dumps({"event":"wrong-ack","code":result.returncode,"stdout":result.stdout})+'\n')
        if behavior == "lateack": time.sleep(1)
        result=subprocess.run(shlex.split(line),capture_output=True,text=True)
        with out.open("a") as f: f.write(json.dumps({"event":"ack","code":result.returncode,"stdout":result.stdout})+"\n")
        if behavior == "channel":
            client=shlex.split(line)
            client=client[:client.index("--request-id")]
            cmd=client+["--request-id","a"*32,"--operation","send","--to","report-to","--message-file","-"]
            for unused in range(2):
                result=subprocess.run(cmd,input="fenced β: quotes '\"\nlast line\n\n",capture_output=True,text=True)
                with out.open("a") as f: f.write(json.dumps({"event":"channel-result","code":result.returncode,"stdout":result.stdout})+"\n")
            hook=json.loads(args[args.index('--settings')+1])['hooks']['Stop'][0]['hooks'][0]['command']
            # Second stale Stop is explicitly allowed after the single blocking reminder.
            subprocess.run(hook,shell=True,input=json.dumps({"hook_event_name":"Stop","last_assistant_message":"precheck"}),capture_output=True,text=True)
            result=subprocess.run(hook,shell=True,
                                  input=json.dumps({"hook_event_name":"Stop","last_assistant_message":"fenced turn complete β"}),
                                  capture_output=True,text=True)
            with out.open("a") as f: f.write(json.dumps({"event":"channel-stop","code":result.returncode,"stdout":result.stdout})+"\n")
        if behavior == "remote-exit7":
            settings=json.loads(args[args.index("--settings")+1])
            transcript=Path('/work/transcript.jsonl')
            transcript.write_text(json.dumps({"type":"assistant","message":{"content":[{"type":"text","text":"remote transcript β '\""}]}})+'\n')
            for kind in ('Stop','StopFailure'):
                event={"hook_event_name":kind,"transcript_path":str(transcript),"error":"remote failure β"}
                command=settings['hooks'][kind][0]['hooks'][0]['command']
                result=subprocess.run(command,shell=True,input=json.dumps(event),capture_output=True,text=True)
                with out.open('a') as f: f.write(json.dumps({"event":"remote-hook","kind":kind,"code":result.returncode,"stdout":result.stdout})+'\n')
            report_line=protocol.split('Supply report bytes on stdin then EOF using:\n',1)[1].split('\n',1)[0]
            result=subprocess.run(shlex.split(report_line),input='remote direct reply β\n\n',capture_output=True,text=True)
            with out.open('a') as f: f.write(json.dumps({"event":"remote-reply","code":result.returncode,"stdout":result.stdout})+'\n')
def harness_hooks():
    if behavior == "codex-hook":
        pad=Path(os.environ['AGENT_SCRATCHPAD'])
        raw=pad.read_text().replace('## Now\n', '## Now\n- [ ] active work\n')
        import datetime, re
        pad.write_text(re.sub(r'^Updated:.*$', 'Updated: '+datetime.datetime.now(datetime.timezone.utc).isoformat(), raw, flags=re.M))
        callback=json.loads(next(a[len('notify='):] for a in args if a.startswith('notify=')))
        result=subprocess.run(callback+[json.dumps({"type":"agent-turn-complete","last-assistant-message":"Codex settled β"})],capture_output=True,text=True)
        with out.open('a') as f: f.write(json.dumps({"event":"codex-hook","code":result.returncode,"stdout":result.stdout})+'\n')
    if behavior == "pi-hook":
        import base64
        extension=Path(args[args.index('--extension')+1])
        script="""
const handlers={};
const mod=await import('data:text/javascript;base64,'+process.argv[1]);
mod.default({on:(name,handler)=>{handlers[name]=handler;}});
const ctx={sessionManager:{getBranch:()=>[{type:'message',message:{role:'assistant',content:[{type:'text',text:'Pi settled β'}],errorMessage:'Pi synthetic failure'}}]}};
await handlers.before_agent_start({prompt:'check scratchpad'});
const first=await handlers.agent_before_settle({outcome:'completed',entries:[{type:'custom',customType:'existing',data:{}}]});
if (first?.continue !== true || first?.entries?.[1]?.content !== 'update your scratchpad (Now/To-do/Done) before ending the turn') throw new Error('scratchpad did not block settlement');
if (first.entries[0]?.customType !== 'existing') throw new Error('scratchpad replaced another extension entry');
const second=await handlers.agent_before_settle({outcome:'completed'});
if (second?.continue) throw new Error('scratchpad blocked more than once');
await handlers.agent_settled({aborted:false},ctx);
await handlers.agent_before_settle({outcome:'error'});
await handlers.agent_settled({aborted:false},ctx);
"""
        result=subprocess.run(['node','--input-type=module','-e',script,base64.b64encode(extension.read_bytes()).decode()],capture_output=True,text=True)
        with out.open('a') as f: f.write(json.dumps({"event":"pi-hook","code":result.returncode,"stderr":result.stderr})+'\n')
if behavior == "human-exit":
    sys.exit(0)
buf=b""
while True:
    part=os.read(0,65536)
    if not part: break
    buf+=part
    if b'\x1b]11;' in buf and (b'\x1b\\' in buf or b'\x07' in buf):
        start=buf.index(b'\x1b]11;')
        end=buf.index(b'\x07',start)+1 if b'\x07' in buf[start:] else buf.index(b'\x1b\\',start)+2
        with out.open('a') as f: f.write(json.dumps({'event':'background','value':buf[start:end].decode()})+'\n')
        buf=buf[:start]+buf[end:]
    while b"\x1b[201~\r" in buf:
        raw,buf=buf.split(b"\x1b[201~\r",1)
        payload=raw.removeprefix(b"\x1b[200~").decode()
        with out.open("a") as f: f.write(json.dumps({"event":"input","payload":payload})+"\n")
        if "RUN SYNTHETIC HOOKS" in payload and behavior in ("codex-hook", "pi-hook"):
            harness_hooks()
        if "TASK β asymmetric" in payload and behavior == "scratch-three":
            binary=shlex.split(protocol.split("Acknowledge this protocol now by running:\n",1)[1].split("\n",1)[0])[0]
            for task in ("Read contracts", "Build feature", "Run gates"):
                subprocess.run([binary,"scratch","now",task],check=True)
                subprocess.run([binary,"scratch","done"],check=True)
            with out.open("a") as f: f.write(json.dumps({"event":"scratch-complete"})+"\n")
        if "TEST EXIT " in payload:
            sys.exit(int(payload[-1]))
        if "TASK β asymmetric" in payload and behavior in ("exit7", "remote-exit7"):
            sys.exit(7)
'''


def wait_for(fn, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(.03)
    raise AssertionError("fixture condition not met")


def events(path):
    return [json.loads(v) for v in path.read_text().splitlines()] if path.exists() else []


class HelpRangesTest(unittest.TestCase):
    def test_agent_numeric_ranges_keep_help_and_errors_compact(self):
        with tempfile.TemporaryDirectory(prefix="tagents-help-") as temporary:
            env = dict(os.environ, TEEREX_CALL_LOG_DIR=str(Path(temporary) / "calls"))
            for operation, flag, lower, upper in [
                ("launch", "--launch-wait-ms", 0, 60000),
                ("launch", "--ack-timeout-ms", 100, 60000),
                ("human", "--launch-wait-ms", 0, 60000),
                ("human", "--ack-timeout-ms", 100, 60000),
                ("prune", "--launch-wait-ms", 0, 60000),
            ]:
                with self.subTest(operation=operation, flag=flag):
                    def invoke(*args):
                        return subprocess.run([BIN, "agents", operation, *args], env=env,
                                              capture_output=True, text=True, timeout=10)
                    help_text = invoke("--help")
                    self.assertEqual(help_text.returncode, 0, help_text.stderr)
                    self.assertIn(flag + " " + str(lower) + ".." + str(upper), help_text.stdout)
                    self.assertLess(len(help_text.stdout.encode()), 8192)
                    for value in (str(lower), str(upper)):
                        accepted = invoke(flag, value, "--help")
                        self.assertEqual(accepted.returncode, 0, accepted.stderr)
                    for value in (str(lower - 1), str(upper + 1), "not-an-integer"):
                        refused = invoke(flag, value, "--help")
                        self.assertEqual(refused.returncode, 2, refused.stderr)
                        self.assertIn("expected integer in " + str(lower) + ".." + str(upper), refused.stderr)
                        self.assertLess(len(refused.stderr.encode()), 8192)


class TimelineTest(unittest.TestCase):
    def test_legacy_archive_filters_order_and_read_only(self):
        with tempfile.TemporaryDirectory(prefix="tagents-timeline-") as tmp:
            root = Path(tmp)
            registry = root / "registry"
            registry.mkdir(mode=0o700)
            env = dict(os.environ, TEEREX_CALL_LOG_DIR=str(root / "calls"))
            first, second = "1" * 32, "2" * 32
            def state(launch, name, at):
                return dict(schema_version=1, launch_id=launch, name=name, created_at=at, protocol_ack_at=at+10,
                            target=dict(session_id="session:fixture", block_id="block:fixture"),
                            last_hook=dict(kind="Stop", at=at+20, text="done\nprivate second line"))
            live = registry / ("agents-" + first + ".json")
            live.write_text(json.dumps(state(first, "alpha", 1000)))
            live.chmod(0o600)
            archive = registry / "archive" / second
            archive.mkdir(parents=True, mode=0o700)
            old = state(second, "beta", 500)
            old["retired"] = dict(at=2000, reason="child_exited")
            path = archive / "retired.json"
            path.write_text(json.dumps(old))
            path.chmod(0o600)
            before = {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in registry.rglob("*") if p.is_file()}
            def command(*args):
                return subprocess.run([BIN, "agents", "timeline", "--registry", str(registry), *args], env=env, capture_output=True, text=True)
            p = command("--json")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            packet = json.loads(p.stdout)
            self.assertEqual([e["at"] for e in packet["events"]], [500, 510, 520, 1000, 1010, 1020, 2000])
            self.assertEqual(packet["events"][-1]["event"], "pruned")
            self.assertEqual(packet["legacy_partial_launches"], [first, second])
            self.assertNotIn("private second line", p.stdout)
            p = command("--name", "alpha", "--since", "1970-01-01T00:00:01.010Z", "--json")
            self.assertEqual([e["event"] for e in json.loads(p.stdout)["events"]], ["protocol_ack", "Stop"])
            self.assertEqual(command("--since", "1020", "--json").returncode, 0)
            self.assertNotEqual(command("--since", "yesterday").returncode, 0)
            self.assertNotEqual(command("--since", "2026-01-01").returncode, 0)
            p = command("--name", "alpha")
            self.assertEqual(len(p.stdout.splitlines()), 3)
            self.assertIn("partial", p.stderr)
            after = {str(p): (p.stat().st_mtime_ns, p.read_bytes()) for p in registry.rglob("*") if p.is_file()}
            self.assertEqual(before, after)


class ContractHelpersTest(unittest.TestCase):
    def setUp(self):
        self.ns = {"__name__": "contract_test", "SCRATCH_LIBRARY": True}
        base = Path(__file__).resolve().parents[1]
        exec(compile((base / "scratch/scratch.py").read_text(), "scratch.py", "exec"), self.ns)
        exec(compile((base.parent / "src/scoped_channel.py").read_text(), "scoped_channel.py", "exec"), self.ns)
        exec(compile((base / "agents/input_events.py").read_text(), "input_events.py", "exec"), self.ns)
        exec(compile((base / "agents/agents.py").read_text(), "agents.py", "exec"), self.ns)

    def test_init_precedence_and_interval_validation(self):
        state = dict(starter=None, purpose="task", intent="intent")
        init = self.ns["contract_init"]
        self.assertEqual(init(state, {}, "Done when: proven", None, None)["done_when"], "proven")
        self.assertEqual(init(state, {}, "done-when — proof", "explicit", 20)["interval_s"], 20)
        self.assertEqual(init(state, {}, "brief", None, None)["done_when"], "intent")
        self.assertEqual(init(state, {"contract_interval_s": 12}, "", None, None)["interval_s"], 12)
        for invalid in (0, -1, True, "10"):
            with self.assertRaises(self.ns["Refusal"]):
                init(state, {"contract_interval_s": invalid}, "", None, None)

    def test_snapshot_steps_declarations_and_flag_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            pad = Path(directory) / "pad.md"
            pad.write_text("# Worker\n## Now\n- [ ] Current\n## To-do\n- [ ] Later\n## Done\n- [x] Earlier\nBlocked: stuck; tried; need\n")
            state = dict(scratchpad=str(pad), contract={})
            snap = self.ns["contract_snapshot"](state)
            self.assertEqual((snap["steps_total"], snap["step_n"], snap["declared"]), (3, 2, "blocked"))
            state["contract"]["flag"] = dict(snap["flag"], delivered_at=123)
            self.assertEqual(self.ns["contract_snapshot"](state)["flag"]["delivered_at"], 123)
            pad.write_text("# Worker\n## Done\n- [x] Finished\n")
            self.assertEqual(self.ns["contract_snapshot"](state)["declared"], "done")
            pad.write_text("# Worker\nWaiting: review\nCheck: 2099-01-01T00:00:00Z\n")
            self.assertEqual(self.ns["contract_snapshot"](state)["declared"], "waiting")

    def test_zero_step_turn_after_ack_refuses_even_if_waiting_and_ambiguous_declarations_refuse(self):
        with tempfile.TemporaryDirectory() as directory:
            pad = Path(directory) / "pad.md"
            pad.write_text("# Worker\nWaiting: review\nCheck: 2099-01-01T00:00:00Z\n")
            state = dict(scratchpad=str(pad), contract={}, brief_attempted=True, brief_attempt_at=1, turn_started_at=1, contract_turn_ended=True)
            first = self.ns["contract_turn"](state)
            self.assertEqual(first["action"], "block")
            self.assertIn("write your steps first", first["reason"])
            self.assertEqual(self.ns["contract_turn"](state)["declared"], "waiting")
            pad.write_text("# Worker\n## Done\n- [x] Finished\nBlocked: stuck; tried; need\n")
            state["contract_reminded"] = False
            self.assertIsNone(self.ns["contract_snapshot"](state)["declared"])
            self.assertEqual(self.ns["contract_turn"](state)["action"], "block")

    def test_tell_deduplicates_and_records_contact(self):
        destination = dict(session_id="s", block_id="b")
        state = dict(name="worker", starter=destination, report_to=destination, target=destination, contract={})
        sent = []
        self.ns["load"] = lambda *_: state
        self.ns["update"] = lambda root, launch, change: change(state)
        self.ns["send"] = lambda *args: (sent.append(args) or (0, {"outcome": "events_acknowledged"}))
        code, packet = self.ns["contract_tell"]("root", "id", "done", "DONE worker: passed")
        self.assertEqual(code, 0)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1]["name"], "teerex-contract")
        self.assertEqual(state["contract"]["awaiting_starter"]["kind"], "done")
        self.assertFalse(state["contract"]["stalled"])
    def test_failed_contact_does_not_clear_lapse_and_timestamp_precedes_send(self):
        destination = dict(session_id="s", block_id="b")
        state = dict(name="worker", starter=destination, report_to=destination, contract=dict(last_contact_at=1, lapses=2, stalled=True))
        self.ns["load"] = lambda *_: state
        self.ns["update"] = lambda root, launch, change: change(state)
        self.ns["now"] = lambda: 10
        def failed(*args):
            self.ns["now"] = lambda: 20
            return 1, {"outcome": "uncertain"}
        self.ns["send"] = failed
        code, _ = self.ns["contract_tell"]("root", "id", "done", "DONE worker: proof")
        self.assertEqual(code, 1)
        self.assertEqual((state["contract"]["last_contact_at"], state["contract"]["lapses"], state["contract"]["stalled"]), (1, 2, True))
        self.assertNotIn("awaiting_starter", state["contract"])
        self.assertEqual(state["contract"]["last_contact_failed"]["at"], 10)
        def acknowledged(*args):
            self.ns["now"] = lambda: 30
            return 0, {"outcome": "events_acknowledged"}
        self.ns["send"] = acknowledged
        code, _ = self.ns["contract_tell"]("root", "id", "done", "DONE worker: proof")
        self.assertEqual(code, 0)
        self.assertEqual(state["contract"]["last_contact_at"], 20)
        self.assertEqual(state["contract"]["awaiting_starter"]["at"], 20)

    def test_flag_claim_is_atomic_and_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pad = root / "pad.md"
            pad.write_text("# Worker\nBlocked: stuck; tried; need\n")
            launch = "a" * 32
            destination = dict(session_id="s", block_id="b")
            state = dict(schema_version=1, launch_id=launch, name="worker", scratchpad=str(pad),
                         starter=destination, report_to=destination, contract={})
            record = root / ("agents-" + launch + ".json")
            record.write_text(json.dumps(state))
            record.chmod(0o600)
            sent = []
            self.ns["send"] = lambda *args: (sent.append(args) or (0, {"outcome": "events_acknowledged"}))
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: self.ns["contract_tell"](str(root), launch, "flag", "FLAG worker step 0/0: stuck; tried; need"), range(2)))
            self.assertEqual(len(sent), 1)
            saved = json.loads(record.read_text())["contract"]
            self.assertIsNotNone(saved["flag"]["delivered_at"])
            self.assertEqual(saved["awaiting_starter"]["kind"], "flag")
            self.assertEqual(sorted(r[1]["outcome"] for r in results), ["already_attempted", "transport_acknowledged"])

    def test_contract_activation_uses_brief_not_turn_start(self):
        state = dict(brief_attempted=False, brief_attempt_at=10, turn_started_at=20)
        self.assertFalse(self.ns["contract_active"](state))
        self.assertEqual(self.ns["contract_turn"](state), dict(status="not_applicable", action="allow"))
        state.update(brief_attempted=True, turn_started_at=9)
        self.assertTrue(self.ns["contract_active"](state))

    def test_contract_first_empty_turn_is_ack_but_steps_and_later_turns_are_judged(self):
        snapshot = dict(steps_total=0, declared=None)
        self.ns["contract_snapshot"] = lambda _: dict(snapshot)
        state = dict(brief_attempted=True, brief_attempt_at=10, turn_started_at=9, contract={})
        self.assertEqual(self.ns["contract_turn"](state), dict(status="protocol_ack", action="allow"))
        snapshot["steps_total"] = 1
        self.assertEqual(self.ns["contract_turn"](state)["action"], "block")
        snapshot["steps_total"] = 0
        state.update(contract_turn_ended=True, contract_reminded=False)
        check = self.ns["contract_turn"](state)
        self.assertEqual(check["action"], "block")
        self.assertEqual(check["reason"], CONTRACT_REFUSAL + "; write your steps first")

    def test_supervisor_contract_is_quiet_before_brief_attempt(self):
        state = dict(brief_attempted=False, brief_attempt_at=10, turn_started_at=9,
                     contract=dict(awaiting_starter=dict(kind="done", at=1)))
        self.ns["load"] = lambda *_: state
        def unexpected(*args, **kwargs):
            self.fail("pre-brief supervisor performed contract work")
        for name in ("contract_snapshot", "contract_tell", "update"):
            self.ns[name] = unexpected
        self.assertEqual(self.ns["contract_steps"]("root", "id", (None, [])), (None, []))
        self.ns["contract_lapse"]("root", "id")
        self.ns["contract_starter"]("root", "id")

    def test_answer_consumed_during_report_dispatch_is_not_reopened(self):
        destination = dict(session_id="s", block_id="b")
        state = dict(name="worker", starter=destination, report_to=destination, target=destination,
                     contract=dict(awaiting_starter=None, starter_lapses=0))
        self.ns["load"] = lambda *_: state
        self.ns["update"] = lambda root, launch, change: change(state)
        self.ns["now"] = lambda: 10
        def send(*args):
            self.ns["delivered_input"]("root", "id", dict(at_ns=11_000_000))
            return 0, {"outcome": "events_acknowledged"}
        self.ns["send"] = send
        code, _ = self.ns["contract_tell"]("root", "id", "done", "DONE worker: passed")
        self.assertEqual(code, 0)
        self.assertIsNone(state["contract"]["awaiting_starter"])

    def test_seat_lookup_is_limited_to_registered_host_and_server(self):
        state = dict(store="/tmp/boards", client_path="/bin", rex_executable="/bin/rex",
                     socket="/tmp/private.sock", target=dict(host="worker-host"))
        target = dict(host="worker-host", server="unix:///tmp/private.sock", session_id="s", block_id="b")
        seats = [dict(target=dict(target, host="other-host")), dict(target=dict(target, server="unix:///tmp/other.sock"))]
        self.ns["invoke"] = lambda *args, **kwargs: (0, dict(state=dict(seats=seats)))
        self.assertIsNone(self.ns["contract_seat"](state))
        seats.append(dict(target=target))
        self.assertEqual(self.ns["contract_seat"](state), target)
        seats.append(dict(target=dict(target, block_id="other")))
        with self.assertRaises(self.ns["Refusal"]):
            self.ns["contract_seat"](state)

    def test_input_older_than_report_does_not_clear_pending_answer(self):
        state = dict(contract=dict(awaiting_starter=dict(kind="flag", at=10), starter_lapses=1))
        self.ns["update"] = lambda root, launch, change: change(state)
        self.ns["delivered_input"]("root", "id", dict(at_ns=9_000_000))
        self.assertIsNotNone(state["contract"]["awaiting_starter"])
        self.ns["delivered_input"]("root", "id", dict(at_ns=11_000_000))
        self.assertIsNone(state["contract"]["awaiting_starter"])
        self.assertEqual(state["contract"]["starter_lapses"], 0)

    def test_failed_lapse_delivery_still_starts_a_fresh_window(self):
        state = dict(name="worker", brief_attempted=True, brief_attempt_at=1, turn_started_at=1,
                     contract=dict(declared=None, last_contact_at=0,
                     interval_s=2, lapses=0, step_n=1, steps_total=2))
        self.ns["load"] = lambda *_: json.loads(json.dumps(state))
        self.ns["update"] = lambda root, launch, change: change(state)
        clock = [2001]
        self.ns["now"] = lambda: clock[0]
        sent = []
        self.ns["contract_tell"] = lambda *args, **kwargs: (sent.append((args, kwargs)) or (1, {}))
        self.ns["contract_lapse"]("root", "id")
        self.assertEqual(state["contract"]["lapses"], 1)
        self.assertTrue(state["contract"]["stalled"])
        self.assertEqual(state["contract"]["last_contact_at"], 0)
        clock[0] += 50
        self.ns["contract_lapse"]("root", "id")
        self.assertEqual(len(sent), 2)
        clock[0] += 2000
        self.ns["contract_lapse"]("root", "id")
        self.assertEqual(state["contract"]["lapses"], 2)
        self.assertEqual(sent[-1][1], {"to": "seat"})



class AgentsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not REX:
            raise RuntimeError("Select the disposable test Rex with REX_BIN")
        cls.temp = tempfile.TemporaryDirectory(prefix="tagents-", dir="/tmp")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.socket = cls.root / "rex.sock"
        cls.base = [REX, "--autostart=false", "--server", "unix://" + str(cls.socket), "--timeout", "3s"]
        cls.log = (cls.root / "server.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.server = subprocess.Popen([REX, "server", "run", "--listen", "unix://" + str(cls.socket),
                                       "--restore=false", "--config", "/dev/null", "--state-dir", str(cls.root / "state")],
                                      stdout=cls.log, stderr=cls.log,
                                      env=dict(os.environ, HOME=str(cls.root), TEEREX_CLUTCH_DIR=str(cls.root / "server-clutch"), PATH=str(Path(REX).parent) + os.pathsep + os.environ.get("PATH", "")))
        cls.addClassCleanup(cls.stop_server)
        wait_for(lambda: cls.socket.exists())
        cls.version = cls.rpc("server.version", {})
        print("Real Rex:", json.dumps(cls.version), flush=True)

    @classmethod
    def stop_server(cls):
        cls.server.terminate()
        try:
            cls.server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.server.kill()
            cls.server.wait(timeout=5)

    @classmethod
    def rpc(cls, method, args):
        return json.loads(subprocess.check_output(cls.base + ["api", "call", method, json.dumps(args)], timeout=10))

    def setUp(self):
        self.work = self.root / str(time.monotonic_ns())
        self.work.mkdir()
        self.registry = self.work / "registry"
        self.registry.mkdir(mode=0o700)
        self.worker_log = self.work / "worker.jsonl"
        self.starter_log = self.work / "starter.jsonl"
        self.fixture = self.work / "fixture.py"
        self.fixture.write_text(FIXTURE)
        target = json.loads(subprocess.check_output(self.base + ["new", "--json", "--keep-open", "--shell=none", "--",
                                                                 sys.executable, str(self.fixture), str(self.starter_log), "noack"], timeout=10))
        self.session = target["session_id"]
        self.starter = target["initial_windows"][0]["block_ids"][0]
        wait_for(lambda: events(self.starter_log))
        self.env = dict(os.environ, HOME=str(self.root), TEEREX_CLUTCH_DIR=str(self.work / "clutch"), PATH=str(Path(REX).parent) + os.pathsep + os.environ.get("PATH", ""),
                        REX_SERVER="unix:///tmp/poison.sock", REX_SESSION="session:poison", REX_BLOCK="block:poison")
        self.config = self.work / "profiles.json"
        self.settings = dict(schema_version=1, defaults=dict(registry=str(self.registry), socket=str(self.socket),
                             session=self.session, cwd=str(self.work), starter_session=self.session, starter_block=self.starter,
                             host="disposable", owner="operator", purpose="asymmetric lifecycle regression", review_after_ms=60000),
                             profiles=dict(probe=dict(argv=[sys.executable, str(self.fixture), str(self.worker_log), "ack"],
                                                      harness="synthetic", protocol_mode="argument", standing_flags=["--explicit-standing-flag"])))
        self.config.write_text(json.dumps(self.settings))
        self.brief = self.work / "brief.txt"
        self.brief.write_text("TASK β asymmetric\nPreserve quotes '\" and final newline.\n")

    def run_cli(self, *args, timeout=15, **kwargs):
        p = subprocess.run([BIN, "agents", *args], text=True, capture_output=True, env=self.env, timeout=timeout, **kwargs)
        return p, json.loads(p.stdout) if p.stdout.strip().startswith("{") else None

    def launch(self, behavior="ack", ack_timeout=2000, contract=False):
        self.settings["profiles"]["probe"]["argv"][-1] = behavior
        self.config.write_text(json.dumps(self.settings))
        result = self.run_cli("launch", "--config", str(self.config), "--profile", "probe", "--brief-file", str(self.brief),
                              "--ack-timeout-ms", str(ack_timeout))
        if not contract and result[1] and result[1].get("launch_id"):
            # Preserve regression coverage for records created before contract enforcement.
            launch_id = result[1]["launch_id"]
            state = self.record(launch_id)
            state.pop("contract", None)
            (self.registry / ("agents-" + launch_id + ".json")).write_text(json.dumps(state))
        if behavior in ("codex-hook", "pi-hook") and result[0].returncode == 0:
            trigger = self.work / "run-hooks.txt"
            trigger.write_text("RUN SYNTHETIC HOOKS")
            sent = subprocess.run([BIN, "send", "--socket", str(self.socket), "--session", self.session,
                                   "--block", result[1]["target"]["block_id"], "--from", "fixture", "--message-file", str(trigger)],
                                  env=self.env, capture_output=True, text=True, timeout=15)
            self.assertEqual(sent.returncode, 0, sent.stdout + sent.stderr)
        return result

    def record(self, launch_id):
        return json.loads((self.registry / ("agents-" + launch_id + ".json")).read_text())

    def test_detached_launch_tracking_prune_present_and_come_forward(self):
        profile = self.settings['profiles']['probe']
        profile.update(layout='detached', come_forward=True)
        self.config.write_text(json.dumps(self.settings))
        process, launched = self.run_cli('launch', '--config', str(self.config), '--profile', 'probe', '--brief-file', str(self.brief), '--ack-timeout-ms', '5000')
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        launch_id = launched['launch_id']
        block = launched['target']['block_id']
        self.assertEqual(launched['placement'], 'detached')
        self.assertTrue(Path(launched['scratchpad']).exists())
        def inspect():
            process, packet = self.run_cli('inspect', '--registry', str(self.registry), '--launch-id', launch_id)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            return packet
        self.assertEqual(inspect()['placement'], 'detached')
        def jobs():
            packet = subprocess.run([BIN, 'jobs', 'list', '--registry', str(self.registry)], env=self.env, capture_output=True, text=True)
            self.assertEqual(packet.returncode, 0, packet.stdout + packet.stderr)
            return json.loads(packet.stdout)['entries'][0]
        entry = jobs()
        self.assertEqual(entry['placement'], 'detached')
        self.backdate(launch_id)
        process, plan = self.run_cli('prune', '--registry', str(self.registry))
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertFalse(plan['retired'])
        target = dict(session_id=self.session, block_id=block, args={})
        child = self.rpc('com.superlogical.terminal.process', target)['child']
        before = self.rpc('session.view', dict(session_id=self.session))
        # This is a new contract launch, so finishing the work is explicit.
        for arguments in (("now", "Detached work"), ("done",)):
            finished = subprocess.run([BIN, "scratch", *arguments, "--session", self.session, "--block", block],
                                      env=self.env, capture_output=True, text=True)
            self.assertEqual(finished.returncode, 0, finished.stdout + finished.stderr)
        event = self.work / 'stop.json'
        event.write_text(json.dumps(dict(hook_event_name='Stop', last_assistant_message='Detached work finished')))
        process, packet = self.run_cli('stop', '--registry', str(self.registry), '--launch-id', launch_id, '--event-file', str(event))
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        wait_for(lambda: inspect()['placement'] == 'placed')
        after = self.rpc('session.view', dict(session_id=self.session))
        self.assertEqual(after['active_window_id'], before['active_window_id'])
        for old in before['windows']:
            new = next(w for w in after['windows'] if w['window_id'] == old['window_id'])
            self.assertEqual(new['focused_block_id'], old['focused_block_id'])
        self.assertEqual(self.rpc('com.superlogical.terminal.process', target)['child'], child)
        self.rpc('session.detach_block', dict(session_id=self.session, block_id=block))
        self.assertEqual(jobs()['placement'], 'detached')
        event.write_text(json.dumps(dict(hook_event_name='StopFailure', error='synthetic detached failure')))
        process, packet = self.run_cli('stop', '--registry', str(self.registry), '--launch-id', launch_id, '--event-file', str(event))
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        wait_for(lambda: inspect()['placement'] == 'placed')
        self.rpc('session.detach_block', dict(session_id=self.session, block_id=block))
        process = subprocess.run([BIN, 'jobs', 'present', '--registry', str(self.registry), '--socket', str(self.socket),
            '--session', self.session, '--block', block, '--owner', entry['owner'], '--generation', str(entry['generation']),
            '--reason', 'bring detached work forward', '--anchor', self.starter, '--focus', 'no'], env=self.env, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(inspect()['placement'], 'placed')
        self.assertEqual(self.rpc('com.superlogical.terminal.process', target)['child'], child)
        # CLI override wins over the profile, with come-forward disabled by default.
        profile.update(layout='tab', come_forward=False)
        self.config.write_text(json.dumps(self.settings))
        process, packet = self.run_cli('launch', '--config', str(self.config), '--profile', 'probe', '--layout', 'detached',
            '--ack-timeout-ms', '5000')
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(packet['placement'], 'detached')

    def test_detached_exit_comes_forward_without_focus(self):
        self.settings['profiles']['probe'].update(layout='detached', come_forward=True)
        before = self.rpc('session.view', dict(session_id=self.session))
        process, packet = self.launch('exit7', ack_timeout=5000)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        launch_id, block = packet['launch_id'], packet['target']['block_id']
        wait_for(lambda: self.record(launch_id).get('come_forward_last', {}).get('event') == 'exit')
        self.assertEqual(self.record(launch_id)['immediate_child_term'], dict(Exited=7))
        after = self.rpc('session.view', dict(session_id=self.session))
        self.assertEqual(after['active_window_id'], before['active_window_id'])
        self.assertEqual(after['windows'][0]['focused_block_id'], self.starter)
        self.assertEqual(self.rpc('session.describe_block', dict(session_id=self.session, block_id=block))['block']['placement'], 'placed')

    def test_stop_notification_waits_for_and_restores_operator_draft(self):
        prompt_log = self.work / "prompt.jsonl"
        fixture = Path(__file__).parents[1] / "send" / "prompt_fixture.py"
        made = json.loads(subprocess.check_output(self.base + ["new", "--json", "--keep-open", "--shell=none", "--",
                          sys.executable, str(fixture), str(prompt_log)]))
        sid, bid = made["session_id"], made["initial_windows"][0]["block_ids"][0]
        wait_for(lambda: prompt_log.exists())
        self.settings["defaults"].update(starter_session=sid, starter_block=bid)
        process, launch = self.launch()
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        text = "PRIVATE_OPERATOR_DRAFT_" + "x" * 34
        def type_char(char):
            self.rpc("com.superlogical.terminal.write", dict(session_id=sid, block_id=bid, args=dict(data=char)))
        type_char(text[0])
        def writer():
            for char in text[1:]:
                time.sleep(.2)
                type_char(char)
        thread = threading.Thread(target=writer)
        thread.start()
        event = self.work / "stop-event.json"
        event.write_text(json.dumps(dict(hook_event_name="Stop", last_assistant_message="notification only")))
        try:
            process, receipt = self.run_cli("stop", "--registry", str(self.registry), "--launch-id", launch["launch_id"],
                                           "--event-file", str(event), timeout=25)
        finally:
            thread.join()
        self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
        lines = [json.loads(line) for line in prompt_log.read_text().splitlines()]
        self.assertEqual(len(lines), 1)
        self.assertIn("notification only", lines[0])
        self.assertNotIn(text, lines[0])
        capture = self.rpc("com.superlogical.terminal.format", dict(session_id=sid, block_id=bid, args=dict(format="text")))
        self.assertIn("❯\xa0" + text, capture["content"])
        result = next(iter(self.record(launch["launch_id"])["notifications"].values()))["results"][0]["receipt"]
        self.assertGreater(result["draft"]["waited_ms"], 10000)
        self.assertTrue(result["draft"]["restore_verified"])
        self.assertNotIn(text, process.stdout + process.stderr)

    def test_four_concurrent_launches_are_all_tracked_and_delivered(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(self.run_cli, "launch", "--config", str(self.config), "--profile", "probe",
                                   "--name", "concurrent-" + str(index), "--brief-file", str(self.brief),
                                   "--ack-timeout-ms", "4000", timeout=30) for index in range(4)]
            launches = [future.result() for future in futures]
        blocks = set()
        for process, receipt in launches:
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            self.assertEqual(receipt["outcome"], "brief_submitted")
            self.assertTrue(receipt["tracked"] and receipt["protocol_acknowledged"])
            state = self.record(receipt["launch_id"])
            self.assertEqual(state["protocol_outcome"], "argument_supplied")
            self.assertEqual(state["brief_outcome"], "events_acknowledged")
            blocks.add(state["target"]["block_id"])
        self.assertEqual(len(blocks), 4)
        jobs = json.loads(subprocess.check_output([BIN, "jobs", "list", "--registry", str(self.registry)], env=self.env))
        self.assertEqual({e["block_id"] for e in jobs["entries"]}, blocks)
        self.assertEqual(len(self.rpc("session.view", dict(session_id=self.session))["windows"]), 5)

    def test_launch_queue_timeout_creates_no_panes_or_launch_records(self):
        lock_path = self.registry / "launch.lock"
        lock_path.touch(mode=0o600)
        before = self.rpc("session.view", dict(session_id=self.session))
        with lock_path.open("r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = [pool.submit(self.run_cli, "launch", "--config", str(self.config), "--profile", "probe",
                                       "--launch-wait-ms", "20") for _ in range(4)]
                for future in futures:
                    process, receipt = future.result()
                    self.assertEqual(process.returncode, 1, process.stdout + process.stderr)
                    self.assertEqual(receipt["failure_reason"], "launch_queue_busy")
                    self.assertTrue(receipt["retry_safe"])
                    self.assertFalse(receipt["creation_attempted"])
                    self.assertIsNone(receipt["created"])
        self.assertEqual(self.rpc("session.view", dict(session_id=self.session)), before)
        self.assertEqual(list(self.registry.glob("agents-*.json")), [])
        self.assertFalse(self.worker_log.exists())

    def test_launch_queue_is_released_before_waiting_for_ack(self):
        quiet = dict(self.settings["profiles"]["probe"])
        quiet["argv"] = [sys.executable, str(self.fixture), str(self.worker_log), "noack"]
        self.settings["profiles"]["quiet"] = quiet
        self.config.write_text(json.dumps(self.settings))
        process = subprocess.Popen([BIN, "agents", "launch", "--config", str(self.config), "--profile", "quiet",
                                    "--ack-timeout-ms", "10000"], env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            def waiting():
                for path in self.registry.glob("agents-*.json"):
                    state = json.loads(path.read_text())
                    if state["phase"] == "awaiting_protocol_ack" and state.get("protocol_outcome") == "argument_supplied":
                        return state
            wait_for(waiting)
            result, receipt = self.run_cli("launch", "--config", str(self.config), "--profile", "probe",
                                           "--brief-file", str(self.brief), "--launch-wait-ms", "0", "--ack-timeout-ms", "4000")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(receipt["tracked"])
            self.assertIsNone(process.poll(), "the first launch must still be waiting for its ACK")
        finally:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=5)

    def test_turn_report_delivery_rules_keep_progress_quiet(self):
        p, launched = self.launch()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        launch_id = launched["launch_id"]
        state = self.record(launch_id)
        pad = Path(state["scratchpad"])
        # Match the actual destination's label, rather than guessing its name.
        label = "lead-worker"
        renamed = subprocess.run([BIN, "surfaces", "rename", "--socket", str(self.socket),
            "--session", self.session, "--pane", self.starter, "--label", label],
            env=self.env, capture_output=True, text=True)
        self.assertEqual(renamed.returncode, 0, renamed.stdout + renamed.stderr)
        event = self.work / "quiet-event.json"
        cases = [
            ("progress", "- [ ] implement\n", "- [ ] test\n", "", "Stop", "progress_turn_suppressed", False),
            ("finished", "", "", "", "Stop", "finished_now_empty", True),
            ("done", "- [x] implement\n", "", "", "Stop", "finished_now_done", True),
            ("waiting", "- [ ] integrate\n", "- [ ] test\n", "Waiting: lead-worker · need review · since 2026-11-13T00:00:00Z\n", "Stop", "waiting_on_report_to_or_seat", True),
            ("other-wait", "- [ ] integrate\n", "", "Waiting: someone-else · dependency · since 2026-11-13T00:00:00Z\n", "Stop", "progress_turn_suppressed", False),
            ("failure", "- [ ] implement\n", "- [ ] test\n", "", "StopFailure", "harness_failed", True),
            ("missing", None, "", "", "Stop", "scratchpad_unreadable", True),
        ]
        expected = 0
        for index, (name, current, todo, waiting, kind, rule, deliver) in enumerate(cases):
            event_id = "%032x" % (index + 1)
            if current is None:
                pad.unlink()
            else:
                pad.write_text("# worker\n" + waiting + "\n## Now\n" + current + "\n## To-do\n" + todo + "\n## Done\n")
            event.write_text(json.dumps(dict(hook_event_name=kind, last_assistant_message=name, error="failure")))
            p, packet = self.run_cli("stop", "--registry", str(self.registry), "--launch-id", launch_id,
                "--event-id", event_id, "--event-file", str(event))
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(packet["delivery_rule"], rule)
            notice = self.record(launch_id)["notifications"][event_id]
            self.assertEqual(len(notice["results"]), int(deliver))
            expected += int(deliver)
            if deliver:
                wait_for(lambda: len([v for v in events(self.starter_log) if v["event"] == "input"]) == expected)
            self.assertEqual(len([v for v in events(self.starter_log) if v["event"] == "input"]), expected)
        p, timeline = self.run_cli("timeline", "--registry", str(self.registry), "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        stops = [e for e in timeline["events"] if e["event"] in ("Stop", "StopFailure")]
        self.assertEqual(len(stops), len(cases))
        self.assertEqual(stops[0]["delivery_rule"], "progress_turn_suppressed")

    def test_agent_keeps_three_step_scratchpad_visible(self):
        p, packet = self.launch("scratch-three")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        wait_for(lambda: any(v["event"] == "scratch-complete" for v in events(self.worker_log)))
        state = self.record(packet["launch_id"])
        pad = Path(state["scratchpad"])
        self.assertEqual(pad.read_text().count("- [x]"), 3)
        self.assertNotIn("- [ ]", pad.read_text())
        side = state["scratch_pane_receipt"]["created"]["block_id"]
        base = [BIN, "observe", "--socket", str(self.socket), "--session", self.session, "--block", side, "--tail"]
        def displayed():
            observed = subprocess.run(base, env=self.env, capture_output=True, text=True, timeout=10)
            return observed.stdout if "✓ Run gates" in observed.stdout else None
        self.assertIn("Read contracts", wait_for(displayed))

    def test_contract_launch_options_and_scratch_done_when(self):
        self.settings["profiles"]["probe"]["contract_interval_s"] = 25
        self.config.write_text(json.dumps(self.settings))
        self.brief.write_text("Task\nDone when: proof complete\n")
        p, packet = self.run_cli("launch", "--config", str(self.config), "--profile", "probe", "--brief-file", str(self.brief),
                                 "--done-when", "explicit proof", "--contract-interval-s", "30", "--ack-timeout-ms", "5000")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        state = self.record(packet["launch_id"])
        self.assertEqual(state["contract"]["done_when"], "explicit proof")
        self.assertEqual(state["contract"]["interval_s"], 30)
        self.assertEqual(state["contract"]["starter"], state["starter"])
        self.assertIn("Done-when: explicit proof", Path(state["scratchpad"]).read_text())
        protocol = Path(state["protocol_file"]).read_text()
        self.assertIn(f'(AGENT_SCRATCHPAD).\n{CONTRACT_PROTOCOL}\n', protocol)
        p, packet = self.launch(contract=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.record(packet["launch_id"])["contract"]["done_when"], "proof complete")
        self.assertEqual(self.record(packet["launch_id"])["contract"]["interval_s"], 25)

    def test_protocol_before_brief_exact_metadata_and_jobs(self):
        self.settings["profiles"]["probe"]["standing_flags"] *= 2
        p, packet = self.launch()
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual(packet["outcome"], "brief_submitted")
        self.assertEqual(packet["agent_readiness"], "not_assessed")
        self.assertFalse(packet["exclusive_input_lease"])
        self.assertNotIn("token", packet)
        state = self.record(packet["launch_id"])
        worker = wait_for(lambda: events(self.worker_log) if len(events(self.worker_log)) >= 4 else None)
        inputs = [v["payload"] for v in worker if v["event"] in ("protocol_argument", "input")]
        self.assertEqual(len(inputs), 2)
        self.assertIn("Messaging protocol (not a task brief):", inputs[0])
        self.assertNotIn("TASK β", inputs[0])
        self.assertIn(CONTRACT_PROTOCOL, inputs[0])
        self.assertEqual(inputs[1], "FROM probe: " + self.brief.read_text())
        self.assertEqual([v["code"] for v in worker if v["event"] == "ack"], [0])
        env = worker[0]["env"]
        scratch = Path(state["scratchpad"])
        self.assertTrue(scratch.is_file())
        self.assertIn("Purpose: asymmetric lifecycle regression", scratch.read_text())
        self.assertIn("Intent: TASK β asymmetric", scratch.read_text())
        self.assertIn(str(scratch), inputs[0])
        self.assertEqual(env["AGENT_SCRATCHPAD"], str(scratch))
        self.assertEqual(env["LC_AGENT_SCRATCHPAD"], str(scratch))
        self.assertTrue(state["scratch_pane_opened"], state.get("scratch_pane_receipt"))
        expected = dict(AGENT_SESSION=self.session, AGENT_PANE=state["target"]["block_id"], AGENT_NAME="probe",
                        AGENT_STARTER=self.session + " " + self.starter, AGENT_REPORT_TO=self.session + " " + self.starter)
        for k, v in expected.items():
            self.assertEqual(env[k], v)
            self.assertEqual(env["LC_" + k], v)
        self.assertEqual(worker[0]["argv"], ["--explicit-standing-flag"])
        jobs = json.loads(subprocess.check_output([BIN, "jobs", "list", "--registry", str(self.registry)], env=self.env))
        self.assertEqual(len(jobs["entries"]), 1)
        self.assertEqual(jobs["entries"][0]["block_id"], state["target"]["block_id"])
        self.assertEqual(jobs["entries"][0]["owner"], "operator")
        self.assertEqual(jobs["entries"][0]["deadline_unix_ms"], state["review_at"])
        view = self.rpc("session.view", {"session_id": self.session})
        self.assertEqual(len(view["windows"]), 2)
        self.assertTrue(any(b["block_id"] == state["target"]["block_id"] for w in view["windows"]
                            for layer in w["layers"] for b in layer["blocks"]))
        p, again = self.run_cli("deliver", "--registry", str(self.registry), "--launch-id", state["launch_id"])
        self.assertEqual(p.returncode, 1)
        self.assertIn("brief_already_attempted", again["failure_reason"])

    def test_timeout_never_sends_brief_wrong_token_address_and_explicit_continue(self):
        p, packet = self.launch("noack", ack_timeout=250)
        self.assertEqual(p.returncode, 124, p.stderr + p.stdout)
        self.assertEqual(packet["outcome"], "protocol_ack_timeout")
        state = self.record(packet["launch_id"])
        self.assertFalse(state["brief_attempted"])
        wait_for(lambda: self.program_state(state["target"]["block_id"]) == "working")
        def acknowledge(token, block):
            return self.run_cli("ack", "--registry", str(self.registry), "--launch-id", state["launch_id"],
                                "--token", token, "--session", self.session, "--block", block)
        p, failure = acknowledge("0" * 64, state["target"]["block_id"])
        self.assertEqual(p.returncode, 1)
        self.assertIn("token_mismatch", failure["failure_reason"])
        p, failure = acknowledge(state["token"], self.starter)
        self.assertEqual(p.returncode, 1)
        self.assertIn("address_mismatch", failure["failure_reason"])
        self.assertEqual(len([v for v in events(self.worker_log) if v["event"] == "input"]), 0)
        p, _ = self.run_cli("deliver", "--registry", str(self.registry), "--launch-id", state["launch_id"])
        self.assertEqual(p.returncode, 1)
        p, acked = acknowledge(state["token"], state["target"]["block_id"])
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual(acked["outcome"], "protocol_acknowledged")
        p, _ = self.run_cli("deliver", "--registry", str(self.registry), "--launch-id", state["launch_id"])
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        wait_for(lambda: len([v for v in events(self.worker_log) if v["event"] == "input"]) == 1)

    def test_idle_error_hooks_and_real_exit_are_different(self):
        p, packet = self.launch()
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        launch_id = packet["launch_id"]
        transcript = self.work / "transcript.jsonl"
        transcript.write_text("not json\n" + json.dumps(dict(type="assistant", message=dict(content=[
            dict(type="text", text="Result β: one changed edge.")]))) + "\n")
        hook = json.dumps(dict(hook_event_name="Stop", transcript_path=str(transcript)))
        p, report = self.run_cli("stop", "--registry", str(self.registry), "--launch-id", launch_id, "--event-file", "-", "--event-id", "1" * 32, input=hook)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        state = self.record(launch_id)
        self.assertIsNone(state["immediate_child_term"])
        self.assertEqual(state["last_hook"]["kind"], "Stop")
        self.assertEqual(state["last_hook"]["text"], "Result β: one changed edge.")
        wait_for(lambda: any("IDLE (harness turn-stop report)" in v.get("payload", "") for v in events(self.starter_log)))
        p, duplicate = self.run_cli("stop", "--registry", str(self.registry), "--launch-id", launch_id, "--event-file", "-", "--event-id", "1" * 32, input=hook)
        self.assertEqual(p.returncode, 1)
        self.assertIn("notification_already_attempted", duplicate["failure_reason"])
        hook = json.dumps(dict(hook_event_name="StopFailure", error="synthetic failure, process still alive"))
        p, _ = self.run_cli("stop", "--registry", str(self.registry), "--launch-id", launch_id, "--event-file", "-", "--event-id", "2" * 32, input=hook)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertIsNone(self.record(launch_id)["immediate_child_term"])
        pid = events(self.worker_log)[0]["pid"]
        os.kill(pid, signal.SIGTERM)  # only this disposable fixture's independently recorded actual child PID
        state = wait_for(lambda: self.record(launch_id) if self.record(launch_id)["immediate_child_term"] else None)
        self.assertEqual(state["immediate_child_term"], {"Signal": signal.SIGTERM})
        wait_for(lambda: any("PROCESS EXIT:" in v.get("payload", "") for v in events(self.starter_log)))
        notices = [v["payload"] for v in events(self.starter_log) if v["event"] == "input"]
        self.assertEqual(len(notices), 3)
        self.assertIn("death not verified", notices[1])
        self.assertIn("Descendants are not verified gone", notices[2])

    def test_distinct_starter_and_report_to_export_and_notify_both(self):
        report_log = self.work / "report-to.jsonl"
        target = self.rpc("session.new_window", dict(session_id=self.session, focus=False, layout=dict(block=dict(
            flavor="com.superlogical.terminal.shell", options=dict(command=[sys.executable, str(self.fixture), str(report_log), "noack"],
                                                                  exit=dict(on_completion=False))))))
        report_session = self.session
        report_block = target["block_ids"][0]
        wait_for(lambda: events(report_log))
        self.settings["defaults"].update(report_to_session=report_session, report_to_block=report_block)
        p, packet = self.launch("exit7")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        state = wait_for(lambda: self.record(packet["launch_id"]) if self.record(packet["launch_id"])[
            "notifications"].get("child-exit", {}).get("outcome") == "transport_acknowledged" else None)
        self.assertEqual(len(state["notifications"]["child-exit"]["results"]), 2)
        env = events(self.worker_log)[0]["env"]
        for prefix in ("", "LC_"):
            self.assertEqual(env[prefix + "AGENT_STARTER"], self.session + " " + self.starter)
            self.assertEqual(env[prefix + "AGENT_REPORT_TO"], report_session + " " + report_block)
        for log in (self.starter_log, report_log):
            reports = wait_for(lambda: [v for v in events(log) if v["event"] == "input"])
            self.assertEqual(len(reports), 1)
            self.assertIn("PROCESS EXIT:", reports[0]["payload"])

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_CROSS_SESSION") == "1", "separate-session shared spawn regression gate")
    def test_cross_session_report_target_independently_visible_then_managed_launch(self):
        report_log = self.work / "cross-session-report.jsonl"
        target = json.loads(subprocess.check_output(self.base + ["new", "--json", "--keep-open", "--shell=none", "--",
                                                                sys.executable, str(self.fixture), str(report_log), "noack"], timeout=10))
        report_session = target["session_id"]
        report_block = target["initial_windows"][0]["block_ids"][0]
        wait_for(lambda: events(report_log))
        view = self.rpc("session.view", dict(session_id=report_session))
        self.assertTrue(any(b["block_id"] == report_block for w in view["windows"] for layer in w["layers"] for b in layer["blocks"]))
        self.settings["defaults"].update(report_to_session=report_session, report_to_block=report_block)
        p, packet = self.launch("exit7")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout + "\n" + json.dumps(self.record(packet["launch_id"])["spawn_receipt"]))
        state = wait_for(lambda: self.record(packet["launch_id"]) if self.record(packet["launch_id"])[
            "notifications"].get("child-exit", {}).get("outcome") == "transport_acknowledged" else None)
        self.assertEqual(len(state["notifications"]["child-exit"]["results"]), 2)
        wait_for(lambda: [v for v in events(report_log) if v["event"] == "input"])

    def backdate(self, launch_id, **changes):
        path = self.registry / ("agents-" + launch_id + ".json")
        state = json.loads(path.read_text())
        state.update(created_at=state["created_at"] - 600000, **changes)
        path.write_text(json.dumps(state))
        path.chmod(0o600)
        return state

    def test_prune_archives_exited_never_started_and_gone_panes_and_launch_prunes_automatically(self):
        alive = self.launch("ack")[1]["launch_id"]
        exited = self.launch("exit7")[1]["launch_id"]
        gone = self.launch("ack")[1]["launch_id"]
        wait_for(lambda: self.record(exited)["immediate_child_term"])
        recent = self.launch("ack")[1]["launch_id"]  # still inside the settle window
        gone_block = self.record(gone)["target"]["block_id"]
        closed = subprocess.run([BIN, "surfaces", "close", "--socket", str(self.socket), "--session", self.session, "--pane", gone_block],
                                capture_output=True, text=True, env=self.env)
        self.assertIn("closed_and_absent", closed.stdout)
        for launch_id in (alive, exited, gone):
            self.backdate(launch_id)
        stale = self.backdate(alive)
        never = dict(stale, launch_id="e" * 32, phase="tracking_uncertain", tracked=False)
        never["target"] = dict(stale["target"], block_id=None)
        (self.registry / ("agents-" + "e" * 32 + ".json")).write_text(json.dumps(never))
        (self.registry / ("agents-" + "e" * 32 + ".json")).chmod(0o600)
        orphan = self.registry / ("agents-" + "f" * 32 + "-brief.txt")
        orphan.write_text("old brief")
        os.utime(orphan, (time.time() - 600, time.time() - 600))

        before = sorted(p.name for p in self.registry.iterdir())
        p, plan = self.run_cli("prune", "--registry", str(self.registry), timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(plan["outcome"], "prune_plan")
        self.assertEqual(sorted(p.name for p in self.registry.iterdir()), before, "a plan must change nothing")
        reasons = {r["launch_id"]: r["reason"] for r in plan["retired"]}
        self.assertEqual(reasons, {exited: "agent_exited", gone: "pane_gone", "e" * 32: "never_started"})
        self.assertEqual(plan["kept"], 2)
        self.assertEqual(plan["orphans"], [orphan.name])

        p, done = self.run_cli("prune", "--registry", str(self.registry), "--apply", timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(done["live_after"], 2)
        scratch_archive = next(v["scratchpad_archive"] for v in done["retired"] if v["launch_id"] == gone)
        self.assertTrue(Path(scratch_archive).is_file())
        self.assertFalse(Path(self.root / ".local/state/teerex/scratch" / self.session / (gone_block + ".md")).exists())
        for launch_id, reason in reasons.items():
            archived = self.registry / "archive" / launch_id
            self.assertEqual(json.loads((archived / "retired.json").read_text())["retired"]["reason"], reason)
            self.assertEqual(list(self.registry.glob("agents-" + launch_id + "*")), [])
        self.assertTrue((self.registry / "archive" / exited / ("agents-" + exited + "-brief.txt")).exists())
        self.assertTrue((self.registry / "archive" / "orphans" / orphan.name).exists())
        self.assertEqual(oct((self.registry / "archive").stat().st_mode & 0o777), "0o700")
        self.assertTrue(self.record(alive) and self.record(recent))
        jobs = json.loads(subprocess.check_output([BIN, "jobs", "list", "--registry", str(self.registry)], env=self.env))
        self.assertNotIn(gone_block, [e["block_id"] for e in jobs["entries"]], "a gone pane's jobs registration is forgotten")
        self.assertIn(self.record(alive)["target"]["block_id"], [e["block_id"] for e in jobs["entries"]])
        # The exited record is already archived, but its still-open pane owns the list.
        exited_history = json.loads((self.registry / "archive" / exited / "retired.json").read_text())
        exited_pad = Path(exited_history["scratchpad"])
        self.assertTrue(exited_pad.exists())
        closed = subprocess.run([BIN, "surfaces", "close", "--socket", str(self.socket), "--session", self.session,
                                 "--pane", exited_history["target"]["block_id"]], capture_output=True, text=True, env=self.env)
        self.assertEqual(closed.returncode, 0, closed.stdout + closed.stderr)
        p, later = self.run_cli("prune", "--registry", str(self.registry), "--apply", timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertFalse(exited_pad.exists())
        self.assertEqual(len(later["archived_scratchpads"]), 1)

        # Fill to the auto-prune threshold with old exited records; the next launch archives them itself.
        template = self.record(alive)
        for i in range(24):
            fake = dict(template, launch_id="%032x" % (i + 1), created_at=template["created_at"] - 600000,
                        immediate_child_term={"Exited": 0})
            path = self.registry / ("agents-" + fake["launch_id"] + ".json")
            path.write_text(json.dumps(fake))
            path.chmod(0o600)
        p, packet = self.launch("ack")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(packet["auto_prune"]["retired"], 24)
        self.assertEqual(len(list(self.registry.glob("agents-" + "?" * 32 + ".json"))), 3)

    def test_immediate_exit7_alert_with_retained_visible_pane(self):
        p, packet = self.launch("exit7")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        launch_id = packet["launch_id"]
        state = wait_for(lambda: self.record(launch_id) if self.record(launch_id)["immediate_child_term"] else None)
        self.assertEqual(state["immediate_child_term"], {"Exited": 7})
        wait_for(lambda: any('"Exited": 7' in v.get("payload", "") for v in events(self.starter_log)))
        self.assertFalse(packet["all_processes_verified_gone"])
        view = self.rpc("session.view", {"session_id": self.session})
        self.assertEqual(len(view["windows"]), 2)

    def shim(self, drop):
        directory = self.work / "shim"
        directory.mkdir()
        path = directory / "rex"
        path.write_text(f"#!{sys.executable}\n" +
                        "import json,subprocess,sys\n"
                        f"r=subprocess.run([{REX!r},*sys.argv[1:]],capture_output=True)\n"
                        "a=json.loads(sys.argv[sys.argv.index('--args')+1]) if '--args' in sys.argv else {}\n"
                        f"drop={drop}\n"
                        "sys.stderr.buffer.write(r.stderr)\n"
                        "if not drop: sys.stdout.buffer.write(r.stdout)\n"
                        "sys.exit(r.returncode)\n")
        path.chmod(0o755)
        self.env["PATH"] = str(directory) + os.pathsep + self.env["PATH"]

    def test_cancellation_cleans_owned_client_without_stopping_server(self):
        before = self.rpc("session.view", dict(session_id=self.session))
        for sig in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=sig):
                directory = self.work / ("hang-" + str(sig))
                directory.mkdir()
                ready = directory / "pid"
                shim = directory / "rex"
                shim.write_text(f"#!{sys.executable}\nimport os,signal,time\nfrom pathlib import Path\n"
                                f"Path({str(ready)!r}).write_text(str(os.getpid()))\n"
                                "signal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(60)\n")
                shim.chmod(0o755)
                env = dict(self.env, PATH=str(directory) + os.pathsep + self.env["PATH"])
                p = subprocess.Popen([BIN, "agents", "launch", "--config", str(self.config), "--profile", "probe"],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
                client_pid = None
                try:
                    wait_for(lambda: ready.exists())
                    client_pid = int(ready.read_text())
                    p.send_signal(sig)
                    out, err = p.communicate(timeout=4)
                    self.assertEqual(p.returncode, 128 + sig, err + out)
                    self.assertEqual(json.loads(out)["outcome"], "cancelled_uncertain")
                    # This is the controlled transport's own PID, not a user/server/agent process.
                    try:
                        os.kill(client_pid, 0)
                        alive = True
                    except ProcessLookupError:
                        alive = False
                    self.assertFalse(alive, "owned Rex transport survived launcher cancellation")
                finally:
                    if p.poll() is None:
                        p.kill()
                        p.wait()
                    if client_pid is not None:
                        try:
                            os.killpg(client_pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
        self.assertEqual(self.rpc("session.view", dict(session_id=self.session)), before)

    def test_lost_real_brief_ack_has_one_consumption_and_no_retry(self):
        self.shim("'TASK β asymmetric' in a.get('text','')")
        p, packet = self.launch()
        self.assertEqual(p.returncode, 1, p.stderr + p.stdout)
        self.assertEqual(packet["outcome"], "brief_uncertain")
        self.assertTrue(packet["brief_attempted"])
        wait_for(lambda: any(v["event"] == "input" for v in events(self.worker_log)))
        state = self.record(packet["launch_id"])
        self.assertTrue(state["protocol_acknowledged"])
        self.assertNotEqual(state["brief_receipt"]["outcome"], "events_acknowledged")
        p, refusal = self.run_cli("deliver", "--registry", str(self.registry), "--launch-id", state["launch_id"])
        self.assertEqual(p.returncode, 1)
        self.assertIn("already_attempted", refusal["failure_reason"])
        self.assertEqual(len([v for v in events(self.worker_log) if v["event"] == "input"]), 1)
        self.assertEqual(len(self.rpc("session.view", {"session_id": self.session})["windows"]), 2)

    def test_lost_real_creation_ack_preserves_intent_without_hidden_launch_or_retry(self):
        self.shim("'argv' in a")
        p, packet = self.launch()
        self.assertEqual(p.returncode, 1, p.stderr + p.stdout)
        self.assertEqual(packet["outcome"], "creation_uncertain")
        self.assertFalse(packet["tracked"])
        self.assertFalse(packet["brief_attempted"])
        self.assertEqual(len(self.rpc("session.view", {"session_id": self.session})["windows"]), 2)
        self.assertFalse(self.worker_log.exists())
        self.assertIsNone(self.record(packet["launch_id"])["target"]["block_id"])
        jobs = json.loads(subprocess.check_output([BIN, "jobs", "list", "--registry", str(self.registry)], env=self.env))
        self.assertEqual(jobs["entries"], [])

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_INTEGRATION") == "1", "requires combined root boards/targets/jobs relocation")
    def test_integrated_named_local_profile_fleet_seat_and_finished_presentation(self):
        store = self.work / "boards"
        store.mkdir(mode=0o700)
        target = ["--store", str(store), "--host", "disposable", "--socket", str(self.socket),
                  "--session", self.session, "--block", self.starter]
        def root(*args):
            result = subprocess.run([BIN, *args], capture_output=True, text=True, env=self.env, timeout=15)
            return result, json.loads(result.stdout)
        p, _ = root("seat", "register", *target, "--owner", "operator")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.settings["profiles"]["probe"]["argv"][-1] = "exit7"
        # This regression isolates moving the retained agent, without a companion pane.
        self.settings["profiles"]["probe"]["scratch_pane"] = False
        self.config.write_text(json.dumps(self.settings))
        # A named local route must retain its exact Rex pin through the in-pane supervisor's notification.
        poison = self.work / "poison"
        poison.mkdir()
        touched = self.work / "wrong-rex-used"
        wrong = poison / "rex"
        wrong.write_text("#!/bin/sh\ntouch " + shlex.quote(str(touched)) + "\nexit 99\n")
        wrong.chmod(0o755)
        self.env["PATH"] = str(poison) + os.pathsep + self.env["PATH"]
        targets = self.work / "targets.json"
        targets.write_text(json.dumps(dict(schema_version=1, hosts=dict(local=dict(
            host_id="disposable", transport="local", home=str(Path.home()),
            platform="macos-arm64" if sys.platform == "darwin" else "linux-x86_64", socket=str(self.socket),
            rex=str(Path(REX).resolve()), teerex=BIN, store=str(store))))))
        p, packet = root("--config", str(targets), "--host", "local", "spawn", "--profile", "probe", "--profiles",
                         str(self.config), "--brief-file", str(self.brief), "--ack-timeout-ms", "2000")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        launch_id = packet["launch_id"]
        state = wait_for(lambda: self.record(launch_id) if self.record(launch_id).get("fleet_reports", {}).get(
            "child-exit", {}).get("outcome") == "reported" else None)
        self.assertEqual(state["immediate_child_term"], {"Exited": 7})
        self.assertEqual(state["rex_executable"], str(Path(REX).resolve()))
        self.assertFalse(touched.exists())
        self.assertEqual([v for v in events(self.starter_log) if v["event"] == "input"], [])
        p, inbox = root("inbox", "inspect", *target)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual(len(inbox["seat"]["records"]), 1)
        self.assertIn('"Exited": 7', inbox["seat"]["records"][0]["body"])
        p, board = root("boards", "state", "inspect", "--store", str(store))
        fleet = board["state"]["fleet"]
        self.assertEqual(len(fleet), 1)
        self.assertEqual(fleet[0]["owner"], "operator")
        self.assertEqual(fleet[0]["purpose"], "asymmetric lifecycle regression")
        self.assertEqual(fleet[0]["state"], "unknown")
        self.assertIn("PROCESS EXIT", fleet[0]["detail"])
        before = self.rpc("session.view", {"session_id": self.session})
        self.assertEqual(len(before["windows"]), 2)
        def present(focus):
            _, jobs = root("jobs", "list", "--registry", str(self.registry))
            generation = jobs["entries"][0]["generation"]
            return self.run_cli("present", "--registry", str(self.registry), "--launch-id", launch_id, "--owner", "operator",
                                "--generation", str(generation), "--reason", "review retained result", "--anchor", self.starter,
                                "--focus", focus)
        p, refused = present("no")
        self.assertEqual(p.returncode, 1, p.stderr + p.stdout)
        self.assertEqual(refused["presentation"]["receipt"]["failure_reason"], "relocating_focused_source_requires_explicit_focus")
        self.assertEqual(self.rpc("session.view", {"session_id": self.session}), before)
        p, moved = present("yes")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual(moved["outcome"], "presentation_verified")
        after = self.rpc("session.view", {"session_id": self.session})
        self.assertEqual(len(after["windows"]), 1)
        block_ids = [b["block_id"] for layer in after["windows"][0]["layers"] for b in layer["blocks"]]
        self.assertEqual(set(block_ids), {self.starter, state["target"]["block_id"]})
        self.assertEqual(after["windows"][0]["focused_block_id"], state["target"]["block_id"])

    def test_launch_archives_fresh_absent_records_even_below_old_threshold(self):
        launch_id = self.launch()[1]["launch_id"]
        original = self.record(launch_id)
        for i in range(32):
            clone = dict(original, launch_id="%032x" % (i + 1), scratchpad=None)
            clone["target"] = dict(original["target"], block_id="block:00000000-0000-0000-0000-%012d" % i)
            path = self.registry / ("agents-" + clone["launch_id"] + ".json")
            path.write_text(json.dumps(clone))
            path.chmod(0o600)
        p, result = self.launch()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(result["auto_prune"]["retired"], 32)
        # Launch must also prune a single new absent entry, below the old 24-entry threshold.
        clone["launch_id"] = "a" * 32
        path = self.registry / ("agents-" + clone["launch_id"] + ".json")
        path.write_text(json.dumps(clone))
        path.chmod(0o600)
        p, result = self.launch()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(result["auto_prune"]["retired"], 1)

    def test_registry_of_live_panes_grows_past_old_count_limit(self):
        original = self.record(self.launch()[1]["launch_id"])
        for i in range(31):
            clone = dict(original, launch_id="%032x" % (i + 1))
            path = self.registry / ("agents-" + clone["launch_id"] + ".json")
            path.write_text(json.dumps(clone))
            path.chmod(0o600)
        p, result = self.launch()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(result["auto_prune"]["retired"], 0)
        self.assertEqual(len(list(self.registry.glob("agents-*.json"))), 33)

    def test_failed_fleet_store_still_starts_harness_and_submits_brief(self):
        store = self.work / "not-private-boards"
        store.mkdir(mode=0o755)
        self.settings["defaults"]["store"] = str(store)
        p, packet = self.launch()
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertTrue(packet["tracked"])
        self.assertTrue(packet["brief_attempted"])
        self.assertEqual(packet["fleet_report"]["outcome"], "uncertain")
        self.assertTrue(self.worker_log.exists())

    def test_full_fleet_still_starts_child_and_later_reports_are_nonfatal(self):
        store = self.work / "boards"
        store.mkdir(mode=0o700)
        rows = []
        for i in range(128):
            rows.append(dict(target=dict(host="disposable", server="unix://" + str(self.socket),
                             session_id=self.session, block_id="block:00000000-0000-0000-0000-%012d" % i),
                             owner="fixture", purpose="capacity", state="unknown", at=1, detail="fixture"))
        state = store / "state.json"
        state.write_text(json.dumps(dict(schema_version=1, generation=0, seats=[], fleet=rows)))
        state.chmod(0o600)
        self.settings["defaults"]["store"] = str(store)
        p, packet = self.launch()
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertTrue(packet["protocol_acknowledged"])
        self.assertTrue(packet["brief_attempted"])
        report = packet["fleet_report"]
        self.assertEqual(report["outcome"], "uncertain")
        self.assertIn("fleet_capacity_reached", json.dumps(report))
        record = self.record(packet["launch_id"])
        self.assertTrue(Path(record["protocol_file"]).exists())
        self.assertTrue(any(e["event"] == "started" for e in events(self.worker_log)))
        event = self.work / "stop.json"
        event.write_text(json.dumps(dict(hook_event_name="Stop", last_assistant_message="still working")))
        p, notice = self.run_cli("stop", "--registry", str(self.registry), "--launch-id", packet["launch_id"],
                                 "--event-file", str(event))
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual(notice["fleet_report"]["outcome"], "uncertain")

    def test_prune_releases_absent_fleet_rows_but_keeps_retired_live_panes(self):
        store = self.work / "boards"
        store.mkdir(mode=0o700)
        self.settings["defaults"]["store"] = str(store)
        live = self.launch("exit7")[1]["launch_id"]
        gone = self.launch()[1]["launch_id"]
        wait_for(lambda: self.record(live)["immediate_child_term"])
        for launch_id in (live, gone):
            self.backdate(launch_id)
        def close(launch_id, archived=False):
            record = (json.loads((self.registry / "archive" / launch_id / "retired.json").read_text())
                      if archived else self.record(launch_id))
            p = subprocess.run([BIN, "surfaces", "close", "--socket", str(self.socket), "--session", self.session,
                                "--pane", record["target"]["block_id"]], env=self.env, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        close(gone)
        p, result = self.run_cli("prune", "--registry", str(self.registry), "--apply", timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual([r["launch_id"] for r in result["retired"] if r.get("fleet_report", {}).get("outcome") == "cleared"], [gone])
        rows = json.loads((store / "state.json").read_text())["fleet"]
        self.assertEqual(len(rows), 1)
        close(live, archived=True)
        p, result = self.run_cli("prune", "--registry", str(self.registry), "--apply", timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(json.loads((store / "state.json").read_text())["fleet"], [])

    def test_pre_protocol_failure_is_recorded_and_displayed_promptly(self):
        ns = {"__name__": "launch_failure_test", "SCRATCH_LIBRARY": True}
        base = Path(__file__).resolve().parents[1]
        for path in (base / "scratch/scratch.py", base.parent / "src/scoped_channel.py",
                     base / "agents/input_events.py", base / "agents/agents.py"):
            exec(compile(path.read_text(), str(path), "exec"), ns)
        ns["RUNTIME"] = BIN
        original = ns["Registry"].write_message
        def fail_protocol(registry, launch_id, kind, body):
            if kind == "protocol":
                raise OSError("forced protocol write failure")
            return original(registry, launch_id, kind, body)
        ns["Registry"].write_message = fail_protocol
        o = ns["parser"]().parse_args(["launch", "--config", str(self.config), "--profile", "probe"])
        from unittest.mock import patch
        start = time.monotonic()
        with patch.dict(os.environ, self.env), self.assertRaisesRegex(OSError, "forced protocol write failure"):
            ns["launch"](o)
        path = next(self.registry.glob("agents-*.json"))
        launch_id = path.stem[7:]
        record = wait_for(lambda: self.record(launch_id) if self.record(launch_id).get("launch_failure_displayed_at") else None)
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual(record["phase"], "launch_failed")
        self.assertEqual(record["failure_reason"], "forced protocol write failure")
        self.assertFalse(self.worker_log.exists())
        p = subprocess.run([BIN, "observe", "--socket", str(self.socket), "--session", self.session,
                            "--block", record["target"]["block_id"], "--tail"], env=self.env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        capture = json.loads(p.stdout)["capture"]["content"]
        self.assertEqual(capture.count("teerex: launch failed before the agent started:"), 1)
        self.assertIn("forced protocol write failure", capture)
        self.assertIn(launch_id, capture)

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_SSH") == "1", "explicit isolated Linux SSH compute acceptance gate")
    def test_isolated_ssh_compute_ack_protocol_hooks_and_measured_exit(self):
        self.assertEqual(sys.platform, "linux")
        for executable in ("/usr/sbin/sshd", "/usr/bin/bwrap", "/usr/bin/ssh-keygen"):
            self.assertTrue(Path(executable).exists(), executable)
        import getpass
        compute = self.work / "compute"
        compute.mkdir(mode=0o700)
        (self.work / "boards").mkdir(mode=0o700)
        # Two actual SSH endpoints: compute runs in a separate mount namespace; registry remains outside it.
        key = self.work / "client-key"
        host_key = self.work / "host-key"
        for path in (key, host_key):
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(path)], check=True)
        authorized = self.work / "authorized_keys"
        authorized.write_text(key.with_suffix(".pub").read_text())
        authorized.chmod(0o600)
        ports = []
        for unused in range(2):
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                ports.append(s.getsockname()[1])
        force = self.work / "compute-shell"
        force.write_text("#!/usr/bin/python3\nimport os\nfrom pathlib import Path\n" +
                         "cmd=['bwrap','--die-with-parent']\n" +
                         "for p in ['/usr','/bin','/sbin','/lib','/lib64','/etc']:\n" +
                         " if Path(p).exists(): cmd+=['--ro-bind',p,p]\n" +
                         "cmd+=['--dev','/dev','--proc','/proc','--tmpfs','/tmp','--tmpfs','/run','--tmpfs','/var']\n" +
                         f"cmd+=['--ro-bind',{sys.prefix!r},{sys.prefix!r}]\n" +
                         f"cmd+=['--ro-bind',{BIN!r},\"/opt/teerex cli's\",'--bind',{str(compute)!r},'/work']\n" +
                         "os.execvp('bwrap',cmd+['--chdir','/work','--','/bin/sh','-c',os.environ['SSH_ORIGINAL_COMMAND']])\n")
        force.chmod(0o700)
        logs = []
        for i, port in enumerate(ports):
            ssh_config = self.work / ("sshd-" + str(i))
            ssh_config.write_text(f"Port {port}\nListenAddress 127.0.0.1\nHostKey {host_key}\n"
                                  f"AuthorizedKeysFile {authorized}\nPidFile {self.work / ('sshd-'+str(i)+'.pid')}\n"
                                  "StrictModes no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nUsePAM no\n"
                                  f"AllowUsers {getpass.getuser()}\nAllowTcpForwarding no\nAllowStreamLocalForwarding no\n"
                                  + (f"ForceCommand {force}\n" if i == 0 else ""))
            log = (self.work / ("sshd-" + str(i) + ".log")).open("w+")
            self.addCleanup(log.close)
            logs.append(log)
            server = subprocess.Popen(["/usr/sbin/sshd", "-D", "-e", "-f", str(ssh_config)], stdout=log, stderr=log)
            self.addCleanup(lambda p=server: (p.terminate(), p.wait(timeout=5)) if p.poll() is None else None)
            def ready():
                if server.poll() is not None:
                    log.seek(0)
                    self.fail(log.read())
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=.1):
                        return True
                except OSError:
                    return False
            wait_for(ready)
        known = self.work / "known-hosts"
        public = " ".join(host_key.with_suffix(".pub").read_text().split()[:2])
        known.write_text("".join(f"[127.0.0.1]:{p} {public}\n" for p in ports))
        shutil.copy(key, compute / "identity")
        shutil.copy(known, compute / "known-hosts")
        (compute / "fixture.py").write_text(FIXTURE)
        def host(port, binary, socket_path, config_key, known_path):
            return dict(host_id="disposable", transport="ssh", address=getpass.getuser()+"@127.0.0.1", port=port,
                        known_hosts=known_path, identity_file=config_key, home="/work", platform="linux-x86_64",
                        socket=socket_path, rex=str(Path(REX).resolve()), teerex=binary, store=str(self.work / "boards"))
        targets = self.work / "compute-targets.json"
        targets.write_text(json.dumps(dict(schema_version=1, hosts=dict(compute=host(ports[0], "/opt/teerex cli's",
                                            "/run/absent-rex.sock", str(key), str(known))))))
        (compute / "callbacks route.json").write_text(json.dumps(dict(schema_version=1, hosts=dict(registry=host(
            ports[1], BIN, str(self.socket), "/work/identity", "/work/known-hosts")))))
        report_log = self.work / "remote-report-to.jsonl"
        target = self.rpc("session.new_window", dict(session_id=self.session, focus=False, layout=dict(block=dict(
            flavor="com.superlogical.terminal.shell", options=dict(command=[sys.executable, str(self.fixture), str(report_log), "noack"],
                                                                  exit=dict(on_completion=False))))))
        report_block = target["block_ids"][0]
        wait_for(lambda: events(report_log))
        self.settings["defaults"].update(report_to_session=self.session, report_to_block=report_block)
        literal_args = ["", "two words", "line\nbreak", "'$;`\" β"]
        self.settings["profiles"]["probe"].update(argv=[sys.executable, "/work/fixture.py", "/work/worker.jsonl", "remote-exit7", *literal_args],
            harness="claude", hook_events=True, execution=dict(config=str(targets), host="compute", cwd="/work"),
            callbacks=dict(config="/work/callbacks route.json", host="registry"))
        self.enable_channel()
        self.config.write_text(json.dumps(self.settings))
        before = self.rpc("session.view", dict(session_id=self.session))
        p, refusal = self.run_cli("launch", "--config", str(self.config), "--profile", "probe")
        self.assertEqual(p.returncode, 1)
        self.assertIn("remote_fenced_delivery_not_yet_supported", refusal["failure_reason"])
        self.assertEqual(self.rpc("session.view", dict(session_id=self.session)), before)
        self.settings["profiles"]["probe"].pop("delivery")
        self.config.write_text(json.dumps(self.settings))
        p, packet = self.run_cli("launch", "--config", str(self.config), "--profile", "probe", "--brief-file", str(self.brief),
                                 "--ack-timeout-ms", "6000")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        launch_id = packet["launch_id"]
        worker = compute / "worker.jsonl"
        wait_for(lambda: len([v for v in events(worker) if v["event"] == "remote-hook"]) == 2)
        started = events(worker)[0]
        self.assertFalse(started["registry_present"], "compute accidentally shares the pane-host registry")
        self.assertTrue(started["stdin_tty"])
        self.assertEqual(started["cwd"], "/work")
        self.assertEqual(started["argv"][:len(literal_args)], literal_args)
        self.assertEqual([v["code"] for v in events(worker) if v["event"] == "wrong-ack"], [1, 1])
        self.assertEqual([v["code"] for v in events(worker) if v["event"] == "ack"], [0])
        self.assertEqual([v["code"] for v in events(worker) if v["event"] == "remote-hook"], [0, 0])
        wait_for(lambda: [v for v in events(worker) if v["event"] == "remote-reply"])
        self.assertEqual([v["code"] for v in events(worker) if v["event"] == "remote-reply"], [0])
        self.assertEqual([v["payload"] for v in events(worker) if v["event"] == "input"], ["FROM probe: " + self.brief.read_text()])
        state = wait_for(lambda: self.record(launch_id) if self.record(launch_id).get("notifications", {}).get(
            "child-exit", {}).get("outcome") == "transport_acknowledged" else None)
        self.assertEqual(state["remote_child_term"], {"Exited": 7})
        self.assertEqual(state["immediate_child_term"], {"Exited": 7})
        self.assertEqual(state["last_hook"]["kind"], "StopFailure")
        for destination_log in (self.starter_log, report_log):
            count = 3 if destination_log == self.starter_log else 4
            notices = wait_for(lambda: [v["payload"] for v in events(destination_log) if v["event"] == "input"]
                               if len([v for v in events(destination_log) if v["event"] == "input"]) == count else None)
            self.assertIn("remote transcript β '\"", notices[0])
            self.assertIn("remote failure β", notices[1])
            self.assertIn('Remote child: {"Exited": 7}', notices[-1])
            self.assertIn("SSH transport:", notices[-1])
            if destination_log == report_log:
                self.assertEqual(notices[2], "FROM probe: remote direct reply β\n\n")
        # Stored protocol and compute protocol differ only in their explicitly routed command lines.
        protocol = [v["payload"] for v in events(worker) if v["event"] == "protocol_argument"][0]
        saved = Path(state["protocol_file"]).read_text()
        def without_routes(value):
            for marker in ("Acknowledge this protocol now by running:\n", "Supply report bytes on stdin then EOF using:\n"):
                before, after = value.split(marker)
                value = before + marker + "ROUTING_COMMAND\n" + after.split("\n", 1)[1]
            return value
        self.assertEqual(without_routes(protocol), without_routes(saved))
        self.assertIn("--config '/work/callbacks route.json' --host registry agents ack", protocol)
        # A later explicit ACK can continue once; timeout never submits the brief by itself.
        profile = self.settings["profiles"]["probe"]
        profile["argv"] = [sys.executable, "/work/fixture.py", "/work/late.jsonl", "lateack"]
        profile["hook_events"] = False
        self.config.write_text(json.dumps(self.settings))
        p, late = self.run_cli("launch", "--config", str(self.config), "--profile", "probe", "--brief-file", str(self.brief),
                               "--ack-timeout-ms", "200")
        self.assertEqual(p.returncode, 124, p.stderr + p.stdout)
        self.assertFalse(late["brief_attempted"])
        wait_for(lambda: self.record(late["launch_id"])["protocol_acknowledged"])
        self.assertEqual([v for v in events(compute / "late.jsonl") if v["event"] == "input"], [])
        p, result = self.run_cli("deliver", "--registry", str(self.registry), "--launch-id", late["launch_id"])
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        wait_for(lambda: [v for v in events(compute / "late.jsonl") if v["event"] == "input"])
        p, result = self.run_cli("deliver", "--registry", str(self.registry), "--launch-id", late["launch_id"])
        self.assertEqual(p.returncode, 1)
        self.assertEqual(len([v for v in events(compute / "late.jsonl") if v["event"] == "input"]), 1)
        # Lose the measured-exit callback: even a terminating SSH result must leave remote evidence unknown.
        (compute / "known-hosts").write_text("")
        os.kill(events(compute / "late.jsonl")[0]["pid"], signal.SIGTERM)
        state = wait_for(lambda: self.record(late["launch_id"]) if self.record(late["launch_id"])[
            "notifications"].get("child-exit", {}).get("outcome") == "transport_acknowledged" else None)
        self.assertIsNone(state["remote_child_term"])
        self.assertEqual(state["immediate_child_term"], {"Exited": 143})
        last_notice = [v["payload"] for v in events(self.starter_log) if v["event"] == "input"][-1]
        self.assertIn("Remote child: unknown; no measured exit callback", last_notice)
        # A refused new compute connection cannot ACK or submit a brief, and is not remote-death evidence.
        route = json.loads(targets.read_text())
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            route["hosts"]["compute"]["port"] = s.getsockname()[1]
        targets.write_text(json.dumps(route))
        p, failure = self.run_cli("launch", "--config", str(self.config), "--profile", "probe", "--brief-file", str(self.brief),
                                  "--ack-timeout-ms", "3000")
        self.assertEqual(p.returncode, 1, p.stderr + p.stdout)
        self.assertEqual(failure["outcome"], "child_exited_before_ack")
        self.assertFalse(failure["brief_attempted"])
        self.assertIsNone(failure["remote_child_term"])
        self.assertEqual(failure["immediate_child_term"], {"Exited": 255})

    def probe_record(self, config, folder=None):
        folder = folder or self.work
        template, protected = folder / "template.json", folder / "protect.json"
        template.write_text(json.dumps(dict(schema_version=1, **config)))
        template.chmod(0o600)
        result, packet = self.run_cli("fence-probe", "--record-identities", "--protect-file", str(template), "--out", str(protected))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(packet["passed"])
        self.assertEqual(protected.stat().st_mode & 0o777, 0o600)
        return protected

    def probe_fence(self, scratch, *, pid=True, session=True):
        command = ["bwrap", "--die-with-parent"]
        if pid:
            command += ["--unshare-pid"]
        if session:
            command += ["--new-session"]
        for path in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc"):
            if Path(path).exists():
                command += ["--ro-bind", path, path]
        command += ["--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", "/run", "--tmpfs", "/var",
                          "--ro-bind", sys.prefix, sys.prefix, "--ro-bind", BIN, BIN,
                          "--bind", str(scratch), "/work", "--chdir", "/work"]
        if (scratch / "protect.json").exists():
            command += ["--ro-bind", str(scratch / "protect.json"), "/work/protect.json"]
        return command

    def probe_evidence(self, argv, **kwargs):
        evidence = self.work / ("evidence-" + str(time.monotonic_ns()))
        fd = os.open(evidence, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            offset = argv.index("--then") if "--then" in argv else len(argv)
            command = argv[:offset] + ["--evidence-fd", str(fd)] + argv[offset:]
            command = [str(fd) if arg == "EVIDENCE_FD" else arg for arg in command]
            result = subprocess.run(command, pass_fds=(fd,), capture_output=True, text=True, timeout=10, **kwargs)
        finally:
            os.close(fd)
        return result, json.loads(evidence.read_text())

    def test_fence_probe_evidence_private_then_output_refusal_and_call_log(self):
        self.env["TEEREX_CALL_LOG_DIR"] = str(self.work / "calls")
        secret = self.work / "PROTECTED_PATH_MUST_NOT_APPEAR"
        protected = self.probe_record(dict(absent_paths=[str(secret)]))
        harness = """import errno,json,os,sys
fd=int(sys.argv[1])
try:os.fstat(fd)
except OSError as exc:assert exc.errno==errno.EBADF
else:raise AssertionError('evidence descriptor survived exec')
if sys.platform=='linux':
 assert not os.path.exists('/proc/self/fd/'+str(fd))
print('HARNESS ONLY')
"""
        args = [BIN, "agents", "fence-probe", "--protect-file", str(protected), "--then", "--",
                sys.executable, "-c", harness, "EVIDENCE_FD"]
        passed, evidence = self.probe_evidence(args, env=self.env)
        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
        self.assertEqual(passed.stdout, "HARNESS ONLY\n")
        self.assertEqual(passed.stderr, "")
        self.assertTrue(evidence["passed"])
        self.assertEqual(evidence["exec"], "started")
        self.assertEqual(evidence["checks"][0]["target"], str(secret))
        secret.touch()
        failed, evidence = self.probe_evidence(args, env=self.env)
        self.assertEqual(failed.returncode, 1)
        self.assertEqual(failed.stdout, "")
        self.assertEqual(failed.stderr, "teerex agents fence-probe: refused: absent_path\n")
        self.assertFalse(evidence["passed"])
        self.assertEqual(evidence["exec"], "not_started")
        self.assertEqual(evidence["checks"][0]["target"], str(secret))
        diagnostic, evidence = self.probe_evidence(args[:5], env=self.env)
        self.assertEqual(diagnostic.returncode, 1)
        self.assertEqual(json.loads(diagnostic.stdout), evidence)
        # The native logger writes selected flag names/canonical IDs only; the probe
        # intentionally bypasses the Python call-log wrapper inside the fence.
        logs = list((self.work / "calls").glob("*.jsonl"))
        self.assertTrue(logs)
        logged = "".join(path.read_text() for path in logs)
        for private in (str(secret), str(protected), "PROTECTED_PATH_MUST_NOT_APPEAR", "st_ino", "HARNESS ONLY"):
            self.assertNotIn(private, logged)

    def test_fence_probe_bad_evidence_fd_precedes_checks_and_errors_are_path_free(self):
        missing = self.work / "PRIVATE_MISSING_PROTECT_FILE"
        base = [BIN, "agents", "fence-probe", "--protect-file", str(missing)]
        pipe_r, pipe_w = os.pipe()
        readonly = os.open(self.brief, os.O_RDONLY)
        directory = os.open(self.work, os.O_RDONLY)
        with socket.socket() as sock:
            try:
                for fd in (-1, 1, 999999, readonly, directory, pipe_w, sock.fileno()):
                    with self.subTest(fd=fd):
                        inherited = (fd,) if fd in (readonly, directory, pipe_w, sock.fileno()) else ()
                        result = subprocess.run(base + ["--evidence-fd", str(fd), "--then", "--", "/bin/echo", "UNEXPECTED"],
                                                pass_fds=inherited, env=self.env, capture_output=True, text=True)
                        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                        self.assertEqual(result.stdout, "")
                        self.assertEqual(result.stderr, "teerex agents fence-probe: refused: invalid_evidence_fd\n")
            finally:
                for fd in (pipe_r, pipe_w, readonly, directory):os.close(fd)
        invalid, evidence = self.probe_evidence(base + ["--then", "--", "/bin/echo", "UNEXPECTED"], env=self.env)
        self.assertEqual(invalid.returncode, 3)
        self.assertEqual(invalid.stdout, "")
        self.assertEqual(invalid.stderr, "teerex agents fence-probe: refused: invalid_protect_file\n")
        self.assertIn(str(missing), evidence["failure_reason"])
        protected = self.probe_record({})
        failed, evidence = self.probe_evidence([BIN, "agents", "fence-probe", "--protect-file", str(protected),
                                               "--then", "--", str(missing)], env=self.env)
        self.assertEqual(failed.returncode, 1)
        self.assertEqual(failed.stdout, "")
        self.assertEqual(failed.stderr, "teerex agents fence-probe: refused: exec_failed\n")
        malformed = json.loads(protected.read_text())
        malformed["required_paths"] = ["/PRIVATE_" + chr(0xd800)]
        protected.write_text(json.dumps(malformed))
        failed, evidence = self.probe_evidence([BIN, "agents", "fence-probe", "--protect-file", str(protected),
                                               "--then", "--", "/bin/echo", "UNEXPECTED"], env=self.env)
        self.assertEqual(failed.returncode, 1)
        self.assertEqual(failed.stdout, "")
        self.assertEqual(failed.stderr, "teerex agents fence-probe: refused: check_failed\n")
        self.assertEqual(evidence["exec"], "not_started")

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_FENCE") == "1", "explicit real Linux bubblewrap acceptance gate")
    def test_fence_probe_private_schema_and_recording_fail_closed(self):
        template = self.work / "template.json"
        protected = self.work / "protect.json"
        valid = dict(schema_version=1, absent_paths=[str(self.registry)])
        for value in (dict(valid, extra=True), dict(valid, absent_paths=["relative"]),
                      dict(valid, absent_paths=["/x"] * 65), dict(valid, closed_tcp=["8.8.8.8:53"]),
                      dict(valid, readonly_paths=[]), dict(valid, require_pid_namespace=1),
                      dict(valid, host_identities={"absent_paths": {str(self.registry): {"st_dev": True, "st_ino": 1}}})):
            template.write_text(json.dumps(value)); template.chmod(0o600)
            result, packet = self.run_cli("fence-probe", "--protect-file", str(template))
            self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
            self.assertEqual(packet["exec"], "not_started")
        for raw, mode in ((b"x" * 65537, 0o600), (b'{"schema_version":1,"schema_version":1}', 0o600),
                          (json.dumps(valid).encode(), 0o644)):
            template.write_bytes(raw); template.chmod(mode)
            self.assertEqual(self.run_cli("fence-probe", "--protect-file", str(template))[0].returncode, 3)
        self.assertEqual(self.run_cli("fence-probe", "--protect-file", str(self.work / "missing"))[0].returncode, 3)
        template.write_text(json.dumps(valid)); template.chmod(0o600)
        link = self.work / "symlink"
        link.symlink_to(template)
        self.assertEqual(self.run_cli("fence-probe", "--protect-file", str(link))[0].returncode, 3)
        for args in (("--then",), ("--then", "--"), ("--out", str(protected)), ("--record-identities",)):
            self.assertEqual(self.run_cli("fence-probe", "--protect-file", str(template), *args)[0].returncode, 2)
        self.probe_record(dict(absent_paths=[str(self.registry)]))
        self.assertEqual(self.run_cli("fence-probe", "--record-identities", "--protect-file", str(template), "--out", str(protected))[0].returncode, 3)

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_FENCE") == "1", "explicit real Linux bubblewrap acceptance gate")
    def test_fence_probe_host_identity_shadow_socket_proc_and_exec(self):
        scratch = self.work / "fenced"
        scratch.mkdir()
        credential = self.work / "synthetic-sign-in"
        credential.write_text("synthetic fixture only")
        copy = scratch / "copy"
        copy.write_text(credential.read_text())
        protected_dirs = [self.registry]
        for name in ("boards", "jobs", "outbox"):
            path = self.work / name
            path.mkdir()
            protected_dirs.append(path)
        outside_proc = f"/proc/{self.server.pid}/root{self.socket}"
        channel = self.root / ("probe-channel-" + scratch.parent.name)
        channel.mkdir(mode=0o700)
        channel_socket = channel / "channel.sock"
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(str(channel_socket)); listener.listen(4); listener.settimeout(2)
            protected = self.probe_record(dict(absent_paths=[str(self.socket), outside_proc, str(credential), *map(str, protected_dirs)],
                                               required_paths=[str(channel_socket)], require_pid_namespace=True, require_new_session=True), scratch)
            with socket.socket(socket.AF_UNIX) as direct:
                direct.connect(str(self.socket))  # A1 counterexample: this is a real reachable disposable Rex.
            outside, packet = self.run_cli("fence-probe", "--protect-file", str(protected))
            self.assertEqual(outside.returncode, 1)
            self.assertFalse(packet["passed"])
            self.assertEqual(packet["exec"], "not_started")
            listener.accept()[0].close()
            marker = scratch / "marker"
            harness = ("import errno,os,json,socket\nfrom pathlib import Path\n" +
                       "for descriptor in Path('/proc/self/fd').iterdir():\n" +
                       " try:link=os.readlink(descriptor)\n" +
                       " except FileNotFoundError:continue\n" +
                       " assert 'evidence-' not in link,'evidence file survived exec'\n" +
                       f"for path in {[str(self.socket), outside_proc]!r}:\n" +
                       " assert not Path(path).is_socket()\n" +
                       " with socket.socket(socket.AF_UNIX) as connection:\n" +
                       "  try:connection.connect(path)\n" +
                       "  except OSError as e:assert e.errno in (errno.ENOENT,errno.EACCES),e\n" +
                       "  else:raise AssertionError('host socket reachable')\n" +
                       "Path('/work/marker').write_text(str(os.getpid()));print(json.dumps(dict(harness_pid=os.getpid())))")
            base = self.probe_fence(scratch) + ["--ro-bind", str(channel), str(channel)]
            args = [BIN, "agents", "fence-probe", "--protect-file", "/work/protect.json", "--then", "--", sys.executable, "-c", harness]
            # A11 counterexample: deliberately expose the host identity, even read-only.
            bad, evidence = self.probe_evidence(base + ["--ro-bind", str(credential), str(credential), "--", *args])
            self.assertEqual(bad.returncode, 1, bad.stdout + bad.stderr)
            self.assertTrue(bad.stderr.startswith("teerex agents fence-probe: refused:"))
            self.assertEqual(bad.stdout, "")
            self.assertNotIn(str(credential), bad.stderr)
            self.assertEqual(evidence["exec"], "not_started")
            self.assertFalse(marker.exists())
            listener.accept()[0].close()
            # A writable per-call copy is explicitly allowed, despite occupying the protected path.
            good, probe = self.probe_evidence(base + ["--bind", str(copy), str(credential), "--", *args])
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
            harness_result = json.loads(good.stdout)
            self.assertTrue(probe["passed"])
            self.assertEqual(probe["exec"], "started")
            self.assertTrue(any(c.get("state") == "shadowed" and c["target"] == str(credential) for c in probe["checks"]))
            self.assertEqual(int(marker.read_text()), harness_result["harness_pid"])
            listener.accept()[0].close()
            # Record the PID before exec from the same in-fence launcher, then compare after exec.
            wrapped = f"import os;from pathlib import Path;Path('/work/before').write_text(str(os.getpid()));os.execv({BIN!r},{args!r})"
            same = subprocess.run(base + ["--", sys.executable, "-c", wrapped], capture_output=True, text=True, timeout=10)
            self.assertEqual(same.returncode, 0, same.stdout + same.stderr)
            self.assertEqual((scratch / "before").read_text(), marker.read_text())
            listener.accept()[0].close()

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_FENCE") == "1", "explicit real Linux bubblewrap acceptance gate")
    def test_fence_probe_pid_namespace_signal_and_descendant_containment(self):
        scratch = self.work / "pid-fence"
        scratch.mkdir()
        self.probe_record(dict(require_pid_namespace=True), scratch)
        tag = "teerex-probe-descendant-" + str(time.monotonic_ns())
        descendant = "import os,time;from pathlib import Path;os.setsid();Path('/work/descendant-ready').touch();time.sleep(120)"
        harness = f'''import errno,json,os,subprocess,time
from pathlib import Path
try:os.kill({self.server.pid},0); outside_signal=True
except ProcessLookupError:outside_signal=False
p=subprocess.Popen([{sys.executable!r},'-c',{descendant!r},{tag!r}],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL)
for i in range(100):
 if Path('/work/descendant-ready').exists():break
 time.sleep(.02)
assert Path('/work/descendant-ready').exists()
Path('/work/descendant-namespace').write_text(os.readlink('/proc/self/ns/pid'))
print(json.dumps(dict(outside_signal=outside_signal)))
'''
        args = [BIN, "agents", "fence-probe", "--protect-file", "/work/protect.json", "--then", "--", sys.executable, "-c", harness]
        result = subprocess.run(self.probe_fence(scratch) + ["--", *args], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(json.loads(result.stdout)["outside_signal"])
        namespace = (scratch / "descendant-namespace").read_text()
        def tagged():
            found = []
            for path in Path('/proc').glob('[0-9]*/cmdline'):
                try:
                    if tag.encode() in path.read_bytes().split(b'\0'):found.append(int(path.parent.name))
                except (FileNotFoundError, ProcessLookupError):pass
            return found
        # bwrap can return while the kernel is still tearing down its PID namespace.
        # A process disappearing between /proc reads is gone, not an escaped child.
        # Live tagged children in any other namespace must fail immediately.
        deadline = time.monotonic() + 3
        while True:
            descendants = tagged()
            for pid in descendants:
                try:
                    actual = os.readlink(f'/proc/{pid}/ns/pid')
                except (FileNotFoundError, ProcessLookupError):
                    continue
                self.assertEqual(actual, namespace, f"tagged descendant PID {pid} escaped its PID namespace")
            remaining = []
            for path in Path('/proc').glob('[0-9]*/ns/pid'):
                try:
                    if os.readlink(path) == namespace:remaining.append(str(path))
                except (FileNotFoundError, ProcessLookupError, PermissionError):pass  # another user's process is not in our namespace
            if not descendants and not remaining:
                break
            self.assertLess(time.monotonic(), deadline,
                            f"PID namespace teardown timed out: tagged={descendants}, members={remaining}")
            time.sleep(.02)
        # A6/A11 counterexample: without PID isolation the probe blocks the harness.
        refused = subprocess.run(self.probe_fence(scratch, pid=False) + ["--", *args], capture_output=True, text=True, timeout=10)
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        # A5/A6 control deliberately omits the probe too, exposing the containment difference.
        (scratch / 'descendant-ready').unlink()
        try:
            control = subprocess.run(self.probe_fence(scratch, pid=False) + ["--", sys.executable, "-c", harness], capture_output=True, text=True, timeout=10)
            self.assertEqual(control.returncode, 0, control.stdout + control.stderr)
            self.assertTrue(json.loads(control.stdout)["outside_signal"])
            self.assertEqual(len(tagged()), 1)
        finally:
            for pid in tagged():os.kill(pid, signal.SIGKILL)

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_FENCE") == "1", "explicit real Linux bubblewrap acceptance gate")
    def test_fence_probe_disposable_tty_session_and_tiocsti(self):
        import pty
        import termios
        scratch = self.work / "tty-fence"
        scratch.mkdir()
        self.probe_record(dict(require_new_session=True), scratch)
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        def disposable(command):
            def attach():
                os.setsid()
                fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
            return subprocess.run(command, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  text=True, preexec_fn=attach, timeout=10)
        args = [BIN, "agents", "fence-probe", "--protect-file", "/work/protect.json"]
        good = disposable(self.probe_fence(scratch) + ["--", *args])
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.assertEqual(json.loads(good.stdout)["checks"][0]["errno"], errno.ENXIO)
        control = disposable(self.probe_fence(scratch, session=False) + ["--", *args])
        self.assertEqual(control.returncode, 1, control.stdout + control.stderr)
        inject = """import fcntl,json,os,select,termios,tty
fd=os.open('/dev/tty',os.O_RDWR);tty.setraw(fd)
try:
 fcntl.ioctl(fd,termios.TIOCSTI,b'z')
 readable=select.select([fd],[],[],1)[0]
 print(json.dumps(dict(injected=os.read(fd,1).decode() if readable else None)))
except OSError as e:print(json.dumps(dict(kernel_errno=e.errno)))
"""
        attempt = disposable(self.probe_fence(scratch, session=False) + ["--", sys.executable, "-c", inject])
        self.assertEqual(attempt.returncode, 0, attempt.stdout + attempt.stderr)
        evidence = json.loads(attempt.stdout)
        print("Disposable PTY TIOCSTI control:", json.dumps(evidence), flush=True)
        # Modern kernels may independently prohibit TIOCSTI; never relax that protection.
        self.assertTrue(evidence.get("injected") == "z" or evidence.get("kernel_errno") in (errno.EIO, errno.EPERM), evidence)

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_FENCE") == "1" and os.environ.get("TEEREX_AGENTS_FENCE_EGRESS") == "1",
                         "explicit real egress gate: slirp4netns joining the fence netns plus public HTTPS (hive; hosted runners restrict both)")
    def test_fence_probe_closed_loopback_with_real_egress_and_host_counterexample(self):
        import select
        self.assertIsNotNone(shutil.which("slirp4netns"))
        scratch = self.work / "network-fence"
        scratch.mkdir()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen(4)
            port = listener.getsockname()[1]
            self.probe_record(dict(closed_tcp=["127.0.0.1:" + str(port)]), scratch)
            marker = scratch / "network-harness"
            probe = [BIN, "agents", "fence-probe", "--protect-file", "/work/protect.json", "--then", "--"]
            refused = subprocess.run(self.probe_fence(scratch) + ["--", *probe, sys.executable, "-c",
                                    "from pathlib import Path;Path('/work/network-harness').touch()"], capture_output=True, text=True, timeout=10)
            self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
            self.assertFalse(marker.exists())
            self.assertEqual(refused.stdout, "")
            self.assertEqual(refused.stderr.strip(), "teerex agents fence-probe: refused: closed_tcp")
            resolver = scratch / "resolv.conf"
            resolver.write_text("nameserver 10.0.2.3\n")
            harness = """import json,socket,ssl
from pathlib import Path
with socket.create_connection(('api.openai.com',443),timeout=15) as tcp:
 with ssl.create_default_context().wrap_socket(tcp,server_hostname='api.openai.com') as tls:
  tls.sendall(b'HEAD / HTTP/1.1\\r\\nHost: api.openai.com\\r\\nConnection: close\\r\\n\\r\\n')
  status=tls.recv(1024).split(b'\\r\\n',1)[0].decode()
  assert status.startswith('HTTP/1.1 '),status
  print(json.dumps(dict(public_https=status)))
Path('/work/network-harness').touch()
"""
            # Test fixture only: configure egress before releasing the fenced probe/harness.
            # No helper daemon, DNS forwarder or host network policy is installed.
            info_r, info_w = os.pipe()
            block_r, block_w = os.pipe()
            ready_r, ready_w = os.pipe()
            exit_r, exit_w = os.pipe()
            descriptors = [info_r, info_w, block_r, block_w, ready_r, ready_w, exit_r, exit_w]
            process = slirp = None
            try:
                command = self.probe_fence(scratch) + ["--unshare-net", "--info-fd", str(info_w), "--block-fd", str(block_r),
                            "--ro-bind", str(resolver), "/run/systemd/resolve/stub-resolv.conf", "--", *probe, sys.executable, "-c", harness]
                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, pass_fds=(info_w, block_r))
                raw = b""
                while b"}" not in raw:
                    self.assertTrue(select.select([info_r], [], [], 10)[0], "bubblewrap did not publish its child identity")
                    part = os.read(info_r, 4096)
                    self.assertTrue(part, "missing bubblewrap child identity")
                    raw += part
                child_pid = json.loads(raw)["child-pid"]
                slirp = subprocess.Popen(["slirp4netns", "--configure", "--disable-host-loopback", "--mtu", "65520",
                                          "--ready-fd", str(ready_w), "--exit-fd", str(exit_r), str(child_pid), "tap0"],
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, pass_fds=(ready_w, exit_r))
                self.assertTrue(select.select([ready_r], [], [], 10)[0], "slirp did not become ready")
                self.assertTrue(os.read(ready_r, 1))
                os.write(block_w, b"1")
                stdout, stderr = process.communicate(timeout=35)
                self.assertEqual(process.returncode, 0, stdout + stderr)
                https = json.loads(stdout)
                self.assertTrue(marker.exists())
                self.assertTrue(https["public_https"].startswith("HTTP/1.1 "))
            finally:
                for descriptor in descriptors:
                    os.close(descriptor)
                for child in (process, slirp):
                    if child is not None:
                        if child.poll() is None:
                            child.terminate()
                        try:child.communicate(timeout=5)
                        except subprocess.TimeoutExpired:
                            child.kill();child.communicate(timeout=5)

    def enable_channel(self, count=32, lifetime=60000):
        self.delivery = self.work / "delivery"
        self.delivery.mkdir(mode=0o700)
        self.settings["profiles"]["probe"]["delivery"] = dict(directory=str(self.delivery), grants=["send", "ack", "stop"],
                                                                  max_requests=count, lifetime_ms=lifetime)

    def channel_cli(self, launch_id, *args, request_id="c" * 32, **kwargs):
        return self.run_cli("channel", "--handle", str(self.delivery / launch_id / "handle.json"),
                            "--request-id", request_id, *args, **kwargs)

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_FENCE") == "1", "explicit real Linux bubblewrap acceptance gate")
    def test_real_fence_denies_rex_and_registry_but_scoped_ack_send_stop_work(self):
        self.assertEqual(sys.platform, "linux")
        self.assertIsNotNone(shutil.which("bwrap"))
        self.enable_channel()
        fenced = self.work / "fenced"
        fenced.mkdir()
        self.probe_record(dict(absent_paths=[str(self.socket), str(self.registry)],
                               require_pid_namespace=True, require_new_session=True), fenced)
        self.worker_log = fenced / "worker.jsonl"
        wrapper = self.work / "fence.py"
        # Rivet's bwrap adapter mounts only toolchain/cwd/declared extra paths; /tmp and /run are masked.
        # Match that contract, with ONLY this launch's channel mounted, never registry/store/Rex socket.
        denial_probe = ("import os,socket,json\nfrom pathlib import Path\n"
                        f"paths={dict(rex=str(self.socket), registry=str(self.registry))!r}\nresults={{}}\n"
                        "for k,p in paths.items():\n"
                        " try:\n"
                        "  socket.socket(socket.AF_UNIX).connect(p) if k=='rex' else os.open(p,os.O_RDONLY)\n"
                        "  results[k]=False\n"
                        " except OSError: results[k]=True\n"
                        "Path('/work/denial.json').write_text(json.dumps(results))\n")
        exiting_fixture = FIXTURE.replace('behavior in ("exit7", "remote-exit7")',
                                          'behavior in ("exit7", "remote-exit7", "channel")')
        wrapper.write_text("import json,os,subprocess,sys\nfrom pathlib import Path\n" +
                           "cmd=['bwrap','--die-with-parent','--unshare-pid','--new-session']\n" +
                           "for p in ['/usr','/bin','/sbin','/lib','/lib64','/etc']:\n" +
                           " if Path(p).exists(): cmd+=['--ro-bind',p,p]\n" +
                           "cmd+=['--dev','/dev','--proc','/proc','--tmpfs','/tmp','--tmpfs','/run','--tmpfs','/var']\n" +
                           f"cmd+=['--ro-bind',{sys.prefix!r},{sys.prefix!r}]\n" +
                           f"cmd+=['--ro-bind',{BIN!r},{BIN!r},'--bind',{str(fenced)!r},'/work']\n" +
                           "channel=str(Path(os.environ['AGENT_CHANNEL']).parent)\ncmd+=['--ro-bind',channel,channel]\n" +
                           f"protect=Path({str(fenced / 'protect.json')!r})\n" +
                           "config=json.loads(protect.read_text());config['required_paths']=[str(Path(channel)/'channel.sock')]\n" +
                           "protect.write_text(json.dumps(config))\ncmd += ['--ro-bind',str(protect),'/work/protect.json']\n" +
                           f"probe={denial_probe!r}\n" +
                           f"code=probe+{exiting_fixture!r}\n" +
                           f"os.execvp('bwrap',cmd+['--chdir','/work','--',{BIN!r},'agents','fence-probe','--protect-file','/work/protect.json','--then','--',{sys.executable!r},'-c',code,'/work/worker.jsonl','channel',*sys.argv[2:]])\n")
        self.settings["profiles"]["probe"].update(argv=[sys.executable, str(wrapper), "channel"], standing_flags=[],
                                                   harness="claude", hook_events=True)
        p, packet = self.launch("channel", ack_timeout=4000)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout + "\n" + str(packet))
        launch_id = packet["launch_id"]
        results = wait_for(lambda: [v for v in events(self.worker_log) if v["event"] == "channel-result"]
                           if len([v for v in events(self.worker_log) if v["event"] == "channel-result"]) == 2 else None)
        self.assertEqual(json.loads((fenced / "denial.json").read_text()), dict(rex=True, registry=True))
        self.assertEqual([v["code"] for v in results], [0, 1])
        self.assertIn("already_attempted", json.loads(results[1]["stdout"])["failure_reason"])
        wait_for(lambda: [v for v in events(self.worker_log) if v["event"] == "channel-stop"])
        self.assertEqual([v["code"] for v in events(self.worker_log) if v["event"] == "channel-stop"], [0])
        env = [v for v in events(self.worker_log) if v["event"] == "started"][0]["env"]
        self.assertNotIn("AGENT_REGISTRY", env)
        self.assertNotIn("LC_AGENT_REGISTRY", env)
        self.assertEqual(env["AGENT_LAUNCH_ID"], launch_id)
        notices = wait_for(lambda: [v["payload"] for v in events(self.starter_log) if v["event"] == "input"]
                           if len([v for v in events(self.starter_log) if v["event"] == "input"]) == 2 else None)
        self.assertEqual(notices[0], "FROM probe: fenced β: quotes '\"\nlast line\n\n")
        self.assertIn("fenced turn complete β", notices[1])
        # The brief still traverses the original ACK-before-one-brief gate and keeps trailing bytes.
        inputs = wait_for(lambda: [v["payload"] for v in events(self.worker_log) if v["event"] == "input"])
        self.assertEqual(inputs, ["FROM probe: " + self.brief.read_text()])
        # The fixture exits on the brief; namespace-local PIDs are never signalled from the host.
        wait_for(lambda: self.record(launch_id)["immediate_child_term"])
        wait_for(lambda: not (self.delivery / launch_id).exists())
        p, result = self.channel_cli(launch_id, "--operation", "send", "--to", "starter", "--message-file", str(self.brief))
        self.assertEqual(p.returncode, 1)
        self.assertFalse(result["retry_safe"])

    def test_channel_fixed_grants_framing_lease_and_no_retry(self):
        self.enable_channel()
        p, packet = self.launch()
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        launch_id = packet["launch_id"]
        handle_path = self.delivery / launch_id / "handle.json"
        handle = json.loads(handle_path.read_text())
        def raw_request(**changes):
            request = dict(launch_id=launch_id, token=handle["token"], request_id="d" * 32,
                           operation="send", to="starter", body="one exact β\n\n")
            request.update(changes)
            if request["operation"] == "stop":
                request.pop("to")
                request.pop("body")
            with socket.socket(socket.AF_UNIX) as c:
                c.settimeout(5)
                c.connect(handle["socket"])
                c.sendall(json.dumps(request).encode() + b"\n")
                data = b""
                while not data.endswith(b"\n"):
                    data += c.recv(65536)
                return json.loads(data)
        for changes, reason in ((dict(token="0" * 64), "token_mismatch"),
                                (dict(launch_id="0" * 32), "launch_mismatch"),
                                (dict(to=self.starter), "fixed_channel_destination"),
                                (dict(operation="exec"), "not_granted"),
                                (dict(body="bad\x1bcontrol"), "invalid_or_oversized"),
                                (dict(body="x" * 32769), "invalid_or_oversized"),
                                (dict(socket=str(self.socket)), "unknown_channel_field"),
                                (dict(operation="stop", event={"hook_event_name":"Stop", "transcript_path":"/etc/passwd"}),
                                 "channel_transcript_path_forbidden")):
            with self.subTest(changes=list(changes)):
                result = raw_request(**changes)
                self.assertEqual(result["code"], 1)
                self.assertIn(reason, result["result"]["failure_reason"])
        self.assertEqual([v for v in events(self.starter_log) if v["event"] == "input"], [])
        p, bad = self.channel_cli(launch_id, "--operation", "ack", "--session", self.session, "--block", self.starter,
                                  "--to", "starter")
        self.assertEqual(p.returncode, 1)
        self.assertIn("irrelevant_channel_argument", bad["failure_reason"])
        for raw, reason in ((b'{"operation":"send","operation":"ack"}\n', "duplicate_channel_field"),
                            (b'{}\n{}\n', "one_channel_frame_required"), (b'{', "incomplete_channel_frame"),
                            (b'x' * 49153, "channel_frame_too_large"),
                            (b'[' * 20000 + b']' * 20000 + b'\n', None)):
            with socket.socket(socket.AF_UNIX) as c:
                c.settimeout(2)
                c.connect(handle["socket"])
                c.sendall(raw)
                try:
                    c.shutdown(socket.SHUT_WR)
                except OSError as error:
                    # macOS can report ENOTCONN after the server already sent its refusal and closed.
                    if error.errno != errno.ENOTCONN:
                        raise
                response = b""
                while not response.endswith(b"\n"):
                    part = c.recv(65536)
                    self.assertTrue(part)
                    response += part
            result = json.loads(response)
            self.assertEqual(result["code"], 1)
            if reason is not None:  # Deep JSON can refuse at parser depth or at the required object envelope.
                self.assertIn(reason, result["result"]["failure_reason"])
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            simultaneous = list(pool.map(lambda unused: raw_request(), range(2)))
        self.assertEqual(sorted(v["code"] for v in simultaneous), [0, 1])
        self.assertTrue(all(not v["result"]["retry_safe"] for v in simultaneous))
        refusal = [v for v in simultaneous if v["code"] == 1][0]
        self.assertIn("already_attempted", refusal["result"]["failure_reason"])
        wait_for(lambda: len([v for v in events(self.starter_log) if v["event"] == "input"]) == 1)
        # Dropping the response after submission still leaves durable intent and refuses a resend.
        request = dict(launch_id=launch_id, token=handle["token"], request_id="e" * 32, operation="send", to="starter", body="lost receipt β")
        with socket.socket(socket.AF_UNIX) as c:
            c.connect(handle["socket"])
            c.sendall(json.dumps(request).encode() + b"\n")
        wait_for(lambda: self.record(launch_id).get("channel_requests", {}).get("e" * 32))
        result = raw_request(request_id="e" * 32, body="lost receipt β")
        self.assertEqual(result["code"], 1)
        self.assertIn("already_attempted", result["result"]["failure_reason"])
        wait_for(lambda: len([v for v in events(self.starter_log) if v["event"] == "input"]) == 2)
        stalled = subprocess.Popen([BIN, "agents", "channel", "--handle", str(handle_path), "--request-id", "f" * 32,
                                    "--operation", "send", "--to", "starter", "--message-file", "-"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env)
        try:
            self.assertEqual(stalled.wait(timeout=4), 1)
            self.assertIn("input_eof_deadline_2s", json.loads(stalled.stdout.read())["failure_reason"])
        finally:
            if stalled.poll() is None:
                stalled.kill()
                stalled.wait()
            stalled.stdin.close()
            stalled.stdout.close()
            stalled.stderr.close()
        self.assertEqual(len([v for v in events(self.starter_log) if v["event"] == "input"]), 2)
        # Final-component symlinks are not accepted as capability files.
        alias = self.work / "handle-link"
        alias.symlink_to(handle_path)
        p, result = self.run_cli("channel", "--handle", str(alias), "--request-id", "f" * 32,
                                 "--operation", "send", "--to", "starter", "--message-file", str(self.brief))
        self.assertEqual(p.returncode, 1)
        os.kill(events(self.worker_log)[0]["pid"], signal.SIGTERM)
        wait_for(lambda: not handle_path.exists())

    @unittest.skipUnless(os.environ.get("TEEREX_AGENTS_INTEGRATION") == "1", "requires combined boards routing")
    def test_channel_registered_seat_and_store_refusal_never_paste(self):
        self.enable_channel()
        store = self.work / "boards"
        store.mkdir(mode=0o700)
        self.settings["defaults"]["store"] = str(store)
        target = ["--store", str(store), "--host", "disposable", "--socket", str(self.socket),
                  "--session", self.session, "--block", self.starter]
        result = subprocess.run([BIN, "seat", "register", *target, "--owner", "operator"], capture_output=True, text=True, env=self.env)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        p, packet = self.launch()
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        launch_id = packet["launch_id"]
        p, result = self.channel_cli(launch_id, "--operation", "send", "--to", "starter", "--message-file", str(self.brief))
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual(result["receipt"]["outcome"], "recorded")
        inbox = json.loads(subprocess.check_output([BIN, "inbox", "inspect", *target], env=self.env))
        self.assertEqual([r["body"] for r in inbox["seat"]["records"]], [self.brief.read_text()])
        self.assertEqual([v for v in events(self.starter_log) if v["event"] == "input"], [])
        store.chmod(0o755)
        try:
            p, result = self.channel_cli(launch_id, "--operation", "send", "--to", "starter", "--message-file", str(self.brief),
                                         request_id="f" * 32)
            self.assertEqual(p.returncode, 1)
            self.assertEqual(result["outcome"], "uncertain")
            self.assertNotEqual(result["receipt"]["outcome"], "events_acknowledged")
            self.assertEqual([v for v in events(self.starter_log) if v["event"] == "input"], [])
        finally:
            store.chmod(0o700)

    def test_channel_expiry_count_and_cancel_revoke_without_stopping_other_panes(self):
        self.enable_channel(count=2, lifetime=1000)
        p, packet = self.launch()
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        launch_id = packet["launch_id"]
        p, result = self.channel_cli(launch_id, "--operation", "send", "--to", "starter", "--message-file", str(self.brief))
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        wait_for(lambda: not (self.delivery / launch_id).exists())
        self.assertIsNone(self.record(launch_id)["immediate_child_term"])
        self.assertEqual(self.record(launch_id)["channel_status"], "revoked")
        self.assertEqual(len(self.rpc("session.view", dict(session_id=self.session))["windows"]), 2)
        # A separate launch expires even when it has unused requests, with its child still alive.
        self.settings["profiles"]["probe"]["delivery"]["max_requests"] = 32
        self.worker_log = self.work / "expiring-worker.jsonl"
        self.settings["profiles"]["probe"]["argv"][2] = str(self.worker_log)
        p, packet = self.launch()
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        expired_grant = json.loads((self.delivery / packet["launch_id"] / "handle.json").read_text())
        wait_for(lambda: not (self.delivery / packet["launch_id"]).exists())
        self.assertIsNone(self.record(packet["launch_id"])["immediate_child_term"])
        # Signal the actual recorded visible supervisor: its channel revokes and its own child is reaped.
        self.settings["profiles"]["probe"]["delivery"]["lifetime_ms"] = 60000
        for sig in (signal.SIGINT, signal.SIGTERM):
            self.worker_log = self.work / ("cancelled-worker-" + str(sig) + ".jsonl")
            self.settings["profiles"]["probe"]["argv"][2] = str(self.worker_log)
            p, packet = self.launch()
            self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
            state = self.record(packet["launch_id"])
            active_grant = json.loads((self.delivery / packet["launch_id"] / "handle.json").read_text())
            for claimed_launch, reason in ((expired_grant["launch_id"], "launch_mismatch"),
                                           (active_grant["launch_id"], "token_mismatch")):
                with socket.socket(socket.AF_UNIX) as c:
                    c.settimeout(3)
                    c.connect(active_grant["socket"])
                    c.sendall(json.dumps(dict(launch_id=claimed_launch, token=expired_grant["token"], request_id="9" * 32,
                                             operation="send", to="starter", body="must not cross launch")).encode() + b"\n")
                    response = b""
                    while not response.endswith(b"\n"):
                        part = c.recv(65536)
                        self.assertTrue(part)
                        response += part
                result = json.loads(response)
                self.assertEqual(result["code"], 1)
                self.assertIn(reason, result["result"]["failure_reason"])
            os.kill(state["supervisor_pid"], sig)
            wait_for(lambda: not (self.delivery / packet["launch_id"]).exists())
            wait_for(lambda: self.record(packet["launch_id"])["immediate_child_term"])
            # SIGINT in Python is reported as KeyboardInterrupt/exit130 rather than an OS signal.
            self.assertIn(self.record(packet["launch_id"])["immediate_child_term"],
                          ({"Signal": sig}, {"Exited": 128 + sig}))
            os.kill(events(self.starter_log)[0]["pid"], 0)

    def program_state(self, block):
        result = json.loads(subprocess.check_output(self.base + ["block", "call", "-s", self.session, "-b", block,
                                                                "program_status", "{}"], timeout=5))
        return next((r["state"] for r in result.get("records", []) if r.get("app") == "teerex-agent"), None)

    def test_all_harness_exits_and_crashes_replace_working_status(self):
        for harness in ("claude", "codex", "pi"):
            for ending in ("exit0", "exit7", "signal", "hangup"):
                with self.subTest(harness=harness, ending=ending):
                    self.settings["profiles"]["probe"].update(harness=harness, hook_events=True)
                    p, launched = self.launch()
                    self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                    launch_id = launched["launch_id"]
                    block = self.record(launch_id)["target"]["block_id"]
                    wait_for(lambda: self.program_state(block) == "working")
                    if ending in ("signal", "hangup"):
                        child = [v for v in events(self.worker_log) if v["event"] == "started"][-1]["pid"]
                        os.kill(child, signal.SIGHUP if ending == "hangup" else signal.SIGKILL)
                        expected = {"Signal": signal.SIGHUP if ending == "hangup" else signal.SIGKILL}
                    else:
                        message = self.work / "exit.txt"
                        message.write_text("TEST EXIT " + ending[-1])
                        sent = subprocess.run([BIN, "send", "--socket", str(self.socket), "--session", self.session,
                            "--block", block, "--from", "test", "--message-file", str(message)], env=self.env, capture_output=True, text=True)
                        self.assertEqual(sent.returncode, 0, sent.stdout + sent.stderr)
                        expected = {"Exited": int(ending[-1])}
                    wait_for(lambda: self.record(launch_id).get("immediate_child_term") is not None)
                    self.assertEqual(self.record(launch_id)["immediate_child_term"], expected)
                    wait_for(lambda: self.program_state(block) == ("done" if ending == "exit0" else "error"))

    def scratch_contract(self, state, now_text="", todo=(), done=(), blocked="", waiting="", check=""):
        Path(state["scratchpad"]).write_text(
            "# probe\nBlocked: " + blocked + "\nWaiting: " + waiting + "\nCheck: " + check +
            "\n## Now\n" + ("- [ ] " + now_text + "\n" if now_text else "") +
            "## To-do\n" + "".join("- [ ] " + text + "\n" for text in todo) +
            "## Done\n" + "".join("- [x] " + text + "\n" for text in done))

    def starter_messages(self):
        return [v["payload"] for v in events(self.starter_log) if v["event"] == "input"]

    def test_ack_turn_is_legacy_and_first_brief_turn_requires_steps(self):
        self.settings["profiles"]["probe"]["contract_interval_s"] = 1
        self.config.write_text(json.dumps(self.settings))
        p, launched = self.run_cli("launch", "--config", str(self.config), "--profile", "probe", "--ack-timeout-ms", "5000")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        launch_id = launched["launch_id"]
        args = ("stop", "--registry", str(self.registry), "--launch-id", launch_id, "--event-file", "-")
        stop = json.dumps(dict(hook_event_name="Stop", last_assistant_message="ACK only"))
        for _ in range(2):
            p, packet = self.run_cli(*args, input=stop)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertNotEqual(packet["outcome"], "scratchpad_blocked")
            self.assertFalse(packet["delivery_rule"].startswith("contract_"))
        # No lapse or automatic STEP/FLAG before the brief, even after the interval.
        self.scratch_contract(self.record(launch_id), "Protocol setup")
        time.sleep(1.2)
        self.assertFalse([m for m in self.starter_messages() if any(tag in m for tag in ("STEP probe", "FLAG probe", "LAPSE probe", "NO ANSWER probe"))])
        self.scratch_contract(self.record(launch_id))
        with (self.registry / "agents.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self.record(launch_id)
            state["brief_file"] = str(self.brief)
            (self.registry / ("agents-" + launch_id + ".json")).write_text(json.dumps(state))
        p, delivered = self.run_cli("deliver", "--registry", str(self.registry), "--launch-id", launch_id)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        state = self.record(launch_id)
        self.assertEqual(state["contract"]["last_contact_at"], state["brief_attempt_at"])
        # The ACK already ended, so no prompt-start timestamp can exempt this stop.
        p, packet = self.run_cli(*args, input=stop)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(packet["outcome"], "scratchpad_blocked")
        self.assertIn("write your steps first", packet["scratchpad_check"]["reason"])

    def test_ack_before_brief_consumes_empty_turn_exemption_across_adapters(self):
        for harness in ("claude", "codex", "pi"):
            with self.subTest(harness=harness):
                p, launched = self.run_cli("launch", "--config", str(self.config), "--profile", "probe", "--ack-timeout-ms", "5000")
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                launch_id = launched["launch_id"]
                state = self.record(launch_id)
                self.assertFalse(state["brief_attempted"])
                def fresh():
                    result = subprocess.run([BIN, "scratch", "flag", "", "--session", state["target"]["session_id"],
                                             "--block", state["target"]["block_id"]], env=self.env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                def end(turn):
                    if harness == "codex":
                        return self.enforcement_hook(launch_id, harness, dict(type="agent-turn-complete", **{
                            "last-assistant-message": turn, "turn-id": turn, "input-messages": [turn]}), notify=True)
                    return self.enforcement_hook(launch_id, harness, dict(
                        hook_event_name="ScratchCheck" if harness == "pi" else "Stop", last_assistant_message=turn))
                fresh()
                ack = end("protocol-ack")
                if harness == "pi":
                    self.assertEqual(ack["scratchpad_check"]["action"], "allow")
                    ack = self.enforcement_hook(launch_id, harness, dict(hook_event_name="Stop", last_assistant_message="ACK"))
                self.assertFalse(ack["delivery_rule"].startswith("contract_"))
                state = self.record(launch_id)
                self.assertFalse(state["brief_attempted"])
                self.assertTrue(state["contract_turn_ended"])
                self.assertEqual(state["contract"]["steps_total"], 0)
                with (self.registry / "agents.lock").open("a") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    state = self.record(launch_id)
                    state["brief_file"] = str(self.brief)
                    (self.registry / ("agents-" + launch_id + ".json")).write_text(json.dumps(state))
                p, _ = self.run_cli("deliver", "--registry", str(self.registry), "--launch-id", launch_id)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertTrue(self.record(launch_id)["brief_attempted"])
                fresh()
                result = end("brief-with-no-steps")
                if harness == "claude":
                    self.assertEqual(result["decision"], "block")
                    reason = result["reason"]
                else:
                    self.assertEqual(result["scratchpad_check"]["action"], "reminded" if harness == "codex" else "block")
                    reason = result["scratchpad_check"]["reason"]
                self.assertEqual(reason, CONTRACT_REFUSAL + "; write your steps first")

    def test_contract_steps_and_flag_are_delivered_once(self):
        p, launched = self.launch(contract=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        state = self.record(launched["launch_id"])
        self.scratch_contract(state, "Read", ["Build"])
        wait_for(lambda: any("STEP probe 1/2 started: Read" in text for text in self.starter_messages()))
        self.scratch_contract(state, "Build", done=["Read"])
        wait_for(lambda: any("STEP probe 2/2 started: Build" in text for text in self.starter_messages()))
        self.assertEqual(sum("STEP probe 1/2 finished: Read" in text for text in self.starter_messages()), 1)
        self.scratch_contract(state, "Build", done=["Read"], blocked="missing input; read brief; need answer")
        wait_for(lambda: any("FLAG probe step 2/2:" in text for text in self.starter_messages()))
        time.sleep(.3)
        self.assertEqual(sum("FLAG probe step 2/2:" in text for text in self.starter_messages()), 1)
        # A turn-end callback observing the same flag must not send a second copy.
        p, packet = self.run_cli("stop", "--registry", str(self.registry), "--launch-id", launched["launch_id"],
                                "--event-file", "-", input=json.dumps(dict(hook_event_name="Stop", last_assistant_message="blocked")))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(sum("FLAG probe step 2/2:" in text for text in self.starter_messages()), 1)

    def contract_seat_fixture(self):
        store = self.work / "boards"
        store.mkdir(mode=0o700)
        self.settings["defaults"]["store"] = str(store)
        self.settings["profiles"]["probe"]["contract_interval_s"] = 2
        self.settings["profiles"]["probe"]["scratch_pane"] = False
        seat_log = self.work / "seat.jsonl"
        target = json.loads(subprocess.check_output(self.base + ["run", "-s", self.session, "--json", "--keep-open", "--",
            sys.executable, str(self.fixture), str(seat_log), "noack"], timeout=10))
        # rex run returns the newly created block IDs on the top level.
        seat = target["block_ids"][0]
        args = ["--store", str(store), "--host", "disposable", "--socket", str(self.socket),
                "--session", self.session, "--block", seat]
        p = subprocess.run([BIN, "seat", "register", *args, "--owner", "operator"], env=self.env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        def records():
            p = subprocess.run([BIN, "boards", "state", "inspect", "--store", str(store)], env=self.env, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            return json.loads(p.stdout)["state"]["seats"][0]["records"]
        return records, seat_log

    def test_contract_lapse_wakes_worker_and_second_lapse_reaches_seat(self):
        seat_records, seat_log = self.contract_seat_fixture()
        p, launched = self.launch(contract=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        launch_id = launched["launch_id"]
        state = self.record(launch_id)
        self.scratch_contract(state, "Work", ["Verify"])
        wait_for(lambda: any("STEP probe 1/2 started" in text for text in self.starter_messages()))
        wait_for(lambda: self.record(launch_id)["contract"]["lapses"] == 1)
        self.assertTrue(self.record(launch_id)["contract"]["stalled"])
        wait_for(lambda: self.program_state(state["target"]["block_id"]) == "blocked")
        wait_for(lambda: any("Contract check:" in v.get("payload", "") for v in events(self.worker_log)))
        wait_for(lambda: len([r for r in seat_records() if "LAPSE probe" in r["body"]]) == 1, timeout=12)
        self.assertEqual(sum("LAPSE probe" in text for text in self.starter_messages()), 2)
        self.assertFalse([v for v in events(seat_log) if v["event"] == "input"])
        self.scratch_contract(state, "Verify", done=["Work"])
        wait_for(lambda: not self.record(launch_id)["contract"]["stalled"])
        self.assertEqual(self.record(launch_id)["contract"]["lapses"], 0)

    def test_contract_expired_wait_check_wakes_before_interval(self):
        import datetime
        self.settings["profiles"]["probe"]["contract_interval_s"] = 60
        p, launched = self.launch(contract=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        state = self.record(launched["launch_id"])
        check = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=1)).isoformat()
        self.scratch_contract(state, "Wait", waiting="dependency", check=check)
        wait_for(lambda: self.record(launched["launch_id"])["contract"]["lapses"] == 1)
        time.sleep(.3)
        self.assertEqual(sum("LAPSE probe" in text for text in self.starter_messages()), 1)

    def test_contract_unanswered_done_escalates_and_acknowledged_input_clears(self):
        seat_records, seat_log = self.contract_seat_fixture()
        p, launched = self.launch(contract=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        launch_id = launched["launch_id"]
        state = self.record(launch_id)
        self.scratch_contract(state, done=["Finished"])
        event = json.dumps(dict(hook_event_name="Stop", last_assistant_message="done yes"))
        p, packet = self.run_cli("stop", "--registry", str(self.registry), "--launch-id", launch_id,
                                "--event-file", "-", input=event)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        wait_for(lambda: (self.record(launch_id)["contract"].get("awaiting_starter") or {}).get("kind") == "done")
        wait_for(lambda: any("UNANSWERED probe done" in r["body"] for r in seat_records()), timeout=12)
        self.assertEqual(sum("UNANSWERED probe done" in text for text in self.starter_messages()), 2)
        p = subprocess.run([BIN, "send", "--socket", str(self.socket), "--session", self.session,
                            "--block", state["target"]["block_id"], "--from", "starter", "--message-file", "-"],
                           input="accepted", env=self.env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        wait_for(lambda: self.record(launch_id)["contract"]["awaiting_starter"] is None)
        self.assertEqual(self.record(launch_id)["contract"]["starter_lapses"], 0)
        self.assertFalse([v for v in events(seat_log) if v["event"] == "input"])

    def test_contract_flag_awaits_answer_and_child_exit_ends_it(self):
        self.settings["profiles"]["probe"]["contract_interval_s"] = 2
        p, launched = self.launch(contract=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        launch_id = launched["launch_id"]
        state = self.record(launch_id)
        self.scratch_contract(state, "Work", blocked="cannot proceed; checked inputs; need source")
        wait_for(lambda: (self.record(launch_id)["contract"].get("awaiting_starter") or {}).get("kind") == "flag")
        wait_for(lambda: any("UNANSWERED probe flag" in text for text in self.starter_messages()))
        os.kill(events(self.worker_log)[0]["pid"], signal.SIGTERM)
        wait_for(lambda: self.record(launch_id)["immediate_child_term"] is not None)
        self.assertIsNone(self.record(launch_id)["contract"]["awaiting_starter"])

    def test_scratch_waiting_blocks_with_text_and_clears_for_all_harnesses(self):
        for harness in ("claude", "codex", "pi"):
            self.settings["profiles"]["probe"].update(harness=harness, hook_events=True)
            p, launched = self.launch()
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            state = self.record(launched["launch_id"])
            block = state["target"]["block_id"]
            wait_for(lambda: self.program_state(block) == "working")
            def waiting(text):
                p = subprocess.run([BIN, "scratch", "now", "review", "--waiting", text,
                    "--session", self.session, "--block", block], env=self.env, capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            waiting("reviewer · approval")
            wait_for(lambda: self.program_state(block) == "blocked")
            result = self.rpc("com.superlogical.terminal.program_status", dict(session_id=self.session, block_id=block, args={}))
            record = next(r for r in result["records"] if r.get("app") == "teerex-agent")
            self.assertIn("reviewer", json.dumps(record))
            waiting("")
            wait_for(lambda: self.program_state(block) == "working")
            # Hand edits are the same source as CLI writes.
            pad = Path(state["scratchpad"])
            pad.write_text(pad.read_text() + "\nWaiting: external result\n")
            wait_for(lambda: self.program_state(block) == "blocked")
            pad.write_text(pad.read_text().replace("Waiting: external result", ""))
            wait_for(lambda: self.program_state(block) == "working")
            waiting("old dependency")
            wait_for(lambda: self.program_state(block) == "blocked")
            p, result = self.run_cli("stop", "--registry", str(self.registry), "--launch-id", launched["launch_id"],
                "--event-file", "-", input=json.dumps(dict(hook_event_name="StopFailure", error="run failed")))
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            wait_for(lambda: self.program_state(block) == "error")

    def test_codex_delivery_notify_and_failure_share_pane_state(self):
        for tint in (False, None):
            self.settings["profiles"]["probe"].update(harness="codex", hook_events=True, tint=tint)
            p, launched = self.launch()
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            launch_id = launched["launch_id"]
            state = self.record(launch_id)
            block = state["target"]["block_id"]
            started = [v for v in events(self.worker_log) if v["event"] == "started"][-1]
            callback = json.loads(next(a[len("notify="):] for a in started["argv"] if a.startswith("notify=")))
            env = dict(self.env, AGENT_SCRATCHPAD=state["scratchpad"])
            def work(text):
                changed = subprocess.run([BIN, "scratch", "now", text, "--session", self.session, "--block", block],
                                         env=self.env, capture_output=True, text=True)
                self.assertEqual(changed.returncode, 0, changed.stdout + changed.stderr)
            def stop(text):
                result = subprocess.run(callback + [json.dumps({"type":"agent-turn-complete", "last-assistant-message":text})],
                                        env=env, capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            work("first turn")
            stop("progress")
            wait_for(lambda: self.program_state(block) == "idle")
            # An input event can reach bookkeeping after its turn already stopped.
            import importlib.util
            spec = importlib.util.spec_from_file_location("input_events", Path(__file__).with_name("input_events.py"))
            inputs = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(inputs)
            marker = self.root / ".local/state/teerex/agent-input" / inputs.agent_input_path(str(self.socket), self.session, block).name
            late_ns = self.record(launch_id)["last_hook"]["at_ns"] - 1
            marker.write_text(json.dumps(dict(at_ns=late_ns)))
            wait_for(lambda: self.record(launch_id).get("last_input_at_ns") == late_ns)
            self.assertEqual(self.record(launch_id)["last_hook"]["state"], "idle")
            self.assertEqual(self.program_state(block), "idle")
            message = self.work / "p0-message.txt"
            message.write_text("start the next turn")
            send = subprocess.run([BIN, "send", "--socket", str(self.socket), "--session", self.session,
                "--block", block, "--from", "test", "--message-file", str(message)], env=self.env, capture_output=True, text=True)
            self.assertEqual(send.returncode, 0, send.stdout + send.stderr)
            wait_for(lambda: self.program_state(block) == "working")
            self.assertEqual(self.record(launch_id)["last_hook"]["state"], "working")
            work("second turn")
            stop("progress again")
            wait_for(lambda: self.program_state(block) == "idle")
            # ask uses the same acknowledged-delivery path, without changing a question to red.
            ask = subprocess.run([BIN, "ask", "--host", "disposable", "--socket", str(self.socket), "--session", self.session,
                "--block", block, "--from", "test", "--title", "review", "--ask", "continue?",
                "--context", "fixture", "--option", "yes::continue::nothing", "--option", "no::stop::nothing",
                "--recommend", "yes"], env=self.env, capture_output=True, text=True)
            self.assertEqual(ask.returncode, 0, ask.stdout + ask.stderr)
            wait_for(lambda: self.program_state(block) == "working")
            finished = subprocess.run([BIN, "scratch", "done", "--session", self.session, "--block", block],
                                      env=self.env, capture_output=True, text=True)
            self.assertEqual(finished.returncode, 0, finished.stdout + finished.stderr)
            stop("finished")
            wait_for(lambda: self.program_state(block) == "done")
            self.assertEqual(self.record(launch_id)["last_hook"]["state"], "done")
            event = self.work / "p0-failure.json"
            event.write_text(json.dumps(dict(hook_event_name="StopFailure", error="fixture failure")))
            p, result = self.run_cli("stop", "--registry", str(self.registry), "--launch-id", launch_id, "--event-file", str(event))
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            wait_for(lambda: self.program_state(block) == "error")
            self.assertEqual(result["turn_state"], "error")

    def test_codex_adapter_validation_conflicts_and_callback_failure_are_visible(self):
        self.env.pop("AGENT_SCRATCHPAD", None)
        self.env.pop("LC_AGENT_SCRATCHPAD", None)
        log = self.work / "callback.json"
        command = [sys.executable, "-c", "import sys; from pathlib import Path; Path(" + repr(str(log)) + ").write_text(sys.stdin.read()); sys.exit(23)"]
        common = ["hook", "--harness", "codex", "--command-json", json.dumps(command), "--payload"]
        for payload in ({"type": "unrecognized"}, {"type": "agent-turn-complete", "last-assistant-message": []},
                        {"type": "agent-turn-complete", "last-assistant-message": "x" * 32768}):
            p, result = self.run_cli(*common, json.dumps(payload))
            self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
            self.assertFalse(log.exists())
        p, _ = self.run_cli(*common, json.dumps({"type": "agent-turn-complete", "last-assistant-message": "bounded β"}))
        self.assertEqual(p.returncode, 23, p.stdout + p.stderr)
        self.assertEqual(json.loads(log.read_text()), dict(hook_event_name="Stop", last_assistant_message="bounded β"))
        for option in ("notify=[]", "--config=notify=[]", "-cnotify=[]"):
            self.settings["profiles"]["probe"].update(harness="codex", hook_events=True, standing_flags=[option])
            p, result = self.launch()
            self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
            self.assertEqual(result["failure_reason"], "profile_notify_conflict")
        self.assertEqual(list(self.registry.glob("agents-*.json")), [])

    def background(self, pid):
        count = sum(v["event"] == "background" for v in events(self.worker_log))
        os.kill(pid, signal.SIGUSR1)
        try:
            wait_for(lambda: sum(v["event"] == "background" for v in events(self.worker_log)) > count)
        except AssertionError:
            self.fail("No OSC11 response from disposable fixture")
        return [v["value"] for v in events(self.worker_log) if v["event"] == "background"][-1]

    def test_tint_idle_prompt_send_reset_custom_and_disabled(self):
        self.settings["profiles"]["probe"].update(harness="claude", hook_events=True, tint=dict(idle="#312345"))
        p, launched = self.launch()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        launch_id = launched["launch_id"]
        state = self.record(launch_id)
        block = state["target"]["block_id"]
        pid = next(v["pid"] for v in events(self.worker_log) if v["event"] == "started")
        self.rpc("com.superlogical.terminal.set_theme", dict(session_id=self.session, block_id=block, args=dict(background="#010203")))
        default = self.background(pid)
        # Harness owns root; supervisor must never replace it.
        event = self.work / "event.json"
        def hook(kind):
            event.write_text(json.dumps(dict(hook_event_name=kind, last_assistant_message="turn done")))
            p, _ = self.run_cli("stop", "--registry", str(self.registry), "--launch-id", launch_id, "--event-file", str(event))
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        progressed = subprocess.run([BIN, "scratch", "now", "active work", "--session", self.session, "--block", block], env=self.env, capture_output=True)
        self.assertEqual(progressed.returncode, 0)
        hook("Stop")
        wait_for(lambda: self.program_state(block) == "idle")
        self.assertIn('rgb:3131/2323/4545', self.background(pid))
        hook("UserPromptSubmit")
        wait_for(lambda: self.program_state(block) == "working")
        self.assertEqual(self.background(pid), default)
        hook("StopFailure")
        wait_for(lambda: self.program_state(block) == "error")
        self.assertIn('rgb:2a2a/1414/1414', self.background(pid))
        message = self.work / "reset.txt"
        message.write_text("next turn")
        p = subprocess.run([BIN, "send", "--socket", str(self.socket), "--session", self.session, "--block", block,
                            "--from", "test", "--message-file", str(message), "--draft", "ignore"], env=self.env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.background(pid), default)
        records = self.rpc("com.superlogical.terminal.program_status", dict(session_id=self.session, block_id=block, args={}))
        self.assertTrue(any(r.get("id") == "teerex/tint" for r in records["records"]))
        self.assertTrue(any(r.get("app") == "synthetic" and r.get("id", "") == "" for r in records["records"]))
        started = next(v for v in events(self.worker_log) if v["event"] == "started")
        injected = json.loads(started["argv"][started["argv"].index("--settings")+1])
        self.assertIn("UserPromptSubmit", injected["hooks"])

    def test_timeline_retains_each_hook_and_archived_exit(self):
        p, launched = self.launch()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        launch_id = launched["launch_id"]
        event = self.work / "event.json"
        for index, kind in enumerate(("Stop", "StopFailure", "Stop")):
            event.write_text(json.dumps(dict(hook_event_name=kind, last_assistant_message="words %d\nsecond line" % index, error="failed")))
            p, _ = self.run_cli("stop", "--registry", str(self.registry), "--launch-id", launch_id, "--event-file", str(event))
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        pid = next(v["pid"] for v in events(self.worker_log) if v["event"] == "started")
        os.kill(pid, signal.SIGTERM)
        wait_for(lambda: self.record(launch_id).get("immediate_child_term") is not None)
        wait_for(lambda: self.record(launch_id).get("notifications", {}).get("child-exit", {}).get("outcome") not in (None, "uncertain"))
        # Age only this disposable fixture past the existing prune settle window.
        state = self.record(launch_id)
        state["created_at"] -= 180000
        state["timeline"][0]["at"] -= 180000
        (self.registry / ("agents-" + launch_id + ".json")).write_text(json.dumps(state))
        p, result = self.run_cli("prune", "--registry", str(self.registry), "--apply")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(any(r["launch_id"] == launch_id for r in result["retired"]))
        p, result = self.run_cli("timeline", "--registry", str(self.registry), "--json")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertFalse(result["legacy_partial_launches"])
        rows = [r for r in result["events"] if r["launch_id"] == launch_id]
        self.assertEqual([r["event"] for r in rows], ["launched", "protocol_ack", "brief_attempted", "Stop", "StopFailure", "Stop", "child_exit", "pruned"])
        self.assertEqual([r["at"] for r in rows], sorted(r["at"] for r in rows))
        self.assertEqual([r["text"] for r in rows if r["event"] == "Stop"], ["words 0", "words 2"])
        self.assertEqual(rows[-2]["term"], {"Signal": signal.SIGTERM})

    def enforcement_hook(self, launch_id, harness, event, notify=False):
        command = [BIN, "agents", "stop", "--registry", str(self.registry), "--launch-id", launch_id, "--event-file", "-"]
        state = self.record(launch_id)
        env = dict(self.env, AGENT_SCRATCHPAD=state["scratchpad"])
        source = ["--payload", json.dumps(event)] if notify else ["--event-file", "-"]
        p = subprocess.run([BIN, "agents", "hook", "--harness", harness, "--command-json", json.dumps(command), *source],
                           input=None if notify else json.dumps(event), text=True, capture_output=True, env=env, timeout=15)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads(p.stdout)

    def test_contract_turn_declarations_across_all_adapters(self):
        for harness in ("claude", "codex", "pi"):
            with self.subTest(harness=harness):
                p, launched = self.launch(contract=True)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                launch_id = launched["launch_id"]
                state = self.record(launch_id)
                pad = Path(state["scratchpad"])
                target = state["target"]
                def scratch(*args):
                    result = subprocess.run([BIN, "scratch", *args, "--session", target["session_id"], "--block", target["block_id"]],
                                            env=self.env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                input_start = sum(v["event"] == "input" for v in events(self.starter_log))
                counter = 0
                latest_refusal = ""
                def start():
                    nonlocal counter
                    counter += 1
                    self.enforcement_hook(launch_id, harness, dict(hook_event_name="UserPromptSubmit"))
                def end(reminder=False):
                    if harness == "codex":
                        return self.enforcement_hook(launch_id, harness, dict(type="agent-turn-complete", **{
                            "last-assistant-message": "proof " + "x" * 400, "turn-id": f"{counter}-{'reminder' if reminder else 'real'}",
                            "input-messages": [latest_refusal if reminder else 'work']}), notify=True)
                    return self.enforcement_hook(launch_id, harness, dict(hook_event_name="ScratchCheck" if harness == "pi" else "Stop",
                                                                          last_assistant_message="proof"))
                def settle(result):
                    if harness == "pi":
                        return self.enforcement_hook(launch_id, harness, dict(hook_event_name="Stop", last_assistant_message="proof"))
                    return result
                def blocked(result):
                    nonlocal latest_refusal
                    if harness == "claude":
                        self.assertEqual(result["decision"], "block")
                        latest_refusal = result["reason"]
                        return latest_refusal
                    self.assertEqual(result["scratchpad_check"]["action"], "reminded" if harness == "codex" else "block")
                    latest_refusal = result["scratchpad_check"]["reason"]
                    return latest_refusal
                def messages():
                    return [v["payload"] for v in events(self.starter_log) if v["event"] == "input"][input_start:]
                start()
                # The first empty end is the ACK; subsequent empty turns need steps.
                scratch("flag", "")
                ack = settle(end())
                self.assertFalse(ack["delivery_rule"].startswith("contract_"))
                self.assertTrue(self.record(launch_id)["contract_turn_ended"])
                start()
                scratch("flag", "")
                reason = blocked(end())
                self.assertEqual(reason, CONTRACT_REFUSAL + "; write your steps first")
                settle(end(reminder=True))
                wait_for(lambda: any("NO ANSWER probe:" in text for text in messages()))
                start()
                scratch("now", "Implement")
                blocked(end())
                settle(end(reminder=True))
                start()
                scratch("done")
                result = settle(end())
                self.assertEqual(result["delivery_rule"], "contract_done")
                wait_for(lambda: any("DONE probe: TASK β asymmetric — proof" in text for text in messages()))
                start()
                scratch("now", "Review")
                scratch("flag", "stuck; tried tests; need review")
                result = settle(end())
                self.assertEqual(result["delivery_rule"], "contract_blocked")
                settle(end(reminder=True))
                exact = "FLAG probe step 2/2: stuck; tried tests; need review"
                self.assertEqual(sum(exact in text for text in messages()), 1)
                start()
                scratch("now", "Review", "--waiting", "reviewer", "--check", "10m")
                result = settle(end())
                self.assertEqual(result["delivery_rule"], "contract_waiting")
                wait_for(lambda: any("WAITING probe step 2/2: reviewer; checks again " in text for text in messages()))
                start()
                scratch("now", "Review", "--waiting", "reviewer", "--check", "2000-01-01T00:00:00Z")
                blocked(end())

    def test_contract_codex_stale_notify_basis_first_turn_with_steps_is_judged(self):
        p, launched = self.launch(contract=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        launch_id = launched["launch_id"]
        state = self.record(launch_id)
        state.update(turn_started_at=1, codex_last_notify_at=1)
        (self.registry / ("agents-" + launch_id + ".json")).write_text(json.dumps(state))
        scratch = subprocess.run([BIN, "scratch", "now", "Implement", "--session", state["target"]["session_id"],
                                  "--block", state["target"]["block_id"]], env=self.env, capture_output=True, text=True)
        self.assertEqual(scratch.returncode, 0, scratch.stdout + scratch.stderr)
        result = self.enforcement_hook(launch_id, "codex", dict(type="agent-turn-complete", **{
            "last-assistant-message": "cannot finish", "turn-id": "first-real-turn", "input-messages": ["work"]}), notify=True)
        self.assertEqual(result["scratchpad_check"]["action"], "reminded")
        self.assertEqual(result["scratchpad_check"]["reason"], CONTRACT_REFUSAL)
        self.assertLess(self.record(launch_id)["turn_started_at"], state["brief_attempt_at"])

    def test_contract_pi_generated_extension_continues_once(self):
        self.settings["profiles"]["probe"].update(harness="pi", hook_events=True)
        p, launched = self.launch(contract=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        state = self.record(launched["launch_id"])
        started = next(v for v in events(self.worker_log) if v["event"] == "started")
        extension = Path(started["argv"][started["argv"].index("--extension") + 1])
        script = r"""
import {readFileSync,writeFileSync} from 'node:fs';
const handlers={};
const mod=await import('data:text/javascript;base64,'+Buffer.from(readFileSync(process.argv[1])).toString('base64'));
mod.default({on:(name,handler)=>handlers[name]=handler});
await handlers.before_agent_start({prompt:'work'});
const pad=process.argv[2];
writeFileSync(pad,readFileSync(pad,'utf8').replace(/^Updated:.*$/m,'Updated: '+new Date().toISOString()));
const ack=await handlers.agent_before_settle({outcome:'completed',entries:[]});
if (ack?.continue) throw new Error('protocol ACK was refused');
await handlers.agent_settled({}, {sessionManager:{getBranch:()=>[]}});
await handlers.before_agent_start({prompt:'work'});
writeFileSync(pad,readFileSync(pad,'utf8').replace(/^Updated:.*$/m,'Updated: '+new Date().toISOString()));
const first=await handlers.agent_before_settle({outcome:'completed',entries:[]});
if (!first?.continue || first.entries[0].content !== process.argv[3] + '; write your steps first') throw new Error('contract did not continue');
const second=await handlers.agent_before_settle({outcome:'completed'});
if (second?.continue) throw new Error('contract refused twice');
await handlers.agent_settled({}, {sessionManager:{getBranch:()=>[]}});
"""
        result = subprocess.run(["node", "--input-type=module", "-e", script, str(extension), state["scratchpad"], CONTRACT_REFUSAL],
                                env=dict(self.env, AGENT_SCRATCHPAD=state["scratchpad"]), text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        wait_for(lambda: any("NO ANSWER probe:" in v.get("payload", "") for v in events(self.starter_log)))

    def test_claude_scratch_stop_blocks_once_fresh_turn_passes_and_no_env_skips(self):
        p, launched = self.launch()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        launch_id = launched["launch_id"]
        self.enforcement_hook(launch_id, "claude", dict(hook_event_name="UserPromptSubmit"))
        pad = Path(self.record(launch_id)["scratchpad"])
        pad.unlink()
        event = dict(hook_event_name="Stop", last_assistant_message="finished")
        self.assertEqual(self.enforcement_hook(launch_id, "claude", event)["decision"], "block")
        self.assertNotEqual(self.record(launch_id).get("last_hook", {}).get("kind"), "Stop")
        second = self.enforcement_hook(launch_id, "claude", event)
        self.assertEqual(second["scratchpad_check"]["status"], "stale")
        self.assertTrue(self.record(launch_id)["last_hook"]["scratchpad_check"]["already_reminded"])
        wait_for(lambda: any(v["event"] == "input" and "Scratchpad: stale; allow" in v["payload"] for v in events(self.starter_log)))
        self.enforcement_hook(launch_id, "claude", dict(hook_event_name="UserPromptSubmit"))
        self.assertEqual(subprocess.run([BIN, "scratch", "init", "--session", self.session, "--block", self.record(launch_id)["target"]["block_id"],
                                        "--purpose", "enforcement", "--intent", "updated"], env=self.env, capture_output=True).returncode, 0)
        fresh = self.enforcement_hook(launch_id, "claude", event)
        self.assertEqual(fresh["scratchpad_check"]["status"], "fresh")
        command = [BIN, "agents", "stop", "--registry", str(self.registry), "--launch-id", launch_id, "--event-file", "-"]
        env = dict(self.env)
        env.pop("AGENT_SCRATCHPAD", None)
        env.pop("LC_AGENT_SCRATCHPAD", None)
        pad.unlink()
        result = subprocess.run([BIN, "agents", "hook", "--harness", "claude", "--command-json", json.dumps(command), "--event-file", "-"],
                                input=json.dumps(event), env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("decision", json.loads(result.stdout))

    def test_codex_scratch_reminder_is_delivered_once_to_own_pane(self):
        p, launched = self.launch()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        launch_id = launched["launch_id"]
        Path(self.record(launch_id)["scratchpad"]).unlink()
        self.enforcement_hook(launch_id, "codex", dict(hook_event_name="UserPromptSubmit", prompt="real prompt"))
        event = dict(hook_event_name="Stop", last_assistant_message="finished")
        first = self.enforcement_hook(launch_id, "codex", dict(type="agent-turn-complete", **{"last-assistant-message": "finished", "turn-id": "original-turn", "input-messages": ["real prompt"]}), notify=True)
        self.assertEqual(first["scratchpad_check"]["action"], "reminded")
        reminder = "update your scratchpad (Now/To-do/Done) before ending the turn"
        wait_for(lambda: any(v["event"] == "input" and reminder in v["payload"] for v in events(self.worker_log)))
        second = self.enforcement_hook(launch_id, "codex", dict(type="agent-turn-complete", **{"last-assistant-message": "finished", "turn-id": "reminder-turn", "input-messages": ["FROM teerex-scratchpad: " + reminder]}), notify=True)
        self.assertTrue(second["scratchpad_check"]["already_reminded"])
        self.assertEqual(sum(v["event"] == "input" and reminder in v["payload"] for v in events(self.worker_log)), 1)
        third = self.enforcement_hook(launch_id, "codex", dict(type="agent-turn-complete", **{"last-assistant-message": "finished", "turn-id": "next-real-turn", "input-messages": ["new work"]}), notify=True)
        self.assertEqual(third["scratchpad_check"]["action"], "reminded")
        wait_for(lambda: sum(v["event"] == "input" and reminder in v["payload"] for v in events(self.worker_log)) == 2)
        target = self.record(launch_id)["target"]
        updated = subprocess.run([BIN, "scratch", "init", "--session", target["session_id"], "--block", target["block_id"],
                                  "--purpose", "updated", "--intent", "fresh"], env=self.env, capture_output=True)
        self.assertEqual(updated.returncode, 0)
        fresh = self.enforcement_hook(launch_id, "codex", dict(type="agent-turn-complete", **{"last-assistant-message": "finished", "turn-id": "updated-real-turn", "input-messages": ["finish work"]}), notify=True)
        self.assertEqual(fresh["scratchpad_check"]["status"], "fresh")

    def test_tint_false_keeps_theme_and_uses_child_record(self):
        self.settings["profiles"]["probe"].update(harness="codex", hook_events=True, tint=False)
        p, launched = self.launch(behavior="codex-hook")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        started = next(v for v in events(self.worker_log) if v["event"] == "started")
        block = self.record(launched["launch_id"])["target"]["block_id"]
        wait_for(lambda: self.program_state(block) == "idle")
        wait_for(lambda: any(v["event"] == "codex-hook" for v in events(self.worker_log)))
        self.rpc("com.superlogical.terminal.set_theme", dict(session_id=self.session, block_id=block, args=dict(background="#010203")))
        self.assertIn("rgb:0101/0202/0303", self.background(started["pid"]))
        self.assertFalse(any(a.startswith("hooks.UserPromptSubmit=") for a in started["argv"]))
        records = self.rpc("com.superlogical.terminal.program_status", dict(session_id=self.session, block_id=block, args={}))
        self.assertTrue(any(r.get("id") == "teerex" for r in records["records"]))

    def test_codex_notify_adapter_and_osc_idle_then_error_exit(self):
        self.settings["profiles"]["probe"].update(harness="codex", hook_events=True)
        p, launched = self.launch(behavior="codex-hook")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        launch_id = launched["launch_id"]
        wait_for(lambda: any(v["event"] == "codex-hook" for v in events(self.worker_log)))
        callback = next(v for v in events(self.worker_log) if v["event"] == "codex-hook")
        self.assertEqual(callback["code"], 0, callback)
        state = self.record(launch_id)
        self.assertEqual(state["last_hook"]["kind"], "Stop")
        self.assertEqual(state["last_hook"]["text"], "Codex settled β")
        self.assertIsNone(state["immediate_child_term"])
        block = state["target"]["block_id"]
        wait_for(lambda: self.program_state(block) == "idle")
        self.assertEqual(len([v for v in events(self.starter_log) if v["event"] == "input" and "Codex settled" in v["payload"]]), 0)
        os.kill(next(v["pid"] for v in events(self.worker_log) if v["event"] == "started"), signal.SIGTERM)
        wait_for(lambda: self.record(launch_id).get("immediate_child_term") is not None)
        wait_for(lambda: self.program_state(block) == "error")

    def test_pi_extension_settled_success_and_failure_reports(self):
        self.settings["profiles"]["probe"].update(harness="pi", hook_events=True)
        p, launched = self.launch(behavior="pi-hook")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        wait_for(lambda: any(v["event"] == "pi-hook" for v in events(self.worker_log)))
        callback = next(v for v in events(self.worker_log) if v["event"] == "pi-hook")
        self.assertEqual(callback["code"], 0, callback)
        state = self.record(launched["launch_id"])
        self.assertEqual(state["last_hook"]["kind"], "StopFailure")
        self.assertEqual(state["last_hook"]["text"], "Pi synthetic failure")
        self.assertIsNone(state["immediate_child_term"])
        wait_for(lambda: self.program_state(state["target"]["block_id"]) == "error")
        inputs = [v["payload"] for v in events(self.starter_log) if v["event"] == "input"]
        self.assertTrue(any("Pi settled β" in v for v in inputs), inputs)
        self.assertTrue(any("Pi synthetic failure" in v for v in inputs), inputs)

    def test_pi_extension_channel_uses_only_grant_directory_and_cleans_up(self):
        self.enable_channel()
        self.test_pi_extension_settled_success_and_failure_reports()
        started = next(v for v in events(self.worker_log) if v["event"] == "started")
        extension = Path(started["argv"][started["argv"].index("--extension") + 1])
        self.assertEqual(extension.parent.parent, self.delivery)
        self.assertTrue(extension.exists())
        self.assertNotIn("AGENT_REGISTRY", started["env"])
        os.kill(started["pid"], signal.SIGTERM)
        wait_for(lambda: not extension.parent.exists())

    def test_human_shell_replaces_function_tracks_without_starter_or_prompt(self):
        self.settings["profiles"]["probe"]["argv"][-1] = "human-exit"
        for key in ("starter_session", "starter_block"):
            self.settings["defaults"].pop(key)
        self.config.write_text(json.dumps(self.settings))
        p, _ = self.run_cli("shell", "--config", str(self.config))
        self.assertEqual(p.returncode, 0, p.stdout)
        launched = subprocess.run(["/bin/bash", "-c", "probe() { return 99; };\n" + p.stdout + "\nprobe"],
                                  capture_output=True, text=True, env=self.env, timeout=15)
        self.assertEqual(launched.returncode, 0, launched.stdout + launched.stderr)
        receipt = json.loads(launched.stdout)
        self.assertEqual(receipt["outcome"], "human_launched")
        wait_for(lambda: self.record(receipt["launch_id"]).get("immediate_child_term") is not None)
        state = self.record(receipt["launch_id"])
        self.assertTrue(state["tracked"])
        self.assertIsNone(state["starter"])
        self.assertIsNone(state["report_to"])
        self.assertFalse(state["protocol_acknowledged"])
        self.assertFalse(state["brief_attempted"])
        self.assertNotIn("Contract:", Path(state["protocol_file"]).read_text())
        self.assertEqual(state["immediate_child_term"], {"Exited": 0})
        started = next(v for v in events(self.worker_log) if v["event"] == "started")
        self.assertEqual(started["argv"], ["--explicit-standing-flag"])
        self.assertFalse(any(v["event"] == "protocol_argument" for v in events(self.worker_log)))
        wait_for(lambda: self.program_state(state["target"]["block_id"]) == "done")
        p = subprocess.run([BIN, "jobs", "list", "--registry", str(self.registry)], capture_output=True, text=True, env=self.env, timeout=15)
        self.assertEqual(p.returncode, 0, p.stdout)
        self.assertIn(state["target"]["block_id"], p.stdout)
        self.assertFalse(any(v["event"] == "input" for v in events(self.starter_log)))

    def test_human_remote_route_quotes_config_and_runs_once(self):
        ssh = self.work / "ssh"
        log = self.work / "ssh.json"
        ssh.write_text("#!" + sys.executable + "\nimport json,sys\nfrom pathlib import Path\nPath(" + repr(str(log)) + ").write_text(json.dumps(sys.argv[1:]))\n")
        ssh.chmod(0o700)
        targets = self.work / "targets.json"
        targets.write_text(json.dumps(dict(schema_version=1, hosts=dict(hive=dict(
            host_id="hive", transport="ssh", platform="linux-x86_64", home="/remote", socket="/remote/rex.sock",
            rex="/remote/rex", teerex="/remote/teerex", store="/remote/store", address="jrg@hive", port=22,
            identity_file="/fixture/key", known_hosts="/fixture/known_hosts")))))
        self.settings["human_route"] = dict(config=str(targets), host="hive", profiles="/remote/config 'quoted'.json")
        self.config.write_text(json.dumps(self.settings))
        self.env["PATH"] = str(self.work) + os.pathsep + self.env["PATH"]
        p, _ = self.run_cli("human", "--config", str(self.config), "--profile", "probe")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        argv = json.loads(log.read_text())
        self.assertIn("-tt", argv)
        self.assertEqual(argv[-2], "jrg@hive")
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertEqual(shlex.split(argv[-1]), ["/remote/teerex", "--rex", "/remote/rex", "agents", "human", "--config", "/remote/config 'quoted'.json", "--profile", "probe", "--routed"])
        self.assertEqual(list(self.registry.glob("agents-*.json")), [])

    def test_profiles_shell_and_refusals_leave_personal_settings_untouched(self):
        self.settings["profiles"]["claude"] = dict(argv=["/not/installed/claude"], harness="claude",
                                                       standing_flags=["--dangerously-skip-permissions"])
        self.settings["profiles"]["codex"] = dict(argv=["/not/installed/codex"], harness="codex",
                                                      standing_flags=["--dangerously-bypass-approvals-and-sandbox"])
        self.config.write_text(json.dumps(self.settings))
        p, profiles = self.run_cli("profiles", "--config", str(self.config))
        self.assertEqual(p.returncode, 0)
        self.assertEqual(profiles["profiles"]["codex"]["standing_flags"], ["--dangerously-bypass-approvals-and-sandbox"])
        self.assertFalse(profiles["security_settings_changed"])
        p, _ = self.run_cli("shell", "--config", str(self.config))
        self.assertEqual(p.returncode, 0)
        self.assertIn("claude() {", p.stdout)
        self.assertIn(shlex.quote(str(self.config)), p.stdout)
        self.assertNotIn("preserved existing", p.stdout)
        self.assertIn("agents human", p.stdout)
        self.assertNotIn("agents launch", p.stdout)
        # No launcher/shell config is sourced or modified by these commands.
        self.assertEqual(sorted(p.name for p in self.work.iterdir()),
                         ["brief.txt", "fixture.py", "profiles.json", "registry", "starter.jsonl"])
        self.registry.chmod(0o755)
        p, refusal = self.launch()
        self.assertEqual(p.returncode, 1)
        self.assertIn("private_owned_registry", refusal["failure_reason"])
        self.assertEqual(len(self.rpc("session.view", {"session_id": self.session})["windows"]), 1)


if __name__ == "__main__":
    unittest.main()
