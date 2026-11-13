# agents — visible profiles, protocol gate and responsibility

**Experimental managed launch ships in current alpha.5; full agent-core migration remains incomplete.** Use [current setup](../../docs/concierge/setup.md) and the [alpha.5 release support guide](../../docs/releases/v0.1.0-alpha.5.md). This module is built into the combined CLI, not an independently packaged cartridge or a recipe requiring users to assemble spawn/send/jobs. Dated leaf validation below remains distinct from released-byte evidence. The root spelling is `teerex spawn --profile NAME --profiles ABS ...`; it maps to `teerex agents launch --config ABS --profile NAME ...`. Legacy `spawn ... -- ARGV` remains a low-level visible-terminal operation: it does **not** perform protocol ACK gating, automatic jobs tracking or these alerts.

## Who / What / When / Where / Why / How

- **Who:** the operator or an authorized starter, explicitly responsible for a profile's program and selected pane. A recorded owner label is responsibility, not authenticated authority or an input lease.
- **What:** create one retained visible tab, register its jobs responsibility before starting the harness, supply only the messaging protocol as its initial prompt argument, await an explicit token-and-pane-bound agent ACK, then attempt the task brief once. A visible in-pane supervisor waits for its immediate child and attempts notifications automatically; optional harness callbacks report idle/error turns separately.
- **When:** use managed launch for a new agent, `inspect` for saved evidence, explicit `deliver` after a late ACK if no brief was attempted, and `present` when deliberately bringing a pane beside the seat. Never re-run launch because an ACK was lost: creation or input might already have happened.
- **Where:** Linux x86_64 and Apple-silicon macOS, Python **3.9+**, an installed teerex and trusted Rex client, existing API13 server/session, command-host-local private registry and absolute executable/cwd paths. The supervisor and registry must be accessible on the pane's execution host. The [source-only extensions below](#source-only-compute-routing-and-scoped-delivery-issues14-and21) add explicit unfenced SSH compute and separately tested local fenced delivery; alpha.5 assets do not include them. CLI host, server and attached terminal host are not interchangeable. Root named-host routing executes the leaf on the selected command host; it does not make these addresses arbitrary cross-host reply routes.
- **Why:** a visible creation ACK is not readiness; terminal input immediately after creation races shell/harness startup. The initial protocol is therefore an explicitly supported **final prompt argv argument**, never a startup-delay guess or a screen-scraped readiness heuristic. Only the agent's explicit ACK opens the brief gate.
- **How:** configure explicit profiles/default targets once, inspect them, then use one managed launch command. Opt-in shell functions can make the profile's name the launch command without editing global shell/security settings.

## Configure deliberately

Create an operator-selected private directory (`0700`) on a trusted local filesystem. This item does not create the directory or select a personal endpoint. Configuration uses schema1, an object of profiles, and optional explicit defaults:

```json
{
  "schema_version": 1,
  "defaults": {
    "registry": "/absolute/private/agents",
    "socket": "/absolute/existing/rex.sock",
    "session": "session:01234567-89ab-cdef-0123-456789abcdef",
    "starter_session": "session:01234567-89ab-cdef-0123-456789abcdef",
    "starter_block": "block:fedcba98-7654-3210-fedc-ba9876543210",
    "host": "configured-host-id",
    "cwd": "/absolute/workspace",
    "owner": "operator",
    "purpose": "review the requested change",
    "review_after_ms": 3600000
  },
  "profiles": {
    "claude": {
      "argv": ["/absolute/bin/claude"],
      "standing_flags": ["--dangerously-skip-permissions"],
      "harness": "claude",
      "protocol_mode": "argument",
      "hook_events": true
    },
    "codex": {
      "argv": ["/absolute/bin/codex"],
      "standing_flags": ["--dangerously-bypass-approvals-and-sandbox"],
      "harness": "codex",
      "protocol_mode": "argument"
    },
    "pi": {
      "argv": ["/absolute/bin/pi"],
      "harness": "pi",
      "protocol_mode": "argument"
    }
  }
}
```

