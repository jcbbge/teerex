# teerex for agents

This is the guide an agent reads before it touches a terminal on Josh's machines. It covers what to run, in what order, and what each result means. Exact flags are in `teerex COMMAND --help`. Each item's README has the full contract.

teerex is the only way agents use Rex. Every pane, read, wait, run, message and board goes through it. Where teerex cannot do something yet, file a `jcbbge/teerex` issue and say so in your report. Do not build plumbing around the gap.

## Addresses

- A pane is a Rex **block**. You address it by session and block: `session:UUID` and `block:UUID`.
- Your own pane is in `REX_SESSION`/`REX_BLOCK` (over ssh: `LC_REX_SESSION`/`LC_REX_BLOCK`).
- **The socket:** `observe`, `watch`, `run-visible`, `send`, `spawn`, `doctor` and `run` fill in `--socket` for you, from `REX_SERVER` or else the personal server, so you can leave it out, even where `--help` still lists it as required. For other verbs (`surfaces`, `jobs`), pass `--socket /run/user/$UID/rex/server.sock` on hive, or `~/Library/Application Support/rex/server.sock` on a Mac. `REX_SERVER` is often empty inside agent panes.
- **Labels and short ids work.** A command that needs a canonical id gets one from `teerex surfaces resolve`:

```sh
teerex surfaces resolve --socket "$S" --session rivet --pane "codex-feat20"   # label or unique id suffix; a tab's label works too
```

- **Another machine:** add `--config ~/.config/teerex/hosts.json --host hive|m5` before the command.

## Keep the working list current

Before work, copy every item from the brief into the scratchpad, one per command,
then confirm the numbered list to your starter. Keep at most one Now step:

```sh
teerex scratch todo "First item from the brief"
teerex scratch now "First item from the brief"
teerex scratch done --proof "check command and observed result"
teerex scratch flag "what is stuck; what you tried; what you need"
teerex scratch now "Pending step" --waiting "on what" --check 10m
```

These commands use your pane identity and update `AGENT_SCRATCHPAD`. Managed
workers send STEP and FLAG lines to their starter. Work only on Now; finish it
with evidence before starting the next item. Flag uncertainty immediately and
continue work that does not depend on it. A waiting declaration names the
dependency and a future check; check again yourself when it is due.

Every turn ends declared: all steps done with To-do empty, blocked with a flag,
or waiting with a future Check. A finished turn is idle, not process death.
The Claude Stop hook blocks the first stale scratchpad stop and asks you to
update Now/To-do/Done; a second stop records the stale exception. Codex notify
runs after the turn and sends a reminder instead of vetoing it. Managed Pi
continues settlement once. See the [scratch contract](../items/scratch/README.md)
and the harness hooks supplied by rexconfig.

## Find the seat

```sh
teerex --config ~/.config/teerex/hosts.json --host hive seat resolve
```

This reads the live registered seat and returns its address or `no_seat`.
Resolve by role each time; never reuse a remembered pane ID. Without named-host
configuration, `teerex seat resolve` requires explicit `--store`, `--host`
and `--socket`. Send questions to your starter when your brief requires it;
only the seat asks the operator.

## Read and wait

```sh
teerex observe --session "$SES" --block "$B" --tail                                 # newest output; text is in .capture.content
teerex observe --session "$SES" --block "$B" --state                                # is that agent idle, working or waiting?
teerex observe --session "$SES" --block "$B" > before.json                          # a baseline for watch
teerex watch   --session "$SES" --block "$B" --baseline before.json \
               --status-state done --status-state error --no-deadline                # wake on done OR error
teerex compare --before before.json --after after.json [--view progress-v1]          # offline
```

- `watch` exits 0 on a change or a matched status, 124 on its deadline, and 1 on error. For a status watch, `--no-deadline` waits for as long as the work takes.
- Add `--view progress-v1` to `watch` or `compare` to ignore spinners and timers. Raw evidence is never masked.
- A change, or a `done` status, is evidence the pane did something. It is not proof the work succeeded: read the program's exit (`run-visible` reports it).
- Use one `watch` in place of any sleep-and-read loop.

## Run a command visibly

