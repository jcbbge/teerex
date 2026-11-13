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

The selected host filters agents and the newest-first stream. The host key
switches all three panels; both feeds continue receiving events. Host failures
retain the last readings with an explicit unavailable notice.

| Key | Action |
|---|---|
| Up/Down, j/k | Select a live agent, or scroll when the stream has focus |
| Enter | `teerex --config … --host ROW_HOST surfaces focus` on that exact pane |
| Space | Inline scratchpad via the selected host's `scratch show --json`; the event's Now/progress remain available if the read fails |
| m | Switch hive / M5 |
| s | Toggle stream focus |
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
| Changed 60×30 frame (10,000 frames) | 99.7 µs | 25.6 µs |
| Key → PTY bytes, median / p95 | 0.262 / 0.534 ms | 0.111 / 0.149 ms |
| Idle CPU ticks over three seconds | 0 | 0 |
| Idle output bytes | 0 | 0 |
| Clear-screen sequences | 0 | 0 |
| Synchronized begin/end pairs | 104 / 104 | 104 / 104 |
| Combined binary size | 1546064 bytes | 1614040 bytes |

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
