"""H06 D1–D15, through the public CLI and private disposable fixtures."""
import json
import subprocess
import unittest
from test_records import RecordsFixture


class Decisions(RecordsFixture):
    def setUp(self):
        super().setUp()
        self.program = self.root / "ver.sh"
        self.program.write_text("#!/bin/sh\necho 'teerex alpha.5'\n")
        self.program.chmod(0o700)
        self.repo = self.root / "repo"
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "fixture"], check=True)
        self.ghstate = self.root / "gh-state"
        self.ghstate.write_text('{"state":"OPEN","stateReason":null}')
        self.gh = self.root / "gh"
        self.gh.write_text("#!/bin/sh\ncat '" + str(self.ghstate) + "'\n")
        self.gh.chmod(0o700)
        self.new(kind="decision")
        self.evidence = self.root / "authority.txt"
        self.evidence.write_text("synthetic authority")
        self.call("attach", "--id", "a", "--by", "worker", "--evidence", self.evidence)
        self.pin("program_version", self.program)
        self.pin("git_ref", str(self.repo) + "@HEAD")
        self.pin("gh_issue_state", "fixture/repo#13", "--gh", self.gh)
        self.claim("version assumption", "p1")
        self.claim("git assumption", "p2")
        self.k = dict(decision=dict(text="Use one collector", decided_by="worker", authority="agent_rubric", authority_ref="e1", decided_at="2026-11-13T00:00:00Z"), because=["k1"], options=[dict(id="o1", label="one", status="chosen", why="one source"), dict(id="o2", label="two", status="rejected", why="duplicates", revisit_when=[dict(pin="p3", becomes="CLOSED:NOT_PLANNED")], revisit_text="if dropped")], invalidators=[dict(id="v1", text="manual review")], card_id=None)
        self.decide()

    def gen(self):
        return self.read()["generation"]

    def pin(self, typ, target, *args):
        return self.call("pin", "add", "--id", "a", "--by", "worker", "--type", typ, "--target", target, *args)

    def claim(self, text, depends="", *args):
        return self.call("add", "claim", "--id", "a", "--by", "claim-author", "--text", text, "--basis", "inferred", "--depends-on", depends, *args)

    def decide(self, code=0):
        return self.call("decide", "--id", "a", "--by", "worker", "--expect-generation", self.gen(), fields=self.k, code=code)

    def revalidate(self, *args):
        return self.call("revalidate", "--id", "a", *args)["results"][0]

    def choose(self, *args, code=0):
        return self.call("set", "--id", "a", "--expect-generation", self.gen(), 'kind_fields.options.o2.status="chosen"', *args, code=code)

    def test_D1_version_only_dependents(self):
        self.program.write_text("#!/bin/sh\necho 'teerex alpha.6'\n")
        v = self.revalidate("--write")
        self.assertEqual(v["claims"], {"k1": "stale", "k2": "provisional"})
        self.assertEqual(v["reasons"], ["k1 stale"])
        self.assertEqual((v["pins"][0]["recorded_value"], v["pins"][0]["last_value"]), ("teerex alpha.5", "teerex alpha.6"))

    def test_D2_unrelated_file(self):
        (self.repo / "unrelated").write_text("new")
        v = self.revalidate()
        self.assertFalse(v["needs_review"])
        self.assertEqual(v["pins"][1]["last_result"], "unchanged")

    def contradiction(self):
        other = self.root / "other-evidence.txt"
        other.write_text("synthetic contradictory observation")
        self.call("attach", "--id", "a", "--by", "worker", "--evidence", other)
        self.call("add", "claim", "--id", "a", "--by", "worker", "--text", "send succeeded", "--basis", "observed", "--evidence", "e1")
        self.call("add", "claim", "--id", "a", "--by", "worker", "--text", "pane shows no message", "--basis", "observed", "--evidence", "e2", "--contradicts", "k3")
        self.k["because"] = ["k3"]
        self.decide()

    def test_D3_bidirectional_and_immutable(self):
        self.contradiction()
        cs = self.read()["claims"]
        self.assertIn("k4", cs[2]["contradicts"])
        self.assertIn("k3", cs[3]["contradicts"])
        self.assertIn("k3 ⟷ k4", self.show()["reasoning"]["open_contradictions"])
        v = self.call("set", "--id", "a", "--by", "worker", "--expect-generation", self.gen(), 'claims.k3.text="different"', code=1)
        self.assertIn("claim_text_immutable", str(v))

    def test_D4_withdrawal_and_lint(self):
        self.contradiction()
        # Imported concluded fixture exercises lint without bypassing close's gate.
        p = self.store / "records/a/record.json"
        r = self.read(); r["state"] = "concluded"; p.write_text(json.dumps(r))
        self.assertIn("L10-open-contradiction", str(self.call("lint", "--id", "a", code=3)))
        self.call("claim-status", "--id", "a", "--claim", "k3", "--status", "withdrawn", "--by", "worker", "--reason", "counterexample", "--expect-generation", self.gen())
        self.call("lint", "--id", "a")
        self.assertEqual(len(self.read()["claims"][2]["status_history"]), 2)

    def test_D5_provisional_stays(self):
        self.call("close", "--id", "a", "--by", "worker", "--state", "concluded")
        for _ in range(3): self.revalidate("--write")
        self.assertEqual(self.read()["claims"][0]["status"], "provisional")
        self.assertEqual(self.show()["reasoning"]["claim_caveat"], "decided on provisional claims")

    def test_D6_not_due_open(self):
        self.assertEqual(self.revalidate("--network", "--gh", self.gh, "--write")["revisit_due"], [])
        self.choose("--by", "worker", code=1)

    def test_D7_wrong_closed_reason(self):
        self.ghstate.write_text('{"state":"CLOSED","stateReason":"COMPLETED"}')
        self.assertEqual(self.revalidate("--network", "--gh", self.gh)["revisit_due"], [])

    def test_D8_due_and_history(self):
        self.ghstate.write_text('{"state":"CLOSED","stateReason":"NOT_PLANNED"}')
        self.assertEqual(self.revalidate("--network", "--gh", self.gh, "--write")["revisit_due"], ["o2"])
        self.choose("--by", "worker")
        self.assertEqual(self.read()["kind_fields"]["options"][1]["history"][0]["status"], "chosen")

    def test_D9_override_requires_actor(self):
        self.choose("--override-reason", "operator requested", code=2)
        self.choose("--override-reason", "operator requested", "--by", "operator")
        self.assertEqual(self.read()["kind_fields"]["options"][1]["history"][0]["reason"], "operator requested")

    def test_D10_deleted_evidence(self):
        self.claim("authority assumption", "e1")
        self.k["because"] = ["k3"]; self.decide()
        self.evidence.unlink()
        v = self.revalidate("--write")
        self.assertEqual(v["evidence"][0]["availability_now"], "missing")
        self.assertEqual(v["claims"]["k3"], "stale")
        self.assertTrue(v["needs_review"])

    def test_D11_no_network(self):
        self.claim("issue assumption", "p3")
        self.gh.unlink()
        v = self.revalidate("--write")
        self.assertEqual(v["pins"][2]["last_result"], "not_rechecked")
        self.assertEqual(v["claims"]["k3"], "provisional")
        self.assertIn("k3", v["not_rechecked"])

    def test_D12_no_ttl(self):
        p = self.store / "records/a/record.json"
        r = self.read(); r["written_at"] = "2020-01-01T00:00:00Z"
        for pin in r["pins"]: pin["recorded_at"] = r["written_at"]
        p.write_text(json.dumps(r))
        self.assertEqual(self.revalidate("--write")["claims"]["k1"], "provisional")

    def test_D13_read_only(self):
        p = self.store / "records/a/record.json"; before = p.read_bytes()
        self.revalidate()
        self.assertEqual(p.read_bytes(), before)

    def test_D14_shape_and_state_gate(self):
        self.k["options"] = self.k["options"][:1]; self.decide()
        self.assertIn("L9-decision-shape", str(self.call("lint", "--id", "a", code=3)))
        self.call("set", "--id", "a", "--expect-generation", self.gen(), 'state="concluded"', code=1)
        self.call("close", "--id", "a", "--by", "worker", "--state", "concluded", code=3)

    def test_D15_export(self):
        self.revalidate("--write")
        v = self.call("export", "--id", "a")
        self.assertNotIn(str(self.evidence), json.dumps(v))
        self.assertEqual(v["pins"][0]["last_value"], "teerex alpha.5")
        self.assertEqual(v["claims"][0]["status"], "provisional")
        self.assertEqual(v["claims"][0]["status_history"][0]["by"], "claim-author")
        md = self.call("export", "--id", "a", "--format", "md")
        self.assertIn("Use one collector", md)
        self.assertIn("CLOSED:NOT_PLANNED", md)
        self.assertNotIn(str(self.evidence), md)
        shown = self.call("show", "--id", "a", "--format", "text")
        self.assertLess(shown.index("Decision:"), shown.index("Authority:"))
        self.assertLess(shown.index("needs_review:"), shown.index("Claim k1:"))
        self.k["options"][1]["revisit_text"] = "token=" + "z" * 25
        self.decide()
        self.assertEqual(self.read()["kind_fields"]["options"][1]["revisit_text"], "[REDACTED]")
        self.assertNotIn("z" * 25, json.dumps(self.call("export", "--id", "a")))
        legacy = self.read()
        legacy["kind_fields"]["options"][1]["revisit_text"] = "token=" + "z" * 25
        (self.store / "records/a/record.json").write_text(json.dumps(legacy))
        self.assertIn("secret_pattern", str(self.call("export", "--id", "a", code=1)))

    def test_pin_failures_unavailable_and_strict_decide(self):
        self.pin("supplied", "manual environment", "--value", "fixture")
        self.program.unlink()
        v = self.revalidate("--write")
        self.assertEqual(v["claims"]["k1"], "unverifiable")
        self.assertEqual(self.read()["claims"][0]["status"], "provisional")
        self.assertTrue(v["needs_review"])
        self.call("pin", "add", "--id", "a", "--by", "worker", "--type", "program_version", "--target", self.program, code=1)
        self.k["invalidators"] = [dict(id="v1", text="changed", pin="p99", condition="changes")]
        self.assertIn("unknown_pin", str(self.decide(code=1)))
        self.k["invalidators"] = [dict(id="v1", text="manual")]
        self.k["unexpected"] = "refuse"
        self.decide(code=1)

    def test_no_bulk_option_or_status_bypass(self):
        self.k["options"][1]["status"] = "chosen"
        self.assertIn("revisit_not_due", str(self.decide(code=1)))
        self.call("set", "--id", "a", "--expect-generation", self.gen(), 'claims.k1.status="accepted"', code=1)
        self.call("add", "claim", "--id", "a", "--by", "worker", fields={"claims": [dict(text="fake acceptance", basis="inferred", status="accepted")]}, code=1)
        self.call("set", "--id", "a", "--expect-generation", self.gen(), 'kind_fields.options=[]', code=1)

    def test_all_filter_and_friction_packet(self):
        self.new("other")
        v = self.call("revalidate", "--all", "--kind", "decision", "--write")
        self.assertEqual([r["id"] for r in v["results"]], ["a"])
        self.assertEqual(self.read("other")["generation"], 1)
        self.assertEqual(self.call("list", "--kind", "decision", "--needs-review"), [])
        packet = self.root / "friction.json"
        packet.write_text(json.dumps(dict(schema_version=1, kind="friction_report", candidates=[], defects=[], refused=[])))
        self.call("attach", "--id", "a", "--by", "worker", "--evidence", packet)
        self.assertEqual(self.read()["evidence"][-1]["type"], "teerex_friction")



if __name__ == "__main__":
    unittest.main()
