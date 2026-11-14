# Terminal surfaces

**Shipped experimentally in current alpha.5's combined CLI**, not as an independent cartridge. Use [current setup](../../docs/concierge/setup.md) and the [alpha.5 release support guide](../../docs/releases/v0.1.0-alpha.5.md). Mac arm64 API10/12/13 and Linux x86_64/API13 were tested; actual API11/every build and Rex.app graphical painting remain uncertified. Dated leaf-only validation below is preserved separately from released-byte acceptance.

## Who

Operators and agents placing an actual terminal program in an explicitly selected Rex session. Boards and restart recovery compose this command instead of maintaining their own placement code. This is native Rex terminal layout, not a new widget toolkit, plugin service, daemon, or Rex fork.

## What

- `surfaces resolve`: read-only canonical session/pane/window resolution from an exact label, unique ID suffix or canonical ID, with original selectors and canonical IDs in separate receipt fields.
- `surfaces session ensure`: find one exact session label or create an empty session once and verify by fresh inventory.
- `surfaces ensure`: find a uniquely labelled pane or single-terminal tab, optionally focus it, or open once using the normal placement contract.
- `surfaces open`: a labeled tiled pane beside an anchor, a floating layer in the anchor's window, or a new tab. The program starts already attached to its window; no detached intermediate.
- `surfaces inspect`: fresh actual geometry, pane `label`, `window_label`, host ID and focus/zoom state without changing them.
- `surfaces rename` (unreleased source): rename an existing window/tab or relabel an attached terminal pane by exact address, with fresh label and unchanged-focus verification.
- `surfaces move`: relocate the **same existing attached terminal** beside an attached anchor, including across tabs in the same session; no new program or replacement pane. Explicit focus intent and fresh split/identity readback are required.
- `surfaces focus`: explicitly select the given pane and its window, then verify that focus in a new view. A minimized layer refuses rather than silently restoring it.
- `surfaces close`: explicitly close the given terminal block, including a window's last pane, then verify its absence from both `session.view` and `session.list_blocks`. This is not proof of all descendant or SSH-remote processes dying.
- `surfaces palette`: prepare one new, exclusive, private Rex action fragment. This alone does **not** claim registration.
- `surfaces palette install`: preview a native-config inclusion plan; apply only the exact approved plan and verify the running server's action list. No runtime script injection or extra plugin layer.

Open never asks for focus, retries creation, falls back to a different layout, or automatically closes a pane. Rex can activate the first window of an empty session; `focus_requested:false` is a request fact, not a promise that focus never changes. A split ends an existing zoom according to Rex's API contract. Floating layers can cover other panes even without requesting keyboard focus.

## Pane authority

Control dispatch protects the active registered seat and every pane in its tab,
including its tasks and board companions. Close, rename, move, resize, focus,
clutch takeover and raw input refuse there after label/suffix resolution. Splits
and floating layers anchored in that tab also refuse. Plain `send`/`ask` messages
retain the draft guard; `send --draft ignore` refuses on the protected tab.
Historical seat registrations marked `inherited_to` do not protect dead tabs.

Close, rename, move and empty-session close require the caller's `REX_SESSION` /
`REX_BLOCK` (or `LC_REX_SESSION` / `LC_REX_BLOCK`) to match the recorded creator.
Creation receipts are stored under `$XDG_STATE_HOME/teerex/pane-creators` (default
`~/.local/state/teerex/pane-creators`), separated by server. Existing managed panes
without a receipt fall back to the agents registry: starter, report-to and the
pane's own supervisor can close them. A managed scratchpad viewer admits its
starter and supervisor; its watcher can close only itself after its owner is gone.
No authority record means `no_recorded_spawner`; a foreign caller's refusal names
the recorded spawner. `AGENT_REGISTRY` selects a custom managed-agent registry.

The explicit `--operator` flag requires `TEEREX_OPERATOR=1`, interactive stdin and
stderr, and a human terminal without managed-agent markers. The registered seat
pane is an agent, never that human terminal. Managed launches strip the operator
markers. The flag permits protected control only for that interactive invocation.
These are cooperative teerex checks, not an OS boundary against another program
running as the same user. Python 3.9+ is required for guarded Rex transports.

Seat registration defaults to `$XDG_STATE_HOME/teerex-boards` (default
`~/.local/state/teerex-boards`); `TEEREX_BOARDS_STORE` selects a different store.
The focused checks in `src/test_pane_guard.py` use disposable Rex servers and
throwaway stores only, on Linux and macOS.

## When

Use open for visible terminal tools such as an inbox, fleet board, log reader, editor or agent program. Use inspect before deciding whether an uncertain creation should be retried. Use explicit focus and close when the operator wants to act on a returned pane ID. Palette install changes selected configuration only after a plan/apply approval; preparation and planning do not register or launch the program.

