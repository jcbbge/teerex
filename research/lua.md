# Rex can provide Rivet’s terminal workspace without a new GUI

Rex documents a substantial Lua automation interface for inspecting and arranging sessions, running terminal programs, reacting to events, and exposing custom actions. It is a credible foundation for a **terminal-first Rivet visibility/control client**. It does **not** document a general Lua GUI/widget API or a built-in Rivet integration.

Research checked on **11 November 2026**. “Documented” below means verified against current official documentation, **not tested on Joshua’s downloaded build**. No Rex binary or Joshua’s VPS was available in this workspace, and no Rivet integration was implemented.

## Start with the installed server’s contract

The official [Lua API](https://www.superlogical.com/rex/docs/reference/lua) says Rex runs **Lua 5.1** and adds APIs only through the global `rex` table. The full standard library is available, including `io`, `os`, and `require`, except that **`io.popen` and `os.execute` raise errors**. Rex supplies `rex.exec` instead.

This is enough for Lua logic, files, modular configuration, JSON, external commands, and Rex control. It does not establish LuaJIT, FFI, C-module compatibility, LuaRocks installation, or bundled LuaSocket/HTTP/WebSocket libraries. Do not design around those without checking the actual runtime.

Rex’s [server API discovery](https://www.superlogical.com/rex/docs/automate/server-api) is especially useful for incremental learning. `rex api list --json` and `rex api describe METHOD --json` return the connected server’s methods, schemas, and examples. `rex version` reports the installed binary; `rex server status` reports the running server, which may still be an older version. Online reference pages can include Snapshot-only features. [Version and upgrade details](https://www.superlogical.com/rex/docs/linux/upgrading).

## Configuration and CLI scripts have different jobs

| Surface | Loading and execution | What to use it for |
| --- | --- | --- |
| Server configuration | `$XDG_CONFIG_HOME/rex/init.lua`, otherwise `~/.config/rex/init.lua` on macOS/Linux; `%AppData%\rex\init.lua` on Windows. `REX_CONFIG` overrides the path in the **server process’s** environment. `require("keys")` can load sibling modules. | Persistent key bindings, modes, named actions, other Rex host declarations. |
| CLI script | `rex do ./script.lua`, `rex do -e '...'`, or `rex do - < script.lua`. Runs **locally wherever the CLI runs**, against the selected Rex server. | One-shot automation and long-running event/timer scripts. |
| Connection-scoped scripts | The server API’s `client.set_script` accepts Lua sources for the calling client connection. | A separate advanced extension point; not interchangeable with a normal `rex do` script or a documented Mac GUI plugin installer. |

### Configuration is declarative at load time, executable when invoked

The configuration runs top to bottom on load, registering bindings and actions. Live server API calls such as creating a window **fail at configuration load time** because there is no client context. They work later inside an action/key callback.

Use `rex config check` to load and diagnose configuration and `rex config reload` to apply it. There is **no automatic file watching**. The file lives on the Rex server’s machine, and reload must use that machine’s local connection; remote reload is refused. A Lua syntax/runtime failure that prevents loading preserves the previous working configuration. Invalid individual Rex declarations can instead be skipped with diagnostics while the rest loads. Configuration is executable Lua, not a security sandbox. [Configuration documentation](https://www.superlogical.com/rex/docs/customize/config).

`rex.action{ name, title, run, ... }` adds a named action to the command palette, key bindings, and CLI. Actions can declare typed arguments or JSON Schema and receive session/block/client context. `rex.invoke` composes custom actions. `rex.client.queue` asks an actual GUI client to perform its own action; it needs a client and CLI-driven app control requires the app’s **Remote Control** setting. The available client actions depend on the client/build. [Custom actions](https://www.superlogical.com/rex/docs/customize/actions), [keyboard shortcuts](https://www.superlogical.com/rex/docs/customize/keyboard-shortcuts).

### CLI scripts can remain alive, but they are not installed services

Inside a Rex terminal, a script defaults to that terminal’s session/block. `-s` and `-b` select targets; `--all` explicitly requests events across sessions on the selected server. Arguments become `rex.args`; the returned value prints as JSON. API failures normally return `nil, error_message`, so scripts must check them. Raising a Lua error exits a one-shot script with status 1; `rex.stop(code)` chooses the exit status.

A script normally finishes after its top-level code. Registered event handlers or active timers keep it running. `rex do FILE --action NAME` can try an action from a draft configuration without reloading it. **Trying it really performs the action.** [Lua scripts](https://www.superlogical.com/rex/docs/automate/lua-scripts).

## The exposed API covers useful visibility and control

| Need | Documented surface | Consequence for Rivet |
| --- | --- | --- |
| Discover Rex state | `rex.call(method, args)` calls server methods by full name, including `session.list` and `session.create`; session-specific helpers are under `rex.session`. | Inventory sessions and construct a workspace. These are Rex objects, not automatically Rivet jobs. |
| Inspect and arrange the workspace | Session view, block/client listing, block description; create windows, splits, detached blocks and floating layers; move/swap/detach/float/zoom/resize/focus; label sessions/windows/blocks. | Arrange logs, agent terminals, a status TUI, and controls without building window management. |
| Start visible programs | `rex.layout.block` with terminal flavor `com.superlogical.terminal.shell`; options include `command`, `shell`, `cwd`, `initial_input`, and keeping output open after exit. Horizontal/vertical layout builders compose panes. | Run a Rivet CLI or terminal dashboard **if one exists or is built**. A terminal block runs its program on the server hosting that block. |
| Read terminal information | `rex.block.call` provides `format` (text/HTML/VT screen representation), `process`, `pwd`, `title`, `size`, `program_status`, and `list_dir`. | Observe terminal screens/processes/status. HTML formatting is an export format, not evidence of an HTML widget renderer. |
| Control terminals | Block methods include `write` (bytes as though typed), `reset`, `resize`, and `set_theme`; server methods also provide input-event delivery and block close. | Can operate terminal programs, but sending text is not a typed Rivet control API or proof of successful execution. |
| Custom user commands | `rex.bind`, `rex.unbind`, modes/sequences, `rex.action`, `rex.invoke`, `rex.client.queue`. | Add an “Open Rivet workspace” or similarly scoped command without a new GUI. Actual Rivet commands remain to be established. |
| Files, structured data, commands | Standard `io`, `require`, `rex.json.encode/decode`, `rex.exec`, `rex.exec.start`, logging. | Bridge to existing tools or a small external adapter rather than assuming native networking support. |
| Other Rex servers | `rex.host` in configuration, `rex.servers()`, `rex.server(label)` returning remote `call/session/block` helpers. | Operate a VPS Rex server. Explicit session/block IDs are needed for calls through `rex.server(label)`. |

Sources: [full Lua reference](https://www.superlogical.com/rex/docs/reference/lua), [server API discovery and Lua calling conventions](https://www.superlogical.com/rex/docs/automate/server-api), [server method reference](https://www.superlogical.com/rex/docs/reference/api).

`rex.session.*` fills in the session where appropriate; `rex.call` does **not** supply the same default session for an arbitrary full-name call. Do not assume every block-targeted session method fills in a block ID. The [Lua API](https://www.superlogical.com/rex/docs/reference/lua) distinguishes these contracts.

## Events and timers support reactive visibility

`rex.on(event, fn)` and `rex.wait(event, filter, timeout)` expose session/server events and terminal events. Useful examples include layout changes, session/block creation and closure, client connections, title/cwd changes, foreground-process changes, bell, notifications, progress, and program-status changes/removals. `block_event` catches all block events. Handlers register at script load and run **one at a time**. A misspelled event name is accepted but never fires. [Event tutorial](https://www.superlogical.com/rex/docs/automate/lua-events), [event reference](https://www.superlogical.com/rex/docs/reference/events).

Important boundaries:

- **`rex.on` does not work in `init.lua`.** It warns and never receives events. Timers, `rex.sleep`, `rex.wait`, and `rex.stop` are CLI-script APIs, not configuration APIs.
- `rex.after` and `rex.every` keep scripts alive. Timers do not run concurrently with other Lua. Missed repeating ticks collapse into one invocation; at most 1,024 active timers are allowed.
- Sleeping or waiting inside a handler blocks other script work. Errors in handlers/timers are reported and normally do not terminate the watcher; `--fail-fast` changes this.
- `terminal.child_exited` means the terminal’s direct child exited, usually the shell. It is **not** an event for every command typed into a shell.
- The published event list does not promise an arbitrary terminal-output-chunk callback in Lua. Screen snapshots and structured status are documented. Lower-level block data streaming is a separate server/WebSocket API, outside the Lua convenience surface.
- Session persistence does not establish persistent Lua watchers, event replay, or automatic resubscription after a failed watcher. Starting/supervising a watcher is separate work. Keep important Rivet state outside a GUI/CLI process.
- Handler API defaults use the event’s session; timer defaults use the script’s original session. Cross-session handlers must carry the intended IDs into timer callbacks. `--all` does not by itself establish a multi-host event subscription.

## External commands are the practical bridge, with lifecycle limits

`rex.exec(argv, opts)` runs an argument array **without a shell**, with cwd/environment/stdin/timeout and captured stdout/stderr. Nonzero command exit is a result, not a Lua API failure: check `result.ok` or `code`. `rex.exec.start` adds streaming stdout/stderr callbacks, writable stdin, process ID, wait, kill, and running-state inspection. Chunks can end mid-line. [Command API](https://www.superlogical.com/rex/docs/reference/lua), [examples](https://www.superlogical.com/rex/docs/automate/lua-scripts).

JSON also has conversion limits: `rex.json.decode` converts `null` to `nil` and drops null array entries; an empty Lua table encodes as an object. Preserve these distinctions if a future Rivet bridge relies on nullable or positional data.

This documents the ingredients for invoking a Rivet CLI, `curl`, `ssh`, or an external event-stream adapter. **It does not verify that Rivet has those interfaces, their schemas, authentication, or compatibility with Rex.** No built-in `rex.http`, `rex.websocket`, or Rivet client is listed in the full Lua API.

For `rex do`, local subprocesses use the CLI machine. Selecting a remote Rex server does **not** relocate the script or its `rex.exec` process to the VPS. Start a program in a remote terminal block, run the CLI on the VPS, or use an explicit remote command when remote execution is intended.

Commands are scoped to the work that started them. Rex stops them when an action/handler/timer returns or a script’s top level finishes unless `detach = true` is used. A detached command is not thereby a supervised service. Configuration actions have a **30-second** execution budget; key-bound Lua functions have **5 seconds**. A command timeout and those caller limits are separate constraints. Long-running Rivet workers should not depend on a palette action staying alive. [Actions](https://www.superlogical.com/rex/docs/customize/actions), [server reference](https://www.superlogical.com/rex/docs/reference/api).

## Program Status Protocol offers native visibility, not approvals

Rex supports **OSC 7501**, the Program Status Protocol. A program in a terminal can report `idle`, `working`, `done`, `blocked`, or `error`, plus progress, identity, title/message, and a blocked kind such as `permission`, `question`, or `auth`. Hierarchical IDs allow several worker records in one terminal.

Rex documents current session-picker indicators, unfocused-tab activity/blocked indicators, and Lua `terminal.program_status_changed` events; Lua can also query `program_status`. This is a promising low-friction way for a future Rivet command/adapter to expose agent/task attention state without scraping screen text. **Rivet emitting these sequences is proposed integration work, not a verified current capability.** [Official protocol and current Rex behavior](https://www.superlogical.com/rex/docs/build/program-status).

The protocol only communicates status. It does **not** approve work, send a response, enforce permission, or supply arbitrary controls. `blocked:kind=permission` must never be mistaken for an authorization channel. Mobile push and a unified priority inbox are listed as future plans, not current guarantees.

## There are extension hooks, but no verified Lua GUI toolkit

The [server method reference](https://www.superlogical.com/rex/docs/reference/api) documents `client.set_script`: Lua sources replace scripts on the **calling connection**, apply across that connection’s attached sessions, and an empty list unloads them. Invalid/overlong loading preserves previous scripts; load has a five-second limit. `client.keymap` exposes bound function keys and must be refreshed after loading. The call cannot select another `client_id` or a `session_id`.

This matters because the user-facing Lua reference describes config and `rex do`, where script bindings have no useful effect, while the server reference also describes connection-scoped key scripts. Treat them as **different pathways**. The checked documentation does not fully specify the latter’s available standard libraries/events/command execution or provide a Mac UI workflow for installing them. Do not infer that a one-shot CLI call installs a lasting plugin into Joshua’s app connection.

The [CLI reference](https://www.superlogical.com/rex/docs/reference/cli) also exposes `--block-dir` for executable block plugins and `--block-plugin-reload`. That is evidence of an extension mechanism, **not** evidence that Lua can register a new block renderer or that a stable public plugin SDK is documented. The full Lua API lists no custom widget, toolbar/sidebar renderer, arbitrary native dialog, canvas, or webview-construction API. A custom terminal dashboard remains different from custom native Rex UI.

## A dedicated VPS fits, but access is powerful

The current [installation documentation](https://www.superlogical.com/rex/docs/linux/installation) supports Linux servers, although downloads/install instructions remain beta-gated through Discord. This is newer than the October launch post’s initial macOS-only testing scope. For one person, the official [server-modes guide](https://www.superlogical.com/rex/docs/linux/server-modes) recommends a personal server.

A practical later arrangement is Rex for Mac connecting to Rex on the Rivet VPS, with terminal work and any always-on observer running on the VPS. This is a recommendation, not a completed deployment. The Mac’s configuration and the VPS’s server configuration are not one shared filesystem; reload on the owning machine.

**Anyone connected can do anything the server can, including starting programs as its OS account.** This is not a read-only telemetry boundary. Keep it off the public Internet: official guidance recommends Tailscale, with SSH Unix-socket forwarding or another tightly controlled VPN as alternatives. Do not expose anonymous HTTP on a public VPS. Rivet’s own mutation/approval permissions still need their own enforcement. [Remote access and security](https://www.superlogical.com/rex/docs/linux/remote-access).

For durable work, plan server upgrades as well: a shared-server package upgrade restarts it and ends its sessions/programs; personal/account-server behavior differs. [Upgrade semantics](https://www.superlogical.com/rex/docs/linux/upgrading).

## Learn one small contract at a time

These are suggested experiments, **not changes made in this research**:

1. **Inspect first.** Record local and running-server versions; inspect session listing, one session view, terminal `format`, and `program_status` with the server’s own schemas. This establishes what Joshua’s actual build exposes.
2. **One visible action.** Try a separate `rex do` script that labels a block or opens a known terminal command. Learn IDs, results, and error handling before editing persistent config.
3. **One reusable command.** Turn that action into a named configuration action and key/palette entry. Use config check/reload; keep it quick and reversible.
4. **One observer.** Run an explicit-session event watcher or timer and observe one real terminal event. Then consider structured Rivet status via a terminal command/adapter and OSC 7501, if Rivet’s actual interfaces support it.
5. **One guarded control.** After Rivet’s interface is established, add one intentional command through its real API/CLI, with errors and confirmation handled at the appropriate boundary. Do not begin with automatic approvals or arbitrary screen-text execution.
6. **Move the proven pieces to the VPS.** Keep the first connection private, use an unprivileged account, place scripts where their commands/data live, and arrange supervision only for observers that must outlive the laptop.

## Evidence and remaining unknowns

The claims above come from current official documentation, read in full for the Lua/config/action/event pages and checked against relevant server/CLI references. **No public Rex core/Lua-runtime source repository was located.** The [Superlogical GitHub organization](https://github.com/superlogical) currently reports **zero public repositories** through its [public GitHub metadata](https://api.github.com/users/superlogical). The official Linux docs explicitly say its Nix flake packages the release binary rather than building Rex from source. This does not prove there is no source elsewhere or privately; it means Lua engine internals were not source-audited here.

No claim here establishes behavior on Joshua’s downloaded build, an end-to-end Rex–Rivet integration, a stable native UI/plugin API, bundled networking/C libraries, durable watcher replay, or Rivet’s specific control/authentication contract. Those remain validation or integration questions. The recommended starting point needs none of those assumptions: **existing Rex terminals, a small explicit Lua action, and one observable state change at a time**.

Out of scope: libghostty internals, the complete source/server transport map, and implementation or VPS changes.
