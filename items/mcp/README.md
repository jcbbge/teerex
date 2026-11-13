# Local stdio MCP tools

`teerex mcp` exposes the existing CLI to an MCP client through stdin/stdout. The Zig leaf execs embedded Python with `python3 -I`, passing its own absolute executable. No checkout, Python package, network listener, daemon, OAuth service or configuration write is needed. Python **3.9+** is required. The host application starts and stops the server; nothing is installed to run on its own.

This implements the handshake-based **MCP 2025-11-25** lifecycle: `initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call`, and `notifications/cancelled`. Messages are UTF-8 newline-delimited JSON-RPC 2.0. It advertises that version during negotiation, including when the client requests an unsupported version. A client unable to use it should disconnect. Modern handshake-free MCP, HTTP transports, resources, prompts, sampling, task queues and subscriptions are not advertised.

## Connect deliberately

```sh
teerex mcp --print-config claude
teerex mcp --print-config codex
teerex mcp --print-config pi
```

These print registration snippets only. Claude uses the `mcpServers` entry in `.mcp.json`; Codex uses `[mcp_servers.teerex]` in `config.toml`; Pi uses `mcpServers` in `~/.pi/agent/mcp.json` or project `.pi/mcp.json`. Follow each client's trust/approval flow. The Codex snippet requests prompt approval and allows named target environment variables through, without printing their values. No credentials, inherited environment contents or personal destinations are put in snippets. The command is this exact teerex executable; choose the installed version deliberately.

The server defaults socket/session from **its** `REX_SERVER=unix:///ABS` and `REX_SESSION=session:UUID`. A client's environment filtering may require forwarding those names explicitly. Explicit tool arguments override them. No personal endpoint, session, block, owner or registry is inferred. Supply paths on the machine running the server; it does not upload files or add named-host lifecycle routing. Rex must be available as required by the native verb (PATH or an inherited global `--rex ABS` pin). Each tool subprocess inherits the server's environment; no tool lets a client change it or choose a different teerex executable.

## Tool inventory and flag ownership

`tools/list` is the authoritative input schema. The same fixed table drives schema validation and argv construction. Underscore argument names map to the actual hyphenated flags. Unknown properties, wrong types, nonfinite numbers, malformed canonical IDs, relative paths, NULs, option-like scalar values and unsupported tools refuse before dispatch. Native verbs retain their remaining cross-flag, identity, ownership and filesystem validation and return their own refusal receipts.

| MCP tool | Existing command / flag owner |
| --- | --- |
| `observe`, `watch`, `compare` | [Observation leaf](../observe/main.zig): explicit block IDs; bounded bytes/deadline, baseline, repeated status states, optional compare view |
| `send` | [Send leaf](../send/main.zig): sender maps to `--from`; message is UTF-8 on `--message-file -` stdin, followed by EOF; draft policy and deadline remain native |
| `surfaces_resolve`, `surfaces_open`, `surfaces_ensure`, `surfaces_inspect`, `surfaces_focus`, `surfaces_close`, `surfaces_rename` | [Surfaces leaf](../surfaces/main.zig): selectors, layout/geometry, label, literal argv; ambiguity never guesses |
| `run_visible` | [Visible execution](../run/visible.py): explicit cwd/env-file/stdin-file/app/title/argv, bounded startup/execution/output, optional registry and retained pane |
| `jobs_list`, `jobs_present`, `jobs_doctor` | [Jobs leaf](../jobs/main.zig): exact registry, recorded owner/generation, reason/anchor/focus for presentation; doctor preserves unknowns |
| `agents_launch` | [Managed profiles](../agents/agents.py): config/profile and explicit launch context; managed visible protocol/ACK/brief path only |
| `boards_calls` | [Calls board](../boards/boards.py): forces `--once --json`; limit and optional named-host metadata selection |
| `doctor` | [Doctor leaf](../doctor/main.zig): bounded read-only existing-host diagnosis |
| `cartridges_list` | [Cartridge manager](../../tools/cartridges/cartridges.py): optional `--root` before `list`; no install/repair exposed |

Use `surfaces_resolve` first when a later native verb needs canonical IDs. The MCP layer performs no hidden resolution reads or automatic fallback. Watch requires a positive deadline capped at **60000 ms**, including status watches; no unbounded watch is exposed. Visible execution likewise caps its execution deadline at 60000 ms. This checkout has no observe tail flag or run-visible detach flag, so neither is invented in its schema. Future flags require updating the table and its tests when their native contracts land.

