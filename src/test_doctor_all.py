import contextlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import doctor_all
import targets

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools/acceptance'))
import test_resources as resources

doctor_all.targets = targets
doctor_all.WORKER_SOURCE = Path(doctor_all.__file__).read_text()


class DoctorAllTest(unittest.TestCase):
    def test_reports_each_failure_and_continues(self):
        with resources.temporary_directory() as directory:
            root = Path(directory)
            home = root / 'home'
            config_root = home / 'rexconfig'
            config_root.mkdir(parents=True)
            (config_root / 'teerex.version').write_text('versions/wrong')
            current = home / '.local/opt/teerex-managed/current'
            current.parent.mkdir(parents=True)
            current.symlink_to('versions/actual')
            profiles = home / '.config/teerex/profiles.json'
            profiles.parent.mkdir(parents=True)
            profiles.write_text(json.dumps({'profiles': {h: {'hook_events': True} for h in ('claude', 'codex')}}))
            host = dict(home=str(home), host_id='test', rex='/rex', teerex='/teerex', socket='/socket', transport='local')
            def invoke(argv):
                if 'server.version' in argv:
                    return 0, json.dumps({'rex_version': 'test', 'api_revision': 13}), ''
                if '--check' in argv:
                    return 1, 'drift: teerex build actual, pinned wrong', ''
                return 0, 'help', ''
            config = root / 'hosts.json'
            config.write_text(json.dumps({'schema_version': 1, 'hosts': {'good': host, 'bad': {}}}))
            with patch.object(targets, 'resolve_host', side_effect=[host, ValueError('bad host')]), patch.object(doctor_all, 'run_command', side_effect=invoke):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = doctor_all.main(['--all', '--config', str(config), '--json'])
            packet = json.loads(output.getvalue())
            self.assertEqual(code, 1)
            failures = [(h['host'], c['check']) for h in packet['hosts'] for c in h['checks'] if not c['ok']]
            self.assertEqual(failures, [('good', 'teerex_build'), ('bad', 'host_reachable')])
            self.assertTrue(all(c['fix'] for h in packet['hosts'] for c in h['checks']))

    def test_shared_pin_match_mismatch_and_missing(self):
        with resources.temporary_directory() as directory:
            home = Path(directory)
            root = home / 'rexconfig'
            (root / 'test/teerex').mkdir(parents=True)
            # A legacy pin must never affect the shared-pin result or act as fallback.
            (root / 'test/teerex/build-pin.txt').write_text('versions/actual')
            current = home / '.local/opt/teerex-managed/current'
            current.parent.mkdir(parents=True)
            current.symlink_to('versions/actual')
            host = dict(home=str(home), host_id='test', rex='/rex',
                        teerex='/teerex', socket='/socket')
            for pin, expected in [('versions/actual', True), ('versions/wrong', False), (None, False)]:
                with self.subTest(pin=pin):
                    pin_path = root / 'teerex.version'
                    if pin is None:
                        pin_path.unlink()
                    else:
                        pin_path.write_text(pin + '\n')
                    with patch.object(doctor_all, 'run_command', return_value=(0, '{}', '')):
                        check = doctor_all.inspect_host(host)[0]
                    self.assertEqual(check['check'], 'teerex_build')
                    self.assertEqual(check['ok'], expected)
                    self.assertEqual(check['fix'], str(root / 'install'))
                    if pin is not None:
                        self.assertEqual(check['detail'], f'installed versions/actual; pinned {pin}')


if __name__ == '__main__':
    unittest.main()
