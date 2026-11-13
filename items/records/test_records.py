"""R1–R24 and C1–C10: public CLI, private fixtures, disposable API13 Rex only."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

BIN = str(Path(os.environ.get("TEEREX_BIN", Path(__file__).resolve().parents[2] / "zig-out/bin/teerex")).resolve())
QUESTION = "SYNTHETIC_QUESTION_CANARY_9c41"
NOTES = "SYNTHETIC_NOTES_CANARY_51be"


class RecordsFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="trecords-", dir="/tmp")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = self.root / "store"
        self.env = dict(os.environ, HOME=str(self.root), TEEREX_CALL_LOG_DIR=str(self.root / "calls"),
                        REX_SERVER="unix:///poison", REX_SESSION="session:poison", REX_BLOCK="block:poison")
        self.fields = dict(question=QUESTION, next_action=dict(actor="worker", step="run the asymmetric cache check", stop_when="twenty iterations complete"), notes=NOTES)
        self.call("init")

    def call(self, operation, *args, fields=None, code=0, stdin=None):
        cmd = [BIN, "records", operation, "--store", str(self.store), *map(str, args)]
        if fields is not None:
            cmd += ["--fields-file", "-"]
            stdin = json.dumps(fields, ensure_ascii=False)
        r = subprocess.run(cmd, input=stdin, env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        for secret in (QUESTION, NOTES):
            self.assertNotIn(secret, r.stderr)
            if operation not in ("show", "resume", "list", "export"):
                self.assertNotIn(secret, r.stdout)
        try:
            value = json.loads(r.stdout) if r.stdout else None
        except ValueError:
            value = r.stdout
        return value

    def new(self, rid="a", kind="investigation", fields=None, *args):
        return self.call("new", "--id", rid, "--kind", kind, "--writer", "worker", *args,
                         fields=self.fields if fields is None else fields)

    def read(self, rid="a"):
        return json.loads((self.store / "records" / rid / "record.json").read_text())

    def show(self, rid="a"):
        return self.call("show", "--id", rid)

    def packet(self, name="failure", code=1, **changes):
        p = dict(schema_version=1, kind="run_visible_result", target=dict(host="fixture", server="unix:///fixture", session_id="session:fixture", block_id="block:fixture"),
                 source_version="synthetic", outcome="exit_reported", exit_report=dict(exit_code=code, signal=None), success=code == 0,
                 stdout=dict(full_complete=False), stderr=dict(full_complete=True), retry_safe=False, task_completion="not_assessed",
                 storage_dir_retained=False, all_descendants_verified_gone=False)
        p.update(changes)
        path = self.root / (name + ".json")
        path.write_text(json.dumps(p))
        return path

    def attach(self, path, rid="a", assertion="failed", code=0):
        return self.call("attach", "--id", rid, "--by", "worker", "--evidence", path, "--check-command", "cache check",
                         "--assertion", assertion, "--establishes", "unit behavior", "--does-not-establish", "deployment", code=code)

    def add_claim(self, basis="chosen", evidence=None, text="unit result", rid="a"):
        args = ["claim", "--id", rid, "--by", "worker", "--text", text, "--basis", basis]
        if evidence:
            args += ["--evidence", evidence]
        if basis == "supplied":
            args += ["--supplied-by", "human"]
        return self.call("add", *args)

    def set(self, *assignments, rid="a", fields=None, code=0):
        return self.call("set", "--id", rid, "--expect-generation", self.read(rid)["generation"], *assignments, fields=fields, code=code)


class RecordsTest(RecordsFixture):
    def test_R01_reasoning_first_git_identity_and_dirty_untracked(self):
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.check_call(["git", "init", "-q", str(repo)])
        (repo / "tracked").write_text("before")
        subprocess.check_call(["git", "-C", str(repo), "add", "tracked"])
        subprocess.check_call(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"])
        head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
        (repo / "tracked").write_text("after")
        (repo / "untracked α").write_text("file")
        index_before = (repo / ".git/index").stat().st_mtime_ns
        self.new("a", "investigation", None, "--git-repo", repo)
        self.assertEqual((repo / ".git/index").stat().st_mtime_ns, index_before)
        shown = self.call("show", "--id", "a", "--format", "text")
        self.assertLess(shown.index(QUESTION), shown.index("hypothesis"))
        self.assertIn("worker · run the asymmetric cache check · twenty iterations complete", shown)
        subject = self.read()["subject"]
        self.assertEqual(subject["commit"], head)
        self.assertEqual(subject["dirty"], "true")
        self.assertEqual(subject["untracked"], ["untracked α"])

    def test_R02_exit_zero_does_not_infer_assertion(self):
        for rid, assertion in (("a", "failed"), ("b", "passed")):
            self.new(rid)
            self.attach(self.packet("zero", 0), rid, assertion)
            r = self.read(rid)
            self.assertEqual(r["checks"][0]["process_exit"], "0")
            self.assertEqual(r["checks"][0]["assertion"], assertion)
            self.assertTrue(r["evidence"][0]["teerex"]["reported_success"])
            self.assertNotIn("success", r)

    def test_R03_explicit_assertion_required(self):
        self.new()
        before = self.read()
        self.call("attach", "--id", "a", "--by", "worker", "--evidence", self.packet(), "--check-command", "unit", code=2)
        self.assertEqual(before, self.read())

    def file_claim(self):
        self.new()
        path = self.root / "output.txt"
        path.write_text("asymmetric output")
        self.call("attach", "--id", "a", "--by", "worker", "--evidence", path)
        self.add_claim("observed", "e1")
        return path

    def test_R04_missing_observed_evidence_then_supplied(self):
        self.file_claim().unlink()
        self.assertEqual(self.show()["evidence"][0]["availability_now"], "missing")
        self.assertIn("L2-observed-evidence", [v["rule"] for v in self.call("lint", "--id", "a", code=3)["violations"]])
        self.set('claims.k1.basis="supplied"', 'claims.k1.supplied_by="human"')
        self.call("lint", "--id", "a")

    def test_R05_moved_reference_keeps_locator_history(self):
        old = self.file_claim()
        new = self.root / "moved.txt"
        old.rename(new)
        self.set("evidence.e1.locator=" + json.dumps(str(new)))
        e = self.show()["evidence"][0]
        self.assertEqual(e["moved_from"], [str(old)])
        self.assertEqual(e["availability_now"], "present")

    def test_R06_digest_mismatch_is_not_rewritten(self):
        path = self.file_claim()
        digest = self.read()["evidence"][0]["digest"]
        path.write_text("different")
        self.assertEqual(self.show()["evidence"][0]["availability_now"], "digest_differs")
        self.assertEqual(self.read()["evidence"][0]["digest"], digest)

    def test_R07_inbound_claim_grants_no_authority(self):
        v = self.call("new", "--kind", "handoff", "--id", "bad", "--writer", "worker",
                      fields=dict(self.fields, kind_fields=dict(direction="sideways")), code=1)
        self.assertEqual(v["failure_reason"], "invalid_field:kind_fields.direction")
        self.assertFalse((self.store / "records/bad").exists())
        f = dict(self.fields, next_action=None, kind_fields=dict(direction="inbound", **{"from": "human", "to": "worker"}, undo="revert change"),
                 claims=[dict(text="ship it", basis="supplied", supplied_by="human", evidence=[])])
        self.new(kind="handoff", fields=f)
        rules = [v["rule"] for v in self.call("lint", "--id", "a", code=3)["violations"]]
        self.assertIn("L8-handoff-authority", rules)
        self.set(fields={"next_action": self.fields["next_action"]})
        self.call("lint", "--id", "a")

    def test_R08_cleanup_export_omits_where_and_owner(self):
        self.new(fields=dict(self.fields, cleanup=dict(status="partial", items=[dict(what="remove scratch", where="private host", owner="private worker")])))
        self.assertEqual(self.show()["reasoning"]["cleanup"]["items"][0]["where"], "private host")
        exported = self.call("export", "--id", "a")
        self.assertEqual(exported["cleanup"]["status"], "partial")
        self.assertEqual(exported["cleanup"]["items"][0], dict(id="u1", what="remove scratch"))

    def test_R09_retained_storage_blocks_done(self):
        self.new()
        self.attach(self.packet(storage_dir_retained=True, storage_dir=str(self.root)))
        self.call("close", "--id", "a", "--state", "concluded", "--by", "worker", fields=dict(cleanup=dict(status="done", items=[])), code=3)
        self.assertEqual(self.read()["state"], "open")

    def test_R10_export_drops_private_notes_and_keeps_caveats(self):
        self.new(fields=dict(self.fields, notes="token=SYNTHETICTOKEN0000000000", uncertainty=dict(text="not a deployment check", confidence="low")))
        self.attach(self.packet())
        self.add_claim("observed", "e1")
        value = self.call("export", "--id", "a")
        raw = json.dumps(value)
        self.assertNotIn("SYNTHETICTOKEN", raw)
        self.assertNotIn("locator", value["evidence"][0])
        self.assertNotIn("target", value["evidence"][0]["teerex"])
        self.assertEqual(value["claims"][0]["basis"], "observed")
        self.assertFalse(value["evidence"][0]["teerex"]["output_complete"]["stdout"])
        self.assertEqual(value["evidence"][0]["teerex"]["carried_flags"]["task_completion"], "not_assessed")

    def test_R11_export_refuses_secret_caveat_without_output_file(self):
        self.new(fields=dict(self.fields, uncertainty=dict(text="token=SYNTHETICTOKEN0000000000", confidence="low")))
        out = self.root / "export.json"
        v = self.call("export", "--id", "a", "--out", out, code=1)
        self.assertEqual(v["failure_reason"], "secret_pattern:uncertainty.text")
        self.assertFalse(out.exists())
        self.assertNotIn("SYNTHETICTOKEN", json.dumps(v))

    def test_R12_caveats_cannot_be_made_private(self):
        self.new()
        self.assertEqual(self.set('private=["uncertainty"]', code=1)["failure_reason"], "invalid_field:private")

    def test_R13_unit_evidence_cannot_claim_production(self):
        self.new(kind="receipt", fields=dict(self.fields, kind_fields=dict(shipped_identity=dict(repo=str(self.root), commit="1" * 40))))
        self.attach(self.packet("unit", 0), assertion="passed")
        self.add_claim("observed", "e1", "fix verified in production")
        self.assertIn("L4-scope-words", [v["rule"] for v in self.call("lint", "--id", "a", code=3)["violations"]])
        self.call("close", "--id", "a", "--state", "concluded", "--by", "worker", code=3)

    def test_R14_vague_draft_is_lintable(self):
        self.new(fields=dict(self.fields, next_action=dict(actor="worker", step="keep digging", stop_when="unknown")))
        self.assertEqual(self.call("lint", "--id", "a", code=3)["violations"][0]["rule"], "L1-next-action")

    def test_R15_mutated_copy_fails_integrity(self):
        self.new()
        self.attach(self.packet())
        path = self.store / "records/a/evidence/e1.json"
        path.write_bytes(path.read_bytes() + b" ")
        self.assertIn("L5-packet-integrity", [v["rule"] for v in self.call("lint", "--id", "a", code=3)["violations"]])

    def test_R16_unsupported_packets_never_append(self):
        self.new()
        malformed = (Path(__file__).parent / "fixtures/malformed.json").read_bytes()
        for raw, reason in ((malformed, "unsupported_packet"), (b'{"kind":"x","schema_version":1,"observation_id":"bad"}', "unsupported_packet"),
                            (b'{not json', "unsupported_packet"), (b'{"kind":"run_result",' + b' ' * 1048576, "evidence_oversize:0")):
            path = self.root / "bad.json"
            path.write_bytes(raw)
            self.assertEqual(self.call("attach", "--id", "a", "--by", "worker", "--evidence", path, code=1)["failure_reason"], reason)
            self.assertEqual(self.read()["evidence"], [])
        v = self.call("attach", "--id", "a", "--by", "worker", "--evidence", "-", stdin="{" + " " * 1048576, code=1)
        self.assertEqual(v["failure_reason"], "evidence_oversize:0")
        self.assertEqual(self.read()["evidence"], [])

    def test_R17_experiment_pairs(self):
        for a, b in (("a", "b"), ("b", "a")):
            self.new(a, "experiment", dict(self.fields, kind_fields=dict(change_made="one variable", pair_with=b)))
        self.assertEqual(len(self.call("list")), 2)
        self.assertEqual(self.show()["reasoning"]["kind_fields"]["pair_with"], "b")

    def test_R18_nonblocking_lock_and_consecutive_ids(self):
        self.new()
        with (self.store / "lock").open("r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            v = self.call("add", "claim", "--id", "a", "--by", "worker", "--text", "chosen", "--basis", "chosen", code=1)
            self.assertEqual(v["failure_reason"], "store_busy")
        self.assertEqual(self.add_claim()["assigned"], ["k1"])
        self.assertEqual(self.add_claim()["assigned"], ["k2"])
        self.assertEqual(self.read()["generation"], 3)

    def test_R19_stale_generation_preserves_bytes(self):
        self.new()
        before = self.read()
        v = self.call("set", "--id", "a", "--expect-generation", "0", 'question="different"', code=1)
        self.assertEqual(v["failure_reason"], "generation_mismatch")
        self.assertEqual(self.read(), before)

    def test_R20_store_file_and_staging_hazards(self):
        self.new()
        self.store.chmod(0o755)
        self.assertEqual(self.call("show", "--id", "a", code=1)["failure_reason"], "store_hazard")
        self.store.chmod(0o700)
        record = self.store / "records/a/record.json"
        safe = self.root / "saved"
        record.rename(safe)
        record.symlink_to(safe)
        self.assertEqual(self.call("show", "--id", "a", code=1)["failure_reason"], "store_hazard")
        record.unlink()
        safe.rename(record)
        (record.parent / "record.json.tmp-0123456789abcdef").touch()
        self.assertEqual(self.call("show", "--id", "a", code=1)["failure_reason"], "staging_present")

    def test_R21_unicode_caps_controls_and_bidi(self):
        value = "é" * 2048
        self.new(fields=dict(self.fields, question=value))
        self.assertEqual(self.show()["reasoning"]["question"].encode(), value.encode())
        self.assertEqual(self.call("new", "--id", "b", "--kind", "investigation", "--writer", "worker", fields=dict(self.fields, question=value + "x"), code=1)["failure_reason"], "cap_exceeded:question")
        self.assertEqual(self.call("new", "--id", "b", "--kind", "investigation", "--writer", "worker", fields=dict(self.fields, question="bad\x01control"), code=1)["failure_reason"], "control_character:question")
        self.set(fields=dict(question="RTL \u202e text"))
        self.assertIn("\\u{202e}", self.call("show", "--id", "a", "--format", "text"))

    def test_R22_fields_file_unknown_conflicts_and_shape(self):
        self.new()
        self.assertEqual(self.call("new", "--id", "b", "--kind", "investigation", "--writer", "worker", fields=dict(self.fields, typo="hidden"), code=1)["failure_reason"], "unknown_field:typo")
        self.call("new", "--id", "b", "--kind", "investigation", "--writer", "worker", "--question", "flag", fields=self.fields, code=2)
        self.call("new", "--unknown-private-argument", QUESTION, code=2)
        self.assertEqual(self.call("new", "--id", "b", "--kind", "investigation", "--writer", "worker", fields=dict(self.fields, next_action="continue"), code=1)["failure_reason"], "invalid_field:next_action")

    def board_fixture(self):
        root = self.root / "boards"
        root.mkdir(mode=0o700)
        (root / "lock").touch(mode=0o600)
        self.seat = dict(host="fixture", server="unix:///fixture", session_id="session:fixture", block_id="block:fixture")
        self.board = dict(schema_version=1, generation=1, seats=[dict(target=self.seat, owner="worker", registered_at=1, records=[
            dict(kind="decision", at=1, **{"from": "worker"}, body=dict(id="q", title="Review", ask="PRIVATE BODY", context="PRIVATE CONTEXT", options=[], recommend="a"))])], fleet=[])
        self.board["seats"][0]["records"].insert(0, dict(kind="message", at=1, **{"from": "worker"}, body="PRIVATE MESSAGE"))
        self.board_path = root / "state.json"
        self.board_path.write_text(json.dumps(self.board))
        self.board_path.chmod(0o600)
        return root

    def test_R23_output_dir_board_card_and_supplied_commit(self):
        self.new()
        directory = self.root / "output"
        directory.mkdir()
        for name in ("stdout.full", "stderr.full", "argv.json", "env.json", "stdin"):
            (directory / name).write_text("PRIVATE CONTENT " + name)
        self.call("attach", "--id", "a", "--by", "worker", "--evidence-dir", directory)
        files = self.read()["evidence"][0]["files"]
        self.assertEqual(files["argv.json"], dict(private_contents_not_read=True))
        self.assertEqual(files["stdout.full"]["digest"], "sha256:" + hashlib.sha256((directory / "stdout.full").read_bytes()).hexdigest())
        board = self.board_fixture()
        self.call("attach", "--id", "a", "--by", "worker", "--card", board, "--card-id", "q", "--seat-host", "fixture", "--seat-socket", "/fixture", "--seat-session", "session:fixture", "--seat-block", "block:fixture")
        self.assertEqual(self.show()["evidence"][1]["card"]["state"], "open")
        self.board["seats"][0]["records"].append(dict(kind="resolution", body=dict(id="q", answer="PRIVATE ANSWER")))
        self.board_path.write_text(json.dumps(self.board))
        shown = self.show()
        self.assertEqual(shown["evidence"][1]["card"]["state"], "resolved")
        self.assertNotIn("PRIVATE ANSWER", json.dumps(shown))
        self.assertNotIn("PRIVATE BODY", json.dumps(shown))
        fake = self.root / "bin"
        fake.mkdir()
        (fake / "git").write_text("#!/bin/sh\nexit 91\n")
        (fake / "git").chmod(0o700)
        self.env["PATH"] = str(fake) + os.pathsep + self.env["PATH"]
        self.call("attach", "--id", "a", "--by", "worker", "--commit", self.root, "1" * 40)
        self.assertEqual(self.read()["evidence"][2]["basis"], "supplied")

    def test_R24_named_host_store_override_and_default(self):
        executable = self.root / "fake"
        executable.write_text("#!" + sys.executable + "\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n")
        executable.chmod(0o700)
        host = dict(host_id="fixture", transport="local", home=str(self.root), platform="linux-x86_64", socket="/fixture", rex="/absolute/rex", teerex=str(executable), store=str(self.root / "boards"), records_store=str(self.store))
        cfg = self.root / "hosts.json"
        cfg.write_text(json.dumps(dict(schema_version=1, hosts=dict(fixture=host))))
        def routed(*extra):
            r = subprocess.run([BIN, "--config", str(cfg), "--host", "fixture", "records", "list", *extra], env=self.env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)
        self.assertEqual(routed()[-2:], ["--store", str(self.store)])
        self.assertEqual(routed("--store", str(self.root)).count("--store"), 1)
        del host["records_store"]
        cfg.write_text(json.dumps(dict(schema_version=1, hosts=dict(fixture=host))))
        self.assertEqual(routed()[-1], str(self.root / ".local/state/teerex-records"))

    def test_supersedes_history_export_out_and_forget(self):
        self.new()
        self.set(fields=dict(question="New question"))
        self.assertEqual(self.read()["history"][0]["previous"], QUESTION)
        out = self.root / "safe.json"
        self.call("export", "--id", "a", "--out", out)
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)
        self.call("export", "--id", "a", "--out", out, code=1)
        self.new("b", "investigation", self.fields, "--supersedes", "a")
        self.assertEqual(self.read()["state"], "superseded_by:b")
        self.call("forget", "--id", "a", "--expect-generation", self.read()["generation"], "--reason", "test completed")
        self.assertFalse((self.store / "records/a").exists())

    def test_inherited_private_stdin_cancellation_releases_store_lock(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            cmd = [BIN, "records", "new", "--store", str(self.store), "--id", "interrupted", "--kind", "investigation", "--writer", "worker", "--fields-file", "-"]
            child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, text=True)
            child.stdin.write('{"question":"' + QUESTION)
            child.stdin.flush()
            with (self.store / "lock").open("r+") as probe:
                for _ in range(200):
                    try:
                        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        fcntl.flock(probe, fcntl.LOCK_UN)
                    except BlockingIOError:
                        break
                    time.sleep(.01)
                else:
                    child.kill()
                    child.communicate()
                    self.fail("controller did not acquire the disposable store lock")
            child.send_signal(sig)
            # Leave stdin open, so only the signal can end the blocked input read.
            child.wait(timeout=5)
            out = child.stdout.read()
            err = child.stderr.read()
            child.stdin.close()
            child.stdout.close()
            child.stderr.close()
            self.assertEqual(child.returncode, 128 + sig, out + err)
            self.assertNotIn(QUESTION, out + err)
            self.assertFalse((self.store / "records/interrupted").exists())
        self.new()

    def test_content_flags_packet_table_refs_and_log_privacy(self):
        self.call("new", "--id", "a", "--kind", "investigation", "--writer", "worker", "--question", QUESTION,
                  "--next-actor", "worker", "--next-step", "run check", "--next-stop-when", "one run", "--hypothesis", "cache ordering",
                  "--hypothesis-basis", "inferred", "--discriminating-experiment", "vary one delay", "--uncertainty", "fixture only", "--confidence", "low",
                  fields={"notes": NOTES})
        for fixture in sorted((Path(__file__).parent / "fixtures").glob("supported-*.json")):
            before = len(self.read()["evidence"])
            self.call("attach", "--id", "a", "--by", "worker", "--evidence", fixture)
            e = self.read()["evidence"][-1]
            self.assertEqual(len(self.read()["evidence"]), before + 1)
            self.assertEqual(e["teerex"]["exit"], dict(code=None, signal=None))
        self.call("attach", "--id", "a", "--by", "worker", "--ref", "human_report", "human report", "--supplied-by", "human")
        self.assertEqual(self.read()["evidence"][-1]["availability_at_attach"], "not_checked")
        self.call("export", "--id", "a", "--include", "evidence.e1.locator", code=1)
        for log in (self.root / "calls").glob("*.jsonl"):
            self.assertNotIn(QUESTION, log.read_text())
            self.assertNotIn(NOTES, log.read_text())



@unittest.skipUnless(os.environ.get("REX_BIN"), "REX_BIN selects a disposable API13 Rex")
class LiveRecordsTest(RecordsFixture):
    @classmethod
    def setUpClass(cls):
        cls.rex = str(Path(os.environ["REX_BIN"]).resolve())
        cls.tmp = tempfile.TemporaryDirectory(prefix="trecords-rex-", dir="/tmp")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.server_root = Path(cls.tmp.name)
        cls.socket = cls.server_root / "rex.sock"
        cls.base = [cls.rex, "--autostart=false", "--server", "unix://" + str(cls.socket), "--timeout", "3s"]
        cls.log = (cls.server_root / "server.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.start_server()
        cls.addClassCleanup(cls.stop_server)

    @classmethod
    def start_server(cls):
        cls.server = subprocess.Popen([cls.rex, "server", "run", "--listen", "unix://" + str(cls.socket), "--restore=false",
                                       "--config", "/dev/null", "--state-dir", str(cls.server_root / "state")], stdout=cls.log, stderr=cls.log)
        for _ in range(200):
            if cls.server.poll() is not None:
                raise RuntimeError("Disposable Rex startup failed")
            if cls.socket.exists():
                try:
                    cls.rpc("server.version", {})
                    return
                except subprocess.SubprocessError:
                    pass
            time.sleep(.02)
        raise RuntimeError("Disposable Rex startup deadline")

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
        return json.loads(subprocess.check_output(cls.base + ["api", "call", method, json.dumps(args)], timeout=5))

    def raw(self, *args, code=0, stdin=None):
        r = subprocess.run([BIN, *map(str, args)], env=self.env, input=stdin, capture_output=True, text=True, timeout=40)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        self.assertNotIn(QUESTION, r.stderr)
        self.assertNotIn(NOTES, r.stderr)
        return json.loads(r.stdout)

    def open_pane(self, label, *argv):
        return self.raw("surfaces", "open", "--socket", self.socket, "--session", self.session, "--layout", "tab", "--label", label,
                        "--", *(argv or ("/bin/sh", "-c", "printf 'target ready\\n'; sleep 180")))["actual"]["block_id"]

    def setUp(self):
        super().setUp()
        self.env["TEEREX_INTERNAL_REX"] = self.rex
        self.env["PATH"] = str(Path(self.rex).parent) + os.pathsep + self.env["PATH"]
        self.session = self.rpc("session.create", {"label": "records disposable"})["session_id"]
        self.addCleanup(self.destroy_session)
        self.anchor = self.open_pane("investigation")
        self.canary = self.root / "neighbour-bytes"
        script = self.root / "canary.py"
        script.write_text("import os,sys,termios,tty\nfrom pathlib import Path\ntty.setraw(0,termios.TCSANOW)\n"
                          "p=Path(sys.argv[1]);p.write_bytes(b'');print('ready',flush=True)\n"
                          "while True:\n b=os.read(0,4096)\n if not b: break\n with p.open('ab') as f: f.write(b)\n")
        self.neighbour = self.open_pane("neighbour", sys.executable, str(script), str(self.canary))
        for _ in range(200):
            if self.canary.exists():
                break
            time.sleep(.01)
        self.assertTrue(self.canary.exists())
        self.addCleanup(lambda: self.assertEqual(self.canary.read_bytes(), b""))

    def destroy_session(self):
        # C4 restarts the fixture, which legitimately destroys the old session.
        if any(s["session_id"] == self.session for s in self.rpc("session.list", {})["sessions"]):
            self.rpc("session.destroy", {"session_id": self.session})

    def view(self):
        return self.rpc("session.view", {"session_id": self.session})

    def park(self, rid="a", block=None, fields=None, observe="no", code=0, extra=()):
        return self.call("park", "--id", rid, "--writer", "worker", "--host", "fixture", "--socket", self.socket,
                         "--session", self.session, "--block", block or self.anchor, "--observe", observe, *extra,
                         fields=self.fields if fields is None else fields, code=code)

    def resume(self, rid="a", *args):
        return self.call("resume", "--id", rid, "--host", "fixture", *args)

    def test_C01_asymmetric_reasoning_observation_and_unicode(self):
        self.park(observe="yes")
        self.attach(self.packet())
        pane = self.open_pane("second investigation")
        question = "Warum schlägt 🧪 fehl? — مرحبا e\u0301"
        self.park("b", pane, dict(question=question, next_action=self.fields["next_action"]))
        a, b = self.resume(), self.resume("b")
        self.assertEqual(a["reasoning"]["question"], QUESTION)
        self.assertEqual(len(a["evidence"]), 2)
        self.assertEqual(a["target"]["now"]["status"], "available")
        self.assertEqual(b["evidence"], [])
        self.assertEqual(b["reasoning"]["question"].encode(), question.encode())
        self.assertIn("hypothesis", b["reasoning"]["missing"])
        self.assertIn("cleanup", b["reasoning"]["missing"])
        self.assertEqual(len(self.call("list")), 2)
        self.assertLess(list(a).index("reasoning"), list(a).index("evidence"))
        self.assertLess(list(a).index("evidence"), list(a).index("target"))

    def test_C02_incomplete_evidence_and_missing_mutated_copies(self):
        self.park()
        path = self.root / "observe.json"
        path.write_text(json.dumps(dict(schema_version=1, observation_id="synthetic", capture=dict(complete=False))))
        self.call("attach", "--id", "a", "--by", "worker", "--evidence", path)
        self.attach(self.packet(exit_report=None), assertion="unknown")
        path.unlink()
        copied = self.store / "records/a/evidence/e2.json"
        copied.write_bytes(copied.read_bytes() + b" ")
        evidence = self.resume()["evidence"]
        self.assertFalse(evidence[0]["teerex"]["output_complete"]["capture"])
        self.assertEqual(evidence[0]["availability_now"], "missing")
        self.assertEqual(evidence[0]["copy_availability_now"], "present")
        self.assertEqual(evidence[1]["teerex"]["exit"], dict(code=None, signal=None))
        self.assertEqual(evidence[1]["copy_availability_now"], "digest_differs")
        self.assertEqual(self.read()["checks"][0]["process_exit"], "unknown")

    def test_C03_absent_target_never_recreated(self):
        self.park()
        self.raw("surfaces", "close", "--socket", self.socket, "--session", self.session, "--pane", self.anchor)
        before = self.view()
        value = self.resume()
        self.assertEqual(value["target"]["now"]["status"], "absent")
        self.assertFalse(value["navigate"]["possible"])
        refused = self.call("navigate", "--id", "a", "--host", "fixture", "--focus", "yes", code=3)
        self.assertEqual(refused["outcome"], "refused_target")
        self.assertEqual(before, self.view())

    def test_C04_instance_change_and_different_host_zero_rex_calls(self):
        self.park()
        fake = self.root / "rex-probe"
        marker = self.root / "rex-was-called"
        fake.write_text("#!" + sys.executable + "\nfrom pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\nraise SystemExit(91)\n")
        fake.chmod(0o700)
        self.env["TEEREX_INTERNAL_REX"] = str(fake)
        value = self.call("resume", "--id", "a", "--host", "different-host")
        self.assertEqual(value["target"]["now"]["status"], "different_server")
        self.assertFalse(marker.exists())
        self.env["TEEREX_INTERNAL_REX"] = self.rex
        self.stop_server()
        self.start_server()
        self.assertEqual(self.resume()["target"]["now"]["status"], "server_instance_changed")

    def test_C05_file_hazards_capacity_and_no_partial_records(self):
        self.park()
        path = self.root / "fifo"
        os.mkfifo(path)
        self.assertEqual(self.call("attach", "--id", "a", "--by", "worker", "--evidence", path, code=1)["failure_reason"], "evidence_hazard:0")
        big = self.root / "fields.json"
        big.write_bytes(b" " * 65537)
        self.assertEqual(self.call("new", "--kind", "investigation", "--writer", "worker", "--id", "b", "--fields-file", big, code=1)["failure_reason"], "fields_oversize")
        record = self.store / "records/a/record.json"
        linked = self.root / "hardlink"
        os.link(record, linked)
        self.assertEqual(self.call("show", "--id", "a", code=1)["failure_reason"], "store_hazard")
        linked.unlink()
        moved = self.root / "store-moved"
        self.store.rename(moved)
        self.store.symlink_to(moved, target_is_directory=True)
        self.call("show", "--id", "a", code=1)
        self.store.unlink()
        moved.rename(self.store)
        with self.subTest("foreign owner evidence"):
            if os.getuid() != 0:
                self.skipTest("foreign UID case requires root; all other hazards still exercised")
            foreign = self.root / "foreign"
            foreign.write_text("foreign")
            os.chown(foreign, 65534, -1)
            self.assertEqual(self.call("attach", "--id", "a", "--by", "worker", "--evidence", foreign, code=1)["failure_reason"], "evidence_hazard:0")
        template = self.read()
        for i in range(4095):
            rid = "fixture-" + str(i)
            folder = self.store / "records" / rid
            folder.mkdir(mode=0o700)
            (folder / "evidence").mkdir(mode=0o700)
            template["id"] = rid
            fd = os.open(folder / "record.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(template, f)
        before = set((self.store / "records").iterdir())
        self.assertEqual(self.park("b", code=1)["failure_reason"], "store_full")
        self.assertEqual(set((self.store / "records").iterdir()), before)

    def test_C06_export_private_refusal_and_secret_caveat(self):
        self.park()
        value = self.call("export", "--id", "a")
        self.assertNotIn(NOTES, json.dumps(value))
        self.assertNotIn("target", value)
        self.assertEqual(self.call("export", "--id", "a", "--include", "notes", code=1)["failure_reason"], "private_field_export_refused:notes")
        self.set(fields=dict(uncertainty=dict(text="ghp_" + "A" * 36, confidence="low")))
        self.assertEqual(self.call("export", "--id", "a", code=1)["failure_reason"], "secret_pattern:uncertainty.text")

    def test_C07_real_run_failure_success_and_decision_card_without_answer(self):
        packets = []
        envfile = self.root / "env.json"
        envfile.write_text("{}")
        envfile.chmod(0o600)
        for label, program, code in (("failure", "/bin/false", 1), ("success", "/bin/true", 0)):
            value = self.raw("run-visible", "--socket", self.socket, "--session", self.session, "--cwd", self.root,
                             "--env-file", envfile, "--stdin-file", "/dev/null", "--app", "records", "--title", label,
                             "--output-dir", self.root / label, "--", program, code=code)
            path = self.root / (label + ".json")
            path.write_text(json.dumps(value))
            packets.append(path)
        digests = [hashlib.sha256(p.read_bytes()).hexdigest() for p in packets]
        self.park(extra=("--evidence", str(packets[0])))
        board = self.root / "board"
        board.mkdir(mode=0o700)
        common = ["--store", board, "--host", "fixture", "--socket", self.socket, "--session", self.session, "--block", self.anchor]
        self.raw("boards", "seat", "register", *common, "--owner", "worker")
        card = self.root / "card.json"
        card.write_text(json.dumps(dict(id="q", title="Review result", ask="Choose", context="records: teerex records resume --id a",
                                           options=[dict(label="a", gain="gain", lose="loss"), dict(label="b", gain="gain", lose="loss")], recommend="a")))
        self.raw("ask", *common, "--from", "worker", "--card-file", card)
        self.call("attach", "--id", "a", "--by", "worker", "--card", board, "--card-id", "q", "--seat-host", "fixture", "--seat-socket", self.socket,
                  "--seat-session", self.session, "--seat-block", self.anchor)
        self.assertEqual(self.resume()["evidence"][1]["card"]["state"], "open")
        self.raw("ask", *common, "--from", "worker", "--resolve", "q", "--answer", "PRIVATE ANSWER")
        self.attach(packets[1], assertion="passed")
        evidence = self.resume()["evidence"]
        self.assertEqual(evidence[0]["teerex"]["exit"]["code"], 1)
        self.assertFalse(evidence[0]["teerex"]["reported_success"])
        self.assertEqual(evidence[2]["teerex"]["exit"]["code"], 0)
        self.assertTrue(evidence[2]["teerex"]["reported_success"])
        self.assertEqual(evidence[2]["teerex"]["carried_flags"]["task_completion"], "not_assessed")
        self.assertEqual(evidence[1]["card"]["state"], "resolved")
        self.assertNotIn("PRIVATE ANSWER", json.dumps(evidence))
        self.assertNotIn("success", self.read())
        self.assertEqual(json.loads(packets[0].read_text())["success"], False)
        self.assertEqual([hashlib.sha256(p.read_bytes()).hexdigest() for p in packets], digests)

    def test_C08_twenty_read_cycles_touch_neither_store_nor_neighbour(self):
        self.park()
        def tree():
            return [(str(p.relative_to(self.store)), p.stat().st_size, p.stat().st_mtime_ns, p.stat().st_ino) for p in sorted(self.store.rglob("*"))]
        before, view = tree(), self.view()
        for _ in range(20):
            self.assertEqual(self.resume()["writes_performed"], 0)
            self.call("list")
            self.call("export", "--id", "a")
        self.assertEqual(before, tree())
        self.assertEqual(view, self.view())
        self.assertEqual(self.canary.read_bytes(), b"")

    def test_C09_explicit_navigation_only_focuses_recorded_pane(self):
        self.park()
        self.raw("surfaces", "focus", "--socket", self.socket, "--session", self.session, "--pane", self.neighbour)
        before = self.view()
        self.call("navigate", "--id", "a", "--host", "fixture", code=2)
        result = self.call("navigate", "--id", "a", "--host", "fixture", "--focus", "yes")
        self.assertEqual(result["outcome"], "focused_and_verified")
        self.assertEqual(result["focus"]["actual"]["block_id"], self.anchor)
        after = self.view()
        self.assertEqual(len(before["windows"]), len(after["windows"]))
        self.assertEqual({b["block_id"] for w in before["windows"] for l in w["layers"] for b in l["blocks"]},
                         {b["block_id"] for w in after["windows"] for l in w["layers"] for b in l["blocks"]})

    def test_remaining_availability_states_refuse_navigation(self):
        self.park(extra=("--target-check", "no", "--allow-unavailable-target", "yes"))
        self.assertEqual(self.resume()["target"]["now"]["status"], "available_unverified_instance")
        self.call("navigate", "--id", "a", "--host", "fixture", "--focus", "yes", code=3)
        self.assertEqual(self.resume("a", "--target-check", "no")["target"]["now"]["status"], "not_checked")
        self.new("no-target")
        self.assertEqual(self.resume("no-target")["target"]["now"]["status"], "no_target_recorded")
        path = self.store / "records/a/record.json"
        record = self.read()
        status = self.rpc("server.status", {})
        record["target_at_park"]["server_identity"] = dict(instance_id=status["instance_id"], host_id=status["host_id"])
        record["target_at_park"]["pane"] = dict(host_id="different-block-host")
        path.write_text(json.dumps(record))
        self.assertEqual(self.resume()["target"]["now"]["status"], "block_host_changed")
        record["target_at_park"]["server_identity"]["host_id"] = "different-server-host"
        path.write_text(json.dumps(record))
        self.assertEqual(self.resume()["target"]["now"]["status"], "different_server")
        record["target"]["server"] = "unix://" + str(self.root / "missing.sock")
        path.write_text(json.dumps(record))
        self.assertEqual(self.resume()["target"]["now"]["status"], "server_unreachable")
        record["target"]["server"] = "unix://" + str(self.socket)
        record["target_at_park"]["server_identity"]["host_id"] = status["host_id"]
        path.write_text(json.dumps(record))
        shim = self.root / "malformed-inspection-rex"
        shim.write_text("#!" + sys.executable + "\nimport subprocess,sys\n"
                        + "if 'api' in sys.argv:\n sys.exit(subprocess.run([" + repr(self.rex) + ",*sys.argv[1:]]).returncode)\n"
                        + "print('not a valid Rex frame')\n")
        shim.chmod(0o700)
        self.env["TEEREX_INTERNAL_REX"] = str(shim)
        self.assertEqual(self.resume()["target"]["now"]["status"], "unknown")

    def test_C10_concurrent_attach_and_stale_generation(self):
        self.park()
        cmd = [BIN, "records", "attach", "--store", str(self.store), "--id", "a", "--by", "worker", "--evidence", str(self.packet())]
        with (self.store / "lock").open("r+") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            children = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, text=True) for _ in range(2)]
            for p in children:
                out, err = p.communicate(timeout=10)
                self.assertEqual(p.returncode, 1, out + err)
                self.assertEqual(json.loads(out)["failure_reason"], "store_busy")
        self.attach(self.root / "failure.json")
        self.assertEqual(self.read()["generation"], 2)
        self.assertEqual(self.call("attach", "--id", "a", "--by", "worker", "--expect-generation", "1", "--evidence", self.packet("other", 0), code=1)["failure_reason"], "generation_mismatch")


if __name__ == "__main__":
    unittest.main()
