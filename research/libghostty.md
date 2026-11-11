# Rex libghostty entry

Rex builds on libghostty as a terminal engine; its documented integration surface for an external Rivet client is Rex’s terminal, control API, Lua actions, and terminal protocols. The sources do not establish a libghostty-powered API for adding arbitrary application UI to Rex.

Research checked 11 November 2026. “Entry” is interpreted below, not treated as an implementation requirement. No implementation, download of Joshua’s installed application, or runtime test was performed.

## “Entry” can refer to three different boundaries

| Interpretation | What the evidence supports | What it does not establish |
| --- | --- | --- |
| Where libghostty enters Rex internally | Superlogical’s founder explicitly says the product consumes public, MIT-licensed libghostty components. This is the terminal-engine dependency. | Exact Rex source filenames, initialization functions, C versus Zig bindings, linkage, or the version bundled in Joshua’s download. |
| Where Rivet could enter the existing Rex app | A terminal program can run in a Rex block; Rex’s CLI/Lua/server API can arrange and inspect the session, send input, and read terminal state. Terminal protocols can report application status. | That Rivet already has a suitable CLI/TUI, or that Rex understands Rivet’s application protocol. |
| Where a new native Rex application view could enter | Rex documents executable block-plugin discovery and creators/flavors. This is a distinct extension mechanism worth investigating. | A documented public renderer/view SDK, a Lua widget API, an HTML/webview host, or a supported way to register arbitrary native views through libghostty. |

