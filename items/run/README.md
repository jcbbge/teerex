# run

**New, separate source capability:** [`run-visible`](VISIBLE.md) adds visible foreground argv execution for disposable Mac/Linux/API13, with [acceptance](ACCEPTANCE.md) and an [opt-in Rivet migration patch](MIGRATION.md). It is not in published alpha.5 and does not change the legacy `run` contract below. Root wiring and combined shipping are integration-owned.

[Operator/agent addendum: Who, What, When, Where, Why, How](../../docs/concierge/features.md#5-run-local-argv-and-actual-exit-evidence) covers current alpha.5 use, platform/API support, verification, privacy and lifecycle. [Install/upgrade current alpha.5](../../docs/concierge/setup.md); runtime remains Mac-only/API10–13. The [independent experimental run cartridge](../../docs/cartridges.md) is available on Mac, not marked ready. Dated increment evidence below is historical.

**Experimental Phase 3 #3/#8 run-and-collect slice.** A Zig 0.15.2 CLI uses fixed Lua source and supported `rex.exec.start` callbacks to execute one explicit argv, retain bounded output and report real exit/deadline/cancellation evidence. This is not a ready cartridge, a terminal-input controller, an installer, or a background job service; experimental independent packaging is separate from the combined CLI. It shares the development executable with [observe/compare/watch](../observe/README.md), but owns separate source and tests here. Process-group supervision is shared in `src/child.zig`; execution framing and program-output collection remain owned here.

API10–13 acceptance with consumed exec bindings first shipped in the compatibility-only [v0.1.0-alpha.2](../../docs/releases/v0.1.0-alpha.2.md), without server restart/update; alpha.1 required API13. That exact candidate passed11 run checks per actual disposable API10/12/13 build. API11/every build and current alpha.5 on Joshua's machines remain separately unverified here; supplied historical M5 evidence is not current-byte certification. Validation sections below preserve their original increment-time builds.

## What was built, and what it teaches

| Historical proposal | Implemented boundary |
| --- | --- |
| C06, C08: argv execution/local reflexes | One Rex CLI/Lua invocation, explicit cwd, no shell interpolation or simulated typing. Fixed Lua handles output/wait; Zig handles bounds, process-group supervision and the final JSON receipt. |
| C09: `run_and_collect`, `capture_on_exit` | Capture bytes until Rex's process handle returns and drain its final transport output. Preserve code, signal and timeout separately. Silence, an empty stream and pipe EOF do not establish exit. No separate capture-on-exit cartridge is necessary. |
| C09/C11: owned `cancel_and_collect` portion | SIGINT/SIGTERM requests cancellation of **this invocation**, retains already received output and cleans up its owned process group. No registry or cancellation of an arbitrary PID, terminal or previous job is exposed. Unknown actual exit remains null. |
| C10: split chunks | Buffer framed transport and join bytes per stream before UTF-8 validation. Callback boundaries are neither complete lines nor complete Unicode characters; arbitrary binary output is preserved as base64. This remains support code, not a new non-Rex library. |
| C11/C24: lifetime and terminal conditions | Rex's timeout/handler cleanup did not reliably kill grandchildren in probes. The wrapper owns a process group, observes CLI exit with macOS kqueue **without reaping the group leader**, then signals the group before reaping. This reserves the group ID against PID reuse. It reports scoped signals, not unverified whole-tree cleanup or task completion. |

Source mapping: [definitive historical review](../../docs/planning/teerex-pdf-work-inventory.md), Phase 3 #3/#8 and C06/C08–C11/C24, P2 PDF pages 3–4 and 6. The historical review, scores, raw-source selection and non-Rex H01–H08 remain unchanged and unassigned. C09's `observe_until_changed` and selected `wait_for_program_status` evidence now have a separate read-only [foreground watch](../observe/README.md#what-c09s-bounded-observation-wait-adds-and-teaches); `verify_then_write` remains unimplemented. A wait result never grants terminal-input authority or means task completion.

## Build and invoke

From the repository root, using Zig **0.15.2**:

```sh
zig build -Doptimize=ReleaseSmall
./zig-out/bin/teerex run --help
```

The pinned compiler is also available through `uv run --with ziglang==0.15.2 python -m ziglang build -Doptimize=ReleaseSmall`. For the tested Mac cross-build, add `-Dtarget=aarch64-macos --prefix zig-out/mac`. Build tools are development dependencies, not an installer. Nothing is installed globally or added to Rex configuration. Upgrades require rebuilding reviewed source and rerunning tests. To stop using it, stop invoking the development executable; remove only your own build output. There is no persistent hook/service to uninstall. Project licensing is still [unselected](../../RIGHTS.md); Rex is a separate proprietary dependency and is not bundled.

Use a deliberately identified **existing** server socket and a deliberate working directory. This example runs the macOS system `pwd` executable, not a shell command:

```sh
./zig-out/bin/teerex run \
  --socket /absolute/path/to/existing/rex.sock \
  --cwd /absolute/path/to/working/directory \
  --timeout-ms 10000 --max-bytes 4096 \
  -- /bin/pwd
```

**Execution is local to the CLI machine.** The socket selects Rex coordination/version evidence, not an execution host or terminal. Even a forwarded socket does not make `rex.exec` execute on its server. No session/block is selected, created or typed into. This increment targets macOS; other OS builds reject `run` before launching Rex. No support for Joshua's particular M5, installed Rex version, or VPS is claimed.

An explicit absolute socket, absolute cwd, `--` and nonempty executable are required. Bare executables resolve through inherited `PATH`; supplying an absolute executable is more explicit. There is no implicit shell. To run a shell intentionally, the caller must explicitly supply that shell and its arguments. Stdin is immediate EOF, not an interactive TTY. The command inherits the environment except `REX_SERVER`, `REX_SESSION`, `REX_BLOCK`, `REX_CLIENT`; these hints cannot redirect this invocation. No custom environment/stdin/config interfaces are added.

**This is not a sandbox or permission system.** The supplied command can modify files, use the network and use account credentials/authority. teerex cannot infer authorization from a program report. It makes no persistent writes itself, but the program and the separately installed Rex CLI may do so. Output, directory, socket, PID and backend diagnostics can contain private data and are escaped, **not redacted**. argv is deliberately not repeated in the receipt, but can still be exposed in process listings/diagnostics. Do not run untrusted commands or commit receipts without review.

## Agent-facing result and bounds

Every normal controller result is one `schema_version=1`, `kind="run_result"` JSON object. Usage errors exit 2 with no JSON; OS/spawn/framing/write failures can exit 1 without a complete JSON result. Always check exit status **and** parse the whole packet. There are no progress records on public stdout and no automatic receipt files, cache or background monitor.

| Field | Meaning and limits |
| --- | --- |
| `execution_id`, `server`, `source`, `requested_cwd`, `client_platform` | Random per-result ID, exact endpoint, reported **server** Rex version/platform/API revision, requested cwd and binary target. Source is null until received. These are not authentication, the CLI's own version, verified actual process cwd, or physical host identity. Integer API revision10–13 and the consumed exec bindings are required before launching argv; numeric acceptance is not every-build certification. |
| `exit_report` | Rex handle's actual `{code, signal, timed_out, ok}` result, or null. Signal/timeout are not coerced into exit zero. This concerns the directly started program, not every descendant or a larger task. |
| `outcome` | `exit_reported`, `command_timed_out`, `cancel_requested`, `outer_deadline_exceeded` or `backend_error`. Cancellation is a **request**, not invented proof that the command received a signal or that every descendant stopped. An exit report can coexist with a cancellation request; neither is silently discarded. |
| `success`, `task_completion` | Success requires a successful Rex transport plus a real zero/ok/non-signalled/non-timeout result and no stop request. `task_completion="not_assessed"` always: an exit zero does not establish the user's goal was achieved. |
| `stdout`, `stderr` | `encoding` (`utf8` or `base64`), `content`, `retained_bytes`, nullable `bytes_seen`, `complete`. Preserve per-stream **prefixes** from first callback arrivals, sharing one raw-byte budget. Cross-stream ordering/priority is not promised; stdout can exhaust the budget before an important stderr message. No line/activity/completion classifier, tail or error summarizer is added. |
| `bytes_seen`, `complete`, `capture_scope` | Seen counts come from the final Rex callback report, not estimated process output. Missing final report makes counts null and completeness false. `complete=true` means **all reported callback bytes were retained**, not complete output from every descendant, a final terminal screen, or all data produced before interruption. Rex can close inherited output pipes after the direct child exits; later descendant output is outside this receipt. `capture_scope="rex_exec_callbacks"` is explicit. |
| `backend_stderr` | Separate Rex CLI diagnostics, capped at 4096 retained raw bytes, with its own encoding/count/EOF-based completeness. Never confused with the program's stderr. |
| `cleanup` | `scope="owned_process_group"`; actual group TERM/KILL call outcomes; `detached_descendants="not_covered"`; `all_descendants_verified_gone=false`. `sent` is an accepted OS signal request, not an enumerated whole-tree verification. Darwin returns EPERM even for a group containing only our zombie leader; `no_signalable_member_or_permission_denied` retains that ambiguity instead of reporting false failure or invented cleanup. |

`--max-bytes` defaults to **4096**, range **1–65536**, counting **combined retained raw stdout/stderr bytes**, not JSON-escaped bytes as in `observe`. Base64/JSON overhead, framing buffers and separately bounded backend diagnostics make the whole packet larger. Frames are incrementally parsed and bounded; per-frame parser memory is released. Rex callbacks do not retain an unbounded aggregate stdout/stderr string. This is not a bound on the program's memory, Rex internals, total I/O, CPU consumption or disk/network effects; it is a retained-output budget.

`--timeout-ms` defaults to **10000**, range **100–60000**, passed to Rex's command timeout. Rex sends TERM and escalates after about two seconds in the tested release. An additional **outer monotonic deadline** starts before spawning Rex and fires at the requested timeout **plus 5000 ms** for startup, transport and cleanup. It protects against a hung/missing final Rex result; it is not the same as the command timeout. Whole-group TERM is followed by KILL after 250 ms (or immediately after observed CLI exit), with a bounded 500 ms transport-drain allowance. Scheduling, uninterruptible kernel waits, fork and final stdout backpressure are not hard real-time guarantees. No background daemon or permanent supervisor is required.

SIGINT/TERM (including Ctrl-C to teerex) requests cancellation, then returns already received bytes with truthful unknown fields. **SIGKILL/crash of teerex itself is not covered**: no userspace cleanup handler can run then. Detached/re-grouped descendants escape the process-group boundary and may survive even a normal exit; do not use this path as a fire-and-forget launcher. A detached fixture did survive in validation and was explicitly cleaned up by the test harness. No arbitrary-process enumeration/killing, isolation or guaranteed whole-tree removal is claimed.

CLI exit codes: **0** successful directly executed command; **1** command/backend/OS failure (the program's actual code remains in JSON); **2** usage; **124** command/outer timeout; **130** SIGINT request; **143** SIGTERM request. A cancelled/failed controller never returns success just because output was quiet or pipes closed.

## Validation — 12 November 2026

Reference contracts: official [Lua reference](https://www.superlogical.com/rex/docs/reference/lua) and [Lua scripts](https://www.superlogical.com/rex/docs/automate/lua-scripts), checked against actual disposable Mac execution rather than treated as sufficient proof of child cleanup. The test runtime was arm64 macOS **27.2**, Rex **0.1.0-preview.16**, API **13**. Download archive SHA-256: `3055299e4fe881d97e8ca452e33906b8a9c7aedf36b836845ebb587829b29a29`. No third-party binary/doc capture is included here.

Initial probes established that callback chunks can split Unicode, callbacks disable the aggregate result capture, `wait(timeout)` does not kill the child, and command timeouts/script return/Ctrl-C did not reliably clean TERM-resistant descendants. A fork/kqueue probe also reproduced Darwin's zombie-only process-group EPERM. The implementation addresses these actual failures with scoped supervision, not assumptions about action lifetime.

Run public CLI tests with Python 3 and the deliberately selected test Rex executable on `PATH`:

```sh
python3 items/run/test_run.py
python3 items/observe/test_observe.py
```

Both suites create private disposable servers under `/tmp`, with explicit sockets, `/dev/null` config and restore disabled. They never attach to your default/personal Rex or VPS. Cross-built/transferred tests need `TEEREX_BIN` set to the absolute tested executable. Three consecutive fresh-server passes produced:

| Pass | Execution suite | Existing observation/comparison suite |
| --- | --- | --- |
| 1 | 11 tests, 15.389 s, OK | 16 tests, 1.471 s, OK |
| 2 | 11 tests, 15.485 s, OK | 16 tests, 1.483 s, OK |
| 3 | 11 tests, 15.471 s, OK | 16 tests, 1.483 s, OK |

After extending the fail-closed test with an absent Rex executable, a final fresh-server pass also passed: 11 execution tests in 15.354 s and 16 observation/comparison tests in 1.469 s. A native Linux smoke check rejected `run` with `RunRequiresMacOS`/exit 1 and no stdout, without launching Rex; this is an unsupported-platform check, not Linux execution support.

Cases include literal/injection-looking argv, Unicode/quotes/newlines, explicit cwd, EOF stdin, inherited environment versus poisoned Rex hints, unchanged session list, real zero/7/signalled exits, 3.2 seconds of silence followed by output, split UTF-8/lines/NUL/binary stderr, 1/4/65536-byte boundaries, 5 MB of output with only 257 bytes retained, TERM-resistant parent/grandchild timeout, SIGINT and SIGTERM partial collection, normal/abnormal Rex CLI exit, inherited pipes, deliberately detached survivors, early-closed pipes with a hung backend, missing server/cwd/executable, invalid arguments, and 20 rapid exits while an unrelated sentinel stays alive. Known same-group fixture PIDs were checked stopped; zombie-only state was not confused with executing work. The detached fixture was checked alive, then cleaned up explicitly. This does not prove behavior for all programs or escaping descendants.

The tested ReleaseSmall arm64 Mac executable is **265304 bytes**, **24080 bytes larger** than C03. SHA-256: `948b58a15cc0d7e595c415bb0f67588b6eaab50e13878accdb6c3c7154c8a5d4`. Native build, Mac cross-build, Zig formatting and seven offline comparison checks also pass. Small-command sampling (20 `/usr/bin/true` invocations) gave **18.12 ms median wall time**, min 17.17/max 53.10 ms. Two post-output RSS samples at 1 MB/64 MB emitted retained exactly **257 bytes**: teerex 1776/1776 KiB and Rex CLI 36768/42048 KiB, elapsed 355/387 ms including a 300 ms fixture hold. These are synthetic samples, **not peak-memory bounds, M5 results, productivity benchmarks or a guarantee of constant memory**.

Current scope excludes live-input/guarded-write authority, remote execution, background registries, arbitrary-job cancellation, whole-tree sandboxing, installed-M5 validation, an installer and non-Rex assignments. The selected CLI is shipped as an experimental prerelease, not a guarantee that those excluded capabilities exist.