These are **explicit examples of Joshua's requested standing flags**, not silently installed security changes or certified harness adapters. Review the actual harness's interactive prompt-argument semantics and flags. The first argv must be absolute; each configured standing flag is appended exactly once by exact-argument comparison. `protocol_mode:"argument"` is required; the launcher supplies no task text in that initial argument. Profile argv is trusted operator configuration, not parsed for hidden initial tasks or harness-specific prompt options. Do not put a task in profile argv. `resume_session_id` can be explicit metadata with an operator-authored resume argv, but generic resume/recovery is **not proven**.

`hook_events:true` currently supports only an explicit `harness:"claude"` profile with no conflicting `--settings` argument. It adds **per-launch** settings for Stop/StopFailure command callbacks; it never writes a personal Claude settings file. Actual paid-harness stop-hook execution remains a migration acceptance gate; tests exercise the same callback command with synthetic hook JSON. Codex/pi and preserved custom shell-function runners do not yet have certified automatic idle/error hook adapters. Immediate-child termination reporting applies to every profile, independent of turn hooks.

`report_to_session`/`report_to_block` default explicitly to the configured starter when omitted. Starter and report-to may name different panes **on the same selected server**; both are notified, with an exact-tuple duplicate sent once. Distinct starter/report-to panes and different report-to sessions on the same server are tested through the combined CLI. The initial different-session regression exposed an unjoined Lua control stream; shared spawn now explicitly attaches the supplied report session before inspecting its terminal. This attachment is not a cross-host route or an input lease. All target/starter/report-to tuples use the selected `host` and Unix endpoint. This is not arbitrary cross-host report-to support. Add `store:"/absolute/private/boards"` for the integrated boards store: launch publishes an explicit fleet report with owner/purpose and state `unknown`; Stop publishes a harness-reported `idle`; errors and immediate-child exits publish `unknown` with their exact evidence, never inferred `dead`/`completed`.

## One managed launch and optional one-word shell names

```sh
teerex agents profiles --config /absolute/private/profiles.json
teerex spawn --profile claude --profiles /absolute/private/profiles.json \
  --name review-worker --brief-file /absolute/private/task.md
# Equivalent leaf spelling:
teerex agents launch --config /absolute/private/profiles.json --profile claude \
  --name review-worker --brief-file /absolute/private/task.md
```

Launch overrides: `--registry`, `--socket`, `--session`, `--name`, `--cwd`, `--starter-session`, `--starter-block`, `--report-to-session`, `--report-to-block`, `--host`, `--owner`, `--purpose`, `--store`, `--brief-file`, `--review-at` (future Unix milliseconds, at most 30 days), and `--ack-timeout-ms` (100–60000, default10000). Every target ID is full canonical lowercase. No active pane or environment hint selects a target. `--host` at the leaf is tuple metadata; use root `--config TARGETS --host NAME ...` for actual named-host routing, not this leaf flag. Root injects exact command-host socket/host/store; file paths belong to that host, not the caller's machine.

With no `--brief-file`, the profile gets the protocol and the same ACK gate but no task submission. Outside any Rex pane, the operation still creates a new visible tab using **the configured existing session and starter**. Automatic selection/creation of an unknown session/starter is not implemented. A stale preset refuses or remains uncertain rather than guessing another destination.

```sh
teerex agents shell --config /absolute/private/profiles.json
```

This prints Bash/zsh functions such as `claude()` that call managed launch with that config. Review and source the output deliberately to type `claude --brief-file ABS`. Nothing is automatically sourced, installed into PATH, or written to `.zshrc`/personal security settings. Existing functions are preserved with a warning and the wrapper is skipped. This is safer than overwriting them, but **not parity with agent-core's saved-function call-through behavior**; skipped functions do not magically become managed launches. Binary names are shadowed only if the operator explicitly sources the generated functions. Positional harness argv is intentionally not a launch interface: it could inject a brief before the protocol gate.

## Addresses and gate evidence

The supervisor runs as the retained program in the created visible Rex terminal; it is not a hidden watcher. It will not start the harness until the creation location is verified, jobs tracking succeeds, and the protocol file is durable. It exports:

