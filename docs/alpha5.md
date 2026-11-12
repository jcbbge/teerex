# Alpha.5 operating layer

Alpha.5 is the selected next milestone, not a claim that alpha.4 already supplies a complete Rex operating layer. Its release gate is an operator-visible, inspectable set of commands across explicitly named hosts. The [alpha.4 tag and assets](https://github.com/jcbbge/teerex/releases/tag/v0.1.0-alpha.4) remain frozen. The [versioned release guide](releases/v0.1.0-alpha.5.md) describes the tested experimental slices and unfinished brief requirements. Confirm the exact release page/assets before installation; this branch document alone is not a publication receipt.

Joshua's 12 November 2026 [product brief](https://github.com/jcbbge/teerex/issues/11) supersedes the old exclusion of agent-core migration as product work. The historical Phase 1–3 inventory and host safety blockers are retained in the [roadmap](roadmap.md), not silently checked off or erased.

## Delivery gates and ownership

| Slice | Owner paths | Acceptance before release |
| --- | --- | --- |
| Shared integration and target selection | `src/**`, `build.zig`, root CLI, CI, packaging, roadmap | Explicit target/executable receipts; unknown-name refusal before network; native Mac/Linux combined tests; public help/version; exact asset verification |
| UI surfaces and palette | `items/surfaces/**` | Tiled/floating/tab programs, measured layout readback, explicit inspect/focus/close controls, no hidden intermediates/fallback/retry; honest config-registration state |
| Boards, seat, inbox, decisions | `items/boards/**` | Readable foreground live boards; full address-bound append before paste; complete decision cards and resolution; reports distinguished from Rex observations and unknown state |
| Profiles, protocol and responsibility | `items/agents/**` | Visible launches; persisted intent and jobs; starter/report-to metadata; agent ACK before one brief attempt; measured direct-child exit versus reported harness stop/error |
| Recovery and update | `items/recovery/**` | Private snapshot and explicit launch metadata; reviewed restore plans, old/new mapping, report/seat/inbox remapping; exact impact and manual update handoff where public update API is absent |
| Fleet installation | `tools/fleet-install/**` | One shared named-host config; plan/apply, strict SSH trust, explicit PATH/launcher consent, retained versions, actual version check and per-host partial results |
| Core installer inspection | `tools/install/**` | Read-only structured inspect/verify, no adoption/execution or manual-tree deletion |

Independent owners transfer source to one integrator; central CLI/build/config changes are not edited in parallel. Existing spawn/jobs and observation diagnostic owners handed off narrow patches before shared wiring began. Their repairs preserve uncertainty and do not close whole issues #1 or #10.

## Current source contract

- `teerex --version` prints `teerex 0.1.0-alpha.5` and exits 0 without contacting Rex. This identifies source builds; it does not establish a published release.
- `teerex --rex ABS COMMAND ...` selects an exact executable for native Rex calls. Selection is not authentication of that executable or its server.
- `teerex targets resolve --config ABS --host NAME` returns one bounded JSON object with `schema_version`, validated `host`, and `identity_basis`. Unknown names fail before any Rex/SSH call.
- `teerex --config ABS --host NAME COMMAND ...` executes on the configured command host and injects its exact socket. Config, message-file, cwd, snapshot and store paths in the resulting invocation belong to that command host; no silent upload, host fallback, or retry occurs.
- Existing `teerex COMMAND --socket ABS ...` invocations remain supported. Named-host targeting conflicts with a second explicit socket/server selector.
- Python3.9+ is an explicit prerequisite for named-host and embedded Python operating-layer commands; legacy direct-socket native commands do not acquire that dependency.

A private JSON config has `schema_version:1` and `hosts`, keyed by names such as `m5`, `hive`, and `m1`. Every record supplies `host_id`, `transport` (`local` or `ssh`), `home`, `platform` (`macos-arm64` or `linux-x86_64`), `socket`, `rex`, `teerex`, and `store`. Paths are explicit absolute paths. SSH also supplies literal `address`, `port`, `identity_file`, and pretrusted `known_hosts`. No real endpoints belong in public examples.

The config declares expected identity; it is not independently observed host identity. SSH uses batch mode, strict host checking and an explicit identity, without agent forwarding, host-key updates, user SSH configuration, connection reuse or retries. Each dispatched invocation emits a target-selection receipt on stderr; leaf stdout keeps its machine-readable contract. Receipts omit program argv and message/capture content.

## Verified combined source and inspection

The shared CLI now wires every owner subtree and embeds fleet support files; a copied/installed native executable can plan/install/verify exact alpha.5 bytes without the source tree. Root help lists the operating-layer commands, Python prerequisite and effect boundaries. Operator programs remain visible, with explicit focus/close and actual identity/geometry readback. Legacy low-level argv spawn remains available but is not mislabeled as managed responsibility.

Final Linux and Mac/API13 combined acceptance covers boards12 including the native route helper, agents12 with both integration gates, recovery11, surfaces15, jobs14, targets7, legacy regressions, installer20 and fleet11. Real loopback SSH verifies exact configured-target observation/board probes, unchanged layout and strict unknown/changed-host-key refusal. Terminal content captures were rendered and inspected for empty, complete/narrow decisions, resolution and partial fleet; these do not certify native Rex.app painting. Exact published-byte and CI receipts belong in the release guide/evidence, not inferred from a worker's earlier green leaf run.

Distinct same-server report sessions now work: the failing regression proved the Lua stream was not attached to the second session; explicit attachment fixes validation without mutating the report layout. Locked `jobs present --relocate yes` moves the existing finished pane beside an explicit anchor; default no preserves the prior contract and focused sources require explicit focus yes. Lifecycle cancellation handles inherited signals and gives the owned native client its bounded cleanup before forced termination.

New operating-layer commands ship in the combined CLI, not as falsely independent cartridge payloads. Existing ten-Mac/seven-Linux native cartridges remain independently installable under their established contract. No new plugin system or detached fleet service is added.

## What remains an honest blocker

- Public preview.16 process evidence exposes argv0, not arbitrary command arguments. Recovery must use deliberately supplied launch metadata, not pretend to rediscover secret-bearing argv.
- No authoritative public draft API distinguishes unsent input from grey suggestions. Draft recovery is unsupported unless that evidence contract becomes available. Heuristic screen parsing does not establish it.
- Automatic harness resume-ID discovery is not proven. An explicit supplied resume ID remains supplied metadata, not measured evidence.
- No public server-upgrade operation was found. Update can show exact impact/snapshot and a manual operator handoff; it cannot invent an updater or authorize a personal restart.
- The private `~/briefs/rex-restart-tabs.sh` and restart accounting were not supplied. They must remain intact, and no parity/deletion claim is allowed without their source and acceptance evidence.
- Named command-host execution is distinct from observing a foreign-host block inside an attached mixed-version server. Disposable native configured-host reads succeed; the exact issue #10 topology remains unverified. A different block host ID alone is not an observation-refusal reason.
- Native layout readback proves structure, not that an unavailable Rex GUI painted the window. Terminal boards can be rendered and reviewed independently; GUI acceptance must be labeled accurately.
- A client lock, ownership label, fresh read or saved state cannot enforce Rex-wide atomic input, immediate human revocation, process-tree death or isolation. Those host-level gaps stay visible.

## Migration without losing working behavior

For each public agent-core stopgap, deliver the replacement invocation, tested parity and a paired source migration. Do not remove `agent-spawn`, `agent-send`, `agent-ask`, `agent-inbox`, `agent-seat`, `agent-stop-alert`, `teerex-target`, shell launch guards or palette entries merely because a similarly named command exists. Preserve wrappers/guards with additional behavior until the replacement demonstrates that behavior or explicitly retains the unsupported boundary.

Every program launched by the new operating layer must be visible in Rex and available to the operator to read, focus and close. Existing low-level local `run`/offstage command-experiment contracts are historical tools, not an exception for launching hidden agents or boards. No agent runs detached as a substitute for visible responsibility.

Actual personal-machine installation, global launcher replacement, pane closure, server update/restart and captured-content publication still require their specific authorization. Product shipping authorization does not authorize those actions.
