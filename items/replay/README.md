# Replay

P0 wire contract probe: `REX_BIN=/absolute/rex python3 items/replay/test_wire.py -v`.
It starts a private disposable server (`--config /dev/null`, `--restore=false`),
opens a persistent API13 control connection and a `rex.data.terminal.v1` data
connection, and checks WELCOME, an opaque nonempty snapshot, initial resize,
`/bin/echo` bytes and its `child_exited` marker. It stops only its own server.

The wire contract comes from the selected server's `/llms.txt` (control/data
connections). The probe reports the server identity; a hive pass does not certify
another Rex build. Tickets and reconnect tokens are never logged.

## Commands

All modes require `--socket ABS --session session:UUID`; no environment target,
focus selection, automatic retry or server autostart. Python3.9+ is required.
The command host and selected Rex must share the local filesystem and Python.

```
teerex replay record --socket ABS --session session:UUID --out NEW_ABS_DIR \
  --id SLUG --allow-sensitive-capture [--layout tab|offstage] [--label TEXT] \
  [--cwd ABS] [--columns 80 --rows 24] [--timeout-ms 60000] \
  [--max-bytes 4194304] [--checkpoint-every-bytes N] -- ARGV...
teerex replay play --socket ABS --session session:UUID --fixture ABS_DIR \
  --observations-out NEW_ABS_DIR [--facts ABS_FILE] [--max-bytes 65536] \
  [--pace fast|recorded] [--timeout-ms 60000] [--keep-open] [--teerex ABS]
teerex replay live --socket ABS --session session:UUID --script ABS_FILE \
  --observations-out NEW_ABS_DIR [--cwd ABS] [--timeout-ms 300000] \
  [--record-out NEW_ABS_DIR --allow-sensitive-capture] \
  [--allow-attached-viewers] [--keep-open] -- ARGV...
```

Record starts a blank gated command (visible tab by default, detached with
`--layout offstage`), checks blank text, then releases its literal argv. The
snapshot is opaque and is never decoded or replayed. Only nonce-matching Rex
APCs are demultiplexed. The first resize and subsequent resizes/exits carry exact
program-byte offsets. Transport loss attempts one exact-count data resume;
rejection or overflow ends the fixture as incomplete. Capture bounds are 16 MiB,
65,536 chunks, 4,096 events, 256 checkpoints and a 4 MiB manifest. Consent does
not imply that captured bytes are safe to publish. Runtime captures are always
marked sensitive. Files are 0600 in 0700 directories and published atomically.

Play creates an owned detached Rex terminal running the embedded byte player.
It preserves chunk boundaries, applies resize events, reads the player's own
stream to verify every byte, and saves real `observe` packets at checkpoints.
PTY query replies are drained. Recorded child exit facts come from fixture events,
not the player's process. No libghostty or terminal emulator is embedded. A
checkpoint is not an atomic read tied to a server stream offset; Rex exposes no
such offset today. `--pace recorded` keeps gaps capped at 60 seconds total.

Live drives only its newly created block. It refuses another attached client
unless `--allow-attached-viewers` explicitly accepts that contamination risk.
There is no exclusive-input claim. Steps are `write`, `paste`, `key`, `resize`,
`checkpoint`, `expect` with `within_ms`, `effect` relative to cwd, and bounded
`sleep_ms`. Filesystem effects must stay inside cwd. `model_turns` must be 0;
Enter/newline inputs need a nonempty `local_only` reason. The runner reports
`model_turns:"not_observed"`, not proof that the application made no call.

Facts use `teerex_display_facts` v1 with independently authored `at` checkpoint
lists. Predicates: `capture_contains`, `capture_not_contains`,
`capture_lines_in_order`, `size`, `status_state` (optional `status_id`),
`process_running`, `child_exit_code`, `mode_enabled`. Missing evidence is
`"unknown"`; a negative capture fact on an incomplete prefix is always unknown.
All facts must be true. See [shared terms](../../docs/observation-terms.md).

Every non-usage invocation emits one `replay_result` v1 JSON with separate `mode`,
`outcome`, steps/checkpoints, source identity, cleanup, `retry_safe:false`,
`interpretation:"none"`, `task_completion:"not_assessed"`. Play additionally
reports `stream_check`; record reports `fixture_path` and stream completeness.
Exit 0: complete record / faithful replay with all facts true / live steps true.
Exit 1: refusal, wire/creation/cleanup uncertainty, incomplete/hash mismatch.
Exit 2: usage (no JSON). Exit 3: false/unknown facts, live divergence, or
`steps_not_run`. Exit 124: deadline; 130/143: interruption. Without `--keep-open`,
only this invocation's block is closed and absence verified. With it, the result
cannot claim absence; the private controller files are removed at exit.

## Verification

```
REX_BIN=/absolute/rex python3 items/replay/test_wire.py -v
REX_BIN=/absolute/rex python3 items/replay/test_replay.py FactContract Replay -v
REX_BIN=/absolute/rex python3 items/replay/test_terms.py -v
python3 items/replay/gen_fixtures.py --check
# Opt-in, no submitted model prompts, fresh cwd and private Rex:
TEEREX_REPLAY_REAL=claude,codex,pi REX_BIN=/absolute/rex \
  python3 items/replay/test_replay.py RealTuiLive -v
```

Real-TUI scripts expose unauthored steps as `not_run:needs_authoring`, never a
pass. Their observations stay in the disposable test directory, never Git.
Synthetic fixture provenance explicitly says authored (no acquired Rex snapshot
or identity); regeneration is byte-identical. Acceptance plays them through the
private server on API13 CI lanes. Shared offline terms run on every lane.

Security surface: explicit local Unix API only, Rex authenticates peer identity;
no new listener, credential store, service, port, network dependency or scheduler.
Inputs and frames are bounded; scripts/fixtures are data, never executed code.
The only executed commands are literal argv supplied to record/live and the
embedded gate/player. SIGINT/SIGTERM stop the controller and verify block absence;
block closure alone does not prove every descendant died. No public server or
browser administration/metrics service is added to this foreground CLI.

Observed hive real-TUI limits: Codex and pi passed startup, unsent marker, resize
100×30→60×20 and Ctrl-U clear checks. Claude's fresh cwd shows workspace trust
before its input box, so its generic marker script reports `live_divergence`.
The separate `claude-trust-decline.json` pins the observed selected `No, exit`
choice and its actual child exit **1**, rather than equating a correct decline
with exit zero. The 500 ms scripted settling delay remains explicit. Codex/pi
confirmation steps remain `not_run:needs_authoring`; no absence of a trust prompt
is inferred beyond these observed starts. Real captures are not committed.

Replay launchers explicitly use Rex terminal options `shell:"none"`, `login:false`
and `interactive:false` on both layouts. This suppresses launcher output such as
macOS `Last login:` banners without stripping any program bytes from fixtures or
weakening replay verification. Visible record tabs use `session.new_window` on
the retained control connection so the same explicit terminal options apply;
the surfaces CLI currently has no non-login launch selector. New tabs retain
`focus:false`. The record checks pin exact program bytes for both tab and
offstage launch paths on Linux and macOS.
