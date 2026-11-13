"""Agent-state contracts: offline weak-evidence cases and disposable drawn harness UIs."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

spec = importlib.util.spec_from_file_location("agent_state", Path(__file__).with_name("state.py"))
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
import test_observe as fixtures


def packet(text, name="python3", draft=False, status=None):
    return dict(capture=dict(content=text, eof=True), process=dict(child=dict(pid=1, name=name), foreground=None, last_exit=None),
                status=dict(records=status or []), draft_present=draft, editor_draft_present=None)


class ClassifyTest(unittest.TestCase):
    def test_all_harnesses_and_states_have_evidence(self):
        cases = [
            ("Claude Code\n❯\u00a0", "claude", "idle_prompt"),
            ("Claude Code\n✻ Thinking… (Esc to interrupt)\n❯\u00a0", "claude", "working"),
            ("· Gesticulating… (3h 31m 1s · ↓ 200.2k tokens)\n❯\u00a0", "claude", "working"),
            ("› Ask Codex to do anything", "codex", "idle_prompt"),
            ("• Working (19s • esc to interrupt)\n› Ask Codex to do anything", "codex", "working"),
            ("pi v1.4.0\n── ⠋ Working ─────\n\n────────────────", "pi", "working"),
            ("Claude Code\nDo you want to allow this command?\n❯ 1. Yes\n2. No\nEnter to confirm · Esc to cancel", "claude", "awaiting_choice"),
            ("›\nWould you like to run this command?\n› 1. Yes\n2. No\nEnter to confirm · Esc to cancel", "codex", "awaiting_choice"),
            ("pi v1.4.0\nProject trust\n→ Trust this project\nNo\n↑↓ navigate  Enter save  Esc cancel", "pi", "awaiting_choice"),
            ("pi v1.4.0\nType your answer:\n>\nEnter to submit · Esc to cancel", "pi", "awaiting_text"),
            ("Claude Code\nAPI Error: request failed\n❯", "claude", "error"),
            ("■ Unable to connect\n›", "codex", "error"),
            ("pi v1.4.0\nError: provider unavailable", "pi", "error"),
        ]
        for text, harness, state in cases:
            with self.subTest(text=text):
                result = reader.classify(packet(text))
                self.assertEqual((result["harness"], result["state"]), (harness, state))
                self.assertTrue(result["evidence_lines"])
                self.assertEqual(result["completion"], "not_inferred")

    def test_partial_conflicting_quoted_and_old_evidence_stay_unknown_or_idle(self):
        value = packet("• Working (2s • esc to interrupt)\n›")
        value["capture"].update(id=3, eof=False)
        self.assertEqual(reader.classify(value)["state"], "unknown")
        self.assertIsNone(reader.classify(value)["draft_present"])
        self.assertEqual(reader.classify(packet("Claude Code\n›"))["state"], "unknown")
        self.assertEqual(reader.classify(packet("text says Working, Error and completed"))["state"], "unknown")
        self.assertEqual(reader.classify(packet("Claude Code\n✻ old (Esc to interrupt)\n" + "old output\n" * 20 + "❯"))["state"], "idle_prompt")
        self.assertEqual(reader.classify(packet("API Error: command printed this\n" + "tool output\n" * 6 + "›"))["state"], "idle_prompt")
        self.assertEqual(reader.classify(packet("› historical agent prompt", name="zsh"))["state"], "unknown")

    def test_draft_text_is_not_copied_into_evidence(self):
        result = reader.classify(packet("› PRIVATE_UNFINISHED_DRAFT", draft=True))
        self.assertTrue(result["draft_present"])
        self.assertNotIn("PRIVATE_UNFINISHED_DRAFT", json.dumps(result))

    def test_shell_and_measured_exit_are_distinct_from_done_report(self):
        result = reader.classify(packet("jrg@hive %", name="zsh"))
        self.assertEqual((result["harness"], result["state"]), ("shell", "idle_prompt"))
        done = packet("", status=[dict(state="done")])
        self.assertEqual(reader.classify(done)["state"], "unknown")
        done["process"] = dict(child=None, foreground=None, last_exit=dict(exit_code=7))
        self.assertEqual(reader.classify(done)["state"], "exited")
        self.assertEqual(reader.classify(done)["completion"], "not_inferred")

    def test_osc_reports_are_preserved_with_unknown_freshness(self):
        for report, expected in ((dict(state="working"), "working"), (dict(state="error"), "error"),
                                 (dict(state="blocked", kind="permission"), "awaiting_choice"),
                                 (dict(state="blocked", kind="question"), "awaiting_text"),
                                 (dict(state="idle"), "unknown"), (dict(state="done"), "unknown")):
            result = reader.classify(packet("", status=[report]))
            self.assertEqual(result["state"], expected)
            self.assertEqual(result["osc7501"]["records"], [report])
            self.assertEqual(result["freshness"], "unknown")


class StateTest(fixtures.ObserveTest):
    def state(self, target, *extra):
        result = self.observe(target, "--state", *extra)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_drawn_claude_codex_placeholders_and_real_drafts(self):
        for prefix, placeholder, harness in (("❯\u00a0", "Try a suggestion", "claude"), ("› ", "Ask Codex to do anything", "codex")):
            with self.subTest(harness=harness):
                vt = "\x1b[2J\x1b[H" + prefix + "\x1b[2m\x1b[48;2;41;44;49m" + placeholder + "\x1b[0m\n"
                target = self.fixture(vt, marker=placeholder)
                result = self.state(target)
                self.assertEqual((result["harness"], result["state"], result["draft_present"]), (harness, "idle_prompt", False))
                typed = self.fixture(prefix + "PRIVATE_DRAFT\n", marker="PRIVATE_DRAFT")
                result = self.state(typed)
                self.assertTrue(result["draft_present"])
                self.assertNotIn("PRIVATE_DRAFT", json.dumps(result))

    def test_drawn_working_menus_questions_and_errors(self):
        for text, state in (("· Gesticulating… (3h 31m 1s · ↓ 200.2k tokens)\n❯\u00a0", "working"),
                            ("Claude Code\n✻ Thinking… (Esc to interrupt)\n❯\u00a0", "working"),
                            ("• Working (19s • esc to interrupt)\n› Ask Codex to do anything", "working"),
                            ("Claude Code\nDo you trust this folder?\n❯ 1. Yes\n2. No\nEnter to confirm · Esc to cancel", "awaiting_choice"),
                            ("pi v1.4.0\nProject trust\n→ Trust this project\nNo\n↑↓ navigate Enter save Esc cancel", "awaiting_choice"),
                            ("pi v1.4.0\nType your answer:\n>\nEnter to submit · Esc to cancel", "awaiting_text"),
                            ("API Error: unavailable\n❯", "error")):
            with self.subTest(state=state, text=text):
                target = self.fixture(text + "\n", marker=text.splitlines()[0])
                result = self.state(target)
                self.assertEqual(result["state"], state)
                self.assertTrue(result["evidence_lines"])

    def test_pi_editor_uses_shared_style_filter_and_real_text(self):
        for content, expected in (("\x1b[2mType a message\x1b[22m", False), ("PRIVATE_PI_DRAFT", True)):
            text = "pi v1.4.0\n────────────────────\n" + content + "\n────────────────────\n"
            target = self.fixture(text, marker="pi v1.4.0")
            result = self.state(target)
            self.assertEqual((result["harness"], result["state"], result["draft_present"]), ("pi", "idle_prompt", expected))
            self.assertNotIn("PRIVATE_PI_DRAFT", json.dumps(result))

    def test_partial_capture_is_unknown_and_no_input_is_sent(self):
        target = self.fixture("old text\n" * 500 + "› Ask Codex to do anything\n", marker="old text")
        result = self.state(target, "--max-bytes", "256")
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["reason"], "partial_capture")
        self.assertIsNone(result["draft_present"])
        self.assertTrue(result["read_only"])
        self.assertFalse(result["atomic_snapshot"])

    def test_real_exit_and_retained_done_are_not_completion(self):
        target = self.fixture("STATE_EXIT\n", after_output="sys.exit(7)")
        self.wait_for(target, "process", lambda v: v.get("last_exit") is not None and not v.get("child") and not v.get("foreground"))
        result = self.state(target)
        self.assertEqual(result["state"], "exited")
        self.assertEqual(result["completion"], "not_inferred")
        target = self.fixture("\x1b]7501;state=done:app=codex\x07STATE_REPORT\n", marker="STATE_REPORT")
        result = self.state(target)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["osc7501"]["records"][0]["state"], "done")

    def test_root_socket_default_and_separate_tail_mode(self):
        command = [str(fixtures.BIN), "observe", "--state", "--session", self.a[0], "--block", self.a[1]]
        result = subprocess.run(command, env=dict(os.environ, REX_SERVER=self.endpoint), capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value["socket_source"], "REX_SERVER")
        self.assertEqual(value["target"]["server"], self.endpoint)
        self.assertNotIn("socket_source", self.state(self.a))
        result = self.observe(self.a, "--state", "--tail")
        self.assertEqual(result.returncode, 2)

    def test_bad_options_and_missing_targets_never_guess(self):
        result = self.observe(self.a, "--state", "--state")
        self.assertNotEqual(result.returncode, 0)
        result = self.observe(self.a, "--state", "--max-bytes", "12")
        self.assertEqual(result.returncode, 2)
        result = self.observe((self.a[0], "block:00000000-0000-0000-0000-000000000000"), "--state")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["state"], "unknown")


def load_tests(loader, suite, pattern):
    return unittest.TestSuite([loader.loadTestsFromTestCase(ClassifyTest), unittest.TestSuite(
        StateTest(name) for name in StateTest.__dict__ if name.startswith("test_"))])


if __name__ == "__main__":
    unittest.main()
