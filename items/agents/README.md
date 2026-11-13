# agents — visible profiles, protocol gate and responsibility

**Experimental managed launch ships in current alpha.5; full agent-core migration remains incomplete.** Use [current setup](../../docs/concierge/setup.md) and the [alpha.5 release support guide](../../docs/releases/v0.1.0-alpha.5.md). This module is built into the combined CLI, not an independently packaged cartridge or a recipe requiring users to assemble spawn/send/jobs. Dated leaf validation below remains distinct from released-byte evidence. The root spelling is `teerex spawn --profile NAME --profiles ABS ...`; it maps to `teerex agents launch --config ABS --profile NAME ...`. Legacy `spawn ... -- ARGV` remains a low-level visible-terminal operation: it does **not** perform protocol ACK gating, automatic jobs tracking or these alerts.

## Who / What / When / Where / Why / How

- **Who:** the operator or an authorized starter, explicitly responsible for a profile's program and selected pane. A recorded owner label is responsibility, not authenticated authority or an input lease.
- **What:** create one retained tracked tab (or an explicitly selected detached terminal), register its jobs responsibility before starting the harness, supply only the messaging protocol as its initial prompt argument, await an explicit token-and-pane-bound agent ACK, then attempt the task brief once. A visible in-pane supervisor waits for its immediate child and attempts notifications automatically; optional harness callbacks report idle/error turns separately.
- **When:** use managed launch for a new agent, `inspect` for saved evidence, explicit `deliver` after a late ACK if no brief was attempted, and `present` when deliberately bringing a pane beside the seat. Never re-run launch because an ACK was lost: creation or input might already have happened.
- **Where:** Linux x86_64 and Apple-silicon macOS, Python **3.9+**, an installed teerex and trusted Rex client, existing API13 server/session, command-host-local private registry and absolute executable/cwd paths. The supervisor and registry must be accessible on the pane's execution host. The [source-only extensions below](#source-only-compute-routing-and-scoped-delivery-issues14-and21) add explicit unfenced SSH compute and separately tested local fenced delivery; alpha.5 assets do not include them. CLI host, server and attached terminal host are not interchangeable. Root named-host routing executes the leaf on the selected command host; it does not make these addresses arbitrary cross-host reply routes.
- **Why:** a visible creation ACK is not readiness; terminal input immediately after creation races shell/harness startup. The initial protocol is therefore an explicitly supported **final prompt argv argument**, never a startup-delay guess or a screen-scraped readiness heuristic. Only the agent's explicit ACK opens the brief gate.
- **How:** configure explicit profiles/default targets once, inspect them, then use one managed launch command. Opt-in shell functions can make the profile's name the launch command without editing global shell/security settings.

Numeric CLI ranges use compact `MIN..MAX` help labels. Non-integers and out-of-range values return a short usage error (exit 2); defaults and inclusive limits are unchanged.

## Concurrent launch queue (source follow-on)

`agents launch --launch-wait-ms N` waits **0..60000 ms**, default **60000**, for the selected registry's dedicated `launch.lock` before saving launch intent or creating a pane. The existing private0700 directory and owned, single-link, no-follow0600 lock checks apply. The lock serializes spawn, native jobs tracking, fleet reporting and protocol preparation. It is released **before waiting for the agent's ACK** or delivering the brief. This is cooperative serialization on that local registry, not FIFO fairness, an input lease or a distributed queue. Existing `agents.lock` still protects short state updates with its2s wait; it is not held across network calls or the ACK wait.

Queue timeout returns exit1, `outcome/failure_reason:launch_queue_busy`, `retry_safe:true`, `creation_attempted:false`, `created:null`; no lifecycle record or pane has been created by that invocation. Zero wait tries once. The stable lock file remains and is never stolen/deleted; a crashed holder releases its OS lock. Every pane creation remains a **single attempt**. Unexpected errors after creation retain the existing uncertain receipt/known target rather than retrying or automatically closing it.

