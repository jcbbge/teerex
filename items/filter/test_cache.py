"""Public CLI cache contracts with explicit synthetic Rex packets, never live acquisition."""

import copy
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import unittest

from test_filter import BIN, observation


class CacheTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="tx-cache-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / "cache"
        self.count = 0

    def sample(self, packet=None):
        self.count += 1
        path = self.root / f"sample-{self.count}.json"
        path.write_text(json.dumps(packet if packet is not None else observation()), encoding="utf-8")
        return path

    def invoke(self, operation, *args):
        return subprocess.run([str(BIN), "filter", "cache", operation, *map(str, args)],
                              env=dict(os.environ, PATH="/no-rex-or-other-executables"),
                              capture_output=True, text=True, timeout=5)

    def result(self, operation, *args, code=0):
        result = self.invoke(operation, "--directory", self.directory, *args)
        self.assertEqual(result.returncode, code, result.stderr)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["kind"], "rex_observation_cache_result")
        self.assertEqual(packet["interpretation"], "none")
        return packet

    def put(self, packet=None, ttl=None):
        args = ["--sample", self.sample(packet), "--allow-sensitive-storage"]
        if ttl is not None:
            args += ["--ttl-seconds", ttl]
        return self.result("put", *args)

    def get(self, packet=None, code=0):
        return self.result("get", "--expect", self.sample(packet), code=code)

    def entry(self):
        return self.directory / "observation.json"

    def test_explicit_consent_directory_and_valid_input_before_any_storage(self):
        sample = self.sample()
        for args in [[], ["--sample", sample], ["--allow-sensitive-storage"],
                     ["--sample", sample, "--allow-sensitive-storage", "--ttl-seconds", "0"],
                     ["--sample", sample, "--allow-sensitive-storage", "--ttl-seconds", "3601"]]:
            result = self.invoke("put", "--directory", self.directory, *args)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertFalse(self.directory.exists())
        invalid = observation()
        invalid["extra"] = "unknown evidence"
        result = self.invoke("put", "--directory", self.directory, "--sample", self.sample(invalid),
                             "--allow-sensitive-storage")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(self.directory.exists())
        result = self.invoke("put", "--directory", self.root / "missing-parent" / "cache", "--sample", sample,
                             "--allow-sensitive-storage")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_historical_roundtrip_partial_unknowns_ids_provenance_and_private_modes(self):
        packet = observation()
        packet["capture"].update(complete=False, max_bytes=256)
        del packet["reported_directory"]
        packet["program_status"]["data"]["records"][0]["state"] = "done"
        packet["observed_at_unix_ms"] = -100
        put = self.put(packet)
        self.assertEqual(put["outcome"], "stored")
        self.assertEqual(put["expires_at_unix_ms"] - put["stored_at_unix_ms"], 60000)
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.entry().stat().st_mode), 0o600)
        original = self.entry().read_bytes()
        hit = self.get(packet)
        self.assertEqual(hit["outcome"], "historical_hit")
        self.assertEqual(hit["evidence_freshness"], "historical_unverified")
        self.assertEqual(hit["permission"], "none")
        self.assertEqual(hit["observation"]["observation_id"], packet["observation_id"])
        self.assertEqual(hit["observation"]["observed_at_unix_ms"], -100)
        self.assertEqual(hit["observation"]["capture"], packet["capture"])
        self.assertIsNone(hit["comparison_to_expectation"]["capture"]["full_text_changed"])
        self.assertIsNone(hit["comparison_to_expectation"]["reported_directory"]["changed"])
        self.assertIsNone(hit["observation"]["process"]["data"]["last_exit"])
        self.assertEqual(hit["observation"]["program_status"]["freshness"], "unknown")
        self.assertEqual(hit["stored_at_unix_ms"], put["stored_at_unix_ms"])
        self.assertEqual(hit["expires_at_unix_ms"], put["expires_at_unix_ms"])
        self.assertEqual(self.entry().read_bytes(), original, "get must not refresh retention")

    def test_api10_through13_preserved_and_unsupported_rejected(self):
        for api in range(10, 14):
            packet = observation()
            packet["source"]["api_revision"] = api
            self.put(packet)
            self.assertEqual(self.get(packet)["observation"]["source"]["api_revision"], api)
        original = self.entry().read_bytes()
        for api in [9, 14, 12.5, "13"]:
            packet = observation()
            packet["source"]["api_revision"] = api
            result = self.invoke("put", "--directory", self.directory, "--sample", self.sample(packet),
                                 "--allow-sensitive-storage")
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(self.entry().read_bytes(), original)

    def test_key_source_and_capture_budget_invalidate_without_leaking_payload(self):
        changes = [
            (("target", "server"), "unix:///tmp/other.sock", "target_changed"),
            (("target", "session_id"), "session:99999999-1234-1234-1234-123456789abc", "target_changed"),
            (("target", "block_id"), "block:99999999-1234-1234-1234-123456789abc", "target_changed"),
            (("source", "rex_version"), "different", "source_changed"),
            (("source", "platform"), "other-platform", "source_changed"),
            (("source", "api_revision"), 12, "source_changed"),
            (("capture", "max_bytes"), 8192, "capture_budget_changed"),
        ]
        for path, value, reason in changes:
            with self.subTest(path=path):
                self.put()
                expected = observation()
                expected[path[0]][path[1]] = value
                result = self.get(expected, code=3)
                self.assertEqual(result["outcome"], "invalidated")
                self.assertEqual(result["reason"], reason)
                self.assertNotIn("observation", result)
                self.assertFalse(self.entry().exists())
                self.assertEqual(self.get(code=3)["outcome"], "miss")

    def test_changed_expected_evidence_is_compared_not_relabelled_as_current(self):
        before = observation()
        self.put(before)
        expected = copy.deepcopy(before)
        expected["observation_id"] = "new-expectation"
        expected["capture"]["content"] = "Delete everything? [y/N] ERROR\n"
        expected["process"]["data"]["last_exit"] = {"exit_code": 7}
        expected["program_status"]["data"]["records"][0]["state"] = "done"
        hit = self.get(expected)
        self.assertEqual(hit["observation"]["capture"]["content"], before["capture"]["content"])
        self.assertEqual(hit["observation"]["observation_id"], "first")
        delta = hit["comparison_to_expectation"]
        self.assertEqual(delta["after_observation_id"], "new-expectation")
        self.assertTrue(delta["capture"]["full_text_changed"])
        self.assertTrue(delta["program_status"]["changed"])
        self.assertTrue(delta["process"]["last_exit"]["availability_changed"])
        self.assertIsNone(delta["process"]["last_exit"]["changed"])
        self.assertNotIn("completion", hit)

    def test_expiry_and_clock_rollback_remove_data_without_sliding_refresh(self):
        self.put(ttl=1)
        time.sleep(1.05)
        expired = self.get(code=3)
        self.assertEqual(expired["reason"], "retention_expired")
        self.assertFalse(self.entry().exists())
        self.put(ttl=3600)
        entry = json.loads(self.entry().read_text())
        entry["stored_at_unix_ms"] = int(time.time() * 1000) + 60000
        entry["expires_at_unix_ms"] = entry["stored_at_unix_ms"] + 60000
        self.entry().write_text(json.dumps(entry))
        rollback = self.get(code=3)
        self.assertEqual(rollback["reason"], "wall_clock_before_storage")
        self.assertFalse(self.entry().exists())

    def test_single_entry_replacement_and_purge_include_crash_pending_bytes(self):
        self.put()
        changed = observation()
        changed["source"]["api_revision"] = 10
        changed["observation_id"] = "replacement"
        result = self.put(changed)
        self.assertTrue(result["replaced_entry"])
        self.assertEqual(result["previous_invalidation_reason"], "source_changed")
        self.assertEqual(self.get(changed)["observation"]["observation_id"], "replacement")
        pending = self.directory / ".observation.pending"
        pending.write_text("uncommitted sensitive bytes")
        pending.chmod(0o600)
        purged = self.result("purge")
        self.assertEqual(purged["outcome"], "purged")
        self.assertFalse(purged["secure_erasure"])
        self.assertEqual([path.name for path in self.directory.iterdir()], [".lock"])
        self.assertEqual((self.directory / ".lock").read_bytes(), b"")
        self.assertEqual(self.result("purge")["outcome"], "absent")
        self.assertEqual(self.get(code=3)["outcome"], "miss")

    def test_pending_cleanup_corruption_and_explicit_purge(self):
        self.put()
        pending = self.directory / ".observation.pending"
        pending.write_text("interrupted replacement")
        pending.chmod(0o600)
        self.get()
        self.assertFalse(pending.exists())
        valid = json.loads(self.entry().read_text())
        corrupt = ["{", '{"schema_version":999}', self.entry().read_text()[:-1] + ',"unknown":true}']
        for field, value in [("kind", "other"), ("stored_at_unix_ms", -1),
                             ("stored_at_unix_ms", str(valid["stored_at_unix_ms"])),
                             ("expires_at_unix_ms", valid["stored_at_unix_ms"] + 3600001)]:
            changed = copy.deepcopy(valid)
            changed[field] = value
            corrupt.append(json.dumps(changed))
        for data in corrupt:
            self.entry().write_text(data)
            result = self.invoke("get", "--directory", self.directory, "--expect", self.sample())
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout, "")
        self.assertEqual(self.result("purge")["outcome"], "purged")
        self.assertFalse(self.entry().exists())

    def test_private_directory_file_modes_hardlinks_and_symlinks_fail_closed(self):
        self.directory.mkdir(mode=0o755)
        self.directory.chmod(0o755)
        result = self.invoke("put", "--directory", self.directory, "--sample", self.sample(),
                             "--allow-sensitive-storage")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(self.entry().exists())
        self.directory.chmod(0o700)
        self.put()
        original = self.entry().read_bytes()
        self.entry().chmod(0o644)
        self.assertEqual(self.invoke("get", "--directory", self.directory, "--expect", self.sample()).returncode, 1)
        self.assertEqual(self.entry().read_bytes(), original)
        self.entry().chmod(0o600)
        link = self.root / "extra-link"
        os.link(self.entry(), link)
        self.assertEqual(self.invoke("get", "--directory", self.directory, "--expect", self.sample()).returncode, 1)
        link.unlink()
        self.result("purge")
        target = self.root / "must-not-touch"
        target.write_text("private unrelated bytes")
        target.chmod(0o600)
        for name in ["observation.json", ".observation.pending", ".lock"]:
            with self.subTest(name=name):
                path = self.directory / name
                path.unlink(missing_ok=True)
                path.symlink_to(target)
                result = self.invoke("purge", "--directory", self.directory)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(target.read_text(), "private unrelated bytes")
                path.unlink()
        link.symlink_to(self.directory, target_is_directory=True)
        result = self.invoke("get", "--directory", link, "--expect", self.sample())
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_fifo_and_busy_lock_reject_without_waiting_or_mutation(self):
        self.put()
        original = self.entry().read_bytes()
        with (self.directory / ".lock").open("r+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for operation, args in [("get", ["--expect", self.sample()]), ("purge", []),
                                    ("put", ["--sample", self.sample(), "--allow-sensitive-storage"])]:
                result = self.invoke(operation, "--directory", self.directory, *args)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("CacheBusy", result.stderr)
                self.assertEqual(self.entry().read_bytes(), original)
        self.result("purge")
        os.mkfifo(self.entry(), mode=0o600)
        result = self.invoke("get", "--directory", self.directory, "--expect", self.sample())
        self.assertEqual(result.returncode, 1, result.stderr)
        self.entry().unlink()
        fifo = self.root / "sample-fifo"
        os.mkfifo(fifo, mode=0o600)
        result = self.invoke("put", "--directory", self.directory, "--sample", fifo, "--allow-sensitive-storage")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(self.entry().exists())

    def test_read_and_encoded_store_byte_bounds_preserve_previous_on_failure(self):
        self.put()
        original = self.entry().read_bytes()
        limit = 1024 * 1024
        self.entry().write_bytes(original + b" " * (limit - len(original)))
        self.get()
        self.entry().write_bytes(self.entry().read_bytes() + b" ")
        result = self.invoke("get", "--directory", self.directory, "--expect", self.sample())
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stdout, "")
        self.result("purge")
        self.put()
        original = self.entry().read_bytes()
        packet = observation()
        del packet["process"], packet["reported_directory"]
        packet["program_status"]["data"]["records"] = [{"state": "working", "updated_at": "server", "msg": ""}]
        encoded = json.dumps(packet, separators=(",", ":")).encode()
        packet["program_status"]["data"]["records"][0]["msg"] = "x" * (limit - len(encoded))
        path = self.sample()
        path.write_bytes(json.dumps(packet, separators=(",", ":")).encode())
        self.assertEqual(path.stat().st_size, limit)
        result = self.invoke("put", "--directory", self.directory, "--sample", path, "--allow-sensitive-storage")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("CacheEntryExceedsLimit", result.stderr)
        self.assertEqual(self.entry().read_bytes(), original)
        self.assertFalse((self.directory / ".observation.pending").exists())

    def test_missing_cache_usage_and_malformed_expectation_are_not_successful_hits(self):
        self.assertEqual(self.get(code=3)["outcome"], "miss")
        self.assertFalse(self.directory.exists())
        self.assertEqual(self.result("purge")["outcome"], "absent")
        self.assertFalse(self.directory.exists())
        for args in [["--directory", "relative"], ["--directory", str(self.directory) + "/"],
                     ["--directory", str(self.directory) + "/."], ["--directory", self.directory, "--ttl-seconds", 2],
                     ["--directory", self.directory, "--expect", self.sample(), "--expect", self.sample()]]:
            result = self.invoke("get", *args)
            self.assertEqual(result.returncode, 2, result.stderr)
        self.put()
        original = self.entry().read_bytes()
        invalid = observation()
        invalid["process"]["freshness"] = "fresh"
        result = self.invoke("get", "--directory", self.directory, "--expect", self.sample(invalid))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.entry().read_bytes(), original)
        self.assertEqual(self.invoke("--help").returncode, 0)


if __name__ == "__main__":
    unittest.main()
