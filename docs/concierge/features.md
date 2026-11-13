# Current feature field guide: Who / What / When / Where / Why / How

**Use verified v0.1.0-alpha.5 for current installation.** Start with [setup](setup.md) for inspect-first installation or upgrade, checksums, retained rollback and the non-restarting read-only smoke. The [alpha.5 release and setup handoff](../releases/v0.1.0-alpha.5.md#quick-changelog-and-current-setup-handoff) and [support matrix](setup.md#supported-platforms-and-api-boundaries) define current delivery. These source-documentation corrections do not replace the README/onboarding already frozen in published archives.

**Separate unreleased source:** [`run-visible`](../../items/run/VISIBLE.md) has a complete Who/What/When/Where/Why/How contract for noninteractive visible argv/cwd/env/stdin, raw output, actual exit/signal and owned-pane lifetime on Mac/Linux API13. It preserves section5's Mac-local legacy `run`, is absent from published alpha.5, and requires the [explicit source-only build route](setup.md#source-only-follow-ons-are-not-an-alpha5-upgrade). The [Rivet opt-in patch and remaining cutover gates](../../items/run/MIGRATION.md) do not authorize applying it or deleting its fallback/guards. Further source adds [explicit unfenced compute callbacks and independent local scoped delivery](../../items/agents/README.md#source-only-compute-routing-and-scoped-delivery-issues14-and21) (#14/#21) and [nested selector routing](../alpha5.md#leaf-aware-named-host-routing-issue16) (#16). Remote compute plus scoped channel refuses before creation; Linux SSH/fence evidence is not Mac fence or physical-host certification. Real Rivet/paid-harness integration and relay cutover remain gated, with wrappers and guards retained. None is in frozen alpha.5.

Sections 1–11 retain the useful alpha.3-origin recipes, with current support corrections; they are not a recommendation to install alpha.3. The [five alpha.4-origin follow-ons](follow-ons.md) also ship in alpha.5. Sections 12–17 route to the alpha.5 operating-layer guides. The combined CLI has one shared binary lifecycle; the separate [cartridge manager](../cartridges.md) provides ten Mac/seven Linux independently removable experimental payloads, not independent surfaces/boards/agents/recovery packages. Stop invoking a command to end its foreground controller; removing code never undoes input, program side effects, retained private state or worker lifetimes. No automatic capture history, telemetry or background service is installed.

## Recipe inputs and common checks

`TEEREX` is the absolute installed binary. The local operator supplies private `SOCKET` (absolute), `SESSION`, `BLOCK` (canonical lowercase full `session:UUID` / `block:UUID`) and any parent/worker addresses. `CHECK_DIR` is a private directory created with `umask 077; CHECK_DIR=$(mktemp -d)`. File examples require independently reviewed existing files, not guessed paths. `WORKSPACE` is an authorized absolute directory on the appropriate execution host. Do not put real endpoint values or captures in public documentation. A trusted separate `rex` is on PATH for direct live commands, or selected by combined-root `--rex ABS`; none autostarts the server. Named-host configuration pins the command-host executable/socket explicitly. Selection is not authentication.

Each command requires its own scope. A prior read, successful diagnosis, status report or saved match does not authorize input/execution. Check exit status **and complete structured output**; redirection can create a file even when a command fails. Native spawn/send diagnostics use `failure_reason`, not an assumed `error` field. Missing source/attempt/ACK frames do not prove no remote effect; `backend_error` is not retry-safe. Core installation and cartridge-manager execution are different launch paths: a held manager lock reports a lifecycle error on stderr, not a native spawn/send receipt, and is not an established cause of issue #12. Usage is normally exit2; operational errors can exit1 without complete JSON. See [troubleshooting](setup.md#troubleshooting-and-safe-next-actions) for source/target mismatch, unknown evidence and lost mutation ACKs.

## 1. Source-tree shared installer

- **Who:** the account owner/local setup agent, not root or sudo.
- **What:** verified version directories and one explicit `current` link. It does not install Rex, add PATH entries or create independent cartridges.
- **When:** after selecting/reviewing an exact published tag; use upgrade for an existing active installation, never `latest`.
- **Where:** default `$HOME/.local/opt/teerex`, user-owned under HOME, Darwin arm64/Linux x86_64. Custom `--prefix` must be repeated on every lifecycle command.
- **Why:** stage and validate before activation, retain prior bytes, avoid overwriting user files.
- **How:** follow [the complete install/verify/upgrade/rollback/remove procedure](setup.md). `bash tools/install/teerex-install --help` and `list` identify the selected operation/root. Success checks HTTPS/checksum, three regular archive members, host architecture and help, not live Rex behavior. No Zig required. [Contract and dependencies](../install.md).

Verification: invoke `current/teerex --help`, check exact release hash and installed active tag; optional authorized live smoke is separate. On download/integrity/tool/root refusal preserve the active version and investigate, not bypass validation. Installation and remove do not touch shell/Rex/agent configuration. Uninstall removes verified code only, not captures or running workers. Mac security denials are not permission to remove quarantine.

## 2. `observe`: bounded attributed evidence

- **Who:** a human/agent explicitly allowed to read one terminal.
- **What:** bounded screen-and-scrollback **prefix**, process/foreground/cwd, last-reported directory and status evidence with source/provenance/unknowns; not a latest-viewport or atomic snapshot.
- **When:** inspect a chosen target or deliberately create a baseline, not to infer task completion or input safety.
- **Where:** Mac/Linux CLI, existing Rex integer API10–13. Forwarded Unix sockets do not prove physical host identity.
- **Why:** preserve what Rex actually returned rather than guessing from focus, silence or a status label.
- **How:** after read/storage authorization:

```sh
"$TEEREX" observe --socket "$SOCKET" --session "$SESSION" --block "$BLOCK" \
  --max-bytes 600 --timeout-ms 5000 > "$CHECK_DIR/observation.json"
```

Expected exit0 / schema1 observation with exact target/source, `atomic_snapshot=false`, bounded `capture` and attributed `process`, `reported_directory`, `program_status`. Check actual API matches the independently queried server and preserve null/unknown evidence. Default capture4096, range256–65536 **JSON-encoded content bytes including quotes**; whole packet/metadata can be larger. Collection deadline default5000ms,100–60000 plus bounded cleanup. Missing consumed bindings, failed RPC or invalid evidence is failure, not empty success. Exits124/130/143 mean deadline/cancellation, no successful interrupted sample. Captures may omit the latest prompt and contain secrets; storage/export must be deliberate.

Update/rollback: shared binary only; preserve existing evidence without relabeling its source. Remove: stop invoking and deliberately remove only selected private capture files if desired. [Detailed observation contract](../../items/observe/README.md). Numeric API acceptance is not certification of attached mixed-host topology; [issue #10 remains unresolved](../../items/observe/README.md#target-routing-diagnostics).

## 3. `compare`: offline evidence differences

- **Who:** a human/agent authorized to read the two saved packets.
- **What:** caller-ordered changes/availability/unknowns, not a timeline, patch or activity classifier.
- **When:** both files are complete successful observations with matching exact target and Rex version/platform/API.
- **Where:** offline Mac/Linux; schema1/API10–13, at most1MiB per file. No Rex or live socket connection needed.
- **Why:** make missing/partial evidence distinguishable from known equality.
- **How:** self-comparison is a useful non-destructive installation control:

```sh
"$TEEREX" compare --before "$CHECK_DIR/observation.json" \
  --after "$CHECK_DIR/observation.json" > "$CHECK_DIR/comparison.json"
```

Expected exit0 / `kind=observation_changes`, `interpretation=none`. Self-comparison has no known changes; incomplete capture still has `full_text_changed=null`. For real deltas select two distinct approved files. `before`/`after` names and clocks do not prove chronology; equal prefixes cannot prove unchanged full text. Source/target/provenance/schema mismatch returns failure; do not edit evidence labels to force acceptance. Original files are not modified; output omits raw capture/cwd/report values but still contains private identifiers. No automatic receipt is saved except your chosen redirection.

Update/rollback/remove: shared code lifecycle; retain original files if byte preservation matters and remove only selected private outputs. [Comparison contract](../../items/observe/README.md#what-c03-adds-and-teaches).

## 4. `watch`: bounded foreground evidence wait

- **Who:** an authorized reader, not a background-monitor owner by implication.
- **What:** one foreground wait against the **original** explicit saved baseline, using one supervised connection and serial reads; no daemon or subscription.
- **When:** wait for evidence/availability change or differing selected status evidence, not program completion.
- **Where:** Mac/Linux, integer API10–13, same exact target/source as baseline; baseline ≤1MiB.
- **Why:** avoid repeated client launches and make quiet/unknown/deadline distinct.
- **How:** after a successful baseline observation:

```sh
"$TEEREX" watch --socket "$SOCKET" --session "$SESSION" --block "$BLOCK" \
  --baseline "$CHECK_DIR/observation.json" --timeout-ms 1000 --interval-ms 250
```

Required deadline100–60000ms; interval50–5000ms **after** each collection. Expected `kind=observation_wait`: exit0/`change_observed`,124/`deadline_exceeded`,1/`observation_failed`,130/143 cancellation. All are outcomes, not task-completion verdicts. Inspect `last_comparison`, unknown/availability fields, interrupted/late markers and source. No accepted comparison is current evidence after a later failed sample.

For a separately chosen status condition append `--status-state done`; without `--status-id` that selects the null-ID root. Literal `--status-id root` is a **named child**, not root. Exit0/`status_report_matched` requires different matching evidence versus baseline; an identical retained `done` report does not wake it. A new report may still be stale, a process may still run, and blocked/permission grants nothing. Cleanup stops only its collector group, never the observed terminal/server; total wall time can exceed collection budget.

Update/rollback/remove: end your own foreground wait before changing binary; no watcher/config to uninstall. No automatic observations/history are saved. [Wait and selected-status contract](../../items/observe/README.md#what-c09s-bounded-observation-wait-adds-and-teaches).

## 5. `run`: local argv and actual exit evidence

- **Who:** an operator/agent separately authorized to execute the exact argv with the CLI account's authority.
- **What:** local noninteractive argv/cwd, immediate EOF stdin, bounded raw stdout/stderr and actual direct-child exit/deadline/cancellation evidence. Never an agent launcher.
- **When:** a deliberate bounded local program is appropriate, not typing into an existing pane or executing remotely.
- **Where:** **Mac CLI host only**, integer API10–13 and consumed exec bindings. A selected/forwarded socket does not change execution host. Linux refuses before launching Rex.
- **Why:** use actual argv/exit evidence rather than screen or status heuristics.
- **How:** this Mac smoke requires execution authorization and an absolute trusted workspace, run from the designated disposable visible execution pane:

```sh
"$TEEREX" run --socket "$SOCKET" --cwd "$WORKSPACE" \
  --timeout-ms 1000 --max-bytes 128 -- /usr/bin/printf '%s\n' teerex-smoke
```

Expected exit0 / `kind=run_result`, `success=true`, actual `exit_report.code=0`, stdout content `teerex-smoke\n` with UTF-8 encoding, no task-completion claim. A program failure returns controller1 but preserves the program's real code in JSON. Output can instead be base64; combined retention is1–65536 **raw bytes**, default4096. Timeout default10000ms,100–60000; outer deadline adds5000ms. Deadline124 and signal130/143 preserve partial/unknown evidence, not success.

No implicit shell, stdin/TTY interaction or sandbox: argv can change files, credentials/network are inherited, process listings/diagnostics may expose argv. Owned-process-group cleanup is not whole-tree termination; detached descendants and SIGKILL/crash escape it. Do not use run for agents/workers/sidecars or arbitrary fire-and-forget work.

Update/rollback/remove: finish your own invocation before changing binary. It has no hook/history; program-created files/processes need their own authorized cleanup. [Execution contract](../../items/run/README.md). API11 and every build in the accepted range are not certified.

## 6. `doctor`: narrow advertised compatibility and drift

- **Who:** an operator allowed to query the selected server's version/descriptors, not a new permission authority.
- **What:** independent CLI/server identities, selected observe/watch/run advertised shapes and Lua binding types; optional prior-identity comparison.
- **When:** diagnose advertised requirements or conservatively detect identity drift, before separately scoped behavior validation.
- **Where:** runtime Mac-only, integer API10–13 with overlapping support. No terminal reads, argv execution, server autostart or repair.
- **Why:** distinguish advertised shape from tested behavior and CLI from server.
- **How:**

```sh
"$TEEREX" doctor --socket "$SOCKET" --timeout-ms 5000 > "$CHECK_DIR/doctor.json"
# Later, only with an actual successful prior receipt:
"$TEEREX" doctor --socket "$SOCKET" --baseline "$CHECK_DIR/doctor.json"
```

Expected schema1/`kind=rex_compatibility_doctor`. Exit0 means advertised requirements met and no supplied baseline drift, **always `behavior_certified=false`**. Inspect per-operation checks; spawn/send/offstage are not covered. Exit1 includes drift/unknown/incompatible;124 deadline;130/143 cancellation. Prior receipt ≤128KiB; default budget5000ms,100–60000. Descriptor/identity hashes are neither signatures nor instance/authentication/permission tokens. A same-identity restart can be indistinguishable.

On drift, review changed identity and rerun relevant scoped tests before deliberately adopting new evidence; do not overwrite the old receipt to make a pass. No automatic remediation. Update/rollback/remove: shared binary lifecycle, stop invoking; only chosen private diagnostic files need retention/deletion. [Doctor contract](../../items/doctor/README.md).

## 7. `spawn`: one visible agent terminal

- **Who:** an operator/local setup agent authorized for the exact agent argv, workspace, destination session and existing visible report-to terminal.
- **What:** low-level argv-only spawn creates one window-attached terminal with agent-core AGENT/LC address/name/report-to metadata; requests no focus switch and verifies acknowledged attachment. For alpha.5's managed ACK-before-brief/jobs path, use [section 15](#15-managed-agents-profiles-protocol-and-responsibility).
- **When:** deliberately launch a visible worker, not a hidden fallback or automatic migration.
- **Where:** Mac/Linux, integer API10–13. Cwd/program live on the **terminal creator's host**, not necessarily CLI host; report-to can be a different session on the same selected server.
- **Why:** retain visible work and exact parent routing rather than guessing active panes.
- **How:** `AGENT_BIN` must be the approved absolute executable and `WORKSPACE` the approved terminal-host cwd; replace/add only its reviewed arguments after `--`:

```sh
"$TEEREX" spawn --socket "$SOCKET" --session "$SESSION" --name worker \
  --cwd "$WORKSPACE" --report-to-session "$PARENT_SESSION" \
  --report-to-block "$PARENT_BLOCK" --timeout-ms 5000 -- "$AGENT_BIN"
```

Expected exit0/`kind=spawn_result`, `outcome=created_and_attached`, full created window/block IDs and verified location. Inspect the **new owned** terminal separately for startup/readiness; these remain `not_assessed`. Confirm parent/name metadata through the authorized agent's own startup report if needed. Exported LC values do not configure SSH forwarding, agent-core, Rivet or guards. Empty sessions may activate the first window despite `focus=false`; it is not a global focus lock.

Default transport budget5000ms,100–60000; encoded args≤48000 bytes and Rex request≤60000. Bad cwd does not execute argv in a fallback directory; the created terminal is retained. Exit1/`uncertain`, lost ACK, deadline124 or cancellation130/143 may leave a worker. **Do not retry or close automatically.** Inspect only the selected session/known IDs, preserving visible failure evidence. No input lease/sandbox/readiness certification is supplied.

Update/rollback/remove: changing teerex does not stop workers. Finish/close only individually owned terminals with explicit authority; no automatic teardown, restore or migration. [Spawn contract](../../items/spawn/README.md).

## 8. `send`: one whole-message paste, then Enter

- **Who:** an operator/agent explicitly authorized to type into a dedicated agent terminal, not any observed pane.
- **What:** exact `FROM worker: <file bytes>` paste then Enter on one connection; separate attempts/ACKs.
- **When:** a reviewed private UTF-8 message is intended for that exact agent and preexisting drafts/prompt context have been considered locally.
- **Where:** Mac/Linux integer API10–13, existing visible terminal, absolute regular message file or alpha.5's bounded EOF-terminated `--message-file -` stdin. Cooperating locks are CLI-host/TMPDIR-local, not shared across forwarded hosts. Explicit `--store` and leaf `--host` enable exact registered-seat inbox append before native paste; store failures never fall back. [Seat routing contract](../../items/boards/README.md#append-without-typing-route-send-fail-closed).
- **Why:** avoid shell joining, truncation, guessed draft clearing and unsafe retries while preserving transport evidence.
- **How:** after creating/reviewing the private regular file at `MESSAGE_FILE`, and obtaining the dedicated `AGENT_BLOCK` and `AGENT_SESSION`:

```sh
"$TEEREX" send --socket "$SOCKET" --session "$AGENT_SESSION" --block "$AGENT_BLOCK" \
  --from worker --message-file "$MESSAGE_FILE" --timeout-ms 10000
```

Expected exit0/`kind=send_result`, `outcome=events_acknowledged`, both paste/Enter ACKs. This is **not delivered/consumed/safe/complete**. Verify application response only through separately authorized inspection; never infer it from ACKs. File1–65536 UTF-8 bytes; LF/tab allowed, CR/ESC/NUL/other controls/DEL refused. Encoded argument/RPC caps can reject smaller raw files; no truncation/chunking. Local inbox markers refuse rather than forwarding.

No draft clearing/detection/restoration, fallback or resend. Existing pending input may be submitted together; newlines can execute input in recipients without bracketed-paste handling. A same-host mkdir lock coordinates cooperating senders only; humans/direct clients bypass it. Native ownership is not an exclusive lease. Paste ACK plus missing Enter, timeout124, signals130/143 or missing receipt leaves uncertain effects. Never blindly resend. Stale locks require checking that sender is gone and inspecting possible prior input before deliberate removal.

Default budget10000ms,100–60000 including lock wait. Messages may appear in process listings/diagnostics even though receipt omits them. Update/rollback/remove: no unsend/retraction; stopping/removing CLI does not invalidate queued input. Delete only the selected private message/receipts with approval. [Send contract](../../items/send/README.md).

## 9. `offstage`: invocation-owned command terminal, not an agent

- **Who:** an operator authorized for one short non-agent command on a known local disposable Mac target.
- **What:** create a detached terminal, collect actual terminal-program exit and bounded screen/scrollback prefix, close only the acknowledged created block and verify absence.
- **When:** off-layout command lifecycle serves an explicitly approved workflow; never launch hidden agents/sidecars or unattended services.
- **Where:** known local Apple-silicon Mac **server/API13 only**. Not supported on the current API10 M5 server. Unlike run, argv runs on the selected terminal creator's host.
- **Why:** keep a bounded owned command off the layout without claiming isolation or whole-tree cleanup.
- **How:** only on a separately authorized suitable target, from the designated execution surface:

```sh
"$TEEREX" offstage --socket "$SOCKET" --session "$SESSION" --cwd "$WORKSPACE" \
  --purpose 'authorized disposable printf smoke' --timeout-ms 1000 --max-bytes 600 \
  -- /usr/bin/printf '%s\n' teerex-smoke
```

Expected NDJSON `offstage_started` **then** `offstage_result`; exit0 requires real reported code0 **and** matched cleanup identity/verified block absence. Parse all records and check capture/cleanup. A started record alone is not success. No other pane/window/focus is changed. PTY output merges streams and terminal formatting differs from raw run output; capture is not atomic final drain/latest viewport. Timeout/cancel returns null capture rather than inventing final output.

Deadline100–60000ms required; capture256–65536 JSON-encoded bytes, default4096; cleanup can add up to5500ms plus scheduling/output. Exit1 includes unknown cleanup/nonzero program;124 deadline;130/143 cancellation. Lost creation ACK may leave a block with no known ID; do not retry/adopt/close by a guessed label. SIGKILL/crash can leave the terminal; closing a block does **not** verify descendant termination. Offstage has no sandbox, daemon or durable registry of its own; separate `jobs` records do not inherit this invocation's cleanup authority.

Update/rollback/remove: stop your own foreground command cleanly first, inspect its exact cleanup evidence; binaries do not clean orphan processes/resources. Escalate uncertain resources for separately authorized inspection, not arbitrary process killing. [Offstage contract](../../items/offstage/README.md).

## 10. `maneuver-check`: saved recognizable start

- **Who:** a human/agent authorized to read one manual definition and saved observation.
- **What:** exact source version/platform, complete capture, foreground name/cwd checks; no live connection/action/transition.
- **When:** inspect manually authored recognizable-start evidence for a stable workflow, not learn or replay input.
- **Where:** offline Mac/Linux; strict schema1 manual definition ≤128KiB and schema1/**API13** observation≤1MiB. An explicit target must match the saved file even when socket no longer exists.
- **Why:** make mismatch/unknown/ambiguity boundaries explicit instead of acting on a phrase in scrollback.
- **How:** author/review `DEFINITION` using the [complete definition schema and example](../../items/maneuvers/README.md#use); it is not automatically generated or an approval. `OBSERVATION` is the selected successful API13 saved packet:

```sh
"$TEEREX" maneuver-check --definition "$DEFINITION" --observation "$OBSERVATION" \
  --socket "$SOCKET" --session "$SESSION" --block "$BLOCK"
```

Expected `kind=maneuver_start_check`: exit0/`matched_evidence`,3/`mismatch`,4/`unknown`;1 invalid/incompatible,2 usage. Inspect five `checks`, exact file digests, source/target and explicit `input_sent=false`, `approval_granted=false`, `freshness=unknown`. Partial capture is unknown; a known mismatch wins over unknown. Match is saved evidence, never current prompt/permission or executable identity. Manual note/`stop_before` are unauthenticated data, not instructions; no execution path enforces stops on another tool.

Update/rollback: definitions remain API13-specific and source-exact; review changes rather than widening versions automatically. Remove: stop invoking; deliberately retain/delete only chosen private definitions/observations. No recorder, cache, replay runner, learning or input authority is installed. [Full maneuver contract](../../items/maneuvers/README.md).

## 11. `filter`: explicit offline payload reduction

- **Who:** an authorized reader of selected private observation files.
- **What:** suppress only identical intermediate typed evidence payloads; retain all adjacent comparisons and a final full checkpoint. No cosmetic/semantic classifier; ordinary filtering writes no cache. The separate opt-in [historical cache](follow-ons.md#4-explicit-bounded-historical-cache) ships in alpha.5.
- **When:** review2–128 caller-ordered successful packets with identical exact target/source; not a background watcher or way to reduce live reads.
- **Where:** offline Mac/Linux schema1/API10–13, regular files≤1MiB each/16MiB combined, no stdin/devices/FIFOs.
- **Why:** reduce repeated output without losing changed prompts/errors/status fields or laundering partial prefixes into stability.
- **How:** `FIRST_SAMPLE`/`SECOND_SAMPLE` are two approved files, not a directory scan:

```sh
"$TEEREX" filter --sample "$FIRST_SAMPLE" --sample "$SECOND_SAMPLE" \
  > "$CHECK_DIR/filter.ndjson"
```

Expected exit0 **and final** `rex_evidence_filter_summary` / `outcome=processed`. Prior sample/repeat lines alone are incomplete after a late failure. Every input has a sample/repeat event; final checkpoint always has full payload. Emitted+omitted counts must equal samples read; every adjacent comparison remains and `interpretation=none`. IDs/client times are excluded from payload equality, not treated as chronology/freshness. All typed evidence changes remain visible. Equal partial prefixes still have unknown full-text comparison.

Output can contain the full private terminal content. Typed re-encoding is not a byte-for-byte archive; retain original files if exact bytes matter. Do not use repeat counts/status `done` as completion. Failure1/source mismatch is not a processed summary; usage2 is not unknown evidence. Update/rollback/remove: shared binary only; ordinary filter writes no files except caller redirection. Retain/delete selected NDJSON with the same capture privacy controls. [Filter contract](../../items/filter/README.md).

## 12. Named command hosts and executable selection

- **Who:** an operator/agent authorized for the selected configured account and operation.
- **What:** `targets resolve` validates one configured command host; root `--config/--host` executes there with explicit Rex/socket selection. `--rex ABS` pins a local executable, not its authenticity.
- **When:** choose a command host deliberately before a feature invocation; never guess from focus or fall back after a failed route.
- **Where:** Mac/Linux with Python3.9+; SSH also needs a reviewed key and pinned known-hosts file. Paths in a dispatched command belong to that command host, not the caller.
- **Why:** separate declared host selection, actual server evidence and attached block-host identity.
- **How:** inspect configuration without contacting Rex/SSH:

```sh
"$TEEREX" targets resolve --config "$TARGETS" --host "$HOST_NAME"
```

`TARGETS` is the absolute reviewed private host-config file; `HOST_NAME` is an exact configured key. Expect exit0 and bounded schema1 JSON containing `host` and `identity_basis`; failure1/usage2 is not a selected host. Resolution selects **command-host names**, not resource labels or UUID suffixes from issue #2. Dispatch additionally emits a selection receipt on stderr, not proof that leaf work succeeded. Unknown names refuse before network; no silent file upload or implicit host defaults. [Complete configuration, transport and limits](../alpha5.md#current-source-contract).

Update/rollback/remove: review explicit config/binary changes; removing teerex does not remove config, keys or trust files. Preserve those privately until deliberately retired. Named-host success does not resolve issue #10 or intermittent issue #12.

## 13. Visible surfaces and native palette

- **Who:** an operator/agent separately authorized to create, move, focus, close a pane or change the selected Rex config.
- **What:** `surfaces open/inspect/move/focus/close` and `palette` prepare/install; attached tiled/float/tab programs with requested versus measured geometry.
- **When:** place a visible tool or inspect a known pane; config registration requires its own reviewed plan/apply.
- **Where:** Mac arm64 API10/12/13 and Linux x86_64/API13 tested; numeric API10–13 acceptance is not every-build certification. Palette install also needs Python3.9+.
- **Why:** one explicit placement with no fallback/retry, not an invented graphical plugin API.
- **How:** inspect the exact owned/authorized pane first:

```sh
"$TEEREX" surfaces inspect --socket "$SOCKET" --session "$SESSION" --pane "$BLOCK"
```

Require exit0, complete JSON and actual geometry/identity readback. Use [complete layout, palette plan/apply and exit recipes](../../items/surfaces/README.md#how) for mutation. Native readback is not Rex.app pixel/palette-click acceptance. Open requests no focus, but a first window can activate; moving a focused source requires explicit focus consent. Lost ACK can leave effects: inspect exact known IDs, never recreate/close automatically. Close proves block absence, not descendant death.

Update/rollback/remove: shared code lifecycle; prepared fragments, appended includes and running panes survive code removal. Review the [migration/config retention gates](../../items/surfaces/MIGRATION.md) before deliberate config cleanup; never reload/restart or delete unrelated actions as an installation side effect.

## 14. Boards, seat, inbox and typed decisions

- **Who:** authorized operators and reporters; sender/owner labels and recorded answers are claims, not authenticated consent.
- **What:** visible foreground inbox/fleet boards, exact tuple seat registration, retained messages, complete decision cards/resolutions and explicit state inspection/remap.
- **When:** register a seat before routing messages; inspect retained cards before clearing. Boards refresh only while deliberately running visibly.
- **Where:** Mac/Linux, Python3.9+, explicit existing0700 private store. Local seat/inbox/ask operations are offline; live fleet/probe requires API13. API10/12 probe refusal remains visible unknown.
- **Why:** append to a registered seat's inbox instead of typing over operator input; keep reported activity separate from observations/unknowns.
- **How:** inspect local state without sending input:

```sh
"$TEEREX" boards state inspect --store "$STORE"
```

Expect exit0/schema1 complete state receipt, not liveness. `STORE` is the reviewed command-host-local board directory. [Full registration, visible board, typed-card, routing and clear/remap recipes](../../items/boards/README.md) include default2s foreground refresh, TTY/`--once` rules,32 seats/128 records per seat/1MiB store bounds, exits and crash recovery. Every failed named host stays visible; one-shot partial fleet failure exits1. No automatic decision execution or reply, log import, eviction, hidden watcher or draft clearing. Store errors refuse, never fall back to paste.

Update/rollback/remove: private state and messages survive binary changes; older releases may not read them. Export/review privately before exact generation/reason-confirmed clears. Clearing registration/reporting never closes panes or stops work; preserve working stopgaps until [paired source-cutover gates](../../items/boards/MIGRATION.md) pass.

## 15. Managed agents: profiles, protocol and responsibility

- **Who:** the operator/authorized starter for one reviewed profile, target, starter and report-to tuple.
- **What:** `spawn --profile/--profiles` or `agents launch` creates a visible supervisor, tracks jobs, supplies protocol-only initial prompt argv, waits for exact token/pane ACK, then attempts one brief.
- **When:** use instead of low-level spawn for managed protocol/responsibility; inspect late/uncertain launches instead of retrying.
- **Where:** Mac/Linux/API13, Python3.9+, exact command-host-local private registry and paths accessible to the pane host. Actual paid Claude/Codex/pi hooks, generic resume and arbitrary cross-host replies are not certified.
- **Why:** attachment is not readiness; explicit cooperative ACK avoids a guessed startup delay without claiming authentication or safe input.
- **How:** inspect reviewed profiles first:

```sh
"$TEEREX" agents profiles --config "$PROFILES"
```

`PROFILES` is the absolute private reviewed profile file. Require exit0/full JSON; profile inspection does not launch. [Full launch, ACK/deliver, reports, present and lifecycle recipes](../../items/agents/README.md) specify32 launch records/256KiB files, bounded messages, ACK100–60000ms/default10000, refusal1/usage2/ACK timeout124/cancellation130/143. `brief_submitted` means paste/Enter ACKs, not consumption. Stop hooks report idle/error; immediate-child exit is not whole-tree death. Supervisor loss can leave alerts unknown. Generated shell functions are opt-in and preserve existing functions by skipping, not saved-function call-through.

Update/rollback/remove: code changes do not stop agents, expire tokens or remove jobs/private records. Finish only separately authorized owned work, inspect exact receipts and preserve unresolved state; no automatic pane close or retry. Real harness/guard/caller parity and [agent-core migration](../../items/agents/agent-core-migration.md) remain incomplete.

## 16. Structural recovery and manual Rex update inventory

- **Who:** an authorized operator preserving one selected server's structure before a separately approved restart, then reviewing a restore.
- **What:** `recovery snapshot/inspect/restore/update` (root aliases also exist), per-field omissions and exact old/new maps; update itself is read-only.
- **When:** inventory first; snapshot before an authorized restart; restore previews against an empty selected target and applies once only with exact confirmation.
- **Where:** Mac/Linux/Python3.9+; snapshot/restore API13 and same observed server host, update inventory numeric API10–13. Foreign-host execution, authoritative drafts and generic harness resume are unsupported.
- **Why:** preserve what can actually be reconstructed without inventing argv, replaying secrets, resuming ungated agents or overwriting live sessions.
- **How:** inventory without updating or restarting:

```sh
"$TEEREX" recovery update --socket "$SOCKET"
```

Require exit0/complete inventory and review running versus installed CLI plus every pane-at-risk/unknown. [Complete per-field table, private snapshot/preview/apply/remap and exit contracts](../../items/recovery/README.md) give32 sessions/128 panes/1MiB bounds. Snapshot success is not full recoverability. Restore failure1/timeout124/cancellation may leave panes; accepted partial restore3 uses holding shells, not resumed agents. Journal interlocks repeats; no automatic cleanup. A real server update/restart remains manual and separately authorized.

Update/rollback/remove: never overwrite snapshots/journals/maps; old binaries may not understand them. Retain private metadata until deliberate deletion. Do not delete private restart scripts or claim full recovery/agent-core parity without source and acceptance.

## 17. Named-host fleet installation and rollback

- **Who:** an operator/agent explicitly authorized to install selected exact bytes on each named account; never implied by reading this guide.
- **What:** `fleet install/rollback` plans or applies managed-core lifecycle with verified per-host bytes/version and separately consented launcher changes.
- **When:** after current [inspect-first setup](setup.md#how-inspect-first-then-choose-exactly-one-activation); named hosts are explicit, never implicit all.
- **Where:** Mac arm64/Linux x86_64 with Python3.9+, Bash/installer tools, reviewed HOME/paths and SSH trust where needed. The alpha.5 executable embeds support sources; source-script entry requires the full reviewed source tree.
- **Why:** retain existing manual trees and older versions while making partial/unknown results inspectable.
- **How:** after supplying reviewed `TARGETS` and `HOST_NAME`, plan one exact current version without applying:

```sh
"$TEEREX" fleet install --config "$TARGETS" --host "$HOST_NAME" --version v0.1.0-alpha.5
```

Require exit0/full per-host plan; planning neither downloads nor installs/executes candidate binaries. [Full apply, launcher consent, partial failure and rollback guide](../fleet-install.md) specifies64MiB asset/1MiB checksum caps, exit1 refusal/partial/unknown and usage2. All-host preflight precedes sequential apply; earlier successes remain after a later failure. Lost SSH leaves unknown, not safe retry or fleet-wide rollback. `--path` verifies transport PATH only; it never edits shell profiles or certifies existing panes.

Update/rollback/remove: exact retained-version rollback uses the same integrity/version checks; legacy pre-`--version` releases require core lifecycle plus byte verification instead. Preserve manual folders/backups/state; launcher restoration is explicit and does not remove managed releases. No Rex install/restart, cartridge bulk install, agent migration or personal-host certification follows.

Presentation views for §3/§4/§11: compare, watch and filter opt into declared spans with `--view progress-v1` or `--view-rules FILE`. See the [observe contract](../../items/observe/README.md#declared-presentation-views) and [lossless filter](../../items/filter/README.md#opt-in-presentation-view). Raw evidence remains alongside every view. Cosmetic counts are not idle, working or done state; partial hidden tails stay unknown. Cache and maneuver recognition behavior is unchanged.
