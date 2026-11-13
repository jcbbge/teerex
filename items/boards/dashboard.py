"""Keyboard fleet view. Explicit public teerex actions; no background work."""
import datetime
import textwrap
import contextlib
import fcntl
import json
import os
import re
import select
import shlex
import sys
import termios
import time
import tty


def lifecycles(path, api):
    check, private = api['check'], api['private']
    check(os.path.isabs(path), 'absolute_agents_registry_required')
    try:
        directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return []
    lock = None
    try:
        private(directory, True)
        try:
            lock = os.open('agents.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError:
            pass
        if lock is not None:
            private(lock)
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        names = sorted(name for name in os.listdir(directory) if re.fullmatch(r'agents-[0-9a-f]{32}\.json', name))
        check(len(names) <= 32, 'agents_registry_limit_32')
        rows = []
        for name in names:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            try:
                private(fd)
                record = api['json_load'](api['read_fd'](fd, 262144))
            finally:
                os.close(fd)
            check(isinstance(record, dict) and isinstance(record.get('target'), dict), 'invalid_lifecycle_record')
            check(record.get('schema_version') == 1 and name == 'agents-' + record.get('launch_id', '') + '.json', 'invalid_lifecycle_record')
            if record.get('target', {}).get('block_id') is None:
                continue  # A creation intent has no pane to select.
            row = dict(target=api['target'](record['target']))
            for key in ('name', 'owner', 'purpose', 'phase'):
                row[key] = api['text'](record[key], 4096)
            at = record.get('created_at')
            check(type(at) is int and at > 0, 'invalid_lifecycle_timestamp')
            row['created_at'] = at
            row['document'] = None
            for key in ('last_report_file', 'report_file', 'brief_file'):
                if record.get(key):
                    path = api['text'](record[key], 4096, False)
                    check(os.path.isabs(path), 'absolute_lifecycle_document_required')
                    row['document'] = path
                    break
            rows.append(row)
        return rows
    finally:
        if lock is not None:
            os.close(lock)
        os.close(directory)


def metadata(agents_registry, api):
    import teerex_calls
    result = dict(calls=[], lifecycles=[], errors=[])
    for name, read in [('calls', lambda: teerex_calls.recent(128)),
                       ('lifecycles', lambda: lifecycles(agents_registry, api) if agents_registry else [])]:
        try:
            value = read()
            # Project the call history too: no extra fields can reach terminal rendering.
            if name == 'calls':
                projected = []
                for call in value:
                    ids = call.get('ids', [])
                    api['check'](type(call.get('at')) is int and call['at'] > 0
                                 and isinstance(ids, list) and len(ids) <= 16
                                 and all(isinstance(value, str) for value in ids), 'invalid_call_metadata')
                    projected.append(dict(at=call['at'], ids=ids))
                result[name] = projected
            else:
                result[name] = value
        except (OSError, ValueError, KeyError, TypeError, api['Refused']) as error:
            result['errors'].append(name + ': ' + str(error)[:160])
    return result


def registry_for(selections, name, selected, api):
    paths = {}
    for value in selections:
        if value.startswith('/'):
            host, path = '*', value
        else:
            host, separator, path = value.partition('=')
            api['check'](separator and api['HOST'].fullmatch(host), 'registry_requires_ABS_or_HOST_equals_ABS')
        api['check'](os.path.isabs(path) and not any(ord(c) < 32 or ord(c) == 127 for c in path), 'absolute_registry_required')
        api['check'](host not in paths and (host == '*' or host in selected), 'duplicate_or_unselected_registry_host')
        paths[host] = path
    api['check'](not ('*' in paths and len(paths) != 1), 'registry_default_cannot_mix_with_named_paths')
    return paths.get(name, paths.get('*'))


def clean(value):
    return ''.join(c if ord(c) >= 32 and not 127 <= ord(c) <= 159 else ' ' for c in str(value))


def key_for(row):
    return json.dumps(row['target'], sort_keys=True)


def cells(row, now):
    data = row.get('dashboard', {})
    life, report, registration = data.get('lifecycle') or {}, row.get('report') or {}, row.get('registration') or {}
    name = life.get('name') or row['observation'].get('label') or row['target']['block_id']
    owner = life.get('owner') or registration.get('owner') or report.get('owner') or '?'
    purpose = life.get('purpose') or registration.get('purpose') or report.get('purpose') or '?'
    records = (row.get('program_status') or {}).get('records', [])
    status = life.get('phase') or report.get('state') or 'unknown'
    provenance = 'lifecycle' if life else 'report' if report else 'unknown'
    at = life.get('created_at') or report.get('at') or registration.get('registered_at_unix_ms')
    delta = now - at if at else None
    if records:
        record = min(records, key=lambda r: r['age_ms'] if r['age_ms'] is not None else float('inf'))
        status, provenance, delta = record['state'], 'OSC', record['age_ms']
    if (row.get('agent_state') or {}).get('state') == 'working' and status != 'working':
        status, provenance = 'working', 'screen'
    def seconds(value):
        return str(value // 1000) + 's' if value is not None and value >= 0 else '?'
    called = data.get('last_call')
    try:
        call_time = time.strftime('%H:%M:%S', time.gmtime(called / 1000)) if called else '?'
    except (OverflowError, OSError, ValueError):
        call_time = '?'
    return [name, row['target']['host'], owner, purpose, status + ' [' + provenance + ']',
            seconds(delta), call_time]


def scratchpad(session, block):
    """Read on the probed host; missing or malformed scratchpads are optional."""
    path = os.path.expanduser('~/.local/state/teerex/scratch/' + session + '/' + block + '.md')
    result = dict(now='', todo=[], done=[], updated=None)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            import stat
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return result
            raw = os.read(fd, 65537)
        finally:
            os.close(fd)
        if len(raw) > 65536:
            return result
        section = None
        for line in raw.decode('utf-8').splitlines():
            if line.startswith('Updated: '):
                result['updated'] = line[9:]
            elif line.startswith('## '):
                section = line[3:]
            elif line.startswith(('- [ ] ', '- [x] ')):
                value = clean(line[6:])
                if section == 'Now' and not result['now']:
                    result['now'] = value
                elif section in ('To-do', 'Done'):
                    result['todo' if section == 'To-do' else 'done'].append(value)
        return result
    except (OSError, UnicodeError, ValueError):
        return result


def summary(row, now):
    data = row.get('dashboard', {})
    life, report = data.get('lifecycle') or {}, row.get('report') or {}
    pad = row.get('scratchpad') or {}
    name = life.get('name') or row['observation'].get('label') or 'terminal'
    records = (row.get('program_status') or {}).get('records', [])
    record = min(records, key=lambda r: r.get('age_ms') if r.get('age_ms') is not None else float('inf')) if records else {}
    state = record.get('state') or report.get('state') or 'idle'
    observed = (row.get('agent_state') or {}).get('state')
    if observed == 'working':
        state = 'working'
    elif observed in ('awaiting_choice', 'awaiting_text'):
        state = 'blocked'
    elif observed == 'error':
        state = 'error'
    elif observed == 'unknown' and state == 'idle' and not pad.get('now'):
        state = 'unknown'
    state = {'waiting_on_operator': 'blocked', 'completed': 'done', 'dead': 'done', 'unknown': 'idle'}.get(state, state)
    if pad.get('now') and state == 'idle':
        state = 'working'
    delta = record.get('age_ms')
    if pad.get('updated'):
        try:
            at = datetime.datetime.fromisoformat(pad['updated'].replace('Z', '+00:00'))
            if at.tzinfo is not None:
                delta = now - int(at.timestamp() * 1000)
        except (ValueError, OverflowError):
            pass
    if delta is None and report.get('at'):
        delta = now - report['at']
    age = '—' if delta is None or delta < 0 else str(delta // 1000) + 's' if delta < 60000 else str(delta // 60000) + 'm' if delta < 3600000 else str(delta // 3600000) + 'h' if delta < 86400000 else str(delta // 86400000) + 'd'
    done = len(pad.get('done', []))
    total = done + len(pad.get('todo', [])) + bool(pad.get('now'))
    question = row.get('question') or record.get('title') or 'Needs your answer'
    message = 'waiting on you  “' + question + '”' if state == 'blocked' else pad.get('now') or ('Checking activity' if state == 'unknown' else '—')
    return dict(name=clean(name), state=state, message=clean(message), progress=str(done) + '/' + str(total) if total else '', age=age)


def fleet_rows(snapshot, now, history=False):
    rows = [r for r in snapshot['rows'] if (r.get('registration') or {}).get('kind') == 'agent'
            and r.get('registration_matches_presence') is True and (r.get('dashboard') or {}).get('lifecycle')]
    if not history:
        rows = [r for r in rows if r['observation'].get('present') is True
                and summary(r, now)['state'] != 'done']
    order = {'blocked': 0, 'error': 1, 'working': 2, 'idle': 3, 'done': 4}
    return sorted(rows, key=lambda r: (order.get(summary(r, now)['state'], 3), summary(r, now)['name'].casefold()))


def fleet_lines(snapshot, rows, now, width, selected=None, flash=(), color=False):
    values = [summary(r, now) for r in rows]
    working = sum(v['state'] == 'working' for v in values)
    waiting = sum(v['state'] == 'blocked' for v in values)
    hosts = ', '.join(dict.fromkeys(s.get('configured_name') or s.get('host', '') for s in snapshot.get('sources', []))) or 'fleet'
    header = hosts + ' · ' + str(working) + ' agents working · ' + str(waiting) + ' waiting on you'
    clock = time.strftime('%H:%M')
    if len(header) + len(clock) + 2 <= width:
        header = header.ljust(width - len(clock)) + clock
    lines = textwrap.wrap(header, width) + ['']
    for source in snapshot.get('sources', []):
        if source.get('outcome') != 'observed':
            lines += textwrap.wrap((source.get('configured_name') or source.get('host') or 'Host') + ' · unavailable', width)
    for row, value in zip(rows, values):
        glyph = {'blocked': '●', 'error': '✗', 'working': '▶', 'done': '✓'}.get(value['state'], ' ')
        prefix = ('›' if key_for(row) == selected else ' ') + ' ' + glyph + ' ' + value['name'] + (' [detached]' if row['observation'].get('placement') == 'detached' else '')
        suffix = '  ' + value['progress'] + '  ' + value['age']
        # Work text always wraps in full, including long individual words.
        wrapped = textwrap.wrap(prefix + '  ' + value['message'] + suffix, width, subsequent_indent='    ') or ['']
        if color:
            ink = {'blocked': '33', 'error': '31', 'working': '32', 'done': '32'}.get(value['state'], '2')
            wrapped[0] = wrapped[0].replace(glyph, '\x1b[' + ink + 'm' + glyph + '\x1b[0m', 1) if glyph != ' ' else '\x1b[2m' + wrapped[0] + '\x1b[0m'
        if key_for(row) in flash:
            wrapped = ['\x1b[5m' + line + '\x1b[0m' for line in wrapped]
        lines += wrapped
    if not rows:
        lines += ['No agents working right now.']
    return lines


def read_key(fd, pending, timeout):
    if not pending:
        if not select.select([fd], [], [], max(0, timeout))[0]:
            return None
        chunk = os.read(fd, 256)
        if not chunk:
            return 'EOF'
        pending.extend(chunk)
    if pending[0] == 27:
        arrows = [(b'\x1b[A', 'UP'), (b'\x1b[B', 'DOWN'), (b'\x1bOA', 'UP'), (b'\x1bOB', 'DOWN')]
        deadline = time.monotonic() + .04
        while len(pending) < 3 and any(code.startswith(pending) for code, _ in arrows):
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
                break
            chunk = os.read(fd, 256)
            if not chunk:
                break
            pending.extend(chunk)
        for code, key in arrows:
            if pending.startswith(code):
                del pending[:len(code)]
                return key
        del pending[:1]
        return 'ESC'
    first = pending[0]
    size = 1 if first < 128 else 2 if first < 224 else 3 if first < 240 else 4
    if len(pending) < size and select.select([fd], [], [], .04)[0]:
        pending.extend(os.read(fd, 256))
    value = bytes(pending[:size]).decode('utf-8', errors='replace')
    del pending[:size]
    return value


class Dashboard:
    def __init__(self, args, api):
        self.a, self.api = args, api
        self.snapshot = dict(rows=[], sources=[])
        self.selected = None
        self.position = 0
        self.query = ''
        self.edit = None
        self.status = 'Ready. Actions only run on a keypress; reports do not prove completion.'
        self.history = False
        self.inline = False
        self.inspect = False
        self.waiting = set()
        self.flash = set()
        self.pending = bytearray()
        self.session = args.dashboard_session or os.environ.get('REX_SESSION') or os.environ.get('LC_REX_SESSION')
        self.block = args.dashboard_block or os.environ.get('REX_BLOCK') or os.environ.get('LC_REX_BLOCK')

    def refresh(self):
        try:
            with contextlib.closing(self.api['Store'](self.a.store)) as store:
                self.snapshot = self.api['fleet_snapshot'](self.a, store.state)
                waiting = {key_for(r) for r in self.snapshot['rows'] if summary(r, self.api['stamp']())['state'] == 'blocked'}
                self.flash = waiting - self.waiting
                self.waiting = waiting
        except (OSError, ValueError, self.api['Refused']) as error:
            self.snapshot = dict(rows=[], sources=[])
            self.status = 'Refresh unknown: ' + str(error)

    def rows(self):
        query = (self.query if self.edit is None else self.edit).casefold()
        candidates = self.snapshot['rows'] if self.a.detail else fleet_rows(self.snapshot, self.api['stamp'](), self.history)
        rows = [r for r in candidates if query in ' '.join(cells(r, self.api['stamp']())).casefold()]
        if rows:
            self.position = next((i for i, r in enumerate(rows) if key_for(r) == self.selected), min(self.position, len(rows) - 1))
            self.selected = key_for(rows[self.position])
        else:
            self.position, self.selected = 0, None
        return rows

    def draw(self):
        if not self.a.detail:
            return self.draw_fleet()
        return self.draw_detail()

    def draw_fleet(self):
        size = os.get_terminal_size(sys.stdout.fileno())
        width = max(20, size.columns)
        rows = self.rows()
        lines = fleet_lines(self.snapshot, rows, self.api['stamp'](), width, self.selected, self.flash, color=True)
        self.flash = set()
        if rows and self.inspect:
            lines += textwrap.wrap(clean(json.dumps(rows[self.position], ensure_ascii=False)), width)
        elif rows and self.inline:
            pad = rows[self.position].get('scratchpad') or {}
            lines += ['', 'Scratchpad']
            for glyph, items in [('▶', [pad.get('now')] if pad.get('now') else []), ('☐', pad.get('todo', [])), ('✓', pad.get('done', []))]:
                for item in items:
                    lines += textwrap.wrap(glyph + ' ' + clean(item), width, subsequent_indent='  ')
            if not any(pad.get(k) for k in ('now', 'todo', 'done')):
                lines += ['No scratchpad yet.']
        lines += ['', '⏎ jump  p present  ␣ scratchpad  a history  i inspect  q quit']
        if self.status != 'Ready. Actions only run on a keypress; reports do not prove completion.':
            lines += [self.status if self.inspect else 'Action finished' if 'exit=0' in self.status else 'Action unavailable' ]
        sys.stdout.write('\x1b[2J\x1b[H' + '\n'.join(lines) + '\x1b[J')
        sys.stdout.flush()

    def draw_detail(self):
        size = os.get_terminal_size(sys.stdout.fileno())
        width, height = max(32, size.columns), max(6, size.lines)
        rows = self.rows()
        page = max(1, height - 10)
        first = self.position // page * page
        name_width = max(8, min(20, width // 6))
        widths = [name_width, 8, 10, max(8, width - name_width - 61), 18, 8, 9]
        def columns(values):
            return ' '.join(clean(value)[:n].ljust(n) for value, n in zip(values, widths))
        lines = ['TEEREX / FLEET  ' + str(len(rows)) + '/' + str(len(self.snapshot['rows'])) + ' rows',
                 'j/k arrows select | Enter focus | p present+focus | o document | r refresh | / filter | q quit']
        sources = [str(s.get('configured_name') or s.get('host') or s.get('name')) + ':' + s['outcome'] + (' (metadata unknown)' if s.get('dashboard_errors') else '') for s in self.snapshot['sources']]
        lines += [' '.join(sources) or 'No observed sources', '  ' + columns(['AGENT', 'HOST', 'OWNER', 'PURPOSE', 'STATUS', 'AGE', 'LAST CALL'])]
        for i, row in enumerate(rows[first:first + page], first):
            lines.append(('> ' if i == self.position else '  ') + columns(cells(row, self.api['stamp']())))
        lines += [''] * (page - min(page, len(rows[first:first + page])))
        if rows:
            row = rows[self.position]
            lines += ['Selected: ' + ' | '.join(cells(row, self.api['stamp']())[:5]),
                      row['target']['session_id'] + ' / ' + row['target']['block_id']]
            errors = row.get('dashboard', {}).get('errors', [])
            lines += ['Metadata: ' + '; '.join(errors) if errors else 'Presence is live; OSC/lifecycle/report are separate claims. Age is a clock difference; last call is UTC.']
        else:
            lines += ['No matching rows. / edits the filter; an empty filter shows all.', '', '']
        if height < 12:
            lines = lines[:4] + lines[4:4 + max(0, height - 6)]
        lines += ['Filter' + (' (editing)' if self.edit is not None else '') + ': ' + (self.query if self.edit is None else self.edit),
                  'Receipt: ' + self.status]
        sys.stdout.write('\x1b[2J\x1b[H' + '\n'.join(clean(line)[:width] for line in lines[:height]) + '\x1b[J')
        sys.stdout.flush()

    def anchor(self, row):
        if row['observation'].get('placement') == 'detached':
            anchor = row.get('dashboard', {}).get('focus_anchor')
            self.api['check'](anchor and anchor != row['target']['block_id'], 'detached_session_has_no_focused_anchor')
            return anchor
        match = next((r for r in self.snapshot['rows'] if r['target']['session_id'] == self.session
                      and r['target']['block_id'] == self.block and r['observation'].get('present') is True
                      and (not self.a.dashboard_host or self.a.dashboard_host in
                           (r['target']['host'], r.get('dashboard', {}).get('configured_name')))), None)
        self.api['check'](match is not None, 'dashboard_anchor_unknown_set_dashboard_session_block_and_host')
        self.api['check'](match['target']['server'] == row['target']['server'] and match['target']['host'] == row['target']['host']
                          and self.session == row['target']['session_id'], 'present_requires_dashboard_on_same_server_and_session_use_Enter_to_focus')
        self.api['check'](self.block != row['target']['block_id'], 'cannot_present_dashboard_beside_itself')
        return self.block

    def action(self, key):
        rows = self.rows()
        if not rows:
            self.status = 'Not dispatched: no selected row'
            return
        row = rows[self.position]
        target, data = row['target'], row.get('dashboard', {})
        command = []
        try:
            self.api['check'](row['observation'].get('present') is True, 'selected_pane_presence_unknown_refresh_before_action')
            name = data.get('configured_name')
            prefix = [self.a.teerex, '--config', self.a.config, '--host', name] if name else [self.a.teerex]
            socket = [] if name else ['--socket', target['server'][7:]]
            common = socket + ['--session', target['session_id']]
            if key in ('\r', '\n'):
                command = prefix + ['surfaces', 'focus'] + common + ['--pane', target['block_id']]
            elif key == 'p':
                anchor = self.anchor(row)
                reg = row.get('registration')
                self.api['check'](reg and row.get('registration_matches_presence') and data.get('jobs_registry'), 'present_requires_matching_jobs_registration_and_jobs_registry')
                command = prefix + ['jobs', 'present', '--registry', data['jobs_registry']] + common + [
                    '--block', target['block_id'], '--owner', reg['owner'], '--generation', str(reg['generation']),
                    '--reason', 'keyboard fleet presentation', '--anchor', anchor, '--focus', 'yes', '--relocate', 'yes']
            elif key == 'o':
                document = (data.get('lifecycle') or {}).get('document')
                self.api['check'](document, 'selected_record_has_no_report_or_brief_document')
                source = next((s for s in self.snapshot['sources'] if s.get('host') == target['host'] and s.get('server') == target['server']), {})
                self.api['check'](row['observation'].get('host_id') == source.get('source', {}).get('host_id'), 'document_execution_host_not_verified')
                command = prefix + ['surfaces', 'open'] + common + ['--layout', 'tiled', '--anchor', target['block_id'],
                    '--direction', 'right', '--label', 'fleet document', '--', 'leaf', 'open', document]
            self.status = 'Running ' + shlex.join(command)
            self.draw()
            result = self.api['bounded_command'](command, timeout=25, receipt=True)
            packet = result['receipt']
            summary = {field: packet[field] for field in ('operation', 'outcome', 'failure_reason', 'reason', 'error') if field in packet}
            self.status = ('surfaces focus' if key in ('\r', '\n') else 'jobs present' if key == 'p' else 'surfaces open') + ' exit=' + str(result['exit']) + ' ' + json.dumps(summary, ensure_ascii=False)
        except (OSError, ValueError, KeyError, TypeError, self.api['Refused']) as error:
            self.status = ('Unknown after command: ' if command else 'Not dispatched: ') + str(error)

    def run(self):
        self.api['check'](sys.stdin.isatty() and sys.stdout.isatty(), 'keyboard_fleet_requires_terminal_stdin_and_stdout')
        self.api['check'](self.a.teerex and os.path.isabs(self.a.teerex), 'absolute_teerex_required')
        self.a.dashboard = True
        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd, termios.TCSANOW)
            sys.stdout.write('\x1b[?25l')
            next_refresh = 0
            while True:
                if time.monotonic() >= next_refresh:
                    self.refresh()
                    next_refresh = time.monotonic() + self.a.interval_ms / 1000
                self.draw()
                key = read_key(fd, self.pending, next_refresh - time.monotonic())
                if key is None:
                    continue
                if key == 'EOF':
                    return 0
                if self.edit is not None:
                    if key in ('\r', '\n'):
                        self.query, self.edit = self.edit, None
                    elif key == 'ESC':
                        self.edit = None
                    elif key in ('\x7f', '\b'):
                        self.edit = self.edit[:-1]
                    elif key.isprintable() and len(self.edit) < 128:
                        self.edit += key
                elif key == 'q':
                    return 0
                elif key == 'a':
                    self.history = not self.history
                elif key == ' ':
                    self.inline = not self.inline
                    self.inspect = False
                elif key == 'i':
                    self.inspect = not self.inspect
                    self.inline = False
                elif key == '/':
                    self.edit = ''
                elif key in ('j', 'k', 'UP', 'DOWN'):
                    rows = self.rows()
                    if rows:
                        self.position = max(0, min(len(rows) - 1, self.position + (1 if key in ('j', 'DOWN') else -1)))
                        self.selected = key_for(rows[self.position])
                elif key == 'r':
                    next_refresh = 0
                    self.status = 'Refresh requested'
                elif key in ('\r', '\n', 'p', 'o'):
                    self.action(key)
                    next_refresh = 0
        finally:
            termios.tcsetattr(fd, termios.TCSANOW, saved)
            sys.stdout.write('\x1b[?25h\n')
            sys.stdout.flush()
