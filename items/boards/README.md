# Boards, decisions, and the operator seat (current alpha.5)

**Shipped experimental combined-CLI commands.** Use [current setup](../../docs/concierge/setup.md) and the [alpha.5 release support guide](../../docs/releases/v0.1.0-alpha.5.md). Boards is not an independent cartridge; full agent-core cutover remains gated. Dated leaf-only receipts below do not replace released-byte acceptance or certify personal machines.

## Who / What / When / Where / Why / How

**Who:** Joshua operates the fleet; agents submit reports and complete questions. Responsibility labels are supplied claims, not authenticated people or permission. Only a deliberate operator answer should be recorded as a resolution. The tool checks schema, not who authorized that answer.

**What:** `teerex boards inbox` renders pinned full decision cards and six recent activity reports; `teerex boards fleet` renders live terminal inventory with explicit keyboard actions; one-shot views remain read-only. `teerex boards seat register` explicitly marks an exact pane as an operator seat. Legacy inbox append/send routing retains private history. `teerex boards ask` types a complete decision card or resolution directly into the target pane through native guarded `send`; history is optional. `seat inspect`, `inbox inspect`, and `state inspect` expose the authoritative stored state.

**When:** register a seat before agents send to it; run a board only as a visible foreground program in Rex. Resolve decisions explicitly, inspect/export before clearing, and preview remapping after a server restore. An unavailable read or quiet terminal never certifies idle, death, or completion.

**Where:** Python **3.9+ standard library**, Linux/macOS, an explicit existing private `--store ABS` directory on the command host. State is not shared merely because two commands use the same path string on different machines. Every pane reference is `{host,server,session_id,block_id}`, where `server` is the exact `unix:///absolute/socket` endpoint and IDs are full lowercase canonical UUIDs. `--host` inside a board command is the declared configured host_id, not a resolver or physical-locality proof. Root `teerex --config ABS --host NAME ...` performs named-host transport; the board leaf never SSHs or probes alternate machines. m5/hive/m1 are configuration names, not hardcoded machines.

**Why:** the operator needs visible questions, ownership, purpose, source, uncertainty, and a place to type without agent messages overwriting a draft. Every unknown remains visible. No hidden watcher, daemon, restart, focus takeover, or pane input clearing is installed.

**How:** use the commands below, inspect their JSON and exit status, and compose placement with the public `surfaces` command. Root aliases (`seat`, `inbox`, `ask`, `fleet`) are wired in alpha.5; explicit `boards` forms below retain the module's public contract. Root `fleet install/rollback` is the separate installation bridge, not board enumeration. Alpha.4 did not contain these commands.

## Source-only named-host routing repair (#16)

Published alpha.5's family-level selector insertion breaks named `boards state|seat|inbox OP`. Current source [routes by complete leaf](../../docs/alpha5.md#leaf-aware-named-host-routing-issue16): state inspect/remap gets store only; seat/inbox/fleet mutations get socket/host/store; inbox renderer is targeted; fleet renderer gets store only and accepts its own explicit fleet config/hosts. Root aliases retain the same contract and explicit store overrides still work. Real named-root register/inspect/inbox/remap/clear/forget tests pass without invoking Rex for offline state. This is not an updated alpha.5 archive or permission to act on personal state.

## Optional historical inbox registration and viewer

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
- `--timeout-ms 100..115000`, default **draft wait + 10000** (40000 by default; ignore10000), bounds registered stdin through EOF and checks the deadline before save. A stalled producer or partial stdin does not append. Root send accepts `--draft guard|ignore` and `--draft-wait-ms 0..55000`; registered routes never type, while unregistered fallback uses the native draft guard. **124/130/143** preserve deadline/INT/TERM, including through the Zig helper. Filesystem scheduling/fsync and interpreter startup are not hard real-time guarantees; a signal or failure during save can leave persistence uncertain. Inspect before retrying.

Registration and native terminal delivery across clients are **not a server-enforced transaction or input lease**. Every sending participant must use the same command-host store and declared tuple. A sender using another store, direct Rex, or a race with registration is outside that coordination boundary. The leaf does not claim global atomicity, draft detection/restoration, exactly-once remote delivery, or authentication.

## Decisions typed into the pane