Only visible-program tools take an argv array. Its first element must be an absolute executable; direct shell and raw Rex entrypoints are refused. Program arguments remain literal after `--`, including shell punctuation and option-looking arguments. There is no generic Rex API, shell command string, arbitrary tool/verb selector or interpreter evaluation tool. This is not a sandbox: an explicitly approved program can itself execute other code, use inherited credentials, write files or reach the network. Managed agents launch only through configured profiles.

## Results, bounds and cancellation

A tool result contains the exact native `stdout`, `stderr` and `exit_code`, plus `receipt` when stdout is one complete JSON value. The receipt is decoded without relabeling its fields or inventing completion. Negative exit codes preserve subprocess signal termination. Non-UTF-8 streams are represented as base64 with an explicit encoding. The envelope appears in both `structuredContent` and a serialized text content block for compatibility. Nonzero native exits or wrapper transport failures set `isError`; the caller must still inspect the original receipt. A native usage refusal remains a usage refusal, not MCP success.

One tool runs at a time. Another call is refused immediately, never queued or retried. Input frames are capped at **256 KiB**; duplicate JSON keys, nonfinite JSON and JSON-RPC batches refuse. Combined retained child output is capped at **2 MiB**, and each invocation has a **180-second** outer deadline. Exceeding either bound cancels the owned invocation and marks a distinct `transport_error`; truncated output is never presented as a complete receipt. A nonreading stdio consumer is disconnected after a five-second write budget; unread diagnostics are best effort rather than a blocking log queue. These limits do not replace the verb's own narrower deadline. Jobs doctor can exceed the outer budget for many slow registrations; its interrupted receipt/effects remain historical and uncertain.

The server continues reading cancellation and ping messages while a worker supervises the tool. Request cancellation, stdin EOF, SIGINT and SIGTERM stop active work through its own process group, first with SIGINT and then bounded SIGKILL if needed. The leader remains unreaped until cancellation signaling is finished, preventing a reused PID from becoming a group target. No unrelated server, pane or process is killed. OS scheduling, detached descendants and already-dispatched Rex effects remain outside this cleanup guarantee. Cancellation is not an inverse mutation: inspect before any deliberate retry. The server may return the final native cancellation receipt even if a cancelling client ignores it.

## Trust and privacy boundary

Creating/closing/focusing/renaming panes, typing messages, presenting jobs, launching profiles and running visible programs all carry `readOnlyHint:false`, `destructiveHint:true`, `openWorldHint:true` and `idempotentHint:false`. Read-only tools carry the opposite read/destructive/open-world hints. These annotations inform a harness; **they do not enforce approval**. The caller must configure its own policy before enabling mutation tools. An untrusted request body or terminal capture cannot add a tool, executable override, flag, shell interpolation or autonomous follow-up operation.

Stdio inherits the local account's authority. Only connect trusted local clients; no bearer token, browser session, database role or remote authentication is introduced. Native permissions, clutch/inbox safeguards and ownership checks remain in force. Tool results may include explicitly requested private terminal text, file paths and native diagnostics; they belong to the requesting client. The MCP server's stderr logs only static tool names, exit codes and fixed transport error codes, never arguments, message bodies, captures, request IDs, environment values or credentials. The existing native calls board independently retains its normal bounded metadata. Stop the client-launched process or disable its MCP registration to turn this surface off; no persistent background switch or service is created.

## Verification and sources

```sh
REX_BIN=/absolute/disposable-test/rex TEEREX_BIN="$PWD/zig-out/bin/teerex" python3 items/mcp/test_mcp.py -v
```

The suite uses disposable HOME roots and an explicit isolated Rex server with `/dev/null` config and restore disabled. It covers handshake/schema/approval metadata, exact result passthrough, literal messages/argv/labels, bad inputs and frames, output/deadline/cancellation bounds, busy refusal, shutdown, and live observe/open/resolve/rename/close/send round trips. The same suite runs on the existing Linux/Mac runtime CI lanes, with no personal server or harness model calls. A passing protocol suite does not claim an approved interactive Claude/Codex/Pi session or hosted-CI result.

External contract sources acquired for this implementation:

- MCP [2025-11-25 lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle), [stdio transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [tools/results](https://modelcontextprotocol.io/specification/2025-11-25/server/tools), and [annotation schema](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/2025-11-25/schema/2025-11-25/schema.ts).
- [Claude Code MCP configuration](https://code.claude.com/docs/en/mcp).
- [Official OpenAI Codex MCP configuration](https://developers.openai.com/codex/mcp/).
- [Pi MCP configuration](https://github.com/badlogic/pi-mono/blob/main/packages/coding-agent/docs/mcp.md).
