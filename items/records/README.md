# Private records

Experimental combined-CLI composition, not an independent cartridge. Python 3.9+ stdlib runs as a supervised foreground controller (`python3 -I`); no service, database, background recorder or automatic action. Rex-facing acceptance uses disposable API13 servers. Installation and personal-store acceptance belong to the integration owner.

## Who, what and when

Operators and agents retain investigations, experiments, shipping receipts, handoffs and parked Rex work in one `teerex.records/1` envelope. Write a question and a structured next action; attach the actual evidence, its limitations and omissions. Start a later turn with `resume`, which puts reasoning before historical evidence and current target availability. A record is a set of attributed claims, not authentication, deployment certification or an authority grant.

## Where

`--store ABS` selects a private store. The default is `$HOME/.local/state/teerex-records`. Named-host routing reads optional `hosts.NAME.records_store`; otherwise it uses `hosts.NAME.home/.local/state/teerex-records`, as the implementation brief directs. An explicit `--store` wins. Store and evidence paths belong to the selected command host; nothing is uploaded. `park`, `resume` and `navigate` receive host/socket routing; offline leaves receive only the store. Park requires explicit canonical session/block IDs and never guesses them from `REX_*`.

The store is caller-owned `0700`; `lock`, `record.json` and copied packets are caller-owned, single-link, regular `0600` files. Final symlinks, FIFOs/devices, wrong ownership/modes and leftover staging files refuse. No read follows a record-directory symlink. Shared readers and exclusive writers use nonblocking flock: contention is `store_busy`, without retry. Writes stage, fsync, replace, fsync directories, then reopen, parse and verify the digest. Readback mismatch is `uncertain`; inspect rather than retry. A multi-record supersession is coordinated under that same lock; disk failure can still leave an uncertain partially completed supersession. Only `forget` deletes record directories.

## Why

A green exit is distinct from a passed assertion, and both are distinct from a shipped outcome. Historical packets retain their own success, exit, completeness and caveat fields. Missing values remain null; evidence availability is recomputed in memory and never relabelled as a fresh snapshot. An observed claim must cite evidence; a supplied claim must name its source. Completeness is checked by lint rather than filled with invented defaults.

## How

```sh
teerex records init --store /absolute/private/records
# Prefer stdin for private content; flags are available for short non-private fields.
teerex records new --kind investigation --id cache-check --writer worker --fields-file - <<'JSON'
{"question":"Why is the cache stale?","next_action":{"actor":"worker","step":"run the cache check with one delay changed","stop_when":"20 iterations; attach the receipt"}}
JSON
teerex records park --id cache-pane --writer worker --host hive --socket "$SOCKET" \
  --session "$SESSION" --block "$BLOCK" --observe yes --fields-file /absolute/private/fields.json
teerex records attach --id cache-check --by worker --evidence /absolute/run/receipt.json \
  --check-command 'cache check' --assertion failed --establishes 'unit behavior' \
  --does-not-establish 'deployment'
teerex records add omission --id cache-check --by worker --what 'integration check c1' --reason 'not run yet'
teerex records add cleanup --id cache-check --by worker --what 'remove scratch' --where 'fixture host' --owner worker
teerex records show --id cache-check --format text
teerex records resume --id cache-pane --host hive --format text
teerex records navigate --id cache-pane --host hive --focus yes
teerex records lint --id cache-check
teerex records export --id cache-check --format md
teerex records forget --id cache-check --expect-generation 4 --reason 'retention completed'
```

Every verb accepts `--store`. `--help` lists flags. Supported operations:

| Verb | Contract |
|---|---|
| `init` | Create or validate the private store and lock. |
| `new --kind investigation\|experiment\|receipt\|handoff\|decision --writer NAME` | New open record; optional `--id`, `--supersedes`, `--git-repo` (observed HEAD/dirty/untracked names), `--subject-artifact`. |
| `park --writer NAME --host H --socket ABS --session ID --block ID` | New parked investigation, question and complete next action required. Target check defaults yes; `--allow-unavailable-target yes` preserves an unavailable target honestly. Optional one `--observe yes` read. |
| `add claim\|check\|omission\|cleanup --id ID --by NAME` | Append assigned `kN`, `cN`, `oN`, `uN` IDs. Claims take text/basis/evidence IDs/source/scope; checks require command, ran, process-exit, assertion, establishes and does-not-establish. Fields-file can append arrays. |
| `attach --id ID --by NAME` | Append evidence plus optional claims/omissions or replacement uncertainty/cleanup/next action from fields-file. Explicit check assertion required when `--check-command` is used. |
| `set --id ID --expect-generation N FIELD=JSON...` | Replace supported fields or ID-addressed element fields. Fields-file supports private notes. Question/next-action/hypothesis/uncertainty replacements retain previous values in bounded history. Moving an evidence locator retains `moved_from`. State cannot be set here. |
| `close --id ID --state concluded\|abandoned --by NAME` | Apply final fields and lint before committing; next action may be null after close. |
| `show --id ID`, `resume --id ID --host H` | Read-only JSON or text. `--evidence-check no` suppresses artifact reads; resume adds a target check unless `--target-check no`. No record timestamp, inode, size or generation changes. |
| `navigate --id ID --host H --focus yes` | Recheck target, then exactly one `surfaces focus`; any status other than available refuses. No open, relaunch, move, resize, rename, close, paste or send. |
| `list [--kind K] [--state open\|parked\|all]` | All by default; open/parked first, then newest. JSON or text summaries. |
| `lint --id ID\|--all` | L1 specific next action; L2 evidence availability; L3 check consistency; L4 scope words; L5 packet integrity; L6 kind requirements; L7 retained storage vs cleanup done; L8 inbound handoff authority. |
| `export --id ID [--format json\|md] [--out NEW_ABS]` | Lint, project private fields away, preserve caveats and scan exported strings before writing. Never overwrite. `--include` cannot override privacy. |
| `forget --id ID --expect-generation N --reason TEXT` | Explicit deletion of that record and its copies only. |

