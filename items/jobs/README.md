# jobs — explicit durable responsibility and presentation

[Operator/agent addendum: Who, What, When, Where, Why, How](../../docs/concierge/follow-ons.md#2-durable-jobs-and-deliberate-presentation) covers current alpha.5 prerequisites, exact targets, generations, verification, adoption/presentation recovery, privacy and lifecycle. [Current setup](../../docs/concierge/setup.md) and [separate experimental cartridge packaging](../../docs/cartridges.md) are shipped, not pending integration. Runtime remains Mac/Linux/API13 only. Jobs was absent in alpha.3 and is not a process authority.

**Follow-on to alpha.3, not part of that frozen release.** This leaf implements the bounded persistent registry and intentional presentation portions of Phase 3 #4/C13–C14. It does not replace [spawn](../spawn/README.md) or change [offstage](../offstage/README.md). Only an explicit foreground invocation acts; no daemon, agent, watcher, auto-adoption, automatic cleanup, configuration or server is installed.

The public leaf interface is `pub fn run(allocator, args) !u8`, importing `supervised_child`. Shared build/dispatch/CI wiring is integrated. `test_cli.zig` remains a standalone development test bridge, not a second product or released executable. Live operations currently require **actual API13 on darwin_arm64 or linux_amd64**. This intentionally does not extend alpha.3's API10–13 promise to new methods on old servers.

## What a record means

A job record names one **explicit absolute socket + full canonical lowercase session/block IDs**, the observed server instance/host and block host, kind (`agent` or `command`), purpose, responsible owner label, absolute review deadline, and `cleanup=manual`. Records survive teerex exit. They do **not** keep processes alive or establish who created, owns, controls or is authorized to use a terminal. `owner` is an operator-supplied responsibility label, not an authenticated person, OS PID, Rex native owner or input lease. Its liveness is never guessed from a PID, terminal silence or a lost connection.

- **`track`** explicitly records an existing, live-verified terminal. It never launches or takes native ownership. A known target cannot be overwritten; the same server resource cannot be tracked twice through socket aliases in the same registry. Unregistered orphan discovery is manual: select the exact IDs, establish authority outside this tool, then track deliberately. No label search guesses an orphan's identity.
- **`list`** reads saved metadata offline, with `live_state=not_checked`. It neither refreshes nor implies freshness. Compare the recorded deadline with `evaluated_at_unix_ms` if working offline.
- **`inspect`** checks the selected live server instance/host and block host, existence, placement, view revision, native owner and optional terminal `last_exit.exit_code`. `last_exit_code_reported` is only Rex's last reported exit; it may belong to an earlier program. Missing blocks, unavailable sessions and unavailable transport are not completion or process-death evidence. Observations are sequential, not an atomic snapshot; every receipt is already historical by the time it arrives.
- **`adopt`** changes only recorded responsibility. It requires the exact target, matching `--from-owner`, a different `--owner`, current `--generation`, explicit reason and new review deadline, plus live identity verification. A native Rex owner causes refusal; no `take` or ownership method is called. A crash/offline owner cannot silently be deemed dead. The operator must establish the handoff's authority outside this tool; matching strings do not grant it. Adoption does not alter offstage's original invocation-owned cleanup, transfer a process handle or cancel a former controller.
- **`present`** requires the recorded owner, current generation, reason, same-session explicit anchor and explicit `--focus yes|no`. It is the only operation that changes Rex presentation; its limits follow below.
- **`forget`** requires recorded owner, current generation and reason, and removes only that local record. It does not contact Rex, stop work, close a terminal or prove process death. It can remove a stale record after explicit operator review.

The per-registry generation counter increases on registration, adoption and each presentation intent. Forget/re-register does not recycle a generation. Old owners and stale-generation requests refuse. This protects cooperating invocations of **this registry**, not other registries, direct Rex clients, humans or same-account programs editing state.

## Use

Create a new operator-chosen private directory on a trusted local filesystem. Never put it in a public repository. `jobs` does not create directories, select a default registry/target or infer an owner from the environment.

```sh
umask 077
mkdir -m 700 /absolute/private/jobs
# Set SOCKET, SESSION and BLOCK from a deliberately selected existing Rex target.
# Choose an absolute future Unix-millisecond review deadline (at most 30 days ahead).
teerex jobs track --registry /absolute/private/jobs \
  --socket "$SOCKET" --session "$SESSION" --block "$BLOCK" \
  --owner operator --kind agent --purpose 'review this visible worker' \
  --deadline-unix-ms "$REVIEW_DEADLINE_MS" --cleanup manual
teerex jobs list --registry /absolute/private/jobs
teerex jobs inspect --registry /absolute/private/jobs \
  --socket "$SOCKET" --session "$SESSION" --block "$BLOCK"
```

Use the latest returned **generation**, not an assumed starting value. A deliberate handoff:

```sh
teerex jobs adopt --registry /absolute/private/jobs \
  --socket "$SOCKET" --session "$SESSION" --block "$BLOCK" \
  --from-owner operator --owner successor --generation "$GENERATION" \
  --reason 'explicitly agreed handoff' --deadline-unix-ms "$NEW_REVIEW_DEADLINE_MS"
```

There is no deadline enforcement after the CLI exits. `cleanup=manual` means the recorded owner must review the exact resource at that deadline, deliberately stop/close only work they are authorized to manage with an appropriate tool, independently verify process effects when required, then forget or explicitly hand off the record with a new deadline. **Neither an expired review date, a forgotten record nor a closed block proves descendants stopped.** This item cannot fulfill unattended hard-deadline, guaranteed whole-tree cleanup or sandbox requirements. Do not choose it for work needing those guarantees.

## Alpha.5 explicit existing-pane relocation

`jobs present` now additionally accepts `--relocate yes|no`, default **no**. The existing in-place contract below is unchanged unless yes is supplied. Yes moves the same already placed terminal beside the explicit same-session anchor in a horizontal half-width split, under the existing owner/generation/identity/intent lock. It preserves the block ID and real child PID; it never launches, recreates or closes an agent. Rex carries a focused source's focus, so `--focus no` refuses that source before mutation; explicitly choose `--focus yes` when presentation should transfer it. Detached-agent refusal and all responsibility/uncertainty limits remain. `agents present` composes this locked operation, never an unlocked surfaces bypass. Public jobs14 and combined managed-agent tests exercise cross-tab placement, focus refusal and exact identity preservation on Linux/Mac API13.

## Deliberate presentation, not a workspace takeover

```sh
teerex jobs present --registry /absolute/private/jobs \
  --socket "$SOCKET" --session "$SESSION" --block "$BLOCK" \
  --owner successor --generation "$GENERATION" \
  --reason 'inspect this command result now' --anchor "$ANCHOR_BLOCK" \
  --focus no --label 'review requested'
```

For a **detached command**, `present` uses one `session.move_block` to place only that target in a horizontal 50/50 split after the explicit visible anchor. It never creates/replaces/closes another pane. The anchor's area necessarily changes to make room; the caller deliberately requested that. A zoomed anchor window refuses rather than silently ending zoom. For an **already placed** target, the anchor must be in the same window and the target must be visible in the returned view. The target is presented in place, not moved across windows or rearranged. Optional label and explicitly requested focus are separate supported calls, verified afterward. `--focus no` verifies the active window and existing per-window focused-block identities stayed unchanged; it never tries to restore focus by fighting another client.

A native Rex owner refuses presentation. **Agents must already be placed, non-minimized and not obscured by another zoomed block in the structural view.** A detached or structurally hidden agent refuses registration/adoption/presentation; there is no hidden-agent rescue/launch path, and a command record is not permission to disguise an agent. `visible_in_view` describes returned layout structure, not whether a human has Rex open, the tab is active, or a window is physically on-screen. All agents/workers/sidecars/messages on Joshua's M5/hive still go through the authorized visible Rex/teerex surface. `spawn` remains the launcher. No personal machine is contacted by the test suite.

Before any presentation dispatch, the next generation and bounded reason/intent are atomically saved with `last_action.outcome=uncertain`. The command then performs one supervised Rex/Lua invocation. After a verified result/refusal it saves the outcome. Lost acknowledgements, a deadline, cancellation, SIGKILL, a crash or a failed postcondition can leave partial or complete presentation changes. **No retry, rollback, automatic close or inverse layout operation occurs.** A missing local attempt marker is not proof no mutation ran. Read the latest registry and inspect the exact target before deciding to request another generation. Even verified placement/label/focus is not task completion, permission, isolation or exclusive control; another client may immediately change it. Preflight checks and mutations are not an atomic lease.

## Private state and explicit limits

- Registry directory: already-existing, owned by the current UID, exact mode **0700**, final component not a symlink. Files: owned, single-link regular files, exact mode **0600**, opened without following final symlinks. Parents, ACLs, mounts and same-account/root access are not a confidentiality or sandbox guarantee; use a trusted private local location.
- One stable `lock` file uses nonblocking advisory `flock`, held across read/check/write/live operation. Busy registries fail, never wait indefinitely or steal/delete a lock. This assumes cooperating processes and local filesystem lock/rename/sync semantics; it is not a distributed lock. A crashed process releases its OS lock. SIGKILL can leave an owned Rex transport client until it exits; that does not become a daemon or authority to kill arbitrary processes.
- `state.json`: schema1, maximum **32 entries / 262144 bytes**. No eviction or auto-forget. The registry retains purpose/owner/target/source/deadline and one latest action/reason, not an append-only history. It saves no screen text, raw output, argv, credentials, environment or process inventory. Explicit free text and target/host identities can still be private. Stdout is unredacted JSON; save it deliberately.
- Updates write one exclusive **`state.next`**, sync its file, rename over `state.json`, then sync the directory. Normal write failures remove only the newly created staging file. A crash can leave at most one staging file created by this item; it is never overwritten or automatically promoted. Existing `state.next` blocks all saves without destroying the last committed state. `list`/`inspect` can still read committed state. For recovery, an operator must retain the staging file privately, inspect exact resources, and reconcile/remove the staged write while no jobs operation is active. Treat committed `state.json` as authoritative, not a staged success claim. Disk/fsync failure after rename can still yield uncertain persistence; inspect before retrying.
- Labels/owner: **1–128 UTF-8 bytes**; purpose/reason: **1–256**. Control bytes refuse. Full lowercase UUID addresses, absolute paths, unknown/repeated/missing options and operation-specific flags are checked before Rex contact. Review deadlines are absolute future Unix milliseconds, at most **30 days** ahead; they depend on the CLI host's wall clock, not a monotonic remote process timer. Existing expired records remain inspectable, never silently renewed.
- Live transport: **100–60000 ms**, default **5000**, plus shared bounded owned-client cleanup and scheduling/OS/output waits. Four bounded frames and an **8192-byte** pending frame buffer; individual Lua API responses are rejected above **128 KiB after decoding/encoding** (not a server-side allocation cap). Inherited `REX_SERVER/SESSION/BLOCK/CLIENT` hints are removed; every call selects the endpoint/session with autostart disabled. The trusted Rex executable/configuration and server remain authoritative. A forwarded socket and host labels are not physical-locality proof or authentication.

Every ordinary result is one JSON object. Check process status too: **0** requested record/evidence verified; **1** error/refusal/uncertainty; **2** usage (normally no JSON); **124** deadline; **130/143** INT/TERM. `task_completion=not_assessed`, `all_processes_verified_gone=false`, `exclusive_control=false`, `deadline_enforced=false` and owner-liveness unknown remain explicit. Local filesystem errors do not prove a remote effect did or did not happen. There is no process-tree stop operation, background reaper, enforced ownership, native renderer, isolation or input injection here.

Live failures retain specific launch/collector errors or Lua refusal reasons; otherwise `failure_reason="rex_transport_incomplete"` replaces a null reason, even for exit 0 with missing/partial frames. `backend_term` records the Rex **client's** tagged termination (for example `{"Exited":7}` or `{"Signal":15}`), not the tracked program's exit. It is null when launch/collection failed without a termination receipt. When supervision returns a result, failures print at most **4096 retained raw stderr bytes** with a `teerex jobs: Rex backend:` prefix. This may be a truncated, unredacted prefix, not a complete log; do not publish real diagnostic text without review. Source/observation/attempt frames already received survive later transport failure. Diagnostics do not prove an absent target is dead, make presentation retry safe, pin the Rex executable, or certify mixed-host transport.

## Build and verification

Zig **0.15.2**, exact source baseline **v0.1.0-alpha.3 / 8b2827860029e30a3ad5724d357655de155520d5**. Before shared integration, build the test bridge from the repository root (use `aarch64-macos` on a disposable Apple-silicon Mac, or `x86_64-linux-musl` on Linux):

```sh
zig fmt --check items/jobs
zig build-exe -O ReleaseSmall -target x86_64-linux-musl \
  --dep rex_jobs -Mroot=items/jobs/test_cli.zig \
  --dep supervised_child -Mrex_jobs=items/jobs/main.zig \
  -Msupervised_child=src/child.zig -femit-bin=/absolute/private/jobs-test-cli
TEEREX_BIN=/absolute/private/jobs-test-cli REX_BIN=/absolute/test/rex \
  python3 items/jobs/test_jobs.py -v
```

The test bridge accepts the same `jobs` subcommand as the integrated CLI. Tests create only private `/tmp/tjobs-*` servers with `/dev/null` configuration and restore disabled, and terminate their own fixture server afterward. There is no personal server restart, setup/configuration change or pane destruction. Deliberate fixture SIGKILL controls explicitly clean their own transport process groups; tracked test terminals are left for their disposable server to stop.

**13 checks passed on 12 November 2026** on Debian 13/Linux x86_64 kernel 6.1.189+ and disposable arm64 macOS **27.2**, using checksum-verified Rex **preview.16/API13**, commit `aa2db1b21261b479a550559fb70e2c3a66c07ba2`. They exercise actual live target identity/placement/last-exit and actual move/label/focus calls, offline persistence, generation/owner handoffs including forget/re-register ABA, hidden-agent and native-owner refusal, missed/stale targets, private files/symlink/hardlink checks, lock contention, capacity/corruption/staged-crash refusal, lost real presentation receipts without retry/rollback, deadline/INT/TERM and owner-SIGKILL durable intent. Stale-server identity is injected into a saved record, not tested by restarting an existing server. Placement/label/focus are verified via real Rex structural APIs, not a graphical Rex client rendering or proof a human sees the window. API10–12, personal M5/hive behavior, hardware-crash durability, throughput/energy benchmarks and filesystem/network/credential isolation are not certified.

**Diagnostics repair validation, 12 November 2026 (now shipped in alpha.5):** the expanded **14-check** suite passed against official checksum-verified preview.16/API13 on disposable Linux x86_64 and arm64 macOS **26.3.1**. The new transport-fault regression fails against the published alpha.4 Linux binary (matching release SHA256) because its failure reasons are null. It checks missing/nonexecutable clients, nonzero exit with/without stderr, exact 4096-byte prefix retention from a longer diagnostic stream, signal termination, empty/partial receipts, and real nonexistent-session diagnostics. Extended real presentation tests retain source/observation/attempt evidence across nonzero exit and malformed output while keeping durable uncertainty and generation protection; deadline/INT/TERM/SIGKILL controls remain. Separate disposable Mac API10/12 probes still return the exact documented API13 refusal, backend exit0, and no saved entry. Native Linux/Mac builds, the Apple-silicon cross-build, formatting and all four direct supervisor tests pass. This does not repair or certify mixed-host routing, implement executable pinning/provenance, or reproduce the exact personal M5 report.

The original leaf checkpoint built the unchanged shared alpha.3 CLI plus its jobs bridge and passed four supervisor tests. Combined jobs dispatch, CI and packaging subsequently shipped in alpha.4 and are retained in alpha.5; [current release evidence](../../docs/releases/v0.1.0-alpha.5.md#verification) is separate from that earlier checkpoint. Historical scores/planning, deferred non-Rex work, licensing and Rex distribution remain unchanged.
