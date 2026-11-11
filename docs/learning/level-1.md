# Level one: meet your installed Rex

**Goal:** learn which Rex binary and running server you actually have, and which APIs that server advertises. No scripts to install, no config edits, no Rivet connection, and no VPS work. You can stop after any step.

This is a guided observation, not a test already completed on your machine. The research inspected Linux `0.1.0-preview.15`, API revision 13; your app/server may differ. There is no requirement to upgrade or make the numbers match.

## 1. One small observation

Use a terminal on the machine where you already use Rex. For now, do not SSH to the VPS, select a different server, install a CLI, or enable Remote Control. If you're unsure which machine a terminal belongs to, stop and ask before running anything.

Run just:

```sh copy Copy Version Command
rex version
```

This reads the CLI version. It does not tell us which version a running server uses. If you see `command not found`, stop: tell me your operating system and the Rex app's About/version text. Do not download a different binary or guess a path to work around it.

You can send that small result now, and we can take the next step together.

## 2. Look before connecting

```sh copy Copy Help Command
rex --help
```

Find the global `--autostart` option. The captured preview's default was **true**: a seemingly read-only CLI query could start a missing local server. For this level, every server-facing command below explicitly uses `--autostart=false` to prevent that. If your help lacks this flag, or the syntax differs, stop and share the relevant help before continuing. Do not retry by dropping the flag.

Also check that you have not intentionally selected a remote server in your shell or Rex setup. If the active target is unclear, stop at version/help and ask; do not assume it is the Mac just because the terminal window is on a Mac. We have not established your connection settings and will not guess or connect to your VPS.

## 3. Identify the existing local server

Once the target is known to be your already-running local server:

```sh copy Copy Server Status Command
rex --autostart=false server status
```

Read the address/status locally. Do not post full connection details, authentication links, or tokens. If no server is running, stop — do not start, restart, install, upgrade, or repair it for this exercise. `--autostart=false` also does not promise to suppress activation by an existing external service manager; use this step only for a server already known to be running.

Then inspect the running server's advertised version:

```sh copy Copy Server Version Command
rex --autostart=false api call server.version
```

Compare the binary's version with the server's version/API revision. A difference is useful information, not a reason to restart. An unsupported method, timeout, or connection error is a result too: stop and share a redacted error rather than changing the server.

## 4. Discover; do not invoke arbitrary methods

```sh copy Copy API List Command
rex --autostart=false api list --json
```

This asks the selected server for its available methods and schemas. **An API list describes capabilities; it is not a list of commands to try.** Some methods create sessions, type input, run actions, or close blocks. The only actual API invocation in this guide is the read-only `server.version` query above.

Look for `session.list`, `session.view`, `session.describe_block`, `com.superlogical.terminal.format`, and `com.superlogical.terminal.program_status`. If a name is absent, record that rather than substituting another operation. The research's 74 control methods are a historical count, not a required test outcome on your version.

Choose just one present method and read its contract, for example:

```sh copy Copy Describe Command
rex --autostart=false api describe session.list --json
```

`describe` does not call `session.list`. Read the required input fields, result fields, and examples. Do **not** execute examples automatically. Session/block inspection may expose terminal contents or attach a client; we will select a known target and review the actual schema together before taking that optional next step. No need to inspect a terminal screen to finish level one.

## 5. Bring back a tiny, redacted note

You do not need to upload the entire API dump. Keep personal observations out of Git history; `local/` is ignored if you choose to save notes inside your checkout. Never commit terminal screens, secrets, reconnect tokens, auth links, private hostnames, or personal paths.

```text copy Copy Observation Template
Machine/OS (no hostname):
Rex CLI version:
Existing local server version / API revision:
Any CLI/server mismatch:
API names found (names only):
One method I described:
What its input/result taught me:
Redacted error or question (if any):
```

Success is understanding one real contract and knowing what remains unknown. It is not proving Rivet integration or changing persistent settings. With that note, we can pick one useful next experiment, such as reading one existing session's structure. We will ask before accessing any runner and before making configuration, installation, or VPS changes.

## References

- [Official server API discovery](https://www.superlogical.com/rex/docs/automate/server-api)
- [Official CLI reference](https://www.superlogical.com/rex/docs/reference/cli)
- [Version/upgrade distinctions](https://www.superlogical.com/rex/docs/linux/upgrading) — reference only; no upgrade is required here.
- [Captured source/API findings](../../research/source-api.md) and [Lua findings](../../research/lua.md)
