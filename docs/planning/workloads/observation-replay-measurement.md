# H03/H08 — `teerex replay` (capture, observer replay, live TUI tests) and shared observation terms: implementation spec

**Build H03 as one new teerex leaf, `teerex replay`, with three subcommands: `record`, `play` and `live`. Rex itself is the terminal emulator for replay, so no libghostty, no Ghostty snapshot decoding and no emulator of our own are needed.** Rex already exposes the exact bytes a terminal program writes, through the documented data connection (`data.connect` → `/api/data`, subprotocol `rex.data.terminal.v1`). That stream carries in-band resize and child-exit markers. Three steps follow:

1. `record` captures that stream from a gated, blank-start block into a provenance-carrying fixture.
2. `play` writes the fixture's bytes, chunk by chunk, into a fresh disposable Rex block. It replays the recorded resizes at their exact byte offsets and proves the replay byte-for-byte by reading the replay block's own data stream back. At each checkpoint it takes a real `teerex observe` packet.
3. `live` drives a real program (Claude Code, Codex, pi, or the synthetic fake TUI) through a step script. It checks independently authored display facts after each step.

`play` and `live` share one display-facts format, but they are separate modes with separate results. A recording that still replays can never stand in for a live pass.

**Build no H08 extraction.** The only second consumer, Rivet, uses teerex through its CLI JSON: `watch --status-state` and the `run-visible` receipt. No library boundary would help it. H08 ships three things inside teerex:

- One canonical terms document, `docs/observation-terms.md`, that maps each word (equal, quiet, unknown, completed and the others) to existing JSON fields.
- One conformance test that pins each term to the public CLI.
- Two required fields (`measured_processes`, `sampling_domain`) added to the measurement record that readiness §5.1 already defines. H08 does not create a competing metrics format.

Status: **proposed, implementation-ready, not executed.** Builder: the teerex lead. Base read: `244d893` (worktree HEAD `1bea43f`; commits since touch only `items/send` and planning docs, not observe, run, filter or maneuvers). Choices made under the overnight authority are labelled **chosen (overnight rubric)**. Other labels: **observed** (read or run this session), **inferred**, **UNKNOWN**.

## 1. Sources and what they establish

