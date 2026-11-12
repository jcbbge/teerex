# agent-core surface migration and deletion gate

This is the capability-1 source migration/deletion plan, not permission to edit or reload Joshua's actual machines. Keep working stopgaps until their callers are migrated and the combined operating-layer acceptance passes.

## Proven source and missing provenance

Reviewed `jcbbge/agent-core-public` at `c26bcfc0e87f82a78ce7993a97bd63033ca131fd`:

- `primitives/tools/agent-messaging/agent-seat`: creates per-seat inbox/log files, remembers a viewer, places a floating `agent-inbox` layer at `[0.667,0,0.333,1]`; on creation failure falls back to `rex run --split=right`, repeated `session.resize_pane`, and logged ratio readback.
- `rex/init.lua`: native `rex.action` entries, `HIVE.argv`/`HIVE.open` terminal launches, generated Hive menu inclusion, agent launch, next-waiting/fleet/inbox actions, key bindings and triage mode.
- `rex/bin/rex-hive-actions`: derives native Rex action source from an external launch menu; `rex/bin/rex-hive-sync` copies/reloads it.
- `rex/PLAN.md` and `rex/INSTALL.md`: distinguish the floating inbox and fallback split, palette actions, target-host command routing and acceptance checks.

The brief references `leaf rex install`, but no source location or source transfer was supplied. No repository or behavior was invented. Leaf installer/palette parity is **unverified**. This does not block the public API surface contract, which is independently exercised on real disposable Rex servers.

## 1. Replace only the placement portion of agent-seat

The equivalent floating placement is now:

```sh
teerex surfaces open --socket "$SOCKET" --session "$CANONICAL_SESSION" \
  --anchor "$CANONICAL_SEAT_BLOCK" --layout float --bounds '[0.667,0,0.333,1]' \
  --label inbox -- env TZ=America/Chicago /absolute/path/agent-inbox "$SEAT_SUFFIX"
```

Use the shared named-host root route when the selected Rex server is on another command host; do not add an SSH control wrapper. If the visible terminal intentionally runs a remote viewer, its explicit argv may be `ssh -t compute-host ...`; a successful Rex placement does not prove that remote viewer is ready. The terminal's Rex host ID and the program's own remote destination are separate facts.

Change the source of placement, not the shell quoting of the old `CMD`: supply an argv array to the teerex CLI. Consume JSON only on exit 0 with `outcome:created_and_verified` and `requested_geometry_verified:true`; record `.actual.block_id`, `.actual.window_id`, `.actual.layer_id`, `.actual.rect`, `.actual.layer_bounds` and the address's explicit host/server/session. Store receipts privately. On uncertain failure inspect the exact session once; never silently fall back or retry creation.

Once the board/seat owner has replaced inbox logging, viewer reuse/idempotence and seat registration, its public seat command should compose `rex_surfaces.run` or the CLI above. Until then, **retain** agent-seat's existing seat/agent guards, inbox/log initialization, viewer checks and record ownership. Surfaces alone is not a replacement for those responsibilities.

Delete from `agent-seat` only after that acceptance:

- the raw `session.new_layer` JSON and `rex api call` placement;
- the two `rex run --split=right` fallback branches;
- `ratio()` and its recursive hand-parser;
- the repeated sleep/resize/readback loop and placement-only retry logging.

After the combined `teerex seat`/board replacement is accepted by its owner and all shell hooks call it, delete `agent-seat` itself and remove its install/link references. Do not delete `agent-inbox` until the board renderer and typed storage separately pass their own migration gates.

Intentional behavior change: failure is now explicit, with no fallback layout. If an operator chooses a tiled inbox instead, it is a separate explicit request with `--layout tiled --direction right --ratio 0.333`; teerex does not guess that choice after a floating creation might already have succeeded.

## 2. Replace terminal-launch palette boilerplate with native generated actions

