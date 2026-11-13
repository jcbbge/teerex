# Q02/C31/C32 readiness and failing-CLI baseline: implementation spec

**Build this.** Readiness becomes an evidence-gated, machine-computed catalog property, and the first payloads to earn it are `observe` on Linux x86_64 and on Apple-silicon macOS. Concretely:

- A runner executes the rubric below and writes a readiness record.
- The packager marks a manifest `ready` only when a matching, non-stale record says so, and narrows the advertised Rex API revisions to the evidenced ones.
- A second script runs the safe-subset failing-CLI baseline (C31) and measures it against a plain-Rex reference arm (C32/Q12).
- Phase B adds a real agent arm, counted through PATH shims, so C32's round-trip, interruption and misdirected-input numbers come from observations, not inference.

The work is in the teerex repo: `tools/acceptance/**`, `tools/cartridges/**`, CI, and the docs listed in §8. agent-core gets one rex-skill line. The parts that are truly host-blocked (atomic input and takeover, whole-tree process death, painted-UI confirmation) get the upstream paragraph in §9.

**Authority and labels.** This spec is implementation-ready under Josh's overnight standing authority, read from `~/rivet/work/seat-2026-11-13/overnight-2026-11-13.md`. Every choice marked **chosen** was made with Josh's rubric (10X developer, agentic and user experience) and replaces the earlier "missing decision" items D1–D3. **Observed** facts were read at base `244d893`. Upstream commits through `4282f23` touch only send, agents and boards, not observe, run or cartridges (`git diff --stat 244d893 origin/main`). Builder: the teerex lead (`block:01a1d34f-9a09-7392-b8e8-17046462c623`). This document was not executed; the acceptance cases in §7 are runnable once the files in §8 exist.

## 1. Decisions (all chosen)

| # | Decision | Why (rubric) |
| --- | --- | --- |
| C1 | Judge readiness per cartridge ID and platform, over the cartridge's whole advertised contract (`observe`, `compare`, `watch`, including status OR and `--no-deadline`). Never per subcommand. | Manifests are already per platform (observed, [cartridges.md](../../cartridges.md#manifest-and-dependency-contract)). `ready` then means one thing to every agent. |
| C2 | The first items are **`observe` on x86_64-linux and on aarch64-macos**. Doctor, maneuvers, filter and the others follow, using the same runner and their own contract maps. | Observe is the read-only base that filter, maneuvers, watch-driven agents and the seat all consume. Proving it first gives every later item a trusted observation. |
| C3 | **A ready manifest advertises only the evidenced API revisions.** Linux becomes `[13]`, because that is the only actual Linux build Josh runs or CI pins (hive: Rex `348d751…`, API13; CI: preview.16 `aa2db1b…`, API13). Mac becomes `[10,12,13]` from the CI lanes preview.13, .14 and .16. API11 stays out until a build is run. **Experimental manifests keep their broader list.** | This replaces old D1. An agent reading the manifest is never told it is supported where nothing ran. Nominal support is restored automatically as soon as evidence exists. |
| C4 | Readiness is **computed by the packager from a committed record**, and goes **stale automatically** when any covered source path changes after the record's commit. There is no hand-flipped `status`. | No drift between claim and evidence, and nobody has to remember to downgrade. |
| C5 | The **executor is the machine**. CI lanes, plus a run on hive against a disposable server started from Josh's actual Rex binary, produce the records. The verdict is computed from the rows, never typed in. | This replaces old D2 and satisfies "never grade your own work" without needing a human. |
| C6 | The **C32 reference arm** does the same task with plain `rex` CLI calls (create pane, poll capture and status, read exit). **Phase B adds a real agent arm** on Josh's subscriptions, launched visibly through managed `agents launch`, with counting PATH shims. | This replaces old D3. "Fewer round trips" is measured against what an agent does without teerex, by an actual agent. |
| C7 | The baseline runs on **hive against a private disposable Rex server** started from `~/.local/bin/rex` with its own socket, `--config /dev/null` and `--restore=false`, and in CI on preview.16. **It never touches `rex.service`** or Josh's panes. Phase B's visible agent tab is the only object placed in Josh's real server (§5.2). | It uses his real build without risking his tabs; restarting Rex still waits for him. |

