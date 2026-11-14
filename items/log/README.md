# Flight log and morning brief

Experimental combined CLI command, Python 3.9+ standard library, Linux and macOS.

`teerex log --since 2026-11-14T00:00Z --hosts hive,m5` merges existing evidence
by UTC timestamp. Hosts come from `~/.config/teerex/hosts.json`; omitted `--hosts`
selects all configured hosts. Agent launches, exits, retained timeline entries,
contract step message files, current and archived scratchpads, decision records,
and configured `held_command` (`rv waiting --json`) are read only. No board files
are read or changed. No event database, background process, or polling is added.

`--page [PATH]` writes self-contained HTML with no scripts, fonts, or network
resources. An existing explicit path is refused rather than overwritten.
`--brief` prints a Markdown document and opens it in a floating leaf reader at
the invoking pane; `--no-open` prints only. `--session`, `--block`, and `--socket`
provide explicit reader context. `--json` exposes normalized evidence for tools.

The brief includes reported finished steps and their supplied proof text, open
decision records, declared stalls, Rivet ship stops, machine load/CPU/disk, and
source errors. A reported finished step is not independently verified success.
Scratch times are snapshot times; contract-file times are recording times.
Missing historical steps cannot be reconstructed. Rivet waiting events carry
the source's `since` timestamp; arbitrary `rv trace` histories are not fetched
because the command has no safe project-neutral enumeration of item IDs.

Privacy boundary: never export registry tokens, argv, raw record bodies, or
transcript reports. Export only named event fields, step first lines, decision
questions, waiting summaries, and vitals. These summaries can still contain
private operator-authored text: review the page before sharing it. Reads refuse
symlinked files, terminal output removes controls, and HTML escapes every value
and forbids network/script resources with CSP. Existing evidence is never edited.

Install and upgrade with the shared verified teerex installer; uninstall with
that installer's lifecycle. Generated HTML persists at its printed path; brief
files persist while the reader may use them. No service or credentials required.

Checks: `python3 src/test_flight_log.py -v`, followed by installed command checks
on each supported machine. Source schemas: `items/agents/agents.py`
(`lifecycle_events`, `contract_tell`), `items/scratch/scratch.py`,
`items/records/records.py`, and Rivet `jobs/src/waiting.ts`, read 2026-11-14.
