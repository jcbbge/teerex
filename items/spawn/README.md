# spawn

[Operator/agent addendum: Who, What, When, Where, Why, How](../../docs/concierge/features.md#7-spawn-one-visible-agent-terminal) covers current alpha.5 low-level argv spawn, platform/API support, verification, lost-ACK recovery and lifecycle. [Current setup](../../docs/concierge/setup.md) installs alpha.5; its [managed profile/ACK-before-brief path](../agents/README.md) is distinct from this low-level Mac/Linux API10–13 operation and the standalone [spawn cartridge](../../docs/cartridges.md). Creation is not readiness; no automatic retry/close follows uncertainty.

**Experimental visible agent launcher.** `teerex spawn` creates one terminal in a new window of an explicitly selected existing Rex session. It requests `focus=false`, verifies the acknowledged block's window attachment, and returns its full address. It never creates a detached intermediate block or falls back to a hidden worker. Rex can make a new window active if the session has no active window; `focus=false` is not a global focus lock against other clients.

```sh
teerex spawn --socket /absolute/path/to/existing/rex.sock \
  --session session:FULL-UUID --name worker --cwd /absolute/workspace \
  --report-to-session session:PARENT-FULL-UUID --report-to-block block:PARENT-FULL-UUID \
  --timeout-ms 5000 -- /absolute/path/to/agent --its-arguments
```

Use canonical lowercase full IDs, an absolute socket and cwd, a 1–128-byte UTF-8 name without controls, and explicit report-to addresses. No environment/focus/label fallback chooses these targets. The report-to block must be an existing window-attached terminal, including when it is in another session on the selected server. Its later availability is not guaranteed. Rex is a separately obtained trusted executable on `PATH`; the command disables autostart and removes inherited `REX_SERVER`, `REX_SESSION`, `REX_BLOCK` and `REX_CLIENT` hints from its transport environment. This does not authorize connecting to an otherwise unauthorized endpoint or starting an arbitrary program.

## Program and address contract

One fixed Lua script checks the actual integer server API revision (accepted **10–13**), selected session and report-to address, then calls `session.new_window` once with one terminal layout. All values are JSON arguments, not interpolated Lua. The terminal command is a fixed `sh -c` shim with positional parameters, followed by the literal argv. The shim performs `cd -- "$1" || exit 125` before `exec "$@"`; a missing directory must not silently run the program in Rex's fallback directory. The cwd belongs to the terminal creator's host, not necessarily the CLI host. The terminal retains its contents after program exit for inspection. Shell initialization/configuration and executable resolution remain Rex/account behavior, not a hermetic environment or sandbox.

The shim preserves the established `agent-core-public` `agent-spawn` address contract (reviewed commit `80c13e4c8d58a851fcab1085437d51f10080c831`):

- `AGENT_SESSION=$REX_SESSION`, `AGENT_PANE=$REX_BLOCK` identify the new terminal, not its starter.
- `LC_REX_SESSION` and `LC_REX_BLOCK` carry those addresses for deliberately configured SSH forwarding.
- `AGENT_NAME` and `LC_AGENT_NAME` contain the selected label.
- `AGENT_REPORT_TO` and `LC_AGENT_REPORT_TO` contain `session:UUID block:UUID` for the explicitly selected parent.

Exporting `LC_` values does not configure SSH `SendEnv`/`AcceptEnv`, forwarding, routing, stop alerts, agent-core tools or Rivet. No agent-core source, personal shell, skill, configuration or launcher is changed. Joshua's setup agent separately owns migration/guards; all agents/workers/sidecars/messages on his machines must continue through the authorized Rex/teerex work surface, without hidden-worker exceptions. `offstage` is not an alternative agent launcher.

## Receipt, limits and lifetime

Stdout is one `schema_version=1`, `kind="spawn_result"` JSON object; check the exit code too. Exit **0** and `outcome="created_and_attached"` require a valid creation receipt and a subsequent session view placing that exact terminal in that exact new window. `created` contains `window_id`, `block_id` and the creation revision; source identity records the actual returned version/platform/revision. Neither the creation ACK nor attachment verifies program startup, agent readiness, successful work or future visibility. `program_start`, `agent_readiness` and `task_completion` remain `not_assessed`; a program that cannot start may leave a retained terminal showing the failure.

Before a mutation is attempted, an explicit preflight refusal returns **1** and `outcome="refused"`. A client launch failure (such as `FileNotFound`) or a normally exited nonzero backend with complete frame output and no creation-attempt frame returns **1** and `outcome="backend_error"`. Rex flushes the marker before calling creation, so these pre-creation failures can be distinguished from uncertain effects. A lost, partial, malformed or abnormally terminated transport, an incomplete exit-0 receipt, or any failed request with an observed attempt returns **1** and `outcome="uncertain"`; a missing marker alone does not establish failure. `retry_safe` remains false for every outcome. Acknowledged IDs survive a later verification failure when available. `creation_attempt_frame_seen` reports only receipt of a pre-call frame, never server dispatch proof. There is **no automatic retry, rollback or close**. Inspect the session before deliberately retrying an uncertain request, using known IDs when available; a terminal may already be running. The launcher does not close an existing or newly created worker merely because its own transport was cancelled.

Failed receipts keep a specific launch/collector error or Lua refusal reason when available; otherwise `failure_reason="rex_backend_nonzero_exit"` names a pre-creation nonzero backend exit, and `failure_reason="rex_transport_incomplete"` replaces a null reason for uncertainty, including an empty or partial receipt after exit 0. When supervision returns a result, `backend_term` records the Rex **client's** tagged termination (for example `{"Exited":7}` or `{"Signal":15}`), not the launched worker's exit. It is null when launch/collection failed without a termination receipt. On failure, up to **4096 retained raw stderr bytes** are printed to stderr with a `teerex spawn: Rex backend:` prefix; this is a possibly truncated, unredacted diagnostic prefix, not a complete log. These diagnostics do not establish whether creation occurred, make retry safe, or pin/authenticate the executable or server.

The total supervised transport budget defaults to **5000 ms**, range **100–60000**, plus bounded owned-client cleanup and OS/output scheduling. Deadline exits **124**, SIGINT **130**, SIGTERM **143**; these are not successful creation or worker-stop receipts. Transport cleanup owns its Rex client process group, not the selected server or server-created terminal. SIGKILL/crashes and disconnected clients may leave a terminal; operator-owned windows have no automatic job deadline.

Usage errors exit **2**, normally without JSON. Only UTF-8 argv/cwd are accepted. Encoded JSON arguments are capped at **48000 bytes** before client launch; Rex's own encoder additionally limits the creation request to **60000 bytes**, leaving protocol headroom below its observed control-frame ceiling. Labels/argv are not copied into receipts, but terminal commands, server configuration and diagnostics can still expose private data. There is no redaction, input lease, global concurrency control, task sandbox or remote identity authentication. The independent experimental spawn package preserves this native low-level contract without adding a persistent registry; managed launch is the separate agents path.

## Verify and remove

Build the shared CLI with Zig **0.15.2**, then run the public suite against a deliberately selected test Rex:

```sh
TEEREX_BIN=/absolute/path/to/teerex REX_BIN=/absolute/path/to/rex \
  python3 items/spawn/test_spawn.py -v
```

Six checks start private `/tmp` servers with `/dev/null` config and restore disabled. They independently inspect the created window, unchanged focus, exact Unicode/empty/quote/newline argv, actual cwd, exported addresses/name/report-to, and retained exit. Negative cases cover missing report targets, encoder expansion, oversized arguments, no-autostart and invalid cwd. A real creation followed by deliberately dropped ACKs leaves exactly one inspectable window and an uncertain receipt without retry/close. Separate controlled transport faults exercise deadline/SIGINT/SIGTERM. Fixtures stop their own disposable server afterward, never a personal endpoint.

These six checks passed on disposable Debian 13/kernel 6.1.189+ x86_64 and arm64 macOS 27.2 with checksum-verified official Rex preview.16/API13. Other actual-build results belong to the combined release/CI record, not an inference from accepting revision numbers. API11 and Joshua's exact M5/hive remain unverified here.

**Diagnostics repair validation, 12 November 2026 (now shipped in alpha.5):** the expanded **7-check** suite passed on disposable Linux x86_64/API13 and arm64 macOS **26.3.1** with the official checksum-verified API10/12/13 builds pinned by CI. The new fault regression fails against the published alpha.4 Linux binary (matching release SHA256) because failed/incomplete transport reasons are null. Coverage includes missing/nonexecutable clients, nonzero exit with/without stderr, an exact 4096-byte diagnostic prefix from a longer stream, signal termination, empty/partial/malformed receipts, real nonexistent sessions, and real creation with lost ACKs or retained IDs followed by failure. Existing deadline/cancellation and unchanged-focus/no-retry/no-close checks also pass. Collection errors still have no termination receipt; the error name is preserved and `backend_term` remains null. This does not implement executable pinning/provenance or certify the reported personal M5/mixed-host setup.

Spawn installs no service or configuration. Stop invoking it to remove its launcher effect; close only the specific terminal/window you deliberately own when its work is no longer needed. Removing/upgrading teerex does not stop existing workers. The [shared installer](../../docs/install.md) manages binary versions, not worker lifetimes or independent cartridges. Rex remains proprietary and unbundled; no project license has been selected ([rights](../../RIGHTS.md)).
