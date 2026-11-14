# Board

`teerex board` is a live, themed terminal view of both configured Rex servers,
teerex activity, agent scratchpad progress and machine vitals. It starts
[`board feed`](../boardfeed/README.md) as its own foreground child; quitting
reaps that feed and its workers. No daemon, install or timer-driven screen
refresh is involved. `boards fleet --detail` remains the evidence table.

```sh
teerex board                                  # hive + m5, standard hosts config
teerex board --config /absolute/hosts.json    # explicit named hosts
teerex board --hosts hive                    # a single configured source
teerex board --replay /absolute/events.jsonl  # bounded JSONL fixture; EOF holds
teerex board --replay /absolute/events.jsonl --once # final 60-column text snapshot
teerex board --json                          # finite live rows + per-host header counts
teerex board --hosts hive --json             # only the selected source
teerex board --no-graphics                    # Unicode only
```

`--once` needs `--replay`. The bundled [`fixture.jsonl`](fixture.jsonl) is
**SAMPLE DATA**, with no real agent identifiers or operator activity.
Interactive mode needs terminal stdin/stdout. Python 3.9+ is required for the
feed and explicit named-host actions; the renderer itself is native Zig.

## Layout and controls

The current host has CPU trend, memory/swap, load, disk and network bands.
Wide panes add per-core heat, the other host's summary and top process trees
grouped by agent. Needs-you rows precede working rows; words and glyphs carry
meaning without colour. One new question flashes its callout once (180 ms),
and OSC 7501's documented `blocked` state marks the board as needing attention.
The board owns only its `teerex/board` status record and clears it on exit.

The selected host filters agents. There is no event stream section: it
repeated low-value events and cost attention (Josh, 2026-11-13). The host key
switches both panels; both feeds continue receiving events. Host failures
retain the last readings with an explicit unavailable notice.

| Key | Action |
|---|---|
| Up/Down, j/k | Select a live agent |
| Enter | `teerex --config … --host ROW_HOST surfaces focus` on that exact pane |
| Space | Expand ordered Done → Now → To-do steps with the current step marked; inline scratchpad via the selected host's `scratch show --json`; the event's Now/progress remain available if the read fails |
| m | Switch hive / M5 |
| ? | Keys overlay |
| q, Ctrl-C, Ctrl-D | Exit and restore terminal settings |
| Mouse | Click selects, double-click jumps, wheel browses |

The board scales from 40-column side panes to full tabs; scarce rows are
bounded with an omitted-agent count and selection scrolls the visible window.
Labels are sanitized before they reach the terminal. CJK/default-wide glyphs
reserve two cells using Unicode's versioned width data. Emoji presentation
selectors are suppressed so untrusted labels cannot enlarge an otherwise
single-cell glyph. Combining marks are retained; complex joined emoji may be
clipped conservatively. No environment value, id or receipt is drawn.

## Theme and glyph-kit