`ask` calls the current CLI's native `send` with **no store selector**, so a registered seat receives terminal input. The default draft guard applies; `--draft guard|ignore` and `--draft-wait-ms 0..55000` have native send semantics. Native delivery receipts, uncertainty and exit codes are preserved. There is no automatic resend. A failed/uncertain delivery does not create a history record. With optional `--store`, a registered seat retains the card **after** successful delivery; this is not atomic with terminal input. `delivered_history_failed` means delivery succeeded but history failed: inspect and never resend automatically. Cancellation reports attempted delivery and requires inspection.

For an inline card, use the agent-core card fields directly (the same plain-text format):

```sh
teerex ask --host "$HOST_ID" --socket "$SOCKET" --session "$SESSION" --block "$SEAT" \
  --from worker --id deploy-7 --title 'Choose deployment timing' \
  --ask 'Deploy now?' --context 'Checks passed; restart interrupts active work.' \
  --option 'Deploy now :: fix available today :: interrupt active work' \
  --option 'Wait :: preserve active work :: delay the fix' \
  --recommend 'Wait until sessions finish.'
```

`--id` defaults to random hex for inline cards; a successful receipt includes `decision_id` and whether history was recorded. Repeat `--option` 2–8 times as `Label :: gain :: loss`; all fields receive the same strict validation as JSON. `--card-file` and inline fields conflict. On a new card, optional `--answer TEXT` adds the agent-core `Reply:` hint (the strict history card schema retains the decision fields). A resolution needs only `--resolve ID --answer TEXT`; without history, no registration is required. `--host` labels the exact command-host target; it is not transport selection. The root named-host form supplies host/socket/store using the existing routing contract.

### JSON cards and optional history

The card file is strict JSON with the six required fields below and optional `prepared`. Supply **2–8 options**, each with nonempty `label`, `gain`, and `lose`. Labels must differ. `id` is 1–128 bytes; other strings 1–4096 bytes. JSON input is capped at 49152 bytes; unknown/duplicate JSON keys, blank fields, controls, and duplicate active decision IDs refuse.

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

When `--store` is supplied, a decision pins in the historical board until its exact ID is resolved. Unknown/already-resolved IDs refuse; a resolution retains the reported answer and clears only that card. The resolution is typed into the selected pane; it does not execute an option. Select the original agent pane explicitly to send an answer there without history. Timestamp and sender are reports supplied by this command, not verified human identity. Seat clear refuses while any records remain; inbox clear refuses while a decision remains open.

### Prepared questions (`ask --deliver paste`)

Use `teerex ask --deliver paste --card-file /absolute/private/card.json` with the same explicit target and sender flags above. This explicit delivery mode requires a `prepared` block on a new card. Existing calls without `--deliver paste`, retained six-field cards and resolutions remain compatible. Delivery still uses native guarded send, with no automatic retry or execution of the no-answer default.

```json
"prepared": {
  "checked": "Reviewed the diff and checked the current owner.",
  "if_no_answer": "Leave the branch in place.",
  "default": null,
  "continuing": "Writing release notes independently.",
  "evidence": ["main@abc1234", "~/work/notes.md#branches"]
}
```

The four required keys are `checked`, `if_no_answer`, `default` and `continuing`; only `evidence` is optional. Text fields use the existing nonblank 1–4096 UTF-8 byte and control rules. `default` is `null` (hold), or an exact option label. Each option optionally accepts a JSON boolean `irreversible`; a default naming an option declared `true` refuses with `silent_default_irreversible`. The declaration is a supplied claim, not a check of the real action's reversibility.

Evidence is a list of 0–16 nonblank single-line references, each at most 1024 UTF-8 bytes, with no C0/DEL controls (including tabs/newlines). Use paths, commits, URLs or record references, never pasted private content. The tool checks this shape; it cannot determine whether a reference contains private material.

Delivered text adds `Checked:`, `If no answer: ... (default: hold|LABEL)`, `Continuing:` and, when nonempty, `Evidence:` after context, before options. Declared irreversible options gain ` [irreversible]`. The inbox uses the same content with upper-case section headings after `CONTEXT`. JSON remains capped at 49152 bytes and rendered delivery at 65536 bytes; native send's existing encoded transport bounds also apply.