- Own address: `AGENT_SESSION`, `AGENT_PANE`, plus `LC_AGENT_SESSION`, `LC_AGENT_PANE`, `LC_REX_SESSION`, `LC_REX_BLOCK`.
- Selected name: `AGENT_NAME`, `LC_AGENT_NAME`.
- Explicit starter: `AGENT_STARTER`, `LC_AGENT_STARTER` as `session:UUID block:UUID`.
- Report-to: `AGENT_REPORT_TO`, `LC_AGENT_REPORT_TO`, same two-address string format.
- Local lifecycle reference: `AGENT_REGISTRY`, `AGENT_LAUNCH_ID` and their `LC_` forms.

Exporting LC variables does not configure SSH SendEnv/AcceptEnv, routing, authentication or shared registry storage. The launcher's client PATH and inherited root `TEEREX_INTERNAL_REX` pin are retained privately for later teerex notification clients; no personal/global PATH is edited and the harness's PATH is not rewritten. Root owns executable pinning/provenance; the leaf does not invent an alternate Rex resolver.

The protocol contains the exact `agents ack --registry ABS --launch-id HEX --token HEX --session FULL --block FULL` command. ACK requires the stored token and exact target tuple on that command-host registry, only while expected. Token+address matching is a cooperative protocol gate, **not authentication against same-account code that can read/edit the private record**. ACK proves the explicit acknowledgement was recorded, not harness readiness, task permission, safe input, consumption or future availability.

The brief's irreversible **attempt flag is saved before** one send invocation. `brief_submitted` means only send's paste+Enter events were acknowledged; it is not application consumption or completion. No draft clearing/restoration, input lease or screen-based ACK exists. Use a dedicated agent terminal; other clients/human typing can still race the submission. `agents deliver --registry ABS --launch-id HEX` is an explicit late-ACK continuation only while the gate is satisfied and the brief has never been attempted. Once attempted, even a missing/failed receipt refuses a second attempt.

`protocol_ack_timeout` exits124 and leaves the visible pane and saved intent intact; it neither silently retries nor kills/closes a possibly running agent. `inspect` is offline metadata, not liveness. Creation/refused/uncertain receipt details stay in private state; a lost creation ACK may leave one visible supervisor pane, but no unverified hidden harness is started or automatically adopted.

## Stops, exits and deliberate presentation

```sh
teerex agents inspect --registry /absolute/private/agents --launch-id HEX
teerex agents stop --registry /absolute/private/agents --launch-id HEX --event-file -
# Supply one bounded Stop/StopFailure JSON object then EOF; per-launch hooks do this automatically.
```

A Stop hook means **reported idle turn**. It carries `last_assistant_message`, or the most recent assistant text among the final200 lines/256KiB of an explicit transcript; missing/unreadable last words are stated. StopFailure means **reported error**, with up to600 error characters, not verified process death. A hook cannot manufacture `immediate_child_term` evidence. Explicit `--event-id HEX32` can identify a specific callback invocation; duplicate attempts refuse. Without it each invocation is distinct, even when two turns have identical last words. Notifications are once-attempt per event, to starter and report-to, and preserve unresolved delivery. The command does not swallow failures as success.

The supervisor inherits the terminal's stdio, waits for its **own immediate child**, saves the actual exit/signal or launch error, emits OSC7501 program status and attempts an automatic exit alert with the last available harness report. Termination of that child is not proof descendants stopped or a task finished. SIGINT/TERM are forwarded only to that immediate child; no unverified PID/process-tree stop operation exists. A wrapper SIGKILL/crash, server failure, inaccessible registry or failed notification transport can leave an unresolved event and **cannot guarantee an automatic death alert** without a separate live authority. No invisible reaper is installed. Missing panes, silence, expired review dates, last_exit from unrelated retained Rex programs and lost connections are never promoted to death evidence.

Integrated presentation (requires alpha.5 jobs relocation):

