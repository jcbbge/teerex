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

Revision 2 adds `steps`, `waiting`, `wait_age_ms`, `executor` and `stalled` to
agent events. Scratch projections use the absolute teerex `scratch show --json`
and cache by file modification time; explicit source overrides and legacy
scratchpads retain a Markdown fallback. Only the model name is extracted from
launch argv; full arguments remain private. `review_at` supplies the deadline.

Decision-directory changes invoke the absolute teerex `decide list --json`.
`decisions` events carry the contract's open-decision array and `complete` flag;
the merge combines both hosts in opening order. Registry/scratch/decision reads
remain filesystem-event driven. The renderer ignores legacy `stream` events.
Projection subprocesses are tracked and reaped during foreground feed shutdown.

Shutdown signals are sent once. Re-entering cleanup does not signal workers
again while their Python signal handlers are setting the stop event.
