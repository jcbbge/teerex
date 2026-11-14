"""Explicit cross-host attention navigation; foreground, no retries or daemon."""
import argparse
import datetime
import fcntl
import json
import os
import re
from pathlib import Path
import shlex
import subprocess
import sys

# Read agent declarations on the same host as the scanned server. Live pane
# membership below is authoritative; a registry entry alone never makes a stop.
POSITION = r'''
import json, os, stat, sys
from pathlib import Path
root=Path(sys.argv[1])/'.local/state'
def read(path):
    try:
        fd=os.open(path, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd) as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                raise ValueError('regular file required: '+str(path))
            return f.read()
    except FileNotFoundError:
        return None
boards=json.loads(read(root/'teerex-boards/state.json') or '{"seats":[]}')
questions={}
for seat in boards['seats']:
    opened={}
    for r in seat['records']:
        if r['kind']=='decision': opened[r['body']['id']]=r
        elif r['kind']=='resolution': opened.pop(r['body']['id'],None)
    for r in opened.values():
        questions.setdefault(r['from'],[]).append(r)
rows=[]
for path in (root/'teerex-agents').glob('agents-*.json'):
    record=json.loads(read(path) or '{}')
    if not record.get('target') or not record.get('created_at'): continue
    target=record['target']
    pad=root/'teerex/scratch'/target['session_id']/(target['block_id']+'.md')
    now=waiting=''
    section=None
    for line in (read(pad) or '').splitlines():
        if line.startswith('## '): section=line[3:].strip()
        elif line.startswith('Waiting:'): waiting=line.partition(':')[2].strip()
        elif section=='Now' and line.startswith('- [ ] ') and not now: now=line[6:]
    cards=questions.get(record.get('name'),[])
    decision=min(cards,key=lambda r:r['at'])['body'] if cards else None
    rows.append(dict(session_id=target['session_id'],block_id=target['block_id'],
        server=target.get('server'),created_at=record['created_at'],name=record.get('name'),
        position=dict(now=now,waiting=waiting,decision=decision)))
print(json.dumps(rows))
'''

SCAN = r'''
local function call(m,a) local v,e=rex.call(m,a); if not v then error(e) end; return v end
local rows={}
local sessions=call("session.attach_all",{event_scope="session"}).sessions or {}
if #sessions>128 then error("session limit 128") end
for _,s in ipairs(sessions) do
 for _,b in ipairs(call("session.list_blocks",{session_id=s.session_id}).blocks or {}) do
  if b.creator_name=="com.superlogical.terminal" and (b.placement=="placed" or b.placement=="detached") then
   if #rows>=1024 then error("terminal limit 1024") end
   local st=call("block.method",{session_id=s.session_id,block_id=b.block_id,method="program_status"})
   rows[#rows+1]={session_id=s.session_id,block_id=b.block_id,window_id=b.window_id,label=b.label,
    detached=b.placement=="detached",records=st.records or {}}
  end
 end
end
if #rex.json.encode(rows)>1048576 then error("response exceeds 1 MiB") end
return {rows=rows,remote_api=type(rex.server),servers_api=type(rex.servers)}
'''
SHOW = r'''
local p=rex.args
local function call(m,a) local v,e=rex.call(m,a); if not v then error(e) end; return v end
call("session.attach",{session_id=p.session_id})
if p.detached then
 local v=call("session.view",{session_id=p.session_id}); local anchor
 for _,w in ipairs(v.windows or {}) do if w.window_id==v.active_window_id then anchor=w.focused_block_id end end
 if not anchor then error("no placed anchor") end
 call("session.move_block",{session_id=p.session_id,block_id=p.block_id,anchor_block_id=anchor,direction="horizontal",side="after",ratio=2/3})
end
return call("session.focus_block",{session_id=p.session_id,block_id=p.block_id})
'''

LABEL = r'''
local p=rex.args
local attached,err=rex.call("session.attach",{session_id=p.session_id}); if not attached then error(err) end
local r,e=rex.call("session.set_window_label",{session_id=p.session_id,window_id=p.window_id,label=p.label})
if not r then error(e) end
return r
'''
PREPARE = r'''
local p=rex.args
local attached,err=rex.call("session.attach",{session_id=p.session_id}); if not attached then error(err) end
local v,e=rex.call("session.view",{session_id=p.session_id}); if not v then error(e) end
local original
for _,w in ipairs(v.windows or {}) do
 if w.window_id==v.active_window_id then original={session_id=p.session_id,window_id=w.window_id,label=w.label or ""} end
end
if not original then error("focused tab not found") end
local q=p.position
local label=(p.name or p.label or "Agent").." | Now: "..q.now.." | Waiting: "..q.waiting
if q.decision then
 label=label.." | "..q.decision.ask
 local default=(q.decision.prepared and q.decision.prepared.default) or q.decision.default
 if default then label=label.." | Default: "..tostring(default) end
end
local r,err=rex.call("session.set_window_label",{session_id=original.session_id,window_id=original.window_id,label=label})
if not r then error(err) end
return original
'''