The visual source is [glyph-kit](https://glyph-kit.traykov.cc), read at
[`a86acc72d5fc0dea09f0dab246c96b568b24e5e7`](https://github.com/alextraykov/glyph-kit/tree/a86acc72d5fc0dea09f0dab246c96b568b24e5e7):
its character ramps, layout rules, planning boards and colour-role rules.
`░▒▓█` carry empty/in-progress/measured density; eighth blocks make numeric
bars; `►` identifies focus. Two-cell inner padding and a two-cell label gap
keep the chosen type rules. No font is bundled; Rex owns font choice.
The Node figure generator does not own an interactive terminal session, live
PTY input, row diffs or kitty placements, so the native renderer implements
those parts instead of shipping a second runtime just for figure generation.
The [MIT notice](GLYPH-KIT-LICENSE.txt) accompanies this adaptation.

| Role | Preferred terminal slot | Minimum contrast against queried background |
|---|---|---|
| Words | default foreground | 4.5:1 |
| Secondary | ANSI 7 | 4.5:1 |
| Accent | ANSI 6 | 4.5:1 |
| Problems | ANSI 1 | 4.5:1 |
| Passes | ANSI 2 | 4.5:1 |
| Lines | ANSI 8 | 1.5:1 |
| Marks | ANSI 6 | 3:1 |

OSC 4/10/11 queries read the actual palette/defaults. A failing preferred slot
falls back to readable default ink, or the strongest available ANSI slot.
If a theme offers no passing slot, the strongest slot is used; the program
does not invent a new colour. Unknown background contrast is **UNKNOWN**:
words fall back to terminal default ink, while a queried ANSI mark colour can
still draw the transparent chart. The M5 probe exposed exactly that missing
default-background response; this is not reported as a passing contrast check.

Only ANSI 0–15 and default foreground/background are emitted as SGR. Graphics
pixels derive solely from the queried ANSI mark slot, with alpha-zero
background. Palette queries happen at startup, focus/resize and at most once
per five seconds **when feed events arrive**; they do not add an idle timer.
`NO_COLOR` disables colour and graphics. [`PROBE.md`](PROBE.md) records protocol
capabilities and their limits. Kitty placements are capability-gated; Unicode
braille and blocks remain available without graphics.

## Renderer choice and measurements

Chosen engine: plain Zig with a bounded model and a small row-diff renderer.
No TUI package or graphics library is downloaded. The existing build pins
Zig 0.15.2; the [Unicode 17.0.0 wide intervals](width.zig) are embedded source
with [their licence](UNICODE-LICENSE.txt). Thus dependency resolution cannot
silently change renderer behavior.

The measured prototype redraws a changed row in a 60×30 frame. The UI uses
`poll` indefinitely when idle, with a signal pipe for resize/shutdown; only
the one-shot attention flash has a deadline. Text and optional kitty updates
share one DEC 2026 transaction. No whole-screen clears or blank intermediary
frames are emitted during redraw.

The decision was to keep this prototype after it met the native latency and
idle budget. libvaxis and OpenTUI would add a new input/rendering dependency
without an unmet measurement here; a VT emulator is not needed for this
board's event-to-frame path. Those alternatives were **not** independently
benchmarked, so this is not a claim that the custom renderer beats them.

| Prototype measurement | hive x86_64 | M5 arm64 |
|---|---:|---:|
| Changed 60×30 frame (10,000 frames) | 98.1 µs | 26.0 µs |
| Key → PTY bytes, median / p95 | 0.195 / 0.470 ms | 0.106 / 0.142 ms |
| Idle CPU ticks over three seconds | 0 | 0 |
| Idle output bytes | 0 | 0 |
| Clear-screen sequences | 0 | 0 |
| Synchronized begin/end pairs | 104 / 104 | 104 / 104 |
| Combined binary size | 1589592 bytes | 1647736 bytes |

Measured values are in [hive evidence](hive-measure.json) and
[M5 evidence](m5-measure.json). The reproduction below records:
10,000 native changed frames, 100 key-to-PTY transitions, a three-second idle
interval, binary size, sync pairing and clear-screen count. Idle CPU is
quantized to 0.01 CPU seconds; zero ticks over three seconds bounds the native
UI's average below 0.34%, rather than proving an exact zero. These measurements
exclude feed sampling and SSH; they do not certify whole-process-tree CPU or
physical display latency/perceptual flicker.

## Verification

```sh
# Build exactly as the repository specifies, then:
REX_BIN=/absolute/rex TEEREX_BIN="$PWD/zig-out/bin/teerex" python3 items/board/test_board.py -v
TEEREX_BIN="$PWD/zig-out/bin/teerex" python3 items/board/measure.py --output /tmp/board-measure.json
teerex board --benchmark 10000
```

The 11 public-CLI tests cover PTYs at 40/60/120 columns, no scrolling/clear
flashes, keys/inline scratchpads, mouse selection, fragmented palette and
kitty replies, contrast fallback, terminal-control sanitizing, event removal,
invalid-event visibility, blocked status, EOF hold, idle output and terminal
restoration on quit/signal. The integration case starts two **disposable** Rex
servers and uses named-host routing to verify Enter's target, full scratchpad
contents, normal live-feed startup/vitals and feed descendant cleanup.
The CI workflow runs this suite on both native API13 lanes.

Darwin sets the kernel's `PENDIN` bit when canonical mode returns. The test
excludes only that kernel-maintained bit, following the existing fleet PTY
contract and a native Python cbreak/restore reproduction; all actual terminal
settings must still match. The probe/PTY evidence establishes protocol behavior,
not a human visual review. Installation and replacement of the seat's current
fleet pane belong to the integrating lead.

Latest focused local gate: board 11/11 on hive and 11/11 on the M5; feed 7/7
on hive and 6 passes plus one Linux-only skip on the M5. Both native targets
built with ReleaseSmall after rebasing onto origin/main; Zig formatting passed.

The agent header counts the same host-filtered pane rows as the list. Idle,
done and unknown rows remain until their live pane disappears. `wait` combines
Rex’s `waiting` and `blocked` states; neither launch phase nor hook state
contributes a count.

`--json` needs no terminal and exits after a finite feed snapshot (also works
with `--replay`). Its `hosts` array contains each selected host's sorted `rows`,
`counts`, and `reachable` evidence. The same row filter and count function drive
the screen and JSON; `blocked` is kept separately in JSON and contributes to
`wait` on screen. An unavailable host or invalid feed event makes the exit
nonzero. Configured host executables must support `board feed --once`.

Run the kept, read-only comparison against every host in the configured file:

```sh
python3 items/board/check_one_source.py --config "$HOME/.config/teerex/hosts.json" --teerex "$PWD/zig-out/bin/teerex"
```

Hand-started panes also qualify when their child/foreground executable matches the host’s `profiles.*.argv[0]`; the independent probe reads the same profiles file (`--profiles ABS` overrides it).

It reads Rex pane/status inventory and launch metadata independently through
the existing named-host transport, then reads `board --json`. It prints every
missing/extra/duplicate pane, session/state mismatch and header discrepancy;
only zero differences exits 0. The board snapshot is bracketed by two Rex reads. A presence, session or
state change marks a pane as in flux. If a discrepancy touches such a pane,
the entire check runs again, up to three runs total. Only the last run is
printed, with its rerun count; settled discrepancies are always retained. Host
read failures are differences, never empty inventories accepted as success.
The disposable two-host test checks live JSON and injects an incorrect header
total to prove the check fails and names the difference.

## Memory reproduction

```sh
REX_BIN=/absolute/rex TEEREX_BIN="$PWD/zig-out/bin/teerex" python3 items/board/measure_memory.py --output /tmp/board-memory.json
```

This drives 2,000 fixture call events through a local Python feed connected to
its own disposable Rex server, relays each event into the board's replay FIFO,
and continuously drains the board PTY. Calls arrive in 100-event batches;
the relay paces individual events by 2 ms. Every 100 events it samples RSS
separately for the native board, Python feed, disposable server and feed
children, plus native board CPU time. It never reads personal state.

The board uses a reclaiming allocator for replaced events and renderer rows.
The command's lifetime arena cannot reclaim those allocations as they expire.
Frame scratch storage is an independent arena reset between redraws, retaining
only its peak frame capacity. No live rows or events are dropped to control
memory. [Kept measurements](memory-measure.json) contain all 100-event samples
and board CPU time before/after on hive and the M5. The fast
`BoardTest.test_replaced_events_release_memory` compares equal
live state after 200 and 2,000 replacements and catches the former retention.

## Held work section

Hosts declaring [`held_command` and `held_open`](../boardfeed/README.md#held-work)
get a compact held-work section. Its oldest-first rows show source text and age;
only broken rows use ANSI red; other held ink uses default foreground. Held rows never flash, make sounds or
change the board's attention status. Arrows/j/k and mouse select them; Enter
opens the item beside the board, using its source host's literal argv template.
Agent Enter and agent header counts retain their existing source and behavior.

Each host in `board --json` has `held: null` when no section is configured, or
`held: {available, rows, count}`. The count comes from the section's row list,
including rows available by scrolling. Unavailable sections have no active rows;
a finite snapshot exits nonzero when a held source fails.

The independent read-only check runs each configured source command on its host
and compares IDs/order, text, broken flags and row-derived count:

```sh
python3 items/board/check_held_source.py --config "$HOME/.config/teerex/hosts.json" --teerex "$PWD/zig-out/bin/teerex"
```

It prints differences and exits zero only when none remain. Source failures are
reported as differences. The disposable-server board integration exercises both
this check and held Enter; fixture tests cover ordering, colour, availability,
counts and independent mismatch detection.

Worker rows show the starter, contract step n/m and age since last contact. Stalled contracts use the problem colour on both row lines; labels retain cell-aware clipping at narrow widths.

Expanded agent machines preserve step executor, `■ outcome` and `⇥ handoff` annotations when present. Plain scratchpads remain supported; absent executor evidence is labelled `agent`.
