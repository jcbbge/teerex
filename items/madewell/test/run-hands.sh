#!/bin/sh
set -eu

item=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
tmp=$(mktemp -d "${XDG_RUNTIME_DIR:-${TMPDIR:-/tmp}}/mw-hands.XXXXXXXX") || exit 1
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

export MW_CALL='probe.1' MW_RETURN="$tmp/return"
title=$(printf '%s' "$MW_CALL" | base64)
for case in done missing failed; do
    rm -f -- "$MW_RETURN"
    code=0
    case "$case" in
        done)
            "$item/hand" sh -c 'printf pong > "$MW_RETURN.tmp" && mv "$MW_RETURN.tmp" "$MW_RETURN"' > "$tmp/actual" || code=$?
            [ "$code" -eq 0 ]
            [ "$(cat "$MW_RETURN")" = pong ]
            state=done
            message=
            ;;
        missing)
            "$item/hand" true > "$tmp/actual" || code=$?
            [ "$code" -eq 70 ]
            [ ! -e "$MW_RETURN" ]
            state=error
            message="Hand exited without writing its return file"
            ;;
        failed)
            "$item/hand" sh -c 'touch "$MW_RETURN"; exit 9' > "$tmp/actual" || code=$?
            [ "$code" -eq 9 ]
            state=error
            message="Hand exited with code 9"
            ;;
    esac
    {
        printf '\033]7501;state=working:app=madewell:title=%s\033\\' "$title"
        printf '\033]7501;state=%s:app=madewell:title=%s' "$state" "$title"
        if [ -n "$message" ]; then
            printf ':msg=%s' "$(printf '%s' "$message" | base64)"
        fi
        printf '\033\\'
    } > "$tmp/expected"
    cmp "$tmp/expected" "$tmp/actual"
    printf 'PASS wrapper %s\n' "$case"
done

unset REX_SESSION REX_BLOCK REX_CLIENT LC_REX_SESSION LC_REX_BLOCK
unset AGENT_NAME AGENT_PANE AGENT_PURPOSE AGENT_QUIET AGENT_REPORT_TO AGENT_SCRATCHPAD AGENT_SESSION AGENT_SPAWNER_ADDRESS

mkdir "$tmp/state"
printf '%s\n' '-- disposable test server' > "$tmp/init.lua"
rr server start --state-dir "$tmp/state" --config "$tmp/init.lua" --restore=false \
    --max-blocks 0 --max-windows 0 --max-panes 0 --max-sessions 0
rr new mw-hands
export LUA_PATH="$item/lua/?.lua;;"
rr do -s mw-hands "$item/test/hands.lua" "item=$item" "dir=$tmp" --json
printf '%s\n' '#!/bin/sh' 'exit 0' > "$tmp/sleep"
chmod +x "$tmp/sleep"
"$item/bin/mw" --autostart=false -s mw-hands "$item/test/composition.lua" "item=$item" "dir=$tmp"
if [ "${1-}" = "--live" ]; then
    rm -f -- "$MW_RETURN"
    rr do -s mw-hands "$item/test/hands.lua" "item=$item" "dir=$tmp" live=true --json
fi
