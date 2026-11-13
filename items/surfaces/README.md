# Terminal surfaces

**Shipped experimentally in current alpha.5's combined CLI**, not as an independent cartridge. Use [current setup](../../docs/concierge/setup.md) and the [alpha.5 release support guide](../../docs/releases/v0.1.0-alpha.5.md). Mac arm64 API10/12/13 and Linux x86_64/API13 were tested; actual API11/every build and Rex.app graphical painting remain uncertified. Dated leaf-only validation below is preserved separately from released-byte acceptance.

## Who

Operators and agents placing an actual terminal program in an explicitly selected Rex session. Boards and restart recovery compose this command instead of maintaining their own placement code. This is native Rex terminal layout, not a new widget toolkit, plugin service, daemon, or Rex fork.

## What

- `surfaces open`: a labeled tiled pane beside an anchor, a floating layer in the anchor's window, or a new tab. The program starts already attached to its window; no detached intermediate.
- `surfaces inspect`: fresh actual geometry, pane `label`, `window_label`, host ID and focus/zoom state without changing them.
- `surfaces rename` (unreleased source): rename an existing window/tab or relabel an attached terminal pane by exact address, with fresh label and unchanged-focus verification.
- `surfaces move`: relocate the **same existing attached terminal** beside an attached anchor, including across tabs in the same session; no new program or replacement pane. Explicit focus intent and fresh split/identity readback are required.
- `surfaces focus`: explicitly select the given pane and its window, then verify that focus in a new view. A minimized layer refuses rather than silently restoring it.
- `surfaces close`: explicitly close the given terminal block, including a window's last pane, then verify its absence from both `session.view` and `session.list_blocks`. This is not proof of all descendant or SSH-remote processes dying.
- `surfaces palette`: prepare one new, exclusive, private Rex action fragment. This alone does **not** claim registration.
- `surfaces palette install`: preview a native-config inclusion plan; apply only the exact approved plan and verify the running server's action list. No runtime script injection or extra plugin layer.

Open never asks for focus, retries creation, falls back to a different layout, or automatically closes a pane. Rex can activate the first window of an empty session; `focus_requested:false` is a request fact, not a promise that focus never changes. A split ends an existing zoom according to Rex's API contract. Floating layers can cover other panes even without requesting keyboard focus.

## When

Use open for visible terminal tools such as an inbox, fleet board, log reader, editor or agent program. Use inspect before deciding whether an uncertain creation should be retried. Use explicit focus and close when the operator wants to act on a returned pane ID. Palette install changes selected configuration only after a plan/apply approval; preparation and planning do not register or launch the program.

## Where

Leaf commands require `--socket ABS`, full lowercase `session:UUID` and `block:UUID` mutation addresses, and Rex on PATH. The shared root supports named command-host routing (`teerex --config ABS --host NAME surfaces ...`) and a pinned Rex binary; it injects the explicit socket. Named-host config, socket, cwd, fragment, init, plan and program paths belong to that command host; files are not silently uploaded. The geometry result's `actual.host_id` identifies where Rex says the terminal lives, not where the controller runs or a command inside `ssh` executes.

The module ABI is `rex_surfaces.run(allocator, args) !u8`, importing `supervised_child`. macOS arm64 and Linux x86_64 are the validated platforms. Native placement uses the public Rex control API. Managed palette install additionally requires Python 3.9+ and stdlib `fcntl`; its bounded Rex subprocesses honor `TEEREX_REX`. No GUI client is required for server/API tests.

## Why

The old `agent-seat` floated an inbox at one third of the width and silently fell back to a split with repeated resize attempts. That hid both the requested placement and uncertainty. Surfaces requests one layout once and returns what Rex actually measured. A program-rendered terminal is the surface; teerex does not pretend to create arbitrary graphical controls.

## How

### Place a terminal and read it back

Set `SOCKET`, `SESSION`, and `ANCHOR` from the explicit server/session you intend to change. These are deliberately not guessed from environment or a focused pane. Replace program paths with executables installed on the terminal's host.

```sh
teerex surfaces open --socket "$SOCKET" --session "$SESSION" \
  --anchor "$ANCHOR" --layout tiled --direction right --ratio 0.23 \
  --label logs -- /usr/bin/tail -f /absolute/log-file

teerex surfaces open --socket "$SOCKET" --session "$SESSION" \
  --anchor "$ANCHOR" --layout float --bounds '[0.667,0,0.333,1]' \
  --label inbox -- /absolute/terminal-inbox-program

teerex surfaces open --socket "$SOCKET" --session "$SESSION" \
  --layout tab --label editor --cwd /absolute/project -- /usr/bin/vi README.md

teerex surfaces inspect --socket "$SOCKET" --session "$SESSION" --pane "$CREATED_BLOCK"
teerex surfaces focus --socket "$SOCKET" --session "$SESSION" --pane "$CREATED_BLOCK"
# Destructive only to this explicit block. The last pane also closes its window.
teerex surfaces close --socket "$SOCKET" --session "$SESSION" --pane "$CREATED_BLOCK"
```

