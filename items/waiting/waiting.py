"""Cross-host navigation for registered agents only; excludes seats and utility panes."""
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


# Read on the selected host, alongside its Rex scan. Missing registries mean no
# managed agents; malformed/unreadable evidence fails the host scan closed.
MANAGED = r'''
import json, sys
from pathlib import Path
home, socket, store = sys.argv[1:]
root=Path(home)/'.local/state/teerex-agents'
rows=[]
for path in sorted(root.glob('agents-*.json')):
    if len(rows)>=1024: raise ValueError('agent registry limit 1024')
    if path.is_symlink() or path.stat().st_size>262144: raise ValueError('invalid agent record')
    state=json.loads(path.read_text())
    if state.get('socket')==socket and state.get('tracked') and not state.get('retired'):
        rows.append(dict(target=state['target'],name=state.get('name')))
seats=[]
path=Path(store)/'state.json'
if path.exists():
    if path.is_symlink() or path.stat().st_size>1048576: raise ValueError('invalid board state')
    seats=[s['target'] for s in json.loads(path.read_text()).get('seats',[])]
print(json.dumps(dict(agents=rows,seats=seats)))
'''


def managed(host):
    argv = ['python3', '-I', '-c', MANAGED, host['home'], host['socket'], host['store']]
    if host['transport'] == 'ssh':
        argv = [*targets.ssh_argv(host), shlex.join(argv)]
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError(result.stderr[-2048:] or 'agent registry read failed')
    return json.loads(result.stdout)


def timestamp(value):
    match = re.fullmatch(r'(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?(Z|[+-]\d\d:\d\d)', value)
    if not match:
        raise ValueError('invalid Rex status timestamp')
    zone = '+00:00' if match[3] == 'Z' else match[3]
    utc = datetime.datetime.fromisoformat(match[1] + zone).astimezone(datetime.timezone.utc)
    return utc.strftime('%Y-%m-%dT%H:%M:%S') + '.' + (match[2] or '').ljust(9, '0')


def scan(hosts, visited, here):
    rows, sources, eligible = [], [], set()
    for name, host in hosts.items():
        try:
            registered = managed(host)
            agents = {(r['target']['session_id'], r['target']['block_id']) for r in registered['agents']
                      if r.get('name') != 'seat'}
            seats = {(r['session_id'], r['block_id']) for r in registered['seats']
                     if r['server'] == 'unix://' + host['socket']}
            sample = command(host, SCAN)
            for pane in sample['rows'] or []:
                label = (pane.get('label') or '').lower()
                address = (pane['session_id'], pane['block_id'])
                if (address not in agents or address in seats or label in ('seat', 'board', 'teerex board')
                        or label.endswith((' scratchpad', ' receipt'))):
                    continue
                eligible.add((name, pane['session_id'], pane['block_id']))
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
    return sorted(rows, key=lambda p: (p['rank'], p['at'], p['host'], p['block_id'])), sources, eligible


def main(argv=None):
    parser = argparse.ArgumentParser(prog="teerex waiting", description=__doc__)
    parser.add_argument('operation', choices=('list', 'next', 'back', 'put-away'))
    parser.add_argument('--config', default=str(Path.home() / '.config/teerex/hosts.json'))
    parser.add_argument('--hosts', help='comma-separated names; default every configured host')
    parser.add_argument('--state', default=str(Path.home() / '.local/state/teerex-waiting/navigation.json'))
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
        rows, sources, eligible = scan(hosts, state['visited'], (a.here_host, a.here_block))
        complete = all(s['ok'] for s in sources)
        result = dict(kind='waiting_result', complete=complete, sources=sources, waiting=rows, moved=False)
        # A partial scan never chooses a winner; its unseen host could be more urgent.
        if complete and a.operation != 'list':
            winner = (next((entry for entry in reversed(state['trail'])
                            if (entry['host'], entry['session_id'], entry['block_id']) in eligible), None)
                      if a.operation == 'back' else next(iter(rows), None))
            result['winner'] = winner
            if winner and a.focus:
                command(hosts[winner['host']], SHOW, winner)
                result['moved'] = True
                if a.operation == 'back':
                    state['trail'] = state['trail'][:state['trail'].index(winner)]
                else:
                    state['visited'][winner['host'] + '/' + winner['block_id']] = winner['at']
                    if (a.here_host, a.here_session, a.here_block) in eligible:
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