Malformed keys refuse with `unexpected_schema_fields`; invalid flags with `invalid_irreversible_flag`; unknown defaults with `unknown_default_option`; invalid evidence with `evidence_must_be_reference`; missing prepared fields in explicit paste mode with `prepared_fields_required`; oversized rendered text with `rendered_card_too_large`. These refusals exit 1 before send and add only the refusal reason, not card content. Usage errors remain 2, deadlines 124 and native delivery uncertainty remains unchanged.

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

### Detailed fleet dashboard (`--detail`)

`teerex boards fleet --detail` retains the evidence dashboard when stdin/stdout are terminals. `--once --detail` text and `--json` keep their existing read-only paths and JSON shape; they do not acquire dashboard-only metadata. No selection or refresh focuses, moves, launches or closes anything.

| Key | Explicit action |
| --- | --- |
| Arrows / `j` / `k` | Select a visible row; preserve the exact target across refreshes |
| Enter | `teerex surfaces focus` for the selected server/session/pane |
| `p` | `teerex jobs present --relocate yes --focus yes` beside this dashboard, with the displayed registration's owner/generation |
| `o` | `teerex surfaces open ... -- leaf open PATH`, tiled beside the selected agent; no focus request |
| `r` | Refresh reads now |
| `/` | Edit a case-insensitive substring filter over row fields; Enter commits, Escape cancels, Backspace edits |
| `q` | Quit; leave all agent and document panes untouched |

The `p` key explicitly permits the native focus transfer needed to relocate a focused source; use Enter when only focus is wanted. The status line shows the explicit action's exit code and native receipt outcome/reason. A timeout/missing receipt stays unknown; actions never retry or reverse automatically. Reads and actions are bounded foreground calls, so keys are processed between them. Ctrl+C/TERM restores terminal settings/cursor before exiting. Long cells/status lines are clipped to the terminal width; the selected row also has a detail line.

Rows show agent name, host, owner, purpose, OSC/lifecycle/report status with provenance, age and last-call time (UTC). Live OSC status is collected even without a jobs registry. The compact status cell uses OSC data first, then lifecycle, then a fleet report; it does not rewrite those records. No recorded status proves completion or process death. Age is the OSC timestamp difference, otherwise time since lifecycle creation/report/registration, not measured work duration. Rex timestamp fractions are padded or truncated to microseconds for Python 3.9 compatibility. Last-call time is the command host's reported clock, not proof of freshness. It matches canonical block IDs within that command host's latest 128 call records (the existing 8 MiB history window); clocks may differ and missing history is unknown.

Use `--jobs-registry ABS` (or repeated `HOST=ABS`) for owner/generation-checked presentation. Add `--agents-registry ABS` (or repeated `HOST=ABS`) for lifecycle names/phases and recorded document paths. Lifecycle reads are command-host-local, owned 0700 directories / single-link 0600 regular files, no final symlinks, read-only existing shared lock, max 32 records / 256 KiB each. Only target/name/owner/purpose/phase/creation time and the first available `last_report_file`, `report_file`, or `brief_file` are projected; tokens, argv and document bodies are never projected. Missing/busy/corrupt lifecycle or call metadata is shown as unknown without replacing live presence. Unobserved lifecycle targets remain visible as absent/unknown claims, never process-death inference. No personal registry is inferred or crawled.

Presentation requires the dashboard and selected pane on the **same server and session**, as required by native jobs. Different-server/session presentation refuses in the status line; use Enter to focus those agents. The dashboard anchor comes from Rex's `REX_SESSION`/`REX_BLOCK` (or SSH `LC_REX_*`) environment, then is verified against live presence. Outside Rex, or when the environment is ambiguous/stale, give `--dashboard-session session:UUID --dashboard-block block:UUID --dashboard-host NAME`. `o` requires a recorded absolute document path and matching observed server/block host; it verifies surface creation, not that Leaf loaded the document. A missing document/registration never creates a fallback pane.

```sh
teerex boards fleet --store "$STORE" --config /absolute/private/hosts.json --hosts hive,m5 \
  --jobs-registry hive=/absolute/hive/jobs --jobs-registry m5=/absolute/mac/jobs \
  --agents-registry hive=/absolute/hive/agents --agents-registry m5=/absolute/mac/agents
```

