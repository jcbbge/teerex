# Visible foreground argv execution (`run-visible`)

**Source capability for [issue #20](https://github.com/jcbbge/teerex/issues/20), not part of published alpha.5.** Combined source now wires root dispatch and named-host selection; publishing source does not rebuild frozen release assets. The leaf export is `rex_run.runVisible(allocator, args) !u8`. [Acceptance](ACCEPTANCE.md) records executed disposable tests; [Rivet migration](MIGRATION.md) includes a tested opt-in patch without deleting the fallback. Legacy [`run`](README.md) remains Mac-local `rex.exec`, EOF stdin, no terminal mutation; this new verb does not change it.

## Who

Operators and automation such as Rivet that need **one visible, noninteractive command** plus raw output and actual immediate-child exit evidence. This is not an interactive agent harness, general remote executor, hidden/headless worker, mailbox relay, daemon, sandbox or permission system. Managed protocol/ACK/brief delivery and callbacks remain owned by `agents`; the optional send-only channel below shares its transport without enrolling the command as a managed agent.

## What

The foreground controller opens one labeled **tab** or **anchored tiled pane** by composing public `surfaces open`, verifies layout and actual in-pane identity, then permits literal argv to start. The Python helper is the actual attached terminal program: it starts the child there, reads separate stdout/stderr pipes, retains bounded raw prefixes, tees output live into that terminal, emits OSC7501 `working` then `done`/`error` with `app`, base64 `title` and `msg`, and publishes an atomic result. The controller collects it and requests public `surfaces close` by default. No detached terminal, hidden execution followed by painting captured text, guessed exit from terminal text, or mutation retry exists.

Child stdout/stderr **are pipes, not TTYs**; stdin is a file, not keyboard input. Programs may buffer or change behavior accordingly. Terminal rendering is best effort and may drop display bytes under backpressure; raw capture continues independently. Rex scrollback/terminal formatting is not used as raw program output. Child-generated OSC can overwrite program-status records; those records are not authenticated execution evidence.

## When

Use for a single command whose argv/cwd/env/stdin are already decided. Wait until real child exit/signal, a deadline, or explicit SIGINT/SIGTERM. `--keep-open` retains an exited terminal for inspection; it is not a fire-and-forget launcher and does not override cancellation/deadline cleanup. The helper exits after publishing its result; Rex retains the terminal through its explicit `on_completion=false` contract. There is no idle post-command supervisor.

## Where

Supported and tested: **Linux x86_64 and Mac arm64, Rex preview.16/API13**, Python3.9+ stdlib and Zig0.15.2. Actual Mac API10/12 builds refuse before creation; API11, future revisions and other architectures are not certified. Legacy run's API10–13 support does not imply visible-run support.

All paths are **selected command-host paths**. Root named-host routing can execute this CLI on a configured host and inject its exact socket; it does not upload files or authorize an arbitrary pane host. Placement uses the current absolute teerex executable, carrying its explicit `TEEREX_INTERNAL_REX`/`TEEREX_REX` pin. The existing `surfaces` semantics apply: default tab; tiled requires an attached full-ID anchor, default right/one-third share; ratio is the new pane's share; no focus request, layout fallback or retry. First-window focus and split-ending-zoom remain Rex's behavior. Native layout attachment is not proof of GUI painting.

Before argv starts, the helper publishes its observed **kernel boot-session identity** and actual `REX_SESSION`/`REX_BLOCK` into the private launch directory. The controller requires its own observed boot identity, the exact acknowledged block/session, and verified placement before writing a matching execution permit. Linux uses `/proc/sys/kernel/random/boot_id`; Mac uses `sysctl kern.bootsessionuuid`. A configured host label, socket path or server platform is not treated as observed pane-host identity. A different boot identity refuses; inaccessible files/missing helper or identity refuse as `pane_identity_unavailable_or_foreign_host`, without claiming which absence caused it. A real Mac-controller→Linux-server proxy test refused with no argv permit. This is an operational same-host gate, **not authentication against malicious same-account code or a mount namespace with deliberately spoofed identity/files**.

## Why

A visible creation ACK, a quiet terminal, closed output pipes, OSC `done`, a shell-like exit128+N, and a missing pane are different facts. This command returns them separately rather than substituting one for real child termination. It does not infer task completion or permission. A direct child that exits143 has `exit_code:143, signal:null`; actual SIGTERM has `exit_code:null, signal:15`.

## How

Create an exact JSON environment map and stdin file yourself, privately. The map **replaces** inherited child environment except actual `REX_SESSION` and `REX_BLOCK`, which are reserved and injected by the helper. The exactness guarantee describes the map passed at process creation; a program/runtime may subsequently mutate its own environment. On the M5, native `/usr/bin/env` observes the supplied map unchanged, while Apple `/usr/bin/python3` adds or replaces `__CF_USER_TEXT_ENCODING` during startup. The Python privacy fixtures permit only that added key on Darwin when the request omitted it; all requested keys and values remain exact assertions. Separate native-child tests verify the entire map, including an explicitly supplied `__CF_USER_TEXT_ENCODING`, in both attached and detached modes. Supply PATH explicitly if argv needs path lookup. Environment keys/values must be strings without NUL; keys are nonempty and contain no `=`. There is no shell unless argv explicitly requests one. The encoded request including the in-memory environment is capped at128KiB; env input at64KiB and stdin at1MiB. Stdin must be an absolute regular file with no final symlink, or literal `/dev/null` for EOF. FIFOs/devices/symlinks refuse rather than stall. Cwd must be an existing absolute directory on this command host and is also passed directly to child launch; there is no fallback cwd.

```sh
teerex --rex /absolute/rex run-visible \
  --socket /absolute/disposable/rex.sock --session session:FULL-LOWERCASE-UUID \
  --cwd /absolute/project --env-file /absolute/private-env.json \
  --stdin-file /dev/null --app build --title 'Build checks' \
  --timeout-ms 120000 --max-bytes 4096 -- /usr/bin/make check

# The same command beside an existing attached pane, retaining its exited terminal:
teerex --rex /absolute/rex run-visible \
  --socket /absolute/disposable/rex.sock --session session:FULL-LOWERCASE-UUID \
  --layout tiled --anchor block:FULL-LOWERCASE-UUID --direction right --ratio 0.23 \
  --cwd /absolute/project --env-file /absolute/private-env.json \
  --stdin-file /absolute/private-stdin --app test --title 'Literal argv' --keep-open \
  -- /absolute/program 'one argument' '' 'literal $(not a shell)'
```

The address strings above are placeholders; use actual canonical lowercase UUIDs. `--app` matches `[A-Za-z0-9_.+-]{1,32}`. Title is1..128 UTF-8 bytes with no C0/C1/DEL controls. Title also labels the placed terminal; every emitted status repeats app/title because an OSC report replaces its record. Status protocol: [official OSC7501 reference](https://www.superlogical.com/rex/docs/build/program-status).

### Optional jobs responsibility

Supply `--registry ABS --owner LABEL --purpose TEXT` together, or omit all three. After verified placement and pane identity, the controller calls its current executable's `jobs track` with kind `command`, cleanup `manual`, and a review deadline calculated immediately before tracking from the execution budget (30 days, jobs' maximum, for `--no-deadline`). This review timestamp is metadata, not enforcement; the helper's execution clock still starts after the permit. Tracking must return a verified registration before argv is permitted. A tracking failure starts no argv and requests owned-pane close, even with `--keep-open`.

On exit, deadline or cancellation, the controller lists the selected registry to obtain the current generation, then makes at most one `jobs forget` attempt under the original owner label. Adoption/owner changes, contention or transport failure remain visible rather than authorizing an overwrite. An opted-in receipt adds `jobs` with track outcome, generation, forget outcome and bounded operation receipts. Failed forget retains the program's actual exit evidence and success calculation; inspect the registry and reconcile it explicitly. No registry format is duplicated. Native jobs calls allow20s for their10s registry queue,5s live query and cleanup margin; successful tracking after the original startup gate expires still refuses argv and forgets the registration. No jobs field or registry call is added when these flags are absent.

### Optional send-only channel

Supply `--channel-dir ABS --report-to-session session:UUID --report-to-block block:UUID` together, or omit all three. Starter aliases this same fixed report-to address. There is no ACK gate, typed brief, arbitrary destination, or `ack`/`stop` grant. Before constructing its fence, the caller creates an **empty, owned, exactly0700, nonsymlink per-launch directory**. Validation refuses before pane creation/argv. No random subdirectory is created. Use a trusted parent: the handle is bearer authority, not authentication against other same-account code.

The foreground controller creates `<dir>/channel.sock`, `<dir>/handle.json` and `<dir>/receipts.jsonl`, all0600. It injects `AGENT_CHANNEL=<dir>/handle.json` and `LC_AGENT_CHANNEL=<dir>/handle.json`, overriding those two exact-env keys only when opted in. Mount **only** `--ro-bind <dir> <dir>` into bubblewrap; no Rex socket or registry is needed inside. Do not expose this directory through another writable cwd/parent bind. The fenced program uses the existing CLI:

```sh
teerex agents channel --handle "$AGENT_CHANNEL" --request-id HEX32_UNIQUE_PER_ATTEMPT \
  --operation send --to report-to --message-file -
```

Supply UTF-8 message bytes on stdin, then EOF. `--to starter` reaches the same fixed address. There are no new client flags or file-drop transport. Framing, request validation, token checks and the service loop are shared with managed agents. Limits: one JSON line/connection,49152-byte frame,32768-byte body,20 admissions/second,500ms frame-read budget, and a24-hour capability lease (even with unlimited execution). Admitted requests can finish their bounded send after expiry. A unique32-lowercase-hex ID is consumed before the single send attempt; duplicates refuse. Lost receipts never authorize replay. Native send uses its draft guard; an in-flight send can delay result collection within its120s transport budget, while the helper independently enforces execution deadlines. INT/TERM interrupts that transport and preserves uncertain delivery without retry.

The parent exclusively creates the no-follow append-only receipt file before argv. It writes/fsyncs **one complete JSON line in one write before the next admission**. Live lines contain `schema_version:1`, `at_unix_ms`, `request_id`, `operation`, `to` (`report_to` or `starter`), `body`, `outcome` and nullable `failure_reason`; invalid/unavailable fields are null. `delivered` means native send returned `events_acknowledged`; other native outcomes keep their names. Protocol refusals are `refused`; lost delivery evidence is `uncertain`. No token field is logged. The receipts deliberately retain message bodies: keep them private and delete them explicitly when consumed.

At most256 lines:255 ordinary admissions plus a reserved final `channel_request_limit` refusal. Malformed/authentication-failed requests also consume admissions. The channel closes on child exit/cancellation or lease/cap exhaustion. Final `channel` metadata summarizes these same lines with `count`, outcome totals, request IDs/operations/outcomes and `receipts_path`. Channel refusal/failure does not rewrite the command's exit evidence. Teardown removes **only socket and handle**; the caller's directory, receipts and other caller files survive. Crash/SIGKILL cannot promise teardown. Omit the flags to retain the original environment/receipt shape and create no channel files.

### Budgets and raw output

- `--max-bytes`: combined raw **first-arrival prefix** retention across stdout/stderr, default4096, range1..65536. Per-stream ordering is preserved; cross-stream read order is not original write ordering. UTF-8 is decoded only after collection; an invalid/split retained prefix is base64, preserving exact bytes including binary/NUL/trailing newlines.
- `--timeout-ms`: execution budget, default10000, range100..86400000, starting in the helper after permission. The controller allows execution budget+1000ms to receive the final result, then requests cancellation and allows up to1000ms result drain. This is not a hard real-time guarantee.
- `--no-deadline`: mutually exclusive with `--timeout-ms`; execution continues until actual child exit or INT/TERM. `timeout_ms` and `limits.execution_ms` are null (the helper request's `timeout_ms` is null). Startup and scoped cancellation/cleanup budgets are unchanged. Controller loss leaves no helper execution deadline in this mode.
- `--startup-ms`: placement/identity gate, default10000, range1000..60000. Placement/version/close each have a bounded5s foreground transport budget plus up to1s transport termination allowance. Startup time is separate from execution; scheduler/fork/OS waits and final stdout backpressure are not hard-bounded. Cancellation during a transport waits for that bounded call, never repeats it.
- Helper cancellation/deadline sends group TERM, escalates to KILL after250ms if still waiting, then allows bounded output drain. On normal child exit it also signals remaining same-group processes before reaping the leader. Linux/newer Mac Python use `waitid(WNOWAIT)`; Mac Python3.9 uses kqueue NOTE_EXIT, preserving the leader PID until the last group signal to prevent numeric reuse. Detached/re-grouped descendants are outside this boundary.
- After actual exit, output drain ends on both EOFs or after500ms. `pipes_eof:false` means late inherited-pipe output is not fully collected. Empty/closed pipes alone never count as exit. A final OS wait that cannot establish termination leaves code/signal null, not an invented signal.
- Public transport diagnostics are separate base64 with a4096-byte cap per invocation; one child receipt is capped at256KiB. JSON/base64 overhead exceeds the raw retention budget. This does not bound the program's memory, CPU, network, filesystem effects or Rex internals.

### Full-file lifetime and privacy

Without `--output-dir`, a new private temporary launch directory holds only bounded prefix files, request/stdin/helper and atomic identity/result/controller records. After **known result plus verified close or requested retention**, its content is collected into the receipt and removed. A finished retained pane does not depend on those files. Uncertain creation/result/close leaves the directory intact. `storage_dir` and `storage_retained` say which happened; an unknown execution is never advertised as safe to replay.

`--output-dir NEW_ABSOLUTE_DIRECTORY` instead creates a0700 directory and **retains it after return**. `stdout.full` and `stderr.full` are separate raw bytes, capped at64MiB combined. Exceeding that cap requests scoped cancellation, returns `full_output_limit_exceeded` and marks full files incomplete, rather than filling disk or claiming a truncated file is full. Prefix retention remains separately bounded. Full files are closed before result publication, and callers can read them **after** the CLI returns. No background deletion timer exists: the caller deletes this directory only after consuming output and reconciling any uncertain execution/owned pane. The OS may remove `/tmp` later; choose a persistent caller-owned parent when durability is needed.

Environment values are never copied into a regular file under the launch directory. The controller hands the exact map to the visible supervisor through an owned0600 FIFO inside the private0700 launch directory, bounded by the startup budget. It is consumed and removed before a detached launch receipt returns; failure or cancellation refuses the handoff. Both `request.json` and the receipt retain only `environment.keys` (sorted), `environment.sha256` and `environment.transport:private_fifo`. The digest is SHA-256 of UTF-8 `json.dumps(env, sort_keys=True, separators=(",", ":"), ensure_ascii=True)` with no trailing newline, including injected channel keys when requested, before actual `REX_SESSION`/`REX_BLOCK` metadata is added. The caller still owns its original `--env-file` and its deletion.

**Retained directories still contain exact argv in `request.json`, raw stdin in `stdin`, and captured stdout/stderr.** Values supplied independently through argv/stdin, or printed by the child, remain in those artifacts and may contain credentials or private output. Environment handoff does not redact command output or scrub independently supplied argv/stdin. Files are0600; directories0700, subject to a stricter umask. Use a trusted local filesystem/parent, not an untrusted or cross-host shared directory. This is not encrypted storage or isolation from arbitrary same-account processes; receipts/paths/diagnostics also need privacy review. Do not commit them or remove an uncertain directory while its helper may still need it.

### Receipt and truthful cleanup

A normal receipt is `schema_version:1, kind:run_visible_result`. Usage errors exit2 on stderr; preflight refusals return bounded JSON with `failure_reason`. Always parse the complete packet and check the controller exit status. Core evidence:

| Field | Meaning |
| --- | --- |
| `source`, `placement` | Actual server version and entire public surface placement receipt/diagnostics, including geometry and host_id. Placement may have happened even when no ACK survives. |
| `created`, `pane_identity_report` | Acknowledged owned block IDs and, when received, exact helper session/block/boot identity. A lost final frame retains an earlier known ID. No ID after complete ACK loss does not mean no terminal exists. |
| `exit_report` | Actual immediate-child `exit_code` **or numeric `signal`**, launch error, stop reason, raw-byte counts, EOF fact and scoped group TERM/KILL facts. Null means actual exit is unknown. |
| `stdout`, `stderr` | `encoding`, exact `content`, retained/raw counts, `complete`; optional `full_path` and `full_complete`. Complete means the observed stream reached EOF with no omitted retained bytes, not intended task completion. Full completeness covers delivered output through the collection boundary, not detached/late descendant output. |
| `cleanup` | `scope:identified_owned_pane`, attempted, public close transport and `block_absence_verified`. False retains uncertainty, including a lost close ACK even if a separate observer happens to see absence. No automatic second close. |
| `success` | Actual exit0, no cancellation/deadline/launch failure, plus verified default close or explicit pane retention. A known child exit0 with unknown cleanup is **not success**. |
| `outcome`, `cancellation_signal` | `exit_reported`, explicit refusal/uncertainty/launch error, deadline, cancellation, full-output limit or controller error. Signal/deadline can coexist with an actual child result; cancellation never becomes success. |
| `storage_dir`, `storage_retained` | Exact private evidence location and whether it remains. `controller.json` records known IDs/cleanup intent before mutations, `started.json` the actual immediate-child PID, `result.json` the helper result. These are same-account evidence, not authenticated receipts. |

Exit0 means the success predicate above;1 failure/refusal/uncertainty including known nonzero/signal;2 usage;124 deadline;130 requested SIGINT;143 requested SIGTERM. Program exit7 remains7 in JSON, not the CLI's exit status. `retry_safe:false`, `task_completion:not_assessed`, `painted_visibility:not_assessed` and `all_descendants_verified_gone:false` are deliberate.

SIGINT/TERM write a launch cancellation request, collect available evidence and close only the identified created pane, even with `--keep-open`. If creation ACKs are completely lost, the controller cannot safely invent an owner ID and cannot guarantee closure: it leaves evidence, issues no permit and does not retry. Controller SIGKILL/crash/disconnection cannot run cleanup; the helper still has its execution deadline if alive, but the pane may remain. If the helper itself dies, the immediate child may survive even verified pane closure; acceptance demonstrates that case and cleans up only its fixture. Never claim pane closure guarantees every descendant or SSH-remote process died. No arbitrary PID enumeration/killing or outside-pane mutation is exposed.

## Development and integration

The standalone acceptance executable dispatches only `run-visible`, `run` and public `surfaces`; it is not a release or alternative installed binary:

```sh
zig build-exe --dep rex_run --dep rex_surfaces -Mroot=items/run/test_visible_cli.zig \
  --dep supervised_child --dep scoped_channel -Mrex_run=items/run/main.zig \
  --dep supervised_child -Mrex_surfaces=items/surfaces/main.zig \
  -Msupervised_child=src/child.zig -Mscoped_channel=src/scoped_channel.zig -lc -O ReleaseSmall -femit-bin=/absolute/teerex-visible
# Full optional jobs/channel acceptance needs the combined CLI, not this core-only entry:
zig build -Doptimize=ReleaseSmall
TEEREX_BIN="$PWD/zig-out/bin/teerex" REX_BIN=/absolute/test-rex TEEREX_AGENTS_FENCE=1 python3 items/run/test_visible.py -v
```

Integrator adds root `run-visible` dispatch to `rex_run.runVisible`, root help and named-host socket injection immediately after this verb; run and agents import the shared `scoped_channel` embedded Python module; no host/config schema is added. Root routing/combined CI/release and Rivet fleet cutover remain separate delivery steps. Do not remove `rex-tab.ts`, restart Rex, touch personal M5/hive, or delete existing relay/guards based on these disposable tests.

### Detached visible execution

`--detach` keeps supervision in the **visible pane's own program** and returns after verified placement, same-host identity, optional jobs registration and the supervisor handoff. The launch receipt has `kind:run_visible_launch`, `outcome:launched`, a32-hex `launch_id`, `session_id`, `created.block_id`, `supervisor_pid` and an absolute `receipt_path`. Its success describes launch, not command completion. A missing/lost launch ACK never authorizes retry. Other argv/cwd/env/stdin, deadline, retention, channel and jobs flags keep their contracts. The default execution deadline remains10000ms; LONG callers explicitly choose `--no-deadline`.

Before self-close, the pane atomically writes exit/output evidence to the named receipt with `receipt_state:cleanup_pending_or_unknown`, `cleanup.block_absence:unknown` and `success:false`. Rex terminates the pane program when it closes itself. One already bounded native `surfaces close --publish-receipt-file ABS` invocation therefore publishes the verified absence afterward, marking `receipt_state:final` and recomputing final success. It has a5000ms RPC budget plus a hard2000ms publication/cleanup allowance, and never retries. A killed/lost publisher loses only absence evidence: the prepared command exit/output survives and stays unknown. This short-lived close is not a long-running supervisor.

The pane program owns the actual command, capture thread and optional scoped channel after handoff; no separate long-running supervisor/daemon is started. The launch client can exit or disappear. After actual child exit, the supervisor closes the channel and forgets its tracked job. `jobs inspect` exposes `entry.receipt_path` while registered. The final private `run_visible_result` preserves exit/signal, separate output summaries, jobs/channel results and cleanup evidence. `--keep-open` retains normally exited success/failure panes; deadline/cancellation still requests scoped cleanup. Full-file capture still requires `--output-dir`.

Read the final evidence independently of Rex:

```sh
teerex run-visible receipt --file /absolute/receipt_path
teerex run-visible receipt --file /absolute/receipt_path --wait-ms 10000
```

`--wait-ms` defaults0, range0..86400000. While cleanup is pending/unknown, a positive wait also waits for final publication until its budget expires, then returns the preserved receipt with unknown absence. A zero wait returns any preserved receipt immediately; inspect `receipt_state` and `cleanup.block_absence`. An absent final file yields `kind:run_visible_receipt,outcome:pending`, exit0, including on wait expiry. Pending means **no final receipt yet**, not proof the command is running; supervisor loss or failed publication can remain pending. INT/TERM cancels only the read wait (130/143), never the command. Final reads return the stored JSON with exit0 even if the command failed; inspect `success`, `outcome`, `exit_report` and cleanup. Input must be an owned, single-link, nonsymlink regular0600 file, at most1MiB. Named-host routing selects only the command host; it injects no Rex socket into this offline leaf.

Detached launch directories are retained, including the default private temporary directory. The caller consumes the final receipt and explicitly deletes its own directory after reconciling unknown outcomes; teerex starts no deletion timer. Choose `--output-dir` under persistent caller-owned storage when OS temporary-file lifetime is insufficient. Directory contents include sensitive argv/env/stdin and output; protect them accordingly. Controller death before handoff, supervisor SIGKILL, Rex loss and host loss cannot guarantee execution evidence or closure; do not replay uncertain work automatically.
