# offstage

**Experimental Phase 3 #4 lifecycle slice: run one explicitly owned terminal outside the selected session's layouts, collect its exit evidence, then close only that created block.** This implements C12 and a bounded foreground-owner subset of C13. It does not implement a durable registry, daemon, automatic presentation/C14, sandbox/C15 or independent cartridge packaging. Historical scores and deferred non-Rex work remain unchanged.

## Use

Build the combined CLI with Zig **0.15.2**, put your deliberately selected Rex executable on `PATH`, and select an already-running, known local Apple-silicon Mac server and existing session:

```sh
zig build -Doptimize=ReleaseSmall
./zig-out/bin/teerex offstage --help
./zig-out/bin/teerex offstage \
  --socket /absolute/path/to/existing/rex.sock --session session:FULL-UUID \
  --cwd /absolute/working/directory --purpose 'check this working tree' \
  --timeout-ms 10000 --max-bytes 4096 -- /usr/bin/git status --short
```

This is an invocation example, not permission to execute arbitrary programs. Commands inherit the terminal host account's filesystem, network, environment and credential authority. Nothing is isolated. Unlike [run](../run/README.md), execution is on the **selected Rex terminal creator's host**, not necessarily the CLI machine. A Unix socket can be forwarded; endpoint and reported host labels are not authentication or proof of physical locality. Do not point this initial local-Mac workflow at a VPS or an unknown forwarded server.

One foreground teerex invocation owns one new block. There is no implicit focus/environment target, existing-block adoption or typing into another program. The command requires an absolute socket, full session UUID, absolute cwd, nonempty UTF-8 purpose (at most 256 bytes), and a **100–60000 ms** collection deadline. `--max-bytes` defaults to **4096**, range **256–65536 JSON-encoded content bytes including quotes**. Unknown/repeated/missing options fail. Child environments discard `REX_SERVER`, `REX_SESSION`, `REX_BLOCK` and `REX_CLIENT`; every Rex call disables autostart and selects the explicit endpoint/session. Rex itself and its configuration/executable must be trusted.

The terminal uses `shell=none`, `login=false`, `interactive=false` and no stdin input. A fixed `/bin/sh` shim performs `cd -- "$1" || exit 125`, shifts the directory argument, then `exec "$@"`. Values are separate argv entries, never interpolated source. This prevents Rex's invalid-cwd fallback from silently running your command in the home directory. A reported 125 is not uniquely attributable to that shim: the selected program could also exit 125. Programs run in a PTY, not a pipe; terminal formatting, buffering and stderr merging differ from `run`.

## Receipts and concurrent observation

Stdout is NDJSON, not a single JSON object. Check the process exit status **and** all records; a started record alone is not a final result.

- `offstage_started` follows acknowledged creation. It carries the invocation ID, unique `teerex-offstage-…` label, purpose, source/server instance/host, exact session/block target, collection budget, foreground owner and close-on-exit/deadline/cancel policy. Another caller can use its target with [observe/watch](../observe/README.md) while this owner remains alive. The block is addressable/listed but detached; creation never changes a window, layout or focus.
- `offstage_result` separates actual reported terminal-program exit from deadline, cancellation request, collector failure, capture and cleanup. `task_completion="not_assessed"` always. Capture is a bounded **screen-and-scrollback prefix after reported exit**, not raw program stdout/stderr, a latest viewport or an atomic final-output drain guarantee. Deadline/cancellation returns null capture rather than claiming a final capture. `complete=false` cannot establish what an uncaptured tail contains.
- `creation_dispatch_observed` means the pre-create transport frame arrived. `creation_request_may_have_run` is true after that frame and otherwise null: losing transport can hide both dispatch and successful creation. `creation_acknowledged=false` and a null block ID do **not** prove no resource exists. Creation is never retried, and unknown targets are never guessed/adopted/closed by label. Inspect the selected server manually using the emitted invocation label if an acknowledgement was lost.
- Cleanup reconnects once, requires the same reported server instance and host, closes only the acknowledged created block, and checks its absence in the session's returned block list. `close_acknowledged`, `block_absent`, identity match and cleanup failure are separate nullable evidence. An identity mismatch refuses close. A lost cleanup response remains unknown even if the close actually succeeded. Missing/malformed lists cannot establish absence.
- `success=true` and exit **0** require reported program exit zero, a valid collection, matching cleanup identity and verified block absence, with no deadline/cancellation/cleanup failure. A nonzero program exit or unknown/error returns **1**. Usage is **2**, deadline **124**, SIGINT/SIGTERM **130/143**. A reported zero program exit with unknown cleanup is **not** success. Exit evidence is not proof that a user task was correct.

Source identity, purpose, argv-derived output, paths and backend diagnostics can contain private information. JSON is escaped, not redacted; the command saves no history or files itself. Save receipts/captures deliberately into private ignored locations, never automatically into a public repository.