## 2. Readiness record (new file format)

Path: `tools/cartridges/readiness/<id>-<platform>.json`, mode 0644. It is committed, and it contains no private paths, IDs or captures.

```json
{
  "schema_version": 1,
  "kind": "cartridge_readiness",
  "id": "observe",
  "platform": "x86_64-linux",
  "rubric": "docs/planning/workloads/readiness-acceptance.md",
  "rubric_sha256": "<sha256 of the rubric file at execution>",
  "source_commit": "<40-hex>",
  "source_tree_dirty": false,
  "covered_paths": ["items/observe", "src/child.zig", "tools/cartridges/entry.zig", "tools/cartridges/build.zig", "tools/acceptance/contracts/observe.json"],
  "payload_sha256": "<sha256 of teerex-observe built from source_commit>",
  "runs": [
    {
      "executor": "ci:<run URL>" ,
      "rex": {"sha256": "<cli sha256>", "version": "<rex_version>", "commit": "<rex commit>", "api_revision": 13},
      "os": "<uname -sr>", "arch": "x86_64",
      "started_at": "<RFC3339>", "finished_at": "<RFC3339>",
      "rows": {"R1": {"pass": true, "detail": "<short, sanitized>"}, "...": {}}
    }
  ],
  "evidenced_api_revisions": [13],
  "verdict": "ready",
  "failed_rows": []
}
```

**Verdict rule** (computed by `readiness.py`, verified again by the packager):

- `verdict="ready"` if and only if three conditions hold:
  - every row R1–R11 has `pass=true` in every run;
  - each revision in `evidenced_api_revisions` has **at least 3 runs**, each on a fresh server (that is R3);
  - `source_tree_dirty=false`.
- Otherwise `verdict="not_ready"`, with `failed_rows` sorted.
- `evidenced_api_revisions` is the set of `api_revision` values in runs that passed.

`executor` is either `ci:<url>` or `local:<host>:<agent name>`.

**covered_paths rule.** These must be exactly the inputs the payload compiles from, plus its contract map. The lead confirms the list against `tools/cartridges/build.zig -Dcartridge=observe`, and adds any other `src/` file the module imports.

## 3. Packager gate (edit `tools/cartridges/package.py`)

For each recipe, replace the hard-coded `status="experimental"` with the result of `readiness(recipe["id"], args.platform, revision)`:

1. If no record file exists, the result is `experimental`.
2. Load the record and require schema 1, kind, id and platform. Any malformed record makes the build **fail**, with exit 1 and the reason on stderr. A broken claim never ships silently.
3. If `verdict != "ready"`, the result is `experimental`.
4. If `git merge-base --is-ancestor <source_commit> HEAD` fails, or `git diff --quiet <source_commit> HEAD -- <covered_paths…>` is non-empty, the result is `stale`, which ships as `experimental`.
5. Otherwise the result is `ready`. The manifest's `compatibility.rex_api_revisions` becomes `evidenced_api_revisions`. `compatibility.readiness` is set to `{"record": "<path>", "source_commit": "…", "evidenced_api_revisions": [...]}`. Experimental manifests keep the recipe's list and get `compatibility.readiness: null`.

Packager stdout JSON gains `"readiness": {"<id>": "ready|experimental|stale:<first changed path>|absent"}`.

`cartridges.py` needs no change: the existing `--all` already selects `status == "ready"` (observed, line 286), so ready-only `--all` now installs `observe` without `--allow-experimental`. The schema-1 manifest validator must accept the new optional `compatibility.readiness` object. `compatibility` is already a free JSON object, so the lead should verify that and add a unit test.

`tools/cartridges/test_cartridges.py` gains four cases:

| Case | Expected result |
| --- | --- |
| No record | `experimental` |
| Valid ready record at HEAD | `ready`, with narrowed revisions |
| Ready record with a covered file changed after its commit | `stale:` output and an `experimental` manifest |
| Malformed record | Packager exits 1 |

Each case uses a temporary git repo fixture.