HIDE = r'''
local p=rex.args
local function call(m,a) local v,e=rex.call(m,a); if not v then error(e) end; return v end
call("session.attach",{session_id=p.session_id})
local blocks=call("session.list_blocks",{session_id=p.session_id}).blocks or {}
local chosen
for _,b in ipairs(blocks) do if b.block_id==p.block_id then chosen=b end end
if not chosen then error("focused pane not found") end
if chosen.label=="seat" then error("the seat stays in sight") end
local count=0
for _,b in ipairs(blocks) do if b.window_id==chosen.window_id and b.placement=="placed" then count=count+1 end end
if count<2 then error("the last pane of a tab stays") end
return call("session.detach_block",{session_id=p.session_id,block_id=p.block_id})
'''


def command(host, script, args=None):
    argv = [host['rex'], '--autostart=false', '--server', 'unix://' + host['socket'],
            '--timeout', '5s', 'do', '-e', script, '--args', json.dumps(args or {}), '--json']
    if host['transport'] == 'ssh':
        argv = [*targets.ssh_argv(host), shlex.join(argv)]
    env = {k: v for k, v in os.environ.items() if k not in ('REX_SERVER', 'REX_SESSION', 'REX_BLOCK', 'REX_CLIENT')}
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30, env=env)
    if result.returncode:
        raise ValueError(result.stderr[-2048:] or 'Rex command failed')
    return json.loads(result.stdout)