All remote actions use the existing named-target transport; fixtures can use explicit `--targets-file` endpoints. The additive `boards probe --dashboard [--agents-registry ABS]` supplies only live-view metadata. Existing probe invocations and one-shot fleet JSON stay unchanged. The API13 boards CI suite drives scripted PTY keys against disposable Rex and reads back focus, presentation geometry, pane identity and document creation; it also checks no-action filtering, refusals, token redaction, and terminal restoration on quit/signal. The PTY harness drains redraw output through process exit and compares restored terminal settings, allowing only Darwin's kernel-maintained `PENDIN` input-reprocessing flag.

### Join a jobs registry and terminal reports (source follow-on #22)

Opt in with `--jobs-registry /absolute/private/jobs`. The path is read on each selected **command host**, not on the board renderer's machine. For different paths, repeat `--jobs-registry hive=/home/worker/jobs --jobs-registry m5=/Users/worker/jobs`; names must be selected by `--hosts` (or match the explicit targets-file host). A shared absolute path cannot mix with named paths; repeated host selections refuse. For direct `--targets-file` probes, the command host is the renderer's machine even when a socket is forwarded; registry files are read there. Unspecified hosts keep the original presence/report-only contract. Without this option, one-shot JSON/rendering remain unchanged and do not read terminal status or jobs. The live keyboard dashboard reads OSC status independently.

The routed `boards probe --jobs-registry ABS` invokes the same executable's `jobs list`, reusing jobs' private-directory/file checks, strict schema, duplicate-target validation and **32 entries / 256 KiB** cap. Listing opens existing files read-only, takes a nonblocking shared lock when the lock exists, and creates no lock, state or mirror registry. The directory must already exist. Missing/corrupt/insecure/busy registries produce a visible unknown source and one-shot failure, never an empty-success substitute. Probe requires the current source CLI on the command host; frozen alpha.5 binaries do not implement this option.

The same bounded Rex/Lua probe connection reads each terminal's `program_status`. Enriched rows retain separate fields: `registration` is saved jobs metadata (owner, purpose, kind, generation, review deadline and recorded source identity); `report` is the existing board-store claim; `program_status` contains terminal-reported ID/state/app/effective_app/title/arrival timestamp; `presence` is the live observation (also retained under the compatible `observation` field). No selected state replaces another source. Rendering labels REGISTRATION [jobs], REPORT, PROGRAM_STATUS [terminal report] and PRESENCE [live] separately. Registration alone does not authenticate an agent; report state and program state may disagree.

A registration matches live presence only when session/block IDs, recorded server instance/host and block host match (`registration_matches_presence=true`). An exact-address registration from an older/different source remains separately displayed with `registration_matches_presence=false`; its identity is not silently adopted. Unmatched registrations remain visible; absence is reported only after a complete read of the same server instance/host, otherwise presence is unknown. Absence does not prove process death. Terminal report age is a **board-host wall-clock difference** from the server timestamp, not report freshness or measured task duration; unparseable, missing or future timestamps have null age. Records are capped at **128/terminal**, projected strings at **4096 bytes**, and the combined probe response including registrations retains the **1 MiB** transport limit. Exceeding a cap fails visibly. Max 16 selected hosts and existing sequential/deadline limits still apply; each selected registry read has the existing 5s command bound. No writes, daemon, mirror registry or completion inference is added.

Probe is deliberately **API13 only**; API10/12 reads refuse as unknown, while local inbox/seat storage operations do not require Rex; ask requires native terminal delivery. Max **16 configured names**, **32 sessions/server**, **128 terminals/server**, **1 MiB decoded response/output per transport** and **8192 diagnostic bytes**. A cap refuses visibly rather than truncating the fleet silently. Each resolver/local read has a 5s client deadline; routed host probe 8s, plus bounded owned-child cleanup and OS scheduling. Named servers are sampled sequentially, so refresh period includes their read time. This is not a performance/energy certification.

## Recent invocation calls (#13)

