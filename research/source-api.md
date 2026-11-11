# Rex source and API map

Rex has a documented custom-client API, but its application source is proprietary and was not publicly available in the sources checked. This index preserves the accessible official packaging code, documentation, and release-generated API schemas without inventing internal call sites.

Checked 11 November 2026. This is research and local indexing only. Nothing was installed system-wide, deployed, or changed on Joshua's Rivet VPS. Detailed Lua capabilities and libghostty integration belong to the separate research notes.

## Start exploring

[Open the original searchable explorer](https://ampcode.com/artifacts/visuals/rex-api-explorer-7d4684ca-6429-415f-a72e-bc1d98bba436). It filters the 524 indexed entries by Public, Extensions, Delivery, Internals, and Gaps. Select an entry for its original capture source path and schema pointer. Amp access may be required.

teerex includes a [name/location-only inventory](api/catalog.json) and [capture provenance](provenance/README.md). The complete original offline bundle, `rex-source-api-map-preview15.tar.gz`, remains privately preserved outside Git history; it is not republished here without established redistribution permission. Its SHA-256 is `2868bc4e5d5bc3da0876cf7d0f7a2b5d7a34c39adac6f77a4c90a6333e8ee112`.

**Historical capture paths below are relative to the original archive's extracted `rex-index/` directory, not the teerex repository.** In that archive:

- `API_MAP.md`: navigable inventory, grouped by contract and API family.
- `index.html`: offline, searchable catalogue with category filters, pagination, and provenance for each entry.
- `catalog.json`: machine-readable symbol/topic index; paths and line numbers point into the capture, not a hypothetical Rex source tree.
- `runtime/llms.txt`: the release's own complete custom-client guide, including WebSocket handshakes, event sequencing, reconnects, terminal streams, and method/event references.
- `runtime/api-list.json`: exact input/output JSON Schemas, examples, and validation notes for the inspected server.
- `runtime/block-creators.json`: creator/flavor option schemas, block method/action definitions, and block event schemas.
- `snapshot/docs.md`: official website navigation. The linked pages have been split locally under `docs/` from the captured full Markdown export.
- `manifest.json` and `SHA256SUMS`: acquisition provenance and integrity checks (also retained as metadata under teerex's `research/provenance/`).

## Official origin, availability, and license

| Item | Finding and evidence |
| --- | --- |
| Publisher | Superlogical, at <https://www.superlogical.com/>. The product documentation is <https://www.superlogical.com/rex/docs.md>. |
| Application source repository | No public official Rex application repository was located. GitHub's `superlogical` organization identifies the Superlogical website and reports zero public repositories; its public repository-list API returned HTTP 200 with `[]`. Preserved in `evidence/github-org.json` and `evidence/github-repos.json`. This does not establish whether private access could be granted. |
| Definitive licensing evidence | Official `packaging/rex/flake.nix:156` says “Rex is proprietary”; lines 265–269 set `license = lib.licenses.unfree` and `sourceProvenance = [lib.sourceTypes.binaryNativeCode]`. Lines 1–5 explicitly say this flake packages the release binary and does not build Rex from source. |
| Price is not a source license | The [public-testing announcement](https://www.superlogical.com/updates/public-testing-beginning) says Rex is free, accountless, and self-hostable. That does not grant application source, modification, or redistribution rights. |
| Accessible source code | The official installer shell script and Nix packaging/module code were downloaded. They are not the Rex client/server implementation. The inspected package contains no standalone LICENSE file, and no separate license grant for the packaging code was identified. Public readability is not an open-source license. |
| Official downloads | <https://pkgs.superlogical.com/rex/install.sh>, <https://pkgs.superlogical.com/rex/nix/preview/0.1.0-preview.15.tar.gz>, and the release metadata endpoint <https://blob.superlogical.com/api/releases/rex/preview>. Downloading these worked without Discord authentication in this check, although the installation guide says beta commands appear after Discord login. |
| Unrelated or unofficial projects | GitHub search returned community clients/extensions, not official Rex application source. Their individual licenses do not license Rex. Distribution packages named `(R)?ex` are also unrelated. |

The precise gap is the Rex application repository and its implementation files, plus full proprietary licensing/redistribution terms. We cannot provide source-level call graphs, a build-from-source recipe, or permission to redistribute Rex. No decompilation or reverse engineering was performed.

## Revisions are explicit and different

| Material | Reproducible identity |
| --- | --- |
| Executed Linux preview | `0.1.0-preview.15`, commit `99caa8e07107e0ec57eeaa868f9f589ccd8bd7cb`, built `2026-11-10T21:59:52Z`. `runtime/version.txt` and `runtime/server-version.json` agree. |
| API | Revision 13; the binary reports support for revisions 0 through 13. `runtime/llms.txt` documents revision negotiation explicitly. |
| Binary download | `rex-linux-amd64.tar.gz`, SHA-256 `280a7366794afe3d210f19220bb5e2fb0e45add83fc2d783dce062d66b884240`, verified before execution. The archive contained only `rex`. The temporary binary/archive were removed after discovery. |
| Nix source bundle | The immutable preview URL above matches the channel download byte-for-byte. Archive SHA-256 `ae3e3fa81af3daf9453a88400f02fbab5ff88234a55a366eac1aada36699892d`. `packaging/rex/sources.json` identifies the same release commit. This is release provenance, not proof that every bundled packaging file is a checkout of that commit. |
| Website documentation | Captured `2026-11-11T20:11:44Z`, SHA-256 `226e2259aba58bb870597a39c7bb7813097a02e5bb425d833c9dfccfca5150fa` for `snapshot/llms-full.txt`. No Git revision was published with the export. Website docs and installer are rolling resources, not asserted to equal preview.15. |
| Installer | Captured 11 November 2026, SHA-256 `68b179d08bf38466422e5e52efdf507b61498f8001f554f24a589adae896b6a1`. It includes newer-looking capability checks, such as `rex server install`; these are not assumed present in preview.15. |

The website's 74 control-method names exactly match the 74 release-discovered names. This is a name-set comparison, not proof that all prose, schemas, client actions, and flags are identical across versions. The inspected binary is not asserted to be the same version Joshua downloaded.

## Public supported surfaces mean documented beta contracts

“Public” here means the publisher documents the interface for clients or automation, not a promise of a stable SDK or unrestricted privileges. Rex is in beta. Negotiate a revision and discover capabilities on the actual server before using an API.

| Boundary | Entry points | Where to read |
| --- | --- | --- |
| CLI | `rex api list --json`, `rex api describe METHOD --json`, `rex api call METHOD`, resource commands and JSON output | `docs/automate/cli.md`, `docs/reference/cli.md`, `runtime/cli-help.txt` |
| Machine-readable discovery | `GET /api/help`, `help.all`, `block_creator.list`, `session.describe_block`, `session.help` | `runtime/http-help.json`, `runtime/api-list.json`, `runtime/block-creators.json` |
| Control connection | `GET /api/control`, WebSocket subprotocol `rex.control.v1`; JSON `hello`, `welcome`, `request`, `response`, `event` messages | `runtime/llms.txt:184–538` |
| Data connection | `GET /api/data`; single-use `data.connect` tickets; binary HELLO/WELCOME/RESUME/REJECT handshake; terminal subprotocol `rex.data.terminal.v1` | `runtime/llms.txt:539–673` |
| Control methods | 74 methods across `block`, `block_creator`, `client`, `data`, `help`, `hosts`, `server`, `session`, `target` | `API_MAP.md`, `runtime/api-list.json` |
| Block methods | 18 terminal methods, plus 2 product-specific onboarding methods; schemas are exposed by the running release | `runtime/llms.txt:5072–5537`, `runtime/api-list.json#/block_types` |
| Events | Server/session event reference plus creator-specific block events and schemas | `runtime/llms.txt:732–1135`, `runtime/block-creators.json`, `docs/reference/events.md` |
| Terminal status | OSC 7501 Program Status Protocol, document revision 0.4 dated 2026-10-10 | `docs/build/program-status.md` |

Important client contracts:

- Within five seconds, send an uncompressed `hello` under 512 bytes and specify the revisions the client can actually handle. Revision 0 is the default if omitted. Never log reconnect tokens.
- Apply a bootstrap/attach snapshot first, then events whose `seq` is greater than the response's `seq`. Responses may arrive out of request order; only the documented ordered methods serialize automatically.
- `session.attach_all` observes sessions but does not join them. `data.connect` and block ownership require `session.attach` or `session.bootstrap`.
- `client.key` gives Lua key bindings first refusal. `block.event` bypasses them. A terminal's `write` injects input, not display output.
- Client-owned actions such as `pane.split` are not server methods. `client.action` does not run them; `client.perform` requests actions from a connected client, subject to that client's policy and support. The official automation guide requires Remote Control to be turned on in the app's settings; its default was not established here.
- The terminal stream starts with Ghostty snapshot data, not a generic text stream. The official guide directs non-Ghostty screen readers to `com.superlogical.terminal.format`. Exact engine integration is intentionally left to the libghostty research.

## Scripting and extension boundaries

| Surface | Documented extent | Limit |
| --- | --- | --- |
| Lua configuration | `init.lua`, `rex.bind`, `rex.mode`, `rex.action`, hosts, layout helpers and JSON helpers | Load-time and action-time APIs differ; not a general graphical widget API. |
| Lua scripts | `rex do`, dynamic `rex.call` and session/block helpers, events and process execution | Runtime/context restrictions are indexed, not analyzed in depth here. |
| Client scripts/actions | `client.set_script`, `client.keymap`, `client.perform`, `client.reply`; Mac/iOS action names | A known action name does not implement the action in a new client. |
| Executable block plugins | Public `rex server run` and `rex login-server` flags `--block-dir DIR` and `--block-plugin-reload`; module options `blockDirs` and `reloadBlockPlugins` | Discovery/reload is documented. No executable plugin handshake/ABI or arbitrary-view renderer registration SDK was located in the captured official docs or release guide. |
| Creator/flavor contract | `block_creator.list` exposes names, flavors, option schemas, methods/actions, event schemas. `session.new_block` or a layout consumes a registered flavor. `session.describe_block` exposes a particular block's methods/events and placement. | Selecting a flavor does not register a plugin or a renderer. The schema does not describe a SwiftUI/HTML/webview/native-view payload or a client-side renderer installer. |

### What is established about graphical blocks

The inspected default server advertises `com.superlogical.terminal.shell` and `com.superlogical.onboarding.onboarding`. The latter is explicitly “a walkthrough ... shown by the client”, with `state`, `set_step`, and `step_changed`. Thus the block model is not terminal-only, and a built-in nonterminal client presentation exists.

The publicly documented generic client side provides block identity (`creator_name`, `flavor`), layout rectangles, methods/events, data tickets/streams, and key/paste/mouse/wheel/focus input. For terminal rendering the release guide specifies the stream and snapshot boundary. Neither the creator/flavor metadata nor the inspected `session.view` block schema contains a renderer registration or arbitrary UI description contract.

**Conclusion:** executable plugins and nonterminal built-in blocks exist; support for a third-party arbitrary graphical block inside the shipped Rex clients is unestablished, not disproven. The missing evidence is a supported executable-plugin protocol and a renderer/client contract explaining how an unknown creator's view is registered, delivered, negotiated, sandboxed, and installed on Mac/iOS/other clients. A new independent Rex client could choose its own UI, but that is not proof Rex.app can host it. Ask Superlogical for those contracts before choosing an in-app native Rivet UI.

## Accessible source and inaccessible internals

| Local source path | Role and provenance |
| --- | --- |
| `packaging/install.sh` | Official rolling installer. Distribution selection, package repositories, download/checksum handling, tarball/user setup. Read only; never executed. |
| `packaging/rex/flake.nix` | Prebuilt package construction, binary provenance/license metadata, exported NixOS/home-manager modules and packaging checks. The file identifies its upstream location as `packaging/nix`. |
| `packaging/rex/nixos-module.nix` | Shared/login server configuration, accounts, Tailscale/listener options, systemd/socket activation, integration assertions. |
| `packaging/rex/home-manager-module.nix` | Personal server, user-level configuration, terminfo and SSH integration. |
| `packaging/rex/update.sh` and `sources.json` | Packaging release metadata refresh and exact artifact URLs/checksums. |
| `packaging/rex/50-rex.conf`, `xterm-rex.bin`, `flake.lock` | SSH terminal-type fallback, compiled terminfo, pinned Nix dependency metadata. |

Official packaging comments mention private-tree paths including `internal/pam/pam_dlopen.go`, `internal/terminfo`, `internal/sshconfig`, `internal/install/units/rex.service`, `packaging/systemd`, `packaging/nfpm/nfpm.yaml`, and `.github/scripts/pack-flake.js`. They are indexed as **references only**. Those files were not retrieved, and comments are not evidence of their current contents or public APIs. There is no invented map of the server's packages, Swift views, libghostty call sites, persistence internals, or plugin host.

## Small learning levels for a Rivet-facing client

These are possible next increments, not implementation completed in this research:

1. **Read-only discovery:** capture Joshua's `rex version`, `server.version`, and `rex api list --json`; compare with this release. Inspect the existing Rivet transport separately rather than assuming it.
2. **One command in one terminal:** if Rivet has a suitable CLI/TUI or a small adapter is later chosen, run it in a terminal block. Learn session/block IDs and screen capture before building a full client.
3. **One action and one status:** add a single action or launch shortcut; only then evaluate OSC 7501 for a concrete progress/approval-waiting state. Status is not an authorization API.
4. **One persistent workflow:** evaluate a narrowly scoped event-driven integration using documented CLI/Lua APIs. Do not assume the Rex and Rivet protocols are interchangeable.
5. **Installable delivery:** later package the adapter/configuration with pinned versions and a private-network connection to the dedicated VPS. Choose personal versus shared versus login server intentionally. If distributing Rex itself, first obtain its redistribution terms. No installable Rivet integration has been created here.

For the VPS, the current official remote-access guide is consequential: a connection can do anything the Rex server account can. Default Unix sockets, Tailscale, or an SSH socket forward are preferable to open listeners. `--allow-anonymous` gives every reachable caller full access; do not expose it on the public Internet. `rex hosts` is currently CLI-only and does not synchronize to the GUI.

## Reproduction and validation

Inside the original extracted `rex-index/` directory, `manifest.json` records URLs and hashes. To verify those captured files without networking, run `sha256sum -c SHA256SUMS` there. To regenerate the original derived index from those same inputs, run `python3 rebuild.py` there. Neither command installs Rex or contacts a server; teerex intentionally does not ship the vendor inputs needed to run them.

Validation completed in the original research: all 83 checksum entries passed both in the working directory and after extracting the archive; all 524 source references and JSON pointers resolved; repeated generation produced identical derived files. The website/runtime comparison matched all 74 control-method names. Browser checks exercised search, category filters, pagination, selection and empty states; the 360-pixel Chromium layout had `scrollWidth = innerWidth = 360`. Final captures and a 16.9-second pointer interaction recording were inspected. These checks validate the index, not unexercised Rex operations.

The runtime capture used a downloaded, checksum-verified release binary and an isolated Unix socket with `--restore=false --config /dev/null`; no terminal sessions were created. Only `version`, help, API discovery, `server.version`, `help.all`, and `block_creator.list` were exercised, plus read-only `GET /api/help` and `GET /llms.txt`. The supervised process was stopped. This verifies discovery/documentation, not every advertised operation or a Rivet connection.

For a later refresh, fetch the full website export and the immutable release artifacts listed in the manifest into a **new** directory. Use the official CLI discovery commands on that release or Joshua's server. Do not silently overwrite this capture or treat the rolling website as a Git revision. The server guide documents fetching `/api/help` and `/llms.txt` from a server; on a Unix socket use `curl --unix-socket PATH` with a placeholder host.

## Out of scope and unresolved

- No access to Joshua's installed Mac app, Discord account, or VPS was needed or attempted.
- No Rivet API implementation, compatibility test, product code modification, installation, deployment, or installable delivery occurred.
- No long-term compatibility promise, arbitrary-native-view SDK, public plugin ABI, or Rex redistribution license was established.
- The full application-source gap remains. The public custom-client wire protocol is **not** a gap: it is preserved in `runtime/llms.txt`.