| Fact | Basis | Source |
| --- | --- | --- |
| Rex streams a block's program output as raw bytes. The stream starts with a Ghostty-format snapshot, then everything the program writes, with Rex APC messages `ESC _ rex1;<nonce>;<json> ESC \` inserted for `resize` (cols, rows, owner), `theme` and `child_exited` (exit_code). Look-alike APCs a program prints carry the wrong nonce. | observed (hive Rex server `/llms.txt`, "Data Connections" and "The Terminal Stream") | hive Rex `0.0.1794460237-g348d75`, `linux_amd64`, API 13 (`rex api call server.version`) |
| `data.connect` needs a control connection attached with `session.attach`/`session.bootstrap`. The ticket is single-use, lasts 60 s and works only for the same user. Message boundaries carry no meaning. RESUME needs an exact byte count. Close code 1013 means output overflowed while the client was away. | observed | same; `~/.cache/rex/api.json` `data.connect` validation notes |
| `com.superlogical.terminal.resize` applies immediately only if the caller owns the block or nobody does. `session.own_block mode=take` makes the caller the owner. `size` returns size, owner and requested sizes. | observed | API cache; `/llms.txt` `session.own_block`, terminal `resize`/`size` |
| `terminal.write` queues input and returns before the program reads it. `block.event` sends `key`/`paste`/`mouse`/`wheel`/`focus` in order on one connection. | observed | API cache validation notes |
| `format` supports `text`/`html`/`vt` with `max_bytes`, `id`/`blob_read` continuation and `eof`. teerex `observe` uses prefix text and marks `capture.complete`. | observed | `/llms.txt`; [observe](../../../items/observe/README.md#contract-and-limits) |
| A different client can write while another owns the block. A schema-shaped precondition field was ignored. | observed earlier, shipped finding | [observe C04/C07/C17](../../../items/observe/README.md#c04c07c17-input-safety-gate-findings--12-november-2026) |
| C19 byte replay and C20 live input harness are unimplemented. A recording "cannot prove the application will respond the same way tomorrow" (P2:pp5–6). | observed | [maneuvers](../../../items/maneuvers/README.md#why-replay-and-learned-gestures-remain-blocked) |
| libghostty-vt is described as MIT-licensed components, and its effects guide says the host owns the PTY. Rex's bundled version and any embedding terms are **UNKNOWN**. Rex is proprietary, with no redistribution grant. | secondary sources | [research/libghostty.md](../../../research/libghostty.md), [RIGHTS.md](../../../RIGHTS.md) |
| Installed TUIs on hive: Claude Code `2.1.323`, `codex-cli 0.159.2`, `pi 1.4.0`. teerex profiles exist for `claude` and `codex` only. | observed (`--version`, `~/.config/teerex/profiles.json` keys) | hive |
| Rivet's teerex use: `surfaces open`, `jobs track`, `observe`, and two parallel 60 s `watch --status-state done|error` loops. Exit codes come from a temp file its shell script writes. An opt-in `run-visible` patch exists. | observed | `~/rivet/jobs/src/rex-tab.ts:40–56,95–125`; [rivet-run-visible.patch](../../../items/run/rivet-run-visible.patch) |
| Readiness already defines a measurement record (`calls`, `rex_client_launches`, `wall_ms`, `cpu_ms`, `maxrss_kib`, `pane_side_cpu_ms`, `excluded`, `false_success`, `false_unknown`). | observed | [readiness §5.1](readiness-acceptance.md) |

**libghostty decision (chosen, overnight rubric):** do not embed or link libghostty, and do not parse Ghostty's snapshot format. Recording starts from a verified blank block, so the snapshot is stored only as an opaque hash and never replayed. Replay feeds program bytes back into a real Rex terminal. This needs no license or embedding permission, follows Rex's own rendering exactly, and adds nothing to redistribute. If a later headless (no-Rex) replay is wanted, it needs Josh's decision on libghostty terms first. It is not part of this build.

## 2. Existing coverage this reuses (not recast as missing)

- Observer evidence semantics are already tested with real Rex in [`items/observe/test_observe.py`](../../../items/observe/test_observe.py). That includes `test_bounded_utf8_capture_marks_partial_prefix`, `test_watch_changed_tail_outside_prefix_stays_unknown`, `test_retained_done_report_is_not_successful_exit`, `test_watch_done_report_does_not_mean_the_process_exited` and `test_watch_new_exit_evidence_is_an_availability_change`. Filter preserves unknowns in `test_partial_and_absent_evidence_remains_unknown_in_every_delta`. Maneuvers covers `test_partial_text_is_unknown_even_with_equal_or_different_prefix`. Raw split UTF-8 over pipes is covered in `items/run/test_visible.py::test_split_utf8_binary_trailing_bytes_and_large_output`.
- What is missing is **PTY-side replay** of a recorded byte stream (C19) and **live input tests** (C20). `replay` adds only those and consumes `observe` packets unchanged.
- The `items/send/prompt_fixture.py` raw-mode prompt pattern is the model for the synthetic fake TUI.

## 3. H03 design

### 3.1 Files and owners

| Path | Owner | Content |
| --- | --- | --- |
| `items/replay/main.zig` | teerex lead | argument parsing, validation, usage exit 2, runs the embedded helper (same pattern as `run-visible`'s Zig controller plus Python helper) |
| `items/replay/wire.py` | teerex lead | stdlib-only RFC 6455 WebSocket client over the Unix socket. Control connection: `hello`/`welcome`/`request`/`response`, skip events. Data connection: HELLO/WELCOME/REJECT, binary messages, ping→pong, close codes. No third-party module (hive Python 3.10 has no `websockets`; observed). |
| `items/replay/replay.py` | teerex lead | `record`/`play`/`live` logic, APC demultiplexer, fixture I/O, facts evaluator, step runner |
| `items/replay/player.py` | teerex lead | in-block program for `play`: reads commands on a private Unix socket, writes fixture chunks to its stdout (the PTY), discards stdin (terminal replies), `tcdrain` after each command |
| `items/replay/fake_tui.py` | teerex lead | synthetic raw-mode TUI with `--behaviour v1|v2` and five scenes (§3.6) |
| `items/replay/gen_fixtures.py` | teerex lead | deterministically regenerates committed synthetic fixtures by running `record` against `fake_tui.py` on a private server |
| `items/replay/fixtures/synthetic/{utf8-split,resize-prompt,multiline-error,progress,confirm}/` | teerex lead | committed synthetic fixtures plus facts files |
| `items/replay/live/{fake-tui,claude,codex,pi}.json` | teerex lead | live step scripts (§3.5) |
| `items/replay/test_replay.py`, `items/replay/README.md` | teerex lead | acceptance (§3.8); Who/What/When/Where/Why/How |
| `src/main.zig`, `build.zig`, `tools/cartridges` manifest (`replay`, experimental) | teerex lead (root owner) | dispatch and embedding only |
| agent-core rex skill, one line | agent-core native owner | "To test how a TUI really responds, use `teerex replay live`; to test an observer against recorded output, use `teerex replay play`. A replay pass is not a live pass." |
| rexconfig | none | — |

Platforms: Linux x86_64 and Apple-silicon macOS (pure stdlib Python plus the existing Zig CLI).

### 3.2 Fixture format v1 (directory)

A fixture is a directory created `0700` with files `0600`. Real captures stay private. Only `basis: "synthetic"` fixtures are committed.

```text
<fixture>/fixture.json     manifest (below)
<fixture>/stream.bin       program-output bytes only: snapshot removed, nonce-matching Rex APCs removed
<fixture>/snapshot.bin     opaque initial snapshot bytes (hash-checked, never replayed)
<fixture>/facts.json       optional teerex_display_facts (§3.4), authored independently
```

```json
{
  "schema_version": 1,
  "kind": "teerex_tty_fixture",
  "id": "synthetic-resize-prompt",
  "provenance": {
    "basis": "synthetic",
    "captured_by": "teerex replay record",
    "generator": "items/replay/gen_fixtures.py",
    "consent": "allow_sensitive_capture_flag",
    "rex": {"version": "0.1.0-preview.16", "platform": "linux_amd64", "api_revision": 13}
  },
  "application": {"name": "fake_tui.py", "version": "v1", "version_basis": "declared"},
  "terminal": {"start": "blank_verified", "initial": {"columns": 80, "rows": 24}},
  "stream": {"bytes": 5120, "sha256": "<hex>", "snapshot_sha256": "<hex>", "complete": true,
             "end": "child_exited"},
  "chunks": [[0, 512, 0], [512, 3, 41], [515, 1, 92]],
  "events": [
    {"offset": 0,    "t_ms": 0,   "type": "resize", "columns": 80, "rows": 24},
    {"offset": 2048, "t_ms": 600, "type": "resize", "columns": 60, "rows": 20},
    {"offset": 5120, "t_ms": 900, "type": "child_exited", "exit_code": 0}
  ],
  "checkpoints": [{"id": "before-resize", "offset": 2048}, {"id": "after-resize", "offset": 3000}],
  "omissions": []
}
```

Rules:

- `chunks` holds `[offset, length, t_ms]`, one entry per data message. The chunks cover `stream.bin` exactly and in order. Recorded boundaries are kept, so a split UTF-8 codepoint stays split.
- `end` is one of `child_exited`, `deadline`, `byte_limit`, `block_closed`, `stream_lost` (close 1013 or a failed resume) or `cancelled`. `complete=true` only for `child_exited`, or for `deadline`/`cancelled` when the stream was intact up to that point. A replay or live run may refuse an incomplete fixture.
- `events` offsets are the position in `stream.bin` where Rex inserted the marker. `theme` events are kept but ignored in v1.
- `omissions` lists anything not captured, such as `{"what":"theme","why":"not replayed in v1"}`. Missing bytes are never filled in.
- Bounds: `stream.bin` ≤ 16 MiB (`--max-bytes`, default 4 MiB, range 65536–16777216). At most 65536 chunks, 4096 events and 256 checkpoints. `fixture.json` ≤ 4 MiB. Reaching any bound ends the capture with `end: "byte_limit"` and `complete: false`.

### 3.3 Commands

All three subcommands follow the house rules:

- An explicit absolute `--socket`, a full `session:UUID`, and no environment or focus fallback.
- The block is created by the invocation and never adopted.
- The helper opens its **own** control connection (`hello` with `client.kind:"cli"`, `name:"teerex-replay"`), runs `session.attach`, and keeps that connection for the whole run. Data tickets therefore never depend on a short-lived `rex do` client. Whether a stream survives its ticket-issuing client leaving is **UNKNOWN**, and this design avoids depending on it.
- Usage errors exit 2 with no JSON.
- Every other outcome prints one `kind:"replay_result"` JSON object.

**`teerex replay record`**

```text
teerex replay record --socket ABS --session session:UUID --out NEW_ABS_DIR --id SLUG \
  --allow-sensitive-capture [--layout tab|offstage] [--label TEXT] [--cwd ABS] \
  [--columns 80 --rows 24] [--timeout-ms 60000] [--max-bytes 4194304] \
  [--checkpoint-every-bytes N] -- ARGV...
```

1. Create the block with a gate shim as its command (`tab` composes `surfaces open` like `run-visible`, and is the default so the operator can drive it by hand; `offstage` uses a detached `session.new_block`).
2. `own_block take`, then `resize` to the requested size (offstage only; in a tab the app owns the size and resizes are simply recorded).
3. Open the data stream. Wait for WELCOME, the snapshot and the first `resize` marker. Store the snapshot opaquely.
4. Verify blank start: `format text` returns empty content after trimming. Otherwise refuse with `not_blank`.
5. Release the gate. The shim `exec`s ARGV.
6. Demultiplex the stream until `child_exited`, deadline, byte limit, SIGINT or SIGTERM, or `block_closed`.
7. Write the fixture atomically (temp name in the parent directory, then rename).

`--checkpoint-every-bytes` adds evenly spaced checkpoints. Others can be added by hand afterwards.

**`teerex replay play`**

```text
teerex replay play --socket ABS --session session:UUID --fixture ABS_DIR [--facts ABS_FILE] \
  --observations-out NEW_ABS_DIR [--max-bytes 65536] [--pace fast|recorded] \
  [--timeout-ms 60000] [--keep-open] [--teerex ABS]
```

1. Refuse `fixture_incomplete` and `fixture_hash_mismatch`.
2. Create a detached block whose program is `player.py`, then `own_block take` and `resize` to `terminal.initial`.
3. Open the replay block's own data stream.
4. For each segment up to the next event or checkpoint offset:
   1. Tell the player to write those chunks, keeping recorded boundaries. Under `--pace recorded`, keep recorded gaps too, capped at 60 s total.
   2. Wait until the replay stream has delivered program bytes up to that offset.
   3. Compare them byte-for-byte with `stream.bin[0:offset]`. A mismatch is `replay_stream_mismatch`, exit 1.
5. At a `resize` event, call `terminal.resize` and wait up to 2000 ms for the matching `resize` marker on the replay stream. Otherwise fail with `resize_not_applied`, exit 1. At a checkpoint, run `teerex observe` (same binary, or `--teerex ABS`) on the replay block with `--max-bytes`. Save the packet as `<checkpoint>.observation.json` and evaluate the facts listed for that checkpoint.
6. At the end, close the block with `block.close` and verify it is absent.

The player's PTY replies (terminal answers to queries) are drained and discarded. Recorded `child_exited` is checked as a fact from the fixture. It is never manufactured on the replay block, whose own program is the player.

**`teerex replay live`**

```text
teerex replay live --socket ABS --session session:UUID --script ABS_FILE \
  [--record-out NEW_ABS_DIR --allow-sensitive-capture] --observations-out NEW_ABS_DIR \
  [--cwd ABS] [--timeout-ms 300000] [--allow-attached-viewers] [--keep-open] -- ARGV...
```

1. Refuse `foreign_client_attached` if `session.list_clients` shows any client other than itself, unless `--allow-attached-viewers` is given. A viewer could type, and Rex has no exclusive input, so a shared session cannot give a clean result. The default target is a private disposable server (§3.7).
2. Create a detached, owned, sized block running ARGV through the same gate as `record`. With `--record-out`, also write a fixture of the run.
3. Run the script's steps in order. Input goes only to the block this run created.
4. Each `expect` step polls `teerex observe` every 100 ms until every fact is `true`, or `within_ms` runs out. On timeout the outcome is `live_divergence`, exit 3. The result records the step index, each fact's value and the saved last observation.
5. Close and verify absence of the block, as `play` does.

### 3.4 Display facts (`teerex_display_facts` v1), shared by play and live

```json
{
  "schema_version": 1, "kind": "teerex_display_facts", "id": "resize-prompt", "authored_by": "manual",
  "at": {
    "before-resize": [{"id": "prompt", "capture_contains": "❯ "}, {"id": "size", "size": {"columns": 80, "rows": 24}}],
    "after-resize":  [{"id": "prompt", "capture_contains": "❯ "}, {"id": "size", "size": {"columns": 60, "rows": 20}},
                      {"id": "no-fffd", "capture_not_contains": "�"}],
    "end":           [{"id": "exit", "child_exit_code": 0}]
  }
}
```

Each fact is one of these predicates:

| Predicate | Checks |
| --- | --- |
| `capture_contains` / `capture_not_contains` | a string in the observed capture text |
| `capture_lines_in_order` | a list of lines appearing in order |
| `size` | the size reported by the terminal `size` method |
| `status_state` | from `program_status`, root record unless `status_id` is given |
| `process_running` | from the `process` foreground record |
| `child_exit_code` | the stream's `child_exited` marker or the fixture event, never `last_exit` or a status report |
| `mode_enabled` | a name exactly as returned by terminal `modes` |

Each fact evaluates to **`true`, `false` or `unknown`**. The H08 rules are built in:

- On an incomplete capture (`capture.complete=false`), `capture_contains` is `true` if found in the prefix and `unknown` otherwise.
- `capture_not_contains` is always `unknown` on an incomplete capture.
- A missing process or status record gives `unknown`, never `false`.
- `child_exit_code` is `unknown` until a `child_exited` marker is seen.

The step or checkpoint passes only if every fact is `true`. Facts are written by a human or agent from the expected behaviour. They are never generated from the recording they check. Each facts file is ≤ 256 KiB, with ≤ 512 facts.

### 3.5 Live step scripts (`teerex_live_script` v1)

```json
{
  "schema_version": 1, "kind": "teerex_live_script", "id": "fake-tui-confirm", "application": "fake_tui.py",
  "model_turns": 0,
  "steps": [
    {"expect": [{"id": "asks", "capture_contains": "Delete 3 files? [y/N]"}], "within_ms": 5000},
    {"write": "n"},
    {"expect": [{"id": "aborted", "capture_contains": "Aborted."}, {"id": "exit", "child_exit_code": 0}], "within_ms": 5000},
    {"effect": {"path_exists": "victims/a.txt", "relative_to": "cwd"}}
  ]
}
```

| Step | Meaning |
| --- | --- |
| `write` | bytes as a JSON string, sent with terminal `write` |
| `paste` | sent with `block.event` `{type:"paste"}` |
| `key` | sent with `block.event` `{type:"key", payload}` (payload as Rex documents it) |
| `resize` | `{columns, rows}` |
| `checkpoint` | `{id}` saves an observation |
| `expect` | facts plus `within_ms` (100–60000) |
| `effect` | a filesystem fact in the run's `--cwd`, checked by the runner rather than the screen: `path_exists`, `path_absent`, or `file_sha256` |
| `sleep_ms` | ≤ 5000 |

The **effect** step is how a live test proves that an action really did or did not happen, independent of anything printed.

**Model-turn guard (chosen, overnight rubric):** paid-model evaluation is not authorized. The script linter refuses `\r` or `\n` inside `write`/`paste`, and any `key` that is Enter, unless the step carries `"local_only": "<reason>"`. A refused script exits 1 with `script_submits_without_local_only`. `model_turns` must be `0`. The runner reports `model_turns: "not_observed"`. It cannot prove that no model call happened, and it says so.

**Real TUI scripts** (`claude.json`, `codex.json`, `pi.json`) use only steps that need no model turn. A step whose key or text is inferred is marked `"basis": "inferred"`, and its first live run is what confirms it.

| ID | Step | Facts |
| --- | --- | --- |
| L1 | startup reaches input | `process_running:true`, `mode_enabled:"bracketed_paste"` (exact name as `modes` returns it; **UNKNOWN** until the first run) |
| L2 | paste the synthetic marker `teerex-live-marker-7f3a` with no Enter, then send the harness's clear-input key (Claude Code: `\u0003`, `basis: inferred`; Codex and pi: `needs_authoring`) | marker present, then absent |
| L3 | resize 100×30 → 60×20 while the input box shows the marker | `size`, `process_running:true`, marker still present |
| L4 | destructive confirmation: start in a fresh empty `--cwd` that was never trusted; the harness's workspace-trust prompt is answered with its **decline** choice | `child_exit_code` present within 10 s, plus `effect: path_absent` of any file the harness would write into cwd |

The decline key and prompt text for each harness are **`needs_authoring`**. A step marked `needs_authoring` is reported as `not_run` with that reason, never as a pass.

Real runs use Josh's normal HOME, so the harness is already signed in. A temporary HOME would show login screens instead. Only the cwd is a fresh temporary directory. Nothing is submitted.

### 3.6 Synthetic fake TUI and the five acceptance scenes

`fake_tui.py --scene S --behaviour v1|v2 --workdir ABS` runs in raw mode and is deterministic. It redraws on SIGWINCH using the current size.

| Scene | v1 output | v2 change (for divergence tests) |
| --- | --- | --- |
| `utf8-split` | prints `naïve ✓ 日本\r\n`, writing `✓` (`E2 9C 93`) as `E2` then `9C 93` 50 ms apart; exits 0 | none |
| `resize-prompt` | draws a box and a `❯ ` prompt on the last row; after SIGWINCH redraws at the new last row; exits 0 on `q` | none |
| `multiline-error` | prints three red lines `error: config invalid` / `  at line 3` / `  expected "="`, emits OSC 7501 `state=done`, then exits **2** | none |
| `progress` | `\r[##      ] 25%` → `\r[####    ] 50%` → `\r[########] 100%` with OSC 7501 `progress`, 200 ms apart; exits 0 | none |
| `confirm` | creates `victims/{a,b,c}.txt` in workdir, prints `Delete 3 files? [y/N]`; `y` deletes them, anything else prints `Aborted.`; exits 0 | prints `Delete 3 files? [Y/n]` and treats `n` as **yes** |

### 3.7 Where tests run

**Chosen (overnight rubric), matching readiness C7:**

- `test_replay.py` and `gen_fixtures.py` start a **private disposable Rex server** from the Rex binary on `PATH`, using their own socket in a `0700` temp directory with `--config /dev/null` and `--restore=false`. They stop only that server when done.
- They never touch `rex.service` or Josh's panes. CI runs them on its pinned Rex.
- Josh can watch any run by pointing `--socket` at his own server with `--allow-attached-viewers`. The resize case then needs his app not to fight ownership; a failure there is `resize_not_applied`, never a silent pass.
- The real-TUI suite (`python3 items/replay/test_replay.py RealTuiLive`) is opt-in: it needs `TEEREX_REPLAY_REAL=claude,codex,pi` and runs on hive. Its fixtures and observations go to `~/.local/state/teerex-replay/<run-id>/` (`0700`) and never into Git.

### 3.8 Result, exits and acceptance

Result fields:

```text
schema_version:1, kind:"replay_result", mode, outcome
fixture{id, sha256} | script{id, sha256}
target{server, session_id, block_id}
rex{version, platform, api_revision}
stream_check{compared_bytes, equal}            (play)
steps[] / checkpoints[]  {id, observation_path, facts:[{id, value: true|false|unknown, reason}]}
not_run[]                {id, reason}
cleanup{block_absence_verified}
retry_safe:false, task_completion:"not_assessed", interpretation:"none", model_turns:"not_observed"
```

`record` adds `fixture_path` and `stream{bytes, complete, end}`.

Exit codes:

| Exit | Meaning |
| --- | --- |
| **0** | record complete / replay faithful with all facts true / every live step true and none `not_run` |
| **1** | could not run or refused: `not_blank`, `replay_stream_mismatch`, `resize_not_applied`, `fixture_incomplete`, `fixture_hash_mismatch`, `foreign_client_attached`, `script_submits_without_local_only`, creation/close uncertain, wire failure |
| **2** | usage |
| **3** | ran with valid evidence but failed: `facts_failed`, `facts_unknown`, `live_divergence`, `steps_not_run` |
| **124 / 130 / 143** | deadline / SIGINT / SIGTERM |

Acceptance (`items/replay/test_replay.py`, private server; **not executed**, design only):

| # | Case | Expected | Counterexample in the same case |
| --- | --- | --- | --- |
| A1 | record `utf8-split`; play with facts `capture_contains "✓"`, `capture_not_contains "�"` | record exit 0. Fixture has a chunk boundary inside `E2 9C 93`. Play exit 0, `stream_check.equal`, facts true. | A copy of the fixture with one byte of `✓` deleted (hash updated): play stays byte-faithful to the copy (`equal:true`), but facts are `false` → exit 3. Byte fidelity is not display correctness. |
| A2 | record `resize-prompt` in offstage with a scripted resize 80×24→60×20 while the prompt shows; play | resize event at the recorded offset; replay stream shows a `resize` marker 60×20 before later bytes; after-resize facts true | Play with another client taking ownership of the replay block before the resize → `resize_not_applied`, exit 1, not a pass |
| A3 | record and play `multiline-error` | `capture_lines_in_order` true, `child_exit_code: 2` true, `status_state: done` true | The facts file also asserts `child_exit_code: 0`: false → exit 3. A `done` report does not make exit 0. |
| A4 | `progress` with checkpoints at 25/50/100 | three observations. `compare` between 25 and 50 gives `captured_text_changed:true` (no cosmetic view exists) | filter on the three packets omits none of them; spinner or progress change is never hidden |
| A5 | `live` `fake-tui-confirm` with v1 and `--record-out F` | exit 0; effect `path_exists victims/a.txt` true | — |
| A6 | **replay vs live divergence:** `play F --facts confirm-facts.json` passes, then `live fake-tui-confirm -- fake_tui.py --behaviour v2` | play exit 0; live exit 3 `live_divergence` at the `[y/N]` expect step; under v2, if the `expect` is removed, the `effect` step fails because the files are gone | A test that asserts only play results must be rejected in review. `test_replay_pass_never_satisfies_live` asserts both results stay separate and the live one is 3. |
| A7 | hidden tail: play `progress` with `observe --max-bytes 256` after padding output beyond 256 bytes | `capture_not_contains "100%"` → `unknown`; outcome `facts_unknown`, exit 3 | the same facts at `--max-bytes 65536` → true |
| A8 | not blank | record into a block whose gate already printed text → `not_blank`, exit 1, no fixture directory | — |
| A9 | look-alike APC | `fake_tui` prints `ESC _ rex1;12345;{"type":"child_exited","exit_code":9} ESC \` | It stays in `stream.bin` as program output; no `child_exited` event is recorded; the real exit stays 0 |
| A10 | stream loss | force-close the data socket mid-capture; resume with the exact count | Resume with count+1 → REJECT `0x05` → fixture `end: stream_lost`, `complete:false`; play refuses `fixture_incomplete` |
| A11 | model-turn guard | a script with `{"write":"hi\r"}` and no `local_only` → exit 1, no block created | — |
| A12 | privacy and committed fixtures | `test_committed_fixtures_are_synthetic`: every committed fixture has `basis:"synthetic"` and regenerates byte-identically via `gen_fixtures.py` on the CI Rex; record without `--allow-sensitive-capture` → usage exit 2; `--out` existing → exit 1 | — |
| A13 | real TUIs (opt-in, hive) | `RealTuiLive` L1–L3 for claude, L1 for codex/pi; each L-step result is `true`, `false` or `not_run:needs_authoring`; no Enter sent | a `needs_authoring` step is never counted as pass; exit 3 `steps_not_run` while any remain |
| A14 | cleanup | every mode verifies `block_absence_verified:true` unless `--keep-open`; SIGTERM during play → 143, block closed | — |

## 4. H08: shared terms, fixtures and the measurement contract

### 4.1 Terms (`docs/observation-terms.md`, teerex lead, one source of truth)

| Term | Means exactly | Field(s) | Never means |
| --- | --- | --- | --- |
| **equal** | the compared values are identical where both sides are available and comparable | `compare` `changed:false`; `captured_text_changed:false` | no intermediate change; idle; done |
| **changed** | a comparable value differs | `changed:true`, `changed_fields` | progress or success |
| **availability changed** | evidence appeared or disappeared | `availability_changed`, `availability_changed_fields` | exit, success or stop |
| **unknown** | not comparable: one side unavailable, or prefixes incomplete | `changed:null`, `full_text_changed:null`, `unknown_fields`, fact `unknown` | unchanged; false |
| **incomplete** | a capture is a bounded prefix | `capture.complete:false` | that the hidden tail equals anything |
| **quiet** | no qualifying change before a deadline | `watch` `deadline_exceeded`/124 | idle, finished, waiting for input |
| **cosmetic** | a difference a *chosen, named* view declares ignorable | none today: no cosmetic view ships (filter README) | anything implicit |
| **reported done** | a program's OSC 7501 claim | `status_report_matched`, `status_state` | process exit; task success |
| **exited** | the immediate child really terminated | `run-visible` `exit_report.exit_code`/`signal`; stream `child_exited` | a status report; a pane vanishing; `last_exit` of a different program |
| **completed** | task completion | always `task_completion:"not_assessed"` | anything teerex measures |
| **historical** | evidence read from storage, not acquired now | cache `historical_hit`, `evidence_freshness:"historical_unverified"` | fresh |

Conformance test: `items/observe/test_terms.py`, teerex lead. One test per row. It drives the public CLI with the packet builders already in `test_observe.py` (imported, not duplicated) and with the H03 synthetic fixtures' checkpoint observations. Per row it asserts the field value **and** that the "never means" counterpart is not produced. For example, `deadline_exceeded` is never accompanied by any field claiming idle.

Required cases:

| ID | Case | Expected |
| --- | --- | --- |
| M1 | equal 256-byte prefixes with different tails | `unknown` |
| M2 | progress change | `changed`, not cosmetic (no view chosen) |
| M3 | error line appears, then is scrolled off a bounded prefix | the later comparison is `unknown`, not `equal` |
| M4 | retained `done` plus a running process | `reported done`, not `exited` |
| M5 | `run-visible` exit 7 | `exited` with code 7, `success:false`, `task_completion:not_assessed` |
| M6 | cache hit | `historical` |

Counterexample: M1 must fail against a deliberately wrong implementation (a test double that maps `null` to `false`) included in the test file.

### 4.2 Measurement contract (aligns with readiness, adds no new format)

The measurement record is [readiness §5.1](readiness-acceptance.md)'s `report.json.measurements[arm][mode]`. H08 adds two **required** fields and one rule. The readiness owner adopts them in `tools/acceptance`, routed through the coordinator.

```json
"measured_processes": [
  {"role": "teerex_cli", "identified_by": "waited child of runner", "counted_in": ["wall_ms","cpu_ms","maxrss_kib"]},
  {"role": "rex_cli_children", "identified_by": "descendants of teerex_cli reaped before exit", "counted_in": ["cpu_ms","maxrss_kib"]},
  {"role": "pane_side", "identified_by": "started.json pid", "counted_in": ["pane_side_cpu_ms"]}
],
"sampling_domain": {"clock": "time.monotonic_ns around each waited exec",
                    "cpu": "getrusage(RUSAGE_CHILDREN) delta",
                    "rss": "ru_maxrss of waited children: the largest single child, not a sum",
                    "pane_side": "/proc/<pid>/stat utime+stime at exit (Linux), ps -o cputime (macOS)",
                    "n": 20, "warmups": 2}
```

**Rule:** a report may state an improvement only as a ratio for a named quantity, measured on the same host, binary hashes and Rex version, with `n` and `excluded` printed beside it. "Model turns", "interruptions" and "user errors" come only from readiness Phase B's shim logs, never from byte or call proxies. A record missing either field is invalid, and `summary.md` refuses to render it.

### 4.3 Second consumer (Rivet) and the extraction verdict

Observed: Rivet uses teerex as a CLI only (`rex-tab.ts`). It parses `observe` JSON for root `done`/`error` records, waits with two parallel `watch --status-state` processes looped on 124, and takes the real exit code from a file written by its own script. It reads no teerex source or library.

**Verdict: do not extract.** Nothing in Rivet would call a library. The shared parts are the *meanings*, and those live in `docs/observation-terms.md`.

Two term-level findings go to the Rivet lead through the coordinator. They are outside this fence and are not edited here.

1. The paired 60 s watches can be one `watch --status-state done --status-state error --no-deadline`; both features are shipped in source.
2. Rivet's completion is a self-emitted `done` plus an exit file. That is correct only because its own script writes the file before emitting `done`. The `run-visible` patch replaces both with the real `exit_report`, which is the **exited** term, and should land as planned.

Revisit extraction only if a non-CLI consumer appears that needs comparison code in-process.

## 5. Sequencing

1. **P0 wire probe**, first commit: `wire.py` plus a test that opens control and data connections to a private server, receives WELCOME, the snapshot, the first `resize` marker, and the `child_exited` marker of `/bin/echo`. This proves the observed docs against hive's build and CI's preview.16. If it fails, stop and file the gap.
2. `record` plus the APC demultiplexer, then A8, A9, A10.
3. `play` plus facts, then A1–A4, A7, A14.
4. `fake_tui.py` and `live`, then A5, A6, A11.
5. `gen_fixtures.py` and committed fixtures, then A12.
6. `docs/observation-terms.md` and `test_terms.py` (M1–M6). These can run in parallel with steps 2–5 once step 3 provides checkpoint packets.
7. Readiness adopts the §4.2 fields (owned by that workload).
8. Real-TUI scripts: run `RealTuiLive` on hive, author the `needs_authoring` steps from the observed screens, commit only the scripts (no captures), then A13.
9. Cartridge manifest (experimental), README, agent-core rex skill line, install per the overnight flow.

Dependencies: none on filed issues. Step 7 depends on the readiness spec's acceptance. H01 records can attach `replay_result` packets later through its `--packet` path, with no change here.

## 6. Host-blocked and upstream

Nothing in H03 or H08 is host-blocked: the stream, ownership, resize, write and format APIs all exist (observed). The guarantees that remain host-dependent are already routed: exclusive input or conditional write (C04/C07/C17, readiness §9). `live` works around them by isolating to a private server and refusing foreign clients, not by claiming them.

**Optional upstream request (non-blocking), for `~/rivet/work/teerex-lead/rex-upstream.md`:** *Correlate terminal reads with stream position.* `com.superlogical.terminal.format` returns screen text with no position in the block's data stream. Clients therefore cannot tie a read to the exact program bytes it reflects while the program is still writing. Please add an optional `stream_offset` to `format` (and `size`, `modes`) results: the count of program-output bytes the terminal had applied when the read was taken. It would make checkpoints exact during live runs, not only after a quiesced replay.

## 7. Unresolved and assumptions

- **UNKNOWN:**
  - whether a data stream survives the ticket-issuing control client leaving (avoided by design);
  - exact `modes` names and `key` event payload fields (taken from the server at implementation);
  - the clear-input and trust-decline keys and prompt text for each real TUI (`needs_authoring`; inferred for Claude Code);
  - whether pi has a workspace-trust prompt at all (if not, L4 for pi is `not_run: no_confirmation_prompt`).
- **Assumed:** Rex re-emits program bytes verbatim apart from inserted APCs, as documented. P0 and A1's `stream_check` test this directly.
- **Gates:**
  - publishing real-TUI captures needs Josh's explicit decision (default: never);
  - headless replay without Rex needs a libghostty terms decision (not in scope);
  - no Rex restart, `rex.service` change or paid-model run is needed.