Tiled defaults to `right` and a new-pane share of 1/3. `--ratio` always means the **new pane's share of its anchor's previous rectangle**. Thus right/down invert it when sending Rex's BEFORE share; left/up do not. Ratios must be finite, strictly between 0 and 1. Asymmetric examples matter: a new right-hand share of 0.23 means actual `rect:[0.77,0,0.23,1]` in an initially full tiled layer, not 77% for the new pane. Nested splits subdivide the current anchor rectangle. Tiled refuses a floating or minimized anchor rather than producing a different kind of placement.

Float requires explicit `[x,y,width,height]` fractions fitting inside the window, positive width/height, and a normal attached terminal anchor to identify the window. A tab requires an existing session, which may be empty, and forbids an anchor, bounds, direction and ratio. Direction/ratio apply only to tiled. Cwd, if supplied, must be absolute; if omitted Rex chooses its terminal default. Cwd existence is checked by Rex on the program host, not guessed on the CLI host. Argv travels as an array, never a shell-interpolated command string. Programs that exit remain attached for inspection.

### Rename a tab or relabel a pane (unreleased source)

```sh
teerex surfaces rename --socket "$SOCKET" --session "$SESSION" --window "$WINDOW" --label seat
teerex surfaces rename --socket "$SOCKET" --session "$SESSION" --pane "$BLOCK" --label 'review requested'
teerex surfaces inspect --socket "$SOCKET" --session "$SESSION" --pane "$BLOCK"
# The selected command host supplies its configured socket and Rex executable:
teerex --config /absolute/hosts.json --host hive surfaces rename \
  --session "$SESSION" --window "$WINDOW" --label seat
```

Supply exactly one canonical lowercase `window:UUID` or `block:UUID`; both or neither is a usage error. Labels use the same validation as open: 1–128 UTF-8 bytes, no control characters. Rename takes only socket, session, window/pane, label and optional `--timeout-ms` (default 5000, range 100–60000). It creates no terminal, requests no focus and makes one label call without retry. Unknown windows refuse with `window_not_found`; missing or detached terminal panes refuse with `pane_not_attached_terminal` before mutation.

Within the existing API10–13 surfaces guard, rename checks the connected server's `help.all.methods` for `session.set_window_label` or `session.set_block_label` before attempting that operation. Missing or unavailable capability evidence refuses with `rename_label_method_unavailable`; an API revision alone is not assumed to imply either method. Schemas and trimming behavior were checked with `rex api describe session.set_window_label --json` and `rex api describe session.set_block_label --json`; this local rename validation exercises actual Linux API13, not historical builds.

Success is exit 0 and `outcome=renamed_and_verified`, with `requested.label`, fresh `actual.label`, `requested_label_verified=true` and `control_acknowledged=true`. `previous` retains the label before the call. A new `session.view` verifies the exact target label, active window and each existing window's focused pane. Pane inspection includes both its `label` and containing `window_label`. Rex trims leading/trailing whitespace; if the actual label differs from the exact request, rename reports `label_mismatch` / `requested_label_not_verified` with nonzero exit and both values, even though the label call took effect. Choose a label without surrounding whitespace for exact verification.

A lost receipt, unavailable readback or concurrent focus change never reports verified success. `control_attempted` records only the locally received pre-call marker; missing evidence is not proof nothing changed. `retry_safe=false`, no rollback and no automatic retry apply to every result. Inspect the exact target after uncertainty before another mutation. Published alpha.5 assets are unchanged.

### Move an existing terminal beside an anchor

```sh
teerex surfaces move --socket "$SOCKET" --session "$SESSION" \
  --pane "$FINISHED_BLOCK" --anchor "$SEAT_BLOCK" --direction right --ratio 0.5 --focus yes
```

Move uses one public `session.move_block`, never close/recreate, then optional explicit `session.focus_block` and fresh view verification. Its ratio is the moved pane's NEW share, with the same direction/inversion contract as open (defaults right, 1/3). Both terminals must already be attached, in the same session, with normal source/anchor layers; the destination anchor must be tiled. Zoomed windows refuse rather than silently ending a zoom. An emptied source window/layer may be removed by Rex as part of the move, not by a separate close request.

