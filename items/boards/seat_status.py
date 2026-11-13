"""Best-effort local tty report. The caller bounds this process independently of delivery."""
import contextlib
import datetime
import fcntl
import hashlib
import time
import tempfile
from pathlib import Path
import json
import os
import re
import stat
import subprocess
import sys


def write_status(pid, report):
    try:
        if sys.platform == "linux":
            tty = None
            for number in (0, 1, 2):
                try:
                    candidate = os.readlink('/proc/%d/fd/%d' % (pid, number))
                except OSError:
                    continue
                if re.fullmatch(r'/dev/pts/[0-9]+', candidate):
                    tty = candidate
                    break
            if tty is None:
                fields = Path('/proc/%d/stat' % pid).read_text().rsplit(')', 1)[1].split()
                number = int(fields[4]) & 0xffffffff
                device = os.makedev((number >> 8) & 0xfff, (number & 0xff) | ((number >> 12) & 0xfff00))
                if number:
                    for name in os.listdir('/dev/pts'):
                        if name.isdigit():
                            candidate = '/dev/pts/' + name
                            if os.stat(candidate).st_rdev == device:
                                tty = candidate
                                break
            if tty is None:
                return 'tty_unavailable'
        elif sys.platform == "darwin":
            name = subprocess.check_output(['ps', '-p', str(pid), '-o', 'tty='], timeout=.1).decode().strip()
            if not re.fullmatch(r'ttys[0-9A-Za-z]+', name):
                return 'tty_unavailable'
            tty = '/dev/' + name
        else:
            return 'unsupported_platform'
        if not re.fullmatch(r'/dev/(pts/[0-9]+|ttys[0-9A-Za-z]+)', tty):
            return 'tty_unavailable'
        fd = os.open(tty, os.O_WRONLY | os.O_NOCTTY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            if not stat.S_ISCHR(os.fstat(fd).st_mode):
                return 'tty_unavailable'
            raw = report.encode()
            return 'written' if os.write(fd, raw) == len(raw) else 'short_write'
        finally:
            os.close(fd)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return 'tty_unavailable'



TTL_SECONDS = 30 * 60


def native(socket, method, args):
    command = [os.environ.get('TEEREX_INTERNAL_REX') or 'rex', '--autostart=false', '--server', 'unix://' + socket,
               '--timeout', '1s', 'api', 'call', method, json.dumps(args)]
    value = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
    if value.returncode or len(value.stdout) > 262144:
        raise ValueError('status_read_unavailable')
    return json.loads(value.stdout)


def origin():
    return dict(session=os.environ.get('REX_SESSION') or os.environ.get('LC_REX_SESSION'),
                block=os.environ.get('REX_BLOCK') or os.environ.get('LC_REX_BLOCK'))


@contextlib.contextmanager
def ledger(socket, write=False):
    root = Path(os.environ.get('TEEREX_ASK_STATE_DIR') or os.path.expanduser('~/.local/state/teerex/asks'))
    if not write and not root.exists():
        yield []
        return
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    lock = None
    try:
        info = os.fstat(directory)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('private_ask_directory_required')
        lock = os.open('lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
            raise ValueError('private_ask_lock_required')
        end = time.monotonic() + 1
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= end:
                    raise ValueError('ask_ledger_busy')
                time.sleep(.01)
        name = hashlib.sha256(socket.encode()).hexdigest() + '.json'
        rows = []
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            pass
        else:
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1:
                    raise ValueError('private_ask_file_required')
                raw = stream.read(262145)
                if len(raw) > 262144:
                    raise ValueError('ask_ledger_too_large')
                rows = json.loads(raw)
                if not isinstance(rows, list) or len(rows) > 512:
                    raise ValueError('invalid_ask_ledger')
        yield rows
        if write:
            raw = json.dumps(rows).encode()
            if len(raw) > 262144 or len(rows) > 512:
                raise ValueError('ask_ledger_full')
            fd, path = tempfile.mkstemp(dir=str(root), prefix='.ask-')
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                os.replace(path, str(root / name))
                os.fsync(directory)
            finally:
                if os.path.exists(path):
                    os.unlink(path)
    finally:
        if lock is not None:
            os.close(lock)
        os.close(directory)


def inventory(socket):
    script = """local rows={}
for _,s in ipairs((rex.call('session.list') or {}).sessions or {}) do
 for _,b in ipairs((rex.call('session.list_blocks',{session_id=s.session_id}) or {}).blocks or {}) do
  if b.creator_name=='com.superlogical.terminal' then rows[#rows+1]={session=s.session_id,block=b.block_id,label=b.label} end
 end
end
io.write(rex.json.encode(rows))"""
    command = [os.environ.get('TEEREX_INTERNAL_REX') or 'rex', '--autostart=false', '--server', 'unix://' + socket,
               '--timeout', '1s', 'do', '-e', script]
    result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
    if result.returncode or len(result.stdout) > 262144:
        raise ValueError('status_inventory_unavailable')
    rows = json.loads(result.stdout)
    return rows if isinstance(rows, list) else []


def find_asker(socket, sender, source):
    if re.fullmatch(r'session:[0-9a-f-]{36}', source.get('session') or '') and re.fullmatch(r'block:[0-9a-f-]{36}', source.get('block') or ''):
        try:
            blocks = native(socket, 'session.list_blocks', dict(session_id=source['session'])).get('blocks', [])
            if any(b['block_id'] == source['block'] for b in blocks):
                return dict(session=source['session'], block=source['block'])
        except (ValueError, subprocess.SubprocessError):
            pass
    rows = inventory(socket)
    matches = [r for r in rows if r['label'] == sender and r['label'] != 'seat']
    return dict(session=matches[0]['session'], block=matches[0]['block']) if len(matches) == 1 else None


def clear(socket, target, record_id):
    process = native(socket, 'com.superlogical.terminal.process', dict(session_id=target['session'], block_id=target['block'], args={}))
    pid = (process.get('child') or {}).get('pid')
    if not pid:
        return False
    # IDs come from validated ask ids or the terminal's own status inventory.
    if not re.fullmatch(r'[A-Za-z0-9_./+%-]{1,1024}', record_id):
        raise ValueError('invalid_status_id')
    return write_status(pid, '\x1b]7501;state=clear:id=' + record_id + '\x1b\\') == 'written'


def register(context):
    asker = find_asker(context['socket'], context['sender'], context.get('origin') or {})
    row = dict(id=context['id'], seat=dict(session=context['session'], block=context['block']),
               asker=asker, sender=context['sender'], expires=time.time() + TTL_SECONDS)
    with ledger(context['socket'], True) as rows:
        rows[:] = [r for r in rows if not (r['id'] == row['id'] and r['seat'] == row['seat'])]
        rows.append(row)


def lookup(socket, seat, record_id):
    with ledger(socket) as rows:
        return next((dict(r) for r in rows if r['seat'] == seat and r['id'] == record_id), None)


def resolve(socket, seat, record_id):
    with ledger(socket) as rows:
        row = next((dict(r) for r in rows if r['seat'] == seat and r['id'] == record_id), None)
    if not clear(socket, seat, record_id):
        raise ValueError('status_clear_unavailable')
    with ledger(socket, True) as rows:
        rows[:] = [r for r in rows if not (r['seat'] == seat and r['id'] == record_id)]
    return row


def answered(context):
    source = context.get('origin') or {}
    if not re.fullmatch(r'session:[0-9a-f-]{36}', source.get('session') or '') or not re.fullmatch(r'block:[0-9a-f-]{36}', source.get('block') or ''):
        return
    target = dict(session=context['session'], block=context['block'])
    with ledger(context['socket']) as cards:
        matches = [dict(r) for r in cards if r['seat'] == source and r.get('asker') == target]
    if not matches:
        return
    blocks = native(context['socket'], 'session.list_blocks', dict(session_id=source['session'])).get('blocks', [])
    block = next((r for r in blocks if r['block_id'] == source['block']), None)
    if block is None:
        return
    if block.get('label') != 'seat':
        view = native(context['socket'], 'session.view', dict(session_id=source['session']))
        if not any(w.get('window_id') == block.get('window_id') and w.get('label') == 'seat' for w in view.get('windows', [])):
            return
    for card in matches:
        resolve(context['socket'], source, card['id'])


def expire(socket, live_rows):
    # The foreground fleet refresh is the clock; no per-card background timer.
    expired = []
    for row in live_rows:
        for record in (row.get('program_status') or {}).get('records', []):
            if not str(record.get('id', '')).startswith('ask/') or record.get('state') != 'blocked' or record.get('app') != 'teerex':
                continue
            try:
                timestamp = record['updated_at'].replace('Z', '+00:00')
                timestamp = re.sub(r'\.(\d+)', lambda match: '.' + match[1][:6].ljust(6, '0'), timestamp)
                at = datetime.datetime.fromisoformat(timestamp).timestamp()
            except (ValueError, KeyError):
                continue
            if time.time() - at >= TTL_SECONDS:
                expired.append((dict(session=row['session'], block=row['block']), record['id']))
    for target, record_id in expired:
        resolve(socket, target, record_id)
    return len(expired)


def apply(pid, report, context):
    outcome = write_status(pid, report) if report and pid else 'tty_unavailable' if report else 'not_requested'
    input_outcome = None
    try:
        if context.get('agent_input'):
            input_outcome = agent_input_write(context['socket'], context['session'], context['block'], context['input_at_ns'], reminder=context.get('sender') == 'teerex-scratchpad')
        if outcome == 'written' and context.get('state') == 'blocked' and str(context.get('id', '')).startswith('ask/'):
            register(context)
        if outcome == 'written' and context.get('state') == 'clear' and str(context.get('id', '')).startswith('ask/'):
            seat = dict(session=context['session'], block=context['block'])
            with ledger(context['socket'], True) as rows:
                rows[:] = [r for r in rows if not (r['seat'] == seat and r['id'] == context['id'])]
        with ledger(context['socket']) as rows:
            expired = [dict(r) for r in rows if r.get('expires', float('inf')) <= time.time()]
        for card in expired:
            resolve(context['socket'], card['seat'], card['id'])
        answered(context)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 'written_tracking_unavailable' if outcome == 'written' else 'tracking_unavailable'
    return input_outcome if input_outcome and outcome == 'not_requested' else outcome


if __name__ == '__main__':
    context = json.loads(sys.argv[3])
    context['agent_input'] = len(sys.argv) > 4 and sys.argv[4] == '1'
    if context['agent_input']:
        context['input_at_ns'] = int(sys.argv[5])
    print(json.dumps(apply(int(sys.argv[1]), sys.argv[2], context)))
