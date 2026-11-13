# Per-pane session scratchpad

`teerex scratch` keeps one ephemeral working list for each Rex pane, separate from project task lists. Python 3.9+ is required. It never contacts Rex. The fixed path is `~/.local/state/teerex/scratch/<session:UUID>/<block:UUID>.md`, preserving colons. Scratch/session/archive directories are 0700; Markdown and lock files are 0600.

The pane verbs accept `--session session:UUID --block block:UUID`. Omitted targets come from `REX_SESSION`/`REX_BLOCK`, falling back to `LC_REX_SESSION`/`LC_REX_BLOCK` over SSH. They require full canonical IDs. HOME selects the local user's home; XDG_STATE_HOME does not change this established path.

```sh
teerex scratch init --name worker --purpose 'Build the feature' --intent 'Required gates pass'
teerex scratch todo 'Run the gate'
teerex scratch now 'Implement the feature' --by computer
teerex scratch now 'Run the gate' --done --outcome implemented
teerex scratch done
teerex scratch show --json
teerex scratch path
teerex scratch watch
```

`init` creates an empty list or preserves and canonicalizes an existing list. `now TEXT` returns the previous Now to the top of To-do; `--done` instead moves it to Done. Starting an existing To-do removes its first matching entry from that section. `todo TEXT` appends. `done` completes Now, newest first, or is a harmless no-op when Now is empty. Text must be one nonempty line. Mutation requires init first.

The canonical format is:

```markdown
# worker
Purpose: Build the feature
Intent: Required gates pass
Updated: 2026-11-13T00:00:00Z

## Now
- [ ] Implement the feature

## To-do
- [ ] Run the gate

## Done
- [x] Read the contracts
```

`now TEXT` and `todo TEXT` accept `--by EXECUTOR` (for example `computer` or `opus high`) and `--handoff AGENT`. `done --outcome TEXT` and `now TEXT --done --outcome TEXT` annotate the completed step. Starting an existing To-do retains its annotations unless a flag replaces one. Markdown stores these after the task, separated by ` · `: `- [x] Build · computer · ■ fixed` or `- [ ] Integrate · computer · ⇥ codex-board`. Plain show/watch display the same executor, outcome and handoff. The separator is reserved in annotation values. Legacy unannotated tasks remain valid and have null annotations.

`teerex scratch wait --on NAME --what TEXT` records `Waiting: NAME · TEXT · since <ISO UTC time>`. `wait --clear` removes it; `now TEXT` also clears it. `show --json` exposes `waiting: {on, what, since}` or null. `scratch waiters --on NAME --json` returns a local list of `{session, block, name}` for active scratchpads waiting on NAME; archives are excluded. The waiting declaration records a dependency; send its exact ask directly to that agent through teerex too.

`wait --on NAME --what TEXT --until done|report [--timeout-ms N]` publishes the waiting line and blocks on a private FIFO beside the scratchpad, without polling. `done` accepts either turn-end or report notification; `report` accepts only reports. On notification it prints `{outcome:"notified", event:"done"|"report"}` and exits 0. Timeout prints `{outcome:"timeout", until:...}` and exits 1, retaining the Waiting line. Notifications do not clear Waiting: the agent clears it or starts its next step. One simultaneous blocking wait per scratchpad is supported; an existing FIFO refuses rather than stealing a wait. Normal exit, timeout and interruption remove the FIFO; after a forced kill, remove the abandoned `.wait.fifo` before retrying.

Managed notifier integration: embedded `scratch_waiters(name)` returns the same list; derive each path with `scratch_path(session, block)`, and call `scratch_wake(path, event="done")` on turn end or `event="report"` on report, alongside the guarded direct message. `scratch_wake` is nonblocking and returns false when no one-shot waiter exists. It validates FIFO ownership and type before writing.