## Lifetime and limits

The owner polls supported process evidence every **50 ms after each query** through one persistent Rex/Lua connection. It does not infer exit from silence or disappearance. On reported exit, deadline, INT/TERM or a collector error after acknowledged creation, it makes one bounded cleanup attempt through a second connection. Cleanup has a **5000 ms** budget; the shared supervisor may add up to about **500 ms per stopped phase**, plus scheduling/output/exceptional OS waits. The collection deadline is not a hard real-time total wall-clock limit. A second cancellation can interrupt cleanup. Blocking stdout, kernel stalls, SIGKILL or a crash are outside the graceful lifetime boundary.

Closing a block removes a Rex resource; it is **not verified process-tree termination**. Ordinary direct children stopped in the disposable tests, but a deliberately forked HUP/TERM-resistant descendant survived close. `all_processes_verified_gone=false` and `process_effect="not_verified"` remain explicit even after block absence. SIGKILL of the teerex owner leaves its detached terminal/program alive; there is no durable registry or external janitor to recover it. The harness manually cleans these deliberate leak controls. Do not use this feature for work requiring isolation, guaranteed whole-tree cleanup or unbounded unattended service lifetime.

No existing block is detached, moved, focused, labelled, closed or adopted by the CLI. The original C14 presentation proposal is still separate. Direct disposable API probes established that `session.move_block` can place a detached block beside a known anchor while preserving anchor focus and `session.detach_block` preserves process life. Those probes are not a shipped `present` command or a promise about Joshua's human workspace. Intentional presentation needs an explicit destination/reason and lifetime rule; this slice preserves layouts by not changing them.

Install/upgrade/remove the shared CLI using its [documented installer](../../docs/install.md) or a reviewed source build. Invoking a released tag only supplies that tag's features. No Rex config, key binding, server startup, background hook or proprietary binary is installed by this item. Stop foreground work before removing/replacing the executable. Rex is separately acquired; project licensing remains [unselected](../../RIGHTS.md).

## Validation — 12 November 2026

```sh
TEEREX_BIN=/absolute/path/to/combined/teerex python3 items/offstage/test_offstage.py -v
```

Seven public-CLI checks pass on a disposable **arm64 macOS 27.2**, checksum-verified **Rex preview.16/API13**, through actual new/describe/process/format/list/close calls. Fixtures use a private socket, `/dev/null` configuration, restore disabled and separate state. No personal M5, VPS or default server is contacted.

- A still-running detached job remains addressable by concurrent `observe`; direct Rex queries confirm its placement and canonical cwd. Literal Unicode/quotes/shell-looking arguments survive without executing embedded text. Session block inventory and `session.view` return to their original state, and the view remains unchanged during the job.
- Programs actually exiting 0 and 7 retain those codes; invalid cwd yields 125 without executing the requested program. The initial default `login=true` probe instead reported 0 for an exit-7 command and added login output. Explicit `login=false` was required and verified before relying on exit evidence.
- Deadline, INT and TERM remove the acknowledged block; a forked resistant descendant still survives close. Owner SIGKILL leaves its addressable block/direct program alive. Tests independently inspect PIDs/block lists and clean deliberately surviving fixtures. A first direct-child survival hypothesis did not reproduce with `login=false`; the final regression deliberately uses a forked resistant descendant and does not claim every direct child survives.
- Both capture-budget boundaries and actual incomplete/complete prefixes are exercised. Missing socket does not autostart; malformed options fail before execution.
- A pass-through wrapper around real Rex deliberately drops creation dispatch/acknowledgement frames. Exactly one real block remains, the final target/creation/cleanup evidence stays unknown and no retry creates a second block. Separate injected malformed transport, lost cleanup receipt and mismatched expected instance tests independently check actual block existence. They show successful cleanup after a collector error, unknown cleanup despite actual successful close, and refused close on identity mismatch. The mismatch is injected, not an actual second Rex installation/server restart.

The first combined run passed **7 offstage checks in 3.980 s**, alongside **27 observe/compare/watch**, **11 run**, **8 executed doctor** (one non-Mac guard skipped) and **10 maneuver** checks. Native and Apple-silicon cross-builds use Zig **0.15.2**; native offline checks cover the shared comparison, doctor and maneuver contracts. Later combined results are recorded separately in the direction/evidence record. These are executable/interface checks, not M5 benchmarks, whole-system memory/energy measurements, sandbox/input-safety certification or completion of all Phase 3 #4 requirements.

Source mapping: original PDF P2 physical **p4**, C12/C13 and V07; C14 presentation and C15 isolation remain separate in the immutable [historical review](../../docs/planning/teerex-pdf-work-inventory.md).
