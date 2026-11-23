"""Owned resources for tests/proofs, including interrupted and abandoned runs.

Only records from this helper's private journal may be recovered. A PID alone,
file name prefix, or a session label is never ownership evidence.
"""
import atexit
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

_RUN = None


def identity(pid):
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart=', '-o', 'command='],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def stop(record):
    if record['identity'] is None or identity(record['pid']) != record['identity']:
        return
    # All sessions on this socket belong to this disposable server. Destroying
    # them reaps PTY children, which have their own process groups.
    close_sessions(record)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if identity(record['pid']) != record['identity']:
            break
        try:
            os.kill(record['pid'], sig)
        except ProcessLookupError:
            break
        deadline = time.monotonic() + 2
        while identity(record['pid']) == record['identity'] and time.monotonic() < deadline:
            time.sleep(.02)


def close_sessions(record):
    if record.get('server') and identity(record['pid']) == record['identity']:
        base = [record['rex'], '--autostart=false', '--server', record['server'], '--timeout', '2s']
        try:
            result = subprocess.run([*base, 'api', 'call', 'session.list', '{}'],
                                    capture_output=True, text=True, timeout=3)
            for session in json.loads(result.stdout).get('sessions', []):
                subprocess.run([*base, 'api', 'call', 'session.destroy', json.dumps(dict(session_id=session['session_id']))],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass


def remove_directory(record):
    path = Path(record['path'])
    try:
        stat = path.lstat()
        if not path.is_symlink() and (stat.st_uid, stat.st_dev, stat.st_ino) == tuple(record['identity']):
            shutil.rmtree(path)
    except FileNotFoundError:
        pass


class Run:
    def __init__(self):
        # Stable across checkouts, separate for each helper; never scan arbitrary
        # teerex-* directories or the personal Rex server.
        entry = Path(sys.argv[0]).resolve()
        parts = entry.parts
        key = '/'.join(parts[next((i for i, p in enumerate(parts) if p in ('items', 'tools', 'src')), len(parts)-1):])
        self.parent = Path('/tmp') / ('.teerex-test-resources-' + str(os.getuid())) / hashlib.sha256(key.encode()).hexdigest()
        self.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.parent.stat().st_uid != os.getuid() or self.parent.is_symlink():
            raise RuntimeError('unsafe test resource journal')
        for previous in self.parent.iterdir():
            self.recover(previous)
        self.root = self.parent / uuid.uuid4().hex
        self.root.mkdir(mode=0o700)
        self.lock = (self.root / 'lock').open('w')
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        self.marker = "TEEREX_TEST_OWNER_" + self.root.name
        os.environ[self.marker] = "1"
        # Keep fixture sockets in the system temp directory (Unix path limits),
        # while child CLIs put their transient storage inside this run journal.
        tempfile.gettempdir()
        os.environ["TMPDIR"] = str(self.root)
        self.records = []
        self.processes = []
        self.closed = False
        (self.root / 'owner').write_text(self.marker)
        self.save()
        atexit.register(self.close)
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self.interrupt)

    def interrupt(self, sig, frame):
        # Cleanup must finish even if a runner forwards a second signal.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            self.close()
        except BaseException as error:
            print('test resource cleanup failed: ' + str(error), file=sys.stderr, flush=True)
            os._exit(1)
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
        os._exit(128 + sig)

    def save(self):
        stage = self.root / 'resources.new'
        stage.write_text(json.dumps(self.records))
        stage.replace(self.root / 'resources.json')

    def add(self, record):
        self.records.append(record)
        self.save()

    @staticmethod
    def clean(records, marker):
        for record in reversed(records):
            if record['kind'] == 'pane':
                result = subprocess.run(record['command'], env=record['environment'], capture_output=True, text=True, timeout=15)
                if result.returncode and json.loads(result.stdout).get('failure_reason') not in ('target_not_found', 'pane_not_attached_terminal'):
                    raise RuntimeError('owned proof pane cleanup failed: ' + result.stdout)
        for record in reversed(records):
            if record['kind'] == 'process':
                stop(record)
        # The marker is inherited by descendants, including detached children.
        # Read only our UID's processes; never output their environment.
        result = subprocess.run(['ps', 'axeww', '-o', 'pid=,uid=,command='], capture_output=True, text=True)
        for line in result.stdout.splitlines():
            fields = line.split(None, 2)
            if len(fields) == 3 and fields[1] == str(os.getuid()) and (marker + '=1') in fields[2].split():
                pid = int(fields[0])
                if pid != os.getpid():
                    stop(dict(pid=pid, identity=identity(pid)))
        for record in reversed(records):
            if record['kind'] == 'directory':
                remove_directory(record)

    def recover(self, root):
        if root.is_symlink() or not root.is_dir() or root.stat().st_uid != os.getuid():
            return
        try:
            with (root / 'lock').open('r+') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    return
                records = json.loads((root / 'resources.json').read_text())
                marker = (root / 'owner').read_text()
                if marker != 'TEEREX_TEST_OWNER_' + root.name:
                    raise RuntimeError('invalid test owner marker')
                self.clean(records, marker)
                shutil.rmtree(root)
        except FileNotFoundError:
            return

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.clean(self.records, self.marker)
        for process in self.processes:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        shutil.rmtree(self.root)
        self.lock.close()
        for parent in (self.parent, self.parent.parent):
            try:
                parent.rmdir()
            except OSError:
                pass


def run():
    global _RUN
    if _RUN is None:
        _RUN = Run()
    return _RUN


def track_directory(path):
    stat = Path(path).lstat()
    run().add(dict(kind='directory', path=str(Path(path).resolve()), identity=[stat.st_uid, stat.st_dev, stat.st_ino]))
    return path


def temporary_directory(*args, **kwargs):
    run()
    if len(args) < 3:
        kwargs.setdefault('dir', '/tmp')
    directory = tempfile.TemporaryDirectory(*args, **kwargs)
    track_directory(directory.name)
    return directory


def mkdtemp(*args, **kwargs):
    run()
    if len(args) < 3:
        kwargs.setdefault('dir', '/tmp')
    return track_directory(tempfile.mkdtemp(*args, **kwargs))


class OwnedProcess(subprocess.Popen):
    def terminate(self):
        if hasattr(self, "resource_record"):
            close_sessions(self.resource_record)
        super().terminate()


def start_process(argv, *args, **kwargs):
    owner = run()
    env = dict(kwargs.get('env') or os.environ)
    env[owner.marker] = '1'
    kwargs['env'] = env
    process = OwnedProcess(argv, *args, **kwargs)
    owner.processes.append(process)
    command = list(map(str, argv)) if not isinstance(argv, str) else []
    record = dict(kind='process', pid=process.pid, identity=identity(process.pid))
    if 'server' in command and 'run' in command and '--listen' in command:
        endpoint = command[command.index('--listen') + 1]
        if not endpoint.startswith('unix://'):
            process.terminate()
            process.wait()
            raise ValueError('test Rex must use a private Unix socket')
        record.update(rex=command[0], server=endpoint)
    process.resource_record = record
    owner.add(record)
    return process
