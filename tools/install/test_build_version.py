"""Install an actual local build through the unchanged fleet identity gate."""
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LocalBuildTest(unittest.TestCase):
    def test_build_identity_survives_fleet_install(self):
        binary = Path(os.environ.get('TEEREX_BIN', ROOT / 'zig-out/bin/teerex')).resolve()
        expected = os.environ.get('TEEREX_BUILD_VERSION')
        if expected is None:
            revision = subprocess.check_output(['git', 'rev-parse', '--short=12', 'HEAD'], cwd=ROOT, text=True).strip()
            expected = '0.1.0-alpha.6.main.' + revision
        self.assertEqual(subprocess.check_output([str(binary), '--version'], text=True).strip(), 'teerex ' + expected)
        tag = 'v' + expected
        target = 'aarch64-macos' if platform.system() == 'Darwin' else 'x86_64-linux'
        # A private root inside the real HOME exercises fleet's actual host and
        # path checks, with no launcher or live installation changes.
        with tempfile.TemporaryDirectory(prefix='.teerex-build-proof-', dir=Path.home()) as temporary:
            root = Path(temporary).resolve()
            asset = root / ('teerex-' + tag + '-' + target + '.tar.gz')
            with tarfile.open(asset, 'w:gz', format=tarfile.USTAR_FORMAT) as archive:
                for name, data in [('teerex', binary.read_bytes()), ('README.md', b'build proof'), ('RIGHTS.md', b'build proof')]:
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    member.mode = 0o755 if name == 'teerex' else 0o644
                    archive.addfile(member, io.BytesIO(data))
            (root / 'SHA256SUMS').write_text(hashlib.sha256(asset.read_bytes()).hexdigest() + '  ' + asset.name + '\n')
            prefix = root / 'installed'
            host = dict(host_id='proof', transport='local', home=str(Path.home().resolve()),
                        platform='macos-arm64' if target == 'aarch64-macos' else 'linux-x86_64',
                        socket=str(root / 'unused.sock'), rex=str(root / 'unused-rex'),
                        teerex=str(prefix / 'current/teerex'), store=str(root / 'store'),
                        install=dict(prefix=str(prefix)))
            config = root / 'hosts.json'
            config.write_text(json.dumps(dict(schema_version=1, hosts=dict(proof=host))))
            result = subprocess.run([str(binary), 'fleet', 'install', '--config', str(config), '--host', 'proof',
                                     '--version', tag, '--from', str(root), '--apply'], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report['ok'], report)
            self.assertEqual(report['hosts'][0]['verified_version'], 'teerex ' + expected)
            self.assertEqual(os.readlink(prefix / 'current'), 'versions/' + tag)
            self.assertEqual(subprocess.check_output([str(prefix / 'current/teerex'), '--version'], text=True).strip(), 'teerex ' + expected)


if __name__ == '__main__':
    unittest.main()