Before dispatch, the combined CLI appends a **start** record in Zig without launching any process or adding a Python dependency to native tools. Native leaves append **end** records at their existing root return/exit points. Existing Python helpers run isolated (`python3 -I`) in their original process and append their own end records. Nothing captures or rewrites stdout/stderr, forwards signals, waits for a command, or changes its PID. A foreign-program exec, fatal signal, an early leaf-owned exit, or a failed append may have no end record: the board shows **unknown**, never an invented success or failure.

The default location is `~/.local/state/teerex/calls`; `TEEREX_CALL_LOG_DIR=/absolute/private/path` selects another command-host directory. The directory is created 0700; lock and log files must be owned single-link regular 0600 files, with final symlinks refused. Writers use one `O_APPEND` write per record and a nonblocking cooperative lock. Logging is best effort and **silent** on failure; it cannot change command bytes or exit status. Each **1 MiB** active `calls.jsonl` rotates to an immutable timestamp/PID segment; history is never deleted automatically. Total retained disk usage grows with calls. This is cooperative history, not a tamper-proof audit boundary. No daemon or supervisory parent exists.

Start records contain wall-clock time, PID, start timestamp, version, allowlisted verb/subverb and flag **names**, and canonical session/block/window IDs. No other argument values, message/card/brief bodies, socket/config paths, parent command, environment, identity claims or error strings are retained. End records contain the same PID/start timestamp key, exit code and elapsed milliseconds. The board pairs by **PID and start timestamp**, so PID reuse cannot attach an old end to a new invocation. A paired exit is labeled completed/nonzero_exit; an unpaired start remains unknown. This does not claim the command's semantic outcome from its exit alone. Duration uses monotonic time within a process, with wall-clock startup offset across an exec.

```sh
teerex boards calls --once --json --limit 32
# Visible foreground board; Ctrl+C stops it.
teerex boards calls --config /absolute/private/hosts.json --hosts hive,m5 --limit 32
# Historical inbox records, newest segment first; bounded output.
teerex inbox inspect --store "$STORE" --host "$HOST_ID" --socket "$SOCKET" \
  --session "$SESSION" --block "$SEAT" --archive --limit 128
```

Numeric options show compact `MIN..MAX` labels in help and reject non-integers or values outside the same inclusive bounds with a short usage error (exit 2).

Calls supports `--once`, `--json`, `--limit 1..128`, `--interval-ms 500..60000`. It pairs the most recent eight segments (at most 8 MiB); history outside that read window remains on disk. Partial append lines are ignored rather than interpreted as an end. Named-host reads use the existing explicit targets transport; unavailable sources stay visible and one-shot partial failure exits 1. Archive inspect supports `--limit 1..1024` (default 128), reads private immutable segments without deleting them, and can include records still active after an interrupted save.

`rex api describe session.view --json` on API13 exposes `creator_name` as the **block type** (e.g. `com.superlogical.terminal`) and `owner` as the **current owning client**. Neither proves which shell command created a block. Bypass attribution is therefore **unknown**, not a false “not via teerex” label. Physical M5 execution and Mac suites are separate acceptance; Linux fixtures do not certify them.

## Private bounded state, inspect, clear, recovery

Store directory: existing, owned by current UID, exact **0700**, final symlink refused. `lock`, `state.json`: owned, single-link regular files, exact **0600**, final symlinks refused. Trusted parents/local filesystem required; no ACL/root/same-account isolation guarantee. The stable advisory `flock` coordinates cooperating local invocations; busy fails immediately. It is not a distributed lock, and crash recovery does not steal/delete lock files.

State schema1: `generation`, `seats:[{target,owner,registered_at,records:[{kind,at,from,body}]}]`, `fleet:[{target,owner,purpose,state,at,detail}]`. Kinds: message (body text), decision (full typed card), resolution (`{id,answer}`). All timestamps are command-host wall-clock Unix ms; negative/future age is labeled unknown. Bounded to **32 seats**, **128 non-open records/seat**, **32 open decisions/seat**, **128 fleet reports**, **1 MiB active encoded state**. Above 128 non-open records, complete resolved pairs and plain messages rotate oldest first until at most 96 remain. Open decisions stay pinned separately and reserve 16 KiB each for resolution. Byte pressure also archives oldest eligible groups across seats. Immutable `archive-GENERATION.json` segments retain every rotated record and exact target, owned 0600 in the store; nothing is automatically deleted. Explicit inbox clear also archives before clearing. Archives are fsynced before active state replacement; an interrupted save can expose the same records in active state and its archive. A conflicting or incomplete archive refuses instead of overwriting it. Archive disk history grows with usage. No terminal output, argv, environment, ACK tokens, or implicit capture is retained; explicit message/decision text itself can still be sensitive.

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