def timestamp(value):
    match = re.fullmatch(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?(Z|[+-]\d\d:\d\d)', value)
    if not match:
        raise ValueError('invalid Rex status timestamp')
    zone = '+00:00' if match[3] == 'Z' else match[3]
    utc = datetime.datetime.fromisoformat(match[1] + zone).astimezone(datetime.timezone.utc)
    return utc.strftime('%Y-%m-%dT%H:%M:%S') + '.' + (match[2] or '').ljust(9, '0')


def scan(hosts, visited, here, circuit=False):
    rows, sources = [], []
    for name, host in hosts.items():
        try:
            sample = command(host, SCAN)
            positions = {}
            if circuit:
                script = 'local r,e=rex.exec({"python3","-c",' + json.dumps(POSITION) + ',' + json.dumps(host['home']) + '}); if not r then error(e) end; if not r.ok then error(r.stderr) end; return rex.json.decode(r.stdout)'
                positions = {(r['session_id'], r['block_id']): r for r in command(host, script) or []
                             if r.get('server') == 'unix://' + host['socket']}
            for pane in sample['rows'] or []:
                if circuit:
                    agent = positions.get((pane['session_id'], pane['block_id']))
                    if agent and (agent['position']['waiting'] or agent['position'].get('decision')):
                        pane.pop('records', None)
                        pane.update(host=name, **{k: agent[k] for k in ('created_at', 'name', 'position')})
                        rows.append(pane)
                    continue
                if (name, pane['block_id']) == here:
                    continue
                records = pane.pop('records')
                records = records if isinstance(records, list) else []
                ranked = [(('blocked', 'error', 'done').index(r['state']), timestamp(r['updated_at']), r)
                          for r in records if r.get('state') in ('blocked', 'error', 'done')]
                if not ranked:
                    continue
                rank, at, record = min(ranked, key=lambda r: r[:2])
                pane.update(host=name, rank=rank, at=at, state=record['state'])
                if visited.get(name + '/' + pane['block_id']) != at:
                    rows.append(pane)
            sources.append(dict(host=name, ok=True, remote_api=sample['remote_api'], servers_api=sample['servers_api']))
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            sources.append(dict(host=name, ok=False, error=str(exc)))
    order = (lambda p: (p['created_at'], p['host'], p['block_id'])) if circuit else (lambda p: (p['rank'], p['at'], p['host'], p['block_id']))
    return sorted(rows, key=order), sources


def main(argv=None):
    parser = argparse.ArgumentParser(prog="teerex waiting", description=__doc__)
    parser.add_argument('operation', choices=('list', 'next', 'back', 'put-away'))
    parser.add_argument('--config', default=str(Path.home() / '.config/teerex/hosts.json'))
    parser.add_argument('--hosts', help='comma-separated names; default every configured host')
    parser.add_argument('--state', default=str(Path.home() / '.local/state/teerex-waiting/navigation.json'))
    parser.add_argument('--circuit', action='store_true', help='repeat ready agents in fixed launch order; back walks in reverse')
    parser.add_argument('--focus', action='store_true', help='focus winner, presenting detached panes beside their active pane')
    parser.add_argument('--here-host')
    parser.add_argument('--here-server', help='Rex action context server label; resolves to configured host')
    parser.add_argument('--here-session')
    parser.add_argument('--here-block')
    a = parser.parse_args(argv)
    config = targets.load_config(a.config)
    names = a.hosts.split(',') if a.hosts else list(config['hosts'])
    if not names or len(names) != len(set(names)):
        raise ValueError('unique configured hosts required')
    hosts = {name: targets.resolve_host(a.config, name) for name in names}
    if a.here_server and not a.here_host:
        label = a.here_server.rsplit('@', 1)[-1]
        a.here_host = next((name for name, host in hosts.items() if label in (name, host['host_id'], host.get('address', '').rsplit('@', 1)[-1])), None)
    if not a.here_host and a.here_session and a.here_block:
        # Context labels differ between app and CLI. Exact live pane ownership
        # resolves an unfamiliar label without silently treating it as local.
        matches = [name for name, host in hosts.items()
                   if any(p['session_id'] == a.here_session and p['block_id'] == a.here_block
                          for p in command(host, SCAN)['rows'] or [])]
        if len(matches) != 1:
            raise ValueError('context pane does not identify exactly one configured host')
        a.here_host = matches[0]
    if a.operation == 'put-away':
        if a.here_host not in hosts or not a.here_session or not a.here_block:
            raise ValueError('put-away requires a configured context host, session and block')
        print(json.dumps(command(hosts[a.here_host], HIDE, dict(session_id=a.here_session, block_id=a.here_block))))
        return 0
    if a.here_server and not a.here_host:
        raise ValueError('context server does not match a configured host')
    if not os.path.isabs(a.state):
        raise ValueError('absolute state path required')
    state_path = Path(a.state)
    state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(str(state_path) + '.lock', 'a') as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(state_path.read_text()) if state_path.exists() else dict(visited={}, trail=[])
        rows, sources = scan(hosts, state['visited'], (a.here_host, a.here_block), a.circuit)
        complete = all(s['ok'] for s in sources)
        result = dict(kind='waiting_result', complete=complete, sources=sources, waiting=rows, moved=False)
        # A partial scan never chooses a winner; its unseen host could be more urgent.
        if complete and a.operation != 'list':
            winner = (state['trail'][-1] if state['trail'] else None) if a.operation == 'back' else next(iter(rows), None)
            if a.circuit:
                current = next((p for p in rows if (p['host'], p['block_id']) == (a.here_host, a.here_block)), None)
                cursor = ([current['created_at'], current['host'], current['block_id']] if current else state.get('circuit_cursor'))
                keys = [(p['created_at'], p['host'], p['block_id']) for p in rows]
                cursor = tuple(cursor) if cursor else None
                choices = [p for p, key in zip(rows, keys) if cursor is None or
                           (key < cursor if a.operation == 'back' else key > cursor)]
                winner = ((choices[-1] if choices else rows[-1]) if a.operation == 'back' else
                          (choices[0] if choices else rows[0])) if rows else None
            result['winner'] = winner
            if winner and a.focus:
                command(hosts[winner['host']], SHOW, winner)
                if a.circuit:
                    # Save and restore the original tab label when advancing.
                    previous = state.pop('circuit_display', None)
                    try:
                        if previous:
                            command(hosts[previous['host']], LABEL, previous)
                        display = command(hosts[winner['host']], PREPARE, winner)
                        state['circuit_display'] = dict(host=winner['host'], **display)
                    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
                        result['display_error'] = str(exc)
                    state['circuit_cursor'] = [winner['created_at'], winner['host'], winner['block_id']]
                result['moved'] = True
                if a.circuit:
                    pass
                elif a.operation == 'back':
                    state['trail'].pop()
                else:
                    state['visited'][winner['host'] + '/' + winner['block_id']] = winner['at']
                    if a.here_host in hosts and a.here_session and a.here_block:
                        state['trail'].append(dict(host=a.here_host, session_id=a.here_session, block_id=a.here_block))
                temporary = state_path.with_name(state_path.name + '.tmp')
                with open(temporary, 'w') as stream:
                    os.chmod(temporary, 0o600)
                    json.dump(state, stream)
                os.replace(temporary, state_path)
        print(json.dumps(result))
        return 0 if complete else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(json.dumps(dict(kind='waiting_error', error=str(exc))), file=sys.stderr)
        sys.exit(1)
