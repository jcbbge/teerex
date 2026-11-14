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
Play and live checkpoints invoke native `observe`, which also needs the Rex
client executable on PATH. Select a specific client with root `--rex ABS` or
`TEEREX_INTERNAL_REX=ABS`; a working server socket alone is insufficient.
`--teerex ABS` selects the observation CLI, not the Rex executable.
The command host and selected Rex must share the local filesystem and Python,
including the same writable `/tmp`: replay creates its gate and player files
there. A sandbox with a private `/tmp` cannot drive a Rex server outside that
mount namespace, even if its socket, cwd and `TMPDIR` are shared. Run the private
Rex server inside the same sandbox, or provide a dedicated `/tmp` shared by
both processes; do not expose a live server or unrelated host files.

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
  [--allow-attached-viewers] [--layout tab|offstage] [--keep-open] -- ARGV...
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

Live defaults to an offstage terminal; `--layout tab` creates a visible tab.
Its creation receipt records the caller, so that caller can close a kept-open
tab through `surfaces close`; other callers are refused.
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

Every non-usage invocation emits one `replay_result` v1 JSON with `mode`,
`outcome`, `target`, `steps`, `checkpoints`, `not_run`, cleanup,
`retry_safe:false`, `interpretation:"none"`, `task_completion:"not_assessed"`
and `model_turns:"not_observed"`. `target` identifies the requested server/session;
its block starts as null. `rex` is added only after `server.version` succeeds,
so input refusals such as `script_checkpoint_invalid` have no observed Rex identity.
Play adds `stream_check` only after byte comparison is reached; an earlier
deadline can omit it. Published records add `fixture_path` and `stream`.
`stream.complete` means the captured interval has no pending partial wire frame,
not that the child finished: inspect `stream.end` (`child_exited`, `deadline`,
`cancelled`, or a failure) and the exit/outcome separately. A deadline can publish
an empty complete interval and still exit 124. Live checkpoint observations are
in `steps`; play checkpoint observations are in `checkpoints`.
Exit 0: complete record / faithful replay with all facts true / live steps true.
Exit 1: refusal, wire/creation/cleanup uncertainty, incomplete/hash mismatch.
`observation_failed` means the checkpoint observation command failed; it does
not establish corrupt recorded bytes. Check its child diagnostic and Rex-client
selection separately from the shared-`/tmp` prerequisite.
Exit 2: usage (no JSON). Exit 3: false/unknown facts, live divergence, or
`steps_not_run`. Exit 124: deadline; 130/143: interruption. Without `--keep-open`,
only this invocation's block is closed and absence verified. With it, the result
cannot claim absence; the private controller files are removed at exit.

## Script and facts files

Save this as an absolute `--script` file for live `/bin/echo cold-live`:

```json
{
  "schema_version": 1,
  "kind": "teerex_live_script",
  "id": "echo",
  "model_turns": 0,
  "steps": [
    {"expect": [{"id": "echo", "capture_contains": "cold-live"}], "within_ms": 1000},
    {"checkpoint": {"id": "end"}}
  ]
}
```

Each step has exactly one verb. The other supported shapes are
`{"write":"n"}`, `{"paste":"text"}`, `{"key":{"key":"Escape"}}`,
`{"resize":{"columns":80,"rows":24}}`, `{"sleep_ms":500}` and
`{"effect":{"relative_to":"cwd","path_exists":"result.txt"}}`.
Effects also accept `path_absent` with a relative path, or
`file_sha256:{"path":"result.txt","sha256":"<64 lowercase hex digits>"}`.
Paths must resolve inside cwd. `within_ms` is required for expect (100–60000);
sleep is 0–5000 ms. Add `"local_only":"reason this submits only to a local program"`
to any step that submits Enter/newline. A checkpoint value is an object with a
slug `id`, never a bare string. `needs_authoring:true` leaves a step unrun and
returns `steps_not_run`; it does not pass.

Save independently authored display assertions as the absolute `--facts` file:

```json
{
  "schema_version": 1,
  "kind": "teerex_display_facts",
  "id": "echo-display",
  "authored_by": "manual",
  "at": {
    "end": [{"id": "echo", "capture_contains": "cold-replay"}]
  }
}
```

`at` maps fixture checkpoint ids (or `end`) to fact lists. Each fact has a string
`id` and exactly one predicate. String values: `capture_contains`,
`capture_not_contains`, `status_state`, `mode_enabled`. Other values:
`capture_lines_in_order:["first","second"]`, `size:{"columns":80,"rows":24}`,
`process_running:true`, `child_exit_code:0`. `status_id` optionally selects a
named status record. Live expect uses the same fact-list shape, directly in the
step; it does not take an `at` envelope. With no `--facts`, play loads the fixture's
`facts.json` if present, otherwise checks stream fidelity without display facts.

The cold-reader failures (zero-byte echo record, live echo divergence and confirm
play deadline) reproduced with the docs checker's bubblewrap mounts: its Rex
server ran outside the sandbox, while `--tmpfs /tmp` hid the controller's gate
and player files from Rex. With the same installed teerex, Rex API13 build
`0.0.1794460237-g348d75`, session and commands, changing only `/tmp` to a shared
mount changed record/live/play exits from 124/3/124 to 0/0/0. Record captured
13 bytes and `child_exited`; confirm compared all 33 bytes equally. A shared
`TMPDIR` did not help because replay explicitly uses `/tmp`. The checker must
put its disposable Rex and controller in the same filesystem namespace (including
`/tmp`), or arrange a dedicated shared `/tmp` for both. Increasing deadlines or
updating only the installed binary does not correct this namespace mismatch.

## Verification

Run from the repository root. `test_terms.py` requires a built combined CLI at
`zig-out/bin/teerex` (see the [root build instructions](../../README.md)), or set
`TEEREX_BIN=/absolute/path/to/teerex` to select an existing build. This applies
to `OfflineTerms` too: its comparisons invoke the CLI. Use a build from the
revision being checked when validating that revision.

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

`teerex replay --help` uses the public command name, including when launched through the embedded Python controller.