The following dated evidence describes the earlier storage-only ask contract; current `ask` intentionally delivers terminal input.

On **12 November 2026**, **12 tests passed** on disposable Debian/Linux x86_64 and Apple-silicon **macOS26.3.1**, Python3.13.5/Linux and Python3.14.3/Mac, checksum-pinned Rex preview.16/API13 commit aa2db1b21261b479a550559fb70e2c3a66c07ba2. Public contracts cover complete/incomplete cards, resolution and clear, capacity reservation, privacy/links/locking/staged-crash refusal, remap collisions/generations/retained card, exact routing, stdin size/EOF/deadline/signals, named-host partial-error contract fixtures, actual Rex terminal enumeration, unchanged layout, and a real raw terminal that receives **zero input bytes** while its displayed operator draft remains unchanged. The same live test ran an actual visible foreground inbox through empty → pinned decision → reported resolution refreshes. Additional disposable Mac checks passed actual preview.13/API10 and preview.14/API12 fleet refusal-as-unknown while local seat/inbox/ask/render remained functional; this is not API10/12 fleet support. Standalone ABI scratch validation additionally checks targeted parent INT/TERM forwarding and unchanged unregistered stdin (empty, multiline Unicode,65536 bytes). With combined CLI the helper-only check skips unless its bridge is supplied; root send integration tests belong to the integrator.

Actual surfaces-created panes ran the renderer, and Rex terminal HTML captures were inspected in Chromium at72/40 columns for empty/open/resolved inbox and partial-error fleet. These show rendered terminal content and public geometry readback, **not native Rex.app painting certification**. Named m5/hive/m1 transport was contract-fixture tested, not contacted; no personal machine, setup, restart, install, or release was performed. Real named-host SSH/root dispatch, merged CLI/packaging, authoritative legacy-log import, automatic login-seat setup, actual private-host support, and a published alpha.5 release are not certified by this leaf. See [migration gates](MIGRATION.md) before deleting stopgaps.

## Default socket for probe

Combined `teerex boards probe` may omit `--socket`: the root resolves `REX_SERVER` or the platform socket in process and exports `TEEREX_SOCKET_SOURCE`. Its JSON then includes `socket_source` (`REX_SERVER` or `platform_default`). Explicit-socket packets are unchanged. Offline store commands and terminal board renderers receive no injected socket or output wrapper; PID, stdin and stdout TTY stay with the foreground command.


## Friction (opt-in)

`teerex boards friction` adds a local sidecar to the ordinary invocation log.
It installs no service, shell hook, schedule or automation. Python 3.9+ stdlib
runs in the existing process with `-I`; native collection also works without Python.
Every command requires `--log-dir ABS`, an existing, owned directory with mode
0700. Files must be owned regular files at 0600, with no symlink or hardlink.
The hook uses the #13 lock and never changes the invoked command's output or exit.

- `enable --for-days N --scope all|callers:a,b [--by NAME]` grants 1–30 days;
  active consent refuses `consent_exists`. Disable before changing consent.
- `disable` removes consent and reports `was_enabled`; repeated disable succeeds.
- `status` reports enabled/expired, expiry, scope, sidecar counts, time range,
  salt presence and labels. It never displays the salt.
- `label --path ABS --name NAME` labels the canonical directory key under active
  consent. Names and callers match `[a-z0-9][a-z0-9._-]{0,63}`.
- `forget (--all|--before TS|--caller NAME) [--yes]` previews by default;
  `--yes` atomically rewrites retained lines with fsync and rename. `--all`
  also deletes the salt and labels. Disable and enable to resume with a fresh salt.
  Invocation history is retained under its own policy.
- `report [--since TS] [--min-episodes K] [--gap-s S] [--json]` reads only;
  defaults K=3, S=300. Times use Unix milliseconds; CLI filters also accept
  timezone-qualified ISO8601. Named-host routing runs the report on that host.

