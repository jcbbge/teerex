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
A live pane qualifies through a launch record, a `teerex-agent` status record, or a child/foreground executable matching `profiles.*.argv[0]` in the host’s `~/.config/teerex/profiles.json` (`--profiles ABS` overrides it; unavailable files add nothing), with process changes refreshing membership.
Scratchpads join by the live pane’s session and block id, including idle/done
panes. State comes only from OSC 7501 `program_status`; `blocked` remains
`blocked`, and missing status is `unknown`.

`--once` reads one finite inventory/status/scratchpad snapshot and exits without
starting vitals or the event subscription. With named hosts it forwards the
same finite option to each configured worker. This powers `board --json`.

## Held work

A named-host entry may supply `held_command`, a nonempty literal argv list. The
selected worker runs it on that host, once at startup and then 30 seconds after
each completed read. Runs never overlap. Each read has a five-second deadline
and a 256 KiB JSON limit; failure, invalid schema or timeout emits unavailable,
not an empty success. Only changes to availability or projected rows emit events;
`generated_at` alone does not. No event source, service or permanent timer is
installed. Quitting the board reaps its active command along with the feed.

The command returns schema 1 with integer millisecond `generated_at` and `items`.
Each item has string `id`, `project`, `title`, `waits`, `text`; nullable string
`on`, `broken_why`; integer millisecond `since`; and boolean `broken`. `waits` is
`promote`, `ship`, `item`, `block` or `hold`. At most 256 unique items are accepted,
ordered by `since` oldest first. IDs start with an ASCII letter or digit and
contain only letters, digits, `_`, `.`, `:` or `-` (at most 256 characters).

`held_open` is an optional literal argv template containing exactly one `{id}`
placeholder, outside the executable argument. Enter routes that command to the
same named host through `targets exec`, in a tiled pane beside the board. The
pane keeps its output until Enter closes it. Commands and IDs never pass through
a shell. Missing/invalid `held_open` leaves the section readable and reports the
open action as unavailable. Hosts without `held_command` have no held section.

Example additions to an existing hive entry (retain its transport/path fields):

```json
{
  "held_command": ["/home/jrg/.local/bin/rv", "waiting", "--json"],
  "held_open": ["/home/jrg/.local/bin/rv", "show", "{id}"]
}
```

Agent rows expose starter display name, contract step_n/step_total, last_contact_at (milliseconds) and stalled. Older launches use scratchpad steps, starter metadata and the last hook contact; absent contact is zero.

Agent rows project ordered scratchpad steps (Done, Now, To-do), preserving optional executor, outcome and handoff annotations. Pane inventory and row-derived counts are unchanged.

Decision snapshots read each configured host’s existing boards store through `boards state inspect`, fold resolutions and publish only open cards. The feed watches that store with the existing filesystem watcher; unavailable sources are explicit. No decision is sent or opened by the feed.