```sh
teerex jobs list --registry /absolute/private/agents
# Use the CURRENT jobs owner and generation from that registry, not cached launch metadata.
teerex agents present --registry /absolute/private/agents --launch-id HEX \
  --owner operator --generation CURRENT --reason 'review the retained result' \
  --anchor block:fedcba98-7654-3210-fedc-ba9876543210 --focus yes
```

This delegates `jobs present --relocate yes` with the saved exact target, under jobs' locked owner/generation/identity/durable-intent checks. It does not bypass those checks with an unlocked surface move. The anchor must be in the same session; focus is explicit. Rex carries focus when moving a focused source, so single-pane finished tabs normally require `--focus yes`; `no` refuses such a source rather than silently restoring focus. No new/recreated terminal, close fallback, automatic presentation or retry occurs. Current jobs records remain the responsibility source of truth after an adoption; lifecycle owner metadata is historical. Presentation does not establish that work is finished.

## Private state, budgets and lifecycle

The native leaf execs Python in the same CLI PID; Python and a usable teerex must exist on the command/pane host. Build/install/upgrade use the shared integrated executable; no separate package is claimed. Upgrades leave existing retained supervisors and state alone. Uninstall by stopping use/removing the installed executable through the shared installer; only deliberately owned panes should be closed. Private records/message files are intentionally retained for reconciliation and are not automatically deleted with the binary.

The explicit registry is an existing owned directory, exact0700, no final symlink. Its stable `agents.lock` and records are owned single-link regular files, exact0600 with final symlinks refused. Cooperating commands wait at most2 seconds for the lifecycle lock; **this is lock acquisition, not a retry of a remote creation/input/notification**. Jobs uses its separate lock in the same directory. Parents/ACLs/root/same-account access are outside this confidentiality boundary; use a trusted local filesystem. At most32 launch records and32 jobs entries; each lifecycle record/config is at most256KiB. Messages/hook JSON are at most32KiB; notifications max64 per launch, presentation attempts max32, no eviction. Current source bounds hook/channel stdin through EOF to2 seconds; the earlier alpha.5 hook CLI had only its EOF/byte bound. This input budget is separate from the channel lease and delivery budget.

Each save exclusively creates `agents-ID.json.next`, syncs, renames over the committed record and syncs the directory. Existing staged writes are never overwritten/promoted. Crash/disk/fsync failure can leave uncertainty; keep the committed and staged files privately, inspect the exact pane/jobs, and reconcile while no operation is active. Files contain private argv, paths, token, brief/protocol text and last reports; public normal receipts omit token/argv/brief, but are not a comprehensive redaction system. Do not publish the registry.

The ACK wait budget excludes creation, jobs, subprocess cleanup, filesystem/scheduling and stdout waits. Each foreground teerex child invocation has a 10-second client wait, bounded diagnostic reads (4096 bytes), and up to one additional second for the owned native client's cleanup after TERM before a required KILL. The Python controller explicitly installs INT/TERM handlers even when INT was inherited as ignored. No client failure closes the server-created agent pane. Exit0 verifies only the reported stage; 1 refusal/error/uncertainty; argparse usage2; ACK wait124; INT130/TERM143. Always inspect exit status **and** JSON. `agent_readiness`, `task_completion` remain `not_assessed`; `all_processes_verified_gone`, `exclusive_input_lease`, `retry_safe` remain false.

## Source-only compute routing and scoped delivery (issues14 and21)

**Not in published alpha.5.** These are two independent opt-in paths, not permission to remove Rivet's relay or change a personal fence. Profiles without either field retain their local lifecycle. Combining `execution` and `delivery` currently refuses **before pane creation** (`remote_fenced_delivery_not_yet_supported`); no SSH forwarding, socket exposure or general RPC proxy is added.

### Explicit unfenced compute route (#14)

Add these fields to the selected **profile**, retaining its literal agent argv (not an argv beginning with ssh):

```json
{
  "argv": ["/absolute/compute/bin/claude"],
  "harness": "claude",
  "protocol_mode": "argument",
  "hook_events": true,
  "execution": {
    "config": "/absolute/pane-host/targets.json",
    "host": "compute",
    "cwd": "/absolute/compute/workspace"
  },
  "callbacks": {
    "config": "/absolute/compute-host/callback-targets.json",
    "host": "pane-registry"
  }
}
```

