"""Seat attention counts. No message bodies, refusals, background work or retention cap.

Only acknowledged terminal input or a saved inbox append enters this log. A label
or explicit registration selects the seat; this is cooperative accounting, never
an identity, consumption or permission claim. Private files reject links/other owners.
"""
import argparse
import contextlib
import datetime
import fcntl
import json
import os
from pathlib import Path
import stat
import sys
import time


def attention_private(fd, directory=False):
    s = os.fstat(fd)
    if (s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != (0o700 if directory else 0o600)
            or not (stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode) and s.st_nlink == 1)):
        raise ValueError('attention requires owned private directory/files')


@contextlib.contextmanager
def attention_log(write=False):
    path = Path(os.environ.get('TEEREX_ATTENTION_DIR', str(Path.home() / '.local/state/teerex/attention')))
    if not path.is_absolute():
        raise ValueError('absolute attention directory required')
    if not write and not path.exists():
        yield None
        return
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    fd = None
    try:
        attention_private(directory, True)
        try:
            flags = (os.O_RDWR | os.O_APPEND if write else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK
            if write:
                # Darwin can return ENOENT for racing O_CREAT without O_EXCL.
                try:
                    fd = os.open('deliveries.jsonl', flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
                except FileExistsError:
                    fd = os.open('deliveries.jsonl', flags, dir_fd=directory)
            else:
                fd = os.open('deliveries.jsonl', flags, dir_fd=directory)
        except FileNotFoundError:
            if write:
                raise
            yield None
            return
        attention_private(fd)
        fcntl.flock(fd, fcntl.LOCK_EX if write else fcntl.LOCK_SH)
        with os.fdopen(fd, 'a+' if write else 'r', encoding='utf-8', closefd=False) as stream:
            yield stream
    finally:
        if fd is not None:
            os.close(fd)
        os.close(directory)


def attention_registered(context):
    store = Path(os.environ.get('TEEREX_BOARDS_STORE', str(Path.home() / '.local/state/teerex-boards')))
    try:
        fd = os.open(store / 'state.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return False
    try:
        attention_private(fd)
        with os.fdopen(fd, closefd=False) as stream:
            state = json.load(stream)
        return any(s['target']['server'] == 'unix://' + context['socket']
                   and s['target']['session_id'] == context['session']
                   and s['target']['block_id'] == context['block'] for s in state['seats'])
    finally:
        os.close(fd)


def attention_record(context, words, seat=False):
    try:
        if not seat and not attention_registered(context):
            return 'not_requested'
        row = dict(at=int(time.time() * 1000), sender=context['sender'], words=words,
                   server='unix://' + context['socket'], session=context['session'], block=context['block'])
        if type(words) is not int or words < 0 or not isinstance(row['sender'], str) or not row['sender']:
            raise ValueError('invalid attention count')
        with attention_log(True) as stream:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
            stream.flush()
        return 'written'
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Delivery has already happened: accounting failure never asks for replay.
        print('teerex attention: count unavailable (%s); delivery unchanged; do not resend' % type(exc).__name__, file=sys.stderr)
        return 'unavailable'


def attention_since(value):
    now = datetime.datetime.now(datetime.timezone.utc)
    if value == 'today':
        return int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    try:
        if value.endswith(('m', 'h', 'd')):
            duration = float(value[:-1]) * {'m': 60, 'h': 3600, 'd': 86400}[value[-1]]
            if duration < 0 or not duration < float('inf'):
                raise ValueError()
            return int((now.timestamp() - duration) * 1000)
        parsed = datetime.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.timezone.utc)
        return int(parsed.timestamp() * 1000)
    except (ValueError, OverflowError):
        raise argparse.ArgumentTypeError('since requires today, duration (1h/30m/2d), or ISO UTC date/time') from None


def attention_shares(profiles_path, registry):
    cfg = json.loads(profiles_path.read_text()) if profiles_path.exists() else {}
    profiles = cfg.get('profiles', {})
    default = cfg.get('defaults', {}).get('attention_messages_per_hour', 6)
    shares = {name: profile.get('attention_messages_per_hour', default) for name, profile in profiles.items()}
    # Match tracked senders to their launch profile; use newest registration.
    launches = []
    for path in registry.glob('agents-*.json'):
        state = json.loads(path.read_text())
        if state.get('name') and state.get('profile'):
            launches.append(state)
    for state in sorted(launches, key=lambda row: row.get('created_at', 0)):
        shares[state['name']] = shares.get(state['profile'], default)
    if any(type(n) is not int or n < 0 for n in [default, *shares.values()]):
        raise ValueError('attention_messages_per_hour must be a nonnegative integer')
    return default, shares


def attention_snapshot(since, profiles_path, registry, now=None):
    now = int(time.time() * 1000) if now is None else now
    totals, hours, rolling = {}, {}, {}
    with attention_log() as stream:
        for line in stream or ():
            row = json.loads(line)
            at, sender, words = row['at'], row['sender'], row['words']
            if type(at) is not int or type(words) is not int or words < 0 or not isinstance(sender, str):
                raise ValueError('invalid attention log row')
            if at > now:
                continue
            if at >= now - 3600000:
                rolling[sender] = rolling.get(sender, 0) + 1
            if at < since:
                continue
            for table, key in ((totals, sender), (hours, (at // 3600000 * 3600000, sender))):
                count = table.setdefault(key, dict(messages=0, words=0))
                count['messages'] += 1
                count['words'] += words
    default, shares = attention_shares(profiles_path, registry)
    rows = []
    for sender, counts in sorted(totals.items()):
        share = shares.get(sender, default)
        last_hour = rolling.get(sender, 0)
        rows.append(dict(sender=sender, **counts, messages_last_hour=last_hour,
                         share_per_hour=share, over_share=last_hour > share,
                         color='amber' if last_hour > share else 'normal'))
    return dict(schema_version=1, kind='attention', since=since, as_of=now,
                messages=sum(r['messages'] for r in rows), words=sum(r['words'] for r in rows),
                senders=rows, hours=[dict(hour=hour, sender=sender, **counts) for (hour, sender), counts in sorted(hours.items())],
                coverage='acknowledged seat sends and saved inbox appends since installation; no scrollback backfill',
                application_consumption='not_assessed')


def attention_main():
    p = argparse.ArgumentParser(prog='teerex boards attention', description='Seat messages and words per sender/hour; advisory share only, never refuses delivery.')
    p.add_argument('--json', action='store_true')
    p.add_argument('--since', type=attention_since, default=attention_since('1h'), help='today, duration (1h/30m/2d), or ISO UTC date/time; default 1h')
    p.add_argument('--profiles', type=Path, default=Path.home() / '.config/teerex/profiles.json')
    p.add_argument('--agents-registry', type=Path, default=Path.home() / '.local/state/teerex-agents')
    a = p.parse_args()
    try:
        snapshot = attention_snapshot(a.since, a.profiles, a.agents_registry)
        if a.json:
            print(json.dumps(snapshot, ensure_ascii=False))
        else:
            print('SEAT ATTENTION · %d messages · %d words' % (snapshot['messages'], snapshot['words']))
            print('SENDER                         MESSAGES      WORDS   LAST HOUR / SHARE')
            for row in snapshot['senders']:
                text = '%-30s %8d %10d   %9d / %d%s' % (row['sender'], row['messages'], row['words'], row['messages_last_hour'], row['share_per_hour'], ' amber' if row['over_share'] else '')
                print(('\x1b[33m' + text + '\x1b[0m') if row['over_share'] and sys.stdout.isatty() else text)
            for row in snapshot['hours']:
                hour = datetime.datetime.fromtimestamp(row['hour'] / 1000, datetime.timezone.utc).strftime('%Y-%m-%d %H:00 UTC')
                print('%s  %s  %d messages  %d words' % (hour, row['sender'], row['messages'], row['words']))
            print(snapshot['coverage'])
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps(dict(kind='attention_error', outcome='unavailable', reason=type(exc).__name__)))
        return 1
