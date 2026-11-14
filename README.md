# teerex

Josh's operating layer for [Rex](https://www.superlogical.com/rex): one CLI that every agent and every human uses to run, watch, message and arrange work in Rex terminals on his machines (hive and the M5). It is personal software for an opinionated SDLC. It is not a Rex fork, a daemon or a plugin.

**Agents start with [docs/agents.md](docs/agents.md)**, the one-page guide to every verb an agent uses.

Licensed under [Apache-2.0](LICENSE) for teerex's original material. Third-party rights are in [RIGHTS.md](RIGHTS.md).

## What it does

| Need | Command |
| --- | --- |
| Learn the basics with six pages of live practice; Enter continues, q cleans up | `tour` |
| Read a pane, or wait until it changes or reports done/error | `observe` (`--tail` for the newest output, `--state` for agent state), `watch`, `compare` |
| Run a command in a visible tab and get its real exit and output | `run-visible` (`--detach` returns at once; `run-visible receipt` reads the result) |
| Open, find, rename, move, focus or close panes and sessions | `surfaces open/ensure/resolve/rename/move/focus/close`, `surfaces session ensure/close` |
| Start an agent that acknowledges its protocol before its brief, is tracked, and reports its stop | `agents launch` (from profiles), `agents human` (Josh types `claude`/`codex`/`pi`) |
| Keep the current task and later work visible beside each agent | `scratch init/now/todo/done/show/path/watch` |
| Message a pane without clobbering what someone is typing | `send` (typing guard on by default), `ask` (decision cards) |
| Take a pane back from agents, and hand it back | `clutch take/release` (cooperative) |
| Let a sandboxed child report back | `run-visible --channel-dir`, `agents channel`, `agents fence-probe` |
| See who owns what and what ran | `jobs`, `boards fleet`, `boards calls` |
| Survive a Rex restart | `recovery snapshot/restore/update` |
| Work on another machine by name | `--config ~/.config/teerex/hosts.json --host hive\|m5 COMMAND …` |
| Install, run and remove single-purpose payloads | `cartridges install/list/run/remove/doctor/repair` |
| Use teerex as native agent tools | `mcp` (stdio MCP server; `--print-config claude\|codex\|pi`) |
| Record and replay terminal sessions | `replay record/play/live` |
| Check the machine | `doctor` |

Managed workers report each turn end with one `DONE` or `NOT DONE` answer. Full last words accompany completion or a flag once; waiting answers contain the wait and next check time.

An empty session attached only by app clients may be closed by its recorded creator or the operator; see the [session close contract](items/surfaces/README.md).

Command receipts are JSON; help and interactive tour output are text, and `mcp --print-config` emits the selected client’s registration format. It states what was verified and labels the rest `unknown`, `uncertain` or `not_assessed`. teerex never starts a hidden process, never retries on its own, never closes a pane you did not ask it to close, and never infers that work is done. Exact flags: `teerex COMMAND --help`. For `clutch take` and `clutch release`, use `teerex clutch --help`; their subcommand help currently prints usage with exit 2. Full contracts: each `items/*/README.md`.

## Build, test, install

From the checkout root, with Python 3 and `uv` installed and on `PATH` (check
`python3 --version` and `uv --version`), run the build below. It obtains the pinned
Zig toolchain; the first run needs network access. Alternatively, with Zig 0.15.2
already installed, replace `uv run --with ziglang==0.15.2 python -m ziglang` with
`zig`.

```sh
uv run --with ziglang==0.15.2 python -m ziglang build -Doptimize=ReleaseSmall -Dtarget=x86_64-linux-musl   # or aarch64-macos
```

- **Tests** are the Python suites under `items/` and `tools/`. They run against disposable Rex servers only. [docs/ci.md](docs/ci.md) lists them and the two current hosted lanes (Linux API13 and Mac API13).
- **Install:** `tools/install/teerex-install upgrade|rollback|list` installs a verified build into `~/.local/opt/teerex-managed`, keeping earlier versions for rollback ([docs/install.md](docs/install.md)).
- **Cartridges:** `tools/cartridges/package.py` builds the catalogs that `teerex cartridges` installs ([docs/cartridges.md](docs/cartridges.md)).

## Where things are

- [docs/roadmap.md](docs/roadmap.md): what is built, what is next, and what is blocked on Rex itself.
- [docs/planning/workloads/](docs/planning/workloads/): the accepted specs behind recent features.
- [docs/releases/](docs/releases/): release notes, including the frozen alpha.1–alpha.5 history.
- [research/](research/README.md): the original Rex research and its provenance.
- Older long-form guides ([docs/alpha5.md](docs/alpha5.md), [docs/concierge/](docs/concierge/README.md), [docs/direction.md](docs/direction.md)) are kept as history. Where they disagree with this page or an item's README, the newer document wins.

Python-backed command help uses public `teerex …` names, including `teerex targets`; after building `zig-out/bin/teerex` above, `python3 src/test_help.py -v` checks the embedded CLI help without contacting Rex. To check an existing executable instead, use `TEEREX_BIN=/absolute/path/to/teerex python3 src/test_help.py -v`.