Native jobs exclusive operations now wait up to10s before reading or mutating state; their registry-busy result is retry-safe only because no live operation or record mutation began. Agents jobs-call subprocess budgets cover that wait plus the live query/cleanup budget. The in-pane supervisor allows60s for verified tracking/protocol preparation (and stops early on explicit tracking failure), separately from the caller-selected ACK deadline. Default relative review deadlines are calculated after queue acquisition. The queue does not keep a daemon running or retry work on its own.

## Retiring finished launches: `agents prune`

The registry holds at most 32 live launch records. `teerex agents prune --registry DIR` plans (changes nothing) and `--apply` acts. A record retires only on evidence, never on age alone:

- `agent_exited`: the in-pane supervisor recorded the agent's exit (`immediate_child_term`).
- `never_started`: the launch ended `creation_uncertain` or `tracking_uncertain`, so no agent ran.
- `pane_gone`: `surfaces inspect` reports the pane absent from its session (`pane_not_attached_terminal`). Any other answer, including an unreachable server, keeps the record. Its jobs registration is forgotten too (local record only).

Records younger than 120 s are never judged, so a launch still in its queue/spawn/track window is untouched. Retired records and their brief/protocol/notice files move to `DIR/archive/<launch_id>/` (0700) with a `retired.json` stating reason, evidence and time; message files whose record is gone move to `DIR/archive/orphans/`. Nothing is deleted, no pane is closed and no process is signalled. Prune holds the launch queue lock, so it never races a launch.

