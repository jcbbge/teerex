# Cooperative human clutch

`teerex clutch take|release|status --socket ABS --session session:UUID --pane block:UUID [--reason TEXT]` records whether the human holds a pane. `take` and `release` are idempotent: receipts include `held`, `changed`, the saved timestamp/reason and state path. Repeating the same state preserves its original timestamp and reason. `status` reads saved state; it does not claim the pane exists or the server is reachable. No expiry or automatic hand-back runs.

The clutch binds **teerex callers only**. It does not stop raw `rex` writers, Rex.app keys or other programs. It is not an input lease. A hold observed by send prevents its subsequent input; there remains a race between the final local check and a server call, and in-flight input cannot be revoked. Server-enforced exclusion and human key revocation are upstream requests **R1/R4**. Do not describe this cooperative control as instantaneous cancellation of already dispatched input.

## Send behavior

All native `send` inputs check the clutch, including `--draft ignore`. The check runs before reading/clearing a draft, before message paste/Enter, and before draft restoration. A hold waits in 100ms slices, consuming at most `--draft-wait-ms` total clutch wait across that send (default30000, range0..55000). A release during that wait allows the same invocation to proceed; no resend is issued. The default overall timeout is draft wait+10000ms for both guard and ignore. An explicitly shorter overall timeout can still end first.

When the wait runs out, `failure_reason:"pane_held_by_human"` reports the refusal. `retry_safe:true` is emitted only if no message paste or draft-clear attempt occurred. After any input, uncertainty remains; never blindly retry a partially dispatched send. A hold during restoration preserves acknowledged message success and reports the restoration warning rather than typing the saved draft into a held pane. Receipts include `clutch.held_observed`, `waited_ms`, `bound_reached` and `state_file`; draft text is never included.

Agent notifications, Stop reports and channel sends that use native send inherit this check. Registered-seat routing and ask cards append records without typing; they can continue while a pane is held. No typing path bypass is added.

## Private state and scope

State lives under `TEEREX_CLUTCH_DIR`, or `~/.local/state/teerex/clutch`. The directory must be owned exact0700, its lock and JSON files owned single-link regular0600; final symlinks are refused. The command creates the private leaf if missing; parents are trusted operator filesystem context. The state key hashes the canonical socket path, session and full pane ID. Socket aliases of an existing server therefore share a hold; a new pane ID or another server path does not inherit one. Stale records are retained and never treated as a new pane's hold. A first send initializes absent state to released under the mutation lock without ever releasing an existing hold.

Atomic writes and a short mutation-only flock protect take/release/initialization. It never spans draft waits, message delivery or process lifetime; lock contention waits at most1s. Corrupt or unsafe state fails closed. Commands and the Rex server must run on the same machine with the same state path; named-host routing executes the whole operation on its selected host. A missing/inaccessible state file during send refuses rather than assuming release. Keep the directory until all send callers stop using it; do not delete it to clear a hold. Deliberately `release` instead.

## Palette and keys

```sh
teerex clutch palette --file /absolute/clutch.lua --socket /absolute/rex.sock
teerex surfaces palette install --file /absolute/clutch.lua --socket /absolute/rex.sock \
  --init /absolute/init.lua --plan /absolute/clutch-plan.json
# Review the returned plan, then repeat with --apply PLAN_SHA256.
```

Generation creates one new0600 native fragment with **Take control of this pane** (`teerex_clutch_take`) and **Hand back** (`teerex_clutch_release`). It refuses overwrite and never reloads personal configuration. The existing surfaces palette plan/apply machinery installs and verifies both actions. rexconfig owns actual installation/key bindings. The actions use their invoking session/pane, the generated socket/state directory and installed teerex path; optional `--teerex ABS` pins that executable. Regenerate deliberately after changing those paths. Each action calls only a bounded synchronous state command, with no pane creation, input or process signal.

Tests run with private disposable Rex config/socket/state. They cover idempotence, release during a wait, hold/refusal without bytes even in ignore mode, draft preservation when a hold arrives during draft waiting, stale pane isolation, canonical socket aliases, private-state refusal, fragment overwrite protection and actual plan/apply/native action invocation. The send suite separately covers Codex's captured dim-placeholder SGR, RGB/indexed background parameters, Pi-style dim fake-cursor segments, and real text that matches a placeholder verbatim. Real Rex.app palette clicks/key bindings and server input leases remain unproven.