Prepare each actual terminal program with `teerex surfaces palette --file ABS --name ACTION --title TITLE ... -- ARGV...`. This emits the native `rex.action` code and shares the same placement/readback implementation as CLI open. Prepare is not registration.

Use `surfaces palette install --init ABS --file ABS --socket ABS --plan ABS` to review the exact appended inclusion and single reload, then use `--apply PLAN_SHA256`. It checks the selected server's actual `client.keymap.config.path` and instance before mutation; no configured path is asserted to be running merely because it exists. It preserves the old init bytes, refuses changed plans/source/config/server and action-name collisions, and reports registration only after a fresh action list identifies the right Lua action source and generation.

For replacing an existing action name, first prepare a distinct new name and validate it in a disposable config and then in the explicitly authorized real config. Compare actual placement and terminal content. Deliberately switch callers/key bindings to the accepted action, then remove only the old action's definition/include and check/reload the selected server. Do not automatically erase the whole existing init to clear a name collision.

After those callers have migrated:

- remove `HIVE.open` only when no remaining generated/action code calls it;
- remove the corresponding terminal-opening action stanzas and generated menu boilerplate;
- delete `rex-hive-actions` / `rex-hive-sync` only if all their menu-generation/copy/reload consumers have actually moved; surfaces does not parse an arbitrary external launch menu;
- preserve independent next-waiting, inbox-toggle, status, keymap and triage behavior until their owning capability explicitly replaces it.

This is ordinary Rex configuration, not a separately installed teerex plugin system. No `rex.exec.start(detach=true)` is needed to keep any launched terminal program running. Config append/reload is explicit apply, never an implicit install side effect.

## 3. Geometry interface for boards and recovery

Boards use the returned attached pane identity and normalized geometry; they do not paste into the seat or run their renderer in a hidden worker. Recovery reconstructs visible programs root-first: open a first tab leaf in an existing (possibly empty) session, split the anchor into the desired top-level two children, then subdivide each child. Convert each saved BEFORE share to the new pane's share according to its side; right/down use `1-before_ratio`. Nested leaf creation may start its real visible program immediately; don't add a detached placeholder.

`surfaces inspect` returns actual split ancestry and layer bounds. It does not infer saved command argv, agent readiness, report-to metadata or drafts. Those remain the owning recovery/agent contracts. Explicit `surfaces focus` and `surfaces close` give operators controls over the returned IDs. Close proves the Rex block disappeared from view/list, not that all descendants or remote jobs died. `surfaces move` also supports same-session cross-tab relocation of the same attached block, with actual split/label/host readback and no recreation; real-server tests preserve the terminal child PID. A source with focus requires explicit `--focus yes` because Rex otherwise moves focus implicitly; default no refuses that case. Managed agents still use the jobs/agents owner's responsibility lock/generation path rather than bypassing it through a low-level surface call.

## Acceptance required before deleting working stopgaps

1. Run `items/surfaces/test_surfaces.py` against the exact combined binary and disposable Rex sockets on Mac/Linux. Capability-local results: 15 tests pass each on Linux API13 and Mac API10/API12/API13, with native palette prepare/load/plan/apply/invoke and explicit controls.
2. Run board/seat and recovery composition tests against these public commands, including the right-third floating inbox and asymmetric/nested split layouts. Keep requested and measured geometry separate in receipts.
3. On separately authorized real configurations, inspect the Rex.app paint and actual palette interaction: the disposable environment lacks the separately distributed tester GUI. Existing HTML terminal-content captures are not app-layout screenshots.
4. Verify seat registration/log append/viewer reuse separately; verify every old action/menu/key binding consumer has a replacement, and the actual selected server advertises/invokes the replacement.
5. Only then remove the bounded source sections listed above, and let the integrator own combined version/install/release changes. Do not delete unrelated agent-core messaging, fleet, launch or restart behavior merely because capability-1 surface tests pass.

No personal server restart, live-pane change, stopgap deletion, push, merge or release was performed by this capability worker.