- **Who/why:** an operator who already authorizes both strict SSH routes; this is an **unfenced** route with ordinary callback SSH authority, never a worker capability.
- **What/when:** the visible pane still runs the outside supervisor beside its registry; `execution` selects a distinct SSH compute environment. It does not reinterpret leaf `--host`, root `--host`, or schema1 host records. Target/starter/report-to remain full host/server/session/block tuples on the pane server. A separate arbitrary registry host or cross-server report-to is not supported by this topology.
- **Where:** `execution.config` is read on the pane/supervisor host; the named entry's teerex is on compute. `execution.cwd`, profile argv and `callbacks.config` are compute paths; `defaults.cwd` remains the supervisor's pane-host cwd. Registry, brief, protocol and boards paths remain on the pane host. Nothing is implicitly uploaded/shared. Both teerex installations need this source and the shared `targets exec --tty` extension.
- **How:** existing `targets resolve` validates the compute route; existing `targets exec --tty ... -- agents exec --payload BASE64` supplies a bounded JSON payload through the one strict serializer. SSH gets a PTY only for the agent, not for machine callbacks. No copied SSH builder, changed forwarding guard, connection reuse, password fallback or creation retry exists. Raw profile argv starting with ssh/mosh now refuses with an instruction to use `execution`, instead of knowingly mangling the protocol.

The compute adapter derives its actual teerex executable there, validates the callback named host's configured host ID/socket against the explicit pane address, and supplies the protocol as **one final literal argument**. The protocol's ACK and report commands use the compute-local callback config and named registry route. An actual token/address-bound ACK still precedes one brief attempt. Stop/StopFailure commands run a compute-side `agents stop --callback-config ABS --callback-host NAME ...` adapter: bounded stdin/transcript reads happen on compute, transcript paths are stripped, and only event bytes travel over the non-TTY callback. No pane-host registry file is opened on compute.

`agents exited --registry ABS --launch-id HEX --token HEX --session FULL --block FULL --term-json JSON` records the compute adapter's separately measured immediate-child exit/signal report as `remote_child_term`. `immediate_child_role:"ssh_transport"` and `immediate_child_term` describe the **local SSH process**, not the remote agent. A missing exit callback remains unknown even after SSH7/143/255/disconnect; no transport status proves remote death. A token/address-bound callback is cooperative evidence, not host attestation or whole-tree death. Hook and exit alerts still notify both fixed starter/report-to (deduplicating an exact tuple); direct report commands target report-to. Root registered-seat routing and its refusal boundaries remain in force.

### Launch-scoped local fence channel (#21)

Add this field to a local profile only:

```json
{
  "delivery": {
    "directory": "/absolute/private/channel-parent",
    "grants": ["send", "ack", "stop"],
    "max_requests": 16,
    "lifetime_ms": 60000
  }
}
```

- **Who:** the starter deliberately authorizes the listed methods for this launch only. Parent directory must already be owned exact0700 on a trusted local filesystem. Grants must be unique/nonempty and drawn only from send/ack/stop; managed launch requires ack, and configured hooks require stop. Omitted grants confer no authority.
- **What/where:** the **visible outside supervisor itself**, not a second daemon/thread/service, owns `PARENT/LAUNCH_ID/channel.sock` and private `handle.json`. Child env exports `AGENT_CHANNEL` (and `LC_AGENT_CHANNEL`) naming that handle plus the existing launch/address metadata; `AGENT_REGISTRY` and its LC variant are removed. The token lives in the handle, not a raw socket/store/config grant.
- **When:** the grant is usable only after the supervisor opens it and until its monotonic lease, connection count, child exit or supervisor INT/TERM revokes it. Lifetime is 1000..86400000ms and no later than review_at; request limit is 1..64 **accepted connections**, including malformed/wrong-token attempts. Unused capacity does not keep it alive after the lease or child exit.
- **How:** the operator's fence adapter mounts **only this launch directory**, preferably read-only, at its original absolute path. A Unix socket is connectable through the tested read-only bind mount; the worker writes no mailbox files. Keep Rex socket, registry, boards store, other launches, SSH keys and host config outside the fence. The binary/toolchain and worker cwd are separate deliberate mounts. The profile does not construct or weaken the fence for you.