All record writes accept `--expect-generation`; `set` and `forget` require it. Write receipts contain IDs, generation, byte counts and digests, never reasoning content. Kind-specific fields and evidence references are schema-checked on write. `new` accepts incomplete drafts; park/close/export enforce the applicable lint rules. Closed or superseded records of the original four kinds cannot be appended to; decision applicability and status updates remain explicit.

### Evidence

`--evidence ABS|-` accepts supported schema-1 run-visible, run, observe, compare and watch packets. The packet table and `KINDS` are centralized for additive extensions. Packet files are copied byte-for-byte to `evidence/eN.json` and SHA-256 pinned. `teerex` metadata carries the packet's values; absent fields stay null. The native run-visible `storage_retained` field maps verbatim to `storage_dir_retained`. Capture completeness is independent of assertion and exit. Malformed teerex-looking JSON refuses rather than becoming a generic file. Other files are streamed for SHA-256 and not copied or printed.

`--evidence-dir ABS` hashes only `stdout.full`/`stderr.full`; argv/env/stdin and other files are listed by name with `private_contents_not_read`, without opening their contents. `--card ABS --card-id ID --seat-host H --seat-socket S --seat-session ID --seat-block ID` reads a registered board under its shared lock and retains only card ID/title/state/answer-present, never body or answer. `--commit REPO SHA` is supplied evidence and runs no Git. `--ref url|human_report|screenshot LOCATOR` reads nothing; human reports require `--supplied-by`. `--label` pairs in input order; `--exportable` marks the immediately preceding ref exportable. Duplicate type/digest refuses.

A changed or missing original stays changed or missing even when a copy is present. Copy integrity has its own status. `show` and `resume` do not repair hashes. Private evidence omits its locator, digest, copy path, moved-from history, source, seat tuple and target/storage identity on export, while retaining packet caveats. Cleanup location/owner and private history/notes/subject paths are omitted. Every exported string is checked against the spec's token, key and long-run patterns; a match refuses the whole export with a field path only. Digest/commit-shaped values are exempt only in their designated fields. This is a heuristic floor, not proof of secret-freedom. Bidi overrides render escaped in text; Unicode bytes are stored without normalization.

### Target availability

`available`, `absent`, `server_unreachable`, `different_server`, `server_instance_changed`, `block_host_changed`, `unknown`, `not_checked`, `available_unverified_instance`, `no_target_recorded`. A different invocation host produces no Rex call. Restarted-server identity never falls back to matching labels or recovery remaps. Only fully verified `available` permits navigation. Resume always reports availability as data and exits zero; it grants no authority, restores no draft, resumes no harness, and reports `writes_performed:0`.

### Bounds and exits

4096 records; record JSON 1 MiB; 256 evidence refs (64 copied packets); copied packet 1 MiB; generic file/full output stream 64 MiB; fields-file 64 KiB; 128 claims/checks/omissions; 64 cleanup/history entries; text 4096 UTF-8 bytes (notes 16 KiB); labels 128 bytes. Caps refuse, never truncate, except the explicitly reported 256-name untracked Git list. Fields-file/stdin has a 10-second deadline. Live calls use `--timeout-ms 100..60000` (default 5000) per bounded request. The supervised outer ceiling is 15 minutes, stdout 64 MiB, subprocess diagnostics bounded and never echoed into records.

| Exit | Meaning |
|---|---|
| 0 | Verified write, completed read/export, or availability reported by resume. |
| 1 | Refusal/operational failure, including store busy/hazard, stale generation, missing record, unsupported evidence, privacy or secret scan. |
| 2 | Usage/schema conflict or missing required CLI input. |
| 3 | Lint/rule refusal, or unavailable navigation target. |
| 124 / 130 / 143 | Deadline / interrupt / termination. No success claim. |