## Where

Leaf commands require `--socket ABS`, explicit session/pane selectors, and Rex on PATH. Surface selectors accept canonical IDs, unique ID suffixes and exact labels; resolution stays on the explicitly selected server. The shared root supports named command-host routing (`teerex --config ABS --host NAME surfaces ...`) and a pinned Rex binary; it injects the explicit socket. Named-host config, socket, cwd, fragment, init, plan and program paths belong to that command host; files are not silently uploaded. The geometry result's `actual.host_id` identifies where Rex says the terminal lives, not where the controller runs or a command inside `ssh` executes.

The module ABI is `rex_surfaces.run(allocator, args) !u8`, importing `supervised_child`. macOS arm64 and Linux x86_64 are the validated platforms. Native placement uses the public Rex control API. Managed palette install additionally requires Python 3.9+ and stdlib `fcntl`; its bounded Rex subprocesses honor `TEEREX_REX`. No GUI client is required for server/API tests.

## Why

The old `agent-seat` floated an inbox at one third of the width and silently fell back to a split with repeated resize attempts. That hid both the requested placement and uncertainty. Surfaces requests one layout once and returns what Rex actually measured. A program-rendered terminal is the surface; teerex does not pretend to create arbitrary graphical controls.

## How

### Resolve addresses and find or create a surface

```sh
teerex surfaces resolve --socket "$SOCKET" --session rivet
teerex surfaces resolve --socket "$SOCKET" --session rivet --pane worker
teerex surfaces resolve --socket "$SOCKET" --session "$SESSION_SUFFIX" --window seat
teerex --config /absolute/hosts.json --host hive surfaces session ensure --label rivet
teerex surfaces ensure --socket "$SOCKET" --session rivet --label seat --focus yes -- /absolute/seat-program
```

Resolve returns `outcome: resolved` and `resolved.session_id`, plus `resolved.block_id` or `resolved.window_id` when requested. `requested` preserves the supplied text. The same resolution runs before open/inspect/rename/move/focus/close/ensure, including anchors, in their one bounded Rex connection. Canonical IDs are literal identities: if the exact ID is absent, resolution refuses even when another label equals that ID. Other label/suffix collisions refuse; no numeric tab indexing or implicit focused target. Canonical-looking malformed IDs are usage errors. Missing targets return `target_not_found` (or the established pane/window missing-target reason), ambiguity returns `ambiguous_target`, and `candidates` contains only matching entries on ambiguity. Missing targets return no candidates or resolved IDs; the available inventory is never substituted. No match or ambiguous selection makes no mutation.

Session ensure matches **only the exact label**. One match returns `existing`; none creates an empty session with `session.create` and returns `created` only after a fresh inventory verifies that label and the receipt's ID. Several matches refuse with `ambiguous_label` and candidates. Both successful outcomes expose `resolved.session_id` and `actual`; `created` records the creation receipt only when created. No terminal/tab or focus call is made. An existing session also receives fresh identity verification.

Pane ensure takes the same placement, cwd, argv and timeout options as open, defaulting to `--layout tab`; `--focus no` is default. A terminal pane label or its single-terminal tab label identifies the same candidate, counted once. Multiple distinct candidates refuse with `ambiguous_label`; a labelled tab containing several terminals refuses with `labelled_tab_requires_single_terminal`. One match returns `existing`, with fresh geometry and canonical `resolved.block_id`; no program is restarted. `--focus yes` verifies the existing or newly created pane is focused in its active tab. No match runs open's one creation and geometry verification and returns `created`. Supply `-- ARGV...` even when an existing pane is expected, so the absent case has an explicit program. Geometry/open options are validated before any lookup.

For a server-wide singleton, use:

```sh
teerex surfaces resolve --socket "$SOCKET" --session any --pane seat
teerex surfaces ensure --socket "$SOCKET" --session any --label seat \
  --create-session "$SESSION" --focus yes -- /absolute/seat-program
teerex --config /absolute/hosts.json --host hive surfaces ensure --session any \
  --label seat --create-session rivet --focus yes -- /absolute/seat-program
```

`--session any` is reserved for global resolve/ensure. Global resolve searches attached terminal panes in **every session on the selected server**, including inactive sessions. It accepts the usual pane selector; one match returns `resolved.session_id` and `resolved.block_id`, none refuses with no candidates or resolved IDs; several refuse with only matching `candidates` carrying `session_id`, `session_label`, `block_id`, pane `label` and `window_id`. Global ensure searches **exact pane labels**, rather than tab labels. One match is reused in its actual session, with optional verified focus. No match creates in the existing session selected by required `--create-session TEXT` (ID, suffix or exact label). The creation target/anchor is unused when reusing a pane elsewhere. More than one match refuses `ambiguous_label`; an unreadable session refuses the entire search, never treating partial inventory as absence. Inventory bounds are 128 sessions and 1024 terminal panes; exceeding either refuses before creation. Global ensure does not itself create the target session: compose `surfaces session ensure` if needed. A literal session named `any` remains selectable by its canonical ID.

