# Command guides in Rex

`teerex docs [COMMAND]` opens an index or command guide in leaf, floating over
its invoking pane. Each page contains the item README embedded at build time,
the installed binary's `--help`, and numbered README examples. No checkout is
needed at runtime. Requires Python 3.9+, leaf and an attached Rex terminal;
`--session`, `--block` and `--socket` allow an explicit invoking context.

```sh
teerex docs
teerex docs send
teerex docs try send-help
```

## Try it safely

Fixed read-only help/version argv have try IDs (`COMMAND-help`, `version`).
`observe-self` and `surfaces-self` inspect only their own sandbox pane.
README examples have stable page-local labels `COMMAND-example-N` and are shown
for reference, without execution authority. There is no arbitrary snippet/shell
execution. Unknown IDs fail before opening a pane.

Try opens a floating sandbox pane and a temporary working directory, runs the
allowlisted example, keeps its output until any key, removes the directory and
closes its own pane through surfaces. These examples open no additional panes
or services. The sandbox is a temporary workspace, not an OS security boundary.
Manual pane closure or process kill can interrupt cleanup; no daemon repairs it.

Guides are private temporary Markdown files under `~/.local/state/teerex/docs`.
The viewer removes its file when leaf exits; an uncertain open retains the file
and reports its path. Generate a native palette fragment with `teerex docs palette --file ABS --rex ABS
--teerex ABS --socket ABS`; it refuses an existing file. No existing configuration is changed. Install/upgrade via
the combined CLI installer; removing the CLI removes this command. The Rex
palette entry is separately owned by rexconfig.

Status: experimental combined CLI composition; Unix, Python 3.9+, Rex surfaces
API10–13. Uses only the standard library and existing teerex/leaf programs.