`--focus no` is the default. Rex automatically carries a pane's focus from its source window, even if that tab was inactive, so no-focus **refuses before mutation** when the source was its window's focused pane (`focused_source_move_requires_focus_yes`). Single-pane finished tabs normally need explicit `--focus yes`. For an unfocused source, no-focus verifies the active window and surviving per-window focus identities stayed unchanged; it never restores focus by fighting another client. `yes` explicitly permits focus and verifies the moved pane is focused in the active destination.

Successful `moved_and_verified` includes `previous`, `previous_anchor`, public `move_receipt` (created/removed split IDs and revision), `control_acknowledged`, separate `focus_acknowledged`, and the same block ID/label/host plus actual destination split path/rect/share. `created` stays null and `creation_attempted:false`. Loss/mismatch returns nonzero, not a focus-only presentation claim; inspect before considering another move. This low-level surface action does not enforce a jobs registry owner/generation lock: managed-agent presentation must compose the owning jobs/agents command, not bypass its responsibility checks.

### Understand the receipt

One bounded JSON object has `schema_version:1`, `kind:surface_result` and separate evidence:

- `requested`: operation, explicit address, placement/label/cwd/argv. Keep receipts private: argv and paths may be sensitive.
- `source`: measured Rex version/platform/API; not a configured expectation.
- `creation_attempted` or `control_attempted`: an attempt frame was received, not proof of server dispatch. Loss before the frame does not prove no effect.
- `created`: returned block ID, any creation window/layer IDs, and creation revision. Missing after loss does not prove creation failed.
- `actual`: fresh `session.view` terminal identity, window/layer, layer kind/state, label, host ID, revision, normalized pane `rect` and `layer_bounds`, split ancestry, active/focused/zoomed IDs, and attachment. `split_path` entries contain `{split_id,direction,ratio,side,rect}`; their ratio is Rex's BEFORE share. Creation of a tiled pane also returns its measured `pane_share`; inspect supplies the path instead.
- `previous`: pre-control geometry for explicit focus/close. Close's successful postcondition is `block_absence_verified`, not process-tree death.
- `requested_geometry_verified`: comparison of the created or moved pane's actual layout/label to its request. Successful creation/move sets it; inspect is a read, not verification of an earlier request.
- `outcome`: `created_and_verified`, `inspected`, `moved_and_verified`, `focused_and_verified` or `closed_and_absent` succeed; `refused`, `geometry_mismatch`, `uncertain`, deadline and cancellation do not.

Geometry is in **window fractions**, not pixels or terminal rows/columns. Inactive tabs, floating occlusion, zoom, minimization and lack of a connected GUI can affect what the operator currently sees. `painted_visibility:not_assessed` and `program_readiness:not_assessed` remain explicit. API layout attachment is not proof that Rex.app painted it, nor agent/program readiness. Inspection of a minimized pane still reports its actual minimized state.

Open/inspect/focus/close default to a 5000ms local budget (`--timeout-ms 100..60000`) with bounded transport cleanup. At most 32KiB of one pending receipt and 4KiB of raw diagnostics are retained (`backend_stderr_base64` keeps arbitrary bytes JSON-safe); overly deep geometry or malformed/partial evidence refuses success. There is one supervised Rex connection, no automatic retry or close. Exit 0 means the command's stated postcondition; 1 is refusal/mismatch/uncertainty; 2 is usage; 124 deadline; 130/143 cancellation. Cancellation can leave a real created or changed pane behind. Inspect before another mutation.

### Prepare and register a palette action

Preparation writes a new 0600 file and refuses overwrite. It uses Rex's native `rex.action`; the program is launched by that action directly in a visible terminal, not as a detached `rex.exec` worker. The invoking Rex session and pane become the placement context. A tab action needs a session but no pane. A tiled or float action needs an attached normal terminal pane.

```sh
teerex surfaces palette --file /absolute/config/inbox-surface.lua \
  --name show_inbox --title 'Open Inbox' --layout float \
  --bounds '[0.667,0,0.333,1]' --label inbox -- /absolute/terminal-inbox-program

# PLAN: writes a new private plan, prints exact appended bytes and plan_sha256.
# It verifies --init against the selected server's observed client.keymap.config.path.
teerex surfaces palette install --socket "$SOCKET" \
  --init /absolute/rex/init.lua --file /absolute/config/inbox-surface.lua \
  --plan /absolute/config/inbox-install-plan.json

# APPLY only after reviewing the plan, using its exact printed hash.
teerex surfaces palette install --socket "$SOCKET" \
  --init /absolute/rex/init.lua --file /absolute/config/inbox-surface.lua \
  --plan /absolute/config/inbox-install-plan.json --apply "$PLAN_SHA256"

# After registered_and_verified, use Open Inbox in the actual Rex palette, or:
rex --autostart=false --server "unix://$SOCKET" do --session "$SESSION" --block "$ANCHOR" show_inbox
```

