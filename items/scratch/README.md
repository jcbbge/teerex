# Per-pane session scratchpad

`teerex scratch` keeps one ephemeral working list for each Rex pane, separate from project task lists. Python 3.9+ is required. It never contacts Rex. The fixed path is `~/.local/state/teerex/scratch/<session:UUID>/<block:UUID>.md`, preserving colons. Scratch/session/archive directories are 0700; Markdown and lock files are 0600.

All seven verbs accept `--session session:UUID --block block:UUID`. Omitted targets come from `REX_SESSION`/`REX_BLOCK`, falling back to `LC_REX_SESSION`/`LC_REX_BLOCK` over SSH. They require full canonical IDs. HOME selects the local user's home; XDG_STATE_HOME does not change this established path.

```sh
teerex scratch init --name worker --purpose 'Build the feature' --intent 'Required gates pass'
teerex scratch todo 'Run the gate'
teerex scratch now 'Implement the feature'
teerex scratch now 'Run the gate' --done
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

Reads tolerate extra blank lines, missing sections and hand-written checkbox capitalization. Extra Now entries become To-do items. Writes normalize the supported fields and sections; arbitrary Markdown outside this format is not preserved. A stable per-file advisory lock protects cooperating writers across atomic replacements. Writes flush the new file and directory; files are bounded to 256 KiB. Symlink files/locks and unowned/nonregular files refuse. Hand editors that ignore the lock can still race a write.

`show --json` returns exactly `{purpose, intent, now, todo, done, updated}`; empty Now is null. Plain `show` and `watch` use ▶, ☐ and ✓ and `updated N min ago`. Watch polls in the foreground, redraws when content or age changes, wraps to at most 40 columns, and exits on interruption. `watch --once` prints one frame. A missing/archived file shows a waiting message.

Managed and human launches initialize the file and export `AGENT_SCRATCHPAD` and `LC_AGENT_SCRATCHPAD`. Profiles accept `intent` and `scratch_pane` (boolean, default true). Intent defaults to the brief's first nonblank line, then Purpose. The protocol names the path and requires updates before and after every step. A tiled watch opens beside the agent through `surfaces open`. A failed/uncertain side-pane creation is retained in the launch receipt, never retried automatically. It does not claim the harness followed the protocol.

`agents prune --apply` archives a scratchpad only after observed pane absence, under `scratch/archive/<session-id>/`. It leaves a live pane's list alone even after child exit. Archive history is retained; nothing is deleted.

Generate the native palette fragment with `teerex scratch palette --file ABS --socket ABS [--teerex ABS] [--rex ABS]`. `--rex ABS` pins the surface controller's Rex executable, including when the Rex server's PATH has no `rex`; without it the controller retains its normal PATH lookup. It adds **Show scratchpad**, opening a watch tiled beside the invoked pane. The output file must be new. Register it through the existing `teerex surfaces palette install` plan/apply workflow; generation does not change personal configuration.

Verification: `TEEREX_BIN=ABS python3 items/scratch/test_scratch.py -v`; launch/display/archive coverage is in `items/agents/test_agents.py` against disposable API13 servers. The fleet board reads the same Markdown independently.
