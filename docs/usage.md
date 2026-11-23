# Using teerex

teerex provides inspectable Rex utilities for reading, waiting, guarded sends, surfaces, records, and recovery. Exact flags are in `teerex COMMAND --help`; each item README has its full contract.

## Addresses

- A pane is a Rex **block**. You address it by session and block: `session:UUID` and `block:UUID`.
- Your own pane is in `REX_SESSION`/`REX_BLOCK` (over ssh: `LC_REX_SESSION`/`LC_REX_BLOCK`).
- **The socket:** `observe`, `watch` and `send` fill in `--socket` for you, from `REX_SERVER` or else the personal server, so you can leave it out, even where `--help` still lists it as required. For other live commands, you can explicitly pass `--socket /run/user/$UID/rex/server.sock` on hive, or `~/Library/Application Support/rex/server.sock` on a Mac. `REX_SERVER` is often empty inside agent panes.
- **Labels and short ids work.** A command that needs a canonical id gets one from `teerex surfaces resolve`:

```sh
teerex surfaces resolve --socket "$S" --session rivet --pane "codex-feat20"   # label or unique id suffix; a tab's label works too
```

- **Named host:** add `--config ~/.config/teerex/hosts.json --host hive` before the command.

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
- A change, or a `done` status, is evidence the pane did something. It is not proof the work succeeded: check the program’s exit separately.
- Use one `watch` in place of any sleep-and-read loop.

## Run a command visibly

```sh
rex run -s "$SES" -c "$PWD" --keep-open --wait -- make test
```

`--wait` returns the command’s exit status. `--keep-open` leaves the finished
pane available to read.

## Panes

```sh
teerex surfaces open   --socket "$S" --session "$SES" --layout tiled --anchor "$ME" --label logs -- tail -f app.log
teerex surfaces ensure --socket "$S" --session "$SES" --label "dev server" -- npm run dev        # reuse or create
teerex surfaces session ensure --socket "$S" --label rivet                                      # find or create a session
teerex surfaces rename|focus|move|close --socket "$S" --session "$SES" --pane "$P" …
```


- Every pane you open is visible, and yours to close when your work lands.
- Use `surfaces open` to show a document or terminal command in a visible pane.

## Records and recovery

```sh
teerex records --help
teerex recovery update --socket "$S" --snapshot
```

Use rexconfig’s `board` to see open work. Never restart the Rex server or kill
Rex processes without Josh’s approval. A restart closes every pane.

## What teerex never does

- It never starts a hidden agent or a daemon.
- It never retries on its own.
- It never closes a pane you did not ask it to close.
- It never infers that work is done.

Every result says what is known, and names anything unknown (`unknown`, `uncertain`, `not_assessed`).