Reads tolerate extra blank lines, missing sections and hand-written checkbox capitalization. Extra Now entries become To-do items. Writes normalize the supported fields and sections; arbitrary Markdown outside this format is not preserved. A stable per-file advisory lock protects cooperating writers across atomic replacements. Writes flush the new file and directory; files are bounded to 256 KiB. Symlink files/locks and unowned/nonregular files refuse. Hand editors that ignore the lock can still race a write.

`show --json` retains `{purpose, intent, now, todo, done, updated}` and adds `steps` and `waiting`; empty Now is null. `steps` is Done oldest first, then Now, then To-do. Each entry has `{state, text, by, outcome, handoff}` with state `done`, `now` or `todo` and null for missing annotations. The original now/todo/done strings retain their Markdown annotations. Plain `show` and `watch` use ▶, ☐ and ✓ and `updated N min ago`. Watch polls in the foreground, redraws when content or age changes, wraps to at most 40 columns, and exits on interruption. `watch --once` prints one frame. A missing file initially shows a waiting message; after watch has shown the scratchpad, removal or archival exits with status 0 so its pane closes with the agent.

Managed and human launches initialize the file and export `AGENT_SCRATCHPAD` and `LC_AGENT_SCRATCHPAD`. Profiles accept `intent` and `scratch_pane` (boolean, default true). Intent defaults to the brief's first nonblank line, then Purpose. The protocol names the path and requires updates before and after every step. A tiled watch opens beside the agent through `surfaces open`. A failed/uncertain side-pane creation is retained in the launch receipt, never retried automatically. It does not claim the harness followed the protocol.

`agents prune --apply` archives a scratchpad only after observed pane absence, under `scratch/archive/<session-id>/`. It leaves a live pane's list alone even after child exit. Archive history is retained; nothing is deleted.

Generate the native palette fragment with `teerex scratch palette --file ABS --socket ABS [--teerex ABS] [--rex ABS]`. `--rex ABS` pins the surface controller's Rex executable, including when the Rex server's PATH has no `rex`; without it the controller retains its normal PATH lookup. It adds **Show scratchpad**, opening a watch tiled beside the invoked pane. The output file must be new. Register it through the existing `teerex surfaces palette install` plan/apply workflow; generation does not change personal configuration.

Verification: `TEEREX_BIN=ABS python3 items/scratch/test_scratch.py -v`; launch/display/archive coverage is in `items/agents/test_agents.py` against disposable API13 servers. The fleet board reads the same Markdown independently.


## Turn-end enforcement and the seat

`teerex scratch hook-settings --teerex /absolute/stable/teerex` prints a Claude settings fragment with UserPromptSubmit and Stop command hooks. Merge its groups through rexconfig; it does not write configuration. Both hooks invoke `teerex scratch hook`, which reads a bounded JSON event from stdin. A seat must export `AGENT_SCRATCHPAD` (or `LC_AGENT_SCRATCHPAD`); without it the hook reports not_checked and allows the stop.

Prompt submit records a private turn-start time and hashes of Now and Done. Stop permits a changed Now, or an empty Now with a new Done entry, or a Waiting line naming the dependency. Updating only To-do or Updated does not count as progress. First stale Stop returns Claude's JSON blocking decision with `say what you are waiting on: teerex scratch wait --on … --what …`; a second Stop in that turn passes and records the stale exception. Missing or unreadable Markdown is stale. Older managed callers without a progress snapshot retain the timestamp check for a nonempty Now until their next prompt snapshot; managed callers should initialize `scratch_start = scratch_progress(scratch_read(path))` before the first turn and refresh it after completed turns for harnesses without prompt hooks. Scratch writes use microsecond ISO timestamps.

Seat enforcement state is `<scratchpad>.turn.json`, mode0600, atomically replaced under the existing scratchpad lock. It records the start time, whether the reminder has been issued, and the last check. Managed agents keep equivalent state in their existing private launch record, described in [agents](../agents/README.md#scratchpad-enforcement-at-turn-end). Neither path installs a daemon or changes project task lists.