Consent lives in `friction-consent.json`, with 32 random bytes in `friction-salt`.
Shapes rotate at 4 MiB once into `friction.jsonl.1` (8 MiB maximum).
Missing, malformed, expired or out-of-scope consent collects nothing. A collection
write failure marks the ordinary start line `friction_write: failed` when possible;
when its shared lock or history cannot be written, logging stays silent.

A shape contains allowlisted, sorted flag **names**, counts, pipe/file stdin
presence, validated caller/agent names, version and host. It contains no argv,
flag values, message, brief, stdin contents, parent command line or file contents.
Directory and nearest `.git` ancestor (stat only) use HMAC-SHA256 keys truncated
to 16 hex digits. Explicit/default direct sockets use the same endpoint selection
as dispatch, including percent-decoded `REX_SERVER`. Named-host configuration is
resolved after the native start hook. The ordinary resolver supplies its validated
endpoint to the same in-process hook, which atomically completes the existing
shape under the shared lock. SSH endpoint keys include address and port as well
as socket path, so identical remote paths cannot pool across machines. Failed or
unfinished resolution leaves `target_unknown: true`; reports count those as
`unresolved_context` and exclude them from runs. No telemetry-only config read
or additional process is introduced.
Offline commands have a null server key. Salt deletion breaks links across windows.

An OS-random `call_id` joins shapes to the existing #13 start/end records and
survives native `--rex` and embedded helper exec without an extra process. #13
uses `at`, `start_at`, `phase`, `exit` and `elapsed_ms`; it currently supplies no
backend refusal reason. Exit 0 means ok, 2 means usage; unexplained nonzero or a
missing end stays uncertain. A defect needs an explicit refusal outcome and reason.

Reports split hashed agent/pane episodes after the configured gap. They count
contiguous 2–6-step sequences once per distinct episode and context (host,
repo-or-directory, server, version). Equal-support subruns disappear. Sequences
that reach the threshold only across contexts appear as `similar_not_same`.
A single-step **explicit refusal** may also appear as a defect summary; singleton
successes never become verb candidates. Retry after an uncertain mutation and
operator authority steps produce `refuse_automation`, without suggestion text.
Known issue mappings precede general verb candidates. Labels are user supplied.
Savings are inferred inter-step gaps, never measured benefit. Reports generate
no scripts and execute no suggestions.

Read-only report/forget preview leave the selected data unchanged. As with every
teerex command, their own invocation is still logged if the hook's active log
is that same directory; use a separate `TEEREX_CALL_LOG_DIR` for a byte-stable
inspection. Consent is checked at invocation start, so disable/forget may record
one final shape before applying their operation.

Acceptance: `python3 items/boards/test_friction.py -v` uses only private temporary
logs and synthetic joined episodes. CI runs it on both Linux and macOS lanes.


`ask` terminal delivery uses the send status options: a seat-labelled target gets `ask/<card id>` in blocked/question state with the question line; `--resolve` clears that same child record. Delivery receipts retain `status_record`. Status is best effort and does not replace the decision history or delivery acknowledgement.

## Compact fleet view

`boards fleet` shows live, unfinished panes ordered by waiting on you, error,
working, then idle. It reads each pane's optional Markdown scratchpad from
`~/.local/state/teerex/scratch/<session-id>/<block-id>.md` on the probed host.
Current work wraps in full at 60 columns; progress counts Done out of Now,
To-do and Done. Waiting rows show the latest open decision from that agent,
falling back to its blocked terminal status title. Ages use seconds, minutes,
hours or days since the scratchpad update or terminal status change.

Enter jumps with `surfaces focus`; Space toggles the selected scratchpad inline;
`a` toggles all history; `i` toggles full evidence; arrows/j/k select; `q` quits.
New waiting rows flash once. The installed Rex API13 exposes no activity badge
method, so this view does not set a badge. Unavailable hosts are retained in JSON.

`--detail` retains the previous evidence table and its filtering, presentation
and document actions. `--once` uses the compact view; `--once --detail` gives the
previous text snapshot. `--once --json` retains its existing schema and rows.
Scratchpads are optional and bounded to 64 KiB; missing or unreadable files leave
current work and progress blank. No scratchpad writes are performed by the board.
