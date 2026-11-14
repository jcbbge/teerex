"""Shared pane authority checked immediately before Rex control calls.

Local cooperative CLI policy, not an OS security boundary against the same uid.
Missing or unreadable authority fails closed. Seat protection always wins.
"""
import json
import os
from pathlib import Path
import stat
import sys
import hashlib
import urllib.parse


def read(path, default=None):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return default
    with os.fdopen(fd) as f:
        s = os.fstat(f.fileno())
        if not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid():
            raise ValueError('pane_authority_requires_owned_regular_file')
        return json.load(f)


def state_root():
    return Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state')))


def canonical_server(value):
    if not isinstance(value, str) or not value.startswith('unix://'):
        return None
    path = urllib.parse.unquote(value[7:])
    if not os.path.isabs(path):
        return None
    return 'unix://' + os.path.realpath(path)


def snapshot(server):
    server = canonical_server(server)
    if server is None:
        raise ValueError('pane_guard_absolute_unix_socket_required')
    root = state_root()
    store = Path(os.environ.get('TEEREX_BOARDS_STORE', str(root / 'teerex-boards')))
    boards = read(store / 'state.json', {'seats': []})
    actor = dict(session_id=os.environ.get('REX_SESSION') or os.environ.get('LC_REX_SESSION'),
                 block_id=os.environ.get('REX_BLOCK') or os.environ.get('LC_REX_BLOCK'))
    directory = root / 'teerex/pane-creators' / hashlib.sha256(server.encode()).hexdigest()
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    s = directory.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or stat.S_IMODE(s.st_mode) != 0o700:
        raise ValueError('pane_creator_directory_requires_private_owned_directory')
    creators = {}
    for path in directory.glob('*.json'):
        record = read(path)
        if canonical_server(record['server']) == server:
            creators[record['id']] = record
    registry = Path(os.environ.get('AGENT_REGISTRY') or os.environ.get('LC_AGENT_REGISTRY') or root / 'teerex-agents')
    for path in registry.glob('agents-*.json'):
        record = read(path)
        target = record.get('target') or {}
        if canonical_server(target.get('server')) != server:
            continue
        starter = record.get('starter') or {}
        spawner = {k: starter.get(k) for k in ('session_id', 'block_id')}
        if target.get('block_id') and not record.get('human'):
            report_to = {k: (record.get('report_to') or {}).get(k) for k in ('session_id', 'block_id')}
            supervisor = {k: target.get(k) for k in ('session_id', 'block_id')}
            creators.setdefault(target['block_id'], dict(spawner=spawner, allowed=[spawner, report_to, supervisor]))
        side = (record.get('scratch_pane_receipt') or {}).get('created') or {}
        if side.get('block_id') and (record.get('scratch_pane_receipt') or {}).get('outcome') == 'created_and_verified':
            supervisor = {k: target.get(k) for k in ('session_id', 'block_id')}
            creators[side['block_id']] = dict(spawner=spawner, allowed=[spawner, supervisor], viewer=True)
    seats = [s['target'] for s in boards['seats'] if canonical_server(s['target']['server']) == server and not s.get('inherited_to')]
    operator = (os.environ.get('TEEREX_OPERATOR') == '1' and
                os.environ.get('TEEREX_OPERATOR_ACTIVE') in (str(os.getpid()), str(os.getppid())) and
                not any(os.environ.get(k) for k in ('AGENT_LAUNCH_ID', 'LC_AGENT_LAUNCH_ID', 'AGENT_NAME', 'LC_AGENT_NAME')))
    if operator and any(actor['block_id'] == seat['block_id'] and actor['session_id'] == seat['session_id'] for seat in seats):
        raise ValueError('registered_seat_pane_is_not_the_operator_terminal')
    return dict(server=server, actor=actor, creators=creators, directory=str(directory), operator=operator, seats=seats)


