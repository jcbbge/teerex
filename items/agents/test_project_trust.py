"""Focused TOML trust edits; all files are disposable."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import json
try:
    import tomllib
except ImportError:
    tomllib = None
import unittest


@unittest.skipUnless(tomllib is not None, "project trust opt-in requires Python 3.11+")
class ProjectTrustTest(unittest.TestCase):
    def setUp(self):
        self.ns = {"__name__": "trust_test"}
        source = Path(__file__).with_name("agents.py")
        channel = source.resolve().parents[2] / "src/scoped_channel.py"
        exec(compile(channel.read_text(), str(channel), "exec"), self.ns)
        exec(compile(source.read_text(), str(source), "exec"), self.ns)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "settings.toml"
        self.profile = {"project_trust_toml": str(self.path)}

    def ensure(self, cwd=None):
        self.ns["ensure_project_trust"](self.profile, str(cwd or self.root), None)

    def test_fresh_file_and_canonical_cwd(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.ensure(alias)
        self.assertEqual(tomllib.loads(self.path.read_text()),
                         {"projects": {str(self.root): {"trust_level": "trusted"}}})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_preserve_other_bytes_mode_and_project_values(self):
        before = b'# untouched\r\nsetting = "yes"\r\n'
        after = b'[other]\r\nvalue = 42 # untouched\r\n'
        table = ('[projects.' + repr(str(self.root)) + ']\r\n'
                 'note = """\n[looks_like_a_table]\n"""\r\n'
                 'trust_level = "untrusted" # replace\r\nkeep = true\r\n').encode()
        self.path.write_bytes(before + table + after)
        self.path.chmod(0o640)
        self.ensure()
        raw = self.path.read_bytes()
        self.assertTrue(raw.startswith(before))
        self.assertTrue(raw.endswith(after))
        values = tomllib.loads(raw.decode())["projects"][str(self.root)]
        self.assertTrue(values["keep"])
        self.assertEqual(values["note"], '[looks_like_a_table]\n')
        self.assertEqual(values["trust_level"], "trusted")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)

    def test_existing_table_without_trust(self):
        self.path.write_text('[projects.' + repr(str(self.root)) + ']\nkeep = true\n')
        self.ensure()
        self.assertTrue(tomllib.loads(self.path.read_text())["projects"][str(self.root)]["keep"])

    def test_already_trusted_has_no_write_or_lock(self):
        self.ensure()
        Path(str(self.path) + '.lock').unlink()
        initial = self.path.stat()
        self.ensure()
        self.assertEqual(self.path.stat().st_mtime_ns, initial.st_mtime_ns)
        self.assertEqual(self.path.stat().st_ino, initial.st_ino)
        self.assertFalse(Path(str(self.path) + '.lock').exists())

    def test_invalid_or_unreadable_refuses_before_lock_creation(self):
        self.path.write_text('invalid = [')
        with self.assertRaisesRegex(self.ns['Refusal'], 'project_trust_toml_update_failed'):
            self.ensure()
        self.assertEqual(self.path.read_text(), 'invalid = [')
        self.assertFalse(Path(str(self.path) + '.lock').exists())
        self.path.unlink()
        self.path.mkdir()
        with self.assertRaisesRegex(self.ns['Refusal'], 'project_trust_toml_update_failed'):
            self.ensure()
        self.assertFalse(Path(str(self.path) + '.lock').exists())

    def test_two_concurrent_writers_both_recorded(self):
        dirs = [self.root / 'one', self.root / 'two']
        for cwd in dirs:
            cwd.mkdir()
        with ThreadPoolExecutor() as pool:
            list(pool.map(self.ensure, dirs))
        projects = tomllib.loads(self.path.read_text())["projects"]
        self.assertEqual(set(projects), set(map(str, dirs)))
        self.assertTrue(all(p['trust_level'] == 'trusted' for p in projects.values()))

    def test_absent_key_no_change_and_remote_explicit_refusal(self):
        self.ns['ensure_project_trust']({}, '/does/not/exist', {'host': 'remote'})
        self.assertFalse(self.path.exists())
        with self.assertRaisesRegex(self.ns['Refusal'], 'requires_local_execution_host'):
            self.ns['ensure_project_trust'](self.profile, str(self.root), {'host': 'remote'})
        self.assertFalse(self.path.exists())


class ProjectTrustJsonTest(unittest.TestCase):
    def setUp(self):
        ProjectTrustTest.setUp(self)
        self.path = self.root / "settings.json"
        self.profile = {"project_trust_json": str(self.path)}

    def ensure(self, cwd=None):
        self.ns["ensure_project_trust_json"](self.profile, str(cwd or self.root), None)

    def test_fresh_file_canonical_cwd(self):
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.ensure(alias)
        self.assertEqual(json.loads(self.path.read_text()),
                         {"projects": {str(self.root): {"hasTrustDialogAccepted": True}}})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_existing_fields_and_mode_preserved(self):
        data = {"global": [1, "β", {"enabled": False}], "projects": {
            "/other": {"hasTrustDialogAccepted": False, "notes": "keep"},
            str(self.root): {"hasTrustDialogAccepted": False, "allowedTools": ["one"], "nested": {"value": 5}}}}
        self.path.write_text(json.dumps(data))
        self.path.chmod(0o640)
        self.ensure()
        data["projects"][str(self.root)]["hasTrustDialogAccepted"] = True
        self.assertEqual(json.loads(self.path.read_text()), data)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o640)

    def test_already_true_no_write_or_lock(self):
        self.ensure()
        Path(str(self.path) + '.lock').unlink()
        initial = self.path.stat()
        self.ensure()
        self.assertEqual(self.path.stat().st_mtime_ns, initial.st_mtime_ns)
        self.assertEqual(self.path.stat().st_ino, initial.st_ino)
        self.assertFalse(Path(str(self.path) + '.lock').exists())

    def test_invalid_json_or_shapes_refuse_before_lock(self):
        for raw in ('{"broken":', '[]', '{"projects": []}', '{"number": NaN}',
                    json.dumps({"projects": {str(self.root): None}})):
            with self.subTest(raw=raw):
                self.path.write_text(raw)
                with self.assertRaises(self.ns['Refusal']):
                    self.ensure()
                self.assertEqual(self.path.read_text(), raw)
                self.assertFalse(Path(str(self.path) + '.lock').exists())
        self.path.unlink()
        self.path.mkdir()
        with self.assertRaisesRegex(self.ns['Refusal'], 'project_trust_json_update_failed'):
            self.ensure()
        self.assertFalse(Path(str(self.path) + '.lock').exists())

    def test_concurrent_writers_both_recorded(self):
        dirs = [self.root / 'one', self.root / 'two']
        for cwd in dirs:
            cwd.mkdir()
        self.path.write_text('{"keep": 7}')
        with ThreadPoolExecutor() as pool:
            list(pool.map(self.ensure, dirs))
        data = json.loads(self.path.read_text())
        self.assertEqual(data['keep'], 7)
        self.assertEqual(set(data['projects']), set(map(str, dirs)))
        self.assertTrue(all(p['hasTrustDialogAccepted'] is True for p in data['projects'].values()))

    def test_absent_key_and_remote_refusal(self):
        self.ns['ensure_project_trust_json']({}, '/does/not/exist', {'host': 'remote'})
        self.assertFalse(self.path.exists())
        with self.assertRaisesRegex(self.ns['Refusal'], 'requires_local_execution_host'):
            self.ns['ensure_project_trust_json'](self.profile, str(self.root), {'host': 'remote'})
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()
