"""Exercise resource ownership through real exits, signals and stale recovery."""
import ast
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_resources as resources

# This source runs in a different process: killing it must not kill this test.
FIXTURE = r'''
import json,os,pathlib,subprocess,sys,time
sys.path.insert(0, sys.argv[1])
import test_resources as resources
sys.argv[0] = 'resource-cleanup-fixture'
owner = resources.run()
if sys.argv[2] == 'sweep':
    print('swept', flush=True)
    sys.exit(0)
temp = resources.temporary_directory(prefix='teerex-cleanup-proof-', dir='/tmp')
root = pathlib.Path(temp.name)
rex = os.environ['REX_BIN']
socket = root / 'rex.sock'
log = (root / 'server.log').open('w')
server = resources.start_process([rex,'server','run','--listen','unix://'+str(socket),'--restore=false','--config','/dev/null','--state-dir',str(root/'state')],stdout=log,stderr=log)
base = [rex,'--autostart=false','--server','unix://'+str(socket),'--timeout','2s']
end=time.monotonic()+5
while not socket.exists():
    if server.poll() is not None or time.monotonic()>end:raise RuntimeError('server start failed')
    time.sleep(.01)
# Both a PTY child and an independently detached child must be reaped.
made = json.loads(subprocess.check_output([*base,'new','--json','--shell=none','--',sys.executable,'-c','import time;time.sleep(600)']))
child=resources.start_process([sys.executable,'-c','import subprocess,sys;subprocess.Popen([sys.executable,"-c","import time;time.sleep(600)"],start_new_session=True);sys.exit(0)'])
child.wait()
print(json.dumps(dict(root=str(root), journal=str(owner.root),server=server.pid,marker=owner.marker)),flush=True)
if sys.argv[2]=='fail':raise RuntimeError('deliberate fixture failure')
if sys.argv[2]=='pass':sys.exit(0)
while True:time.sleep(1)
'''


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.rex = os.environ.get('REX_BIN') or shutil.which('rex')
        if not self.rex:
            self.skipTest('Rex required')
        self.environment = dict(os.environ, REX_BIN=self.rex)
        self.info = None
        self.process = None
        self.addCleanup(self.cleanup)

    def spawn(self, mode):
        self.process = resources.start_process([sys.executable, '-c', FIXTURE,
            str(Path(__file__).resolve().parent), mode], env=self.environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertTrue(select.select([self.process.stdout], [], [], 15)[0], 'fixture not ready')
        line = self.process.stdout.readline()
        if not line:
            self.fail(self.process.stderr.read())
        self.info = json.loads(line)
        return self.process

    def cleanup(self):
        if self.process and self.process.poll() is None:
            self.process.kill()
            self.process.wait()
        self.sweep()

    def sweep(self):
        result = subprocess.run([sys.executable, '-c', FIXTURE, str(Path(__file__).resolve().parent), 'sweep'],
                                env=self.environment, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def assert_reaped(self):
        self.assertFalse(Path(self.info['root']).exists(), self.info)
        self.assertFalse(Path(self.info['journal']).exists(), self.info)
        result = subprocess.run(['ps', 'axeww', '-o', 'pid=,uid=,command='], capture_output=True, text=True)
        matches = [line.split(None,2)[0] for line in result.stdout.splitlines()
                   if self.info['marker'] + '=1' in line.split()]
        self.assertEqual(matches, [], 'owned descendants remain')

    def test_test_and_proof_allocators_use_owned_helpers(self):
        root = Path(__file__).resolve().parents[2]
        paths = {*root.glob('items/**/test*.py'), *root.glob('src/test*.py'),
                 *root.glob('tools/**/test*.py'), *root.glob('tools/acceptance/*.py')}
        unmanaged = []
        for path in paths:
            # F6 deliberately hands detached children to its enclosing proof,
            # which owns their inherited marker until after measuring survival.
            if path.name in ('test_resources.py', 'fail_fixture.py'):
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    if (node.func.value.id, node.func.attr) in {
                        ('tempfile', 'TemporaryDirectory'), ('tempfile', 'mkdtemp'), ('subprocess', 'Popen')}:
                        unmanaged.append(f'{path.relative_to(root)}:{node.lineno}')
        self.assertEqual(unmanaged, [])

    def test_replaced_directory_is_preserved(self):
        with resources.temporary_directory() as directory:
            path = Path(directory)
            stat = path.stat()
            resources.remove_directory(dict(path=str(path), identity=[stat.st_uid, stat.st_dev, stat.st_ino + 1]))
            self.assertTrue(path.exists())

    def test_pass_and_failure_reap_server_children_and_directories(self):
        for mode, code in [('pass', 0), ('fail', 1)]:
            with self.subTest(mode=mode):
                process = self.spawn(mode)
                out, err = process.communicate(timeout=20)
                self.assertEqual(process.returncode, code, err)
                self.assert_reaped()

    def test_interrupts_reap_and_sigkill_is_swept_by_same_helper(self):
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
            with self.subTest(signal=sig):
                process = self.spawn('wait')
                process.send_signal(sig)
                process.wait(timeout=20)
                self.assertEqual(process.returncode, -sig if sig == signal.SIGKILL else 128 + sig)
                if sig == signal.SIGKILL:
                    self.assertTrue(Path(self.info['root']).exists())
                    self.sweep()
                process.communicate(timeout=20)
                self.assert_reaped()

    def test_timeout_cleanup_and_foreign_directory_preserved(self):
        with resources.temporary_directory(prefix='teerex-cleanup-foreign-', dir='/tmp') as foreign:
            sentinel = Path(foreign) / 'keep'
            sentinel.write_text('not owned by fixture')
            process = self.spawn('wait')
            with self.assertRaises(subprocess.TimeoutExpired):
                process.communicate(timeout=.05)
            process.terminate()
            process.communicate(timeout=20)
            self.assert_reaped()
            self.assertEqual(sentinel.read_text(), 'not owned by fixture')

    def test_recovery_does_not_reap_an_active_run(self):
        process = self.spawn('wait')
        self.sweep()
        self.assertIsNone(process.poll())
        self.assertTrue(Path(self.info['root']).exists())
        process.terminate()
        process.communicate(timeout=20)
        self.assert_reaped()


if __name__ == '__main__':
    unittest.main()
