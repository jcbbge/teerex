# Visible foreground argv execution (`run-visible`)

**Source capability for [issue #20](https://github.com/jcbbge/teerex/issues/20), not part of published alpha.5.** Combined source now wires root dispatch and named-host selection; publishing source does not rebuild frozen release assets. The leaf export is `rex_run.runVisible(allocator, args) !u8`. [Acceptance](ACCEPTANCE.md) records executed disposable tests; [Rivet migration](MIGRATION.md) includes a tested opt-in patch without deleting the fallback. Legacy [`run`](README.md) remains Mac-local `rex.exec`, EOF stdin, no terminal mutation; this new verb does not change it.

## Who

Operators and automation such as Rivet that need **one visible, noninteractive command** plus raw output and actual immediate-child exit evidence. This is not an interactive agent harness, general remote executor, hidden/headless worker, mailbox relay, daemon, sandbox or permission system. A managed agent's protocol, scoped worker channel and callbacks remain owned by `agents`, not this runner.

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

Create an exact JSON environment map and stdin file yourself, privately. The map **replaces** inherited child environment except actual `REX_SESSION` and `REX_BLOCK`, which are reserved and injected by the helper. Supply PATH explicitly if argv needs path lookup. Environment keys/values must be strings without NUL; keys are nonempty and contain no `=`. There is no shell unless argv explicitly requests one. The private request JSON is capped at128KiB; env input at64KiB and stdin at1MiB. Stdin must be an absolute regular file with no final symlink, or literal `/dev/null` for EOF. FIFOs/devices/symlinks refuse rather than stall. Cwd must be an existing absolute directory on this command host and is also passed directly to child launch; there is no fallback cwd.

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

**Retained directories also contain exact argv/environment/stdin and may contain credentials or private output.** Files are0600; directories0700, subject to a stricter umask. Use a trusted local filesystem/parent, not an untrusted or cross-host shared directory. This is not encrypted storage or isolation from arbitrary same-account processes; receipts/paths/diagnostics also need privacy review. Do not commit them or remove an uncertain directory while its helper may still need it.

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
  --dep supervised_child -Mrex_run=items/run/main.zig \
  --dep supervised_child -Mrex_surfaces=items/surfaces/main.zig \
  -Msupervised_child=src/child.zig -lc -O ReleaseSmall -femit-bin=/absolute/teerex-visible
TEEREX_BIN=/absolute/teerex-visible REX_BIN=/absolute/test-rex python3 items/run/test_visible.py -v
```

Integrator adds root `run-visible` dispatch to `rex_run.runVisible`, root help and named-host socket injection immediately after this verb; no new Zig module dependency or host/config schema is needed. Root routing/combined CI/release and Rivet fleet cutover remain separate delivery steps. Do not remove `rex-tab.ts`, restart Rex, touch personal M5/hive, or delete existing relay/guards based on these disposable tests.