LUA = r'''
local guard_call=rex.call
local guard_policy=rex.json.decode(GUARD_DATA)
local function guard_view(sid)
 guard_call('session.attach',{session_id=sid})
 local v,e=guard_call('session.view',{session_id=sid})
 if type(v)~='table' or v.session_id~=sid then error('pane_guard_view_unavailable',0) end
 return v
end
local function guard_window(view,bid)
 for _,w in ipairs(view.windows or {}) do
  for _,l in ipairs(w.layers or {}) do for _,b in ipairs(l.blocks or {}) do
   if b.block_id==bid then return w.window_id end
  end end
 end
end
local function guard_owner(id)
 local r=guard_policy.creators[id]
 if not r then error('no_recorded_spawner',0) end
 local spawner=r and r.spawner or {}
 local allowed=false
 for _,who in ipairs(r and r.allowed or {}) do
  if type(who.block_id)=='string' and type(who.session_id)=='string' and
   who.block_id:match('^block:[0-9a-f%-]+$') and #who.block_id==42 and
   who.session_id:match('^session:[0-9a-f%-]+$') and #who.session_id==44 and
   who.block_id==guard_policy.actor.block_id and who.session_id==guard_policy.actor.session_id then allowed=true end
 end
 if not allowed then error('pane control refused; recorded spawner: '..(spawner.session_id or 'unknown')..' '..(spawner.block_id or 'unknown'),0) end
end
local function guard_record(id,sid)
 if type(id)~='string' or not id:match('^[a-z]+:[0-9a-f%-]+$') then error('invalid_creator_receipt_id',0) end
 local record={id=id,session_id=sid,server=guard_policy.server,spawner=guard_policy.actor,allowed={guard_policy.actor}}
 guard_policy.creators[id]=record
 local path=guard_policy.directory..'/'..id:gsub(':','-')..'.json'
 local file,err=io.open(path..'.next','w')
 if not file then io.stderr:write('pane creator recording failed: '..tostring(err)..'\n'); return end
 local written,write_err=file:write(rex.json.encode(record)); local closed,close_err=file:close()
 if not written or not closed then
  io.stderr:write('pane creator recording failed: '..tostring(write_err or close_err)..'\n'); os.remove(path..'.next'); return
 end
 local renamed,rename_err=os.rename(path..'.next',path)
 if not renamed then io.stderr:write('pane creator recording failed: '..tostring(rename_err)..'\n'); os.remove(path..'.next') end
end
local guard_controls={['block.close']=true,['session.destroy']=true,
 ['session.set_window_label']=true,['session.set_block_label']=true,
 ['session.move_block']=true,['session.focus_block']=true,
 ['session.resize_pane']=true,['session.resize_layer']=true,
 ['session.zoom_block']=true,['session.detach_block']=true,
 ['session.close_window']=true,['session.close_layer']=true,
 ['session.focus_window']=true,['session.focus_direction']=true,
 ['session.focus_next_pane']=true,['session.focus_previous_pane']=true,
 ['session.focus_next_window']=true,['session.focus_previous_window']=true,
 ['session.new_split']=true,['session.new_layer']=true,
 ['com.superlogical.terminal.resize']=true,['com.superlogical.terminal.key']=true,
 ['com.superlogical.terminal.write']=true,['com.superlogical.terminal.paste']=true}
rex.call=function(method,p)
 p=p or {}
 if method=='teerex.guard.operator' then return guard_policy.operator end
 if method=='session.destroy' then
  for _,seat in ipairs(guard_policy.seats) do
   if seat.session_id==p.session_id then error('registered_seat_session_cannot_be_closed',0) end
  end
 end
 local viewer_cleanup=method=='teerex.guard.viewerclose'
 if viewer_cleanup then method='block.close' end
 local control=guard_controls[method] or method=='teerex.guard.take'
 local raw=method=='block.event'
 if (control or raw) and not guard_policy.operator then
  for _,seat in ipairs(guard_policy.seats) do
   if seat.session_id==p.session_id then
    local protected=method=='session.destroy'
    local v=guard_view(p.session_id)
    local sw=guard_window(v,seat.block_id)
    if not sw then error('registered_seat_tab_unavailable',0) end
    local tw=p.window_id or guard_window(v,p.block_id) or guard_window(v,p.anchor_id)
    if p.layer_id then
     for _,w in ipairs(v.windows or {}) do for _,l in ipairs(w.layers or {}) do
      if l.layer_id==p.layer_id then tw=w.window_id end
     end end
    end
    if method:match('^session%.focus_') and not tw then
     -- Relative focus can select the protected tab without naming its pane.
     protected=true
    end
    protected=protected or tw==sw or guard_window(v,p.anchor_block_id)==sw
      or guard_window(v,p.before_block_id)==sw or guard_window(v,p.after_block_id)==sw
    if protected and raw then
     local event=p.event or {}; local key=event.payload or {}
     local allowed=GUARD_MESSAGE and rex.args.draft_mode=='guard' and (event.type=='paste' or
       (event.type=='key' and (key.key=='enter' and (key.mods or '')=='' or
         key.key=='u' and key.mods=='ctrl')))
     if not allowed then error('registered_seat_tab_refuses_raw_input',0) end
    elseif protected then error('registered_seat_tab_is_operator_only',0) end
   end
  end
 end
 local owned=method=='block.close' or method=='session.destroy' or method=='session.move_block'
   or method=='session.set_block_label' or method=='session.set_window_label' or method=='session.detach_block'
 if owned and not guard_policy.operator then
  if method=='session.destroy' then guard_owner(p.session_id)
  elseif p.window_id then
   local v=guard_view(p.session_id)
   for _,w in ipairs(v.windows or {}) do if w.window_id==p.window_id then
    for _,l in ipairs(w.layers or {}) do for _,b in ipairs(l.blocks or {}) do guard_owner(b.block_id) end end
   end end
  elseif viewer_cleanup and p.block_id==guard_policy.actor.block_id and
   guard_policy.creators[p.block_id] and guard_policy.creators[p.block_id].viewer then
   -- The watcher may close only itself after its recorded owner disappears.
   local owner_present=false
   local blocks=guard_call('session.list_blocks',{session_id=p.session_id})
   if type(blocks)~='table' then error('viewer_owner_check_unavailable',0) end
   local record=guard_policy.creators[p.block_id]
   local supervisor=record.allowed[2]
   for _,b in ipairs(blocks.blocks or {}) do if b.block_id==supervisor.block_id then owner_present=true end end
   if owner_present then error('viewer_owner_still_live',0) end
  elseif method=='block.close' and p.session_id==guard_policy.actor.session_id and
   p.block_id==guard_policy.actor.block_id and guard_policy.creators[p.block_id] and
   not guard_policy.creators[p.block_id].viewer then
   -- A recorded pane's supervisor may close its own pane, never another pane.
  else guard_owner(p.block_id) end
 end
 if method=='teerex.guard.take' then return {allowed=true} end
 local value,err=guard_call(method,p)
 if type(value)=='table' then
  if method=='session.create' then guard_record(value.session_id,value.session_id) end
  if method=='session.new_window' or method=='session.new_split' or method=='session.new_layer' then
   for _,bid in ipairs(value.block_ids or {}) do guard_record(bid,p.session_id) end
  elseif method=='session.new_block' then guard_record(value.block_id,p.session_id) end
 end
 return value,err
end
'''


