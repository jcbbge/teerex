"""Real caller identities for tests that control disposable Rex panes."""
import json
import os
import pty
from pathlib import Path
import subprocess
import threading
import time


def caller(test, rpc, env, root, session_id=None):
    """Keep the creator outside the subject session so its layout stays unchanged."""
    root = Path(root)
    env['XDG_STATE_HOME'] = str(root / 'authority-state')
    env['TEEREX_BOARDS_STORE'] = str(root / 'authority-boards')
    env['AGENT_REGISTRY'] = str(root / 'authority-agents')
    sid = session_id or rpc('session.create', dict(label='test caller ' + str(time.monotonic_ns())))['session_id']
    if session_id is None:
        test.addCleanup(lambda: rpc('session.destroy', dict(session_id=sid)))
    made = rpc('session.new_window', dict(session_id=sid, focus=False, layout=dict(block=dict(
        flavor='com.superlogical.terminal.shell', label='test caller',
        options=dict(command=['/bin/sleep', '3600'], exit=dict(on_completion=False))))))
    env.update(REX_SESSION=sid, REX_BLOCK=made['block_ids'][0],
               LC_REX_SESSION=sid, LC_REX_BLOCK=made['block_ids'][0])
    return env


def session(binary, socket, env, label):
    result = subprocess.run([binary, 'surfaces', 'session', 'ensure', '--socket', str(socket), '--label', label],
                            env=env, capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)['resolved']['session_id']


def operator(command, env, **kwargs):
    """Exercise the explicit human path, in an actual disposable interactive tty."""
    environment = {k: v for k, v in env.items() if not k.startswith(('AGENT_', 'LC_AGENT_'))}
    environment['TEEREX_OPERATOR'] = '1'
    at = 3 if len(command) > 2 and command[1] == '--rex' else 1
    return terminal([*command[:at], '--operator', *command[at:]], environment, **kwargs)


def terminal(command, env, **kwargs):
    """Drain the tty during execution; macOS may block before a long usage exits."""
    master, slave = pty.openpty()
    diagnostic = bytearray()
    def drain():
        while True:
            try:
                part = os.read(master, 65536)
            except OSError:
                return
            if not part:
                return
            diagnostic.extend(part)
    reader = threading.Thread(target=drain)
    reader.start()
    try:
        kwargs.pop('capture_output', None)
        text = kwargs.get('text', False)
        result = subprocess.run(command, env=env,
                                stdin=slave, stdout=subprocess.PIPE, stderr=slave, **kwargs)
        os.close(slave)
        slave = None
        reader.join()
        result.stderr = diagnostic.decode(errors='replace') if text else bytes(diagnostic)
        return result
    finally:
        if slave is not None:
            os.close(slave)
        reader.join()
        os.close(master)