Init, fragment and plan must be distinct, absolute, caller-owned regular UTF-8 files (the new plan is created by planning); symlink final components and oversized files refuse. The init must already exist and be the config actually reported by the selected running server; this command does not guess/create a personal config. Reads are capped at 256KiB per file/Rex response, diagnostics at 4KiB. The embedded install controller has a 15s overall budget; each of at most four bounded Rex commands in apply has a 3s process budget. It is not a background worker.

Apply rejects changed plan bytes, fragment, init, running server instance, or loaded-config hash, and refuses an already registered action name. It appends only the previewed comment plus native `dofile(...)`, preserves existing bytes/mode, checks config, requests **one** `server.config_reload`, and verifies fresh `client.keymap` config path/instance/generation and the actual Lua action's name/source. Rex can report source paths relative to its init directory; these are resolved against that observed directory, not the controller cwd.

A plan is not registration. A prepared file is not registration. A successful reload ACK alone is not registration. Any missing/mismatched evidence keeps `registered_in_running_server:false` and nonzero status. After an append with failed/lost reload evidence, `config_updated:true` or `unknown` warns that the change may exist; there is no automatic rollback or retry. Review the exact inclusion and actual config/action list before further changes. Advisory locking excludes cooperating init writers, not another administrator ignoring that lock. Installation isn't an exclusive lease over concurrent config edits or server restarts.

For removal, deliberately remove only that action's recorded inclusion from the actual init, check/reload the selected server, verify its disappearance, then delete its fragment and plan if no longer needed. This is a reviewable native-config removal, not an automatic removal of unrelated palette actions. To update, prepare a new fragment and review the replacement inclusion; frozen generated fragments do not secretly follow installed teerex upgrades.

## Validation and boundaries

On 12 November 2026, `python3 items/surfaces/test_surfaces.py -v` passed **15 tests** in each disposable-server environment:

| Platform | Rex | API | Evidence |
| --- | --- | --- | --- |
| Linux x86_64 | preview.16 (`aa2db1b…`) | 13 | 15 tests, OK |
| Mac arm64, macOS 26 satellite | preview.13 (`1b66548…`) | 10 | 15 tests, OK |
| Mac arm64, macOS 26 satellite | preview.14 (`7e460d0…`) | 12 | 15 tests, OK |
| Mac arm64, macOS 26 satellite | preview.16 (`aa2db1b…`) | 13 | 15 tests, OK |

All used Zig 0.15.2 and checksum-pinned Rex archives already named in repository CI. The suite uses random private Unix sockets, isolated config/state, visible attached terminal programs, and cleanup of only its disposable server/session. It covers independent 23% rectangles in all four directions, nested subdivision, actual floating bounds/label/host, exact argv/cwd including quotes/Unicode, captured real terminal output, empty-session tabs/retained exits, no focus request, explicit focus/last-pane close, invalid/missing/minimized/floating anchors, loaded native palette actions, plan/apply config preservation and generation, changed plan/source/init/wrong-config refusal, lost registration evidence, cross-tab moves in all four asymmetric directions with stable block IDs/child PIDs and terminal content, explicit source-focus refusal, no-focus relocation, lost move receipts without recreate/retry, transport loss/deadlines/cancellation, and no automatic creation retry/close.

Actual terminal HTML returned by Rex was rendered in Chromium and inspected for tiled, float and tab programs with their independent API geometry receipts. These are terminal-content readbacks, **not Rex.app placement screenshots**. The disposable Mac has the CLI/server, not the separately distributed tester GUI app. No claim is made about GUI paint/palette click interaction, API11, every old/new Rex build, Joshua's personal Mac/hive/m1, or live named-host integration in this leaf-only test. See [migration](MIGRATION.md) before deleting any working agent-core code.

Optional standalone development test build (current combined root/build wiring is already shipped):

```sh
zig build-exe --dep rex_surfaces -Mroot=items/surfaces/test_cli.zig \
  --dep supervised_child -Mrex_surfaces=items/surfaces/main.zig \
  -Msupervised_child=src/child.zig -lc -O ReleaseSmall -femit-bin=/absolute/teerex-surfaces
TEEREX_BIN=/absolute/teerex-surfaces REX_BIN=/absolute/rex python3 items/surfaces/test_surfaces.py -v
```
