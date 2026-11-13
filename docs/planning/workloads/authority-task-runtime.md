# H04 authority/isolation and H05 task contracts/interruption (implementation-ready spec)

**Conclusion.** The smallest enforceable boundary for Rivet's fenced coding workers on hive is the bubblewrap fence Rivet already has, plus the launch-scoped channel from teerex #21. It needs three hardening changes and one per-launch proof:

1. A **private PID namespace**. Measured on hive: today a fenced worker can signal any same-UID process, and a daemonized child outlives the fence.
2. A **private network namespace with outbound-only egress** (`slirp4netns --disable-host-loopback`). Measured on hive: today a fenced worker reaches every loopback service, including the Rivet engine and the browser DevTools forward from the M5.
3. **`--new-session`** for non-interactive calls, so a worker cannot inject keystrokes into the pane's terminal.
4. **`teerex agents fence-probe`**: before the harness starts, a check run inside the fence fails closed if any protected resource is reachable.

The cutover from the shared relay mailbox to the per-launch channel is owned by the Rivet lead and the teerex lead. This spec consumes that cutover; it does not redesign it.

H05 adds three operator verbs to Rivet (`rv pause`, `rv redirect` and `rv takeover`), an `--invalidate`/`--reinstate` assumption ledger, and stop receipts that measure namespace death. Each verb ends at an existing gate, where the existing `go`/`redo`/`stop` continue the item.

