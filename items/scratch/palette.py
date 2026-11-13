"""Generate a native Show scratchpad action for surfaces palette install."""
import argparse
import json
import os
import sys


def quote(value):
    return '"' + ''.join('\\' + c if c in '\\"' else '\\%03d' % ord(c) if ord(c) < 32 or ord(c) == 127 else c for c in value) + '"'


def main():
    p = argparse.ArgumentParser(prog="teerex scratch palette", description=__doc__)
    p.add_argument("--file", required=True)
    p.add_argument("--socket", required=True)
    p.add_argument("--teerex", default=sys.argv[1])
    o = p.parse_args(sys.argv[2:])
    for value in (o.file, o.socket, o.teerex):
        if not os.path.isabs(value) or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("absolute_path_without_controls_required")
    command = [o.teerex, "surfaces", "open", "--socket", o.socket, "--layout", "tiled", "--label", "Scratchpad"]
    body = """-- teerex-surface-action:teerex_scratch_show
rex.action{name='teerex_scratch_show',title='Show scratchpad',category='teerex',run=function(ctx)
if not ctx.session_id or not ctx.block_id then error('invoke from an attached pane',0) end
local argv=rex.json.decode(COMMAND)
for _,v in ipairs({'--session',ctx.session_id,'--anchor',ctx.block_id,'--',BINARY,'scratch','watch','--session',ctx.session_id,'--block',ctx.block_id}) do argv[#argv+1]=v end
local r=rex.exec(argv,{timeout=20})
if type(r)~='table' or not r.ok then error('scratchpad opening uncertain; inspect before retry',0) end
return rex.json.decode(r.stdout)
end}
""".replace("COMMAND", quote(json.dumps(command))).replace("BINARY", quote(o.teerex))
    fd = os.open(o.file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(body)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps(dict(outcome="generated", file=o.file, installed=False)))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