## 4. Readiness runner (`tools/acceptance/readiness.py`, new)

```text
python3 tools/acceptance/readiness.py --item observe --catalog ABS --rex ABS \
  --previous-teerex ABS --runs 3 [--long] --out NEW_FILE [--merge EXISTING_RECORD]
```

- `--catalog` is a catalog directory built by `package.py` from a **clean** tree; the runner refuses one with `source_tree_dirty=true`.
- `--rex` is the Rex CLI used to start private servers.
- `--previous-teerex` is the alpha.5 combined binary, used for the schema-compatibility row R4. On hive it is `~/.local/opt/teerex-managed/versions/<alpha.5 dir>/teerex`.
- `--long` adds R9's 60 s RSS wait. It runs once per invocation, not per run.
- `--merge` appends runs to an existing record for another revision or executor, then recomputes the verdict.
- Exit codes: 0 for a `ready` verdict, 1 for `not_ready` or an operational failure (the record is still written if identity was captured), 2 for usage errors.
- The runner writes `NEW_FILE` atomically, as a temp file plus rename. It refuses an existing path unless `--merge` is used.

Each run proceeds as follows:

1. Create a fresh `0700` temp HOME and a private Rex server, exactly as `items/observe/test_observe.py` `setUpClass` does: `server run --listen unix://… --restore=false --config /dev/null --state-dir …`.
2. Install the catalog through the manager into `HOME/cartridges` with `install observe --allow-experimental --apply`.
3. Execute rows R1–R11 (table below) and record each row's pass flag and a sanitized detail: test names, counts and exit codes only.
4. Stop the server (TERM, then KILL after 5 s) and remove the temp HOME.

Neighbouring-pane controls are read before and after each run, in the runner's own fixture session:

| Control | Reading |
| --- | --- |
| N1 | block list |
| N2 | layout rectangles and focus, via `surfaces inspect` |
| N3 | the sentinel pane's complete capture, `program_status` and PID |
| N4 | server PID and `server.version` |
| N5 | an outside sentinel process is alive |
| N6 | a file listing of HOME and the temp root |

**Contract map** (new file, `tools/acceptance/contracts/observe.json`):

```json
{"schema_version": 1, "item": "observe",
 "help_options": {"observe": ["--socket", "--session", "--block", "--max-bytes", "--timeout-ms"], "compare": ["--before", "--after"],
                  "watch": ["--socket", "--session", "--block", "--baseline", "--timeout-ms", "--no-deadline", "--interval-ms", "--status-state", "--status-id"]},
 "claims": [{"id": "observe.explicit-target", "text": "No focus/label/env fallback selects target", "tests": ["ObserveTest.test_explicit_target_and_read_only_result", "ObserveTest.test_wrong_block_is_not_replaced_by_focus"]}]}
```

The lead fills in one claim per bullet and table row of the observe README sections *Contract and limits*, C02, C03 and C09, mapping each to existing test names. These exist today (observed): 8 `CompareTest` and 24 `ObserveTest` methods, such as `test_watch_changed_tail_outside_prefix_stays_unknown` and `test_retained_done_report_is_not_successful_exit`. A claim with no test gets a new test in `items/observe/test_observe.py`, or is removed from the README in the same change.

The help lists above are what I read in the README. The runner parses each subcommand's `--help` output and treats the map's option list as authoritative only after comparing it with that output.