```sh
# Supply message bytes on stdin, then EOF; pick a fresh ID for each new message.
teerex agents channel --handle "$AGENT_CHANNEL" --request-id 0123456789abcdef0123456789abcdef \
  --operation send --to report-to --message-file -
# Generated protocol uses the same handle for ACK plus the exact own --session/--block.
# Generated Stop/StopFailure hooks use operation stop and --event-file -.
```

Only send accepts `--to starter|report-to`/`--message-file`; ACK accepts only own full session/block; Stop accepts only event-file. All require handle and request-id. Irrelevant flags, unknown/duplicate frame fields, wrong tokens/launch IDs, arbitrary destinations/methods, invalid message controls/UTF-8 and oversize frames refuse. Worker Stop reads a transcript only inside its own fence and strips its path; the outside handler refuses transcript paths rather than opening worker-selected host files.

The channel admits at most one request at a time, backlog4, at most20 accepted connections/second, 49152-byte newline-delimited JSON frames and 32768-byte messages/events. Frame acquisition has a total0.5-second deadline; CLI stdin needs EOF within2 seconds, with the same32KiB cap. A send retains the existing ten-second foreground-client budget and original nested send/seat/refusal receipt; the client bounds its connect/write/response waits to12 seconds each. Notifications, history and state retain the existing finite registry budgets; direct channel sends create at most64 bounded message files, with hook notices subject to the existing notification cap, not a worker-writable spool. Durable request intent precedes any send. Duplicate/concurrent IDs refuse, even after a dropped response; `retry_safe:false` always. An unresolved response is `delivery_uncertain_no_retry`, never an instruction to reconnect/replay. Inspect the private registry outside the fence to reconcile it.

Lease/revocation stops **new admission**; it does not undo input or cancel an already dispatched send. Socket/handle are removed through the pinned launch directory on normal teardown; substitution never triggers recursive deletion or following symlinks. SIGKILL/crash may leave inert files, but no independent servicing process remains. A filesystem bearer capability is not kernel revocation, authentication against arbitrary same-account host code, or proof descendants stopped. If a worker can access other launches/host sockets through a bad fence mount, these files do not repair that sandbox. **Linux bubblewrap acceptance is tested; macOS fence/channel equivalence is not certified.**

### Source acceptance and remaining cutover

On disposable Linux x86_64, Zig0.15.2, Rex preview.16/API13, all **17** public lifecycle tests passed with the shared `targets exec --tty` patch. Run `TEEREX_AGENTS_SSH=1 TEEREX_AGENTS_FENCE=1 TEEREX_AGENTS_INTEGRATION=1 TEEREX_AGENTS_CROSS_SESSION=1 TEEREX_BIN=ABS REX_BIN=ABS python3 items/agents/test_agents.py -v`. SSH/fence gates require working OpenSSH server/client/keygen, Linux bubblewrap namespaces and no personal endpoints; omitted gates explicitly skip, not pass.

The SSH test uses two real ephemeral SSH endpoints and a separate compute mount namespace where the pane registry and Rex socket are absent. It checks a quoted executable path, callback config with spaces, empty/Unicode/quote/newline argv, preserved protocol, wrong token/address, real ACK before one exact brief, late continuation once, compute-local transcript Stop/StopFailure, exact starter/report-to replies, measured exit7, lost exit callback and SSH255 remaining unknown. This is not the old same-server cross-session test.

The independent real bubblewrap test masks /tmp, /run and /var, denies direct Rex socket and registry access, then permits the scoped ACK, one exact multiline/trailing-newline report and configured Stop hook through only the read-only launch directory. Further cases cover malformed/oversized/duplicate frames, invalid targets/tokens/launch IDs, duplicate/lost response without resend, EOF budget, symlink refusal, expiry/count/INT/TERM teardown, seat append with zero PTY input and original store refusal without paste fallback. Synthetic hooks are not paid-harness certification; isolated environments are not two physical hosts or personal M5/hive validation.

