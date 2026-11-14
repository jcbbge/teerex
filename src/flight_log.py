"""Read-only flight log over existing local evidence; no daemon or new event store."""
import argparse
import datetime as dt
import html
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

UTC = dt.timezone.utc

def clean(value):
    return ''.join(c for c in str(value) if ord(c) >= 32 and not 127 <= ord(c) <= 159)

def timestamp(value):
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('timestamp requires a timezone')
        return int(parsed.timestamp() * 1000)
    return 0

def iso(value):
    return dt.datetime.fromtimestamp(value / 1000, UTC).isoformat(timespec='seconds').replace('+00:00', 'Z')

def read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd) as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('regular file required')
        return stream.read()

def collect(home, held_command=None):
    root = Path(home) / '.local/state'
    result = dict(events=[], finished=[], decisions=[], stalled=[], ship=[], vitals={}, unavailable=[])
    def event(at, who, kind, text, source):
        at = timestamp(at)
        if at:
            result['events'].append(dict(at=at, who=clean(who), kind=kind, text=clean(text), source=str(source)))
    registry = root / 'teerex-agents'
    if not registry.exists():
        result['unavailable'].append('agent registry missing')
    paths = list(registry.glob('agents-*.json')) + list((registry / 'archive').glob('*/agents-*.json'))
    for path in paths:
        try:
            retired = path.parent / 'retired.json'
            agent = json.loads(read(retired if retired.exists() else path))
            name = agent.get('name', path.stem)
            rows = agent.get('timeline') or [dict(at=agent.get('created_at'), event='launched', evidence='launch intent; process creation not proven')]
            for row in rows:
                event(row.get('at'), name, row.get('event', 'agent'), row.get('text') or row.get('evidence') or row.get('reason') or row.get('event'), path)
            contract = agent.get('contract') or {}
            # Contract deliveries contain timestamped step lines; never expose command argv or tokens.
            for message in path.parent.glob(path.stem + '-contract-*.txt'):
                first = read(message).splitlines()
                if first:
                    event(message.stat().st_mtime_ns // 1000000, name, 'step recorded', first[0], message)
            if contract.get('last_contact'):
                event(contract.get('last_contact_at'), name, 'step', contract['last_contact'], path)
            if agent.get('immediate_child_ended_at'):
                event(agent['immediate_child_ended_at'], name, 'child_exit', str(agent.get('immediate_child_term')), path)
            if path.parent == registry and (contract.get('flag') or contract.get('stalled') or contract.get('declared') == 'blocked'):
                flag = contract.get('flag') or {}
                result['stalled'].append(clean(name + ': ' + str(flag.get('text') or contract.get('now') or 'blocked')))
            pad = agent.get('scratchpad')
            if pad:
                try:
                    if not Path(pad).exists():
                        original = Path(pad)
                        archived = original.parent.parent / 'archive' / original.parent.name / original.name
                        pad = str(archived) if archived.exists() else pad
                    raw = read(pad)
                    updated = next((line[9:] for line in raw.splitlines() if line.startswith('Updated: ')), '')
                    section = ''
                    for line in raw.splitlines():
                        if line.startswith('## '):
                            section = line[3:]
                        elif line.startswith('- [x] ') and section == 'Done':
                            text = clean(name + ': ' + line[6:])
                            result['finished'].append(dict(at=timestamp(updated), text=text, owner=clean(agent.get('owner') or name)))
                            event(updated, name, 'scratch snapshot', line[6:] + ' (snapshot time; completion time unknown)', pad)
                except (OSError, ValueError) as exc:
                    result['unavailable'].append(clean(str(pad) + ': ' + str(exc)))
        except (OSError, ValueError, TypeError) as exc:
            result['unavailable'].append(clean(str(path) + ': ' + str(exc)))
    records = root / 'teerex-records/records'
    if not records.exists():
        result['unavailable'].append('decision records missing')
    for path in records.glob('*/record.json'):
        try:
            record = json.loads(read(path))
            if record.get('kind') == 'decision':
                text = clean(str(record.get('id')) + ': ' + str(record.get('question') or 'decision'))
                event(record.get('updated_at') or record.get('written_at'), record.get('writer', 'decision'), 'decision', text + ' [' + str(record.get('state')) + ']', path)
                if record.get('state') == 'open':
                    result['decisions'].append(text)
        except (OSError, ValueError) as exc:
            result['unavailable'].append(clean(str(path) + ': ' + str(exc)))
    if held_command:
        try:
            completed = subprocess.run(held_command, capture_output=True, text=True, timeout=30)
            if completed.returncode:
                raise ValueError(clean(completed.stderr) or 'command failed')
            waiting = json.loads(completed.stdout)
            for item in waiting['items']:
                text = clean(str(item['id']) + ': ' + item['text'])
                event(item.get('since'), item.get('project', 'Rivet'), 'Rivet waiting', text, 'rv waiting --json')
                if item.get('waits') == 'ship':
                    result['ship'].append(text)
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            result['unavailable'].append('Rivet waiting: ' + clean(exc))
    else:
        result['unavailable'].append('Rivet waiting command not configured on this host')
    try:
        disk = shutil.disk_usage(home)
        result['vitals'] = dict(load=os.getloadavg(), disk_free_bytes=disk.free, disk_total_bytes=disk.total, cpu_count=os.cpu_count())
    except OSError as exc:
        result['unavailable'].append('machine vitals: ' + clean(exc))
    return result

def merged(hosts, since):
    rows = []
    for name, data in hosts.items():
        rows.extend(dict(row, host=name) for row in data['events'] if row['at'] >= since)
    unique = {(r['host'], r['at'], r['who'], r['kind'], r['text']): r for r in rows}
    return sorted(unique.values(), key=lambda r: (r['at'], r['host'], r['who'], r['kind']))

def brief(hosts, since):
    text = ['# Morning brief', '', 'Generated ' + iso(timestamp(dt.datetime.now(UTC).isoformat())), '']
    for title, key in [('Finished (reported; proof retained when supplied)', 'finished'), ('Open decisions', 'decisions'), ('Stalled', 'stalled'), ('Waiting at Rivet’s ship stop', 'ship')]:
        text += ['## ' + title, '']
        lines = []
        for host, data in hosts.items():
            items = data[key]
            if key == 'finished':
                groups = {}
                for item in items:
                    if item['at'] >= since:
                        groups.setdefault(item.get('owner', 'work'), []).append(item)
                items = []
                for owner, steps in sorted(groups.items()):
                    latest = max(steps, key=lambda item: item['at'])
                    proven = [item for item in steps if 'proof:' in item['text']]
                    proof = max(proven, key=lambda item: item['at'])['text'].partition('proof:')[2].strip() if proven else 'no proof supplied'
                    items.append(owner + ': ' + str(len(steps)) + ' reported steps finished. Latest: ' + latest['text'].split(' — ')[0] + '. Proof sample: ' + proof)
            for item in items:
                if isinstance(item, dict):
                    if item['at'] < since:
                        continue
                    item = item['text']
                lines.append('- ' + clean(host) + ' · ' + clean(item))
        text += (lines or ['No recorded entries.']) + ['']
    text += ['## Machine vitals', '']
    for host, data in hosts.items():
        v = data['vitals']
        text.append('- ' + clean(host) + ': ' + (f"load {v['load'][0]:.2f}; {v['cpu_count']} CPUs; disk free {v['disk_free_bytes'] / 2**30:.1f} GiB / {v['disk_total_bytes'] / 2**30:.1f} GiB" if v else 'UNKNOWN'))
    text += ['', '## Evidence gaps', '']
    gaps = ['- ' + clean(host) + ': ' + clean(gap) for host, data in hosts.items() for gap in data['unavailable']]
    text += (gaps or ['No source errors reported.'])
    text += ['', 'Scratchpad times are snapshot times. Agent stops are reports, not proof of process exit. Historical steps absent from retained records cannot be reconstructed.', '']
    return '\n'.join(text)

def page(rows, hosts):
    escape = lambda value: html.escape(str(value), quote=True)
    entries = ''.join('<tr><td>' + escape(iso(r['at'])) + '</td><td>' + escape(r['host']) + '</td><td>' + escape(r['who']) + '</td><td>' + escape(r['kind']) + '</td><td>' + escape(r['text']) + '<small>' + escape(r['source']) + '</small></td></tr>' for r in rows)
    gaps = ''.join('<li>' + escape(host + ': ' + gap) + '</li>' for host, data in hosts.items() for gap in data['unavailable'])
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>Flight log</title><style>body{font:16px system-ui;background:#faf9f5;color:#242424;margin:4vw}h1{font-size:3rem}table{border-collapse:collapse;width:100%}td,th{text-align:left;vertical-align:top;padding:12px;border-bottom:1px solid #ddd}small{display:block;color:#666;margin-top:6px;overflow-wrap:anywhere}td:first-child{white-space:nowrap} @media(max-width:700px){table{font-size:12px}td,th{padding:5px}}</style><h1>Flight log</h1><p>Timestamped retained evidence. Scratch entries are snapshots; reported completion is not independently verified.</p><table><thead><tr><th>UTC</th><th>Host</th><th>Who</th><th>Event</th><th>Evidence</th></tr></thead><tbody>' + entries + '</tbody></table><h2>Evidence gaps</h2><ul>' + gaps + '</ul></html>'

def main(argv=None):
    parser = argparse.ArgumentParser(prog='teerex log', description='Merge existing agent, step, decision and Rivet waiting evidence. Read only; no new event store.')
    parser.add_argument('--since', default=dt.datetime.now(UTC).date().isoformat() + 'T00:00Z')
    parser.add_argument('--hosts', help='comma separated configured hosts; default: all configured hosts')
    parser.add_argument('--config', default=str(Path.home() / '.config/teerex/hosts.json'))
    output = parser.add_mutually_exclusive_group()
    output.add_argument('--page', nargs='?', const='', metavar='PATH', help='write a self-contained offline HTML page')
    output.add_argument('--brief', action='store_true', help='print Markdown and open it in a leaf float')
    parser.add_argument('--no-open', action='store_true', help='print brief without opening leaf')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--session')
    parser.add_argument('--block')
    parser.add_argument('--socket', default=os.environ.get('REX_SERVER') or ('/run/user/' + str(os.getuid()) + '/rex/server.sock' if sys.platform != 'darwin' else str(Path.home() / 'Library/Application Support/rex/server.sock')))
    parser.add_argument('--local-data', action='store_true', help=argparse.SUPPRESS)
    o = parser.parse_args(argv)
    try:
        since = timestamp(o.since)
    except ValueError:
        parser.error('--since must be an ISO 8601 time')
    config = targets.load_config(str(Path(o.config).resolve()))
    if o.local_data:
        local = next((h for h in config['hosts'].values() if h.get('transport') == 'local'), {})
        print(json.dumps(collect(Path.home(), local.get('held_command'))))
        return 0
    names = o.hosts.split(',') if o.hosts else list(config['hosts'])
    hosts = {}
    for name in names:
        host = targets.resolve_host(str(Path(o.config).resolve()), name)
        try:
            if host['transport'] == 'local':
                data = collect(host['home'], host.get('held_command'))
            else:
                import shlex
                args = [host['teerex'], 'log', '--local-data']
                response = subprocess.run(targets.ssh_argv(host) + [shlex.join(args)], capture_output=True, text=True, timeout=60)
                if response.returncode:
                    raise ValueError(clean(response.stderr) or 'remote collection failed')
                data = json.loads(response.stdout)
            hosts[name] = data
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            hosts[name] = dict(events=[], finished=[], decisions=[], stalled=[], ship=[], vitals={}, unavailable=[clean(exc)])
    rows = merged(hosts, since)
    if o.brief:
        content = brief(hosts, since)
        print(content, flush=True)
        if not o.no_open:
            session = o.session or os.environ.get('REX_SESSION') or os.environ.get('LC_REX_SESSION')
            block = o.block or os.environ.get('REX_BLOCK') or os.environ.get('LC_REX_BLOCK')
            if not session or not block:
                raise ValueError('brief printed; pass --session and --block to open leaf, or use --no-open')
            fd, path = tempfile.mkstemp(prefix='teerex-morning-', suffix='.md')
            with os.fdopen(fd, 'w') as stream:
                stream.write(content)
            leaf = shutil.which('leaf') or str(Path.home() / '.cargo/bin/leaf')
            opened = subprocess.run([SELF, 'surfaces', 'open', '--socket', o.socket, '--session', session, '--anchor', block, '--layout', 'float', '--bounds', '[0.08,0.08,0.84,0.84]', '--label', 'Morning brief', '--', leaf, 'open', path], capture_output=True, text=True)
            if opened.returncode:
                raise ValueError('leaf opening failed; retained ' + path + ': ' + clean(opened.stderr))
            print(opened.stdout, file=sys.stderr)
    elif o.page is not None:
        if o.page:
            path = Path(o.page).expanduser()
        else:
            fd, temporary = tempfile.mkstemp(prefix='teerex-flight-', suffix='.html')
            os.close(fd)
            path = Path(temporary)
        # Explicit paths never overwrite an existing share or document.
        with path.open('x' if o.page else 'w') as stream:
            stream.write(page(rows, hosts))
        print(path)
    elif o.json:
        print(json.dumps(dict(events=rows, hosts=hosts)))
    else:
        for row in rows:
            print(iso(row['at']), row['host'], row['who'], row['kind'] + ':', row['text'])
        for host, data in hosts.items():
            for gap in data['unavailable']:
                print('UNKNOWN ' + clean(host) + ': ' + clean(gap), file=sys.stderr)
    return 0

if __name__ == '__main__':
    SELF = sys.argv.pop(1)
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print('teerex log: ' + clean(exc), file=sys.stderr)
        sys.exit(1)