| Row | How the runner executes it | Pass |
| --- | --- | --- |
| R1 contract | Parse `teerex-observe {observe,compare,watch} --help` options and compare them with `help_options`. Run `items/observe/test_observe.py` against the **installed payload**, using the existing `test_payloads.py` argv adapter (`TEEREX_BIN` pointing at an adapter that runs `<code>/teerex-observe "$@"`). Collect per-test outcomes. | The help option sets match exactly; every test named in `claims` ran and passed; no claim is empty. |
| R2 platform/API | Record `server.version.api_revision`. | The revision is an integer in 10–13; it is recorded per run, and the verdict narrows to evidenced revisions (C3). |
| R3 stability | Each of `--runs` N uses a fresh server and HOME, with no retries. | All N runs pass. A test that fails once fails the row; nothing is re-run. |
| R4 schema compat | With the fixture pane, run `--previous-teerex observe …` to produce `old.json`, and the candidate `observe` to produce `new.json`. Then run candidate `compare --before old.json --after new.json`, and candidate `watch --baseline old.json --timeout-ms 500`. | `compare` exits 0 with `kind="observation_changes"`. `watch` exits 124 `deadline_exceeded` or 0 `change_observed`, not 1. An old packet with its `source.api_revision` edited to 9 makes `compare` exit 1 with no stdout. |
| R5 managed lifecycle | Through `cartridges.py --root R run observe -- …`: (a) a live `observe` of the fixture pane gives exit 0 and a complete JSON packet with `kind` and target equal to the request; (b) `compare` gives exit 0; (c) `watch --status-state done --no-deadline`, sent SIGTERM after 300 ms, gives exit 143 with `cancel_requested`; (d) while (c) is running, `remove observe --version V --deactivate --apply` exits 1 with an in-use refusal JSON on stderr; (e) after (c) exits, `remove --deactivate`, `restore` and `activate --apply` each exit 0, and `list` shows observe active. | All five behave exactly as described. |
| R6 read-only | Diff the N1–N6 controls around the whole run. | No delta except the fixture pane's own program output. |
| R7 exit discipline | Covered by the test outcomes for usage, deadline and cancel in R1, plus the runner's own spot checks: unknown subcommand gives exit 2 with empty stdout, and a missing server gives exit 1 with no success JSON. | All as stated. |
| R8 unknown/refusal | R1's `test_missing_target_diagnostics_keep_requested_route_and_watch_unknown`, `test_api_range_preserves_revision_and_refuses_outside_bounds`, `test_file_limits_malformed_packets_and_arguments` and `test_watch_target_source_transport_and_usage_fail_closed`. | They pass. |
| R9 bounds | R1's capture-limit tests. With `--long`: a 60000 ms quiet watch at `--max-bytes 65535 --interval-ms 50`, sampling RSS each second from 5 s onward. | Exit 124. teerex RSS growth between the 10 s and 60 s samples is at most 256 KiB. |
| R10 limits labelled | Check one live packet and one wait result. | `atomic_snapshot=false`, `freshness="unknown"` on every evidence node, `interpretation="none"`, `capture.complete` present, and on watch `all_descendants_verified_gone=false`. |
| R11 privacy | grep the manager's lifecycle stdout/stderr and the runner's own log for the fixture's planted marker `TEEREX_SECRET_CANARY_<random>`. Check the modes of evidence files. | The marker is absent outside the observation packets; packets are 0600 and directories 0700. |

**R12 (independence)** is satisfied structurally. `executor` is CI or a session other than the code's author, and the verdict is computed from the rows. The runner refuses to write `verdict=ready` when `--executor` is missing.

## 5. Failing-CLI baseline (`tools/acceptance/baseline.py` and `tools/acceptance/fail_fixture.py`, new)

### 5.1 Phase A: deterministic arms (teerex versus plain Rex)

```text
python3 tools/acceptance/baseline.py --teerex ABS --rex ABS --out NEW_DIR \
  [--arms teerex,reference] [--modes F1,F2,F3,F4,F5,F6] [--warm-runs 40] [--warmups 2]
```

- Output: `NEW_DIR` (mode 0700) holds `report.json` (0600), `summary.md` (0600, sanitized, safe to share) and `evidence/` (raw receipts and observations, private).
- Exit codes: 0 if B1–B12 all pass, 1 otherwise, 2 for usage errors.
- `--teerex` must be a `run-visible`-capable combined build. Its SHA-256 is recorded.

`fail_fixture.py MODE` is a stdlib Python script. All output is synthetic.

