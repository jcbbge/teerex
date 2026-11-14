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


def snapshot(server):
    root = state_root()
    store = Path(os.environ.get('TEEREX_BOARDS_STORE', str(root / 'teerex-boards')))
    boards = read(store / 'state.json', {'seats': []})
    return dict(server=server, seats=[s['target'] for s in boards['seats']
                if s['target']['server'] == server])


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
local guard_controls={['block.close']=true,['session.destroy']=true,
 ['session.set_window_label']=true,['session.set_block_label']=true,
 ['session.move_block']=true,['session.focus_block']=true,
 ['session.resize_pane']=true,['session.set_layer_bounds']=true,
 ['session.zoom_block']=true,['session.toggle_zoom']=true,
 ['session.detach_block']=true,['session.set_split_ratio']=true,
 ['com.superlogical.terminal.resize']=true,['com.superlogical.terminal.key']=true,
 ['com.superlogical.terminal.write']=true,['com.superlogical.terminal.paste']=true}
rex.call=function(method,p)
 p=p or {}
 local control=guard_controls[method] or method=='teerex.guard.take'
 local raw=method=='block.event'
 if control or raw then
  for _,seat in ipairs(guard_policy.seats) do
   if seat.session_id==p.session_id then
    local protected=method=='session.destroy'
    local v=guard_view(p.session_id)
    local sw=guard_window(v,seat.block_id)
    if not sw then error('registered_seat_tab_unavailable',0) end
    local tw=p.window_id or guard_window(v,p.block_id)
    protected=protected or tw==sw or guard_window(v,p.anchor_block_id)==sw
      or guard_window(v,p.before_block_id)==sw or guard_window(v,p.after_block_id)==sw
    if protected and raw then
     local event=p.event or {}; local key=event.payload or {}
     local allowed=GUARD_MESSAGE and (event.type=='paste' or
       (event.type=='key' and (key.key=='enter' and (key.mods or '')=='' or
         key.key=='u' and key.mods=='ctrl')))
     if not allowed then error('registered_seat_tab_refuses_raw_input',0) end
    elseif protected then error('registered_seat_tab_is_operator_only',0) end
   end
  end
 end
 if method=='teerex.guard.take' then return {allowed=true} end
 return guard_call(method,p)
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
    for seat in snapshot(server)['seats']:
        if seat['session_id'] != payload.get('session_id'):
            continue
        view = rpc('session.view', {'session_id': seat['session_id']})
        sw = window(view, seat['block_id'])
        if not sw:
            raise ValueError('registered_seat_tab_unavailable')
        if method == 'session.destroy' or (payload.get('window_id') or window(view, payload.get('block_id'))) == sw:
            raise ValueError('registered_seat_tab_is_operator_only')


if __name__ == '__main__':
    try:
        print(prelude(sys.argv[1], len(sys.argv) > 2 and sys.argv[2] == 'message'))
    except Exception as exc:
        sys.exit('pane_guard_unavailable: ' + str(exc))