Rivet `jobs/src/relay.ts` explicitly grants its configured command to otherwise read-only workers; `jobs/src/sandbox.ts` currently adds a **shared** configured relay mailbox to writable fence paths. `jobs/sandboxes/bwrap.ts` uses explicit toolchain/cwd mounts and masks /tmp,/run,/var. Source was inspected, not personal service configuration. A migration must replace that shared mount/command with the per-launch grant without broadening any harness/git/native-owner guard. Actual Rivet adapter integration, remote fenced compute transport, macOS parity and authorized relay cutover remain open. **Retain agent-relay.service, its callers and all working guards until that parity is proven.** `run-visible` can later compose literal supervisor argv and scoped env for the same lifetime; no second service or extra run ABI is required here.

## Verification and migration gates

`TEEREX_AGENTS_INTEGRATION=1 TEEREX_AGENTS_CROSS_SESSION=1 TEEREX_BIN=/absolute/teerex REX_BIN=/absolute/rex python3 items/agents/test_agents.py -v` starts only private disposable Rex servers with `/dev/null` config and restore disabled. All **12** final combined checks passed on Linux x86_64 and native-built macOS26.3.1 arm64 with Zig0.15.2 and checksum-verified Rex preview.16/API13 (`aa2db1b21261b479a550559fb70e2c3a66c07ba2`), including cancellation cleanup and cross-session report-to. The standalone bridge intentionally skips three combined-only cases; those skips are not passing evidence. Final packaged identities and released-byte acceptance belong in the versioned release guide. The synthetic interactive fixture independently consumes the protocol argument, runs the actual ACK CLI and captures exact brief PTY bytes. Cases include AGENT/LC metadata, automatic jobs owner/purpose/review, duplicate flags, timeout/wrong-token/wrong-pane gates, late ACK continuation, retained exit7/SIGTERM notifications, idle versus reported failure, bounded transcript fallback, function preservation, private-directory refusal, and dropped real creation/brief receipts after actual Rex effects without retry/close.

These are not real Claude/Codex/pi prompt/hook tests, graphical Rex UI validation, API10–12 managed-launch certification, arbitrary attached-host routing, harness resume, a whole-tree death proof or Joshua's personal M5/hive validation. The source test bridge deliberately leaves shared integration to its owner. Integrated Linux acceptance additionally proved named-local managed-spawn alias routing with a poisoned PATH and exact configured Rex pin, typed fleet owner/purpose with `unknown` exit state, a registered seat's exit alert appended with zero terminal input, failed fleet-store refusal before harness start, and explicit finished-pane relocation with no-focus refusal followed by consented focus and preserved block IDs. Run these two additional cases with `TEEREX_AGENTS_INTEGRATION=1`; the standalone bridge skips them explicitly. The public cross-session regression (`TEEREX_AGENTS_CROSS_SESSION=1`, `AgentsTest.test_cross_session_report_target_independently_visible_then_managed_launch`) independently verifies the report pane exists and now passes after the explicit report-session attachment fix. Combined CI enables both integration gates; a standalone skipped gate is not passing evidence.

See [agent-core migration gates](agent-core-migration.md) before deleting stopgaps. No agent-core source, personal shell, security settings or running personal server was changed. Rex remains separately obtained proprietary software and is not bundled; teerex licensing remains [unselected](../../RIGHTS.md).

### Native send draft guard (source follow-on #4)

Notifications, automatic exit alerts, delivered briefs and scoped-channel sends all call native `send`, whose default now preserves parsed operator drafts. Native sends may wait30s for typing (configurable up to55s), then clear/send/restore without submitting the draft. See the [exact send contract and race limits](../send/README.md#default-draft-guard---draft-guardignore). Send subprocesses allow120s, channel responses and Stop/callback wrappers250s for two destinations; receipt ACKs still do not prove application consumption. The typed protocol itself does not bypass this guard.