| Mode | Behaviour | Final exit |
| --- | --- | --- |
| F1 | Prints 40 progress lines `step N/40`, a Unicode line `résumé ✓`, then a 6000-byte padding block. Writes `assertion failed: expected 4 got 5` to stderr, and `PASS` to stdout. | 3 |
| F2 | Prints `starting`, sets SIGTERM to ignored, then sleeps 600 s. | Killed |
| F3 | Prints `starting`, then sleeps 600 s with SIGTERM at its default action. | Signal 15 |
| F4 | Identical to F1 except the last two lines are `ok` (stdout) and nothing on stderr. | 0 |
| F5 | Writes `ESC ] 7501 ; state=done … BEL` (the exact OSC 7501 encoding from the [Rex program-status reference](https://www.superlogical.com/rex/docs/build/program-status)), sleeps 2 s. | 1 |
| F6 | Starts `sleep 600` in its own group, and a `setsid sleep 600` whose PID it writes to `$FIXTURE_DIR/detached.pid`. | 3 |

The teerex arm runs these steps for each mode:

1. Run `observe` on the sentinel pane S, saving `S0`.
2. Run `teerex --rex REX run-visible --socket S --session SESSION --layout tiled --anchor S_BLOCK --direction right --ratio 0.3 --cwd FIXTURE_DIR --env-file ENV --stdin-file /dev/null --app c31 --title "c31 F<n>" --timeout-ms 5000 --max-bytes 4096 --output-dir NEW --keep-open -- python3 fail_fixture.py F<n>`. Use `--timeout-ms 2000` for F2. For F3, send SIGTERM to the controller after 1 s.
3. In parallel with step 2: `observe` the created pane, saving `P0`, then `watch --baseline P0 --status-state done --status-state error --timeout-ms 8000`.
4. After return: `observe` again, saving `P1`, and run `compare P0 P1`.
5. Re-run F1 without `--keep-open`, which tests the default close.

The reference arm runs the same F1 and F4 tasks. It uses only `rex --autostart=false --server unix://S --timeout 3s …` calls:

- one creation call that runs the fixture in a new tiled pane, using the method `surfaces open` uses, read from `rex api describe`;
- a poll every 250 ms of `api call com.superlogical.terminal.program_status`, `…process` and `…format` (text, `max_bytes` 4094), until `process.last_exit` is non-null or 8 s pass;
- a final full `format` read.

Counts are taken in the same way as for the teerex arm.

| Row | Pass condition |
| --- | --- |
| B1 | F1: `exit_report.exit_code == 3`, `signal == null`; `stderr.full` contains the assertion line byte-exact; controller exits 1; `success == false`. |
| B2 | F4: `exit_code == 0`, `success == true`, controller exits 0. F1 and F4 differ in `exit_report`. |
| B3 | F5: `exit_report.exit_code == 1`, while the F5 `watch` reports `status_report_matched`, a different fact. `report.json` stores both side by side as `reported_status` and `direct_child_exit`, and no field derives one from the other. |
| B4 | `process.last_exit` of the run-visible pane is recorded as `terminal_program_exit`. The runner asserts it is **not** used as the fixture's exit: it equals the helper's exit, which is 0 or null, while F1's is 3. If Rex ever reports 3 there, record that as an observed fact and keep B4's not-substituted assertion. |
| B5 | For F1 and F4, retained prefixes and full files equal the fixture's known bytes, and the `complete`/`full_complete` flags are as documented. |
| B6 | Counterexample X1 (§6) holds. |
| B7 | F2: controller exits 124, the outcome names the deadline, an actual `signal: 9` is recorded, partial output is retained, and `block_absence_verified == true`. The quiet `watch` exits 124 `deadline_exceeded`. |
| B8 | F3 with controller SIGINT gives 130, and with SIGTERM gives 143. Keep-open is overridden, so the pane is absent. Partial output is retained. |
| B9 | The refusals each give controller exit 1, `failure_reason` set, no `started.json` child PID, and no new block in N1: missing cwd, missing executable, an `REX_SESSION` key in the env file, a FIFO stdin, and a `watch --baseline` whose target differs from `--block` (exit 1 before contacting Rex). |
| B10 | The unknown outcomes cite `items/run/test_visible.py` `test_lost_creation_and_close_acks_are_not_retried` and `test_controller_sigkill_retains_known_ids_and_helper_own_deadline`, run in the same invocation against the same Rex, with their pass state recorded. The baseline does not re-implement them. |
| B11 | F6: the same-group sleep is gone after return. The detached PID is **alive** and is recorded as `detached_survivor: true`, then the script kills **only** that PID. `all_descendants_verified_gone == false`. |
| B12 | N1–N6 show no unexplained delta. |

**Measurements**, recorded in `report.json.measurements[arm][mode]`:

| Field | Definition |
| --- | --- |
| `calls` | Top-level invocations per task. |
| `rex_client_launches` | teerex's `collector_invocations` plus placement and close transports; the reference arm counts every `rex` exec. |
| `wall_ms` | `{cold, warm_median, warm_p95}` from `time.monotonic_ns()` around each exec. |
| `stdout_bytes`, `stderr_bytes` | Bytes per invocation, summed per task. |
| `output_dir_bytes` | Size of the `--output-dir` files. |
| `cpu_ms`, `maxrss_kib` | From `resource.getrusage(RUSAGE_CHILDREN)` deltas around each waited exec. macOS `ru_maxrss` is in bytes and is divided by 1024. |
| `pane_side_cpu_ms` | The in-pane helper and fixture, which are children of the Rex server and invisible to rusage, read from `/proc/<pid>/stat` on Linux and `ps -o cputime` on macOS at exit. It is null if unreadable. |
| `excluded` | Always `["rex_server", "gui", "neighbour_panes", "whole_machine_energy"]`. |
| `false_success`, `false_unknown` | Counts over all repetitions. |

**Cold and warm runs.** A cold run is the first exec of each binary against a freshly started server. Warm runs follow `--warmups` excluded executions and alternate arms, `--warm-runs` times each.

`summary.md` states, per quantity, the teerex arm against the reference arm as a ratio, with every B row. An improvement is claimed only for a quantity where teerex is better **and** B1–B12 passed.

### 5.2 Phase B: agent arm (C32 round trips, interruptions and misdirected input)

```text
python3 tools/acceptance/baseline.py --agent-arm --profiles ~/.config/teerex/profiles.json \
  --agent-profiles codex,claude --agent-runs 5 --teerex ABS --rex ABS --out NEW_DIR
```

For each profile, each run and each condition (`with-teerex` or `plain-rex`), the script does the following:

1. Prepare a `0700` work directory containing `fail_fixture.py` and a task file. The task text is: "Run `python3 fail_fixture.py F1` visibly, find why it fails, and report the failing assertion and the exit code. Do not edit files."
2. Create a PATH shim directory that holds counting wrappers for `teerex` and `rex`. Each wrapper appends one JSONL line to `$SHIM_LOG`, then execs the real binary. The line is `{"t": monotonic_ns, "tool": "teerex|rex", "verb": argv[1..2], "target_block": <value of --block if present>, "stdout_bytes": n, "exit": code}`; it carries no other argv. In the `plain-rex` condition, the `teerex` shim exits 127 and logs `blocked`.
3. Launch the agent with `teerex --config ~/.config/teerex/hosts.json --host hive agents launch …`, using the profile, a brief built from the task file, and the shim PATH. It opens in a new **visible** tab named `c32-<profile>-<n>` in Josh's hive Rex server. This is the only object in his real server, and it closes after the run through `surfaces close` of the owned block. The fixture itself still runs in that tab's own panes.
4. Wait for the agent's Stop report through the registry (`agents inspect`), with a 15 min cap.

Metrics are recorded per run:

| Metric | Source |
| --- | --- |
| `tool_round_trips` | Number of shim lines. |
| `interruptions` | Count of `agent-send`/`ask` lines to the seat. These are also shimmed and logged, but not delivered: the seat is replaced by a stub address that records the message. |
| `misdirected_inputs` | `send` lines whose `target_block` is not a block the agent created. |
| `correct_report` | The Stop report contains `expected 4 got 5` and `3`, checked by exact substring. |
| `wall_s` | Wall time of the run. |

The report gives medians per condition. **No model output is published.** Only counts and pass flags go to `summary.md`. The runs use Josh's existing subscriptions, with no new paid service or credential.

## 6. Counterexamples (runnable assertions)

- **X1. Equal visible prefix, hidden tail differs.** Observe the F1 and F4 panes at `--max-bytes 256` while each is still printing its identical first 4 KiB; this needs both captures incomplete, so pad if the terminal is tall. Then `compare` must give `captured_text_changed=false`, `full_text_changed=null`, `capture.*.complete=false`. The baseline's verdict text must say `unknown`, never `unchanged`, while the actual exits are 3 and 0.
- **X2. Retained `done` without direct-child exit.** With `--keep-open`, F4 leaves a `done` record. Start F5 in a new run-visible pane anchored to the same session, and also re-observe the kept F4 pane. `watch --status-state done` against a baseline containing the identical retained record does not match within 1 s. F5's new `done` matches only as `status_report_matched`, and its `exit_report` is 1. This is the existing `test_retained_done_report_is_not_successful_exit` pattern, extended to run-visible.
- **X3. `compare` alone cannot make the cartridge ready.** Using a record whose runs include only the `CompareTest` rows, `readiness.py` must compute `not_ready` with R1, R5 and R9 failed, and the packager must ship `experimental`. Add this as a unit test in `tools/acceptance/test_acceptance.py`.
- **X4. Numeric API acceptance is not evidence.** A `doctor` packet with `advertised_requirements_met=true` given to `readiness.py --merge` is refused with exit 1 and the reason `not_a_readiness_run`.
- **X5. Pane closure is not descendant death.** This is B11.
- **X6. Packaging success is not readiness.** A green `test_payloads.py` alone yields no record, so the result is `absent`, which ships as `experimental`.

## 7. Acceptance for the build (what "done" means)

1. **Unit tests.** `python3 -m unittest discover -s tools/acceptance -p 'test_*.py' -v` and `python3 -m unittest discover -s tools/cartridges -p test_cartridges.py -v` both pass. The former covers the verdict rule, X3, X4 and record schema validation.
2. **Linux record.** On hive, from a clean checkout of the landed commit, build the catalog with `python3 tools/cartridges/package.py --platform x86_64-linux --version <v> --output NEW`. Then run `python3 tools/acceptance/readiness.py --item observe --catalog NEW --rex ~/.local/bin/rex --previous-teerex <alpha.5 path> --runs 3 --long --out tools/cartridges/readiness/observe-x86_64-linux.json`. It exits 0 with `verdict=ready` and `evidenced_api_revisions=[13]`. The CI Linux API13 lane runs the same command with `--merge`, and its run is added.
3. **Mac record.** The CI Mac API10, API12 and API13 lanes each run `readiness.py --runs 3 --merge`, producing `observe-aarch64-macos.json` with `[10,12,13]`. If any lane fails a row, the Mac payload stays experimental and the failed rows are reported. That is a valid outcome, not a reason to edit the row.
4. **Packager.** Rebuilding the catalog at the record commit prints `"readiness": {"observe": "ready", …}`. The observe manifest has `status: ready` and narrowed revisions. `cartridges.py install --all --catalog NEW` (no `--allow-experimental`) plans exactly `observe`.
5. **Staleness.** A whitespace-only commit touching `items/observe/main.zig` makes the next build print `stale:items/observe/main.zig` and ship `experimental`. Verify this on a scratch branch, then discard the branch.
6. **Baseline phase A.** `python3 tools/acceptance/baseline.py --teerex <built> --rex ~/.local/bin/rex --out NEW` on hive exits 0, and also passes in the CI Linux API13 lane. `summary.md` is attached to the landing report.
7. **Baseline phase B.** One run per profile and condition completes on hive. Each `c32-*` tab is visible during its run and absent afterwards, and `summary.md` reports medians.
8. **Install.** The ready-only observe cartridge is installed on hive and the M5 with `cartridges.py install --all --catalog <published> --apply`. `cartridges.py run observe -- observe --socket <own socket> --session <own> --block <own>` succeeds on each machine, as the live check.

## 8. Files and owners

| Path | Change | Owner |
| --- | --- | --- |
| `tools/acceptance/readiness.py`, `baseline.py`, `fail_fixture.py`, `test_acceptance.py`, `contracts/observe.json`, `README.md` | New | teerex lead |
| `tools/cartridges/package.py`, `test_cartridges.py` | Readiness gate (§3) | teerex lead |
| `tools/cartridges/readiness/observe-*.json` | Generated records (§7) | teerex lead, committed from CI artifacts or the hive run |
| `items/observe/test_observe.py`, `items/observe/README.md` | Tests for any unmapped claim, and a line linking the readiness record | teerex lead |
| `.github/workflows/ci.yml`, `docs/ci.md` | A readiness and baseline step per lane, uploading the record and report as artifacts | teerex lead (the overnight plan gives the lead every teerex item) |
| `docs/cartridges.md` | Replace "every item stays experimental" with the evidence-gated rule and the current ready list | teerex lead |
| `docs/roadmap.md` (Q02, C31, C32, N09, Q12) | Mark the delivered parts with links to the records and summary | planning integrator |
| agent-core `primitives/skills/rex/SKILL.md` | One line: "Prefer ready cartridges: `cartridges.py install --all` installs only evidence-ready items; `compatibility.readiness` names the proving record." | codex · agent-core native |
| `~/rivet/work/teerex-lead/rex-upstream.md` | Append §9 | teerex lead |

## 9. Host-blocked: upstream Rex request (one paragraph, for `rex-upstream.md`)

**Request: input lease, process-tree ownership, paint and report authenticity for automation.** teerex can prove what a block's direct child did, but four guarantees need the server.

- **Input lease.** An exclusive, revocable input lease on a block: a conditional write that fails if any other client wrote since a given sequence number, plus an immediate human-revocation event. Without it, full C31 takeover and atomic agent input cannot be guaranteed by any client.
- **Process-tree ownership.** Process-tree ownership for a block's program, such as a cgroup or session-wide kill, with a verification read that includes `setsid`/detached descendants. Without it, "all descendants stopped" stays `false`.
- **Paint confirmation.** A presentation event confirming that a block was actually painted or focused in a client window. Without it, Rex.app visibility (Q10) is structural readback only.
- **Report attribution.** The emitting PID and process start time on each OSC 7501 `program_status` record. Without it, a `done` report cannot be attributed to the direct child.

Counterexamples the fixtures above already exercise:

- a `setsid` survivor after verified pane closure (F6);
- an identical retained `done` record coexisting with exit 1 (F5);
- a second client's concurrent paste racing a brief, as in the existing send and agents tests.

## 10. Still unsupported after this build

Without the §9 server work, the following stay unsupported:

- full takeover and immediate revocation;
- atomic input or an exclusive lease;
- detached-descendant and SSH-remote process death;
- isolation or sandboxing;
- painted-visibility proof;
- API11 and builds that have not been run;
- task completion, which stays `not_assessed`.

Phase B's agent metrics are measured on a fixed synthetic task with N=5 runs per profile and condition. They are evidence for that workload, not a general productivity claim.

## Sources

The source baseline is `244d893`; upstream through `4282f23` was checked for overlap.

- **Planning:** [roadmap](../../roadmap.md#prepare-readiness-and-a-baseline-in-parallel) (Q02/Q05/Q10/Q11/Q12/C31/C32/N09); [PDF inventory](../teerex-pdf-work-inventory.md) C31 (P2:p7), C32 (P2:pp7–8), V11.
- **Product docs:** [alpha5.md](../../alpha5.md); [cartridges.md](../../cartridges.md); [alpha.5 release](../../releases/v0.1.0-alpha.5.md).
- **Item contracts:** [observe](../../../items/observe/README.md); [run-visible](../../../items/run/VISIBLE.md) and its [acceptance](../../../items/run/ACCEPTANCE.md); [agents](../../../items/agents/README.md#stops-exits-and-deliberate-presentation); [doctor](../../../items/doctor/README.md).
- **Code read:** `tools/cartridges/package.py`, `cartridges.py`, `test_payloads.py`, `manifests/source.json`; `items/observe/test_observe.py`; `.github/workflows/ci.yml` (Rex pins).
- **Live identity:** hive's `rex version --json` (`348d751…`, API13).
- **Authority:** `~/rivet/work/seat-2026-11-13/overnight-2026-11-13.md`.
