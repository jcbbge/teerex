# Rex terminal capability probe

Measured on 2026-11-13 with [`probe.py`](probe.py), run in real, temporary Rex
terminal panes via `teerex surfaces open`, once on hive's server (the server
viewed from the M5) and once on the M5's native server via named-host SSH.
Replies were read from `/dev/tty` in raw mode with a 700 ms deadline per query,
then the original terminal settings were restored. Result files were read back;
both temporary blocks were closed through `teerex surfaces close`, whose
receipts reported `closed_and_absent` and `block_absence_verified: true`.

This measures the actual terminal protocol endpoint, not a TERM-name guess or
an external terminal emulator. It does **not** establish that a human inspected
the rendered pixels, font coverage, or perceptual flicker in the M5 app.

| Capability | hive | M5 | Reply / interpretation |
|---|---|---|---|
| Kitty graphics | yes | yes | `Gi=31;OK` before the primary DA response |
| Kitty Unicode placeholder feature query | unproven | unproven | `Gi=32;EINVAL: dimensions required`; no `e=T,U=1` feature acknowledgement |
| Sixel | not advertised | not advertised | DA `?62;22c` does not include 4; XTSMGRAPHICS query got no reply |
| Truecolor | yes | yes | DECRQSS SGR reply retained `38:2::1:2:3` |
| Synchronized output | yes, initially reset | yes, initially reset | DECRQM reply `?2026;2$y` |
| ANSI palette query | 16 slots | 16 slots | OSC 4 replies for slots 0–15 |
| Default foreground/background query | both replied | neither replied | OSC 10/11: contrast is UNKNOWN without the default background |

The bounded raw query/reply files were retained locally at
`/tmp/codex-render-hive-probe.json` and `/tmp/codex-render-m5-probe.json`;
protocol captures are not committed. The table above preserves the results.
Both environments reported `TERM=xterm-256color`
and `COLORTERM=truecolor`. The server identities returned by teerex were
Linux API13 `0.0.1794460237-g348d75` and Darwin API13 `0.1.0-preview.16`.
Those strings identify this measurement, not future installations.

## Rendering decision

Use ordinary kitty image placements for the dense CPU chart after an in-pane
kitty acknowledgement and a queried ANSI mark colour. Do not rely on Unicode
placeholders or sixel. The image contains only that ANSI colour and transparent
pixels: changing the Rex palette changes the next chart without inventing an
RGB theme. Text, bars, per-core heat and the fallback sparkline use Unicode.
40-column panes use the Unicode chart to preserve the available room.

Every frame is one DEC 2026 transaction; no clear-screen escape is issued during
redraw. Graphics and text are updated inside the same transaction. Exit deletes
only the board's own image id and restores modes/cursor/alternate screen.

## Reproduce

Open `python3 /absolute/path/items/board/probe.py --output /tmp/probe.json`
through `teerex surfaces open` on the selected server. Read the file after the
bounded queries finish; close the returned block through `surfaces close`.
The program remains alive for at most 120 seconds so the creator can close the
surface explicitly. No service or permanent configuration is installed.

Query references fetched for this work:

- [Kitty protocol: support and feature queries](https://sw.kovidgoyal.net/kitty/graphics-protocol/#querying-support-and-available-transmission-mediums).
- [Xterm control sequences: DA, DECRQSS, OSC colours](https://www.xfree86.org/current/ctlseqs.html).
- [Synchronized output extension](https://github.com/contour-terminal/vt-extensions/blob/master/synchronized-output.md).
