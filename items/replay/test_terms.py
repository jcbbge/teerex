"""H08 terms pinned to public CLI results; never touch a personal Rex server."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "items/observe"))
sys.path.insert(0, str(ROOT / "items/filter"))
sys.path.insert(0, str(ROOT / "items/run"))
import test_observe as observe
import test_cache as cache
import test_visible as visible


class OfflineTerms(unittest.TestCase):
    def setUp(self):
        self.fixture = observe.CompareTest("test_equal_evidence_ignores_packet_times_ids_and_object_key_order")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def compare(self):
        return self.fixture.compared()

    def test_equal(self):
        result = self.compare()
        self.assertIs(result["capture"]["captured_text_changed"], False)
        self.assertNotIn("idle", result)
        self.assertNotIn("completed", result)

    def test_changed_progress_is_not_cosmetic_M2(self):
        self.fixture.after["program_status"]["data"]["records"][0]["progress"] = 50
        result = self.compare()
        self.assertIs(result["program_status"]["changed"], True)
        self.assertNotIn("cosmetic", result)
        self.assertNotIn("success", result)

    def test_availability_changed(self):
        del self.fixture.after["reported_directory"]
        node = self.compare()["reported_directory"]
        self.assertTrue(node["availability_changed"])
        self.assertIsNone(node["changed"])

    def test_unknown_equal_prefixes_M1_and_wrong_double(self):
        self.fixture.before["capture"]["complete"] = False
        self.fixture.after["capture"]["complete"] = False
        value = self.compare()["capture"]["full_text_changed"]
        self.assertIsNone(value)
        # Deliberately wrong implementation: null -> false must fail this contract.
        def wrong_double(value):
            return False if value is None else value
        with self.assertRaises(AssertionError):
            self.assertIsNone(wrong_double(value))

    def test_incomplete_error_scrolled_off_M3(self):
        self.fixture.before["capture"].update(content="error: config invalid\n", complete=False)
        self.fixture.after["capture"].update(content="later prefix\n", complete=False)
        node = self.compare()["capture"]
        self.assertTrue(node["captured_text_changed"])
        self.assertIsNone(node["full_text_changed"])

    def test_cosmetic_has_no_implicit_view(self):
        self.fixture.after["capture"]["content"] = "spinner /\n"
        result = self.compare()
        self.assertTrue(result["capture"]["captured_text_changed"])
        self.assertNotIn("cosmetic", result)
        self.assertEqual(result["interpretation"], "none")

    def test_historical_M6(self):
        fixture = cache.CacheTest("test_historical_roundtrip_partial_unknowns_ids_provenance_and_private_modes")
        fixture.setUp()
        try:
            fixture.test_historical_roundtrip_partial_unknowns_ids_provenance_and_private_modes()
        finally:
            fixture.doCleanups()


class LiveTerms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        observe.ObserveTest.setUpClass()
        cls.addClassCleanup(observe.ObserveTest.doClassCleanups)

    def test_quiet_is_only_deadline(self):
        fixture = observe.ObserveTest("test_watch_quiet_deadline_is_not_completion_or_known_missing_evidence")
        try:
            fixture.test_watch_quiet_deadline_is_not_completion_or_known_missing_evidence()
        finally:
            fixture.doCleanups()

    def test_reported_done_is_not_exit_M4(self):
        fixture = observe.ObserveTest("test_watch_done_report_does_not_mean_the_process_exited")
        try:
            fixture.test_watch_done_report_does_not_mean_the_process_exited()
        finally:
            fixture.doCleanups()


class ExitTerms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        visible.VisibleTest.setUpClass()
        cls.addClassCleanup(visible.VisibleTest.doClassCleanups)

    def fixture(self):
        fixture = visible.VisibleTest("test_exit7_signal_and_silent_wait")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def test_exited_M5(self):
        result, packet = self.fixture().invoke("import sys;sys.exit(7)")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(packet["exit_report"]["exit_code"], 7)
        self.assertFalse(packet["success"])
        self.assertEqual(packet["task_completion"], "not_assessed")

    def test_completed_is_not_assessed(self):
        result, packet = self.fixture().invoke("pass")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(packet["task_completion"], "not_assessed")
        self.assertNotIn("completed", packet)


if __name__ == "__main__":
    unittest.main()
