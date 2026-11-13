# Boards, decisions, and the operator seat (current alpha.5)

**Shipped experimental combined-CLI commands.** Use [current setup](../../docs/concierge/setup.md) and the [alpha.5 release support guide](../../docs/releases/v0.1.0-alpha.5.md). Boards is not an independent cartridge; full agent-core cutover remains gated. Dated leaf-only receipts below do not replace released-byte acceptance or certify personal machines.

## Who / What / When / Where / Why / How

**Who:** Joshua operates the fleet; agents submit reports and complete questions. Responsibility labels are supplied claims, not authenticated people or permission. Only a deliberate operator answer should be recorded as a resolution. The tool checks schema, not who authorized that answer.

**What:** `teerex boards inbox` renders pinned full decision cards and six recent activity reports; `teerex boards fleet` renders live read-only terminal inventory and saved agent reports. `teerex boards seat register` explicitly marks an exact pane as an operator seat. Messages append to its private inbox; they never become terminal input. `teerex boards ask` requires a complete typed card or an explicit resolution. `seat inspect`, `inbox inspect`, and `state inspect` expose the authoritative stored state.

**When:** register a seat before agents send to it; run a board only as a visible foreground program in Rex. Resolve decisions explicitly, inspect/export before clearing, and preview remapping after a server restore. An unavailable read or quiet terminal never certifies idle, death, or completion.

**Where:** Python **3.9+ standard library**, Linux/macOS, an explicit existing private `--store ABS` directory on the command host. State is not shared merely because two commands use the same path string on different machines. Every pane reference is `{host,server,session_id,block_id}`, where `server` is the exact `unix:///absolute/socket` endpoint and IDs are full lowercase canonical UUIDs. `--host` inside a board command is the declared configured host_id, not a resolver or physical-locality proof. Root `teerex --config ABS --host NAME ...` performs named-host transport; the board leaf never SSHs or probes alternate machines. m5/hive/m1 are configuration names, not hardcoded machines.

**Why:** the operator needs visible questions, ownership, purpose, source, uncertainty, and a place to type without agent messages overwriting a draft. Every unknown remains visible. No hidden watcher, daemon, restart, focus takeover, or pane input clearing is installed.

**How:** use the commands below, inspect their JSON and exit status, and compose placement with the public `surfaces` command. Root aliases (`seat`, `inbox`, `ask`, `fleet`) are wired in alpha.5; explicit `boards` forms below retain the module's public contract. Root `fleet install/rollback` is the separate installation bridge, not board enumeration. Alpha.4 did not contain these commands.

## Register and open a visible inbox

Create the store deliberately on the command host. All following `$SOCKET`, `$SESSION`, `$SEAT`, `$HOST_ID`, `$STORE`, `$TEEREX` values must name the selected target and absolute executable; none is inferred from the active pane or environment.

```sh
umask 077
mkdir -m 700 /absolute/private/teerex-boards
teerex boards seat register --store "$STORE" --host "$HOST_ID" \
  --socket "$SOCKET" --session "$SESSION" --block "$SEAT" --owner operator
teerex boards seat inspect --store "$STORE" --host "$HOST_ID" \
  --socket "$SOCKET" --session "$SESSION" --block "$SEAT"

# Visible tiled renderer. ratio is the NEW pane's share. No retry or float fallback.
teerex surfaces open --socket "$SOCKET" --session "$SESSION" \
  --layout tiled --anchor "$SEAT" --direction right --ratio 0.333333 \
  --label inbox -- "$TEEREX" boards inbox --store "$STORE" --host "$HOST_ID" \
  --socket "$SOCKET" --session "$SESSION" --block "$SEAT"
```

Choose an explicit float instead with `--layout float --anchor "$SEAT" --bounds '[0.667,0,0.333,1]'`; choose a separate tab with `--layout tab` and no anchor. Creation is exclusively owned by `surfaces`; its receipt separates creation attempts, acknowledgements, and actual `session.view` geometry. Seat registration itself creates no viewer and makes no live-pane claim. Opening a second viewer is explicit, not deduplicated by a hidden saved viewer ID. The board is a normal visible terminal: focus it, read/scroll it, close it, or Ctrl+C its foreground process. No separate background renderer remains. Large/multiple cards use terminal scrollback; not every full card can fit in a small pane at once. `inbox inspect` gives all full bodies without display clipping.

```sh
teerex boards inbox --store "$STORE" --host "$HOST_ID" \
  --socket "$SOCKET" --session "$SESSION" --block "$SEAT" --once --width 40
teerex boards inbox inspect --store "$STORE" --host "$HOST_ID" \
  --socket "$SOCKET" --session "$SESSION" --block "$SEAT"
```