`agents launch` runs the same prune automatically, under its queue lock, whenever 24 or more live records exist; the receipt's `auto_prune` reports `{retired, live_before}`. `registry_full` now means 32 records that are all live or unknown: retire live agents explicitly.

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
      "protocol_mode": "argument",
      "hook_events": true
    },
    "pi": {
      "argv": ["/absolute/bin/pi"],
      "harness": "pi",
      "protocol_mode": "argument",
      "hook_events": true
    }
  }
}
```

These are **explicit examples of Joshua's requested standing flags**, not silently installed security changes or certified harness adapters. Review the actual harness's interactive prompt-argument semantics and flags. The first argv must be absolute; each configured standing flag is appended exactly once by exact-argument comparison. `protocol_mode:"argument"` is required; the launcher supplies no task text in that initial argument. Profile argv is trusted operator configuration, not parsed for hidden initial tasks or harness-specific prompt options. Do not put a task in profile argv. `resume_session_id` can be explicit metadata with an operator-authored resume argv, but generic resume/recovery is **not proven**.

`hook_events:true` supports explicit `harness:"claude"`, `"codex"`, and `"pi"`; false omits all turn callbacks. These profiles share schema1: absolute `argv`, optional string-array `standing_flags`, `harness`, required `protocol_mode:"argument"`, optional boolean `hook_events`. No extra Pi-specific profile field or global extension install is needed.

| Harness | Per-launch adapter | Verified contract/source |
| --- | --- | --- |
| Claude | `--settings JSON` with Stop/StopFailure/UserPromptSubmit commands; conflicting settings refused | Existing Claude callback contract and disposable synthetic-hook tests |
| Codex | `-c 'notify=[...]'`; Codex appends one JSON argv payload; `agents hook --harness codex --command-json JSON --payload JSON` translates `type:"agent-turn-complete"` and `last-assistant-message` to Stop | Installed `codex --version` = 0.159.2 and `codex --help`; [official advanced configuration](https://learn.chatgpt.com/docs/config-file/config-advanced), fetched 2026-11-13 |
| Pi | `--extension ABS.ts`; private generated extension observes `agent_before_settle` outcome then `agent_settled`, reads the last assistant message on the current branch, sends Stop or StopFailure | Installed Pi1.4.0 `--help`, package `docs/extensions.md` and `dist/core/extensions/types.d.ts`, read 2026-11-13; [upstream extension guide](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md) |

Codex notify exposes turn completion only. No per-launch Codex hooks are injected: their trust-review prompt can prevent protocol ACK. Codex tint resets when guarded send delivers into its pane. See [official hooks documentation](https://learn.chatgpt.com/docs/hooks) and [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference), fetched 2026-11-13. No synthetic failure claim is made. Pi's `agent_end` can precede retries or queued continuations, so it is deliberately not the idle boundary. Aborted Pi settlement reports idle; outcome `error` reports StopFailure. Unfenced generated files stay in the private launch registry and archive with the launch. With scoped delivery, Pi's extension lives beside the exposed channel handle and is removed when the grant revokes; the hidden registry never needs a sandbox mount. Explicit Pi `--extension` works even with `--no-extensions`. These tests execute generated callbacks with synthetic payloads, including the actual generated Pi JavaScript in Node; paid live-harness turn execution is still unproven. CI's existing API13 agents suite includes these tests; Node is required for the Pi extension callback test. Immediate-child termination reporting remains independent of hooks.

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

This prints replacement Bash/zsh functions, such as `claude()`, calling `teerex agents human --config ABS --profile claude`. Source the reviewed output deliberately. Existing functions with the same names are replaced; the previous function is never called through. Type `claude`, `codex`, or `pi` alone: profile standing flags are applied once and a visible tracked tab opens in the configured existing session. Human launch needs no starter, report-to, brief or ACK; no messaging prompt is inserted. It records a normal jobs/lifecycle entry and emits process/turn status, but never sends human-turn text into another pane. `agents launch` retains its protocol/ACK/one-brief contract. For an agent-started task, keep using that explicit verb; shell names now mean human launch.

The human path requires the same explicit registry/socket/session/cwd/host/owner/purpose defaults as managed launch, minus starter/report-to. It accepts launch target overrides, but refuses a brief or explicit starter. It uses `surfaces open --layout tab`, then verified jobs tracking before starting the harness. `human_launched` certifies that creation/tracking/configuration gate, not harness readiness. `execution`/`delivery` are managed-only; human compute routing uses the following optional top-level `human_route` object in profiles.json:

```json
{
  "human_route": {
    "config": "/absolute/local/hosts.json",
    "host": "hive",
    "profiles": "/absolute/on/hive/profiles.json"
  }
}
```

`config` is the existing named-host configuration on the invoking machine; `host` selects its compute entry; `profiles` belongs to that selected host. This reuses `teerex targets exec --tty` for both local and SSH targets, including pinned teerex/Rex paths, strict host-key checks, literal argv and foreground status propagation. No separate SSH transport or kernel-hostname guess is introduced. On the Mac, choose the SSH hive entry; on hive, omit human_route or choose its local entry. The remote call runs `agents human` with profile selection and an internal `--routed` marker that prevents routing loops, using the remote profile's defaults and standing flags. No local paths/config are copied. Remote human launch forwards profile selection only; target overrides belong in the remote config. This route is tested with an actual named-target resolver and literal-argv SSH fixture; physical Mac-to-hive launch remains an installation acceptance check. Nothing is automatically sourced or written to shell startup/security settings.

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

`protocol_ack_timeout` exits124 and leaves the visible pane and saved intent intact; it neither silently retries nor kills/closes a possibly running agent. `inspect` combines saved metadata with a fresh placement read, not task liveness. Creation/refused/uncertain receipt details stay in private state; a lost creation ACK may leave one visible supervisor pane, but no unverified hidden harness is started or automatically adopted.

## Stops, exits and deliberate presentation

```sh
teerex agents inspect --registry /absolute/private/agents --launch-id HEX
teerex agents stop --registry /absolute/private/agents --launch-id HEX --event-file -
# Supply one bounded Stop/StopFailure JSON object then EOF; per-launch hooks do this automatically.
```

A Stop hook means **reported idle turn**. It carries `last_assistant_message`, or the most recent assistant text among the final200 lines/256KiB of an explicit transcript; missing/unreadable last words are stated. StopFailure means **reported error**, with up to600 error characters, not verified process death. A hook cannot manufacture `immediate_child_term` evidence. Explicit `--event-id HEX32` can identify a specific callback invocation; duplicate attempts refuse. Without it each invocation is distinct, even when two turns have identical last words. Notifications are once-attempt per event, to starter and report-to, and preserve unresolved delivery. The command does not swallow failures as success.

The supervisor inherits the terminal's stdio, waits for its **own immediate child**, saves the actual exit/signal or launch error, emits valid [OSC7501](https://www.superlogical.com/rex/docs/build/program-status) program status (`app=teerex-agent`, base64 title/message) and attempts an automatic exit alert with the last available harness report. The supervisor emits `working` when starting the child, `idle` for observed Stop, `error` for StopFailure or unsuccessful child exit, and `done` for exit0. Turn callbacks update the registry; the supervisor emits them on its own terminal, so callback stdout capture cannot hide the status. It does not infer a later turn start from typing or screen content. Termination of that child is not proof descendants stopped or a task finished. SIGINT/TERM are forwarded only to that immediate child; no unverified PID/process-tree stop operation exists. A wrapper SIGKILL/crash, server failure, inaccessible registry or failed notification transport can leave an unresolved event and **cannot guarantee an automatic death alert** without a separate live authority. No invisible reaper is installed. Missing panes, silence, expired review dates, last_exit from unrelated retained Rex programs and lost connections are never promoted to death evidence.

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

### One-shot fence admission (`agents fence-probe`)

Before starting a fenced harness, check the caller-declared resources with the same teerex binary **inside** that fence. This leaf never contacts Rex, opens a pane or starts a monitor. It is a launch-time check, not authentication against unfenced processes running as the same UID. The fence builder and protect file remain trusted; a worker that already ran can change its environment after a probe. Only the listed paths/ports are checked, not arbitrary aliases elsewhere in a mount tree.

Prepare an owned regular0600 JSON template on the host (synthetic example):

```json
{
  "schema_version": 1,
  "absent_paths": ["/absolute/private-control.sock", "/absolute/private-store", "/absolute/sign-in.json"],
  "closed_tcp": ["127.0.0.1:7001", "[::1]:7002"],
  "require_pid_namespace": true,
  "require_new_session": true,
  "required_paths": ["/absolute/launch-channel/channel.sock"]
}
```

Record fresh host identities **outside** the fence for every launch; no hand-maintained inode numbers:

```sh
teerex agents fence-probe --record-identities --protect-file /absolute/template.json --out /absolute/launch/protect.json
```

`--out` is a new absolute file, created exclusively/no-follow0600, flushed before return; existing files refuse. It contains the template plus `host_identities.absent_paths` (each path's `st_dev`/`st_ino`, or null if absent on the host) and, when required, `host_identities.pid_namespace`. Symlinks are followed when identifying objects: a link to the host object cannot masquerade as a copy. Missing host paths are recorded as null; if one appears inside, the probe fails with `state:identity_unknown` rather than inventing its identity. Other recording errors fail closed. Never record from inside the fence or reuse stale per-launch snapshots.

Mount that recorded file read-only, then put the probe before the literal harness argv:

```sh
teerex agents fence-probe --protect-file /absolute/launch/protect.json --evidence-fd 3 --then -- /absolute/harness 'literal argument'
# Check only, without a harness:
teerex agents fence-probe --protect-file /absolute/launch/protect.json
```

Protect files must be owned, single-link, nonsymlink regular files, exactly0600, at most64KiB. Unknown/duplicate fields, relative paths, duplicate list entries, more than64 entries/list, wrong types and nonnumeric/non-loopback TCP addresses refuse. Lists default to empty, booleans to false. There is **no `readonly_paths` list**: a per-call writable sign-in copy may refresh its token.

Checks return separate facts:

- `absent_path`: missing (ENOENT) or inaccessible (EACCES) passes. A present object with the recorded host identity **fails**, even a read-only bind or a socket refusing connections. A different identity passes with `state:shadowed`, allowing a writable per-launch copy. Present objects without an available recorded identity fail. Path checks require the outside snapshot.
- `closed_tcp`: each literal loopback endpoint must refuse (ECONNREFUSED/ENETUNREACH) or time out within500ms. A successful connection fails. Other errors fail closed; ports may be omitted in the caller's per-launch derivative. DNS names are forbidden. These checks neither install egress nor prove public network access.
- `pid_namespace`: the current `/proc/self/ns/pid` must differ from the recorded host namespace. This supports a fresh `/proc` mount, where `NSpid` legitimately has only one value. Missing namespace evidence fails.
- `new_session`: opening `/dev/tty` must fail with ENXIO. This checks the absence of a controlling terminal; it never attempts TIOCSTI on a pane.
- `required_path`: must exist; a Unix socket must accept one bounded500ms connection, immediately closed **without a frame**. This costs one channel admission (and produces a refused/incomplete-frame receipt when logged); budget for it. It is not an agent ACK. Ordinary required files are checked for existence only.

Without `--then`, stdout remains one flushed diagnostic JSON object: `kind:fence_probe_result`, `schema_version:1`, `passed`, `checks` (each has `check`, `target`, `result:pass|fail`, nullable numeric `errno`, plus path state where applicable), and `exec:started|not_started`. Recording adds `recorded_protect_file`. These details include protected paths and must stay private.

With `--then`, the probe writes **nothing to stdout**, on pass or refusal; successful `execvp` replaces it in the **same PID**, and subsequent stdout/exit belongs to the harness. Failed checks produce only `teerex agents fence-probe: refused: CHECK_KIND` on stderr, without targets, identities or counts. Invalid protect input and exec failure likewise use fixed path-free categories. Native call logging retains selected flag names and canonical target IDs, never protected path values; this in-fence probe bypasses the Python call-log wrapper. No retry or fallback runs.

To retain the full JSON privately, the caller opens a private0600 regular evidence file **outside the fence**, passes its writable descriptor through bubblewrap, and supplies `--evidence-fd N`. The path must not be mounted into the worker. N must be an open writable regular-file descriptor **>=3** (standard streams, read-only files, sockets, pipes and directories refuse before protect-file loading or checks). The caller owns file permissions and placement; the probe validates descriptor type/access, not that the path is outside the fence. It flushes and fsyncs the JSON, then closes the descriptor **before exec**; it also marks it non-inheritable as a safeguard. Evidence write failure refuses without starting the harness. With no evidence descriptor, `--then` discards check details rather than exposing them. Diagnostic use with an evidence descriptor writes both that file and the usual stdout JSON. `exec:started` in evidence describes the handoff attempt, not proof that the OS accepted exec; inspect the command exit status too. Without `--then`, exec remains `not_started`.

Exit0: all checks passed (or identities recorded). Exit1: a failed check/exec or invalid/unwritable evidence descriptor, with stderr beginning `teerex agents fence-probe: refused:` and the first failure; the harness is never started on failed checks. Exit2: usage. Exit3: missing/invalid/oversized/nonprivate protect input, missing host baseline or failed identity recording/output. A successfully execed harness controls its own exit status.

The agents suite covers evidence-fd validation, private results, exec closure and path-free output on both platforms. Linux API13 CI additionally runs real fences under `TEEREX_AGENTS_FENCE=1`. Real bubblewrap controls show host socket/store and `/proc/<outside-pid>/root` denial, a host bind rejected versus a writable copy accepted, same-PID handoff, PID namespace teardown of setsid descendants, host-signal exclusion, scoped channel ACK after the required-socket check, and no controlling terminal on a **disposable** PTY. The PTY counterexample attempts TIOCSTI only there; modern kernels may independently deny it (reported as kernel evidence, never relaxed). A disposable slirp4netns egress fixture checks both blocked host loopback and real public HTTPS; it installs no helper/service on the host. CI provisions bubblewrap/slirp4netns; production fence/egress construction remains the caller's responsibility. macOS/Linux parity and a live Rivet cutover are separate checks.

### Session scratchpad

Every `agents launch` and `agents human` creates the pane's fixed Markdown [scratchpad](../scratch/README.md), records `scratchpad` in its private registry and public receipt, and exports `AGENT_SCRATCHPAD` plus `LC_AGENT_SCRATCHPAD` to the harness. The protocol names the file and directs the agent to keep Now/To-do/Done current before and after every step. Profiles accept `intent` (one line; otherwise the brief's first nonblank line or Purpose) and `scratch_pane` (boolean, default **true**). The default opens `teerex scratch watch` in a tiled pane anchored beside the agent. `scratch_pane_opened` and `scratch_pane_receipt` retain observed display results; uncertainty never causes a second creation attempt. Human launches export the same path without adding an unsolicited prompt.

`agents prune --apply` moves a gone pane's scratchpad under `scratch/archive/<session-id>/`, with the same private permissions. An exited child whose pane still exists retains its scratchpad. The Markdown is local to the pane host; a remote compute route carries the pane-host path in metadata and requires an explicit route back to that host to edit it. Fences must deliberately expose the scratchpad if the worker is expected to edit it directly; this change grants no additional filesystem access.


## State tint

Profiles may set `"tint": {"idle":"#2a2013","error":"#2a1414","done":"#142a1a"}`; missing keys use these defaults, and `"tint": false` disables colour writes. Values must be six-digit hex colours. These defaults come from the Rex lead's measured spec `research/rex/specs/teerex-1-5-10.md` (2026-11-13). Stop paints idle, StopFailure and nonzero exit paint error, exit zero paints done; working restores the theme with OSC111. Supervisor OSC7501 reports now use child `id=teerex/tint` (or `id=teerex` with tint disabled), preserving the harness's root record. A successful `send` detects the tinted child record and restores the theme on the pane host, using the same bounded best-effort tty helper as seat status.

Claude UserPromptSubmit and Pi before_agent_start report turn start through the existing hook/channel path; this updates working status without forwarding a stop notification. Pi's event is verified in installed Pi1.4.0 `dist/core/extensions/types.d.ts`. Codex uses its notify callback for settled reports and guarded send for tint reset; it has no injected prompt-start hook. These are per-launch hook additions, with no global configuration edits. Physical Mac painting and paid-harness turns require their own acceptance; disposable fixtures query OSC11 and read program_status.


## Timeline

`teerex agents timeline --registry DIR [--name NAME] [--since ISO|ms] [--json]` reads live lifecycle files and `archive/<launch id>/` without creating registry locks or modifying records. Events are oldest first: launch intent (`launched`, not creation proof), protocol ACK, brief attempt, every Stop/StopFailure with at most 180 characters from its first line, immediate child exit term, and prune. Plain output gives UTC time, name, launch ID, event, session, block and detail; JSON gives `events`, timestamps in milliseconds, and `legacy_partial_launches`. Name matching is exact; since is inclusive and accepts ISO timestamps with timezone or Unix milliseconds.

New saves retain event history in the existing atomic lifecycle record. Older records expose only timestamps and the final hook still present; overwritten hooks and untimestamped brief attempts cannot be recovered. JSON names those partial launches and plain output warns on stderr. The timeline is a snapshot of reported evidence, not live liveness, readiness, consumption or whole-tree death proof. No watcher or daemon runs.

## Tracked detached agents

`agents launch --layout detached` overrides profile `layout: tab|detached` (default
`tab`). Detached launches use API13 `session.new_block` in the selected session;
protocol ACK, one guarded brief, jobs registration, scratchpad and turn reports
remain required. Their scratchpad is created, but its optional side pane waits
until an operator opens it: a detached block has no visible anchor.

`agents inspect` now reads fresh placement (`placed`, `detached`, `absent`, or
`unknown` on unavailable evidence), alongside lifecycle metadata. Launch receipts
include initial `placement` and the selected `layout`. Prune reads the complete
block list: a live detached pane is present, not gone.

Profile `come_forward: true` opts the existing supervisor into placing its own
block on Stop, StopFailure or immediate-child exit. It acts only while detached,
uses the right third beside that session's current focused pane, and never requests
focus or moves an already placed block. No extra watcher is started. An unavailable
anchor or uncertain operation is recorded in `come_forward_last`, without retry.
This is placement, not approval or proof of task completion.


## Scratchpad enforcement at turn end

Managed harness hooks check `Updated` against the private launch record's `turn_started_at`. Prompt-submit starts a new allowance; the initial child start supplies a baseline before the first prompt hook. Missing, invalid or unreadable Markdown is stale. Without `AGENT_SCRATCHPAD` (or `LC_AGENT_SCRATCHPAD`) the hook does not check. All state is private to the launch; nothing is scheduled.

* Claude: generated Stop hooks run through `agents hook --harness claude --command-json JSON --event-file -`. First stale Stop returns `{"decision":"block","reason":"update your scratchpad (Now/To-do/Done) before ending the turn"}` and does not publish idle/last words yet. The second Stop passes even if stale; `last_hook.scratchpad_check` records the stale allowance and the stop report says so. This uses the installed Claude hook-development Stop decision contract (read 2026-11-13).
* Codex: notify is after the turn, so it cannot veto. One stale notification sends the reminder to the agent's own pane through native guarded send, from `teerex-scratchpad`; no registry-store inbox route or automatic retry is used. The send receipt and any failure stay in `scratchpad_check`. No per-launch hooks or trust bypass are added. Notify's `turn-id` renews the allowance for new turns; `input-messages` identifies the reminder-generated continuation so it cannot recursively send itself forever. Notify does not supply an actual start timestamp: freshness uses the previous notify time (initially child startup), and the result explicitly records `basis=previous_notify_or_initial_child_start_actual_turn_start_unknown`. An idle-time edit before a prompt can therefore count; exact Codex prompt-time enforcement is unproven. The fields follow [official advanced configuration](https://learn.chatgpt.com/docs/config-file/config-advanced#notifications), fetched 2026-11-13.

* Pi: `agent_before_settle` checks through `agents hook --harness pi ...`; one stale completed turn returns `continue: true` with a visible custom message containing the reminder. Its next settlement passes. Aborted/error outcomes are never continued by this check. `agent_settled` remains the final report boundary. This follows installed Pi1.4.0 `docs/extensions.md` and extension types' actionable boundary contract (read 2026-11-13).

`agents stop` remains the low-level report transport; the installed harness wrapper adds the enforcement marker only for scratchpad-enabled panes. Scoped channel and explicit compute callbacks carry the same decision back to that wrapper; workers never need direct registry access for the check. Tests drive the generated Pi extension with Node, Claude decision output, and a real disposable Rex self-reminder; they do not run paid model turns.

The unmanaged seat uses the installable settings printed by `teerex scratch hook-settings --teerex ABS`; rexconfig can merge the `UserPromptSubmit` and `Stop` groups into its Claude seat settings. Generation only prints settings and never edits personal configuration.

### Physical two-host compute acceptance

`test_compute_hosts.py PhysicalComputeTest.test_physical_compute_ack_literal_argv_brief_and_measured_exit`
is an opt-in synthetic acceptance test for an actual pane-host/compute-host pair.
It uses only a disposable Rex server and temporary profiles, callback routes,
private call-log directories and fixture files. Configure `TEEREX_BIN`, `REX_BIN`,
`TEEREX_COMPUTE_HOST`, `TEEREX_PANE_HOST`, `TEEREX_HOSTS_CONFIG`,
`TEEREX_COMPUTE_HOSTS_CONFIG`, `TEEREX_COMPUTE_BIN` and
`TEEREX_COMPUTE_PYTHON`. Host configs supply existing SSH identities; no credentials
are copied. Binary/fixture copies are exclusively for tools on the other host.
It verifies literal argv (including empty strings, quotes and newlines), routed
protocol ACK, exactly one brief and measured remote exit 7 without a paid model.
CI discovers the explicit test but skips physical estate access unless enabled.
