# teerex

Josh's operating layer for [Rex](https://www.superlogical.com/rex): a CLI on hive for reading, watching, messaging and arranging Rex terminals. It is personal software for an opinionated SDLC. It is not a Rex fork, a daemon or a plugin.

Start with [docs/usage.md](docs/usage.md), the guide to the Rex utilities.

Licensed under [Apache-2.0](LICENSE) for teerex's original material. Third-party rights are in [RIGHTS.md](RIGHTS.md).

## What it does

| Need | Command |
| --- | --- |
| Read a pane, or wait until it changes or reports done/error | `observe` (`--tail` for the newest output, `--state` for agent state), `watch`, `compare` |
| Open, find, rename, move, focus or close panes and sessions | `surfaces open/ensure/resolve/rename/move/focus/close`, `surfaces session ensure/close` |
| Message a pane without clobbering what someone is typing | `send` (typing guard on by default) |
| Take a pane back from agents, and hand it back | `clutch take/release` (cooperative) |
| Store private evidence and decisions | `records` |
| Survive a Rex restart | `recovery snapshot/restore/update` |
| Select a configured command host | `--config ~/.config/teerex/hosts.json --host hive COMMAND …` |
| Install or roll back a verified build | `fleet install/rollback` |

Managed workers report each turn end with one `DONE` or `NOT DONE` answer. Full last words accompany completion or a flag once; waiting answers contain the wait and next check time.

An empty session attached only by app clients may be closed; see the [session close contract](items/surfaces/README.md).

Rex revision checks specify minimums. Commands verify the method and response they use, and name methods that Rex rejects.

Command receipts are JSON; help output is text. It states what was verified and labels the rest `unknown`, `uncertain` or `not_assessed`. teerex never starts a hidden process, never retries on its own, never closes a pane you did not ask it to close, and never infers that work is done. Exact flags: `teerex COMMAND --help`. For `clutch take` and `clutch release`, use `teerex clutch --help`; their subcommand help currently prints usage with exit 2. Full contracts: each `items/*/README.md`.

## Named-host recovery stores

In `hosts.json`, each host may set `"recovery_store": "/absolute/private/recovery"`,
like `records_store`. It is a path on the selected command host. If omitted,
recovery uses `<host.home>/.local/state/teerex-recovery`.

```sh
teerex --config ~/.config/teerex/hosts.json --host hive recovery snapshot
teerex --config ~/.config/teerex/hosts.json --host hive recovery inspect
teerex --config ~/.config/teerex/hosts.json --host hive recovery restore
```

Routing supplies `--root` and the selected host's socket where needed.
Explicit `--root` or `--directory` takes precedence. Snapshot creates a fresh
private timestamped folder; inspect/restore select the newest complete capture.
Restore previews first and still requires its exact confirmation to apply;
see the [recovery contract](items/recovery/README.md).

## Build, test, install

From the checkout root, with Python 3 and `uv` installed and on `PATH` (check
`python3 --version` and `uv --version`), run the build below. It obtains the pinned
Zig toolchain; the first run needs network access. Alternatively, with Zig 0.15.2
already installed, replace `uv run --with ziglang==0.15.2 python -m ziglang` with
`zig`.

```sh
uv run --with ziglang==0.15.2 python -m ziglang build -Doptimize=ReleaseSmall -Dtarget=x86_64-linux-musl   # or aarch64-macos
```

Local Git builds report `0.1.0-alpha.6.main.<12-character HEAD>`. Package them
under the matching `v`-prefixed build ID. Release packaging can set an exact
identity with `-Dversion=0.1.0-alpha.6`; without Git, the default is
`0.1.0-alpha.6`. The same option applies when cross-compiling.

- **Tests** are the Python suites under `items/` and `tools/`. They run against disposable Rex servers only. [docs/ci.md](docs/ci.md) lists them and the two current hosted lanes (Linux API13 and Mac API13).
- **Install:** `tools/install/teerex-install upgrade|rollback|list` installs a verified build into `~/.local/opt/teerex-managed`, keeping earlier versions for rollback ([docs/install.md](docs/install.md)).

## Where things are

- [docs/roadmap.md](docs/roadmap.md): what is built, what is next, and what is blocked on Rex itself.
- [docs/planning/workloads/](docs/planning/workloads/): the accepted specs behind recent features.
- [docs/releases/](docs/releases/): release notes, including the frozen alpha.1–alpha.5 history.
- [research/](research/README.md): the original Rex research and its provenance.
- Older long-form guides ([docs/alpha5.md](docs/alpha5.md), [docs/concierge/](docs/concierge/README.md), [docs/direction.md](docs/direction.md)) are kept as history. Where they disagree with this page or an item's README, the newer document wins.

Python-backed command help uses public `teerex …` names, including `teerex targets`; after building `zig-out/bin/teerex` above, `python3 src/test_help.py -v` checks the embedded CLI help without contacting Rex. To check an existing executable instead, use `TEEREX_BIN=/absolute/path/to/teerex python3 src/test_help.py -v`.
