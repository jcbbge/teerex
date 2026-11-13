# Rivet visible-run migration candidate

**Delivered:** [rivet-run-visible.patch](rivet-run-visible.patch) adds an explicit opt-in adapter, preserving `rex-tab.ts` and its current fallback as the default. It is **not applied to Rivet**, not a release, and not authorization to alter hive, personal M5, running jobs, relay services or Rex. The teerex source owner delivers this patch to integration, not a second implementation in Rivet.

## Reference actually inspected

Repository [`jcbbge/rivet`](https://github.com/jcbbge/rivet), commit [`cc5db328345c64f484ce8704f4c402628cfacab9`](https://github.com/jcbbge/rivet/commit/cc5db328345c64f484ce8704f4c402628cfacab9), `jobs/src/rex-tab.ts`. It really creates a window, emits its own OSC7501, shell-quotes argv/env, tees merged output into `out`, writes an exit file, polls it every 500 ms, closes a block and removes its temp directory. This is not a claim that documented Mac-local `run` regressed or that published alpha.5 already replaces it.

The patch adds `jobs/src/teerex-tab.ts` and exactly one explicit dispatch branch to `runInTab`. `RIVET_USE_TEEREX_RUN_VISIBLE=1` selects it **before** the legacy helper creates a session or file. If teerex returns missing/uncertain evidence, it rejects with the retained private directory, **never falls back or repeats the command**. Unset the flag to select the old implementation for **future** calls only; that is not permission to rerun a possibly applied request.

## New adapter contract

Provide these explicit environment settings to the Rivet process on its command host, after review:

| Setting | Meaning |
| --- | --- |
| `RIVET_USE_TEEREX_RUN_VISIBLE=1` | Explicit opt-in. Default remains the old wrapper. |
| `RIVET_TEEREX_BIN` | Absolute, reviewed combined teerex executable containing the new root dispatch. Alpha.5 is not sufficient. |
| `RIVET_REX_BIN` | Absolute Rex executable pin. |
| `RIVET_REX_SOCKET` | Absolute existing same-host socket, never an inferred personal/default endpoint. |
| `RIVET_REX_SESSION_ID` | Existing canonical full session ID. The adapter does not implicitly create or resolve a session label. |
| `RIVET_TEEREX_TIMEOUT_MS` | Explicit execution budget if supplied; default 24 hours, maximum 24 hours. Startup/cleanup budgets remain separate. |

The adapter preserves the supplied literal command/fence argv, explicit cwd, input string and existing environment filtering: remove Rivet credentials and stale session/block metadata, merge the caller's exact env, then let teerex inject actual pane metadata. It invokes a fixed positional shell shim `exec "$@" 2>&1` so stdout/stderr merge **before** the actual program starts; no argv interpolation occurs, and exec leaves actual immediate-child signal evidence intact. This preserves the original wrapper's merged output semantics without guessing a write ordering between separately captured pipes. The full merged bytes are read from `stdout.full` only after final execution and verified close.

The retained output is logged, the original 2,000,000-character threshold/1,000,000-character tail is applied, and the existing `RunResult {code,out,tail}` is returned for normal zero/nonzero exits. The full numeric signal remains in the controller receipt and log. The original Rivet convention is retained: actual signal or normal exit130/137/143 does not settle the call into a successful job record. Existing process-signal handlers continue to apply; the adapter forwards INT/TERM to active teerex controllers, which request scoped cancellation. This forwarding is not proof of every worker, descendant or SSH-remote process dying.

Only after known execution, verified close and successful full-output consumption does it remove its own temporary directory. Unknown outcomes and transport/launch failures retain it and reject without a retry. New bounded refusals are deliberate: stdin over 1 MiB, invalid/reserved env metadata, unsupported API, unknown/foreign pane host, or output beyond 64 MiB do not become a successful Rivet step. The old wrapper had no equivalent explicit deadlines/storage limits; callers must accept these boundaries before cutover. Programs whose stdout/stderr require a TTY need a separate design; this adapter, like the old tee pipeline, is noninteractive.

## Executed migration checks

The candidate patch was checked against the exact downloaded reference (`git apply --check`), then its **actual patched `runInTab` export** was imported and run with Bun 1.4.4 against the disposable Linux API13 server and the standalone teerex acceptance binary. These were real visible commands, not mocks:

- Empty, quote, Unicode, newline and shell-looking argv remained literal; injection marker absent.
- Exact cwd, caller env and multiline stdin survived; `RIVET_SECRET` was absent in the child.
- stdout followed by stderr returned as merged output and was logged after collection.
- Actual exit0 and exit7 mapped to `RunResult.code` correctly.
- A 2.1 MB output fixture produced the expected one-million-character retained tail.
- All known created blocks were absent afterwards; the legacy file and default path remained present.

The underlying runner's [Mac/Linux acceptance](ACCEPTANCE.md) separately covers signals, deadlines, retained panes, raw binary/Unicode, output limits, lost create/final/close ACKs, actual controller/helper death and foreign-host refusal. This migration fixture does **not** establish real Claude/Codex versions, bubblewrap fence behavior, fleet-board/#13 call-record integration, systemd process-signal topology, actual hive environment, or production cutover parity. Those are integration/cutover gates, not silent assumptions.

## Review and eventual cutover

In an isolated Rivet checkout at the exact reference commit, review and check the patch before any apply. Its dispatch hunk intentionally carries minimal context rather than reprinting the vendor wrapper; use `--unidiff-zero` with that pinned reference:

```sh
git apply --check --unidiff-zero /absolute/teerex/items/run/rivet-run-visible.patch
# Applying this reviewed patch is a separate action, not part of the teerex implementation.
```

Combined teerex source now wires the root verb/host injection and passes the new runner's combined Mac/Linux acceptance; check the exact pushed-head CI separately before selecting its source commit. The Rivet owner then opts in on a disposable node with the exact reviewed teerex/Rex pins, real fence and harness commands, verifies cancellation and retention from its actual service supervisor, and reconciles all unknown outcomes. Only after that parity and an explicit approved fleet cutover should it remove the old shell script/exit-file polling, fallback, or guards. No such removal, deploy or personal-host access occurred here.

## Rivet LONG steps (source follow-on)

The native runner now accepts `--no-deadline` instead of `--timeout-ms` for LONG steps. Pass one or the other; the default remains 10000 ms. Execution ends on actual child exit or SIGINT/SIGTERM, with startup/cleanup budgets unchanged and `limits.execution_ms:null`. The earlier candidate patch above still supplies a finite budget; the Rivet owner must explicitly choose the new flag when updating its adapter. This source change neither applies that patch nor changes a service.

## Rivet responsibility mapping (source follow-on)

Pass `--registry ABS --owner rivet --purpose 'item · step'` to track the visible command before it starts and forget its current generation after it ends. All three flags are required together. The controller uses native jobs track/list/forget and reports them in `jobs`; Rivet should inspect a failed forget without repeating execution. Unlimited steps use a 30-day review timestamp, not a 30-day execution deadline. Omitting the flags preserves the original adapter behavior.

## Rivet socket channel and live first-turn evidence (source follow-on)

Before building the worker's fence argv, create a fresh empty0700 per-launch directory. Pass `--channel-dir ABS --report-to-session session:UUID --report-to-block block:UUID` to run-visible. Bind exactly `--ro-bind ABS ABS` into bubblewrap; keep the Rex socket and registry outside, and do not expose the channel through another writable parent mount. Both `AGENT_CHANNEL` and `LC_AGENT_CHANNEL` name `ABS/handle.json`; its socket is `ABS/channel.sock`. Starter aliases report-to. The child calls `teerex agents channel --handle "$AGENT_CHANNEL" --request-id HEX32 --operation send --to report-to --message-file -`, writes its message on stdin and closes stdin. No managed ACK/brief, `--drop`, or `requests/` directory is involved.

Read `ABS/receipts.jsonl` while the worker runs for first-turn message evidence; the parent creates it before argv and fsyncs each line before the next admission. `delivered` means native `events_acknowledged`, not task completion. The file records bodies and refusals without a token field; final `channel.count`/`channel.outcomes` summarize the same lines. It survives socket/handle teardown and belongs to Rivet to consume/delete. A used directory cannot be reused without explicit caller reconciliation/cleanup. [Limits and no-replay behavior](VISIBLE.md#optional-send-only-channel):24-hour lease,255 ordinary admissions plus final cap refusal,32KiB messages. Even a LONG command's channel is bounded; exhausted/expired authority never restarts the command.

Disposable Linux acceptance uses the actual CLI through a real read-only bubblewrap bind with Rex/registry inaccessible: two live delivered lines, fixed-destination/token/replay/grant refusals, cap and cancellation cleanup. This proves the socket mount contract, not any particular harness's internal sandbox policy or a production Rivet cutover. Rivet must allow the worker's socket connection under that worker's own policy.

## Rivet agent/fleet runner launch (source follow-on)

Use `run-visible --detach` with the existing explicit socket/session/cwd/env/stdin/app/title and literal argv instead of a spawn that leaves a completed tab. Return the launch receipt immediately after handoff, store its `launch_id`, `created.block_id` and `receipt_path`, and later read `teerex run-visible receipt --file ABS [--wait-ms N]`. Launch success is separate from the command's final success; `pending` is missing final evidence, not liveness. Keep `--no-deadline` explicit for LONG runners, and add the existing jobs/channel flag groups as needed. The visible pane program keeps those responsibilities after the caller exits; jobs inspection exposes the final receipt pointer until the registration is forgotten. Use `--keep-open` when retaining a normally completed pane is intentional. No Rivet files, production services or installed assets are changed here.