No new broker, daemon, sandbox platform or orchestrator is introduced. A Rex-wide input lease and immediate human revocation (C07/C17) are host-blocked; see [upstream request](#host-blocked-upstream-rex-request).

- **Status:** proposed by worker `planning-runtime`, wave 1. The overnight authority (`overnight-2026-11-13.md`, seat work folder) makes this build work. Choices made under it are labelled **chosen (overnight rubric)**.
- **Mode:** design only. **The acceptance cases below have not been executed.** Three bypass observations in [measured today](#measured-today-on-hive) were run read-only on hive this session against a fence equivalent to Rivet's. Every example is synthetic.
- **Bases:**
  - teerex: dispatch base `244d893c2131c94778b49038910815c5fc2b04a5`. The worktree is at `1bea43f`, rebased onto `4282f23`. Public main is now `1bbb9dc` (agents prune). None of these changes the contracts used here.
  - Rivet: the checkout was read at `d520081` (`jobs/src/{sandbox,relay,rex-tab,kill,stop,agent,gitguard,gitsafe}.ts`, `jobs/sandboxes/bwrap.ts`, `rv.ts`, `jobs/harnesses/*`).
- **Builders:** the Rivet lead (fence, `rv` verbs, kill/receipts); the teerex lead (`agents fence-probe` and its test); the agent-core owner (rule text); rexconfig (the protect file in Josh's config). See [who builds what](#who-builds-what-and-in-what-order).
- **Origins:**
  - H04: the generic parts of A10/A11 (P1:p4), B01/B03/B04 (P1:pp6–7), C15 (P2:p4) and C28 (P2:p7).
  - H05: Phase 2 #1/#2/#4, B01–B04/B08/B09 (P1:pp6–9). B18 (P1:pp11–12) is a recap, not a runtime.
  - Briefs: [H04](../teerex-delegation-briefs.md#h04--authority-isolation-and-privacy-boundaries) and [H05](../teerex-delegation-briefs.md#h05--task-contracts-experiments-and-interruption-semantics).

## The selected workflow and topology (observed)

- **What runs:** Rivet (`rivet-node` on hive) runs each worker call through `runInTab`, which opens a visible tab in Rex session `rivet` (`teerex surfaces open --layout tab`). It records the tab with `teerex jobs track --owner rivet --kind command`, then waits for the tab's OSC 7501 done/error status with `teerex watch`. The tab runs `bash run.sh`, which runs `env -i <filtered env> bwrap <fence prefix> -- <harness argv>` with stdin from a file and output going to `tee`.
- **The fence today:** `jobs/sandboxes/bwrap.ts` uses `--die-with-parent`, read-only system directories, `--dev`, `--proc`, and tmpfs over `/tmp`, `/run` and `/var`. An empty per-call home is laid over `$HOME`. The toolchain is mounted read-only. The checkout, its git store, the shared relay mailbox and extra paths are writable. There is **no `--unshare-pid`, `--unshare-net`, `--unshare-ipc` or `--new-session`**.
- **Messaging today:** the shared `~/.local/state/agent-relay/outbox` is mounted read-write in **every** fence (`sandbox.ts`, `relay.mailbox`), and `agent-send` is granted as the only send command (`relay.command`).
- **Messaging after cutover:** teerex #21 gives each launch a channel: a `PARENT/LAUNCH_ID` directory mounted read-only, holding `channel.sock` and `handle.json`. It grants send, ack and stop ([agents README](../../../items/agents/README.md#launch-scoped-local-fence-channel-21)).
- **Stopping today:** `rv stop` saves the item record, then `killAll(id)` finds processes whose argv names the item plus their descendants by parent PID. It sends TERM, waits 2 s, then sends KILL, and removes the call homes, the actor and the reap.
- **Pausing today:** Rivet pauses **only at gates** (`wait()` in `registry.ts`): step, maintainer, promote and ship. At a gate, `go`/`redo`/`stop`/`answer`/`pick` continue the item, and `rv note` steers roles that start later.
- **Outside the boundary:** interactive agents started with `teerex agents launch` on profiles that have no fence (the seat, planning workers like this one) run as Josh's UID with `--dangerously-skip-permissions` and hold full same-UID authority. **Explicit exclusion:** H04 does not cover them. H05 maps them to the existing cooperative messaging and `jobs adopt` only ([interactive agents](#interactive-teerex-launched-agents-not-fenced)).

## H04 — authority and isolation

### Measured today on hive

All of these were run read-only this session. The fence was built from the same argument list `bwrap.ts` emits (bubblewrap 0.6.1, kernel 5.15, Ubuntu 22.04, yama `ptrace_scope` 1).

| Probe inside the fence | Rivet fence today | With the added flag | What it means |
| --- | --- | --- | --- |
| `test -S $XDG_RUNTIME_DIR/rex/server.sock` | masked | — | The tmpfs over `/run` hides the Rex socket: **holds** |
| Same socket and the agents registry through `/proc/<host pid>/root/...` | blocked | — | The magic-link route is closed: **holds** |
| `kill -0 <host sentinel pid>` | **ALLOWED** | `--unshare-pid`: the host PID is not visible | A worker can signal or kill Josh's shells, other agents and the supervisor |
| `setsid -f` daemon, then fence exit | **1 survivor** | `--unshare-pid`: **0 survivors** | Descendants escape today. With a PID namespace, the kernel kills them when the namespace's init exits |
| TCP connect to the Rivet engine and the DevTools-forward loopback ports | **open** | `--unshare-net`: closed | Every loopback listener is reachable today. The DevTools forward is unauthenticated control of Josh's M5 browser |

**Already handled, keep as is:**

- `gitguard.ts` snapshots git configuration and attributes and restores them after each call.
- `gitsafe.ts` runs host-side git with an engine-owned empty `core.hooksPath` and fsmonitor off.
- The engine's bearer token and harness sign-ins are not inside the fence. A killed call's home is removed by `rv stop`.

### Protected resources and principals

The principals are:

- **J**: Josh at the M5 or his seat pane.
- **S**: the seat agent.
- **E**: the Rivet engine and `rv`, unfenced and same-UID.
- **V**: the teerex supervisor, outside the fence.
- **W**: the fenced worker and all its descendants.
- **O**: other fenced workers.
- **U**: any other same-UID code, including unfenced agents.
- **R**: root.

| # | Protected resource | Allowed operations | W after this spec | Route that bypasses the fence today | Enforced by |
| --- | --- | --- | --- | --- | --- |
| P1 | Rex server socket (typing into any pane, including the seat) | J, S, E, V, U: any API13 call | **none** | none measured | tmpfs over `/run`; probe |
| P2 | teerex agents registry, which holds launch tokens | V, E: lifecycle | **none** | none (masked home) | home overlay; probe |
| P3 | boards store (seat inbox, decisions) and jobs registry | V, E, S | **none** | none (masked home) | home overlay; probe |
| P4 | shared relay outbox | E and the relay service | **none after cutover** | **writable by every worker**: any worker can drop a message addressed anywhere and signed with any name | #21 cutover removes the mount; probe |
| P5 | Loopback services: Rivet engine, DevTools forward, database, tunnelled SSH to the M5, dev servers | the owner processes | **none** | **open** | `--unshare-net` + slirp4netns `--disable-host-loopback`; probe |
| P6 | Other same-UID processes (signals) | owners | **none** | **open** | `--unshare-pid`; probe |
| P7 | The pane's terminal input queue (TIOCSTI) | the program in the pane | **none** for non-interactive calls | inferred open on kernel 5.15, not measured, to avoid injecting into a live pane | `--new-session`; acceptance case A10 |
| P8 | SSH keys and agent socket, harness sign-ins, engine `.env` | J, E | **none** | none (masked home and `/tmp`/`/run`) | home overlay; probe |
| P9 | The worker's own checkout and git store | W: read/write; E: git outside the fence | read/write (by design) | config and hooks tampering | gitguard restore + gitsafe hooksPath (existing) |
| P10 | The per-launch channel (send to starter/report-to, ack, stop) | W: the granted methods only | granted, bounded | — | #21 token, lease, count and frame checks (existing) |
| P11 | The Internet (model APIs, package registries) | W | egress allowed | — | **Not protected**, by choice: harnesses need it. Exfiltration of the checkout is possible. See [limits](#what-remains-possible) |

### The boundary: exact fence changes (Rivet lead, `jobs/sandboxes/bwrap.ts`, `jobs/src/sandbox.ts`)

1. **Always add** `--unshare-pid --unshare-ipc --info-fd 3`. `run.sh` opens fd 3 as `3>"$dir/fence-info.json"`. bubblewrap writes `{"child-pid": N}` there. Right after that file appears, `run.sh` records `pidns=$(readlink /proc/N/ns/pid)` and `/proc/N/stat` field 22 (starttime) into `$dir/fence-ns.json` (mode 0600). These are the identity used for stop verification ([H05 receipts](#receipts-and-exit-codes)).
2. **Add `--new-session`** whenever the call's stdin is not the pane's terminal (every Rivet `runInTab` call today). An interactive profile that needs terminal job control omits it, and its record says `tty_injection: "not_enforced"`.
3. **Network** (chosen, overnight rubric): add a required config key `fence.network: "egress" | "host"`. It follows the same fallback rule as the sandbox itself (`fallback: "refuse"` means a call that cannot be fenced as configured fails as an environment cause).
   - `"egress"` makes `wrap()` return a small helper, `jobs/sandboxes/bwrap-egress` (POSIX sh, in the Rivet repository), in place of plain `bwrap`. The helper:
     1. Starts `bwrap --unshare-net --info-fd 3 --block-fd 4 <rest of prefix> -- <argv>` in the background.
     2. Reads the `child-pid`.
     3. Runs `slirp4netns --configure --disable-host-loopback --mtu 65520 --ready-fd 5 --exit-fd 6 <child-pid> tap0`.
     4. Waits for ready, then writes one byte to fd 4 so the sandbox continues.
     5. Waits for bubblewrap and returns its exit status.
   - The helper generates `nameserver 10.0.2.3` into the call's scratch directory and binds it at `/run/systemd/resolve/stub-resolv.conf` (read-only). This replaces the current read-only bind of the real `/run/systemd/resolve`.
   - slirp4netns exits with the namespace (`--exit-fd`). No process outlives the call.
   - **Install dependency:** slirp4netns is not installed. The jammy/universe candidate is `1.0.1-2`; passt has no candidate. Installing the package is the Rivet lead's host action under the overnight authority. Until it is installed, the config stays `"host"`, and every call record carries `network: "host"` plus P5 as an explicit exclusion. It is not silently treated as enforced.
4. **Remove the shared outbox** from the writable paths, along with `RV_RELAY_MAILBOX`/`RV_RELAY_COMMAND` in the environment. Replace them with the #21 per-launch directory, mounted read-only at its original absolute path. **This is the externally owned cutover:** do it only in that change, after its parity gate. H04 adds only that the fence's final mount list must pass the probe below.
5. **Run the probe first.** The fenced argv becomes `… -- <teerex> agents fence-probe --protect-file <launch-dir>/protect.json --then -- <harness argv>`. The probe execs the harness only if every check passes ([probe contract](#teerex-agents-fence-probe-teerex-lead-itemsagents)).

### `teerex agents fence-probe` (teerex lead, `items/agents`)

One foreground check that runs **inside** the fence, before the harness exists. The worker's code has not run yet, so the result is trustworthy for this launch at this moment. It is a check, not a monitor.

```sh
teerex agents fence-probe --protect-file /ABS/protect.json [--then -- ARGV...]
```

The protect file is JSON, schema 1, mode 0600. The supervisor or Rivet writes it per launch from Josh's config (rexconfig owns the source list). Example (synthetic):

```json
{
  "schema_version": 1,
  "absent_paths": ["/run/user/1001/rex/server.sock", "/home/u/.local/state/teerex-agents",
                   "/home/u/.local/state/teerex-boards", "/home/u/.local/state/agent-relay/outbox",
                   "/home/u/.ssh"],
  "closed_tcp": ["127.0.0.1:7001", "127.0.0.1:7002", "127.0.0.1:7003"],
  "require_pid_namespace": true,
  "require_new_session": true,
  "required_paths": ["/ABS/channel-parent/LAUNCH_ID/channel.sock"]
}
```

**Checks** (each is one fact):

- `absent_paths[]`: `lstat` fails with ENOENT or EACCES. A socket that exists but refuses connections still **fails** the check: if it is visible, it is in reach.
- `closed_tcp[]`: a non-blocking connect gets ECONNREFUSED or ENETUNREACH, or no SYN-ACK within 500 ms.
- `require_pid_namespace`: `/proc/self/status` `NSpid:` has at least 2 fields.
- `require_new_session`: `open("/dev/tty")` fails with ENXIO.
- `required_paths[]`: the path exists and, for a socket, accepts a connect (which is closed at once without sending a frame, so the channel's accepted-connection count goes up by one; the probe is documented to cost one of the `max_requests`).

**Output:** stdout is one JSON object, `{"kind":"fence_probe_result","schema_version":1,"passed":bool,"checks":[{"check","target","result":"pass"|"fail","errno"}],"exec":"started"|"not_started"}`.

**Exit codes:**

| Code | Meaning |
| --- | --- |
| 0 | every check passed. With `--then`, the probe execs ARGV (same PID) and no JSON follows the exec |
| 1 | at least one check failed. The harness is **not** started, and stderr starts with `teerex agents fence-probe: refused:` and the first failing check |
| 2 | usage error |
| 3 | protect file missing, invalid, over 64 KiB, or not mode 0600 |

**Refusals:** a relative path, more than 64 entries in any list, a non-loopback address in `closed_tcp`, or an unknown field.

Rivet copies the JSON into the call record before the exec, through the existing tee to the log. A failed probe is an environment hold (the maintainer's), never a worker failure.

**Why it lives in teerex:** the #21 channel, its handle and its tests live in `items/agents`. The same probe serves Rivet's fence and any future fenced `agents launch` profile. It reads no registry and contacts no Rex server.

### Revocation: what each lever can and cannot do

| Lever | Who | Takes effect | Stops | Does not stop |
| --- | --- | --- | --- | --- |
| Channel lease, count, child exit or supervisor INT/TERM (#21, existing) | V | the next connection | new admissions | a send already dispatched, or input already typed |
| Wrong token, wrong launch, wrong destination or method (#21, existing) | V | per request | that request | — |
| Killing the namespace's init (from `fence-info.json`) | E (`rv stop`, `rv redirect`, `rv takeover`) | immediately; the kernel SIGKILLs every namespace member | **every process in W**, measured by an `ns/pid` scan | effects already issued: network calls, sends, files written to the checkout |
| `jobs forget` / `jobs adopt` | E, J | at once, in that registry | responsibility labels | any process. It is not authority |
| Closing the tab (`surfaces close`) | E, J | at once | the pane and its PTY. Processes get SIGHUP | processes that ignore SIGHUP. Pane closure is not death proof without the namespace scan |
| Revoking human control of a pane's input | — | **impossible today** | — | host-blocked (C07/C17) |

### What remains possible

- **Same-UID code outside the fence (U), including unfenced agents and Josh's shells,** can read and write every protected resource. This boundary protects Josh's estate *from fenced workers*, not from himself or his unfenced agents.
- **Root** can do anything.
- The #21 token is a **bearer capability**: every process inside W can use it (by design, since descendants share the launch). It is not authentication against U.
- **Exfiltration over egress** (P11) of whatever is readable inside W, which is the checkout and the read-only toolchain, is not prevented. The selected workflow needs the network, and an egress allowlist would be a broker (a non-goal).
- **Reporting is not enforcing.** The probe proves the fence's shape at start. The namespaces enforce it for the call's lifetime. A board or registry record of "fenced" is only a report.
- **A local lock is not a Rex input lease.** `jobs` generations and the `agents.lock` order cooperating teerex invocations. They do not stop Josh, other clients or same-UID programs from typing into a pane.
- **macOS:** no equivalence. The workflow runs on hive (Linux).

### Interactive teerex-launched agents (not fenced)

They are out of H04 scope by the exclusion above. If a future profile fences one, it uses the same three namespace flags, the probe and the #21 `delivery` field. `--new-session` is then traded for job control, and the record says so (`tty_injection: "not_enforced"`).

### Host-blocked: upstream Rex request

> **Request: per-block input lease with human-revocable override (closes teerex C07/C17).** Add `block.input.lease.acquire {block_id, holder_label, ttl_ms}` → `{lease_id, expires_at}`, plus `release` and `inspect`. While a lease is held, the server rejects `send_text`, paste and key-injection API calls for that block from any API client that does not present `lease_id`, with a typed error (`input_leased`). Keyboard or paste input from a Rex.app view of that block is never rejected. Instead, **the first human keystroke revokes the lease at once**, and the server emits `block.input.lease.revoked {lease_id, reason:"human_input"}` to the holder's stream. Leases end on holder disconnect and TTL expiry. Counterexamples a fix must pass: (1) a second API client typing into a leased block is refused; (2) a human keystroke during an agent's leased paste revokes the lease before the next API write, and the holder is told; (3) an expired lease admits other clients. Without this, teerex can only offer cooperative locks, and an operator cannot take a pane back from an agent atomically.

The teerex lead appends this paragraph to `~/rivet/work/teerex-lead/rex-upstream.md` (the overnight file for host-blocked items). Nothing else is built for C07/C17.

## H05 — task contract, interruption and takeover

### Gap analysis (existing Rivet versus the brief)

| Brief requirement | Rivet today | Gap → change |
| --- | --- | --- |
| Task outcome and boundaries | item spec plus `rv agent --read/--write`, role contracts | No named assumptions and no budget → add `contract.assumptions`, `contract.budget` |
| Pause stops new work, without claiming death | only at gates; nothing while a step runs | **`rv pause`** (hold at the next boundary) |
| Explain leaves execution unchanged | `rv show`, `rv trace`, `rv call` are reads | none (acceptance only) |
| Wrong direction abandons the approach and keeps evidence | `rv redo <note>` only at a gate; nothing mid-step | **`rv redirect`**, plus `--invalidate` on redo/redirect |
| Continue does not revive invalid assumptions | notes are appended to later prompts; abandoned output is not tracked | an invalidation ledger in the prompt builder; abandoned calls are excluded from `received` |
| Takeover reports exactly what was relinquished | none | **`rv takeover`** |
| Stop with honest death evidence | `killAll` by argv and parent PID; no measurement | namespace-scan receipt |
| Reviewable promotion with real verification | Rivet land/ship with the check's exit and log | none (acceptance only) |

### Contract fields (Rivet item spec, `contract` object)

```json
{
  "contract": {
    "outcome": "cache reads return fresh values after invalidate()",
    "done_when": ["test_cache_invalidate passes", "no new lint findings"],
    "boundaries": {"write": ["<checkout>"], "read": ["<toolchain>"], "network": "egress",
                   "channel_grants": ["send", "ack", "stop"]},
    "assumptions": [{"id": "A1", "text": "stale reads come from the LRU layer"},
                    {"id": "A2", "text": "invalidate() is called on every write path"}],
    "budget": {"wall_ms": 3600000, "calls": 12}
  }
}
```

- `boundaries` is **derived** from the fence config, not authored, and is copied into each call record next to the probe result. It is a report of the H04 boundary, not a second enforcement layer.
- `assumptions` come from the discovery/plan roles (contract text in `~/rivet/contracts/plan.md`: "name each load-bearing assumption as A<n>") or from `rv note --assume "text"`. IDs are `A[1-9][0-9]{0,2}`. They are never renumbered.
- `budget`: when either limit is reached, the engine performs `pause` itself, with `by: "budget"`. **It never kills.** Chosen (overnight rubric): Josh decides at the gate.
- H01's record envelope (`teerex records`, [evidence-records.md](evidence-records.md)) holds the evidence. Rivet stores record IDs on events and has no second store.

### States and transitions

States are shown on the board row (`status`, `waiting`). New values are in **bold**.

```
running ──pause──▶ **pausing** ──(current call returns)──▶ waiting[pause]
running ──redirect──▶ **redirecting** ──(evidence saved, ns killed, checkout reset)──▶ running (new attempt)
running|waiting ──takeover──▶ **redirecting**-style kill ──▶ waiting[takeover]   (operator owns checkout)
waiting[pause|takeover|step|…] ──go──▶ running        ──redo [--invalidate]──▶ running (new attempt)
any ──stop──▶ stopped   (existing reap; checkout kept if taken over)
```

| Verb (new = **bold**) | Precondition | Effects, in order (each one durable before the next) | Never does |
| --- | --- | --- | --- |
| **`rv pause <id> [note]`** | running, not already pausing | 1) appends event `pause`; 2) the workflow's `step` wrapper checks for a pending pause **before scheduling any function call** and enters `wait(ctx, "pause-<n>", "approver", …)`. The current call runs to completion, and its output is kept for the gate. | signals, freezes or kills anything; claims descendants stopped |
| `rv go <id> [note]` at the pause gate (existing) | waiting[pause] | resumes scheduling. The prompt still carries every invalidation | revives an invalidated assumption |
| **`rv redirect <id> <note> [--invalidate A<n>]…`** | running | 1) event `redirect` (intent, `outcome:"uncertain"`); 2) saves evidence: call log path; `git -C <checkout> add -A && git diff --cached <step-start> > logs/<id>/abandoned-<n>.patch`; a `teerex records` experiment with outcome `abandoned`, linking the patch; 3) kills the call's namespace init and runs the namespace scan; 4) `git reset --hard <step-start>` in the **engine-owned** checkout; 5) marks the abandoned call `abandoned:true` (excluded from `received`); 6) records the invalidations; 7) reruns the step with the note; 8) updates the event `outcome` | discards the patch or log; reuses abandoned output |
| `rv redo <id> <note> [--invalidate A<n>]…` at a gate (existing, extended) | waiting | the same as redirect steps 2, 5, 6 and 7 (nothing to kill) | — |
| **`rv takeover <id> [note]`** | running or waiting | 1) event `takeover` (intent); 2) if running: saves evidence as redirect step 2 does, then kills the namespace and scans it; 3) sets `checkout_owner: "operator"`: from now on, `reap`, `R.cleanup`, rebase, land and push **refuse** for this item; 4) `jobs adopt --from-owner rivet --owner operator` for any still-tracked worker tab (usually already closed, which is fine); 5) `wait(ctx, "takeover-<n>", "approver", …)`; 6) prints the relinquish receipt | resets the checkout; closes anything the operator now owns |
| `rv go <id> [note]` at the takeover gate (existing) | waiting[takeover] | records the operator's commits (`<step-start>..HEAD`) and dirty state as evidence and as assumption `A<next>: "operator changes at <sha> are intended"`. Sets `checkout_owner: "rivet"` and reruns the step on top of HEAD | rewrites the operator's commits |
| `rv note <id> --reinstate A<n> <why>` (extended) | an invalidated A<n> exists | explicitly restores the assumption, with the reason | — (the only route back) |
| `rv stop <id>` (existing, extended) | any | the existing stop, plus the namespace scan in its receipt. If `checkout_owner` is `operator`, the checkout and branch are **kept** and named in the receipt | removes an operator-owned checkout |
| `rv show/trace/call` (existing) | any | read only | appends events or changes processes |

**Invalidation ledger in the prompt builder** (`registry.ts`, next to the existing "Words sent while this work was running" section): add `## Invalidated assumptions — do not rely on these\n- A<n>: <text> (invalidated by <by> at <time>: <note>)`, minus any reinstated ones. Calls marked `abandoned` are dropped from `received`, and the builder adds one line naming the abandoned patch's path as *evidence of a rejected approach*.

### Namespace scan (Rivet lead, `jobs/src/kill.ts`)

`killNs(fenceNs)` checks that `/proc/<child-pid>/stat` starttime still matches `fence-ns.json`, which guards against PID reuse. It sends SIGKILL to `child-pid` (the namespace init; the kernel kills every member). After up to 2 s it scans `/proc/[0-9]*/ns/pid` for the recorded `pid:[INODE]`. The existing argv/parent-PID `killAll` stays as a fallback for processes outside the fence (the run.sh bash, tee, slirp4netns).

### Receipts and exit codes

Every new or extended verb accepts `--json` and prints one object:

```json
{"kind":"rv_transition","schema_version":1,"verb":"takeover","item":"t-cache-12",
 "outcome":"verified","state":"waiting","gate":"takeover-1",
 "worker_processes":{"pid_namespace":"pid:[4026532901]","signalled":true,
                     "ns_members_remaining":0,"verified_gone":true},
 "relinquished":[
   {"resource":"scheduling","to":"operator","detail":"held at gate takeover-1"},
   {"resource":"checkout","to":"operator","detail":"<checkout path> branch rv/t-cache-12 head 3f2a…"},
   {"resource":"worker_process","to":"none","detail":"terminated; namespace verified empty"},
   {"resource":"channel","to":"none","detail":"revoked by child exit"},
   {"resource":"jobs_record","to":"operator","detail":"adopted generation 41"}],
 "retained_by_rivet":["item record","call logs","abandoned-1.patch","books promises"],
 "not_relinquishable":[{"effect":"channel_send","count":2,"detail":"already delivered to report-to"},
                       {"effect":"network_egress","count":"unknown","detail":"not recorded by the fence"}],
 "evidence":["records:exp-t-cache-12-1"],
 "pause_semantics":null}
```

- For `pause`, `worker_processes` is `{"signalled":false,"verified_gone":false,"note":"pause does not stop running calls"}` and `pause_semantics` is `"no_new_scheduling"`.
- `outcome` is one of:
  - `verified`: every effect was checked.
  - `uncertain`: an effect was attempted but not verified, for example `ns_members_remaining > 0`, a lost reply from the engine, or a failed scan.
  - `refused`: a precondition failed. Nothing was done beyond the read.
- **Exit codes:** 0 verified; 1 refused or uncertain (read `outcome`); 2 usage.
- An interrupted `rv redirect` or `rv takeover` leaves its intent event marked `uncertain`. Re-running the same verb on that item **refuses** with `transition_pending_uncertain`, and `rv show` lists the saved steps. Josh or the seat then decides with `go`, `redo` or `stop`. Nothing is retried automatically.

### Resource ownership across transitions

| Resource | running | pausing | waiting[pause] | redirecting | waiting[takeover] | stopped |
| --- | --- | --- | --- | --- | --- | --- |
| Scheduling of new calls | engine | engine, **blocked** | approver | engine | **operator** | none |
| Running worker processes (W) | engine | engine (runs on) | none | being killed → none, verified | none, verified | none, verified or `uncertain` |
| Checkout and branch | engine via W | engine via W | engine | engine (reset after the patch) | **operator** (engine refuses to write) | removed, unless operator-owned: then **kept** |
| Worker tab (jobs record) | `rivet` | `rivet` | closed and forgotten | closed and forgotten | adopted by `operator` if open | closed and forgotten |
| #21 channel | open, lease running | open | revoked (child exit) | revoked | revoked | revoked |
| Item record, logs, patches, H01 records | engine | engine | engine | engine (**adds** the abandoned patch) | engine | engine, kept in `stopped/<id>.json` |
| Effects already issued (sends, egress, files) | — | — | not undone, listed | not undone, listed | not undone, listed | not undone, listed |

### H05 mapping for interactive (unfenced) agents

| Brief control | Mapping | Honest label |
| --- | --- | --- |
| Pause | `agent-send` "pause after this step" to the agent's pane | **cooperative**; nothing is enforced |
| Takeover | `teerex jobs adopt --from-owner <starter> --owner operator …`, then `teerex agents present … --focus yes`; Josh types | the receipt lists the jobs generation. **No input lease**, so typing races are possible (C07/C17) |
| Stop | Ctrl+C in the pane, or the supervisor's INT/TERM forwarding to its immediate child | `immediate_child_term` only. Descendants are **not** verified |

No new teerex code is needed for H05. agent-core's messaging rule gains the cooperative pause wording ([below](#who-builds-what-and-in-what-order)).

## Who builds what, and in what order

| # | Owner | Change | Depends on |
| --- | --- | --- | --- |
| 1 | Rivet lead | `bwrap.ts`: `--unshare-pid --unshare-ipc --info-fd 3`, `--new-session` for non-TTY calls; `run.sh` (in `rex-tab.ts`) writes `fence-info.json`/`fence-ns.json` | none. **Ship first**: it closes P6 and descendant escape |
| 2 | Rivet lead | `kill.ts` `killNs` + scan; extend the `rv stop` receipt | 1 |
| 3 | teerex lead | `items/agents`: `fence-probe` leaf op, help text, README section, tests A1, A2, A5–A7, A10 and A11 in `test_agents.py` behind `TEEREX_AGENTS_FENCE=1` | none (parallel to 1) |
| 4 | rexconfig | `~/.config/teerex/protect.json` source list (Josh's paths and loopback ports; private, not in any repository) | none |
| 5 | Rivet lead | `sandbox.ts`: per-launch `protect.json` generated from 4 plus the launch directory; argv goes through `fence-probe --then` | 3, 4 |
| 6 | Rivet lead | install `slirp4netns`; `bwrap-egress` helper; `fence.network` key, set to `"egress"` | 1. Until installed: `"host"` plus the explicit P5 exclusion in every record |
| 7 | Rivet lead + teerex lead (existing cutover) | outbox mount → #21 per-launch channel | their parity gate; H04 only adds "probe passes with the outbox absent" |
| 8 | Rivet lead | `contract.assumptions/budget`, invalidation ledger, `rv pause`, `rv redirect`, `rv takeover`, `redo --invalidate`, `note --reinstate/--assume`, `checkout_owner` guards, `--json` receipts | 2; H01 `teerex records` for the evidence links (store the link as null until it ships) |
| 9 | agent-core owner | `primitives/rules/agent-messaging/RULE.md`: add one line: "A message that says pause means finish the current step, report, and start nothing new until told." Rex skill: document `fence-probe` and the `rv` verbs | 3, 8 |
| 10 | teerex lead | append the [upstream request](#host-blocked-upstream-rex-request) to `rex-upstream.md` | none |

## Acceptance cases (runnable; not executed)

Rivet cases live in `jobs/test/fence.test.ts` and `jobs/test/interrupt.test.ts` and run against a disposable project, Rex session and checkout. teerex cases live in `items/agents/test_agents.py`. Each case has a **counterexample** (CE), which must observably differ.

### H04

- **A1 direct socket bypass.** Inside the fence, run `test -S <rex socket>` and `connect()` both directly and through `/proc/<outside pid>/root/...`: absent or denied. **CE:** the same probe outside the fence connects. This proves the probe can see the socket.
- **A2 store bypass.** `lstat` of the registry, boards store, jobs registry and relay outbox (after step 7): ENOENT. **CE:** the per-launch channel directory is present and `channel --operation ack` succeeds.
- **A3 wrong recipient or token** (re-run the #21 cases inside the Rivet fence). A forged handle token, another launch's ID, and `--to` other than starter/report-to are each refused with no send. **CE:** the correct handle and `--to report-to` delivers exactly once.
- **A4 expired capability.** `lifetime_ms: 1000`; send at about 1.5 s: refused, with zero sends. **CE:** a send at about 0.2 s succeeds.
- **A5 descendant escape.** `setsid -f` a tagged sleeper, then exit the harness: after the fence exits, `pgrep -f <tag>` finds 0 and the namespace scan finds 0. **CE:** the same run with `--unshare-pid` removed leaves 1 survivor (observed on hive this session).
- **A6 host signal.** The worker runs `kill -0 <outside sentinel pid>`: fails (ESRCH). **CE:** without `--unshare-pid` it succeeds (observed).
- **A7 loopback.** With `network:"egress"`, every `closed_tcp` entry is unreachable, and HTTPS to a public model-API hostname succeeds. **CE:** with `network:"host"` the loopback ports connect (observed), and the probe exits 1 with no harness started.
- **A8 lost acknowledgement.** Kill the channel client after the frame is written and before the response arrives. The registry shows the request intent. Re-using the same `--request-id` refuses (`delivery_uncertain_no_retry`). **CE:** a fresh ID, after inspecting the registry from outside the fence, delivers once.
- **A9 git store tamper.** The worker sets `core.hooksPath` and a filter driver in `.git/config`. After the call the files are restored and the call record lists them. Host-side git runs no hook. **CE:** a write to a checkout source file is kept (the checkout is meant to be writable).
- **A10 terminal injection.** On a **disposable** PTY, a fenced process attempts `ioctl(TIOCSTI)` on `/dev/tty`: fails (`open` ENXIO). **CE:** without `--new-session` on the same disposable PTY, an injected byte appears in the reader's input. Never run on a live pane.
- **A11 probe fails closed.** A protect file lists a path that is in fact bind-mounted: exit 1, `exec:"not_started"`, a sentinel harness never writes its marker file, and Rivet holds for the maintainer. **CE:** a clean fence exits 0, and the harness marker is written by the same PID.
- **A12 same-UID limit is stated, not hidden.** An unfenced process (outside) reads the registry: succeeds. The test asserts that the H04 documentation says so. It is a counterexample by design: the boundary is the fence, not the UID.

### H05

- **B1 pause does not claim death.** Pause during a long fake call. The call continues and finishes; no new call starts; the receipt has `signalled:false, verified_gone:false, pause_semantics:"no_new_scheduling"`; the item reaches `waiting[pause-1]` only after the call returns. **CE:** a receipt or board row saying `stopped`/`verified_gone:true` while the call's namespace still has members fails.
- **B2 explain leaves execution unchanged.** `rv show`, `rv trace` and `rv call` during a running call: the event count and the namespace member count are unchanged. **CE:** `rv note` during the same window adds exactly one event.
- **B3 wrong direction keeps evidence.** `rv redirect --invalidate A1`: `abandoned-1.patch` exists and contains the worker's change; a `teerex records` experiment has outcome `abandoned`; the namespace scan finds 0; the checkout HEAD and tree equal `<step-start>`; the new prompt contains the Invalidated section with A1 and **does not** contain the abandoned output in `received`. **CE:** a prompt-builder run that includes the abandoned call's output fails the test.
- **B4 continue does not revive.** Pause, then `go`: the next prompt still lists A1 as invalidated. Then `rv note --reinstate A1 "<why>"`: the next prompt drops it. **CE:** `rv go "A1 is fine actually"` (a plain note) must **not** remove A1 from the Invalidated section.
- **B5 takeover reports exactly.** Takeover during a call that has made 2 channel sends. The receipt's `relinquished` is exactly {scheduling, checkout, worker_process, channel, jobs_record}; `not_relinquishable` includes `channel_send count 2`; the scan finds 0. A following `rv stop` keeps the checkout and branch and names them. **CE:** an engine `reap` or `land` attempted while `checkout_owner:"operator"` refuses with `checkout_operator_owned`, and a receipt missing the issued sends fails.
- **B6 noncooperating child.** The worker traps and ignores SIGTERM. `rv stop` still reaches `ns_members_remaining:0` (SIGKILL to the namespace init). An external effect issued before the stop (a delivered channel send) is listed as not relinquishable. **CE:** with the fence's info file deleted, the receipt says `outcome:"uncertain"`, `verified_gone:false`, never true.
- **B7 interrupted transition.** SIGKILL `rv redirect` after its intent event. A second `rv redirect` refuses with `transition_pending_uncertain`, and `rv show` lists which steps completed. **CE:** `rv stop` on the same item proceeds and records the abandoned patch if step 2 had completed.
- **B8 budget pauses and does not kill.** `budget.calls: 1`: after one call the item is at `waiting[pause-1]` `by:"budget"` and no process is signalled. **CE:** `budget.calls: 5` with the same workload never pauses.
- **B9 promotion is reviewable.** On done, `rv show` gives the diff `<base>..<head>` and the actual check command's exit code and log path. **CE:** a step whose check exited non-zero cannot reach `done`.

## Live check after install (hive)

1. `rv agent --project <disposable> "run: sh -c 'kill -0 1; setsid -f sleep 300; curl -sm2 http://127.0.0.1:<engine port>/'"`. The call record shows `fence_probe_result.passed:true`; `kill -0 1` targets the namespace's own init; after the call, `pgrep -f 'sleep 300'` finds 0; curl fails.
2. On one real item, `rv pause`, then `rv takeover`, then `rv go`, with `--json` each time. The receipts match the tables above.
3. Report the probe JSON and the three receipts to the seat. Exit 0 alone is not the check.

## Non-goals

No general multi-agent controller, second sandbox platform, egress proxy or allowlist broker, production credentials, global userns/sysctl/firewall change, automatic pausing of arbitrary agents, silent redaction, macOS fence parity, or redesign of #14/#21 or of the agent-core migration.

## Sources

- [H04/H05 briefs](../teerex-delegation-briefs.md#h04--authority-isolation-and-privacy-boundaries)
- [roadmap current plan](../../roadmap.md#current-phased-plan--13-november-2026)
- [agents contract, #14/#21](../../../items/agents/README.md#source-only-compute-routing-and-scoped-delivery-issues14-and21)
- [jobs](../../../items/jobs/README.md)
- [boards](../../../items/boards/README.md)
- [recovery](../../../items/recovery/README.md)
- [alpha5](../../alpha5.md)
- [H01 records](evidence-records.md)
- [U01/U02](continuity-park-resume.md)
- Rivet source at `d520081`, read only: `jobs/sandboxes/bwrap.ts`, `jobs/src/{sandbox,relay,rex-tab,kill,stop,agent,gitguard,gitsafe,registry}.ts`, `rv.ts`, `jobs/harnesses/{claude,codex}.ts`.
- Rivet config keys `fence`/`relay`; values are private and not reproduced.
- The overnight authority file in the seat's work folder.
- **Observed this session:** the bubblewrap probes in [measured today](#measured-today-on-hive); `apt-cache policy` (slirp4netns 1.0.1-2 candidate; passt none); `ss -ltn` loopback listeners (counted, not published).