All pane ensure calls, including ordinary session-scoped ones, hold one advisory exclusive lock across lookup, optional creation/focus, fresh readback and bounded transport cleanup. The exact stable path is **`$XDG_STATE_HOME/teerex-surfaces/server-<SHA256>.lock`**, falling back to **`$HOME/.local/state/teerex-surfaces/server-<SHA256>.lock`** when `XDG_STATE_HOME` is unset. The hash is lowercase SHA-256 of the canonical absolute Unix socket path, so socket symlink aliases share a lock; labels and creation sessions do not split it. The selected command host owns the lock under named-host routing. The directory must be caller-owned `0700`; the stable lock must be caller-owned, single-link regular `0600`; final symlinks and unsafe modes refuse without mutation. Successful ensure receipts include `ensure_lock`. Cooperating callers must use the same state directory and server endpoint; raw Rex/other writers do not take this lock.

`--timeout-ms` (default 5000, range 100–60000) bounds lock wait plus the remaining transport budget. Contention that exhausts the pre-mutation budget returns nonzero, `failure_reason: ensure_busy`, `retry_safe: true`, and both attempt flags false. Cancellation while waiting releases resources and returns the signal status without a Rex mutation. The OS releases held locks on exit; lock files intentionally remain and must **not** be unlinked while any ensure command can be running, since that would split coordination across two inodes. Lock setup failures refuse; no fallback to an unlocked lookup. There is no pointer file, daemon or automatic retry.

Socket canonicalization uses POSIX path resolution so it can resolve the socket itself and final-component symlinks on macOS without trying to open a Unix socket as a regular file. The original descriptor-based canonicalization returned `Unexpected` before lock acquisition on Apple silicon; the existing busy-wait and socket-alias concurrency cases cover that regression in the surfaces suite.

The lock coordinates find-or-create calls, not an exclusive lease on Rex or a proof of program liveness. A noncooperating client can create the same label; fresh ambiguity refuses and callers must inspect uncertainty before retrying. Session ensure retains its separate inventory/readback contract. Neither operation destroys duplicates or restores another client's focus. These commands do not certify that a reused program is still running or ready.

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

Supply exactly one window or pane selector (canonical ID, unique suffix or exact label); both or neither is a usage error. Labels use the same validation as open: 1–128 UTF-8 bytes, no control characters. Rename takes only socket, session, window/pane, label and optional `--timeout-ms` (default 5000, range 100–60000). It creates no terminal, requests no focus and makes one label call without retry. Unknown windows refuse with `window_not_found`; missing or detached terminal panes refuse with `pane_not_attached_terminal` before mutation.

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

### Focus an existing pane from the palette

Generate a fragment with `teerex surfaces palette focus --file ABS --teerex ABS --name jump_board --title "Jump to board" --label board`. The action resolves the label (or unique pane ID) server-wide through native `surfaces resolve --session any` semantics, then focuses and verifies that pane. It refuses absent or ambiguous matches and never opens a replacement.

Add `--config ABS --host NAME` to focus a label on a named host instead of the palette server. The generated action calls `surfaces resolve --session any --pane LABEL` through that host, then focuses the returned canonical session and pane through the same named host. Missing or ambiguous labels refuse before focus; neither command creates a pane. Named focus requires `--label` and cannot combine local `--socket`, `--board-store`, or `--seat` options. Config paths belong to the palette server, while the selected host's paths belong to that command host.

For the registered seat, replace `--label seat` with `--seat --board-store ABS --socket ABS`. The explicit socket selects the board references for the palette's server; exactly one seat registration must match, and its canonical pane must still exist. Install either fragment with the normal palette install plan/apply workflow. (Jump to seat itself is native Rex Lua in rexconfig's `rex/seat.lua`.) Generation alone does not register it.

### Prepare and register a palette action

Generate complete native menus with:

```sh
teerex surfaces palette agents --profiles /absolute/profiles.json --file /absolute/agents-menu.lua \
  --teerex /absolute/teerex --rex /absolute/rex
teerex surfaces palette hosts --config /absolute/hosts.json --file /absolute/hosts-menu.lua \
  --teerex /absolute/teerex
# Install either generated file with the same palette install plan/apply commands below.
```

