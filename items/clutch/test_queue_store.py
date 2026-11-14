"""Private queue storage checks independent of Rex transport."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("focus_queue", Path(__file__).resolve().parents[1] / "send/focus_queue.py")
queue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue)


class QueueStoreTest(unittest.TestCase):
    def test_restart_order_and_no_entry_cap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            root.chmod(0o700)
            state = root / ("a" * 64 + ".json")
            request = dict(socket="/tmp/queue-test.sock", session="session:" + "00000000-0000-0000-0000-000000000001",
                           pane="block:" + "00000000-0000-0000-0000-000000000002", sender="worker", body="held",
                           draft="guard", draft_wait_ms=0, timeout_ms=1000)
            state.write_text(json.dumps(dict(request, held=True)))
            state.chmod(0o600)
            ids = [queue.enqueue(state, request)["id"] for _ in range(1025)]
            restarted = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(restarted)
            messages = restarted.inspect(state, False)["messages"]
            self.assertEqual([m["id"] for m in messages], ids)
            self.assertEqual(len(set(ids)), 1025)
            state.unlink()
            self.assertEqual(restarted.enqueue(state, request), dict(outcome="released"))
            self.assertEqual(len(restarted.inspect(state, False)["messages"]), 1025)

    def test_missing_probe_does_not_create_store(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "absent" / ("a" * 64 + ".json")
            self.assertEqual(queue.inspect(state, False), dict(outcome="inspected", messages=[]))
            self.assertFalse(state.parent.exists())


if __name__ == "__main__":
    unittest.main()