Live boards require a TTY and refresh every 2000 ms by default (`--interval-ms 500..60000`). A pipe must use `--once`; it cannot accidentally become a hidden live watcher. `--once --json` emits one structured snapshot; `--width 32..160` selects one-shot text wrapping. Live width follows the actual terminal. Fresh reads happen sequentially each refresh; there is no atomic fleet snapshot. Full message text and board output are private and unredacted.

## Append without typing; route send fail-closed

```sh
teerex boards inbox append --store "$STORE" --host "$HOST_ID" \
  --socket "$SOCKET" --session "$SESSION" --block "$SEAT" \
  --from worker --message-file /absolute/private/report.txt
# --message-file - accepts bounded UTF-8 stdin.
```

Messages preserve LF/tab, max **65536 UTF-8 bytes**; other C0/DEL controls refuse. No terminal API is called on this path. Messages bearing legacy `DECISION-JSON:` or `DECISION-RESOLVED-JSON:` prefixes refuse: use the typed `ask` interface rather than silently demoting an invalid card to ordinary activity. ACK/report text is not hidden by sender-name filters and grants no launch-ACK authority.

The root send integration owns `teerex send --store ABS --host HOST_ID --socket ABS --session ID --block ID --from NAME --message-file ABS|-`. It calls `rex_boards.tryRoute` **before paste**. The leaf's public equivalent is `teerex boards try-route` with those same flags:

- **Exit 0 / `outcome=recorded`:** appended to the exact registered seat, `terminal_input_attempted=false`, `application_consumption=not_assessed`. Persistence receipt is not a terminal-event acknowledgement, operator approval, or agent consumption.
- **Exit 3 / `outcome=not_registered`:** that exact tuple was absent in the selected store. Stdin has not been touched. The Zig helper returns null and suppresses this receipt so root native send can read stdin once and emit its own single receipt.
- **Any error:** refuse, never fall back to typing. Missing/corrupt/insecure/busy storage and failed saves are not evidence of an unregistered seat.
- `--timeout-ms 100..60000`, default **10000**, bounds registered stdin through EOF and checks the deadline before save. A stalled producer or partial stdin does not append. **124/130/143** preserve deadline/INT/TERM, including through the Zig helper. Filesystem scheduling/fsync and interpreter startup are not hard real-time guarantees; a signal or failure during save can leave persistence uncertain. Inspect before retrying.

Registration and native terminal delivery across clients are **not a server-enforced transaction or input lease**. Every sending participant must use the same command-host store and declared tuple. A sender using another store, direct Rex, or a race with registration is outside that coordination boundary. The leaf does not claim global atomicity, draft detection/restoration, exactly-once remote delivery, or authentication.

## Complete typed decisions

The card file is strict JSON with exactly these fields. Supply **2–8 options**, each with nonempty `label`, `gain`, and `lose`. Labels must differ. `id` is 1–128 bytes; other strings 1–4096 bytes. JSON input is capped at 49152 bytes; unknown/duplicate JSON keys, blank fields, controls, and duplicate retained decision IDs refuse.

```json
{
  "id": "release-7",
  "title": "Choose deployment timing",
  "ask": "Deploy the reviewed fix now?",
  "context": "Checks passed. A restart interrupts active sessions.",
  "options": [
    {"label": "Deploy now", "gain": "Fix available today", "lose": "Interrupt active sessions"},
    {"label": "Wait", "gain": "Keep sessions intact", "lose": "Delay the fix"}
  ],
  "recommend": "Wait until active work finishes; preserve current sessions."
}
```

```sh
teerex boards ask --store "$STORE" --host "$HOST_ID" \
  --socket "$SOCKET" --session "$SESSION" --block "$SEAT" \
  --from worker --card-file /absolute/private/card.json
teerex boards ask --store "$STORE" --host "$HOST_ID" \
  --socket "$SOCKET" --session "$SESSION" --block "$SEAT" \
  --from operator --resolve release-7 --answer 'Wait until sessions finish.'
```

A decision pins above activity until its exact ID is resolved. Unknown/already-resolved IDs refuse; a resolution retains the reported answer and clears only that card. It does not send an answer back to an agent or execute an option. Send that answer deliberately if needed. Timestamp and sender are reports supplied by this command, not verified human identity. Seat clear refuses while any records remain; inbox clear refuses while a decision remains open.

## Fleet: observations, reports, unknown

