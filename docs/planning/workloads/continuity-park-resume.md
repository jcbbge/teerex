# U01 park/resume and U02 evidence attachments (implementation-ready spec)

**Conclusion: build one new combined-CLI leaf, `teerex continuity`, with five operations: `park`, `resume`, `attach`, `export` and `navigate`, plus `list` and `close` for housekeeping.** It is a Python 3.9+ stdlib module behind a thin supervised Zig wrapper, the same shape as `recovery`. Records are private JSON files in an explicit 0700 store, using H01's envelope field names. Resume is pure inspection. It prints the reasoning first, then attributed historical evidence re-checked now, then the current availability of the recorded target. It writes nothing, focuses nothing and types into nothing. Navigation is a separate verb that re-checks availability and then delegates to the existing `surfaces focus`. U02 is `continuity attach`: it appends bounded, digest-pinned references to teerex packets, `run-visible` output directories and board decision cards, plus explicit omissions, to an existing record. It never edits the referenced packet or card. The one supported workflow is **failed check → park with the failure receipt → decision card to the seat → resume by another agent or Josh**.

- **Status:** proposed by worker `planning-continuity`, wave 1. The roadmap names U01/U02 as the first and third features. The overnight authority ([overnight run, 13 November 2026](#sources)) makes every roadmap item build work. Choices made under that authority are labelled **chosen (overnight rubric)**.
- **Mode:** design only. **No acceptance case below has been executed.** Every example is synthetic.
- **Base:** `jcbbge/teerex` public main `244d893c2131c94778b49038910815c5fc2b04a5`.
- **Builder:** teerex lead (all repository files). agent-core owner (rex skill text). rexconfig owner (store directory and host field). See [who builds what](#who-builds-what-and-in-what-order).
- **Origins:** U01 = A01/A02, P1:p2/p5. U02 = Rex-facing A08/A12, P1:pp4–5 ([roadmap](../../roadmap.md#first-proposed-feature-manual-rex-parkresume), [inventory](../teerex-pdf-work-inventory.md)).

## Why this shape

| Decision | Choice | Reason |
| --- | --- | --- |
| Verb family | New leaf `teerex continuity …`, not `recovery` or `boards` | The roadmap proposes "a continuity leaf and its own interface tests". `recovery` is about server restarts and layout, so mixing reasoning records into its snapshot directories would blur its omission contract. `boards` state has a fixed schema and a 1 MiB cap. **chosen (overnight rubric)** |
| Runtime | Python stdlib `items/continuity/continuity.py`, embedded by `items/continuity/main.zig` through `supervised_child` | This copies `recovery`'s proven wrapper: a 15-minute outer bound, signal exit codes 130/143 and a deadline of 124. Python already has the 0700/0600/`O_NOFOLLOW`/single-link helpers in `recovery.py` and `boards.py`, so the builder reuses them rather than writing new Zig file code. |
| Record format | JSON (`record.json`), H01 field names | H01 allows "JSON with the same fields". Every teerex packet is JSON, and agents parse it without a YAML dependency. Export can render H01's Markdown later. **chosen (overnight rubric)** |
| Target selection | Explicit `--socket`, `--session`, `--block` and `--host HOST_ID`. No `REX_*` fallback | This matches observe, surfaces and boards. Agents pass `"$REX_SESSION"`/`"$REX_BLOCK"` themselves, so the CLI never guesses. |
| Reasoning input | `--fields-file ABS\|-` (JSON), **never argv** | argv shows in `ps` and in shell history. Questions and notes are private, so stdin and files are the only routes. This matches boards `--card-file` and send `--message-file -`. |
| Availability check | Re-use `surfaces inspect` (read-only) plus the `server.version`/`server.status` identity read used by `recovery.py` and `boards.py` | Both are tested read-only paths. No new Rex call is introduced. |
| Navigation | Separate `continuity navigate`, delegating to `surfaces focus` | The roadmap requires it as a "separately tested effect". Resume never calls it. |

## Store, record and file contract

### Location and permissions

- `--store ABS` is required on every operation. It is an existing directory owned by the invoking UID, with mode exactly **0700**, and a symlink as its final component is refused. This is the boards/recovery rule.
- **Estate default (chosen, overnight rubric):** `~/.local/state/teerex-continuity` on each machine. rexconfig's `./install` creates it with mode 0700. A new host field `continuity_store` in `~/.config/teerex/hosts.json` lets `teerex --config … --host NAME continuity …` inject `--store` along with `--socket`/`--host` (see [named-host routing](#named-host-routing)). The CLI itself never assumes a default path.
- Layout:

```text
<store>/lock                         0600, advisory flock, nonblocking
<store>/records/                     0700 (created by first park, O_NOFOLLOW checks)
<store>/records/<id>/                0700, created with mkdir (fails if exists)
<store>/records/<id>/record.json     0600, single link, atomically replaced
<store>/records/<id>/evidence/       0700
<store>/records/<id>/evidence/<eN>.json   0600, copied teerex packet (≤1 MiB), never overwritten
```

- **Writes:** take the nonblocking `flock` on `<store>/lock`. If it is busy, the operation refuses at once with `store_busy` and does not retry. Write `record.json.tmp-<16 hex>` with `O_CREAT|O_EXCL|O_NOFOLLOW` and mode 0600, `fsync` it, `rename` it over `record.json`, then `fsync` the directory. `generation` increments on every write. `--expect-generation N` (optional, on `attach`/`close`) refuses a mismatch with `generation_mismatch`.
- **Reads:** `O_NOFOLLOW|O_NONBLOCK`, then `fstat`. The file must be a regular file, owned by the UID, mode 0600 (store files) and `st_nlink == 1`, or the read refuses.
- **Nothing is deleted** by any operation. There is no eviction or retention timer. Josh deletes a record directory himself.
- **Bounds:** 1024 records per store (a park beyond that refuses with `store_full`). `record.json` at most 256 KiB encoded. 64 evidence entries per record. Copied packet at most 1 MiB. `--fields-file` at most 64 KiB.

### Identifiers

- `id`: `--id SLUG` matching `[a-z0-9][a-z0-9-]{0,63}`, or generated as `park-<UTC YYYYMMDDTHHMMSSZ>-<8 hex>`. An existing id refuses with `record_exists`. Ids are never reused.
- Evidence ids: `e1`, `e2`, … in record order. They are never renumbered.

### Record JSON (schema `teerex.continuity/1`)

Key order is fixed and is the order resume renders.

```json
{
  "schema": "teerex.continuity/1",
  "record_version": 1,
  "kind": "investigation",
  "id": "inv-cache-stale",
  "generation": 2,
  "state": "parked",
  "written_at": "2026-11-13T10:05:00+00:00",
  "writer": "agent-a",
  "supersedes": null,

  "question": "Why does the read-through cache return a stale entry after an update?",
  "hypothesis": {"text": "Invalidation runs before the write commits", "basis": "inferred"},
  "next_action": "agent-a: run `make test-cache CASE=update_then_read DELAY_MS=50`; stop after 20 iterations; attach the run-visible receipt.",
  "claims": [{"text": "Stale read reproduced 3/20", "basis": "observed", "evidence": ["e1"]}],
  "omissions": [{"what": "concurrency suite", "reason": "40 min; deferred until hypothesis narrows"}],
  "uncertainty": "3/20 is a small sample.",
  "notes": "free text, private",

  "subject": {"repo": "example/widget", "commit": "1111111", "dirty": "unknown"},
  "target": {
    "host": "hive",
    "server": "unix:///run/user/1000/rex/server.sock",
    "session_id": "session:00000000-0000-4000-8000-000000000001",
    "block_id": "block:00000000-0000-4000-8000-000000000002"
  },
  "target_at_park": {
    "checked": true,
    "status": "available",
    "server_identity": {"instance_id": "inst-SYNTH", "host_id": "host-SYNTH", "version": "SYNTH", "api": 13},
    "pane": {"label": "cache-investigation", "window_label": "work", "host_id": "host-SYNTH"},
    "checked_at": "2026-11-13T10:04:58+00:00"
  },

  "evidence": [ "…see evidence entry below…" ],
  "cleanup": {"status": "none_needed", "items": []},
  "private": ["target", "target_at_park", "notes", "evidence[].locator", "evidence[].copy", "subject.repo"]
}
```

- `kind` is `investigation` for park. U02 attachment does not change it. `close` may set `state`.
- `state`: `parked`, `concluded`, `abandoned` or `superseded_by:<id>`. `open` exists in H01, but teerex records are only ever written parked or closed.
- `basis` uses H01's set: `observed`, `inferred`, `supplied` or `chosen`. A claim with basis `observed` must cite at least one evidence id that exists, or it refuses with `observed_claim_without_evidence`.
- `next_action` is required while the record is parked. It is refused when shorter than 12 bytes or when it equals (case-insensitively, trimmed) one of `continue`, `keep digging`, `keep investigating`, `tbd`, `todo` or `continue investigating` (`vague_next_action`). This is a cheap mechanical floor. It is no substitute for review.
- Missing optional fields are stored as explicit `null`. Resume shows each one as `missing`, never as an empty string.

### Evidence entry (U02; H01 evidence ref plus H01 `teerex` block)

```json
{
  "id": "e2",
  "type": "teerex_run_visible",
  "locator": "/home/agent/work/x/runs/2026-11-13-b/receipt.json",
  "digest": "sha256:…",
  "bytes": 18234,
  "recorded_at": "2026-11-13T11:40:02+00:00",
  "attached_by": "agent-a",
  "availability_at_attach": "present",
  "copy": "evidence/e2.json",
  "label": "failing check",
  "teerex": {
    "packet_kind": "run_visible_result",
    "schema_version": 1,
    "target": {"host": "hive", "server": "unix:///…", "session_id": "session:…", "block_id": "block:…"},
    "source_version": "SYNTH/API13",
    "observation_id": null,
    "outcome": "exit_reported",
    "exit": {"code": 1, "signal": null},
    "reported_success": false,
    "output_complete": {"stdout": false, "stderr": true},
    "storage_dir_retained": true,
    "carried_flags": ["retry_safe:false", "task_completion:not_assessed"]
  }
}
```

- **Types and how each is read.** Every input path is absolute, owned by the UID, a regular file or directory, not a symlink in its final component, and opened `O_NOFOLLOW|O_NONBLOCK`, so FIFOs and devices are refused by `fstat`.

| Flag | `type` | Read | Copied |
| --- | --- | --- | --- |
| `--evidence ABS` where JSON `kind` is `run_visible_result`/`run_result`/`observation_changes`/`observation_wait`, or the object has `observation_id`+`capture` (an observe packet) | `teerex_run_visible` · `teerex_run` · `teerex_compare` · `teerex_watch` · `teerex_observation` | ≤1 MiB, parsed. The `teerex` block fields are copied **verbatim** (no defaults, absent stays `null`) | yes, to `evidence/eN.json` |
| `--evidence ABS` for any other file | `file` | sha256 streamed, ≤64 MiB. **Content never parsed, copied or printed** | no |
| `--evidence-dir ABS` (a `run-visible --output-dir`) | `teerex_output_dir` | Names and sha256 of `stdout.full`/`stderr.full` (≤64 MiB each). Other files (argv/env/stdin) are listed **by name only**, flagged `private_contents_not_read` | no |
| `--card BOARD_STORE_ABS --card-id ID --seat-host H --seat-socket S --seat-session SS --seat-block B` | `board_card` | Reads boards `state.json` under its shared read path; records `{card_id, title, open|resolved, answer_present}`. Never the card body or answer text | no |
| `--commit REPO_ABS SHA` | `commit` | Records the supplied SHA as `basis: supplied`. Runs no Git | no |

- `carried_flags` is built only from fields that are present in the packet: `retry_safe`, `task_completion`, `painted_visibility`, `all_descendants_verified_gone`, `atomic_snapshot` and `freshness`, rendered `name:value`. A packet without them gets `[]`. Nothing is inferred.
- `reported_success` is the packet's own `success` and appears only inside `teerex`. **There is no record-level success field.**
- Truncation stays visible: `capture.complete` or per-stream `complete`/`full_complete` is copied into `output_complete`. A `null` exit stays `null` (rendered `unknown`).
- **Duplicate attach:** if an entry already has the same `type` and digest, the attach refuses with `duplicate_evidence` and names the existing id.

## Commands

All operations print exactly one JSON object on stdout (or, for `resume --format text`, the rendering below). Diagnostics on stderr are fixed codes and byte counts only (see [no content leakage](#no-content-leakage)).

### `continuity park`

```sh
printf '%s' "$FIELDS_JSON" | teerex continuity park --store "$STORE" --host hive \
  --socket /run/user/1000/rex/server.sock \
  --session "$REX_SESSION" --block "$REX_BLOCK" \
  --writer agent-a --fields-file - \
  [--id inv-cache-stale] [--supersedes OLD_ID] \
  [--evidence ABS]... [--evidence-dir ABS]... [--card …] [--commit REPO SHA]... \
  [--observe yes|no] [--observe-max-bytes 256..65536] \
  [--target-check yes|no] [--allow-unavailable-target yes] [--timeout-ms 100..60000]
```

- `--fields-file` JSON keys: `question` (required, 1–2048 bytes), `next_action` (required, ≤2048), and optionally `hypothesis{text,basis}`, `claims[]` (≤32), `omissions[]` (≤32, each `what`/`reason` ≤512), `uncertainty` (≤2048), `notes` (≤16 KiB), `subject{repo,commit,dirty,artifact,digest}` and `cleanup`. Unknown keys refuse with `unknown_field:<name>`, so a typo never drops a caveat silently.
- `--target-check yes` (default) runs the [availability check](#target-availability). When the status is not `available`, park refuses with `target_not_available:<status>` unless `--allow-unavailable-target yes` is given. With that flag the record is written with the actual status: parking the reasoning of a pane that already died is legitimate.
- `--observe yes` (default **no**) runs one `observe` on the exact target with `--max-bytes` (default 4096) and attaches the packet as `e1`, type `teerex_observation`, copied. Terminal content then lives **only** in that 0600 copy.
- `--supersedes OLD` (in the same store) sets the old record's `state` to `superseded_by:<new id>` in the same locked transaction. A missing or already-closed OLD refuses before anything is written.
- **Receipt:** `{"schema_version":1,"kind":"continuity_park_result","outcome":"parked","id":…,"generation":1,"path":…,"target_status":…,"evidence_ids":[…],"bytes":{"question":n,"next_action":n,"notes":n},"record_digest":"sha256:…"}`. The reasoning text is **not echoed**.
- **Verified readback:** after the rename, park re-opens `record.json`, re-parses it and compares the digest. On a mismatch the result is `outcome: uncertain`, exit 1, and the file is left in place for inspection.

### `continuity resume` (inspection only)

```sh
teerex continuity resume --store "$STORE" --record ID --host hive \
  [--target-check yes|no] [--evidence-check yes|no] [--format json|text] [--timeout-ms N]
```

Output (JSON, fixed top-level order):

```json
{
  "schema_version": 1, "kind": "continuity_resume",
  "record": {"id": "…", "state": "parked", "generation": 3, "written_at": "…", "writer": "agent-a"},
  "reasoning": {"question": "…", "hypothesis": {…}, "next_action": "…", "claims": […],
                "omissions": […], "uncertainty": "…", "notes": "…", "missing": ["cleanup"]},
  "evidence": [{"id": "e2", "type": "teerex_run_visible", "label": "failing check",
                "attached_by": "agent-a", "recorded_at": "…", "teerex": {…},
                "availability_now": "present|missing|digest_differs|hazard_refused|not_checked",
                "copy_availability_now": "present|missing|digest_differs|none"}],
  "target": {"recorded": {…}, "at_park": {…},
             "now": {"status": "available", "checked_at": "…", "server_identity": {…}, "pane": {…}}},
  "navigate": {"possible": true, "argv": ["teerex","continuity","navigate","--store","…","--record","ID","--host","hive","--focus","yes"]},
  "is_fresh_snapshot": false, "authority_granted": "none", "draft_restored": false, "harness_resumed": false,
  "writes_performed": 0
}
```

- **Order is the contract.** Reasoning comes first, historical evidence (each item attributed with `attached_by` and `recorded_at`) second, current target availability last. `--format text` renders the same three sections with the headers `REASONING`, `EVIDENCE (historical, re-checked now)` and `TARGET (now)`, so Josh can read it in `leaf`.
- **Evidence re-check:** each locator and copy is re-hashed under the same file-hazard rules. `digest_differs` is reported, never "fixed". A symlinked, linked or wrong-owner path becomes `hazard_refused`, and that file is not read. A `board_card` is re-read for open/resolved only.
- **Writes nothing.** No lock is taken beyond a shared read lock (`flock LOCK_SH|LOCK_NB`; busy refuses with `store_busy`). There is no `last_resumed_at`. `writes_performed: 0` is asserted by test.
- The four explicit `false`/`none` fields are carried verbatim on every resume. A resumed record is not a fresh snapshot, an authority grant, a draft buffer or a harness resume.

### Target availability

This check is shared by park, resume and navigate. It makes two read-only calls on the **recorded** socket only:

1. `server.version` + `server.status` (recovery's identity read): `instance_id`, `host_id`, version, API.
2. `teerex surfaces inspect --socket S --session SS --pane B --timeout-ms N`, invoked as the current teerex executable (recovery's `TEEREX_…_EXECUTABLE` pattern).

| `status` | Condition | Fallback |
| --- | --- | --- |
| `available` | Same `instance_id` and `host_id` as `target_at_park`; inspect finds the block attached; block `host_id` matches | — |
| `absent` | Same server instance, complete inspect, block not present | **none**. No search by label, title, cwd or neighbour |
| `server_unreachable` | Socket missing or refused, or identity read failed | none |
| `different_server` | Socket answers but `host_id` differs, **or** the current invocation's `--host` differs from `target.host` (then no call is made at all) | none |
| `server_instance_changed` (stale) | Same `host_id`, different `instance_id` (Rex restarted). Block IDs from the old instance are not trusted, even if an equal ID exists | none. The output adds `hint: "recovery remap receipts may map this pane; continuity does not follow them"` |
| `block_host_changed` | Block present but its `host_id` differs from park time | none |
| `unknown` | Deadline, partial transport or malformed inspect | none |
| `not_checked` | `--target-check no` | — |

`instance_id` is compared only when park recorded one. A record parked with `--allow-unavailable-target` and no identity yields `available_unverified_instance` when the block is found. Navigate refuses that status.

### `continuity navigate` (the separate effect)

```sh
teerex continuity navigate --store "$STORE" --record ID --host hive --focus yes [--timeout-ms N]
```

- `--focus yes` is required, and any other value is a usage error. It runs the availability check; anything other than `available` refuses with exit **3**, `outcome: refused_target`, and the status. It then calls `teerex surfaces focus --socket --session --pane` for the recorded block only and returns that receipt nested under `focus`. Success is `focused_and_verified`.
- It never opens, relaunches, moves, resizes, renames, closes, pastes or sends, and makes one attempt only. It writes nothing to the record.

### `continuity attach` (U02)

```sh
teerex continuity attach --store "$STORE" --record ID --by agent-b \
  [--evidence ABS]... [--evidence-dir ABS]... [--card …] [--commit REPO SHA]... \
  [--label TEXT]... [--fields-file ABS|-] [--expect-generation N]
```

- At least one evidence flag or a `--fields-file` is required. `--label` pairs positionally with the evidence flags, each 1–128 bytes, with no control characters.
- In `attach`, `--fields-file` may contain only `claims`, `omissions`, `uncertainty`, `cleanup` and `next_action`. The new values **append** to `claims`/`omissions` and **replace** `uncertainty`/`cleanup`/`next_action`. The previous `next_action` is kept in `history[]` (`{generation, next_action, replaced_at}`, ≤32 entries), so the reasoning trail survives.
- Attaching to a `concluded`/`abandoned`/`superseded` record refuses with `record_closed`.
- The receipt names the new ids, the new generation and the record digest. It does not echo the content.
- **The receipt kinds U02 attaches to:**
  - a park record: directly, as above;
  - a `run_visible_result`/`run_result` packet: attached **into** a park record as evidence. The packet file is never modified;
  - a decision card: attached as a `board_card` reference. The boards schema is **not** changed. The card author puts the line `continuity: teerex continuity resume --record ID` in the card `context`, which is plain text the boards contract already allows.

### `continuity export`

```sh
teerex continuity export --store "$STORE" --record ID [--include FIELD]...
```

- This is a projection to stdout only and writes no file. It drops every path in `private[]`. The defaults are `target`, `target_at_park`, `notes`, every `evidence[].locator`, every `evidence[].copy`, `subject.repo`, `teerex.target`, card seat tuples and `history[].next_action`.
- **Always exported, and cannot be private:** `kind`, `state`, `question`, `next_action`, every `claims[].basis`, `omissions`, `uncertainty`, `cleanup.status`, every `availability_*`, every `teerex.exit/outcome/output_complete/carried_flags/reported_success`.
- A private evidence ref becomes `{id, type, label, availability_at_attach, private: true}`.
- `--include` naming a private field refuses with exit 1, `private_field_export_refused:<field>`. There is no override flag. To share a private value, the writer edits the record by hand outside teerex.
- **Secret refusal:** before printing, every always-exported string is scanned for `-----BEGIN`, `AKIA[0-9A-Z]{16}`, `gh[pousr]_[A-Za-z0-9]{20,}`, `sk-[A-Za-z0-9_-]{20,}`, `xox[abpr]-`, `eyJ[A-Za-z0-9_-]{10,}\.` and any run of 40 or more characters from `[A-Za-z0-9+/=_-]` without spaces. A hit refuses the whole export with `export_refused_secret_shaped:<field path>`. The value is not printed and nothing is silently redacted (H01 rule). This is a floor and does not guarantee secret-freedom; the output says so in `"secret_scan": "heuristic_floor_only"`.

### `continuity list` and `continuity close`

- `list --store S [--state parked|all]` returns `[{id, kind, state, written_at, writer, question, target:{host,session_id,block_id}, evidence_count, generation}]`, newest first, all of them (≤1024). It is read-only, under the shared lock. Default `--state parked`.
- `close --store S --record ID --state concluded|abandoned --by NAME [--fields-file]` writes the final `uncertainty`/`cleanup`/`claims` and sets the state. `next_action` may then be `null`.

### Exit codes (every operation)

| Exit | Meaning |
| --- | --- |
| 0 | Operation completed. Park/attach/close: written **and** read back. Resume/list/export: record(s) read and printed. **Resume exits 0 whatever the target status**, because availability is reported data |
| 1 | Refusal or operational failure, with JSON `outcome: refused\|uncertain\|failed` and `failure_reason` (codes below) |
| 2 | Usage error: unknown flag, bad value, missing required flag. Message on stderr, no JSON |
| 3 | `navigate` only: target not available (`refused_target`) |
| 124 / 130 / 143 | Outer deadline / SIGINT / SIGTERM, through the supervised wrapper. No success JSON |

`failure_reason` codes: `store_busy`, `store_hazard` (owner, mode, symlink or link count), `store_full`, `record_exists`, `record_not_found`, `record_closed`, `record_oversize`, `record_corrupt`, `generation_mismatch`, `fields_oversize:<field>`, `unknown_field:<name>`, `invalid_utf8:<field>`, `control_character:<field>`, `vague_next_action`, `observed_claim_without_evidence`, `evidence_hazard:<flag index>`, `evidence_oversize:<flag index>`, `evidence_limit`, `duplicate_evidence:<id>`, `target_not_available:<status>`, `private_field_export_refused:<field>`, `export_refused_secret_shaped:<path>`, `readback_mismatch`, `internal_error`.

## Unicode

- Every text field must be valid UTF-8 with no lone surrogates. It is stored with `ensure_ascii=False` and read back **byte-identical**. No NFC/NFKC normalization, trimming or case folding is applied, except in the `vague_next_action` comparison, which works on a lowercased trimmed copy only.
- Bounds count **UTF-8 bytes**, not code points.
- C0 controls except `\t` and `\n`, DEL and C1 controls are refused (`control_character:<field>`) in every field except `notes`. `notes` additionally keeps `\r`. Bidi override characters (U+202A–U+202E, U+2066–U+2069) are stored but rendered in `--format text` as `\u{…}` escapes, so a question cannot visually reorder itself.
- Labels follow the surfaces rule: 1–128 UTF-8 bytes, no control characters.

## No content leakage

- Reasoning reaches teerex only through `--fields-file` or stdin, never argv.
- Park, attach and close receipts echo ids, byte counts and digests, **never** question/hypothesis/notes text. Only `resume`, `list` (question only) and `export` print content, and only on the caller's stdout.
- stderr carries fixed codes plus field names and byte counts only. The Python entry point catches every exception and prints `internal_error` with the exception **class name** only, so no traceback and no message, since values can be embedded in exception text.
- continuity emits no OSC program status, sets no pane title or label, writes no `teerex boards` fleet report, sends no message, and adds nothing to the agents launch registry or hook output. The Zig wrapper relays the child's stderr unchanged; it never logs stdout.
- Test: plant `SYNTHETIC_QUESTION_CANARY_9c41` in the question and `SYNTHETIC_NOTES_CANARY_51be` in notes, run every operation including each refusal path, and assert both canaries are absent from all stderr bytes and from park/attach/close stdout. Then assert the question canary is present in resume stdout and the notes canary absent from export stdout.

## Neighbouring panes are untouched

Park (with `--observe no`), resume, list, attach, export and close make **no** Rex call other than the identity read and `surfaces inspect` on the recorded target. `--observe yes` adds one `observe` read of that target. None of them issues `session.focus_block`, terminal write, `session.move_block`, open, close or rename. Navigate adds exactly one `surfaces focus`, on the recorded block.

## Named-host routing

`src/targets.py` adds these entries to `SELECTORS`:

- `("continuity", op): ("socket", "host", "continuity_store")` for `park`, `resume` and `navigate`;
- `("continuity", op): ("continuity_store",)` for `attach`, `export`, `list` and `close`.

`continuity_store` joins `PATH_FIELDS` and is injected as `--store`. A configured host without `continuity_store` refuses the routed call (`named_host_missing_continuity_store`), which is the existing missing-field behaviour. rexconfig adds `"continuity_store": "<home>/.local/state/teerex-continuity"` (and the M5 equivalent) to `hosts.json`, and creates both directories 0700. **chosen (overnight rubric)**: one routed command works from any machine, the same way boards does.

## Who builds what, and in what order

| Step | Owner | Files | Depends on |
| --- | --- | --- | --- |
| 1 | teerex lead | `items/continuity/continuity.py`, `items/continuity/main.zig` (copy of the recovery wrapper with env `TEEREX_CONTINUITY_EXECUTABLE`), `items/continuity/test_continuity.py`, `items/continuity/README.md` (Who/What/When/Where/Why/How, the [bounds](#location-and-permissions), the [exit table](#exit-codes-every-operation)) | nothing. U01 (park/resume/list/close/navigate) first |
| 2 | teerex lead | `build.zig` (module `rex_continuity`, imports `supervised_child`), `src/main.zig` (dispatch `continuity` → `rex_continuity.run(rest)` and one usage line: `continuity park\|resume\|navigate\|attach\|export\|list\|close  Private park/resume records and evidence attachments`), `src/targets.py` + `src/test_targets.py` (selectors) | step 1 |
| 3 | teerex lead | U02 additions inside the same files (`attach`, `export`, card/dir evidence types) | step 1. The H01 field names are already used. If the coordinator renames an H01 field, only the JSON key strings change |
| 4 | teerex lead | `items/README.md` (one line: combined-CLI composed command, not a cartridge), `docs/alpha5.md` command list. CI test registration is coordinated with the CI owner (`.github/workflows/ci.yml` is theirs) | steps 1–3 |
| 5 | rexconfig | `hosts.json` field `continuity_store` on hive and the M5; `./install` creates the 0700 store | step 2 released |
| 6 | agent-core owner | rex skill: one "Park before you stop" paragraph: `continuity park` with the agent's own explicit `REX_SESSION`/`REX_BLOCK`, attach the failing receipt, put the `continuity resume` line in the decision card | step 5 |

Implementation needs no new Rex API and no change to the observe, run, run-visible, surfaces, boards or recovery packets and schemas.

## Acceptance (design only, not executed)

Fixture: a disposable Rex server (repository CI's checksum-pinned build, random private socket), a disposable 0700 store under a private temporary directory, the synthetic `example/widget` texts, and a canary program `canary.py` in a **neighbour** pane that appends every stdin byte it receives to a private file. Every case also asserts the [leak test](#no-content-leakage) and, unless noted, that the neighbour canary file stays empty and that `session.view` focus, zoom, labels and layout revision are identical before and after.

| # | Case | Pass | Counterexample that must fail |
| --- | --- | --- | --- |
| C1 | **Two asymmetric investigations.** Record A on pane P1: full fields, `--observe yes`, a run-visible failure packet. Record B on pane P2: question and next action only, no evidence, Unicode question `"Warum schlägt 🧪 fehl? — مرحبا"` | `resume A` shows A's question first, then `e1`/`e2`, then `available`. `resume B` shows `evidence: []` and `missing` lists hypothesis/uncertainty/cleanup. B's question round-trips byte-identical (sha256 of the field before/after). `list` returns two distinct ids | resume of B containing any A text or evidence id; B's question normalized (NFC) or byte count changed; missing fields rendered as `""` |
| C2 | **Incomplete evidence.** Attach an observe packet with `capture.complete=false` and a run-visible packet with `exit_report` null; then delete the original packet locator and mutate the copy of another | `output_complete` false and `exit {code:null,signal:null}` rendered `unknown`. `availability_now: missing` for the deleted locator, `copy_availability_now: present`. The mutated copy shows `digest_differs` | any `true`/`0` filled in for an absent field; `present` reported for the deleted file; the digest silently updated |
| C3 | **Missing target.** Close P2 with `surfaces close`, then resume B | exit 0, `target.now.status: absent`, `navigate.possible: false`. `navigate` exits 3 `refused_target`. No pane is created and the session's block count is unchanged | any fallback match by label or neighbour; a new pane opened; navigate exit 0 |
| C4 | **Stale and different server.** (a) Restart the disposable server on the same socket, then resume A. (b) Resume A with `--host m5` against a record parked with `host: hive` | (a) `server_instance_changed`, even though a block with an equal ID may exist. (b) `different_server` and **zero** Rex calls (assert with a wrapper `rex` that logs invocations) | (a) `available`; (b) any Rex invocation |
| C5 | **File hazards.** Store mode 0755; store as a symlink; `record.json` hard-linked; `record.json` replaced with a symlink to a 0600 file; `--evidence` as a FIFO; `--evidence` owned by another UID (skipped where root is unavailable, and recorded as skipped); fields file 65 KiB; 1025th park | `store_hazard`, `store_hazard`, `store_hazard`, `store_hazard`, `evidence_hazard:0`, `evidence_hazard:0`, `fields_oversize:fields_file`, `store_full`. Each exits 1 and makes no partial write (store tree listing unchanged) | the operation following a symlink or reading a FIFO (test times out); a partial record directory left behind |
| C6 | **Export refuses private fields.** Record A with `SYNTHETIC_SECRET_DO_NOT_EXPORT_7f3a` in notes; then `export --include notes`; then a record whose `uncertainty` contains `ghp_` + 36 synthetic characters | First export: exit 0, no canary, no locators or target tuple, `uncertainty`/`omissions`/every `basis`/`carried_flags` present. `--include notes`: exit 1 `private_field_export_refused:notes`. Third: exit 1 `export_refused_secret_shaped:uncertainty`, value not on stdout or stderr | canary present; `uncertainty` silently dropped or masked to pass |
| C7 | **Success vs failure receipt (U02 workflow).** `run-visible -- /bin/false` and `run-visible -- /bin/true`, both with `--output-dir`. Park with the failure attached, `boards ask` a card whose context carries the resume line, attach the card. Fix and attach the success | `e1.teerex`: `exit.code 1`, `reported_success false`, `outcome exit_reported`. `e3.teerex`: `exit.code 0`, `reported_success true`, `carried_flags` include `task_completion:not_assessed`. The `board_card` entry shows `open`, then `resolved` after `boards ask --resolve`, with no answer text. The record has **no** top-level success field. Packet files' sha256 unchanged | a record-level `success`; `carried_flags` dropped; answer text copied; packet modified |
| C8 | **Inspection has no effects.** Run resume, list and export 20 times while the neighbour runs | canary file empty. Before/after `session.view` identical. Store tree (names, sizes, mtimes, inode numbers) identical. `writes_performed: 0` | any byte to the canary; any mtime change |
| C9 | **Navigation is separate.** `navigate --focus yes` on available A | exactly one focus change, to P1 (`focused_and_verified`). Neighbour canary empty; no pane created, closed or moved | navigate without `--focus yes` succeeding; any second mutation |
| C10 | **Concurrency.** Two `attach` calls racing on A while a third holds the lock | one succeeds, others `store_busy` exit 1 without retry; `--expect-generation` stale → `generation_mismatch`. Final record has a single coherent generation | a lost update (both attaches report success, one missing) |

Recorded as test steps, not executed here: `python3 items/continuity/test_continuity.py -v` (C1–C10 on Linux/API13 in CI; Mac API13 on a disposable runner per the existing CI owner's matrix).

## Host-blocked parts

None of U01/U02 is host-blocked. The only adjacent gap is **drafts**: Rex exposes no authoritative input-buffer read, so a park cannot preserve unsent text in a pane. That is an explicit non-goal here, already recorded by recovery. Upstream request text, if wanted: *"Expose a read-only, per-block `terminal.input_buffer` (or equivalent) API returning the pending unsubmitted line(s) of an attached terminal with its owning program, without consuming or echoing them, so tools can preserve operator drafts across restarts and handoffs."*

## H01 envelope fields this spec consumes (for the coordinator's alignment)

`record_version`, `kind`, `id`, `written_at`, `writer`, `state` (incl. `superseded_by:<id>`), `subject{repo,commit,dirty,artifact,digest}`, `question`, `hypothesis{text,basis}`, `next_action`, `claims[]{text,basis,evidence[]}`, `omissions[]{what,reason}`, `uncertainty`, `cleanup{status,items[]}`, `private[]`, `evidence[]{id,type,locator,digest,recorded_at,availability,private}` and the `teerex` block `{packet_kind,schema_version,target,source_version,observation_id,outcome,exit,output_complete,storage_dir_retained,carried_flags}`.

**teerex-specific additions** (proposed for H01 to accept or namespace): `schema`, `generation`, `supersedes`, `history[]`, `target`, `target_at_park`, `evidence[].bytes/copy/label/attached_by/availability_at_attach`, `teerex.reported_success`, and evidence `type` values `teerex_run_visible`, `teerex_watch` and `teerex_output_dir`.

**Deliberate differences:** H01's `availability` becomes `availability_at_attach` (stored) plus `availability_now` (computed on resume and never stored), so a stored value is never mistaken for current. H01's `checked_at` is the resume time and is not persisted. H01's `open` state is unused.

## Non-goals

No automatic layout reconstruction, relaunch or execution on resume. No draft, input-buffer or harness-session resume claims. No continuous or automatic recorder, and no trigger that parks on failure by itself. No new service, database or daemon. No change to any existing teerex packet, boards or recovery schema. No following of recovery remaps. No deletion or retention policy.

## Sources

[Roadmap current plan](../../roadmap.md#current-phased-plan--13-november-2026) · [delegation briefs, H01](../teerex-delegation-briefs.md#h01--evidence-investigation-and-handoff-records) · [H01 evidence records (wave-1 draft)](evidence-records.md) · [observe](../../../items/observe/README.md) · [run](../../../items/run/README.md) · [run-visible](../../../items/run/VISIBLE.md) · [boards](../../../items/boards/README.md) · [jobs](../../../items/jobs/README.md) · [recovery](../../../items/recovery/README.md) · [surfaces](../../../items/surfaces/README.md) · root dispatch `src/main.zig` and named-host selectors `src/targets.py` at `244d893`. The overnight authority is the seat's private run note for 13 November 2026, quoted in the brief. It is not in this repository.
