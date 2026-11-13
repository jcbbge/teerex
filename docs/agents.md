# teerex for agents

This is the guide an agent reads before it touches a terminal on Josh's machines. It covers what to run, in what order, and what each result means. Exact flags are in `teerex COMMAND --help`. Each item's README has the full contract.

teerex is the only way agents use Rex. Every pane, read, wait, run, launch, message and board goes through it. Where teerex cannot do something yet, file a `jcbbge/teerex` issue and say so in your report. Do not build plumbing around the gap.

## Addresses

- A pane is a Rex **block**. You address it by session and block: `session:UUID` and `block:UUID`.
- Your own pane is in `REX_SESSION`/`REX_BLOCK` (over ssh: `LC_REX_SESSION`/`LC_REX_BLOCK`).
- The server socket is in `REX_SERVER` as `unix://…`. Decode it, or use the personal path: `/run/user/$UID/rex/server.sock` on hive, `~/Library/Application Support/rex/server.sock` on a Mac.
- **Labels and short ids work.** A command that needs a canonical id gets one from `teerex surfaces resolve`:

```sh
teerex surfaces resolve --socket "$S" --session rivet --pane "codex-feat20"   # label or unique id suffix
```

- **Another machine:** add `--config ~/.config/teerex/hosts.json --host hive|m5` before the command.

## Read and wait

```sh
teerex observe --socket "$S" --session "$SES" --block "$B" > before.json            # bounded, attributed read
teerex watch   --socket "$S" --session "$SES" --block "$B" --baseline before.json \
               --status-state done --status-state error --no-deadline                # wake on done OR error
teerex compare --before before.json --after after.json [--view progress-v1]          # offline
```

- `watch` exits 0 on a change or a matched status, 124 on its deadline, and 1 on error. For a status watch, `--no-deadline` waits for as long as the work takes.
- Add `--view progress-v1` to `watch` or `compare` to ignore spinners and timers. Raw evidence is never masked.
- A change, or a `done` status, is evidence the pane did something. It is not proof the work succeeded: read the program's exit (`run-visible` reports it).
- Use one `watch` in place of any sleep-and-read loop.

## Run a command visibly

```sh
teerex run-visible --socket "$S" --session "$SES" --cwd "$PWD" --env-file env.json --stdin-file /dev/null \
  --app build --title "make test" --timeout-ms 600000 -- make test
```

- The command runs in a tab Josh can see, and you get back its real exit code and its output.
- Long or unbounded work: use `--no-deadline`.
- Track it as a job: add `--registry … --owner … --purpose …`.
- Let a sandboxed child report back:
  - add `--channel-dir DIR` (you create it in advance, mode 0700) with `--report-to-session`/`--report-to-block`;
  - the child sends with `teerex agents channel --handle "$AGENT_CHANNEL" --request-id HEX32 --operation send --to report-to --message-file -`;
  - every request is written to `DIR/receipts.jsonl` as it happens.

## Panes

```sh
teerex surfaces open   --socket "$S" --session "$SES" --layout tiled --anchor "$ME" --label logs -- tail -f app.log
teerex surfaces ensure --socket "$S" --session "$SES" --label "dev server" -- npm run dev        # reuse or create
teerex surfaces session ensure --socket "$S" --label rivet                                      # find or create a session
teerex surfaces rename|focus|move|close --socket "$S" --session "$SES" --pane "$P" …
```

- Every pane you open is visible, and yours to close when your work lands.
- Long output for Josh goes in a `.md` file, opened in `leaf` in a pane beside yours.

## Start and talk to agents

- **Start one:** `agent-spawn --brief-file brief.md --owner ME --purpose WHY "$SES" NAME -- claude|codex|pi`. This runs `teerex agents launch` with the profiles in `~/.config/teerex/profiles.json`.
  - The new agent acknowledges the messaging protocol before it gets the brief.
  - It is tracked as a job.
  - When its turn ends, its last message reaches you once, as its stop report (Claude, Codex and pi).
- **Several at once:** concurrent launches queue. If the queue wait runs out, the launch refuses with `launch_queue_busy`, which is safe to retry; nothing was created.
- **Send:** `agent-send SES PANE ME "message"`. This is `teerex send`.
  - The message arrives as `FROM ME: …` followed by Enter.
  - If someone is typing in that pane, send waits until they stop, then puts their draft back after the message.
- **Your report** is the last message of your turn. Do not also send it with `agent-send`; use `agent-send` only for a question while you are still working.
- **Questions for Josh** go to the seat, never to an on-screen prompt in your own pane.
- **Housekeeping:** dead launch records are archived automatically. To do it by hand: `teerex agents prune --registry DIR [--apply]`.

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