```sh
teerex boards fleet report --store "$STORE" --host "$HOST_ID" \
  --socket "$SOCKET" --session "$SESSION" --block "$AGENT" \
  --owner worker --purpose 'review the release' --state working --detail 'review started'
teerex boards fleet --store "$STORE" --config /absolute/private/hosts.json --hosts m5,hive,m1
```

The current executable is pinned by the Zig bridge's `selfExePath`; Python-script callers must give `--teerex ABS`. Each exact name is resolved by the shared `teerex targets resolve`, then sampled with `teerex --config ABS --host NAME boards probe`. Root transport pins the configured Rex executable using `TEEREX_INTERNAL_REX`. No private leaf SSH, host-label guessing, host fallback, or silent retry exists. Direct local/forwarded fixtures can instead provide `--targets-file ABS`, JSON `[{"host":"hive","server":"unix:///absolute/rex.sock"}]`.

- **Observation:** Rex API13 server version/instance/host, terminal presence, placement, label, block host, and observation time. Probe attaches for read access to each listed session; it never changes layout, focus, owner, or terminal input. It observes every terminal because Rex cannot independently classify all terminals as agents. Unregistered ones are `unknown_terminal`, owner/purpose/state unknown, not silently omitted. Attached terminal host_id is displayed; inventory is not proof of execution support on that attached host.
- **Report:** recorded owner/purpose/state/detail and report age. Allowed states are `working`, `waiting_on_operator`, `idle`, `dead`, `completed`, `unknown`; even dead/completed remain **reports**, never process certification. Repeated reports reset report age; that is not measured duration of an internal task state. `hook_idle` is not death; `hook_error` is a report; immediate-child exit is not whole-tree death. Launch ACK tokens stay in the agents registry, not in this store.
- **Inference:** `none`. No inference from quiet panes, expired deadlines, absent terminal rows, stale reports, or failed transport. Missing/unselected saved agents remain visible with observation unknown and their report separately retained. Every failed named host emits a visible source row; one-shot partial failure exits 1, never an all-host success. Configured names/host_id are expectations, not observed authentication.

Probe is deliberately **API13 only**; API10/12 reads refuse as unknown, while local inbox/seat/ask operations do not require Rex. Max **16 configured names**, **32 sessions/server**, **128 terminals/server**, **1 MiB decoded response/output per transport** and **8192 diagnostic bytes**. A cap refuses visibly rather than truncating the fleet silently. Each resolver/local read has a 5s client deadline; routed host probe 8s, plus bounded owned-child cleanup and OS scheduling. Named servers are sampled sequentially, so refresh period includes their read time. This is not a performance/energy certification.

## Private bounded state, inspect, clear, recovery

Store directory: existing, owned by current UID, exact **0700**, final symlink refused. `lock`, `state.json`: owned, single-link regular files, exact **0600**, final symlinks refused. Trusted parents/local filesystem required; no ACL/root/same-account isolation guarantee. The stable advisory `flock` coordinates cooperating local invocations; busy fails immediately. It is not a distributed lock, and crash recovery does not steal/delete lock files.

State schema1: `generation`, `seats:[{target,owner,registered_at,records:[{kind,at,from,body}]}]`, `fleet:[{target,owner,purpose,state,at,detail}]`. Kinds: message (body text), decision (full typed card), resolution (`{id,answer}`). All timestamps are command-host wall-clock Unix ms; negative/future age is labeled unknown. Bounded to **32 seats**, **128 records/seat**, **128 fleet reports**, **1 MiB total encoded state**. No automatic eviction. Each open card reserves one resolution slot and 16 KiB so capacity exhaustion cannot strand its resolution. No terminal output, argv, environment, ACK tokens, or implicit capture is retained; explicit message/decision text itself can still be sensitive.

```sh
teerex boards state inspect --store "$STORE"
# Use the exact generation from inspect; clear only after reviewing/exporting privately.
teerex boards inbox clear --store "$STORE" --host "$HOST_ID" \
  --socket "$SOCKET" --session "$SESSION" --block "$SEAT" \
  --generation "$GENERATION" --reason 'reviewed and exported'
# Then inspect again before seat clear, which unregisters only an empty seat.
```

`fleet forget` uses the same exact target, current `--generation`, and explicit `--reason`; it removes only a saved report, never a terminal/process. `seat clear` removes only registration. Neither implies death or cleanup. State generation increases on every save, including clears/remaps; stale generation refuses.

