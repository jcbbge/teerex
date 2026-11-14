# Cooperative human clutch

`teerex clutch take|release|status --socket ABS --session session:UUID --pane block:UUID [--reason TEXT]` records whether the human holds a pane. `take` and `release` are idempotent: receipts include `held`, `changed`, and state path. Repeating `take` preserves its timestamp/reason. `release` deletes the hold record and returns `record:null`, then drains the queue; repeating it drains only remaining pending records. `status` reads saved state; it does not claim the pane exists or the server is reachable. No expiry or automatic hand-back runs.

The clutch binds **teerex callers only**. It does not stop raw `rex` writers, Rex.app keys or other programs. It is not an input lease. A hold observed by send prevents its subsequent input; there remains a race between the final local check and a server call, and in-flight input cannot be revoked. Server-enforced exclusion and human key revocation are upstream requests **R1/R4**. Do not describe this cooperative control as instantaneous cancellation of already dispatched input.

## Send behavior

All native `send` inputs check the clutch, including `--draft ignore`. The check runs before reading/clearing a draft, before message paste/Enter, and before draft restoration. By default a confirmed hold durably queues the message without input and returns `outcome:"queued"`, `queue_id`, exit0. With `--no-queue`, a hold waits in 100ms slices, consuming at most `--draft-wait-ms` total clutch wait across that send (default30000, range0..55000). With `--no-queue`, a release during that wait allows the same invocation to proceed; no resend is issued. The default overall timeout is draft wait+10000ms for both guard and ignore. An explicitly shorter overall timeout can still end first.

When the `--no-queue` wait runs out, `failure_reason:"pane_held_by_human"` reports the refusal. `retry_safe:true` is emitted only if no message paste or draft-clear attempt occurred. After any input, uncertainty remains; never blindly retry a partially dispatched send. A hold during restoration preserves acknowledged message success and reports the restoration warning rather than typing the saved draft into a held pane. Receipts include `clutch.held_observed`, `waited_ms`, `bound_reached` and `state_file`; draft text is never included.

Agent notifications, Stop reports and channel sends that use native send inherit this check. Registered-seat routing and ask cards append records without typing; they can continue while a pane is held. No typing path bypass is added.

## Private state and scope

State lives under `TEEREX_CLUTCH_DIR`, or `~/.local/state/teerex/clutch`. The directory must be owned exact0700, its lock and JSON files owned single-link regular0600; final symlinks are refused. Only take/release create the private leaf if missing; parents are trusted operator filesystem context. The state key hashes the canonical socket path, session and full pane ID. Socket aliases of an existing server therefore share a hold; a new pane ID or another server path does not inherit one. Status only reads. Ordinary unheld sends create no clutch state; confirmed held sends create private queue records. Missing state is released, with the same path rechecked before each input.

Atomic writes and a short mutation-only flock protect take/release/prune. The clutch mutation lock never spans draft waits or message delivery; a separate per-queue drain lock serializes release delivery. take/release lock contention waits at most1s. Take/release/status refuse corrupt or unsafe state with a named `failure_reason`; ordinary send reports `clutch.state:"unknown"` with that reason and proceeds without a hold. Only a positively read hold blocks input. Commands and the Rex server must run on the same machine with the same state path; named-host routing executes the whole operation on its selected host. An inaccessible/corrupt state file during send reports `unknown` and proceeds; it never turns a clutch-store fault into a messaging outage. Keep the directory until all send callers stop using it; do not delete it to clear a hold. Deliberately `release` instead.

## Palette and keys

```sh
teerex clutch palette --file /absolute/clutch.lua --socket /absolute/rex.sock
teerex surfaces palette install --file /absolute/clutch.lua --socket /absolute/rex.sock \
  --init /absolute/init.lua --plan /absolute/clutch-plan.json
# Review the returned plan, then repeat with --apply PLAN_SHA256.
```

Generation creates one new0600 native fragment with **Take control of this pane** (`teerex_clutch_take`) and **Hand back** (`teerex_clutch_release`). It refuses overwrite and never reloads personal configuration. The existing surfaces palette plan/apply machinery installs and verifies both actions. rexconfig owns actual installation/key bindings. The actions use their invoking session/pane, the generated socket/state directory and installed teerex path; optional `--teerex ABS` pins that executable. Regenerate deliberately after changing those paths. Each action calls only a bounded synchronous state command, with no pane creation, input or process signal.

Tests run with private disposable Rex config/socket/state. They cover idempotence, release during a wait, hold/refusal without bytes even in ignore mode, draft preservation when a hold arrives during draft waiting, stale pane isolation, canonical socket aliases, private-state command refusal and nonblocking unknown send receipts, fragment overwrite protection and actual plan/apply/native action invocation. The send suite separately covers Codex's captured dim-placeholder SGR, RGB/indexed background parameters, Pi-style dim fake-cursor segments, and real text that matches a placeholder verbatim. Real Rex.app palette clicks/key bindings and server input leases remain unproven.

Darwin socket identity uses POSIX `realpath`, preserving symlink aliases and paths containing spaces without opening the socket as a file. The state lock retries Darwin's transient concurrent-create ENOENT with a bound, following the existing agents/jobs pattern. Unexpected platform errors are named `clutch_state_system_error`, never a bare `Unexpected`. Linux and M5 disposable suites exercise ordinary sends, confirmed holds and store-failure fallback separately. Cancellation tests wait for the sender's post-handler state publication instead of assuming Darwin startup completes within100ms.

## One-time stale record cleanup

`teerex clutch prune` plans cleanup in the selected clutch directory; inspect `selected` and `skipped`, then run `teerex clutch prune --apply`. Python3.9+ is required. No socket/session selectors are needed: each record supplies its original target. No scheduled cleanup is installed.

Only valid owned single-link0600 records with `held:false` qualify, and only when the socket path is absent or a successful read-only Rex query confirms the session/pane is absent. Held records survive even when their target is gone. Live targets, unreachable servers, malformed records, unsafe links/files, and uncertain endpoints are preserved. Plan changes nothing. Apply recomputes eligibility and rechecks record identity under the existing mutation lock before unlinking; it never deletes the lock or directory. This coordinates with take/release, not arbitrary same-account filesystem writers. Rex queries have bounded response retention and time, are cached per socket/session during the invocation, and never autostart, attach, type or close panes. A missing directory is an empty plan. Unsafe/missing locks or contention refuse cleanup rather than manufacturing a new lock.

All sending test fixtures set `TEEREX_CLUTCH_DIR` in their own disposable directory. Regressions cover no-store sends/status, lock-independent reads, deletion on release, no-write planning, missing sockets/dead panes, held/live preservation, a take between plan/apply, corrupt records, links and unknown endpoints. Existing send/clutch/agents/boards CI suites include these checks.

`teerex clutch palette --help` uses the public command name.

## Durable held deliveries

`clutch queue --socket ABS --session ID --pane ID --json` inspects the durable queue without changing it. Messages have ordered IDs, pending/inflight state, sender, age and first line; `--show` includes full bodies. Queue directories are owned0700 and records owned single-link0600, with symlinks refused. There is no entry-count or queue-size cap. Complete records are flushed and atomically renamed; acknowledged records are removed.

Release deletes the hold and drains pending records through guarded native send in ID order, including on a repeated release. A record is durably claimed before dispatch. An uncertain dispatch stays inflight and stops the drain; later releases never replay that ID. This prevents duplicate input, but cannot establish application consumption or guarantee delivery after a crash during dispatch. No background drain or automatic retry runs.
