# H02 + H06 — friction from the call log, decisions in `teerex records` (implementation spec)

**H02: build `teerex boards friction`. It is an opt-in sidecar to the #13 call log, and it reports which repeated teerex call sequences justify a verb.** While consent is active, the same hook that writes the #13 line also writes one *shape* line. A shape line holds the verb, the allowlisted flag names, keyed hashes of the directory and repo, and the caller. It never holds a value, argv text, message, brief or environment value: those are excluded when the line is collected, not redacted afterwards. A read-only `report` groups calls into episodes and counts each sequence once per episode, only within one context. Each candidate is labelled `verb_candidate`, `existing_issue`, `defect` or `refuse_automation`. The report never generates or runs a script.

**H06: add a `decision` kind, pins and `records revalidate` to H01's `teerex records` leaf.** It adds no new store. A decision names the claims it rests on, the rejected options, the condition for revisiting each one, and its invalidators. Pins record the environment facts that claims depend on: a Git ref, a file digest, a program version or an issue state. Revalidation marks stale only the claims whose own pins or evidence changed. It reports `revisit_due` only when a rejected option's recorded condition holds, and it never promotes, decides or expires anything. Tonight's roadmap decisions go in the hive store `~/.local/state/teerex-records`. Canonical docs link record ids, and Circadian stays untouched.