The direct dependency statement is [Mitchell Hashimoto’s Superlogical announcement](https://mitchellh.com/writing/superlogical): “Superlogical will consume the same MIT-licensed components available to everyone else,” and upstream shared terminal work. The [public-testing announcement](https://www.superlogical.com/updates/public-testing-beginning) separately confirms that the Mac application hosts its own Rex server and can connect to other servers.

## The verified libghostty entry points process terminals, not application widgets

The current [libghostty-vt documentation](https://lib.ghostty.org/) defines the library as a terminal-emulation engine: feed it program output and inspect screen, cursor, styles, and scrollback. The [first-terminal guide](https://lib.ghostty.org/vt/first-terminal.html) documents these concrete C API entry points:

- `ghostty_terminal_new`: allocate terminal state.
- `ghostty_terminal_vt_write`: parse program-output bytes and update that state.
- `ghostty_formatter_terminal_new` and formatter calls: export screen snapshots as text, HTML, or VT sequences. The guide expressly warns against using the formatter for a live renderer.
- `ghostty_render_state_update` and render-state iterators: expose changed rows, cells, and styling to a host-supplied renderer.
- `ghostty_terminal_set`: register effects such as title changes, bell, clipboard requests, status reports, and replies written back to the PTY.

These are verified **library APIs**, not verified Rex call sites. Rex may use Zig interfaces or other glue. No public Rex implementation source was located in this research, so substituting these C symbols for Rex’s actual entry functions would be speculation.

The strongest statement of the ownership boundary is in the [effects guide](https://lib.ghostty.org/vt/guide-effects.html): “libghostty-vt has no window, no clipboard and no pty. Those are yours.” The host supplies the OS resources, policy, renderer, and application UI.

Ghostty also has an [internal embedding header](https://github.com/ghostty-org/ghostty/blob/108cacb17ed8990840cd14abfce43d8ed8503ca1/include/ghostty.h#L1-L12) containing `ghostty_app_*`, `ghostty_surface_*`, native-view pointers, drawing/input functions, and host callbacks. Its opening comment explicitly calls it `libghostty-internal`, tailored to Ghostty’s Mac app and not designed for external use. These symbols are not evidence that Rex exposes them, uses that exact API, or makes them available to Lua. A native surface API is not a generic application-widget SDK.

## Lua reaches Rex’s public terminal/control layer

The [full Rex Lua reference](https://www.superlogical.com/rex/docs/reference/lua) documents a `rex` table, not a `ghostty` binding. Relevant capabilities include:

| Lua-accessible capability | Documented surface |
| --- | --- |
| Start a terminal running a program | `rex.layout.block` with `flavor = "com.superlogical.terminal.shell"` and `options.command`; place it with session window/split methods. |
| Inspect or manipulate terminal state | `rex.block.call("com.superlogical.terminal", method, args)` with `format`, `title`, `pwd`, `process`, `size`, `write`, `reset`, `resize`, `set_theme`, and `program_status`. |
| Extend existing app commands | `rex.action` adds named actions shown in the command palette; `rex.bind` binds keys. `rex.client.queue` requests actions already offered by the client. |
| React to terminal signals | `rex.on` in `rex do` scripts handles documented terminal events. Event handlers are not a general configuration-load facility. |

There is no documented Lua access to raw libghostty handles, render-state iterators, effect registration, native view pointers, arbitrary widgets, or a renderer-replacement callback. `require` being available does not establish LuaJIT FFI or a supported native libghostty binding.

Two easy mistakes matter for a Rivet adapter:

- Terminal `write` means input “as if typed,” not injecting display output into libghostty. Output should normally come from the program running in the terminal.
- `format` returning HTML is a screen export, not an API for embedding an interactive HTML application in Rex.

[Server API documentation](https://www.superlogical.com/rex/docs/automate/server-api) says CLI/Lua APIs derive from the connected server’s API. Client actions requested externally require a running client with Remote Control enabled. Discovering the installed version’s methods is more reliable than assuming the website matches Joshua’s download.

## OSC 7501 is the clearest verified application-to-engine-to-Rex integration

The [official Program Status Protocol](https://www.superlogical.com/rex/docs/build/program-status) lets a program report `idle`, `working`, `done`, `blocked`, and `error`, with optional progress and structured reasons for blocking. It explicitly leaves presentation to the terminal.

There is evidence on both sides of the boundary:

- Upstream Ghostty [parses OSC 7501](https://github.com/ghostty-org/ghostty/blob/108cacb17ed8990840cd14abfce43d8ed8503ca1/src/terminal/osc/parsers/program_status.zig#L1-L35), and its [public header](https://github.com/ghostty-org/ghostty/blob/108cacb17ed8990840cd14abfce43d8ed8503ca1/include/ghostty/vt/terminal.h#L1305-L1472) provides `GhosttyTerminalProgramStatusFn`; the callback is registered with `GHOSTTY_TERMINAL_OPT_PROGRAM_STATUS`.
- Rex documents session-picker indicators, unfocused-tab spinners/blocked indicators, Lua `terminal.program_status_changed` events, and terminal `program_status` reads.

Thus a Rivet-facing terminal program could report progress and approval-waiting state without a new GUI, **if such a program or adapter exists**. This is a status channel, not a button/form protocol or an approval API. Programs still need an actual input path for the user’s decision. Reports are untrusted terminal content, not authoritative permission grants.

The website mentions mobile push and a unified inbox as future possibilities; they are not established current capabilities.

## Native extensions exist as possibilities, not Lua guarantees

The [CLI reference](https://www.superlogical.com/rex/docs/reference/cli#rex-server-run) documents `--block-dir` for executable block-plugin discovery and `--block-plugin-reload`. The [control API](https://www.superlogical.com/rex/docs/reference/api#block_creatorlist) documents `block_creator.list`, flavors, option schemas, block methods, and actions. `session.new_block` consumes a flavor that a registered creator provides; inventing a flavor name in Lua does not register a new renderer or implementation.

Those sources prove a Rex-specific block extension mechanism exists. They do not provide enough information to claim a third-party plugin can ship a custom SwiftUI view, webview, or Rivet GUI inside the installed Rex client. The plugin protocol and supported client rendering contract remain the gating questions.

At the lower-level engine boundary, libghostty-vt’s [custom-sequence hooks](https://lib.ghostty.org/vt/guide-custom-sequences.html) let an embedder handle unknown OSC/APC sequences or intercept string boundaries with `ghostty_terminal_vt_write_until`. They require native host registration and do not constitute a documented Lua hook in Rex. Unknown-sequence capture is disabled by default.

A concrete example of host/engine cooperation comes from [Hashimoto’s Kitty-graphics announcement](https://x.com/mitchellh/status/2113761797308391526): Rex rewrites file-based graphics instructions into in-band chunks for remote clients, and the work required libghostty changes. This is terminal protocol plumbing, not arbitrary application UI support.

## Recommendation and verification limits

For “use Rex as my Rivet client rather than build a separate GUI,” the supported direction to evaluate first is a Rivet CLI/TUI or terminal adapter hosted in a Rex block, with Rex actions/layouts and OSC 7501 status integration. This is a feasibility direction, not an agreed implementation plan or a claim that a complete Rivet client exists.

If Joshua needs custom graphical controls, the next research target is Rex’s executable block-plugin protocol and the shipped clients’ rendering contract. Replacing or hooking libghostty alone does not provide those controls.

Verification limits:

- Rex’s native source and exact libghostty call sites were not available here. An empty public `superlogical` GitHub repository listing is not proof no source exists elsewhere.
- Third-party posts describe raw PTY fan-out, binary snapshots, and independent client emulation. Those exact handshake details were not independently verified in official Rex implementation source and should not be promoted to a source-backed contract.
- Upstream Ghostty source was pinned to [the inspected revision](https://github.com/ghostty-org/ghostty/commit/108cacb17ed8990840cd14abfce43d8ed8503ca1), not established as the version bundled in Rex.
- This research does not claim a browser client is currently shipped merely because WebAssembly or browser WebSocket support exists.
- No Rivet implementation or compatibility test was performed. Installed-version discovery and source/API indexing are separate workstreams.