def prelude(server, message=False):
    data = json.dumps(json.dumps(snapshot(server), separators=(',', ':')))
    return 'do\nlocal GUARD_DATA=' + data + '\nlocal GUARD_MESSAGE=' + ('true' if message else 'false') + '\n' + LUA + '\nend\n'


def authorize(server, method, payload, rpc):
    """Use the same guard for the replay controller's native wire connection."""
    guarded = {'block.close', 'session.destroy', 'session.set_window_label',
               'session.set_block_label', 'session.move_block', 'session.focus_block',
               'session.resize_pane', 'com.superlogical.terminal.resize',
               'com.superlogical.terminal.key', 'com.superlogical.terminal.write',
               'com.superlogical.terminal.paste', 'block.event'}
    if method not in guarded:
        return
    def window(view, bid):
        for w in view.get('windows', []):
            for layer in w.get('layers', []):
                if any(b['block_id'] == bid for b in layer.get('blocks', [])):
                    return w['window_id']
    policy = snapshot(server)
    if method == 'session.destroy' and any(seat['session_id'] == payload.get('session_id') for seat in policy['seats']):
        raise ValueError('registered_seat_session_cannot_be_closed')
    if policy['operator']:
        return
    for seat in policy['seats']:
        if seat['session_id'] != payload.get('session_id'):
            continue
        view = rpc('session.view', {'session_id': seat['session_id']})
        sw = window(view, seat['block_id'])
        if not sw:
            raise ValueError('registered_seat_tab_unavailable')
        if method == 'session.destroy' or (payload.get('window_id') or window(view, payload.get('block_id'))) == sw:
            raise ValueError('registered_seat_tab_is_operator_only')
    if method in {'block.close', 'session.destroy', 'session.move_block', 'session.set_block_label', 'session.set_window_label'}:
        ids = [payload.get('session_id') if method == 'session.destroy' else payload.get('block_id')]
        if payload.get('window_id'):
            view = rpc('session.view', {'session_id': payload['session_id']})
            ids = [b['block_id'] for w in view['windows'] if w['window_id'] == payload['window_id']
                   for layer in w.get('layers', []) for b in layer.get('blocks', [])]
        for id in ids:
            creator = policy['creators'].get(id)
            if creator is None:
                raise ValueError('no_recorded_spawner')
            if (method == 'block.close' and not creator.get('viewer') and
                    policy['actor'] == dict(session_id=payload.get('session_id'), block_id=id)):
                continue
            if not policy['actor'].get('block_id') or policy['actor'] not in creator.get('allowed', []):
                spawner = creator.get('spawner', {})
                raise ValueError('pane control refused; recorded spawner: ' + str(spawner.get('session_id', 'unknown')) + ' ' + str(spawner.get('block_id', 'unknown')))


def record_created(server, method, payload, result):
    ids = []
    if method in {'session.new_window', 'session.new_split', 'session.new_layer'}:
        ids = result.get('block_ids', [])
    elif method == 'session.new_block':
        ids = [result['block_id']]
    elif method == 'session.create':
        ids = [result['session_id']]
    if not ids:
        return
    policy = snapshot(server)
    for id in ids:
        path = Path(policy['directory']) / (id.replace(':', '-') + '.json')
        record = dict(id=id, session_id=payload.get('session_id', id), server=policy['server'],
                      spawner=policy['actor'], allowed=[policy['actor']])
        temporary = path.with_name(path.name + '.next')
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as f:
                json.dump(record, f)
            os.link(temporary, path)
        except OSError as exc:
            print('pane creator recording failed: ' + str(exc), file=sys.stderr)
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        print(prelude(sys.argv[1], len(sys.argv) > 2 and sys.argv[2] == 'message'))
    except Exception as exc:
        sys.exit('pane_guard_unavailable: ' + str(exc))