## Verification and security boundary

`python3 items/records/test_records.py -v` exercises R1–R24 plus C1–C10 when `REX_BIN` selects a disposable API13 server. The foreign-UID hazard subcase explicitly skips without root; no other hazard is skipped. CI runs the suite in Linux and Mac API13 lanes. Tests isolate HOME, call logs, store and server state, plant question/notes canaries, and compare store metadata and neighbouring-pane input before/after repeated reads. Fixtures are synthetic; actual packets and records are private and never committed.

The new surface is a local UID-owned CLI/filesystem store. Its risks are following hostile files, losing concurrent updates, mistaking historical or supplied claims for authority, leaking private reasoning, and falsely promoting exit zero. Invariants: no path-hazard reads, no unlocked record writes, no reasoning in write receipts/errors/call logs, no inferred assertion, no mutation on resume, no navigation without explicit focus and verified identity. There is no new listener, credential, provider, service, schedule or deployment mechanism. Writer/source names are assertions, never credentials. Personal-store and installed-artifact checks are separate integration work.

Live run-result fixtures use the test runner’s `sys.executable` for explicit zero/nonzero exits on Linux and macOS; they do not assume `/bin/true` or `/bin/false` exists.

## Decision applicability (H06)

`records new --kind decision` creates an open proposal in the same private store.
`records pin add --id ID --by NAME --type git_ref|file_sha256|program_version|gh_issue_state|supplied --target TEXT [--value TEXT] [--gh ABS]`
records one of at most 64 pins. Git targets use `/absolute/repo@ref`; file and program targets are absolute; issues use `owner/repo#N` and an explicit `--gh` executable. Programs run with `--version`, a five second deadline and a bounded first line. Supplying `--value` records attribution without probing. Pins never expire.

`records add claim … --depends-on p1,e2 --contradicts k2 --supersedes k1`
adds dependency links and symmetric contradictions. New claims are provisional. Referenced claim text and basis become immutable; add a superseding claim instead.
`records claim-status --id ID --claim kN --status accepted|withdrawn --by NAME --reason TEXT --expect-generation N`
is the only command that accepts or withdraws a claim, preserving its status history.

`records decide --id ID --by NAME --expect-generation N --fields-file ABS|-`
accepts a strict object with `decision` (`text`, `decided_by`, `authority`, `authority_ref`, `decided_at`), `because` claim IDs, `options`, `invalidators`, and nullable `card_id`.
Authority is `operator_standing|operator|agent_rubric`; its reference names attached evidence.
Options have `oN` IDs, label, `chosen|rejected` status, why, optional `revisit_text` and `revisit_when` conditions (`{"pin":"p1","becomes":"VALUE"}` or `{"pin":"p1","changes":true}`). Invalidators have `vN` IDs, text, and optionally a pin with condition `"changes"` or `{"becomes":"VALUE"}`. Text-only conditions remain manual.
A concluded decision freezes its text and because links; `new --supersedes OLD` replaces it.

`records revalidate (--id ID|--all --kind decision) [--network --gh ABS] [--write]`
reports recorded/current pin values, evidence availability, per-claim results, `needs_review` reasons and rejected options whose complete pinned condition is due. Without `--write`, record bytes and generation remain unchanged. With it, last results are stored and only claims depending on changed pins or missing/changed evidence become stale. Unavailable dependencies report unverifiable; issue pins without network and supplied pins remain not rechecked. Nothing accepts a claim, expires one, chooses an option, or changes the record state.

`records set --id ID --expect-generation N --by NAME 'kind_fields.options.o2.status="chosen"'`
requires the last stored revalidation to list that rejected option as due. An explicit `--override-reason TEXT --by NAME` records an override. Both paths append option history. Whole-option replacement cannot bypass this guard.
`records list --kind decision --needs-review` filters the last stored result.
`show --format text` starts with decision, authority, state and review reasons, preserves provisional caveats and shows open contradiction pairs.

Lint adds L9 decision shape (because claims, rejected alternative with why and invalidators), L10 unresolved contradictions on concluded because claims, L11 changed protected claim text/basis, and L12 dangling dependencies. Close and export retain the existing lint gate. Decision records allow explicit applicability/status updates after conclusion. `attach` additionally accepts H02 `friction_report` packets. Export preserves decision reasoning, statuses, revisit conditions and public pin values; mark `pins` or `pins[].target|recorded_value|last_value` private when needed. The existing secret scan also covers decision text and revisit text.

`python3 items/records/test_decisions.py -v` runs D1–D15 with temporary Git, program-version and fake-gh fixtures, alongside the original records suite in API13 CI lanes. No real issue, store or configuration is changed.