- **Status:** chosen under Josh's overnight standing authority (the seat's overnight file of 2026-11-13: build every roadmap item; decide by 10X developer/agentic/user experience). It supersedes the brief's "defer collection" gate. Choices made here are marked **chosen (overnight rubric)**. This is a spec only. No source was edited and no Git write was run.
- **Implementer:** the teerex lead, in `jcbbge/teerex`, for everything in teerex. The agent-core native owner does the [agent-core lines](#agent-core-changes-owner-agent-core-native). rexconfig has nothing to do.
- **Base read:** `244d893c2131c94778b49038910815c5fc2b04a5`. Public main is now `1bbb9dc`, which touches `items/{agents,boards,send}` but does not add #13.
- **Dependencies (externally owned, consumed, not redesigned):** issue #13 "Record every teerex call" is briefed to the teerex lead's `codex-boards` worker (`feat/boards-ask-log`) and not yet built. H01 `teerex records` ([evidence-records.md](evidence-records.md)) is accepted; names here are aligned with it.
- **Host-blocked:** none. Both parts are local file work plus read-only probes. #13's bypass marking is #13's own concern.
- **Acceptance cases below are specified but not executed.**

## Origins (preserved IDs and locators)

H02: Phase 1 #2, A03–A05, P1:pp2–3. H06: Phase 2 #3/#5 and ledger, B06/B07/B10/B11/B17, P1:pp8–9,11. Briefs: [H02](../teerex-delegation-briefs.md#h02--opt-in-friction-instrumentation) and [H06](../teerex-delegation-briefs.md#h06--causal-decisions-knowledge-view-and-counterfactual-ledger). Roadmap placement: [current phased plan](../../roadmap.md#current-phased-plan--13-november-2026), Phase 1/2 disposition table.

## Chosen decisions (formerly missing)

| Decision | Chosen | Why (rubric) |
| --- | --- | --- |
| H02 data source | the #13 call log plus an opt-in sidecar in the same directory, written by the same hook | Josh asked for #13. A second collector would duplicate it, and a shell hook would see far more than teerex calls. |
| H02 workflow | teerex calls themselves, including those made by the agent-core stopgaps `agent-send`, `agent-read`, `agent-spawn`, `agent-ask` and `teerex-target` (marked with `TEEREX_CALLER`) | This is where agents feel the friction tonight, and the stopgaps being retired show which verbs are still missing. |
| H02 home | `teerex boards friction` in `items/boards`, next to #13's `boards calls` view | One leaf owns the call log and its views. No new verb root. |
| Consent | explicit `enable --for-days 1..30 --scope`; first window on hive is 7 days for all callers, enabled at the live check | Collection that is bounded and visible, with a one-command off. **chosen (overnight rubric)**; see [Not done](#what-the-coordinator-should-know). |
| H06 store | H01's `teerex records`, new kind `decision` plus a small envelope delta | H01 owns the envelope. H06 owns only the interpretation and applicability rules. |
| H06 workflow | tonight's roadmap/planning decisions: the "Chosen decisions" tables in each workload spec and the coordination ledger events | These are being made right now, with dated evidence that will go stale. |
| Where decision records live | hive: `~/.local/state/teerex-records` (H01 estate store). Shared only through `records export`. Roadmap/spec docs cite the record id | One source of truth. Circadian is memory, not a ledger: it decays and sinks atoms, which is exactly the "silent certification" H06 must avoid. |

## Part A — H02 `teerex boards friction`

### What #13 must provide (dependency; the #13 owner decides the final names)

H02 reads #13's line as written. It relies on these fields: `ts`, `host`, `version`, `verb`, `subverb`, `target{server,session_id,block_id}`, `outcome`, `failure_reason`, `exit`, `elapsed_ms`, `caller{agent_name,pid,parent_comm}`, which are #13's own list. It asks for **two small additions** in the same hook. If #13 lands without them, the teerex lead adds them in the H02 change:

1. `call_id`: 32 lowercase hex from the OS RNG, unique per invocation. The friction line joins on it.
2. `caller.via`: the value of env `TEEREX_CALLER` when it matches `^[a-z0-9][a-z0-9._-]{0,63}$`, otherwise `null`, with `caller.via_invalid: true` if it was set but rejected. This is a name only. The parent's command line is **never** read, because a wrapper's argv carries the message.

`<LOG_DIR>` below means #13's log directory, wherever #13 puts it (0700). The friction files live inside it.

### Files and owners

| Path | Owner | Change |
| --- | --- | --- |
| `src/calllog.zig` (or wherever #13's hook lives) | teerex lead | after writing the #13 line, if consent applies, write one friction line ([collection](#collection-what-is-kept-and-what-never-is)) |
| `src/flagnames.zig` | teerex lead | new; compiled allowlist of teerex flag names (every `--name` any leaf declares) |
| `items/boards/boards.py` | teerex lead | new operation group `friction enable|disable|status|forget|label|report` |
| `items/boards/test_friction.py` | teerex lead | new; cases F1–F14 |
| `items/boards/fixtures/friction/*.jsonl` | teerex lead | new; synthetic call/friction logs |
| `items/boards/README.md` | teerex lead | new section "Friction (opt-in)" |
| `.github/workflows/ci.yml` | teerex lead with the CI owner | run `test_friction.py`, and a flag-allowlist completeness check (each leaf's `--help` flags ⊆ `flagnames.zig`) on the Linux and Mac lanes |
| `primitives/tools/agent-messaging/{agent-send,agent-read,agent-spawn,agent-ask,teerex-target}` | agent-core native | `export TEEREX_CALLER=<script name>` before calling teerex. This is deleted together with each script when it retires |

### Consent, disable, delete

All of these take `--log-dir ABS` (explicit, no env fallback) and refuse unless the directory exists at 0700 and is owned by the user. Exit codes follow boards: **0** ok, **1** refusal (`{"ok":false,"failure_reason":…}` on stderr), **2** usage, **130/143** signals.

| Command | Effect |
| --- | --- |
| `boards friction enable --log-dir D --for-days N --scope all\|callers:a,b [--by NAME]` | `N` must be 1–30. Writes `D/friction-consent.json` (0600) `{schema_version:1, enabled_at, expires_at, scope, enabled_by}` and `D/friction-salt` (0600, 32 random bytes) if absent. Refuses `consent_exists` if one is active; extend by disable + enable. |
| `boards friction disable --log-dir D` | Removes the consent file. The hook stops at the next call. Data stays until `forget`. Idempotent: it reports `was_enabled: false`. |
| `boards friction status --log-dir D` | `{enabled, expires_at, scope, lines, bytes, oldest_ts, newest_ts, salt_present, labels}`. |
| `boards friction forget --log-dir D (--all \| --before TS \| --caller NAME) [--yes]` | Without `--yes`, it prints the line count it would remove and exits 0, writing nothing. With `--yes`, it rewrites `friction.jsonl*` through `.next` + fsync + rename. `--all` also deletes `friction-salt` and the labels, so old keys can no longer be linked. **The #13 log is never touched**; its retention is #13's. |
| `boards friction label --log-dir D --path ABS --name NAME` | Stores `{key → NAME}` in the consent file, so the report can name a repo or directory. It requires active consent, and NAME matches the record-id pattern. Josh chooses what gets named. |

The hook writes nothing if the consent file is absent, expired, unparseable or out of scope. It never extends or renews consent itself. Expiry is not a schedule: there is no timer, and the next call simply finds the consent expired.

### Collection: what is kept and what never is

One line per teerex call while consent applies, appended to `D/friction.jsonl` (0600). The file is capped at **4 MiB** and rotates once to `friction.jsonl.1`, so at most 8 MiB is kept; `--help` says so.

```json
{"schema_version":1,"call_id":"9f…32hex","ts":"2026-11-13T09:14:02Z",
 "shape":{"verb":"boards","subverb":"probe","flags":["config","host"],"positionals":0,"other_tokens":0,"stdin":false},
 "context":{"host":"hive","cwd_key":"k:3a9c…16hex","repo_key":"k:77d0…16hex","server_key":"k:c41e…16hex","version":"0.1.0-alpha.5+1bbb9dc"},
 "caller":{"via":"teerex-target","agent_name":"planning-knowledge","episode_key":"k:5be2…16hex"}}
```

Rules, applied **at collection** in the hook (nothing goes to disk first to be filtered later):

- `flags`: only tokens of the form `--name` or `--name=…` whose `name` is in `flagnames.zig`. Only the name is kept, deduplicated and sorted. A value is never read into the record, including the `=…` part and the token after the flag.
- Every other token (positionals, unknown `--x`, values) contributes only to the counts `positionals` and `other_tokens`. Their text is never stored.
- `stdin`: whether stdin is a pipe or file. Its contents are never read by the hook.
- `cwd_key`, `repo_key`, `server_key`: `"k:" + first 16 hex of HMAC-SHA256(salt, value)`. The values are `realpath(cwd)`, the nearest ancestor containing `.git` (found by stat only; no `git` exec) or `null`, and the resolved target server URI. Without the salt they cannot be linked across `forget --all`.
- `episode_key`: HMAC of `agent_name + "\0" + (AGENT_PANE | REX_BLOCK | LC_REX_BLOCK | "")`.
- **Never collected:** argv text, flag values, message/brief/card text, stdin, environment values other than the three names above, shell history, keystrokes, screen content, parent command lines, file contents.
- The hook's own failure (disk full, lock busy) never changes the teerex command's exit or output. It sets `friction_write: "failed"` in the #13 line and continues.

### `boards friction report`

`boards friction report --log-dir D [--since TS] [--min-episodes K] [--gap-s S] [--json]` (defaults K=3, S=300) is read-only. It also accepts the named-host form `teerex --config C --host H boards friction report …` and runs on that host, against that host's log only. Comparing across hosts is done by the reader, never by merging logs.

Algorithm (exact):

1. **Join.** Each friction line is joined to its #13 line by `call_id`. Outcome, `failure_reason`, `exit` and `elapsed_ms` come from #13. Unjoined lines are counted as `unmatched` and excluded.
2. **Step token.** `verb[.subverb](flags…)=class`, where class is `ok`, `refused:<failure_reason>`, `uncertain` or `usage`.
3. **Episodes.** Calls are grouped by `episode_key` and split wherever consecutive calls are more than S seconds apart.
4. **Context key.** `(host, repo_key ?? cwd_key, server_key, version)`.
5. **Candidates.** Every contiguous run of 2–6 step tokens inside an episode. Support is the number of **distinct episodes** that contain it within **one context key**. Repeats inside a single episode count once, because a loop in one script is not a repeated workflow. Keep runs with support ≥ K. Drop a run that is contained in a longer kept run with equal support.
6. **Similar-not-same.** If the same token run reaches K only when context keys are pooled, it is listed under `similar_not_same` with the context fields that differ. It is never counted as a candidate.
7. **Classification**, first match wins:
   - `refuse_automation:retry_of_uncertain`: the run contains `X=uncertain` and later a mutating `X` again. Mutating verbs are `send`, `spawn`, `agents.launch`, `agents.deliver`, `surfaces.open`, `surfaces.close`, `ask`, `boards.ask`, `inbox.append`, `recovery.restore`, `fleet.install`. Automating it would retry uncertain input.
   - `refuse_automation:operator_authority`: the run contains `ask`/`boards.ask` with `resolve`, `recovery.restore`, `fleet.install`, `fleet.rollback`, `surfaces.close` or `agents.stop`. These are decisions or destructive acts and must not be chained.
   - `defect`: every occurrence ends in the same `refused:<reason>`. That is a bug to route to the owner of the reason, not a verb to wrap.
   - `existing_issue:#N`: the run matches a row of the static issue map below.
   - `verb_candidate`: anything else.
8. **Estimate.** For each candidate: the median over occurrences of (sum of `elapsed_ms`) and of (sum of the gaps between steps), and the count of refusals inside. Output `plausible_saving_s` = the median sum of inter-step gaps, labelled `"estimate_basis":"inferred: inter-step gaps only; occurrence counts are not measured benefit"`.

Static issue map in `boards.py`, edited when issues close:

| Token run (flags ignored) | caller.via | Maps to |
| --- | --- | --- |
| `boards.probe` → `boards.probe` → `targets.resolve` | `teerex-target` | #2 label/suffix lookup, #23 find-or-create session |
| `boards.probe` → `targets.resolve` → `agents.launch` | `agent-spawn` | #14 cross-host launch (refused caller host) |
| `boards.probe` → `targets.resolve` → `send` | `agent-send` | #2 |

`--json` output:

```json
{"schema_version":1,"kind":"friction_report","host":"hive","window":{"from":"…","to":"…"},
 "consent":{"enabled":true,"expires_at":"…"},"calls":412,"unmatched":0,"episodes":57,
 "candidates":[{"run":["observe(block,max-bytes,session)=ok"],"support":9,"context":{"repo_label":null,"host":"hive"},
   "callers":["agent-read"],"class":"verb_candidate","median_elapsed_ms":180,"plausible_saving_s":0.0,
   "estimate_basis":"inferred: …","suggestion_text":"agent-read wraps observe only to extract capture text"}],
 "similar_not_same":[…],"refused":[…],"defects":[…]}
```

`suggestion_text` is a fixed template filled with token names. It is never generated code. The text mode prints the same rows in this order: verb candidates, existing issues, defects, refusals, similar-not-same.

**What the report is for:** an agent or Josh reads it and, if a candidate is worth a verb, files or updates a teerex issue, or records a [decision](#part-b--h06-decision-records-on-teerex-records) citing the saved report as evidence (`records attach` accepts it once `friction_report` is added to H01's packet kinds; see the [envelope delta](#envelope-delta-for-the-h01-owner)). Nothing is executed or proposed automatically.

### H02 acceptance (`items/boards/test_friction.py`, runnable; not yet executed)

All cases use synthetic #13 and friction fixtures in a temp 0700 directory. The hook cases run the built binary against a disposable Rex server or against verbs that need no Rex (`boards friction status`, `targets resolve` with a fixture config).

| # | Case | Expected |
| --- | --- | --- |
| F1 | no consent, run 3 verbs | #13 lines appear (#13's test). `friction.jsonl` absent. |
| F2 | `enable --for-days 0`, `31`; `--scope callers:` (empty) | exit 2 / 1 `invalid_days` / 1 `invalid_scope`. No consent file. |
| F3 | enable, run `send --message-file - …` with stdin `token=SYNTHETICTOKEN0000000000` and `--from agent-x`, plus a positional `--hunter2-not-a-flag` | the friction line has `flags` ⊆ allowlist, contains neither `SYNTHETICTOKEN` nor `agent-x` as a value nor `hunter2`, and has `other_tokens ≥ 1`, `stdin: true`. `grep -r SYNTHETICTOKEN D` finds nothing, which is exclusion at collection. |
| F4 | `TEEREX_CALLER='agent-send; rm -rf /'` | `caller.via: null`, `via_invalid: true`. The command result is unchanged. |
| F5 | **meaningful repeat**: 3 episodes, same context, each `boards.probe → targets.resolve → send` via `agent-send` | one candidate, support 3, class `existing_issue:#2`. |
| F6 | **counterexample, superficially similar**: the same run in 3 episodes but in 3 different `repo_key`s (or 2 hosts) | no candidate. One `similar_not_same` row naming `repo_key` (or `host`) as the difference. |
| F7 | **counterexample, loop in one episode**: one episode repeats `observe → observe` 40 times | support 1, no candidate. |
| F8 | **must not yield automation**: 4 episodes of `send=uncertain → observe=ok → send=ok` | class `refuse_automation:retry_of_uncertain`, with no `suggestion_text`. |
| F9 | 3 episodes containing `boards.ask(resolve,…)=ok → send=ok` | `refuse_automation:operator_authority`. |
| F10 | 3 episodes where `inbox.append=refused:capacity` | class `defect`, naming `capacity`. |
| F11 | 3 episodes of `observe(block,max-bytes,session)=ok` via `agent-read`, plus a 2-step run inside them | one `verb_candidate` with the maximal run only. `estimate_basis` starts `inferred:`. |
| F12 | expiry: consent with `expires_at` in the past (fixture clock) | the hook writes nothing; `status` shows `enabled:false`, `expired:true`. |
| F13 | `disable`, run a verb; then `forget --all` without `--yes`, then with `--yes` | no new line after disable. The dry run prints the count and changes nothing. After `--yes`: friction files and salt gone, #13 log byte-identical. |
| F14 | hook failure: make `friction.jsonl` read-only | the teerex verb exits as without consent. The #13 line carries `friction_write:"failed"`. |
| F15 | allowlist completeness (CI) | every `--flag` in every leaf's `--help` is in `flagnames.zig`. A new flag without an allowlist entry fails CI, so a new flag is never silently reduced to `other_tokens`. |

**Live check after install (hive):** `enable --for-days 7 --scope all --by seat`. Run `agent-read` once and `agent-send` once to a scratch pane. `report --json` shows both calls joined, with `caller.via` set, and `grep` for the message text in `<LOG_DIR>` finds nothing.

## Part B — H06 decision records on `teerex records`

### Envelope delta for the H01 owner

These are additive and optional for the existing kinds. H01's fields and rules are unchanged. Command and flag names here are aligned with the accepted [H01 spec](evidence-records.md) (`--expect-generation`, `--fields-file`, `--by`, `attach`, `close`, `superseded_by:<id>`); where they differ, H01 wins.

- Top-level `pins[]`: `{"id":"p1","type":"git_ref|file_sha256|program_version|gh_issue_state|supplied","target":"…","recorded_value":"…","recorded_at":"…","basis":"observed|supplied","last_value":null,"last_checked":null,"last_result":"unchecked"}`. Targets: `git_ref` → `"/abs/repo@refname"`; `file_sha256` → abs path; `program_version` → abs program path (run `PROG --version`, 5 s, first line ≤256 bytes); `gh_issue_state` → `"owner/repo#N"` (value `OPEN`, or `CLOSED:<STATEREASON>`); `supplied` → free text, never probed.
- Claim fields: `status` (`provisional` default \| `accepted` \| `stale` \| `withdrawn`), `depends_on` (pin and evidence ids), `contradicts` (claim ids), `supersedes` (claim id or null), `status_history[]` `{status, at, by, reason}`.
- Element id prefix `p` for pins, never reused. Cap: 64 pins per record.
- New packet kind accepted by `records attach`: `friction_report` (H02).

### Kind `decision`: `kind_fields`

```json
{"decision":{"text":"H02 builds on the #13 call log, not a separate collector","decided_by":"teerex planning","authority":"operator_standing|operator|agent_rubric","authority_ref":"e1","decided_at":"2026-11-13T09:30:00Z"},
 "because":["k1","k2"],
 "options":[
   {"id":"o1","label":"Sidecar to #13 log","status":"chosen","why":"one collector, Josh asked for #13"},
   {"id":"o2","label":"Per-script shell wrapper log","status":"rejected","why":"duplicates #13; scripts are retiring",
    "revisit_when":[{"pin":"p1","becomes":"CLOSED:NOT_PLANNED"}],"revisit_text":"if #13 is dropped"}],
 "invalidators":[{"id":"v1","text":"#13 ships without a per-call id","pin":"p2","condition":"changes"}],
 "card_id":null}
```

Record `state` keeps H01's meaning: `open` is proposed, `concluded` is decided, and `superseded_by:<id>` (set by `records new --supersedes OLD`) is replaced by a newer decision. "needs review" is **computed** by `revalidate` and never stored as a state.

### Commands (added to `records`)

| Command | Effect |
| --- | --- |
| `records pin add --id ID --by NAME --type T --target X [--value V] [--gh ABS] [--expect-generation N]` | `observed` types probe now and store `recorded_value`. With `--value`, `basis: supplied`, no probe. `gh_issue_state` needs `--gh ABS` (explicit binary). A probe failure refuses `pin_probe_failed`. |
| `records decide --id ID --by NAME --expect-generation G --fields-file ABS\|-` | Sets the decision's `kind_fields` from strict JSON (the shape above). Refuses unknown keys, option or invalidator ids not matching `o\d+`/`v\d+`, and dangling pins (`unknown_pin`). Once `state` is `concluded`, changing `decision.text` or `because` refuses; supersede the record instead. |
| `records add claim … [--depends-on p1,e2] [--contradicts k2] [--supersedes k1]` | Extends H01's `add claim`. `--contradicts` writes the link on **both** claims. Neither text is changed. |
| `records claim-status --id ID --claim kN --status accepted\|withdrawn --by NAME --reason T --expect-generation G` | The only way a claim becomes `accepted` or `withdrawn`. It appends to `status_history`. Nothing sets `accepted` automatically. |
| `records revalidate (--id ID \| --all --kind decision) [--network --gh ABS] [--write]` | Probes every pin (`gh_issue_state` only with `--network`, otherwise `not_rechecked`) and recomputes each evidence entry's `availability_now` as H01's `show` does (H01 dropped its `recheck` verb). It computes the [results](#revalidation-rules-exact). Without `--write` it is read-only. With `--write` it stores `last_value`/`last_checked`/`last_result` and moves claims to `stale` with a `status_history` entry. It never changes `state`, decision text, options or `accepted`. |
| `records set --id ID … kind_fields.options.oN.status="chosen"` | Refused with `revisit_not_due` unless the latest stored revalidation listed `oN` as `revisit_due`, or `--override-reason T --by NAME` is given (the override is appended to the option's `history[]` `{status, at, by, reason}`). |
| `records show --id ID` (decision) | Order: decision text · authority · state · **needs_review yes/no and why** · because claims (status, basis, pins with recorded vs last value) · open contradictions as `k2 ⟷ k5` pairs · options (chosen first, rejected with revisit condition and `revisit_due`) · invalidators · evidence availability. |
| `records list --kind decision [--needs-review]` | `--needs-review` filters on the last stored revalidation. |

New failure reasons: `pin_probe_failed`, `revisit_not_due`, `claim_text_immutable`, `unknown_pin`. Exit codes are H01's.

### Revalidation rules (exact)

1. **Pin result:** `unchanged` (same value) · `changed` (different value; both kept) · `unavailable` (probe failed: repo gone, program missing, `gh` error) · `not_rechecked` (`supplied`, or `gh_issue_state` without `--network`).
2. **Claim result:** `stale` iff any id in `depends_on` is a `changed` pin, or evidence that is `missing`/`deleted`/`digest_mismatch`. `unverifiable` iff none changed but any is `unavailable`. Otherwise its stored status stays as it is. **A claim with no dependency on the changed pin is not touched.** This is how a changed version invalidates only the claims that depend on it.
3. **Decision `needs_review`:** any `because` claim is `stale`/`unverifiable`/`withdrawn`, or any invalidator holds (`condition: "changes"` → its pin `changed`; `{"becomes":V}` → `last_value == V`; `text`-only invalidators are listed as `manual`, never evaluated).
4. **`revisit_due`:** a rejected option is due iff **every** entry in its `revisit_when` holds now (`becomes: V` or `changes`). An option with no pinned condition is never due; it is shown as "revisit: manual".
5. **No expiry:** no field, age or TTL ever makes a claim stale or accepted. An `unchanged` result is a report, not a certificate.

### Lint additions (H01's `records lint`)

| Rule | Violation when |
| --- | --- |
| `L9-decision-shape` | kind `decision` lacks `decision.text`/`decided_by`/`authority`/`authority_ref`; has 0 `because` claims; has no option with `status: rejected`; a rejected option has no `why`; or there are 0 invalidators |
| `L10-open-contradiction` | `state` is `concluded` and a `because` claim has a `contradicts` partner where neither is `withdrawn`, unless `uncertainty.text` names both claim ids |
| `L11-claim-immutable` | (enforced on `set`, reported by lint for imported files) a claim referenced by `because`, `contradicts` or `supersedes` had its `text`/`basis` changed. `set` refuses `claim_text_immutable`; write a new claim `--supersedes kN` instead |
| `L12-dangling-dependency` | `depends_on`, `revisit_when.pin` or `invalidators.pin` names an unknown pin or evidence id |

A concluded decision whose `because` claims are all `provisional` is **not** a violation. `show` prints `decided on provisional claims` above the claims. A claim that nobody has resolved stays provisional and visible as such.

### Where the records live, and what else touches them

- **Store:** hive `~/.local/state/teerex-records` (created by H01's live check). Record ids `dec-<workload>-<slug>`, for example `dec-h02-on-13`.
- **Canonical docs:** roadmap and workload specs keep their "Chosen decisions" tables as the reader's view and add a `Record` column with the id. The record holds the evidence, the rejected options and when to revisit them. The table never copies them.
- **Decision cards:** when a decision came from a typed card ([boards ask](../../../items/boards/README.md#decisions-typed-into-the-pane)), `card_id` holds the card id, and the resolution answer is attached as evidence `type: board_card`, `supplied_by: operator`. A card answer is `supplied`, not `observed`.
- **Circadian** (Josh's private memory repo on hive): unchanged and read-only. Its beliefs are weighted, decaying atoms with supersede edges (its private MIND-SPEC). That memory shape must not become the decision of record. A session may remember "decision X is record dec-…", the pointer only, under the existing memory rule "store decisions and why".
- **agent-core report contract:** a decision settled during work is reported in the delta with its record id. See the agent-core lines below.

### Migration from existing notes (manual, no importer)

The coordinator records tonight's decisions by hand, one `records new --kind decision` per row of each accepted workload spec's "Chosen decisions" table and per ledger event that decided something. The first batch is the coordination ledger's overnight event (void defers), Q03 approval, H01 destination and this spec's H02 source. Each gets at least one pin (the teerex main ref or the relevant issue state) and the overnight file as `authority_ref` evidence (`type: file`, private). There is no bulk importer: Markdown tables do not carry rejected options or conditions, and inventing them would fabricate them.

### Worked example (synthetic paths; the decision is this spec's own)

```sh
S=~/.local/state/teerex-records
teerex records new --store $S --kind decision --id dec-h02-on-13 --writer "teerex planning" \
  --question "Where does H02 friction data come from?" \
  --next-actor "teerex lead" --next-step "build boards friction after #13 lands" --next-stop-when "F1-F15 green"
teerex records attach --store $S --id dec-h02-on-13 --by "teerex planning" --evidence /abs/overnight.md --label authority  # e1, type file, private
teerex records pin add --store $S --id dec-h02-on-13 --by "teerex planning" --type gh_issue_state --target jcbbge/teerex#13 --gh /usr/bin/gh   # p1 = OPEN
teerex records pin add --store $S --id dec-h02-on-13 --by "teerex planning" --type git_ref --target /abs/teerex@refs/remotes/origin/main  # p2
teerex records add claim --store $S --id dec-h02-on-13 --by "teerex planning" --text "#13 is briefed to codex-boards" --basis supplied \
  --supplied-by "teerex lead brief" --depends-on p1                                                              # k1
teerex records add claim --store $S --id dec-h02-on-13 --by "teerex planning" --text "No call log exists in source" --basis observed \
  --evidence e2 --depends-on p2                                                                                  # k2
teerex records decide --store $S --id dec-h02-on-13 --by "teerex planning" --expect-generation 7 --fields-file /abs/dec-h02-kind.json   # the kind_fields JSON above
teerex records close --store $S --id dec-h02-on-13 --by "teerex planning" --state concluded --expect-generation 8
teerex records revalidate --store $S --id dec-h02-on-13 --network --gh /usr/bin/gh
```

When #13 lands, `p2` changes, so `k2` goes stale and `needs_review` turns on with reason "k2 stale (p2 changed)". That is correct: "no call log exists" is no longer true. `k1` and the decision text are untouched. Option `o2` becomes `revisit_due` only if `p1` reads `CLOSED:NOT_PLANNED`.

### H06 acceptance (`items/records/test_decisions.py`, runnable; not yet executed)

Fixtures: a temp Git repo, a fixture program `ver.sh` that prints `teerex 0.1.0-alpha.5`, and a fake `gh` script whose output is a fixture file.

| # | Case | Expected |
| --- | --- | --- |
| D1 | **changed version invalidates only dependents**: k1 depends on p1 (program_version), k2 depends on p2 (git_ref). Change `ver.sh` to alpha.6, `revalidate --write` | p1 `changed` (old and new values kept), k1 `stale`, k2 status unchanged, `needs_review` reason names only k1. |
| D2 | counterexample: change an **unrelated** file in the repo (not the pinned ref) | everything `unchanged`; `needs_review: false`. |
| D3 | **contradictory evidence stays navigable**: k3 observed (e3) "send succeeded"; add k4 observed (e4) "pane shows no message" `--contradicts k3` | both claims present, each lists the other. `show` prints `k3 ⟷ k4`. `set claims.k3.text=…` refuses `claim_text_immutable`. |
| D4 | conclude a decision resting on k3 with the contradiction open | `lint` exit 3 `L10-open-contradiction`. `claim-status --claim k3 --status withdrawn --reason …` clears it, and `status_history` keeps both entries. |
| D5 | **unresolved claim stays provisional**: decision concluded on an inferred claim; revalidate 3× with nothing changed | the claim is still `provisional`. No command except `claim-status` produced `accepted`. `show` says `decided on provisional claims`. |
| D6 | **revisit only on its condition**: o2 `revisit_when p1 becomes CLOSED:NOT_PLANNED`; fake gh returns `OPEN` | `revisit_due: []`. `set options.o2.status="chosen"` refuses `revisit_not_due`. |
| D7 | fake gh returns `CLOSED:COMPLETED` | still not due (a different condition). |
| D8 | fake gh returns `CLOSED:NOT_PLANNED` | `revisit_due: ["o2"]`. The same `set` now succeeds and the option history records it. |
| D9 | override without due | `--override-reason "Josh asked" --by operator` succeeds and is recorded. Without `--by`: exit 2. |
| D10 | **deleted evidence is explicit**: delete e3's file | e3 `missing`, k3 `stale`, `needs_review`. Nothing is silently dropped. |
| D11 | `--network` absent | `gh_issue_state` pins are `not_rechecked`. Dependent claims keep their status and are listed as not rechecked. |
| D12 | **no TTL**: set the fixture clock +400 days, revalidate with nothing changed | no status changes. |
| D13 | `revalidate` without `--write` | the record file is byte-identical (generation unchanged). |
| D14 | `L9` counterexample: a decision with no rejected option | `lint` exit 3 `L9-decision-shape`; `set state="concluded"` refused. |
| D15 | export | the md export keeps decision text, options, revisit conditions, pin `recorded_value`/`last_value` for non-private pins, and claim statuses. Private evidence locators are dropped. A planted secret in `revisit_text` refuses `secret_pattern` (H01 rule 3). |

**Live check after install (hive):** record `dec-h02-on-13` as in the worked example against the real `jcbbge/teerex`, then run `revalidate --network`. It shows `p1 OPEN unchanged`. After #13 merges, the coordinator reruns it and sees `k2 stale` and `needs_review` with only that reason.

## agent-core changes (owner: agent-core native)

1. In `primitives/tools/agent-messaging/{agent-send,agent-read,agent-spawn,agent-ask,teerex-target}`, add after the shebang/comment block: `export TEEREX_CALLER=<basename>`. For `teerex-target`, which is sourced, the sourcing script's own export applies, so add nothing to it. The line is removed together with each script.
2. Add to the rex skill (records paragraph from H01):

   > **Decisions.** When you settle a decision that someone could later reasonably reopen, record it with `teerex records new --kind decision` in `~/.local/state/teerex-records`. Include the claims it rests on (`--depends-on` pins for each version, ref or issue state they assume), at least one rejected option with `revisit_when`, and an invalidator. Before acting on an older decision, run `records revalidate --id <id>`. If it says `needs_review`, report that instead of acting on it. Never reopen a rejected option whose condition has not changed; ask the seat if you think it should be.

3. Add to `primitives/rules/report-contract/RULE.md` under "Decisions owed", last line:

   > A decision you settled goes in the delta with its `teerex records` id. A decision you need goes here.

## Sequencing

1. #13 lands with `call_id` and `caller.via` (teerex lead / `codex-boards`). H02 cannot start before then.
2. The H02 hook sidecar, `flagnames.zig` and `boards friction` (teerex lead). In parallel, the agent-core native owner adds the `TEEREX_CALLER` exports, which are harmless before H02.
3. H01 `records` lands (teerex lead). Then the H06 delta goes onto `items/records` and is tested with D1–D15.
4. Install on hive and the M5. The H02 live check enables the 7-day window on hive. The coordinator records tonight's decisions (migration batch) and adds `Record` columns.
5. After the 7-day window, or sooner on request: `boards friction report` goes to the seat as a document. Josh or an agent files issues for `verb_candidate` rows. Consent then lapses unless re-enabled.

## Non-goals (unchanged)

No silent shell history, keystroke or screen logging, parent-argv capture, shell-wide hooks, weekly schedule, universal miner, generated or auto-executed scripts, automatic truth maintenance, TTL certification, retrieval/embedding service, model training, or change to Circadian. No change to #13's own retention, board or bypass behaviour.

## What the coordinator should know

- **Consent window (chosen, overnight rubric):** the live check *enables* friction collection on hive for 7 days for all callers. The overnight authority covers building and installing. Data collection was a named gate in the H02 brief. If the coordinator reads that gate as needing Josh's own yes, skip the `enable` in the live check, and everything else stands. Off is `teerex boards friction disable --log-dir <LOG_DIR>`; erase is `forget --all --yes`.
- **Unresolved inputs:** #13's final field names and log directory, and H01's final field names. Both are owned elsewhere, and this spec maps onto them.