```sh
teerex run-visible --session "$SES" --cwd "$PWD" --env-file env.json --stdin-file /dev/null \
  --app build --title "make test" --timeout-ms 600000 -- make test
```

- The command runs in a tab Josh can see, and you get back its real exit code and its output.
- `--env-file` is a JSON object that **replaces** the whole environment, so include at least `PATH`: `printf '{"PATH":"/usr/bin:/bin"}' > "$PWD/env.json"`. Paths given to teerex (`--env-file`, `--cwd`, `--stdin-file`) must be absolute. Use `--stdin-file /dev/null` for no input.
- The tab closes when the command ends. Add `--keep-open` to leave it up for Josh to read.
- teerex itself exits 1 when your command fails. Your command's own exit code is in the result at `exit_report.exit_code`; read that, not teerex's exit status.
- Long or unbounded work: use `--no-deadline`.
- Track it as a job: add `--registry … --owner … --purpose …`.
## Panes

```sh
teerex surfaces open   --socket "$S" --session "$SES" --layout tiled --anchor "$ME" --label logs -- tail -f app.log
teerex surfaces ensure --socket "$S" --session "$SES" --label "dev server" -- npm run dev        # reuse or create
teerex surfaces session ensure --socket "$S" --label rivet                                      # find or create a session
teerex surfaces ensure --socket "$S" --session any --label seat --create-session "$SES" -- seat   # one pane server-wide
teerex surfaces rename|focus|move|close --socket "$S" --session "$SES" --pane "$P" …
```

Generate a palette jump with `teerex surfaces palette focus --file /absolute/jump.lua --teerex /absolute/teerex --name jump_logs --title "Jump to logs" --label logs`. It resolves across all sessions and focuses the existing pane; absent or ambiguous targets refuse without opening anything. For the registered seat, use `--seat --board-store /absolute/boards --socket "$S"` instead of `--label logs`. Install the fragment through the [palette plan/apply workflow](../items/surfaces/README.md#prepare-and-register-a-palette-action).

- Every pane you open is visible, and yours to close when your work lands.
- Long output for Josh goes in a `.md` file, opened in `leaf` in a pane beside yours.

## Start and talk to agents

Agent lifecycle commands belong to rexconfig: use `agent-spawn`, `agent-send`, `scratch`, `agent-hook` and `agent-close`. teerex no longer provides an `agents` command, a launch registry, per-launch hooks, or a sandboxed channel. Use `teerex send` for guarded whole-message delivery and `run-visible` for visible noninteractive commands.

## Jobs, boards, recovery

```sh
teerex jobs list|present|forget --registry "$REG" …     # who owns which pane; bring a finished pane beside you
teerex boards fleet --store "$ST" --config ~/.config/teerex/hosts.json --hosts hive,m5   # read-only fleet board
teerex recovery update --socket "$S" --snapshot          # before any Rex restart: panes at risk + snapshot
```

Never restart the Rex server or kill Rex processes without Josh's yes. A restart closes every pane.

## Cartridges

Single-purpose native payloads, managed by `teerex cartridges`. Each can be installed, run and removed on its own:

```sh
teerex cartridges list
teerex cartridges install filter --catalog DIR --allow-experimental          # plan; add --apply to do it
teerex cartridges run filter -- --sample a.json --sample b.json
```

Every item is currently experimental, so a plain `--all` selects none (the plan lists them under `excluded_experimental`). Removing a cartridge keeps its data.

## Inspect and repair state

```sh
teerex jobs doctor --registry "$REG" [--socket "$S"]     # read-only: stale, due, uncertain, orphaned registrations
teerex cartridges doctor                                # read-only: stage leftovers, hash/state mismatches
teerex cartridges repair --plan                         # only old orphaned stages; --apply to remove
```

## Machine check

```sh
teerex doctor --socket "$S"     # rex executable used, client/server mismatch, what this server supports
```

## What teerex never does

- It never starts a hidden agent or a daemon.
- It never retries on its own.
- It never closes a pane you did not ask it to close.
- It never infers that work is done.

Every result says what is known, and names anything unknown (`unknown`, `uncertain`, `not_assessed`).