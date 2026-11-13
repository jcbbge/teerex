# Board feed

`teerex board feed [--config ABS --hosts hive,m5]` writes version 1 JSONL
matching the shared board event contract. Both configured hosts are selected by
default. Each runs its own foreground feed through `targets exec`; no daemon,
installation, retry, or SSH fallback is started. Disconnects produce `host`
events while the other host continues.

`--local --host-name NAME --socket ABS --rex ABS` runs a transport worker on
one host. Read-only source overrides: `--agents-registry ABS`,
`--jobs-registry ABS`, `--scratch ABS`, `--calls ABS`. Defaults are the host's
standard teerex state paths; `TEEREX_CALL_LOG_DIR` selects the call directory.
The named-host transport injects the configured socket and Rex executable.
Python 3.9+ is required, using only its standard library.

Rex `events --all --json` provides pane, title, focus, process and program status
changes. Initial process/status reads seed registered panes. Session view events refresh
placement and remove closed panes from the agent view. inotify on Linux
and kqueue vnode notifications on macOS watch registries, call logs and
scratchpads, including directory creation and atomic replacement. Only changed
agent projections are emitted; a removed record emits `gone`. Successful call
end records are joined to their starts before projecting plain descriptions.
Tokens, arguments, brief/report bodies and arbitrary call fields are excluded.

Vitals sample once per second. Linux reads `/proc`, macOS uses Mach per-core
counters and native `vm_stat`, `sysctl`, `mount`, `netstat` and `ps` tools.
Network counters exclude loopback; disk entries exclude virtual filesystems.
Process trees are attributed to the registered agent's pane root; unattributed
processes retain a null agent. First CPU/network samples establish the baseline.
Missing process/status evidence leaves agent CPU/RSS null; grouped process
measurements are in `vitals.top`. macOS process CPU is the native `ps` average,
while Linux reports interval deltas. Filesystem events trigger state reads;
there is no periodic registry or Rex polling.

Verification: `REX_BIN=/absolute/disposable-capable/rex python3
items/boardfeed/test_feed.py -v`. Tests create private temporary directories and
a disposable Rex server with restore disabled and `/dev/null` configuration.
The Linux `/proc` fixture case is selected only on Linux; all other cases run
on both operating systems. Tests never use a personal Rex socket or registry.

Agent rows start from the live Rex pane inventory, one row per block id.
Launch records supply metadata only; a dead launch never creates a row.
A live pane qualifies through a launch record or a `teerex-agent` status record.
Scratchpads join by the live pane’s session and block id, including idle/done
panes. State comes only from OSC 7501 `program_status`; `blocked` remains
`blocked`, and missing status is `unknown`.
