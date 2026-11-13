"""Pull-only decisions: proceed on the default unless Josh vetoes it."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import time

ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z')
MAX_FILE = 65536
MAX_DECISIONS = 512


def check(ok, why):
    if not ok:
        raise ValueError(why)


def text(value, limit=4096, empty=False):
    check(isinstance(value, str) and (empty or bool(value.strip())) and len(value.encode()) <= limit
          and not any(ord(c) < 32 and c not in '\n\t' for c in value) and '\x7f' not in value, 'invalid_text')
    return value


def identifier(value):
    check(isinstance(value, str) and ID.fullmatch(value), 'invalid_id_or_key')
    return value


def address(value, kind):
    check(isinstance(value, str) and re.fullmatch(kind + r':[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', value), 'canonical_asker_' + kind + '_required')
    return value


def private(fd, directory=False):
    info = os.fstat(fd)
    check(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600)
          and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1), 'private_owned_store_required')


class Store:
    def __init__(self, root):
        self.root = Path(root)
        check(self.root.is_absolute(), 'absolute_store_required')

    @contextlib.contextmanager
    def locked(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        lock = None
        try:
            private(directory, True)
            lock = os.open('lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
            private(lock)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('decisions_store_busy')
            self.directory = directory
            yield self
        finally:
            if lock is not None:
                os.close(lock)
            os.close(directory)

    def read(self, ident):
        fd = os.open(identifier(ident) + '.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.directory)
        with os.fdopen(fd, 'rb') as stream:
            private(stream.fileno())
            raw = stream.read(MAX_FILE + 1)
        check(len(raw) <= MAX_FILE, 'decision_too_large')
        row = json.loads(raw)
        check(row['id'] == ident, 'decision_id_mismatch')
        validate(row)
        return row

    def write(self, row):
        raw = json.dumps(row, ensure_ascii=False).encode()
        check(len(raw) <= MAX_FILE, 'decision_too_large')
        fd, path = tempfile.mkstemp(prefix='.decision-', dir=self.root)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(path, self.root / (row['id'] + '.json'))
            os.fsync(self.directory)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def rows(self):
        names = sorted(n for n in os.listdir(self.directory) if n.endswith('.json'))
        check(len(names) <= MAX_DECISIONS, 'decisions_store_full')
        return [self.read(n[:-5]) for n in names]


def validate(row):
    identifier(row['id'])
    text(row['title'], 256)
    text(row['ask'])
    text(row['context'], empty=True)
    check(isinstance(row['options'], list) and 2 <= len(row['options']) <= 9, 'two_to_nine_options_required')
    keys = []
    for option in row['options']:
        keys.append(identifier(option['key']))
        text(option['label'], 512)
    check(len(set(keys)) == len(keys) and row['default'] in keys, 'unique_options_and_valid_default_required')
    text(row['asker']['name'], 128)
    address(row['asker']['session'], 'session')
    address(row['asker']['block'], 'block')
    check(type(row['opened_at_ms']) is int and type(row['expires_at_ms']) is int
          and row['expires_at_ms'] > row['opened_at_ms'], 'invalid_expiry')
    check(row['state'] in ('open', 'answered', 'default_stood'), 'invalid_decision_state')


def expire(store, row):
    if row['state'] == 'open' and row['expires_at_ms'] <= int(time.time() * 1000):
        row.update(state='default_stood', outcome='default stood', closed_at_ms=int(time.time() * 1000))
        store.write(row)


def project(row, host):
    return dict({k: row[k] for k in ('id', 'title', 'ask', 'context', 'options', 'default', 'asker', 'opened_at_ms', 'expires_at_ms')}, host=host)


def invoke(argv, body=None):
    # One bounded invocation, no retry after an uncertain delivery.
    result = subprocess.run(argv, input=body, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    check(len(result.stdout) <= 1048576, 'transport_output_too_large')
    check(result.returncode == 0, 'command_failed: ' + result.stderr.decode(errors='replace')[-512:])
    return json.loads(result.stdout)


def named(self, config, host, command):
    # Resolve and reuse targets' validated local/SSH transport. The explicit socket
    # is an item argument; it never passes through targets' selector rewriting.
    selected = targets.resolve_host(config, host)
    argv = [selected['teerex'], '--rex', selected['rex'], 'decide', *command]
    if command[0] == 'answer':
        argv += ['--socket', selected['socket']]
    argv += ['--store', selected['home'] + '/.local/state/teerex/decisions']
    if selected['transport'] == 'ssh':
        argv = [*targets.ssh_argv(selected), shlex.join(argv)]
    return invoke(argv)


def main(self, argv):
    parser = argparse.ArgumentParser(prog='teerex decide', description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    for op in ('open', 'list', 'answer'):
        p = sub.add_parser(op, help={'open': 'record a decision; proceed on its default; no pane input',
                                     'list': 'pull open decisions; expire silently as default stood',
                                     'answer': 'guarded delivery to the saved asker, then close'}[op])
        p.add_argument('--store', default=os.environ.get('TEEREX_DECISIONS_DIR') or os.path.expanduser('~/.local/state/teerex/decisions'), help='private absolute command-host decision store')
        if op == 'open':
            for field in ('id', 'title', 'ask', 'default'):
                p.add_argument('--' + field, required=True)
            p.add_argument('--context', default='')
            p.add_argument('--option', action='append', required=True, help='KEY::LABEL; repeat 2..9 times')
            p.add_argument('--asker-name', default=os.environ.get('AGENT_NAME') or 'asker')
            p.add_argument('--asker-session', default=os.environ.get('REX_SESSION') or os.environ.get('LC_REX_SESSION'))
            p.add_argument('--asker-block', default=os.environ.get('REX_BLOCK') or os.environ.get('LC_REX_BLOCK'))
            p.add_argument('--expires-in', default='24h', help='positive integer with s, m, h or d; at most 30d')
        else:
            p.add_argument('--config', default=os.path.expanduser('~/.config/teerex/hosts.json'))
            if op == 'list':
                p.add_argument('--hosts', help='1..16 comma-separated configured hosts; failures make complete false')
                p.add_argument('--json', action='store_true', help='JSON result (also the default)')
            else:
                p.add_argument('--host', help='configured decision host; omit for local store')
                p.add_argument('--id', required=True)
                choice = p.add_mutually_exclusive_group(required=True)
                choice.add_argument('--option')
                choice.add_argument('--default', action='store_true')
                p.add_argument('--socket', help='local asker Rex socket (defaults to REX_SERVER or platform socket)')
    a = parser.parse_args(argv)
    if a.operation == 'list' and a.hosts:
        hosts = a.hosts.split(',')
        check(1 <= len(hosts) <= 16 and len(set(hosts)) == len(hosts) and all(ID.fullmatch(h) for h in hosts), 'invalid_hosts')
        sources, decisions = [], []
        for host in hosts:
            try:
                packet = named(self, a.config, host, ['list', '--json'])
                check(packet['complete'] is True and isinstance(packet['decisions'], list), 'incomplete_host')
                decisions.extend(dict(row, host=host) for row in packet['decisions'])
                sources.append(dict(host=host, outcome='observed'))
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
                sources.append(dict(host=host, outcome='unknown', reason=str(error)[:512]))
        complete = all(s['outcome'] == 'observed' for s in sources)
        return dict(complete=complete, sources=sources, decisions=sorted(decisions, key=lambda r: (r['opened_at_ms'], r['host'], r['id']))), 0 if complete else 1
    if a.operation == 'answer' and a.host:
        identifier(a.id)
        return named(self, a.config, a.host, ['answer', '--id', a.id, *(['--default'] if a.default else ['--option', identifier(a.option)])]), 0
    store = Store(a.store)
    with store.locked():
        if a.operation == 'open':
            match = re.fullmatch(r'([1-9][0-9]{0,7})([smhd])', a.expires_in)
            check(match, 'invalid_expires_in')
            duration = int(match[1]) * {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[match[2]]
            check(duration <= 30 * 86400, 'expiry_exceeds_30_days')
            options = []
            for item in a.option:
                key, sep, label = item.partition('::')
                check(sep, 'option_requires_KEY_double_colon_LABEL')
                options.append(dict(key=key, label=label))
            now = int(time.time() * 1000)
            row = dict(id=identifier(a.id), title=a.title, ask=a.ask, context=a.context, options=options,
                       default=a.default, asker=dict(name=a.asker_name, session=a.asker_session, block=a.asker_block),
                       opened_at_ms=now, expires_at_ms=now + duration * 1000, state='open')
            validate(row)
            rows = store.rows()
            check(len(rows) < MAX_DECISIONS, 'decisions_store_full')
            check(not any(r['id'] == row['id'] for r in rows), 'decision_id_already_used')
            store.write(row)
            return dict(outcome='opened', decision=project(row, 'local'), default_policy='proceed_unless_vetoed', terminal_input_attempted=False), 0
        if a.operation == 'list':
            rows = store.rows()
            for row in rows:
                expire(store, row)
            return dict(complete=True, sources=[dict(host='local', outcome='observed')], decisions=[project(r, 'local') for r in sorted(rows, key=lambda r: (r['opened_at_ms'], r['id'])) if r['state'] == 'open']), 0
        row = store.read(a.id)
        expire(store, row)
        if row['state'] == 'default_stood':
            return dict(outcome='default_stood', id=a.id, terminal_input_attempted=False), 0
        check(row['state'] == 'open', 'decision_already_closed')
        key = row['default'] if a.default else identifier(a.option)
        option = next((o for o in row['options'] if o['key'] == key), None)
        check(option is not None, 'unknown_option')
        check(not row.get('delivery_attempted'), 'delivery_already_attempted_inspect_asker_do_not_retry')
        socket = a.socket or os.environ.get('REX_SERVER') or (os.path.expanduser('~/Library/Application Support/rex/server.sock') if sys.platform == 'darwin' else '/run/user/%d/rex/server.sock' % os.getuid())
        if socket.startswith('unix://'):
            socket = socket[7:]
        check(os.path.isabs(socket), 'absolute_socket_required')
        # Persist before invoking send: a lost receipt must never authorize a retry.
        row.update(delivery_attempted=True, selected=key)
        store.write(row)
        packet = invoke([self, 'send', '--socket', socket, '--session', row['asker']['session'], '--block', row['asker']['block'],
                         '--from', 'Josh', '--message-file', '-', '--draft-wait-ms', '0'],
                        ('DECISION [' + row['id'] + '] Josh chose: ' + option['label']).encode())
        check(packet.get('outcome') == 'events_acknowledged', 'delivery_not_acknowledged_inspect_asker_do_not_retry')
        row.update(state='answered', closed_at_ms=int(time.time() * 1000))
        store.write(row)
        return dict(outcome='answered', id=a.id, option=key, terminal_input_attempted=True, delivery=packet), 0


if __name__ == '__main__':
    try:
        packet, code = main(sys.argv[1], sys.argv[2:])
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        packet, code = dict(outcome='refused_or_unknown', reason=str(error)[:512], retry_safe=False), 1
    print(json.dumps(packet, ensure_ascii=False), flush=True)
    sys.exit(code)
