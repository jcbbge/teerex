#!/bin/sh
# The engine journal gate. Needs a running journal node (journal/node.mjs) and the library credential.
#   MW_ENGINE_ENDPOINT   default http://127.0.0.1:7420
#   MW_ENGINE_CREDENTIALS default ~/.local/share/agent-credentials/madewell-journal
# 1. the core cases on the engine store; 2. the ping demo on a disposable Rex server, saved through the
# engine, then rerun: the rerun must replay every saved return and launch nothing.
set -eu
item=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
endpoint=${MW_ENGINE_ENDPOINT:-http://127.0.0.1:7420}
credentials=${MW_ENGINE_CREDENTIALS:-$HOME/.local/share/agent-credentials/madewell-journal}
engine=$(python3 -c 'import json,sys; print(json.dumps({"endpoint":sys.argv[1],"credentials":sys.argv[2]}))' "$endpoint" "$credentials")

MW_TEST_ENGINE=$engine sh "$item/test/run-core.sh"

tmp=$(mktemp -d "${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}/mw-engine.XXXXXXXX") || exit 1
export REX_SERVER="unix://$tmp/rex.sock"
rr() {
    rex -S "$REX_SERVER" --autostart=false "$@"
}
cleanup() {
    code=$?
    trap - EXIT
    if [ -S "$tmp/rex.sock" ]; then
        rr server stop || exit 1
    fi
    rm -rf -- "$tmp" || exit 1
    [ "$code" -eq 0 ] || exit 1
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

printf '%s\n' '-- disposable test server' > "$tmp/init.lua"
rr server start --state-dir "$tmp/state" --config "$tmp/init.lua" --restore=false \
    --max-blocks 0 --max-windows 0 --max-panes 0 --max-sessions 0
rr new mw-engine
run=${MW_ENGINE_RUN:-ping-engine-$(date +%Y%m%d-%H%M%S)-$$}
# The WI-1 ping (demo/josh.lua) without questions; MW_ENGINE_LIVE=1 makes a Codex hand answer.
args=$(python3 -c 'import json,sys; print(json.dumps({"run":sys.argv[1],"store":"engine","engine":json.loads(sys.argv[2]),"place":"detached","auto":True,"inputs":["ping"],"live":sys.argv[3]=="1"}))' "$run" "$engine" "${MW_ENGINE_LIVE:-0}")
for pass in first rerun; do
    LUA_PATH="$item/lua/?.lua;;" rr do -s mw-engine "$item/demo/josh.lua" --args "$args" --json > "$tmp/$pass.json"
done
python3 - "$tmp/first.json" "$tmp/rerun.json" <<'PY'
import json, re, sys
def read(path):
    text = re.sub(r"\x1b\]7501;[^\x1b]*\x1b\\", "", open(path).read())
    summary = re.search(r"(\d+) returned, (\d+) replayed, (\d+) failed", text)
    return json.loads(text[text.index("{"):]), summary and tuple(map(int, summary.groups()))
(first, first_counts), (rerun, rerun_counts) = read(sys.argv[1]), read(sys.argv[2])
print("first:", first_counts, "rerun:", rerun_counts)
assert first == rerun, "the rerun's result differs from the first run's"
assert "verified pong" in json.dumps(first["shipped"]), "the demo did not ship a verified pong"
assert first_counts and first_counts[0] > 0 and first_counts[2] == 0, "the first run saved nothing"
assert rerun_counts and rerun_counts[0] == 0 and rerun_counts[2] == 0 and rerun_counts[1] > 0, "the rerun did not replay"
PY
echo "PASS engine journal: core cases, ping saved through the engine, rerun replayed ($run)"