A save writes exclusive **state.next**, file-syncs, renames to state.json, and directory-syncs. This is one local-file update, not global atomicity. An existing state.next blocks saves, never gets overwritten/promoted; committed state stays inspectable. After a crash, stop cooperating writers, privately retain both files, inspect `state.json`, inspect affected resources independently, then reconcile/remove the staging file deliberately. A post-rename fsync failure can leave persistence uncertain: do not retry blindly. Old messages are not imported from UUID-only agent-core logs automatically.

For restore, recovery emits a private JSON map `[{"old":{host,server,session_id,block_id},"new":{host,server,session_id,block_id}}]` only after visible surfaces are verified:

```sh
teerex boards state remap-preview --store "$STORE" --map-file /absolute/private/board-map.json
teerex boards state remap-apply --store "$STORE" --map-file /absolute/private/board-map.json \
  --generation "$PREVIEW_GENERATION" --reason 'verified restored panes; deliberate handoff'
```

Preview changes nothing. Apply changes seat and fleet addresses together in this one store, preserving full cards/answers. It requires the current generation; unknown sources and colliding destinations refuse. Supplied mappings are reports; no live validity is claimed here. Recovery never applies this automatically. No cross-store or cross-host transaction is promised.

## ABI, help, and verification

`rex_boards.run(allocator,args)!u8`: args omit root `boards`; inbox/fleet render modes and seat/inbox/fleet operations, ask, try-route, probe, state are supported. `rex_boards.tryRoute(allocator,args)!?u8`: args omit try-route; null means only verified not_registered, receipt suppressed, stdin untouched. A returned code is final; a thrown error refuses, never calls native send. Runtime uses embedded Python3.9+ stdlib in the foreground (no extra installed script or Python packages). Normal commands exec into Python, preserving pane/PID; tryRoute supervises its bounded child to capture/suppress only the absence receipt. Help exists for every operation. Exit0 requested record/read, 1 refusal/error/unknown, 2 argparse usage, 3 try-route not_registered only, 124 stdin deadline, 130/143 INT/TERM.

For optional standalone ABI development checks, build this bridge with Zig0.15.2; current root integration is already shipped:

```sh
zig fmt --check items/boards
zig build-exe -O ReleaseSmall --dep rex_boards -Mroot=items/boards/test_cli.zig \
  -Mrex_boards=items/boards/main.zig -femit-bin=/absolute/private/boards-cli
TEEREX_BIN=/absolute/private/boards-cli REX_BIN=/absolute/test/rex python3 items/boards/test_boards.py -v
# Combined CLI is the default test target; optional BOARDS_ROUTE_HELPER_BIN selects ABI scratch bridge.
TEEREX_BIN="$PWD/zig-out/bin/teerex" REX_BIN=/absolute/test/rex python3 items/boards/test_boards.py -v
```

On **12 November 2026**, **12 tests passed** on disposable Debian/Linux x86_64 and Apple-silicon **macOS26.3.1**, Python3.13.5/Linux and Python3.14.3/Mac, checksum-pinned Rex preview.16/API13 commit aa2db1b21261b479a550559fb70e2c3a66c07ba2. Public contracts cover complete/incomplete cards, resolution and clear, capacity reservation, privacy/links/locking/staged-crash refusal, remap collisions/generations/retained card, exact routing, stdin size/EOF/deadline/signals, named-host partial-error contract fixtures, actual Rex terminal enumeration, unchanged layout, and a real raw terminal that receives **zero input bytes** while its displayed operator draft remains unchanged. The same live test ran an actual visible foreground inbox through empty → pinned decision → reported resolution refreshes. Additional disposable Mac checks passed actual preview.13/API10 and preview.14/API12 fleet refusal-as-unknown while local seat/inbox/ask/render remained functional; this is not API10/12 fleet support. Standalone ABI scratch validation additionally checks targeted parent INT/TERM forwarding and unchanged unregistered stdin (empty, multiline Unicode,65536 bytes). With combined CLI the helper-only check skips unless its bridge is supplied; root send integration tests belong to the integrator.

Actual surfaces-created panes ran the renderer, and Rex terminal HTML captures were inspected in Chromium at72/40 columns for empty/open/resolved inbox and partial-error fleet. These show rendered terminal content and public geometry readback, **not native Rex.app painting certification**. Named m5/hive/m1 transport was contract-fixture tested, not contacted; no personal machine, setup, restart, install, or release was performed. Real named-host SSH/root dispatch, merged CLI/packaging, authoritative legacy-log import, automatic login-seat setup, actual private-host support, and a published alpha.5 release are not certified by this leaf. See [migration gates](MIGRATION.md) before deleting stopgaps.
