# H01 + U01/U02 — `teerex records`: one store for investigations, experiments, receipts, handoffs and Rex park/resume (implementation spec)

**Build `teerex records`: one combined-CLI leaf, one private store, one record envelope.** It covers four record kinds (investigation, experiment, shipping receipt, handoff) and Rex park/resume. Agents and Josh write records with small append commands, taking content from flags or from `--fields-file ABS|-`. `attach` pins teerex packets, `run-visible` output directories, board decision cards and commits as digest-checked evidence, copying their identity and caveat fields verbatim. `show` and `resume` put the reasoning first. `resume` adds a live, read-only target-availability table and performs zero writes. `navigate --focus yes` is the one separate effect, a single `surfaces focus`. `lint` rejects known false-success shapes. `export` drops private fields, keeps every caveat, and refuses when a secret pattern would leave. No Rex API beyond those already used is needed.

- **Status:** **chosen** under Josh's overnight standing authority (relayed by the coordinator, 2026-11-13). The coordinator's integration ruling makes `teerex records` the single store and envelope and folds the accepted [U01/U02 continuity spec](continuity-park-resume.md) into it. **This replaces the separate `teerex continuity` leaf and the `~/.local/state/teerex-continuity` store** ([mapping](#replacement-of-the-continuity-leaf-and-field-mapping)). This file is a spec only: no source edits, no Git writes.
- **Implementer:** teerex lead (`block:01a1d34f-9a09-7392-b8e8-17046462c623`), repository `jcbbge/teerex`. rexconfig owns the store directory and the `hosts.json` field. agent-core native owns the skill/rule text.
- **Base read:** `244d893`. Public main is now `4282f23`, which touches only `items/{agents,boards,send}`; no file this spec touches.
- **Normative sources:** this file for store, schema, commands, lint, export and files. The continuity spec remains normative for [target availability](continuity-park-resume.md#target-availability), [navigate refusals](continuity-park-resume.md#continuity-navigate-the-separate-effect), [Unicode](continuity-park-resume.md#unicode), [no content leakage](continuity-park-resume.md#no-content-leakage), [neighbouring panes untouched](continuity-park-resume.md#neighbouring-panes-are-untouched), [acceptance C1–C10](continuity-park-resume.md#acceptance-design-only-not-executed) and the [drafts upstream request](continuity-park-resume.md#host-blocked-parts). It applies with the command renames given [below](#continuity-acceptance-c1c10-under-records).
- **No acceptance case here has been executed.**

## Origins

A01 manual park (P1:p2, p5). A02 reasoning-first resume (P1:pp2, 5). A08/A09 failed run next to its successful comparator (P1:p4). A12 shipping receipt (P1:p5). B05 experiment record (P1:p7). B15 handoff (P1:pp10–11). B16 inbound human-run evidence (P1:p11). U01 = A01/A02; U02 = Rex-facing A08/A12 ([inventory](../teerex-pdf-work-inventory.md), [H01 brief](../teerex-delegation-briefs.md#h01--evidence-investigation-and-handoff-records), [roadmap](../../roadmap.md#first-proposed-feature-manual-rex-parkresume)).

## Chosen decisions

| Decision | Chosen | Why (rubric) |
| --- | --- | --- |
| Verb family and store | one leaf `teerex records`, one store; no `continuity` leaf | One place to look and one schema for agents and Josh (coordinator ruling) |
| Runtime | `items/records/records.py` (Python ≥3.9 stdlib) behind `items/records/main.zig`, a copy of the **recovery** `supervised_child` wrapper with env `TEEREX_RECORDS_EXECUTABLE` | park, resume and navigate make bounded Rex calls, so they need the 15-min outer bound and the 124/130/143 behaviour; offline operations share the same path |
| Format | JSON, `"schema": "teerex.records/1"` | Python stdlib, agent-parseable; `show --format text` and `export --format md` are for Josh |
| Store path | explicit `--store ABS`; estate path `~/.local/state/teerex-records` on hive and M5; `hosts.json` field `records_store` | explicit like boards; named-host routing injects it |
| Content input | flags **and** `--fields-file ABS\|-` on `new`, `park`, `add`, `attach`, `set`, `close` | flags for quick agent use; fields-file keeps private questions and notes out of argv and `ps` |
| Next action | structured `{actor, step, stop_when}` | mechanically checkable; rules out "keep digging" |
| Availability | stored `availability_at_attach`, computed `availability_now`; never a stored "current" value | a stored value is never mistaken for current |
| Packaging | combined-CLI composition, not a cartridge | same as the other operating-layer commands ([cartridges](../../cartridges.md)) |

## Files and owners

| Path | Owner | Change |
| --- | --- | --- |
| `items/records/records.py` | teerex lead | new: whole leaf. Reuse the 0700/0600/`O_NOFOLLOW`/single-link helpers from `items/recovery/recovery.py` and `items/boards/boards.py` |
| `items/records/main.zig` | teerex lead | new: copy of the recovery wrapper, `pub fn run(allocator, args) !u8` |
| `items/records/test_records.py` | teerex lead | new: R1–R24 offline cases, plus C1–C10 live cases gated on `REX_BIN` |
| `items/records/fixtures/*.json` | teerex lead | new: synthetic packets per supported kind, plus malformed ones |
| `items/records/README.md` | teerex lead | new: Who/What/When/Where/Why/How, bounds, exit table |
| `build.zig` | teerex lead | module `rex_records` → `items/records/main.zig`, `addImport("supervised_child", child)`, `exe.root_module.addImport("rex_records", records)` |
| `src/main.zig` | teerex lead | `if (eql(command,"records")) std.process.exit(try @import("rex_records").run(allocator, rest));`; usage line `  records init\|new\|park\|add\|attach\|set\|close\|show\|resume\|navigate\|list\|lint\|export\|forget  Private records, park/resume and evidence`; add `records` to the Python line and to the guide list |
| `src/targets.py`, `src/test_targets.py` | teerex lead | [named-host routing](#named-host-routing) below |
| `.github/workflows/ci.yml` | teerex lead, coordinated with the CI owner | add `python3 items/records/test_records.py -v` to the Linux and Mac API13 lanes |
| `docs/concierge/features.md`, `items/README.md`, `docs/alpha5.md` command list | teerex lead | new "18. `records`" section; one line: composed command, not a cartridge |
| `~/rexconfig` `hosts.json` (hive, m5) and `./install` | rexconfig | add `"records_store": "<home>/.local/state/teerex-records"`; create the directory 0700 |
| agent-core `primitives/skills/rex/SKILL.md`, `primitives/rules/report-contract/RULE.md` | agent-core native | [text below](#agent-core-changes-owner-agent-core-native) |

## Store

- `records init --store ABS` creates the directory at 0700 plus `lock` (0600). It refuses an existing path with the wrong owner or mode, or a symlink. Every other operation requires that exact state (`store_hazard`).
- Layout:

```text
<store>/lock                              0600, flock
<store>/records/<id>/record.json          0600, single link
<store>/records/<id>/evidence/<eN>.json   0600, verbatim copied teerex packet, never overwritten
```

- **Writes:** nonblocking exclusive `flock` (busy → `store_busy`, no retry). Write `record.json.tmp-<16hex>` with `O_CREAT|O_EXCL|O_NOFOLLOW` at 0600, fsync, rename, then fsync the directory. Then **verified readback**: re-open, re-parse and compare the digest; a mismatch → `outcome: uncertain`, exit 1, file left in place. `generation` increments on every write. `--expect-generation N` is accepted on every write and **required** on `set` and `forget`; a mismatch → `generation_mismatch`.
- **Reads:** shared nonblocking `flock` (busy → `store_busy`). Files are opened `O_NOFOLLOW|O_NONBLOCK` and checked by `fstat` (regular file, owner, 0600, `st_nlink==1`).
- **Bounds:** 4096 records per store (`store_full`); `record.json` ≤ 1 MiB; 256 evidence refs, 64 of them copied packets; each copied packet ≤ 1 MiB; 128 claims, 128 checks, 128 omissions, 64 cleanup items, 64 `history[]` entries; text fields 1–4096 UTF-8 bytes (`notes` ≤ 16 KiB); `--fields-file` ≤ 64 KiB. A cap is a refusal, never a truncation.
- **Ids:** record `[a-z0-9][a-z0-9._-]{0,63}`; if omitted, `<kind>-<UTC YYYYMMDDTHHMMSSZ>-<8hex>` (`park-…` for park). An existing id → `record_exists`. Element ids `e1…`, `c1…`, `k1…`, `o1…`, `u1…` are assigned by the tool and never reused.
- Only `forget` deletes. There are no timers.

## Record schema `teerex.records/1`

Key order is fixed and is the `show`/`resume` render order.

```json
{
  "schema": "teerex.records/1",
  "kind": "investigation | experiment | receipt | handoff",
  "id": "inv-cache-stale",
  "generation": 3,
  "state": "open | parked | concluded | abandoned | superseded_by:<id>",
  "written_at": "2026-11-13T10:05:00Z", "updated_at": "…", "writer": "agent-a", "supersedes": null,

  "question": "…",
  "hypothesis": {"text": "…", "basis": "inferred | chosen"},
  "discriminating_experiment": "…",
  "next_action": {"actor": "agent-a", "step": "make test-cache CASE=t DELAY_MS=50", "stop_when": "20 iterations; attach the run-visible receipt"},
  "claims":   [{"id": "k1", "text": "…", "basis": "observed | inferred | supplied | chosen", "evidence": ["e1"], "supplied_by": null, "scope": "…"}],
  "checks":   [{"id": "c1", "command": "…", "ran": "yes | no | unknown", "process_exit": "0 | <int> | signal:<int> | unknown", "assertion": "passed | failed | not_evaluated | unknown", "establishes": "…", "does_not_establish": "…", "evidence": ["e2"]}],
  "omissions": [{"id": "o1", "what": "…", "reason": "…"}],
  "uncertainty": {"text": "…", "confidence": "low | medium | high"},
  "notes": "…",

  "subject": {"repo": "/abs", "commit": "<40hex>", "dirty": "true | false | unknown", "untracked": [], "untracked_truncated": false, "artifact": null, "digest": null, "basis": "observed | supplied"},
  "target": null,
  "target_at_park": null,

  "evidence": [ "see evidence entry" ],
  "cleanup": {"status": "none_needed | done | partial | not_started | unknown", "items": [{"id": "u1", "what": "…", "where": "…", "owner": "…"}]},
  "kind_fields": {},
  "history": [{"generation": 2, "field": "next_action", "previous": {"…": "…"}, "replaced_at": "…", "by": "agent-b"}],
  "private": ["notes", "target", "target_at_park", "subject.repo", "subject.untracked", "history[].previous"]
}
```

- `target` and `target_at_park` are filled by `park` only, in the continuity shapes ([record JSON there](continuity-park-resume.md#record-json-schema-teerexcontinuity1)). They are `null` on other records.
- `kind_fields` by kind: experiment `{change_made, pair_with, cost?}`; receipt `{shipped_identity{repo,commit,tag?,artifact_digest?}, human_caveat?{text,basis:"supplied",supplied_by}}`; handoff `{direction: outbound|inbound, from, to, changes[evidence ids], risks[], undo, reply_to?}`; investigation `{}`.
- Missing optional fields are stored as explicit `null`; `show`/`resume` list them under `missing` and never render them as `""`.
- Replacing `question`, `next_action`, `hypothesis` or `uncertainty` (through `set` or `attach --fields-file`) appends the previous value to `history[]`.
- `basis` meanings: `observed` = a referenced artifact shows it; `supplied` = someone said it; `inferred` = reasoned; `chosen` = decided. `writer`, `by`, `supplied_by` and times are claims, not authentication. There is **no record-level `success` field**.

### Evidence entry

```json
{"id": "e2", "type": "teerex_run_visible", "label": "failing check",
 "locator": "/abs/runs/b/receipt.json", "digest": "sha256:…", "bytes": 18234,
 "recorded_at": "…", "attached_by": "agent-a", "availability_at_attach": "present",
 "moved_from": [], "copy": "evidence/e2.json", "supplied_by": null, "private": true,
 "teerex": {"packet_kind": "run_visible_result", "schema_version": 1,
   "target": {"host": "hive", "server": "unix:///…", "session_id": "session:…", "block_id": "block:…"},
   "source_version": "…", "observation_id": null, "outcome": "exit_reported",
   "exit": {"code": 1, "signal": null}, "reported_success": false,
   "output_complete": {"stdout": false, "stderr": true},
   "storage_dir": "/abs/dir", "storage_dir_retained": true,
   "carried_flags": {"retry_safe": false, "task_completion": "not_assessed", "painted_visibility": null,
                     "all_descendants_verified_gone": false, "atomic_snapshot": null, "freshness": null, "interpretation": null}}}
```

`teerex` fields are copied verbatim from the packet. Absent fields stay `null` and nothing is defaulted. `reported_success` is the packet's own `success`.

### Evidence inputs (`attach`, and `new`/`park` accept the same flags)

The types, read rules and copy rules are those of the [continuity evidence table](continuity-park-resume.md#evidence-entry-u02-h01-evidence-ref-plus-h01-teerex-block), extended:

| Flag | `type` | Read / copied |
| --- | --- | --- |
| `--evidence ABS\|-` with `kind` `run_visible_result`/`run_result`/`observation_changes`/`observation_wait`, or `observation_id`+`capture` | `teerex_run_visible`, `teerex_run`, `teerex_compare`, `teerex_watch`, `teerex_observation` | ≤1 MiB, parsed; copied to `evidence/eN.json`. `-` reads stdin with a 10 s deadline (124). A malformed teerex-looking packet or a wrong `schema_version` → `unsupported_packet` |
| `--evidence ABS` (any other regular file) | `file` | sha256 streamed, ≤64 MiB; content never parsed, copied or printed |
| `--evidence-dir ABS` (a `run-visible --output-dir`) | `teerex_output_dir` | names and sha256 of `stdout.full`/`stderr.full`; other files (argv/env/stdin) **by name only**, flagged `private_contents_not_read`; not copied |
| `--card BOARD_STORE_ABS --card-id ID --seat-host H --seat-socket S --seat-session SS --seat-block B` | `board_card` | `{card_id, title, open\|resolved, answer_present}` only; never the body or answer text; boards schema unchanged |
| `--commit REPO_ABS SHA` | `commit` | `basis: supplied`; no Git run (the observed alternative is `new --git-repo`) |
| `--ref TYPE LOCATOR` with TYPE `url\|human_report\|screenshot` | as given | nothing read; `availability_at_attach: not_checked`; `--supplied-by` required for `human_report` |

- All paths must be absolute and owned by the UID, with no final symlink; FIFOs and devices are refused (`evidence_hazard:<flag index>`).
- Evidence is private by default; `--exportable` (positional with the evidence flags) marks one exportable.
- `--label TEXT` pairs positionally with the evidence flags (1–128 bytes).
- An entry with the same `type` and digest as an existing one → `duplicate_evidence:<id>`.
- Check from a packet: `attach --evidence F --check-command C --assertion A --establishes T --does-not-establish T` also appends a check whose `ran: yes` and `process_exit` come from the packet's exit fields (null → `unknown`). `--assertion` is then required and never inferred; omitting it is exit 2.

## Commands

Every operation takes `--store ABS` and prints exactly one JSON object on stdout. The exceptions are `show`/`resume`/`list --format text` and `export --format md`. Write receipts echo ids, generation, byte counts and the record digest, **never content**:

```json
{"schema_version": 1, "kind": "records_result", "operation": "attach", "outcome": "written", "id": "inv-cache-stale", "generation": 4, "assigned": ["e3", "c2"], "record_digest": "sha256:…", "warnings": []}
```

| Command | Effect |
| --- | --- |
| `init --store ABS` | create the store |
| `new --kind K [--id ID] --writer NAME [--supersedes OLD] [content flags] [--fields-file ABS\|-] [--git-repo ABS] [--subject-artifact ABS] [evidence flags]` | create a record (`state: open`). `--git-repo` runs read-only `git -C ABS rev-parse HEAD`, `status --porcelain=v1 -z` and `ls-files --others --exclude-standard -z` (names ≤256), with `basis: observed`; a failure → `git_failed`. `--supersedes` sets the old record to `superseded_by:<new>` in the same locked write |
| `park` | see [Rex park/resume](#rex-parkresume) |
| `add claim\|check\|omission\|cleanup --id ID --by NAME [flags] [--fields-file ABS\|-]` | append one element (flags below); with `--fields-file`, append the arrays given (`claims`, `checks`, `omissions`, `cleanup.items`) |
| `attach --id ID --by NAME [evidence flags…] [--label…] [check flags] [--fields-file ABS\|-] [--expect-generation N]` | append evidence. Its `--fields-file` may carry only `claims`, `omissions` (appended) and `uncertainty`, `cleanup`, `next_action` (replaced, with history) |
| `set --id ID --expect-generation G [FIELD=JSON…] [--fields-file ABS\|-]` | replace fields: `question`, `next_action`, `hypothesis`, `discriminating_experiment`, `uncertainty`, `cleanup.status`, `kind_fields.<name>`, `private`, `notes`, and id-addressed element fields (`claims.k2.basis`, `evidence.e9.locator`; the old locator goes to `moved_from`). `state` is **not** settable here |
| `close --id ID --state concluded\|abandoned --by NAME [--fields-file ABS\|-] [--expect-generation N]` | final `claims`/`uncertainty`/`cleanup`, then the state; runs lint first (violations → exit 3, nothing written); `next_action` may be null after close |
| `show --id ID [--format json\|text] [--evidence-check yes\|no]` | read-only render: header, **question, next action (actor · step · stop when)**, hypothesis/experiment, claims grouped by basis, checks (`ran / exit / assertion`, establishes, does-not), omissions, cleanup, uncertainty, `missing`, then evidence with `availability_now` computed in memory. No Rex call |
| `resume`, `navigate` | see [Rex park/resume](#rex-parkresume) |
| `list [--state open\|parked\|all] [--kind K] [--format json\|text]` | `[{id, kind, state, written_at, updated_at, writer, question, next_action.step, target{host,session_id,block_id}\|null, evidence_count, generation}]`: open/parked first, then newest. Read-only |
| `lint --id ID \| --all` | rules below; exit 0 clean, 3 violations, `violations:[{rule,path,message}]` |
| `export --id ID [--format json\|md] [--out NEW_ABS] [--include FIELD…]` | [export rules](#export-rules); stdout by default, or a new 0600 file |
| `forget --id ID --expect-generation G --reason T` | delete `records/<id>/` |

**Content flags** on `new`/`park`: `--question T`, `--next-actor A --next-step S --next-stop-when W`, `--hypothesis T --hypothesis-basis inferred|chosen`, `--discriminating-experiment T`, `--uncertainty T --confidence L`. `add claim`: `--text T --basis B [--evidence e1,e2] [--supplied-by N] [--scope S]`. `add check`: `--command C --ran R --process-exit X --assertion A --establishes T --does-not-establish T [--evidence eN]` (all required). `add omission`: `--what T --reason T`. `add cleanup`: `--what T --where T --owner N`.

**`--fields-file ABS|-`** is a JSON object whose keys match the schema field names above (`question`, `next_action{actor,step,stop_when}`, `hypothesis{text,basis}`, `claims[]`, `checks[]`, `omissions[]`, `uncertainty{text,confidence}`, `notes`, `subject`, `cleanup`, `kind_fields`).
- Size ≤64 KiB; `-` reads stdin with a 10 s deadline.
- Unknown keys → `unknown_field:<name>`.
- A field given both by flag and in the file → exit 2 (no silent precedence).
- `next_action` as a plain string → `invalid_field:next_action` (the object shape is required).
- `notes` can be set **only** through `--fields-file` or `set` with a fields-file, because notes are private. Questions can be passed either way, and the README recommends the fields-file for private ones.

**Validation on write:** `observed` claims need ≥1 existing evidence id (`observed_claim_without_evidence`); `supplied` claims need `supplied_by` (`supplied_without_source`); UTF-8, controls and bidi follow the [continuity Unicode rules](continuity-park-resume.md#unicode) (`invalid_utf8:<f>`, `control_character:<f>`). Drafts may be incomplete; completeness is checked by `lint`, `close`, `park` and `export`.

### Exit codes

**0** done (writes: written and read back; reads: printed; `resume` exits 0 whatever the target status). **1** refusal or failure (`{"outcome":"refused|uncertain|failed","failure_reason":…}` on stdout for routed callers, codes only on stderr). **2** usage. **3** rule refusal: lint violations (`lint`, `close`, `park`, `export`) or `navigate` target not available (`refused_target`). **124/130/143** deadline/INT/TERM through the wrapper.

`failure_reason` codes: `store_busy`, `store_hazard`, `store_full`, `staging_present`, `record_exists`, `record_not_found`, `record_closed`, `record_oversize`, `record_corrupt`, `generation_mismatch`, `cap_exceeded:<field>`, `fields_oversize`, `unknown_field:<name>`, `invalid_field:<name>`, `invalid_utf8:<field>`, `control_character:<field>`, `observed_claim_without_evidence`, `supplied_without_source`, `evidence_hazard:<i>`, `evidence_oversize:<i>`, `evidence_limit`, `duplicate_evidence:<id>`, `unsupported_packet`, `git_failed`, `target_not_available:<status>`, `named_host_missing_records_store`, `private_field_export_refused:<field>`, `secret_pattern:<path>`, `output_exists`, `readback_mismatch`, `internal_error` (exception class name only).

## Rex park/resume

These are the U01 operations on the same store, records and evidence as everything above.

### `records park`

```sh
printf '%s' "$FIELDS_JSON" | teerex records park --store "$STORE" --host hive \
  --socket /run/user/1000/rex/server.sock --session "$REX_SESSION" --block "$REX_BLOCK" \
  --writer agent-a --fields-file - [--id ID] [--supersedes OLD] [--git-repo ABS] \
  [evidence flags…] [--observe yes|no] [--observe-max-bytes 256..65536] \
  [--target-check yes|no] [--allow-unavailable-target yes] [--timeout-ms 100..60000]
```

- Equals `new --kind investigation` with `state: parked`, plus these steps:
  1. Records `target {host, server, session_id, block_id}` from the explicit flags. There is no `REX_*` fallback; agents pass their own values.
  2. Runs the [target availability check](continuity-park-resume.md#target-availability) (default `--target-check yes`) and stores the result as `target_at_park`. A status other than `available` → exit 1 `target_not_available:<status>`, unless `--allow-unavailable-target yes` is given, which stores the actual status.
  3. With `--observe yes` (default no), runs one `teerex observe` on the exact target with `--observe-max-bytes` (default 4096) and attaches the packet as `teerex_observation`, copied.
- `question` and a complete `next_action` are required (lint `L1` runs before writing; exit 3).
- The receipt adds `target_status` and `evidence_ids` and does not echo content.

### `records resume` (inspection only)

```sh
teerex records resume --store "$STORE" --id ID --host hive \
  [--target-check yes|no] [--evidence-check yes|no] [--format json|text] [--timeout-ms N]
```

- Output is the [continuity resume JSON](continuity-park-resume.md#continuity-resume-inspection-only) with `kind: "records_resume"`, in three sections in fixed order:
  1. `reasoning`: question, hypothesis, next action, claims, checks, omissions, uncertainty, notes, `missing`.
  2. `evidence`: historical, each with `attached_by`/`recorded_at`, re-checked now as `availability_now`/`copy_availability_now`.
  3. `target`: `recorded`, `at_park` and `now`, the live availability table, whose statuses are exactly those of [target availability](continuity-park-resume.md#target-availability).
- Also present: `navigate {possible, argv}`, `is_fresh_snapshot: false`, `authority_granted: "none"`, `draft_restored: false`, `harness_resumed: false`, **`writes_performed: 0`**.
- `--format text` renders the headers `REASONING`, `EVIDENCE (historical, re-checked now)` and `TARGET (now)` for `leaf`.
- Shared lock only; no field updated; no `last_resumed_at`.
- Works on any record kind. A record with `target: null` reports `target.now.status: "no_target_recorded"` and `navigate.possible: false`.
- Rex calls are limited to the identity read and `surfaces inspect` on the recorded target ([neighbours untouched](continuity-park-resume.md#neighbouring-panes-are-untouched)).

### `records navigate --focus yes` (the separate effect)

```sh
teerex records navigate --store "$STORE" --id ID --host hive --focus yes [--timeout-ms N]
```

- Behaves exactly as [continuity navigate](continuity-park-resume.md#continuity-navigate-the-separate-effect):
  - `--focus yes` is required;
  - it re-checks availability, and any status other than `available` (including `available_unverified_instance`, `no_target_recorded` and `not_checked`) → exit 3 `refused_target`;
  - otherwise it makes one `teerex surfaces focus --socket --session --pane` on the recorded block, with the receipt nested under `focus`; success is `focused_and_verified`.
- It never opens, relaunches, moves, resizes, renames, closes, pastes or sends, and writes nothing to the record.

### Park → card → resume workflow (U02)

1. A failed `run-visible` packet goes into a parked record with `park --evidence F` or `attach --evidence F --check-command … --assertion failed`.
2. `boards ask` a card whose `context` contains the plain line `records: teerex records resume --id ID`.
3. `attach --card …` records the card reference.
4. Whoever resumes sees the reasoning, the failure receipt with its caveats, the card's open/resolved state, and whether the pane is still there.

## Named-host routing

`src/targets.py` changes:

- `PATH_FIELDS` gains `records_store`.
- `SELECTORS` gains `("records", op): ("socket", "host", "records_store")` for `park`, `resume` and `navigate`, and `("records", op): ("records_store",)` for every other operation.
- In `command_argv`, the field `records_store` is emitted as `--store <value>`. It is skipped when `--store` is already present, generalizing the existing `field == "store"` check to "any field whose flag is `--store`".
- A host without `records_store` → `named_host_missing_records_store` (the existing missing-field path).
- `src/test_targets.py` covers injection, the explicit-store override and the missing-field refusal.

## Lint rules

| Rule | Violation when |
| --- | --- |
| `L1-next-action` | state `open`/`parked` and `next_action` null or any of `actor`/`step`/`stop_when` blank, or `step` (trimmed, lowercased) is one of `continue`, `keep digging`, `keep investigating`, `continue investigating`, `tbd`, `todo` |
| `L2-observed-evidence` | an `observed` claim's evidence ids all have `availability_now` `missing`/`deleted`/`digest_differs`/`hazard_refused` (relabel `supplied` or re-attach) |
| `L3-check-consistency` | `assertion` `passed`/`failed` while `ran` ≠ `yes`; `ran: no` with no omission naming the check id |
| `L4-scope-words` | an `observed` claim containing `production`, `prod`, `deployed`, `live`, `released` or `customer` (case-insensitive) where no linked check's `establishes` contains that word (heuristic, deliberately strict) |
| `L5-packet-integrity` | a copied packet's sha256 ≠ the stored digest, or `teerex` block fields differ from a re-derivation |
| `L6-kind-required` | experiment/receipt with 0 checks; receipt without `shipped_identity`; handoff without `direction`/`from`/`to`/`undo`; park record without `target`/`target_at_park` |
| `L7-cleanup-retained` | `cleanup.status: done` while an attached packet has `storage_dir_retained: true` and that directory still exists |
| `L8-handoff-authority` | an inbound handoff with a `supplied` claim lacking evidence while `next_action` is null |

## Export rules

1. **Always exported, never private** (adding one to `private[]` → `invalid_field:private`): `kind`, `id`, `state`, `question`, `next_action`, `hypothesis`; claims' `text`/`basis`/`scope`; checks except evidence ids; `omissions`; `cleanup.status` and item `what`; `uncertainty`; each evidence `id`/`type`/`label`/`availability_at_attach`/`private`; each `teerex.exit`/`outcome`/`output_complete`/`reported_success`/`carried_flags`; `kind_fields` except `shipped_identity.repo`; `target_at_park.status`.
2. **Dropped:** everything in `private[]`. For private evidence: `locator`, `digest`, `copy`, `moved_from`, `supplied_by`, `teerex.target`, `teerex.storage_dir`, card seat tuples. Cleanup item `where`/`owner`. A dropped evidence ref becomes `{id, type, label, availability_at_attach, private: true}`.
3. `--include FIELD` naming a private field → exit 1 `private_field_export_refused:<field>`; there is no override.
4. **Secret scan** of every exported string, union of both specs:
   - patterns: `-----BEGIN [A-Z ]*PRIVATE KEY-----`; `(?i)\b(api[_-]?key|secret|token|passwd|password|bearer)\b\s*[:=]\s*\S{8,}`; `\bgh[pousr]_[A-Za-z0-9]{20,}`; `\bgithub_pat_[A-Za-z0-9_]{20,}`; `\bsk-[A-Za-z0-9_-]{20,}`; `\bxox[abpr]-[A-Za-z0-9-]{10,}`; `\bAKIA[0-9A-Z]{16}\b`; `eyJ[A-Za-z0-9_-]{10,}\.`; a run of ≥40 characters of `[A-Za-z0-9+/=_-]`.
   - The run rule exempts only values that match `^(sha256:)?[0-9a-f]{40,64}$` in the fields `digest`, `commit` and `artifact_digest`.
   - A hit → exit 1 `secret_pattern:<path>`; the value is printed nowhere and nothing is written; no silent redaction. The output carries `"secret_scan": "heuristic_floor_only"`.
5. Lint runs first; violations → exit 3, no output.
6. `md` renders the `show` order under the header `Exported <utc> from teerex.records/1; private fields omitted: <list>`.

## Replacement of the continuity leaf and field mapping

`teerex continuity`, `items/continuity/`, the `rex_continuity` module, the `continuity_store` host field and `~/.local/state/teerex-continuity` are **not built**. Their behaviour lives in `teerex records`. Nothing has been built under continuity yet, so there is no migration of data, only of names.

| Continuity spec | `teerex records` | Note |
| --- | --- | --- |
| `teerex continuity park\|resume\|navigate\|attach\|export\|list\|close` | `teerex records park\|resume\|navigate\|attach\|export\|list\|close` | same semantics, plus the extra records verbs |
| `--record ID` | `--id ID` | — |
| `--by` / `--writer` | same | — |
| `"schema": "teerex.continuity/1"`, `record_version` | `"schema": "teerex.records/1"` | `record_version` dropped; the schema string carries the version |
| store `~/.local/state/teerex-continuity`, host field `continuity_store` | `~/.local/state/teerex-records`, `records_store` | one store |
| `records/<id>/record.json`, `evidence/eN.json` | identical | adopted as-is |
| `generation` | `generation` | identical; `--expect-generation` now on every write, required on `set`/`forget` |
| `history[]` = previous `next_action` only, `{generation, next_action, replaced_at}`, ≤32 | `history[]` = `{generation, field, previous, replaced_at, by}` for `question`/`next_action`/`hypothesis`/`uncertainty`, ≤64 | generalized; `history[].previous` private by default |
| `availability_at_attach` (stored) / `availability_now` (computed) | identical; also `copy_availability_now` | the first records draft's stored `availability` + `recheck` verb is **dropped** in favour of this |
| `next_action` string + vague-word floor | `next_action {actor, step, stop_when}` + the same vague-word list on `step` | a string → `invalid_field:next_action` |
| states without `open` | `open` exists for non-park records; park writes `parked` | — |
| evidence types `teerex_run_visible`… `teerex_output_dir`, `board_card`, `commit` | identical, plus `file`, `url`, `human_report`, `screenshot` | — |
| `carried_flags` list of `"name:value"` strings | object `{name: value}`, absent → null | machine-friendlier; same source fields |
| `teerex.storage_dir_retained`, `reported_success` | identical, plus `teerex.storage_dir` | `storage_dir` needed by lint L7 |
| exit 3 = navigate `refused_target` | exit 3 = rule refusal: `refused_target` **or** lint violations | per operation there is no ambiguity |
| bounds 1024 records / 256 KiB record / 64 evidence | 4096 / 1 MiB / 256 refs (64 copied packets) | C5's `store_full` case becomes the 4097th record |
| export to stdout only | stdout default, optional `--out NEW_ABS` | — |
| `failure_reason` `export_refused_secret_shaped:<p>` | `secret_pattern:<p>` | — |
| `fields_oversize:fields_file` | `fields_oversize` | — |
| reasoning **only** through `--fields-file` | flags **or** `--fields-file`; `notes` fields-file only | per coordinator ruling; README recommends the fields-file for private questions |

### Continuity acceptance C1–C10 under records

Run [C1–C10](continuity-park-resume.md#acceptance-design-only-not-executed) as written, with these substitutions:

- `continuity` → `records`, `--record` → `--id`;
- C5's 1025th park → 4097th;
- C6's `export_refused_secret_shaped:uncertainty` → `secret_pattern:uncertainty`;
- C7's `carried_flags` include `task_completion:not_assessed` → `carried_flags.task_completion == "not_assessed"`.

Include the [leak test](continuity-park-resume.md#no-content-leakage) canaries in every records operation, including the offline ones.

## Offline acceptance R1–R24 (`items/records/test_records.py`; not yet executed)

Each case uses a fresh umask-077 store, fixture packets and a `git init` fixture repo, and needs no Rex.

| # | Case | Expected |
| --- | --- | --- |
| R1 | second-reader resume: `new` investigation with all content flags and `--git-repo`; `show --format text` | question and `actor · step · stop when` are the first content lines; commit = fixture HEAD; dirty/untracked match |
| R2 | exit 0 vs failed assertion: the same exit-0 fixture attached with `--assertion failed` in record A and `passed` in record B | both `process_exit: "0"`, assertions differ; no top-level `success`; `teerex.reported_success` as in the packet |
| R3 | no inferred assertion: `attach --check-command` without `--assertion` | exit 2; generation unchanged |
| R4 | missing output: delete an attached file's locator; `show`; `lint` | `availability_now: missing`; lint 3 `L2`; relabel through `set claims.k1.basis` (+ `supplied_by`) clears it |
| R5 | moved reference: `set evidence.e2.locator="/new"` | old locator in `moved_from`; `availability_now` from the new path |
| R6 | digest mismatch: modify a referenced file | `availability_now: digest_differs`; stored digest unchanged |
| R7 | human-supplied conclusion: inbound handoff, supplied "ship it", no evidence, `next_action` null | lint 3 `L8`; adding a next action clears it |
| R8 | partial cleanup | `show` lists where/owner; export keeps `status: partial` and `what`, drops where/owner |
| R9 | retained storage vs done (run-visible fixture, `storage_dir_retained: true`, dir exists) | `close` with `cleanup.status: done` → exit 3 `L7` |
| R10 | export drops planted secret (`token=SYNTHETICTOKEN0000000000` in `notes`) | exit 0; no `SYNTHETICTOKEN`, no private locators/targets; caveats, every `basis` and `availability_at_attach` present |
| R11 | export refuses secret in a caveat (token in `uncertainty`) | exit 1 `secret_pattern:uncertainty.text`; no output; token absent from stderr |
| R12 | caveat cannot be private: `set private=["uncertainty"]` | exit 1 `invalid_field:private` |
| R13 | counterexample, green exit as shipped: receipt with an observed "fix verified in production" claim linked only to a unit check | lint 3 `L4`; `close` refused with 3 |
| R14 | counterexample, vague next action: `--next-step "keep digging"` | `new` succeeds as a draft; lint 3 `L1`; `park` with it → 3 |
| R15 | packet integrity: edit one byte of `evidence/eN.json` | lint 3 `L5` |
| R16 | unsupported packet: `{"kind":"x","schema_version":1,"observation_id":…}` malformed, invalid JSON, >1 MiB | each exit 1 (`unsupported_packet` / `unsupported_packet` / `evidence_oversize:0`); no ref added |
| R17 | experiment pair with `pair_with` both ways; `list` | both listed; `show` names the pair |
| R18 | concurrency: a held lock; two sequential `add claim` | `store_busy`; then `k1`, `k2`, consecutive generations |
| R19 | stale generation on `set` | exit 1 `generation_mismatch` |
| R20 | store hazards: mode 0755; symlinked `record.json`; leftover tmp file blocking | `store_hazard` ×2; `staging_present` |
| R21 | Unicode and caps: a 4096-byte multibyte question round-trips byte-identically; 4097 bytes → `cap_exceeded:question`; C0 → `control_character:question` | as stated |
| R22 | fields-file: `new --fields-file -` carrying question/notes; the same with an unknown key; the same field by flag and file; `next_action` as a string | ok with no question/notes text in argv or receipt; `unknown_field:<k>`; exit 2; `invalid_field:next_action` |
| R23 | evidence types: `--evidence-dir` of a run-visible output dir; `--card` against a fixture boards store; `--commit` | names/sha256 only (argv/env/stdin by name, `private_contents_not_read`); card `{card_id,title,open,answer_present:false}`, then `resolved` after resolution, no answer text; commit `basis: supplied`, no git invocation (wrapper `git` logs zero calls) |
| R24 | named host: `teerex --config C --host H records list` with a fixture config holding `records_store`; again with explicit `--store`; a host without the field | `--store <records_store>` injected once; explicit wins, no duplicate; `named_host_missing_records_store` |

## Live checks after install

These are not CI cases.

1. **hive and M5:** `records init` (or confirm 0700). Then, on a throwaway id: `park` on the agent's own pane with `--observe yes`, then `attach` a real `run-visible -- /bin/false` packet and a `-- /bin/true` packet. Then `resume --format text` (expect `available`, `writes_performed: 0`), `navigate --focus yes` (expect `focused_and_verified`), `export` (no target tuple or locators), and `forget`.
2. **Routed:** `teerex --config ~/.config/teerex/hosts.json --host hive records list` from the M5.
3. **Continuity gain:** the next two Rivet/planning handoffs are written with `records`; the receiving agent starts from `records resume` and names the correct next action without opening a transcript (stated in its report).

## agent-core changes (owner: agent-core native)

Add to `primitives/skills/rex/SKILL.md`, teerex verbs section, as written:

> **Records.** When a check result, open question or handoff must outlive your turn, write it with `teerex records` in `~/.local/state/teerex-records` (once: `teerex records init --store ~/.local/state/teerex-records`). Put private text in a JSON `--fields-file -` rather than flags. **Before you stop on unfinished work, park:** `teerex records park --store … --host <host> --socket <socket> --session "$REX_SESSION" --block "$REX_BLOCK" --writer <your name> --fields-file -` with `question` and `next_action {actor, step, stop_when}`. Attach every teerex receipt that matters: `teerex records attach --id <id> --by <you> --evidence <packet.json> --check-command "<argv>" --assertion passed|failed|unknown --establishes "…" --does-not-establish "…"`. Never infer the assertion from exit 0. Record skipped checks with `records add omission` and leftovers with `records add cleanup`. In a decision card's `context`, add `records: teerex records resume --id <id>`. Run `records lint --id <id>` before reporting and name the id in your report. To pick work up, run `teerex records resume --id <id>` first; use `records navigate --focus yes` only if you need the pane.

Add to `primitives/rules/report-contract/RULE.md`, under "What is unproven":

> Name the `teerex records` id that holds the checks, omissions and cleanup behind this section when one exists.

## Host-blocked

Nothing in `records` is host-blocked. The only adjacent gap is unsent drafts. The upstream request text is the [continuity drafts paragraph](continuity-park-resume.md#host-blocked-parts), for `~/rivet/work/teerex-lead/rex-upstream.md`.

## Extensions specified elsewhere (build on this envelope)

- **H06 decisions** ([friction-and-decisions.md](friction-and-decisions.md#part-b--h06-decision-records-on-teerex-records)): adds kind `decision`, top-level `pins[]`, claim `status`/`depends_on`/`contradicts`/`supersedes`/`status_history`, the `p` element prefix, the `pin add`, `decide`, `claim-status` and `revalidate` verbs, lint rule `L9-decision-shape`, and the `friction_report` packet kind for `attach`. All additive; build the `kind` enum and `attach` packet table so they extend without a schema bump.
- **H07 attention** ([attention-policy.md](attention-policy.md)): decision-card `context` may carry `records: teerex records resume --id <id>`; no envelope change.

## Non-goals

No storage service, database, daemon, automatic summarizer, continuous recorder or auto-park trigger. No trusted audit log, deployment certification, layout reconstruction, relaunch, draft or harness resume. Recovery remaps are not followed. No change to any existing teerex packet, boards, jobs or recovery schema.
