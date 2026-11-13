# C03/C21/C22 presentation view with C24 safety: implementation spec

**Build one opt-in, declared cosmetic view and let `compare`, `watch` and `filter` consume it.** A view is a small rules file, or the built-in `progress-v1`, that names spans such as spinner glyphs, elapsed timers and token counters. When the only difference between two captures falls inside those spans, the result is labelled `cosmetic_only`. The raw comparison stays in the output, along with the exact before/after text of every masked span.

The key change is to `watch`. Today, any spinner or timer in the captured text makes `watch` return almost at once, which makes it useless on agent panes. With `--view`, cosmetic-only comparisons are counted but do not wake the caller. Errors, prompts, exits, status, process, directory, availability and unknowns are never maskable and still wake it.

`filter --view` omits cosmetic-only payloads losslessly: the referenced payload plus the listed spans reproduces the exact capture. Benefit is measured against the [Q02/C31/C32 baseline](readiness-acceptance.md#51-phase-a-deterministic-arms-teerex-versus-plain-rex) with the same measurement fields, plus false wakes, false suppression and hidden-tail unknowns.

**Authority and labels.** This spec is implementation-ready under Josh's standing overnight authority (seat file `overnight-2026-11-13.md`, 13 November 2026), which voids the [roadmap's](../../roadmap.md#consider-presentation-filtering-only-after-measurement) "only after measurement" gate. Measurement is now part of acceptance (§7), not a precondition.

- **Observed:** facts read at worktree head `1bea43f` (base `244d893` plus send/agents/boards and the U01/U02 spec). That head does not touch `items/observe`, `items/filter` or `items/maneuvers`.
- **Chosen (overnight rubric):** marks a decision made with Josh's rubric of 10X developer, agentic and user experience.
- **Build owner:** the teerex lead (`block:01a1d34f-9a09-7392-b8e8-17046462c623`), except for the agent-core line in §8.
- **Not executed:** nothing in this document has been run. Every acceptance case in §7 runs once the files in §8 exist.

## 1. What exists, and what this adds

| Exists today (observed) | Gap this closes |
| --- | --- |
| `compare` gives typed `observation_changes` with `captured_text_changed` and `full_text_changed`. The latter is null unless both captures are complete. `interpretation="none"` ([observe README, C03](../../../items/observe/README.md#what-c03-adds-and-teaches)). | No way to say "these differences are only the spans I declared cosmetic". |
| `watch` wakes when `changed_fields` or `availability_changed_fields` is non-empty (`items/observe/main.zig`, the collector's `satisfied` test). Any captured-text change qualifies. | A pane with a spinner or timer in its captured text wakes `watch` every interval (default 250 ms), so callers fall back to polling `observe`. That is the repetitive-read cost. |
| `filter --sample…` omits only intermediate payloads whose typed evidence is identical. It always keeps adjacent comparisons and the final checkpoint, and says "No cosmetic filter is enabled or available" ([filter README](../../../items/filter/README.md#use)). | A ticking timer defeats deduplication, so every sample is emitted in full. |
| The `filter cache` gives historical hits only (C21's retained observation). | Unchanged. C21's "last stable observation" and "known phase" stay out of scope (§9). |
| The `maneuver-check` exact whole-capture match "deliberately rejects cosmetic churn" ([maneuvers README](../../../items/maneuvers/README.md)). | Unchanged. Applying views to recognition is a separate later choice, not part of this build. |

This build extends those three verbs. It adds no new verb, service, store, background process or Rex read. Mapping to the source items ([inventory](../teerex-pdf-work-inventory.md), P2:p2 and P2:p6):

- **C03:** adds deltas, kept separate from interpretation.
- **C22:** suppresses cosmetic churn, keeps the raw evidence and tests both cosmetic and meaningful changes.
- **C21:** adds only the view part; the existing cache stays as is.
- **C24:** acts as a hard constraint. Nothing here says stable, idle, complete or awaiting input.

## 2. Decisions (all chosen, overnight rubric)

| # | Decision | Why |
| --- | --- | --- |
| V1 | **One view model and one rules format**, implemented once in `items/observe/view.zig` and consumed by `compare`, `watch` and `filter`. Filter already links observe's validator and comparator statically ([cartridges.md](../../cartridges.md)), so the cartridges stay independent. | One meaning everywhere, and one test surface. |
| V2 | **Opt-in per invocation**, through `--view NAME` (built-in) or `--view-rules FILE`. The two are mutually exclusive. There is no default view, no environment variable and no config file. | It cannot silently change an existing caller's evidence. |
| V3 | **A rule matches declared tokens inside one line, with literal anchors.** There is no general regex: matching is linear-time, there is no ReDoS risk and spans never cross newlines. | Predictable, auditable, and cheap in Zig without a regex dependency. |
| V4 | **Protected lines are never masked.** This is a fixed built-in list; callers can add to it but cannot remove from it (§3.3). | C24: an asymmetric prompt or error that happens to contain a timer surfaces as a real change. That is a false wake, never a false suppression. |
| V5 | **Only captured text is ever maskable.** Process, last exit, reported directory, program status, availability, source and target are always compared raw. | Exits and reports are where completion-like evidence lives. A view must not touch them. |
| V6 | **Losslessness.** Every masked difference is emitted as an exact span with before and after text. Omitted filter payloads are byte-reconstructible. | The raw delta is kept and the view is only a presentation. |
| V7 | **Ship the built-in `progress-v1`** (§3.4) so agents need no setup for Claude- and Codex-style progress lines. Its glyph and anchor list is calibrated by acceptance case A-cal. A missed pattern fails safe as a false wake. | 10X agentic: `watch --view progress-v1` works on an agent pane first time. |
| V8 | **Watch wakes on `changed` or `unknown` view verdicts, never on `cosmetic_only`.** `--view` is refused together with `--status-state`, where it would have no effect. | Status waits already ignore text, so refusing the combination avoids a silent no-op. |
| V9 | **Hidden tails stay unknown.** The view never reports a `full_text` verdict unless both captures are complete. Until N07 lands, prefix captures limit the view to what the prefix holds. | This matches C03's existing comparability rules. |

## 3. View rules format

### 3.1 File

The file is a regular file of at most 16 KiB, UTF-8 JSON, using the same strict parser posture as observations. Unknown fields, duplicate keys and wrong `kind` or `schema_version` are refused. FIFOs, devices and directories are refused, and the file is opened non-blocking.

```json
{
  "schema_version": 1,
  "kind": "rex_presentation_view",
  "id": "my-build-progress",
  "note": "Synthetic example: build tool prints a percent and an elapsed timer.",
  "protect_also": ["deploy"],
  "rules": [
    { "id": "pct",     "position": "anywhere",   "pattern": "[{digits}%]" },
    { "id": "elapsed", "position": "anywhere",   "pattern": "elapsed {digits}.{digits}s" },
    { "id": "spin",    "position": "line_start", "pattern": "{one_of:⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏} " }
  ]
}
```

| Field | Rule |
| --- | --- |
| `id` | 1–64 bytes from `[a-z0-9._-]`. |
| `note` | Optional, at most 512 bytes. It is echoed nowhere. |
| `protect_also` | Optional, at most 32 entries of 1–64 bytes each. These are extra case-insensitive ASCII substrings added to §3.3. |
| `rules` | 1–32 entries. Each rule `id` is unique and follows the same charset as the top-level `id`. |
| `rules[].position` | `anywhere`, or `line_start` (after optional leading spaces and tabs only). |
| `rules[].pattern` | 1–256 bytes, using the grammar in §3.2. |

### 3.2 Pattern grammar

| Token | Matches |
| --- | --- |
| literal text | Itself, byte for byte. `{{` and `}}` are literal braces. |
| `{digits}` | 1–12 ASCII digits, greedy. |
| `{number}` | `{digits}`, optionally followed by `.` and 1–6 digits, then optionally one of `k K m M`. |
| `{one_of:CHARS}` | Exactly one Unicode code point from CHARS. CHARS holds 1–32 code points with no newline, no `}` and no duplicates. |

Validation refuses a rule when:

- it has more than 8 tokens;
- it has adjacent variable tokens with no literal between them;
- it contains a newline anywhere;
- it is **unanchored**. A rule is anchored if its literal text has at least 2 non-whitespace code points. The only exception is a rule made of a single `{one_of}` (plus optional literal whitespace) whose set contains no ASCII code point. So `{one_of:|/-\}` alone is refused, because it would mask path separators and hyphens. `[{one_of:|/-\}]` is accepted.

**Matching.** Each line is scanned left to right. At each byte offset, rules are tried in declaration order and the first match wins. A match consumes its span, and matches never overlap. Literals match exactly, `{digits}` and `{number}` are greedy without backtracking into the following literal, and a failed match advances one code point. The masked line replaces each match with the placeholder `U+FFFC` followed by the rule index. Masked text is used only for equality and is never emitted.

### 3.3 Protected lines (fixed, extendable only)

A line is never masked, in either capture, if its ASCII-lowercased bytes contain any of the following, or any `protect_also` entry:

`error`, `fail`, `fatal`, `panic`, `exception`, `traceback`, `abort`, `killed`, `denied`, `refused`, `exit`, `warning`, `permission`, `password`, `passphrase`, `token:`, `allow`, `approve`, `confirm`, `[y/n]`, `(y/n)`, `(yes/no)`, `press enter`

A line is also protected if, after trimming trailing whitespace, it ends in `?`, `:` or `>`.

A protected line whose timer changes therefore yields `changed`. That costs one extra wake, never a hidden prompt. The `protected_lines` count is reported (§4).

### 3.4 Built-in `progress-v1` (exact text)

```json
{
  "schema_version": 1, "kind": "rex_presentation_view", "id": "progress-v1",
  "rules": [
    { "id": "braille-spinner", "position": "anywhere",   "pattern": "{one_of:⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏}" },
    { "id": "star-spinner",    "position": "line_start", "pattern": "{one_of:·✢✳✶✻✽∗} " },
    { "id": "elapsed-ms",      "position": "anywhere",   "pattern": "({digits}m {digits}s" },
    { "id": "elapsed-s",       "position": "anywhere",   "pattern": "({digits}s" },
    { "id": "tokens",          "position": "anywhere",   "pattern": "{number} tokens" }
  ]
}
```

These rules are compiled into the binary. `teerex compare --view progress-v1 --print-view` prints this exact JSON and exits 0, so a caller can audit what it opted into.

The glyphs and anchors are chosen and still need calibration (A-cal, §7). Changing them is a new built-in name (`progress-v2`), never an edit to `progress-v1`.

## 4. Output contract (additive to `schema_version=1`)

Every consumer adds the same `view` node, computed from one adjacent raw comparison:

```json
"view": {
  "kind": "rex_presentation_view_result",
  "interpretation": "none",
  "rules_id": "progress-v1",
  "rules_sha256": "<sha256 of the canonical rules JSON bytes>",
  "captured_text": "cosmetic_only",
  "full_text": "unknown",
  "non_text_evidence_changed": false,
  "spans": [
    { "rule": "elapsed-s", "line": 41, "byte_offset": 12,
      "before": "(12s", "after": "(13s" }
  ],
  "spans_truncated": false,
  "protected_lines": 2,
  "wake": false
}
```

**`captured_text` and `full_text`** are each one of `unchanged`, `cosmetic_only`, `changed` or `unknown`. Each is derived only from the matching raw flag:

| Raw flag | View verdict |
| --- | --- |
| `null` | `unknown` |
| `false` | `unchanged` |
| `true`, and the masked texts are equal | `cosmetic_only` |
| `true`, and the masked texts differ | `changed` |

So `full_text` is `unknown` whenever either capture is partial, exactly as `full_text_changed=null` is today.

**`spans`** is ordered by line, then byte offset. It lists only masked occurrences whose text differs, with exact before and after strings, escaped but not redacted, like all observation output. `line` is a 0-based line index in the capture and `byte_offset` is within that line. There are at most 64 spans. If more differ, `spans_truncated=true`, and the verdict is forced to `changed` (fail closed).

**Match counts.** If a rule matches a different number of times in the two captures, the masked texts differ, so the verdict is `changed`. A new spinner line is a structural change, not cosmetic.

**`non_text_evidence_changed`** is `true` if any process, last-exit, reported-directory or program-status field changed or changed availability. It is `null` (unknown, which wakes) if a whole method (process, reported directory or program status) is absent or unavailable in either sample, or if a delta is unknown for any other reason. An optional field that is absent in **both** samples with no availability change (for example `process.last_exit` on a pane whose program is still running) is not new non-text evidence and does not make the result `null`. Otherwise it is `false`. *(Contract fix decided at implementation by the teerex lead, 13 November 2026: without it, every active pane lacks `last_exit`, so `watch` would wake on every spinner tick and V-W1 could not pass.)*

**`wake`** is computed as:

```
non_text_evidence_changed != false
  OR captured_text ∈ {changed, unknown}
  OR full_text == changed
```

So unknown evidence wakes the caller, and only a fully declared, fully explained, cosmetic-only text change does not.

**Raw is kept alongside the view.** Each consumer keeps its existing raw comparison object and field lists unchanged. `view` is a sibling, and nothing existing is removed or renamed.

### 4.1 `compare`

```
teerex compare --before FILE --after FILE [--view NAME | --view-rules FILE]
teerex compare --view NAME --print-view
```

The output is the existing `observation_changes` object plus `view`.

### 4.2 `watch`

```
teerex watch … --baseline FILE (--timeout-ms N) [--interval-ms N] [--view NAME | --view-rules FILE]
```

- Each accepted comparison against the baseline computes `view`.
- A comparison with `wake=false` is counted and **does not satisfy** the wait. Polling continues with the same baseline.
- The final `observation_wait` keeps every existing field and adds:
  - `view`: from the last accepted comparison, or `null` if none was accepted;
  - `cosmetic_only_comparisons`: the count of accepted comparisons with `wake=false`;
  - `last_cosmetic_spans`: the spans of the most recent non-waking comparison, at most 64, or `null`;
  - `view_rules_sha256`.
- `changed_fields` and `availability_changed_fields` are still the raw lists. On a cosmetic-then-real wake they include `capture.captured_text`.
- Outcomes and exits are **unchanged**: 0 `change_observed`, 1 `observation_failed`, 2 usage, 124 `deadline_exceeded`, 130/143 cancel.
- A deadline with `cosmetic_only_comparisons > 0` is still `deadline_exceeded`, with `interpretation="none"`. The count is evidence that declared spans kept differing. It is **not** "busy", "working", "idle" or "not done". Help text and README say so in those words.
- `--view` combined with `--status-state` or `--no-deadline` is a usage error (exit 2, reason `view_not_applicable_to_status_wait`).

### 4.3 `filter`

```
teerex filter --sample FILE --sample FILE … [--view NAME | --view-rules FILE]
```

This adds the event `rex_evidence_filter_cosmetic_repeat`, emitted for an **intermediate** sample whose typed evidence differs from the reference payload only in `capture.content`, where every difference is a listed span. The reference payload is the last event that carried a full payload.

The event keeps `observation_id`, client times, `sample_index`, the **entire adjacent raw comparison**, the adjacent `view`, and `evidence_sample_index`, which points to the reference. It also carries `reconstruction`:

```json
"reconstruction": {
  "from_sample_index": 3,
  "spans": [ { "rule": "elapsed-s", "line": 41, "byte_offset": 12, "before": "(12s", "after": "(17s" } ]
}
```

Its spans are relative to the **reference** payload, not the adjacent sample. Applying them in order to the reference's `capture.content` yields this sample's `capture.content` byte for byte. Every other typed value is equal by construction.

The rest of the filter contract is unchanged:

- The final input always carries its full payload (`latest_checkpoint`).
- Baselines and non-cosmetic changes carry full payloads.
- An adjacent `full_text` or `captured_text` of `unknown` always carries the full payload, so unknowns are never reconstructed.

The summary adds `cosmetic_repeats`, `view_rules_sha256` and `payload_bytes_emitted`. The invariant becomes:

```
observation_payloads_emitted + observation_payloads_omitted = samples_read
observation_payloads_omitted = repeats + cosmetic_repeats
```

### 4.4 Refusals and exits

A rules problem is a usage error: exit **2**, with no stdout JSON and no Rex contact, because `watch` refuses before collection. Stderr gets one line:

```
teerex: view refused: <reason>
```

| Reason | When |
| --- | --- |
| `view_flags_exclusive` | Both `--view` and `--view-rules` were given. |
| `builtin_unknown` | `--view` names an unknown built-in. |
| `rules_unreadable` | The rules file is missing or is not a regular file. |
| `rules_too_large` | The rules file is over 16 KiB. |
| `rules_schema` | The JSON, kind, version or fields are invalid, or keys are duplicated. |
| `rule_id_duplicate` | Two rules share an `id`. |
| `rule_pattern_invalid` | A pattern breaks the §3.2 grammar. |
| `rule_unanchored` | A rule is unanchored. |
| `rule_token_limit` | A rule exceeds the token limit. |
| `view_not_applicable_to_status_wait` | `--view` was combined with `--status-state` or `--no-deadline`. |
| `print_view_requires_builtin` | `--print-view` was given without a built-in `--view`. |

Every other exit is exactly as each verb documents today.

## 5. C24 invariants the build must hold

1. **No new state words.** No output field or help line says stable, idle, done, complete, finished, waiting, ready, busy or working. `interpretation` stays `"none"`. A test greps the help text and README additions for these words. The only allowed hits are inside quoted existing status states and in negations.
2. **Masking never touches non-text evidence** (V5). A `last_exit` appearing, a `program_status` record changing, or the foreground process changing always yields `wake=true`, even when the text change is cosmetic.
3. **Asymmetric text events survive.** A new line that is not entirely covered by masked spans changes the masked text, so the verdict is `changed`.
4. **Hidden tails are unknown, never unchanged** (V9). A partial capture never yields `full_text` of `unchanged` or `cosmetic_only`.
5. **Quiet is not completion.** `deadline_exceeded` with zero comparisons, or with only cosmetic ones, is reported as such and nothing more.

## 6. Dependency: N07 latest-view capture (externally owned)

Today `observe` captures a **prefix** of screen-and-scrollback (`capture.portion="prefix"`), and `validateObservation` refuses any other portion. On a long agent pane, the spinner, the newest prompt and the newest error sit in the hidden tail. The view cannot see them, and correctly reports `full_text: unknown`.

N07 latest-view capture (roadmap 2026-11-13 table 1c, owner teerex lead, "**do**"; no filed issue) is what makes the view pay off on long agent panes. This spec is written portion-agnostic:

- `view.zig` reads only `capture.content`, `capture.complete` and the existing comparability flags.
- Whatever portion value N07 adds (for example `latest`) works here once `compare` accepts it.

Sequencing:

- **Do not block on N07.** The view ships now and is useful immediately on complete captures: short panes, `--max-bytes 65536`, run-visible fixture panes.
- **When N07 lands,** rerun the measurement in §7 with the new portion as arm A3. No view code changes.
- **Do not redesign N07 here.** Its portion name, tail semantics and comparability rules are the lead's. The only request is that N07 keep `captured_text_changed` and `full_text_changed` meaning what they mean today, for the new portion.

## 7. Acceptance (runnable once §8 exists; not executed)

### 7.1 Contract cases

These are added to `items/observe/test_observe.py` (offline `CompareTest` cases plus real-Rex `watch` cases) and `items/filter/test_filter.py`, using synthetic observation files and fixtures. Each case lists a **counterexample** that must not pass.

| ID | Case | Pass | Counterexample that must fail the build |
| --- | --- | --- | --- |
| V-A1 | Two complete captures differ only in `(12s` → `(13s` and `⠋` → `⠙`. `compare --view progress-v1` | `captured_text` and `full_text` are `cosmetic_only`; 2 exact spans; `wake=false`; raw `captured_text_changed=true` still present | The same captures, plus one new line `Continue? [y/n]`, must give `changed` and `wake=true`. |
| V-A2 | Timer change on a line containing `error` | `changed` (protected line), `protected_lines≥1` | The same change on an unprotected line gives `cosmetic_only`. This proves the protection itself, not general noise, makes the difference. |
| V-A3 | Text cosmetic-only, but `process.last_exit` becomes available (exit 3) | `non_text_evidence_changed=true`, `wake=true` | No `--view` path may hide this. A deliberately broken build that masks it is detected by this row. |
| V-A3b | Text cosmetic-only; `process.last_exit` absent in both samples; `process` method available in both | `non_text_evidence_changed=false`, `cosmetic_only`, `wake=false` | The same pair with the whole `process` method unavailable in the after sample must give `null` and `wake=true`. |
| V-A4 | Text cosmetic-only; root `program_status` goes `working` → `done` | `wake=true` | Same for `blocked:permission`. |
| V-A5 | Both captures partial (`--max-bytes 256`), identical prefix, tail differs (readiness [X1](readiness-acceptance.md#6-counterexamples-runnable-assertions) fixture) | `captured_text=unchanged`, `full_text=unknown` | Any output with `full_text` of `unchanged` or `cosmetic_only` fails. |
| V-A6 | Rule-count mismatch: a second spinner line appears | `changed` | Masking both spinners away into equality fails. |
| V-A7 | 65 differing timer spans | `spans_truncated=true`, `changed`, `wake=true` | `cosmetic_only` with truncated spans fails. |
| V-A8 | Refusals: unanchored `{one_of:\|/-\}`, `{digits}{digits}`, a newline in a pattern, 33 rules, a 16385-byte file, a FIFO, a duplicate key, both flags, `--view` with `--status-state` | Exit 2, exact reason, no stdout, no Rex contact (Rex removed from `PATH`) | A `[{one_of:\|/-\}]` anchored rule must be **accepted**. |
| V-W1 | Real-Rex `watch --view progress-v1 --timeout-ms 3000` on a fixture printing a ticking `⠋ Working (Ns` line every 100 ms in a complete capture | `deadline_exceeded`, exit 124, `cosmetic_only_comparisons≥5`, `interpretation="none"` | The same watch **without** `--view` returns `change_observed` within 600 ms (the false wake this build removes). |
| V-W2 | The same fixture, which at t=1.5 s prints `Error: boom` (E1), or `Proceed? [y/n]` (E2), or exits 3 (E3), or emits a status report (E4), or prints a plain new output line (E5) | `change_observed`, exit 0, within 1.5 s + 2 intervals + 500 ms for every E | Any E returning 124 is false suppression and fails the build. |
| V-W3 | The fixture's event is printed beyond a 256-byte prefix (hidden tail) | 124 with `view.full_text="unknown"` and `capture complete=false` in the last comparison | The output never says the tail is unchanged. |
| V-F1 | 128 samples of a ticking fixture (complete captures), `filter --view progress-v1` | 1 baseline, 126 `cosmetic_repeat`, 1 checkpoint; invariant counts hold. **Reconstruction:** a test-side applier rebuilds each sample's `capture.content` from the reference plus spans, byte-equal to the typed re-encoding of the input | Corrupting one span's `after` in the output must make the test's reconstruction check fail. That proves the check is real. |
| V-F2 | The same 128 samples, with sample 64 carrying a new error line | Sample 64 is a full `evidence_changed` payload | Emitting it as a `cosmetic_repeat` fails. |
| V-F3 | Mixed budgets or partial captures | Full payloads; no `cosmetic_repeat` from an `unknown` verdict | — |
| V-C24 | Grep the help text and README additions for the state words in §5.1 | No hits except the allowed ones | — |
| A-cal | Calibrate `progress-v1` against synthetic fixtures that reproduce Claude Code's and Codex's progress-line shapes. Shapes only, no transcripts. Optionally, one live read-only observation of a disposable agent pane on a private disposable server, with only the matched span strings kept | Each shape is `cosmetic_only` | A shape that yields `changed` is recorded and fixed as `progress-v2`. It is not a build failure, because it fails safe. |

### 7.2 Measurement (benefit vs the readiness baseline)

The script is `tools/acceptance/view_measure.py`, new. It reuses `tools/acceptance/baseline.py`'s disposable server (readiness [C7](readiness-acceptance.md#1-decisions-all-chosen): own socket, `--config /dev/null`, `--restore=false`, never `rex.service`), its exec timing, and its rusage helpers. It writes `report.json.measurements["view"][arm][event]` with the readiness field names `calls`, `rex_client_launches`, `wall_ms{cold,warm_median,warm_p95}`, `stdout_bytes`, `stderr_bytes`, `cpu_ms`, `maxrss_kib` and `excluded`, plus:

| Field | Definition |
| --- | --- |
| `false_wakes` | Returns before the event whose last comparison was cosmetic-only by the reference oracle. |
| `false_suppression` | Event E1–E5 occurred in captured text or non-text evidence, but the arm did not return within the V-W2 latency bound. **Must be 0 over all runs.** |
| `detection_latency_ms` | Event time from the fixture's monotonic marker file to the arm's return. |
| `hidden_tail_unknown` | Count of E events beyond the capture; each must report `full_text=unknown`. |
| `bytes_to_detect` | Total stdout bytes from start until the event is detected. |
| `filter_payload_ratio` | `payload_bytes_emitted / input_bytes` for F0 vs F1. |

The workload is the ticking fixture (100 ms ticks, 20 s, event at a randomized 5–15 s), run for E1–E5 and the hidden-tail variant, `--warm-runs 20` each.

The arms model what callers do today and what this build offers:

- **A0, poll-observe.** `observe --max-bytes 65536` every 250 ms, with a caller-side raw diff that stops on any change. This is the agent-read loop.
- **A1, raw watch loop.** `watch`, re-baselined after each `change_observed`, stopping when the caller's oracle sees the event.
- **A2, watch with view.** `watch --view progress-v1`, a single call.
- **A3, after N07.** A2 with the latest-view portion.
- **F0 and F1.** `filter` without and with `--view`, over the saved A0 samples.

`summary.md` reports A2 against A0 and A1 as ratios per field. **A benefit is claimed only for a field where A2 is better, `false_suppression=0` in every arm and event, and V-A1…V-F3 all passed.** If A2 is not better on bytes or calls, the view still ships opt-in, and `summary.md` says plainly that it was not better. Nothing is rounded up.

The **agent arm** (optional, same terms as readiness [§5.2](readiness-acceptance.md#52-phase-b-agent-arm-c32-round-trips-interruptions-and-misdirected-input), Josh's existing subscriptions, counts only) adds a task variant: "watch the fixture pane and report the first error". It is run `with-view` and `without-view` and compares `tool_round_trips`. It is optional because the deterministic arms already measure the mechanism.

### 7.3 Done when

- V-A1…V-C24 pass in CI on Linux x86_64 and Apple-silicon macOS (the readiness lanes).
- `view_measure.py` has run on hive against a disposable server from Josh's Rex binary, and its `report.json`/`summary.md` are committed under `tools/acceptance/results/view/`.
- `false_suppression=0`.
- The build is installed on hive and the M5 through the normal install path.
- The **live check** runs on each machine: `teerex compare --view progress-v1 --print-view` exits 0, and `teerex watch --view progress-v1 …` against a disposable fixture pane in a private server returns 124 with `cosmetic_only_comparisons>0`, then 0 after the fixture prints an error.

## 8. Files and owners

| Path | Change | Owner |
| --- | --- | --- |
| `items/observe/view.zig` (new) | Rules parser and validator, built-in `progress-v1`, matcher, `computeView(rules, before, after, raw_comparison)`, span emission and canonical-JSON SHA-256 | teerex lead |
| `items/observe/main.zig` | `compare` and `watch` flags, refusals, the `view` node, and the watch satisfaction rule (§4.2). No change to observation capture or `validateObservation` | teerex lead |
| `items/filter/main.zig` | `--view`, `--view-rules`, the `cosmetic_repeat` event, `reconstruction`, and summary fields | teerex lead |
| `items/observe/test_observe.py`, `items/filter/test_filter.py` | V-A*, V-W*, V-F*, V-C24 | teerex lead |
| `tools/acceptance/view_measure.py` (new), `tools/acceptance/fixtures/progress_fixture.py` (new) | §7.2 measurement; reuses readiness `baseline.py` helpers | teerex lead (after readiness §8 lands, or the helpers are inlined) |
| `items/observe/README.md`, `items/filter/README.md`, `docs/concierge/features.md` §3, §4 and §11 | View contract, C24 wording, N07 boundary. The filter README's "No cosmetic filter is enabled or available" becomes "No cosmetic view unless `--view`/`--view-rules` is given" | teerex lead |
| Combined and cartridge `--help` text | New flags and the deadline-is-not-idle sentence | teerex lead |
| agent-core `rex` skill | One line: "To wait on a pane with spinners or timers, use `teerex watch --view progress-v1 …` instead of polling `observe`. 124 is not idle; `cosmetic_only_comparisons` is evidence, not state." | agent-core owner (`block:01a1d372-e6db-7abe-8048-55203533aa2f`), after the install |
| rexconfig | None | — |

Sequencing:

1. Build `view.zig` and `compare` first, with offline tests only.
2. Then `watch`, then `filter`.
3. Then the measurement script, using readiness helpers when they exist.
4. Then docs, install and the agent-core line.

N07 runs in parallel and only feeds arm A3. Readiness's runner (Q02) later judges the filter and observe cartridges, including `--view`, as part of their whole advertised contract. This build does not change catalog readiness.

## 9. Not in scope

- **No universal perception engine,** no automatic normalization, and no learned or guessed cosmetic classes. Every masked span comes from a rule the caller named.
- **No activity, phase, stable, idle, completion or input-wait inference** (C24). C21's "last stable observation" and "known phase" are not built. Generic interpretation stays with H08 scoping ([delegation briefs](../teerex-delegation-briefs.md)).
- **No change to `observe` capture,** the `filter cache` or `maneuver-check`. Views for cache expectations and maneuver recognition are possible later additions, not part of this build.
- **No Rex reads saved.** The view reduces wakes, calls and returned bytes. A `watch` still collects every interval.

**Host-blocked:** none. The view is pure post-acquisition processing over the existing API10–13 reads. The only host-adjacent limit, prefix-only capture, belongs to N07, which the teerex lead has marked "do" with existing Rex `format` options. It is not an upstream Rex request.

## Sources

- Read at worktree head `1bea43f`:
  - [roadmap current plan](../../roadmap.md#current-phased-plan--13-november-2026)
  - [delegation briefs](../teerex-delegation-briefs.md) (H08 origins C03/C21–C24)
  - [inventory](../teerex-pdf-work-inventory.md) rows C03, C21, C22 and C24 (P2:p2, P2:p6) and group 7 (C21–C24)
  - [alpha5](../../alpha5.md) and the [alpha.5 release](../../releases/v0.1.0-alpha.5.md)
  - [cartridges](../../cartridges.md)
  - the [observe](../../../items/observe/README.md), [filter](../../../items/filter/README.md) and [maneuvers](../../../items/maneuvers/README.md) READMEs
  - `items/observe/main.zig`: the `Observation` and `Comparison` structs, `validateObservation`'s prefix-only portion check, and the watch satisfaction test
  - `items/filter/main.zig`: the adjacent-repeat logic
  - [readiness spec](readiness-acceptance.md) §1, §5 and §6
- The installed `teerex observe/compare/watch/filter --help` on hive.
- The overnight authority file and roadmap 2026-11-13 table 1c (N07, C03/C21/C22 rows) under `~/rivet/work/` (private, cited by name only).
