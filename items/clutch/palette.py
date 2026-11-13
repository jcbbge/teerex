"""Prepare the same native action fragment consumed by surfaces palette install."""
import argparse
import json
import os
from pathlib import Path
import sys


def quote(text):
    return '"' + ''.join('\\' + c if c in '\\"' else '\\%03d' % ord(c) if ord(c) < 32 or ord(c) == 127 else c for c in text) + '"'


def absolute(value):
    if not os.path.isabs(value) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("absolute_path_without_controls_required")
    return value


def main():
    parser = argparse.ArgumentParser(prog='teerex clutch palette', description=__doc__)
    parser.add_argument("--file", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--teerex", default=sys.argv[1])
    args = parser.parse_args(sys.argv[2:])
    for value in (args.file, args.socket, args.teerex):
        absolute(value)
    root = absolute(os.environ.get("TEEREX_CLUTCH_DIR") or str(Path.home() / ".local/state/teerex/clutch"))
    actions = []
    for operation, title in (("take", "Take control of this pane"), ("release", "Hand back")):
        name = "teerex_clutch_" + operation
        command = ["/usr/bin/env", "TEEREX_CLUTCH_DIR=" + root, args.teerex, "clutch", operation, "--socket", args.socket]
        body = ("if not ctx.session_id or not ctx.block_id then error('invoke from an attached pane',0) end\n"
                "local argv=rex.json.decode(" + quote(json.dumps(command, ensure_ascii=False)) + ")\n"
                "for _,v in ipairs({'--session',ctx.session_id,'--pane',ctx.block_id,'--reason','palette " + operation + "'}) do argv[#argv+1]=v end\n"
                "local r=rex.exec(argv,{timeout=3})\n"
                "if type(r)~='table' or not r.ok then error('clutch change unavailable: '..rex.json.encode(r),0) end\n"
                "return rex.json.decode(r.stdout)")
        actions.append("-- teerex-surface-action:" + name + "\nrex.action{name=" + quote(name) + ",title=" + quote(title) +
                       ",category='teerex',run=function(ctx)\n" + body + "\nend}\n")
    fd = os.open(args.file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("-- Cooperative teerex writers only; no Rex input lease.\n" + ''.join(actions))
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps(dict(schema_version=1, kind="clutch_palette", outcome="generated", file=args.file,
                          actions=["teerex_clutch_take", "teerex_clutch_release"], cooperative=True, installed=False)))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(json.dumps(dict(kind="clutch_palette", outcome="refused", reason=str(error))))
        raise SystemExit(1)