`--profiles` defaults to `~/.config/teerex/profiles.json`; host `--config` defaults to `~/.config/teerex/hosts.json`. `--teerex` is the installed absolute controller path on the palette server's machine; agent menus also require an absolute `--rex` pin. Generation reads caller-owned regular files with a 256KiB cap, creates one exclusive 0600 fragment, and never edits or reloads personal config. At most 128 actions/256KiB per fragment. Stable action names derive from profile or host/workspace identities. Generation freezes the menu entries; deliberately generate a new fragment and review a replacement inclusion to refresh. There is no always-on refresher or hidden config writer.

Each profile becomes **Start an agent: PROFILE**. Managed agent actions require API13 jobs; an older/unknown server revision refuses before opening either a form or worker. Invoked without arguments, the action opens and focuses one visible terminal form asking for an agent name and absolute brief-file path. That form runs `agents launch`, preserving the original invoking pane as starter and report-to; its controller tab closes after completion, and the actual worker remains a managed visible tab. Invoked through `rex do ACTION name=NAME brief_file=/absolute/brief`, it runs a synchronous controller with a 20-second command budget and immediate launch-queue refusal, leaving ACK-before-brief and responsibility tracking to `agents launch`. A timed-out/lost action is uncertainty, never authorization to retry. Profiles/defaults must already provide the selected socket, private registry, host, cwd and ownership settings; compute routing remains the profile's explicit execution/callback contract. A form-created receipt means the form opened, not that an agent started. No schema argument is treated as an inline task prompt.

Host records may add `workspaces`, an object mapping menu labels to `{ "cwd": "/absolute/path", "argv": ["/absolute/program", "arg"], "session": "session label" }`. `session` defaults to the host's configured name; `argv` defaults to `/bin/sh`. A host without `workspaces` gets one **HOST: Terminal** action in its configured home. Each **HOST: WORKSPACE** action explicitly routes session ensure and then `surfaces open --layout tab` through the named-host config, returning the latter's verified receipt. File/program paths belong to that command host. It opens a new workspace tab on each invocation, with open's no-focus-request semantics; selecting a remote session in a GUI is not claimed. A failure after session creation can leave that empty session; there is no rollback or automatic retry.

Install plans list every generated action name; apply verifies **all** names/kinds/source paths in the running server after its single reload. A partial registration refuses. Plan/apply behavior for individual action fragments remains the same.

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

Source contract additions were checked against `gh issue view 2`, `23`, `18`, the agent-core `primitives/tools/agent-messaging/{teerex-target,seat}` callers, the installed API13 `rex api describe session.create`/`session.attach`, and the [Rex native actions and synchronous command contract](https://www.superlogical.com/rex/docs/customize/actions.md) acquired during this change. The disposable Linux API13 tests cover these additions through the combined CLI; Mac palette painting and paid-harness interaction remain separate acceptance. The existing CI surfaces/targets steps discover the added cases, without a separate test runner.

### Prepared run-visible receipt publication

`surfaces close --socket ABS --session session:UUID --pane block:UUID --publish-receipt-file ABS` is an additive close-only hook for detached run-visible. The visible pane first atomically writes its exit/output and jobs/channel evidence to its private `receipt.json`, with `receipt_state:cleanup_pending_or_unknown` and `cleanup.block_absence:unknown`. The same bounded native close reads that owned regular0600, single-link, no-follow file (at most1MiB, in an owned0700 directory), requires its exact server/session/block to match, then attempts one close. It atomically publishes the verified-absence result and returns. It starts no persistent helper and never retries a close. A separate watchdog thread hard-exits this invocation at `--timeout-ms + 2000ms`, covering publication as well as the existing bounded RPC cleanup. If it is killed or publication fails, prepared execution evidence remains with unknown absence; no later process invents a successful close. Normal close calls without this flag retain their existing output/behavior.

Palette help uses `teerex surfaces palette` for menu generation and `teerex surfaces palette install` for registration.

### Close an empty session

`teerex surfaces session close --socket ABS --session TEXT [--timeout-ms N]`
resolves the existing session selector, checks all blocks (including detached
panes) and explicitly attached clients, then attempts one session destroy and
verifies absence from a fresh session list. It observes through `attach_all`
without joining the session itself. A non-empty session refuses with
`failure_reason=session_has_panes`; an attached client refuses with
`failure_reason=session_has_attached_clients`. Both return exit 1 and a single
JSON line without requesting closure. Unavailable evidence also refuses.
Success returns exit 0, `outcome=session_closed_and_absent`,
`session_absence_verified=true`, and the resolved session ID. Client/block
checks are snapshots immediately before the destroy call, not a server-side
conditional destroy; Rex exposes no conditional session-destroy method.

Verification: `TEEREX_BIN=ABS REX_BIN=ABS python3 items/surfaces/test_surfaces.py
SurfacesTest.test_session_close_empty_unattached_and_verify_absence
SurfacesTest.test_session_close_refuses_attached_and_detached_panes
SurfacesTest.test_session_close_refuses_empty_session_with_attached_client -v`.
