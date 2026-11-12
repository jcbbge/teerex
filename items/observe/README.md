# observe

**Experimental incremental implementation of Phase 3 #1.** A small Zig CLI returns bounded terminal text plus C02 process, last-reported-directory and program-status evidence as JSON. C03 adds an explicit offline comparison of two observation files, not activity/completion interpretation. C09's `watch` adds a bounded foreground wait for changes or selected status-report evidence against an explicit baseline, reusing those same evidence rules. This is still not the complete proprioception packet, a ready cartridge, an installer, or a general Rex client. Phase 3 #8 contributes only the five concrete bindings observation needs: `server.version` and terminal `format`, `process`, `pwd`, `program_status`.

The shared CLI is distributed as [v0.1.0-alpha.1](../../docs/releases/v0.1.0-alpha.1.md), including checksums, explicit invocation and upgrade/removal instructions. The validation sections below preserve increment-time builds; the release guide identifies the final combined executable.

## Contract and limits

- Select an absolute Unix socket path and full `session:UUID` / `block:UUID` explicitly. No current-focus, label, ID-suffix, or `REX_*` environment fallback selects the target.
- One explicitly attached `rex do --session FULL --block FULL` runs fixed embedded Lua and five serial supported reads, using `--autostart=false`, an explicit endpoint and a three-second Rex connection/request timeout. Values arrive as JSON arguments, never interpolated source; no configuration is installed. Each response is re-encoded and checked against 128 KiB at the Lua boundary, not before Rex allocates/decodes it. A bounded aggregate buffer independently caps collector output; stderr retention is 4096 bytes. Required RPC/decode/size-limit failures produce no success packet, not fabricated empty evidence.
- Live `observe` and `watch` are macOS-only. Standalone `observe --timeout-ms N` defaults to **5000 ms**, range **100–60000**. Its supervisor bounds collection, including a stalled executable, then applies the same TERM/KILL/drain limits as `watch`. Deadline exits **124**, SIGINT/SIGTERM **130/143**, with no success JSON from an interrupted sample. Preflight, final serialization/stdout backpressure and kernel stalls are outside a hard real-time promise. Offline `compare` still needs neither Rex nor macOS.
- Output includes an observation ID, client observation time, exact requested target, actual server version/platform/API revision, and bounded capture. API revision 13 is required; other revisions fail rather than silently claiming compatibility. Version checks do not authenticate the server or prove schema semantics.
- The capture is **screen and scrollback**, not necessarily the visible viewport. Rex returns a **prefix** when limited; this may omit the latest prompt. `capture.complete=false` makes that omission explicit. This increment does not fetch continuation blobs or claim that a truncated capture is enough to act safely.
- `--max-bytes` limits the JSON-encoded **content string**, including its two quotes, not the whole JSON packet or Rex's internal capture memory. Default 4096; range 256–65536. Unicode and escaping count toward this budget. The tested Rex counts the escaped string body without the quotes, so teerex reserves those two bytes before requesting and independently checks the returned string. `atomic_snapshot=false`: no atomicity, ownership, completion, process-state, or permission inference is made.
- Reads only: no input, session creation, focus/layout changes, configuration edits, background service, or file writes by teerex. The Rex CLI still opens/attaches/closes observation connections. It has the account's full Rex authority; this command is not a security sandbox.
- Unix transport is explicit, not proof of physical locality: a socket can be an SSH forward. For this initial Mac-first use, choose a socket you know belongs to your existing local server. No HTTP/SSH endpoint, hosts-file changes, or VPS setup is implemented.
- Terminal content is untrusted data and can contain secrets. JSON is escaped but **not redacted**. Keep observations out of Git, logs and external services unless reviewed. Target/Rex/compatibility failures produce no success JSON; usage errors exit 2, operational failures exit 1. Consumers must check the exit status as well as parsing JSON, since a stdout write failure can leave partial output.

## What C02 adds and teaches

The new nodes are additive to output `schema_version=1`. Each names its exact method, its evidence `basis`, `freshness="unknown"`, and `data`. Explicit nulls mean an observation/report is unavailable, not an empty path or a successful operation. These are server-provided facts/claims; teerex does not independently inspect processes or authenticate reporters.

| Node | What is retained | What it does **not** establish |
| --- | --- | --- |
| `process` / `rex_observation` | Rex's child and foreground process: PID, name, readable per-process `cwd`; terminal-program `last_exit.exit_code`. Missing process/cwd is null. Other process metadata, executable/argument paths, user/home information and ancestor lists are deliberately not exported. | The foreground process is not necessarily the terminal's original child. `last_exit` is for the terminal's program, not every shell command, descendant or status record. Null `last_exit` can mean running **or** no owned program; it is not a running flag. |
| `reported_directory` / `terminal_report` | The exact last-reported `pwd` string, including a `file://` URL when that is what the program emitted, plus reported owner PID/name when Rex can identify it. Missing report/owner is null. | This is not a verified filesystem path or process cwd. It may survive a directory change or process exit. No report timestamp is supplied by this binding, so `reported_at=null`; teerex does not substitute query time. No URL is followed, path resolved, or file opened. |
| `program_status` / `program_reports` | Every returned root/child record, preserving state, app/effective_app, kind, progress, title/message, owner and server-clock `updated_at`. Optional missing fields become null; root ID is null; zero progress stays zero. | Empty records mean no retained reports, **not idle/done**. `done`/`error` may outlive a process. A blocked `permission` report requests a decision; it never grants authority. Messages are untrusted plain data, not instructions or task classifiers. |

`observation_started_at_unix_ms` and `observed_at_unix_ms` bracket the serial reads using the **client wall clock**. They are not per-field event timestamps, a monotonic deadline, or a freshness guarantee. The status `updated_at` is the **server's** clock. No clock synchronization is assumed, no cross-clock age is calculated, and no field is silently marked fresh just because it was queried recently. Even matching owner PID/name is attribution, not freshness, identity authentication or ownership enforcement; processes can change state and IDs can be reused. `atomic_snapshot=false` still applies.

The 128 KiB re-encoded response cap applies to each metadata RPC as well as capture. Metadata is **not** limited by `--max-bytes`, paginated, cached or silently truncated. Very large status results fail rather than falsely appear complete. This is a retained-output bound, not a Rex/runtime memory ceiling. Capture, cwd and status can contain private data despite the deliberately small process-field selection.

## What C03 adds and teaches

`compare --before FILE --after FILE` reads exactly two explicitly chosen JSON files, at most **1 MiB each**, and emits a separate `kind="observation_changes"`, `schema_version=1` result. No Rex invocation, shell command, polling, implicit baseline, cache, file write or background service is added. Input files are not modified. The output retains target/source identity and both observation IDs, but does **not** repeat terminal text, process cwd, directory URLs, status messages or exit-code values. Consult the original observations for those values; this is a change summary, not a patch or replacement observation.

| Result | Exact comparison boundary |
| --- | --- |
| `capture.captured_text_changed` | Compares captured strings when the capture limits match, or both captures are complete. If limits differ and either capture is partial, returns null rather than mislabel a different-length prefix as terminal change. Both limits and completeness flags remain visible. |
| `capture.full_text_changed` | Compares full captured screen-and-scrollback text only when **both** captures are complete. Otherwise null, even if equal prefixes or a changed prefix are known. This says nothing about intermediate activity, the latest viewport, or atomicity. |
| `process.child`, `.foreground`, `.last_exit` | Separately compare returned child/foreground records (PID, name, nullable cwd) and terminal-program exit records. A changed record need not mean a different process: a cwd or its availability can change. It does not identify completed tasks or nested shell commands. |
| `reported_directory` | Compares the exact reported path plus owner record, without URL/path normalization. Available only when a non-null directory report exists; null owner stays unknown. This is not actual cwd or freshness. |
| `program_status` | Compares the retained records, including server-clock arrival timestamps and nullable fields. Records are matched by ID independent of list order; duplicate IDs are rejected. Zero progress differs from unavailable progress. A new timestamp alone is an evidence change, not proof of meaningful activity. An empty record list is available evidence of no retained reports, not idle/completion. |

Each metadata comparison has `before_available`, `after_available`, `availability_changed`, and nullable `changed`. When either side is unavailable, `changed=null`, not false: newly available exit evidence or a disappearing foreground record is an **availability change**, not an inferred transition to success, stopped, or done. Missing whole C02 nodes are allowed for earlier text-only observations. Known records normalize omitted optional fields to null; changes inside such records compare the returned data, not unobserved underlying state.

The command requires matching exact server/session/block strings and matching Rex version/platform/API revision. Schema version 1, API 13, prefix/screen-and-scrollback capture, and the current evidence method/basis/unknown-freshness labels are required. Unsupported/malformed/incompatible/oversized inputs fail without success JSON. Compared fields are typed; unrelated additive fields are ignored. Object-key order and top-level observation IDs/client timestamps do not create evidence changes. Status timestamps **are** retained report data and are compared as strings, not interpreted as ages.

`before` and `after` are **caller-supplied order**, not independently verified chronology. Wall clocks can move backwards. Matching labels/IDs do not authenticate files, prove they came from Rex, prove the server never restarted, or establish shared observation time. The five live reads remain non-atomic; no continuous observation or no-intermediate-change guarantee follows from equality. `interpretation="none"` is explicit: no activity, phase, confidence, success/completion, freshness or permission classifier is implemented. Optional generic interpretation/cache/filter work remains deferred rather than silently assigned to teerex or another agent.

Saving observations is an explicit caller choice, not automatic history. If redirecting stdout, use owner-only files (for example, set `umask 077` **before creating them**) in an ignored local location and check each observe command's success before comparison. Git ignore rules do not protect secrets. Comparison output still contains target/observation identifiers and is **not a redaction or authenticity boundary**; review it before sharing too. No paths or URLs inside a packet are opened or followed.

## What C09's bounded observation wait adds and teaches

`watch --socket PATH --session session:UUID --block block:UUID --baseline FILE --timeout-ms N [--interval-ms N]` implements the read-only `observe_until_changed` portion of Phase 3 #3's C09, using Phase 3 #1's observations/C03 comparisons. Its optional status predicate is described below. It is a single foreground invocation, not a daemon, subscription, completion detector, input controller or new cartridge. It never runs a command in or sends input to the observed terminal.

The baseline must be a valid observation file of at most **1 MiB**. The separately supplied socket/session/block must match it exactly **before contacting Rex**; file contents cannot silently select a different endpoint. Every live sample must match the baseline's target, source version/platform/API revision and supported provenance. Each sample uses the baseline's capture budget. No implicit baseline, focus fallback, byte-budget override or rolling-baseline reset is added. Identifiers/labels are not authentication, authorization or server-instance identity; a server restart with the same labels/version is not detected.

Every sample compares against the **original baseline**, not the previous poll. A known field-value change **or an evidence-availability change** wakes the wait. A newly available exit report is not inferred success; a disappearing process record is not an invented completion transition. A change in capture completeness is an availability change for full text. A retained status timestamp can wake the wait even when its state/message is unchanged; it is changed report evidence, not proof of useful activity. Unavailable evidence and equal incomplete prefixes stay unknown where C03 says unknown. No sampled equality proves that no intermediate changes occurred.

The monotonic **collection budget is required**, range **100–60000 ms**. It covers polling delays and collection, including stalled Rex subprocesses. The interval defaults to **250 ms**, range **50–5000 ms**, **after each collection finishes**, not a fixed sampling frequency. One persistent, supervised Rex/Lua connection performs the same five serial reads for every sample; API revision is checked each time. This removes five client launches plus a teerex collector per sample, not the reads or their non-atomic/staleness limitations. No direct socket protocol or server subscription is added. One baseline, one bounded frame buffer and one last accepted comparison survive; each decoded sample's arena is freed. No private capture is automatically saved or repeated in the wait result.

The same macOS process-group supervisor used by `run` owns only the persistent collector and its subprocesses, **not the observed terminal/process or Rex server**. A stalled collection gets TERM then KILL after at most 250 ms, or immediately when its leader exits; pipe drain is limited to 500 ms. A satisfied predicate also requests collector cleanup, not termination of the observed program. Signals remain handled during poll gaps. Cleanup may extend the requested deadline by 500 ms plus scheduling. Baseline/file/environment preflight, kernel stalls, final JSON serialization/stdout backpressure and SIGKILL/crash of teerex are not a hard real-time guarantee. Detached/re-grouped collection descendants remain outside the cleanup scope. `all_descendants_verified_gone=false` is explicit, and `last_collection_cleanup` reports the collector group's signal results, not whole-tree verification. Initial live support is macOS only.

Normal results are `schema_version=1`, `kind="observation_wait"`:

| Field / outcome | Meaning |
| --- | --- |
| `change_observed` / exit **0** | A comparable value or availability change was accepted before the deadline. **Not** task success, completion, permission or fresh-report verification. |
| `status_report_matched` / exit **0** | The explicitly selected root/named record matched the requested state with differing evidence relative to the original baseline. Not process exit, task completion, permission or proven report freshness. |
| `deadline_exceeded` / exit **124** | No qualifying change was accepted in the budget. Not proof of unchanged full text, idle, failure or completion. A collection may have been interrupted or a late sample discarded. |
| `observation_failed` / exit **1** | Collection/decoding/source compatibility failed; the wait stops, without laundering failure into unavailable evidence or a quiet timeout. `failure_reason` names the error. Bounded collector diagnostics go to stderr, not into the change summary. |
| `cancel_requested` / exit **130/143** | SIGINT/SIGTERM requested cancellation, including during a poll gap. Previously accepted comparisons survive; an interrupted sample is not treated as complete. |
| `changed_fields`, `availability_changed_fields`, `unknown_fields` | Separate named field lists from the **last accepted comparison**. A field can have changed availability while its value comparison remains unknown. Lists are null, not empty, if no comparison was accepted. Raw terminal/report/path/exit values are not repeated. |
| `baseline_observation_id`, `baseline_source`, `target`, `last_comparison` | Caller-selected reference and exact C03 comparison, retaining both observation IDs and the compatibility/provenance boundary. `baseline_source` is not a fresh source observation after a later failure. |
| `collector_invocations`, `collection_attempts`, `observations_compared`, `last_comparison_elapsed_ms` | One collector invocation, logical attempt/accepted counts and last accepted comparison's monotonic offset. A previous comparison is **not current evidence** after a later failed/interrupted attempt. It is labelled last, not substituted for the failed sample. |
| `condition`, `matched_status_report` | Null for a generic wait. A status wait names the selected record/state and differing-evidence requirement. Its match retains only record ID, state and server-clock arrival timestamp, not message/title/progress/owner. |
| `last_sample_interrupted`, `last_sample_discarded_at_deadline`, `interpretation` | Explicit interrupted/late-sample markers; `interpretation="none"` always. Full-sample collection is at most **1 MiB**, independently of its terminal-content budget; the current internal frame buffer additionally stops at **655680 bytes**. Collector stderr retention is capped at **4096 bytes**. |

Syntax errors exit 2 without JSON. Baseline/preflight/unsupported-platform and output-write errors may exit 1 without a complete result. Always check both exit status and complete JSON. The underlying observations are still non-atomic and potentially stale/untrusted. Result identifiers and stderr can still contain private information; escaping and omitted raw values are not redaction or an authority boundary.

### C09 selected program-status evidence

Add `--status-state idle|working|done|blocked|error` to wait for one report, not any change. Without `--status-id`, the selected record is the **root (null ID)**; a supplied ID matches exactly, so the literal ID `root` selects a named child, not the root. IDs must be nonempty and at most 1024 bytes. A status ID without a state is a usage error.

An identical retained matching record in the baseline does **not** satisfy the condition. A different report for the selected ID that matches the state does; unrelated records, text/cwd changes, disappearing reports and nonmatching states do not. Equality includes every retained record field and the server-clock timestamp, not just its state. Newly available matching evidence can qualify even when the baseline had no report: this proves neither when the program emitted it nor that it is fresh. There is no cross-clock age calculation, owner authentication or same-process continuity guarantee.

A deadline with no matching evidence is still `deadline_exceeded`, with explicit condition, last comparison and nullable unknowns. No retained report does not prove that the program is unsupported: teerex cannot distinguish “never reports” from “hasn't reported yet.” `done` remains a program claim even while its process runs, and `blocked:permission` grants no authority. No status interpreter or completion detector is added.

## Build and invoke individually

Building requires Zig **0.15.2**. Live observation requires an existing compatible Rex CLI on `PATH` and an already-running selected server; offline comparison needs neither Rex nor a server. The initial target is macOS; exact validation results are recorded below. No system-wide installation or Rex configuration is required.

From the repository root:

```sh
zig build -Doptimize=ReleaseSmall
./zig-out/bin/teerex --help
```

If Zig is not installed, the same pinned compiler can be invoked through `uv run --with ziglang==0.15.2 python -m ziglang build -Doptimize=ReleaseSmall`; `uv` fetches/caches the toolchain but does not install it globally. Cross-building the tested Mac binary uses `-Dtarget=aarch64-macos --prefix zig-out/mac` in addition to the build options above. Tests on that Mac need `TEEREX_BIN` set to the absolute path of the transferred binary; the default is `zig-out/bin/teerex` in this checkout.

After independently identifying your existing server socket and a known terminal's full IDs, replace the placeholders deliberately:

```sh
./zig-out/bin/teerex observe \
  --socket /absolute/path/to/existing/rex.sock \
  --session session:FULL-UUID \
  --block block:FULL-UUID \
  --max-bytes 4096
```

After deliberately saving **two successful observations** of that same target, compare their existing private files:

```sh
./zig-out/bin/teerex compare \
  --before local/observations/before.json \
  --after local/observations/after.json
```

Or wait on macOS against one deliberately saved **successful** observation, explicitly selecting the same target again:

```sh
./zig-out/bin/teerex watch \
  --socket /absolute/path/to/existing/rex.sock \
  --session session:FULL-UUID \
  --block block:FULL-UUID \
  --baseline local/observations/before.json \
  --timeout-ms 5000 --interval-ms 250
```

Humans can read the formatted JSON directly; agents consume the same fields. There is no installer or persistent hook to remove: stop invoking the executable and delete only the build output you created. To upgrade, rebuild a reviewed revision and repeat validation; never replace another item's config or binary silently. No third-party binary is bundled. Project licensing remains [unselected](../../RIGHTS.md); Rex is a separate proprietary dependency.

## Validate the increment

The full public-CLI suite requires Python 3 and the test Rex CLI on `PATH`. Integration tests create disposable servers/sessions under `/tmp`, with an explicit private Unix socket, `--restore=false`, and `/dev/null` configuration, then stop them. They never use your default server, Rex config, Mac installation, or VPS. Do not substitute a production endpoint. Seven additional offline comparison tests use synthetic files and intentionally remove Rex/all other executables from the comparison subprocess's `PATH`.

```sh
python3 items/observe/test_observe.py
```

To exercise only offline comparison without a Rex installation, use `python3 items/observe/test_observe.py CompareTest -v` after building the executable for the test host. This test host capability is not a commitment to initial Linux/VPS product support.

The tests cover explicit selection despite conflicting `REX_*` variables, correct target/text/server-version attribution, unchanged session and selected-session block listings, complete and truncated Unicode/quoted output, repeated observations without terminal changes, the exact encoded-byte boundary, cross-session block rejection, missing-server/no-autostart, and invalid arguments. C02 adds missing-report unknowns, real process PID/cwd versus an intentionally different OSC 7 directory, unchanged retained reports after a real cwd change, multiple OSC 7501 records/owner provenance, zero versus absent progress, selected process-field privacy, and a retained `done` report despite exit code 7. Those original observation cases use real Rex, not mock responses. C09 separately labels controlled transport fault injection below.

### Original text-only slice validation — 11 November 2026

- Zig 0.15.2 `ReleaseSmall` cross-build to `aarch64-macos` succeeded; `zig fmt --check build.zig items/observe/main.zig` passed. The arm64 Mach-O executable is **156424 bytes**; SHA-256 `931e07237b8488b8c2f8f75104942805212f00d12afac9d160adcaf0935c457d`. Its archive was checksum-verified on the disposable Mac before execution.
- **Six integration tests passed** on arm64 macOS **27.2**, Rex **0.1.0-preview.16**, API revision **13**, server commit `aa2db1b21261b479a550559fb70e2c3a66c07ba2`. The final run reported `Ran 6 tests in 0.888s — OK`; after cleanup, no owned fixture processes remained. The suite creates its own sessions; the observed command itself does not.
- The initial long-text test failed because Rex's bound excluded JSON's surrounding quotes. After reserving those bytes, the regression case verifies that a 257-byte encoded string is partial at a limit of 256 and complete at 257. The 65536-byte accepted limit and invalid values below/above the supported range are also exercised.
- A separate **20-observation** short-text sample measured **39.48 ms median, 42.20 ms p95, 43.32 ms maximum**, with a 631-byte result on this disposable Mac. This includes two Rex CLI process launches, not server startup. It is a small local sample, not a performance guarantee, an M5 benchmark, or evidence of an end-to-end agent productivity gain. Binary size excludes Rex and says nothing about the server's capture memory.

### C02 validation — 11 November 2026

- Inspected the running server's three method descriptions and exercised actual responses before choosing the retained fields. The API revision is still 13, on arm64 macOS 27.2/Rex preview.16, commit `aa2db1b21261b479a550559fb70e2c3a66c07ba2`. Zig 0.15.2 formatting and Mac cross-build passed. The updated **182648-byte** executable has SHA-256 `3388f450deaaa48d1fb708004aafd9e7cac00bfcc3e7de631eab1bfdad1a5581`; archive and executable checksums were verified on the Mac.
- The three new scenarios failed against the previous text-only executable because the evidence nodes did not exist. After implementation and correcting an empty-arguments encoding error (Zig's untyped empty tuple serializes as `[]`, while these methods require `{}`), **all nine integration tests passed in three consecutive fresh-server runs**: 1.628 s, 1.568 s, 1.538 s. This includes all six earlier tests, not just the new happy path.
- A controlled program advertised one directory, then changed its actual cwd between two observations without updating its reports. Rex's process cwd changed; the advertised URL, report owner and status arrival timestamps did not. Another program reported `done`, exited 7, and left its directory/status behind while current process identities became unavailable. These are exercised counterexamples to assuming reports are current or equivalent to success. No process permission-denial or PID-reuse scenario was induced on Joshua's machine or the test Mac.
- Same-Mac comparison, alternating 20 observations per binary after two excluded warmups each: text-only median **38.13 ms**, p95 **40.34 ms**; C02 median **91.17 ms**, p95 **98.90 ms**, maximum **107.43 ms**. Plain-fixture JSON grew from **631 to 1477 bytes**. The added evidence costs three more Rex CLI process launches; it is not a free performance improvement. Server startup was excluded. These small synthetic samples are not M5/resource ceilings or evidence of agent productivity gains; no busy watcher or direct-protocol optimization was added.

### C03 validation — 12 November 2026

- Zig 0.15.2 formatting, native build and `aarch64-macos` `ReleaseSmall` cross-build passed. The Mac executable is **241224 bytes**, SHA-256 `4f626151ce92c7313a4b23d5381203e253b549284e31f8fab701767ebbdafe99`; archive and executable checksums were verified on the disposable Mac. This is **58576 bytes larger** than C02. Comparison adds no Rex calls, but does add parsing/comparison/output code and file I/O; no new latency, memory ceiling, token-saving or productivity benchmark is claimed.
- **Seven offline tests passed** on the orb and Mac. They distinguish equal evidence from new packet IDs/backwards client clocks, JSON object-key order, partial-prefix equality versus complete-text equality, mixed capture budgets, missing versus empty evidence, process/cwd and report changes, newly available exit evidence, record order versus status timestamp changes, absent versus zero progress, duplicate IDs, incompatible target/version/provenance, malformed/oversized inputs and invalid arguments. They test the executable, not private helpers; synthetic files are not Rex evidence.
- The full suite, **seven offline plus nine real-Rex integration tests**, passed in **three final fresh-server runs: 1.461 s, 1.476 s, 1.480 s**, on arm64 macOS **27.2**, Rex **0.1.0-preview.16**, API **13**, commit `aa2db1b21261b479a550559fb70e2c3a66c07ba2`. The running server's version was queried directly. Four existing integration scenarios now also compare real captures: unchanged repeated observations; actual cwd/text changes while directory/status reports stay unchanged; working → retained `done` with actual exit **7** and disappeared foreground evidence; and the 256/257-byte partial/complete boundary, which remains unknown for full-text comparison rather than a false change. The comparison subprocess has no usable `PATH` in these scenarios either. No owned fixture processes remained after cleanup.

### C09 bounded observation wait validation — 12 November 2026

First extracted the existing execution supervisor into shared `src/child.zig` and made C03's comparison result reusable **without changing their semantics**. All 27 existing checks passed before adding the wait: 11 execution tests in 15.578 s, 16 observation/comparison tests in 1.775 s. The new quiet-wait scenario failed against that previous binary with exit 2 (`watch` did not exist), then passed against the new executable.

The final public suites passed in three consecutive fresh-server runs on the same arm64 macOS **27.2**, Rex **preview.16/API 13** environment:

| Pass | Execution suite | Observation/comparison/wait suite |
| --- | --- | --- |
| 1 | 11 tests, 15.639 s, OK | 25 tests, 10.625 s, OK |
| 2 | 11 tests, 15.613 s, OK | 25 tests, 10.626 s, OK |
| 3 | 11 tests, 15.630 s, OK | 25 tests, 10.570 s, OK |

The 25 comprise seven offline comparisons, nine original real-Rex scenarios, seven new real-Rex wait scenarios and two new transport/cancellation scenarios with multiple controls. New real cases cover quiet deadlines despite changing packet IDs, explicit target selection despite poisoned environment, input-file preservation, visible text changes with the observed process still running, **cwd-only** changes while reported directory/text stay unchanged, a `done` report while its process **continues running**, exit **7** producing newly available exit evidence instead of inferred success, and an actual changed tail hidden beyond an equal bounded prefix. Target/source/argument and missing-server/executable failures remain fail-closed with no autostart or implicit focus.

Fault-injection cases deliberately replace/wrap the transport executable; they are **not evidence that real Rex ordinarily hangs**. A closed-pipe, TERM-resistant fake Rex and grandchild were stopped by deadline, SIGINT and SIGTERM, with no accepted sample and null (not empty/unchanged) comparison lists. A pass-through real-Rex shim then exercises SIGINT/TERM during a five-second poll gap and a later deliberate query failure: the last accepted comparison survives, labelled with its monotonic offset; the failed/interrupted sample does not become fresh evidence. Known owned fixture PIDs were verified non-executing, excluding zombie-only state from running work. The actual observed target remained unchanged/alive. No fixture server/process remained after cleanup. This is scoped process-group evidence, not a whole-tree guarantee.

Native build, Mac cross-build, Zig formatting and seven native offline comparisons pass. The Mac `ReleaseSmall` binary is **284888 bytes**, **19584 bytes larger** than the preceding run-and-collect binary. SHA-256: `e18f9aa1d2b4cce1e63964beff0a248356c3ac902824c0a88ee6d74491f8e31d`; transfers and the executed Mac binary were checksum-verified. Native Linux rejects `watch` as unsupported; that is not Linux/VPS support.

A separate real demo used disposable synthetic terminals and independently checked the target afterward: visible text change returned **`change_observed`, 406 ms, three comparisons** while process records remained identical; a quiet **1500 ms** budget returned **`deadline_exceeded`, 1514 ms**, four accepted comparisons/five attempts, with the fifth interrupted; an **800 ms** bounded-prefix wait returned **`deadline_exceeded`, 851 ms**, full-text change still null, even though a larger capture confirmed a changed tail. These are executed examples, not fabricated receipts or M5/performance guarantees. The private demo JSON's SHA-256 is `3d01c74d6fe5aaa1ef59de810be4c8524eccf35a09350d7c4d56e874b80f9e66`; it is not bundled with source. Each complete sample still costs five Rex CLI launches plus a collector. No CPU/peak-memory/productivity improvement is claimed. Reducing that concrete acquisition cost without changing evidence semantics is the next optimization to investigate.

This is **not yet validated on Joshua's M5 or installed Rex version**. Activity/phase interpretation, a terse human-facing view, latest-viewport retrieval and ownership enforcement remain later increments. The separate [experimental run item](../run/README.md) covers the selected local run-and-collect boundary. No whole-packet atomicity, status truthfulness, reporter authentication or full Phase 3 #1 completion is claimed. The historical phase/scoring review is unchanged; the non-Rex handoff is unchanged and unassigned.

### Acquisition, sustained polling and status evidence — 12 November 2026

This follow-up removes the preceding implementation's concrete acquisition cost. Fixed `collect.lua` uses one explicit Rex connection for the same five serial reads; `watch` keeps that supervised connection for the entire bounded wait, rather than launching a collector and five clients per sample. Lua's null-member omission and empty-array encoding were verified on the actual runtime; the script restores only the known process-null/empty-status shapes. Typed recursive evidence comparison replaces paired JSON-string allocations, and encoded capture-length validation uses the standard serializer with a counting/discarding writer. No custom JSON-escaping estimate, cache, inferred activity or direct socket client is introduced.

The standalone deadline scenario failed against the previous implementation, which rejected the new flag. The new status-predicate scenario failed against the pre-feature executable. The unchanged control first passed its existing 36 checks. The final **38 public checks** then passed three consecutive fresh-server runs on arm64 macOS **27.2**, Rex **preview.16/API 13**: 27 observation/comparison/wait checks in **13.792/13.874/13.978 s** and 11 execution checks in **15.459/15.381/15.439 s**. The latter covers the shared supervisor's unchanged execution behavior. New coverage includes root versus literal named `root`, stale matching versus different/newly available reports, unrelated report changes, unchanged live processes, 113-byte fragmentation of large real samples, controlled malformed/truncated/oversized/early-EOF frames, and standalone observation deadline/SIGINT/SIGTERM against resistant closed-pipe descendants. Later injected Lua RPC failure and poll-gap cancellation preserve the last accepted comparison. These transport faults are controlled tests, not claimed ordinary Rex failures.

One new immediate-frame-failure assertion initially demanded strictly increasing millisecond timestamps. Two legitimate offsets rounded to the same millisecond; the assertion now permits equality for that scenario only. It still requires a failed result, the exact failure reason, one retained accepted comparison and its correct contents. No behavior was weakened to manufacture a green result.

Alternating **40 observations per binary per case**, after two excluded warmups each, compared the old `e18f9aa…` executable with the final `c39108d…` on the same disposable Mac and stable real targets:

- Short complete capture: median **76.271 → 18.288 ms**, p95 **80.907 → 19.909 ms**. All observation evidence matched exactly after excluding generated packet IDs/client times.
- Truncated Unicode prefix: median **78.817 → 18.896 ms**. Complete 19999-byte capture: **76.971 → 18.902 ms**. Neither case changes the captured-prefix/unknown-full-text contract.
- Quiet **650 ms**, interval **50 ms**, eight repetitions: waited-child CPU median **478.434 → 63.600 ms**, accepted comparisons **4 → 10.5**. Wall median was **663.098 → 680.500 ms**, not a deadline-latency improvement.
- Quiet **5000 ms**, interval **250 ms**, three repetitions: waited-child CPU median **1877.955 → 96.748 ms**, accepted comparisons **14 → 20**. Wall median **5019.010 → 5030.264 ms**. CPU excludes the Rex server and whole-machine costs; more polls are not an end-to-end productivity benchmark.
- Offline comparison, 100 alternating runs after four warmups each: median **3.005 → 2.430 ms**, p95 **3.137 → 2.623 ms**. The comparison-only control predates typed equality (`e802794…`), not the live-acquisition control above. Inputs contained 320 synthetic status records, about 250 KiB each, valid for the offline file contract but beyond a live metadata RPC's cap. **120 differential public-interface cases** matched exactly, including ordering, strings, nulls, changed/missing records and incompatible sources/targets. These are synthetic comparison checks, not real program-status reports.

A real **60000 ms** quiet wait with a **65535-byte encoded prefix**, interval **50 ms**, accepted **866 samples** from **one collector invocation**, attempted 867 and returned deadline at **60063 ms**. Known prefix evidence stayed unchanged; full-text change stayed null. Point-in-time RSS samples from about five seconds onward were **2112–2272 KiB** for teerex and **40160–40960 KiB** for its Rex child; final samples were 2112/40960 KiB. This found no growing teerex retention in that run, not an allocator proof, peak/server memory bound or guarantee of constant memory. An initial fixture setup exceeded Rex's 65536-byte control-message limit; generating the large output inside the disposable program fixed the fixture without changing teerex limits.

The final Mac executable is **300712 bytes**, **15824 bytes larger** than the previous wait implementation, SHA-256 `c39108dc3bfedf240c62c4f7b0c683f6f06b5ef59fa78cd377aa8b38b007abe9`. These results are measurements on a disposable test Mac, not Joshua's M5/installed Rex, busy workloads, machine-wide energy or agent-productivity guarantees. No raw transcripts, vendor schemas, live personal captures, installer or public publication are included.

### C04/C07/C17 input-safety gate findings — 12 November 2026

The running API-13 method descriptions expose owner/host/placement metadata through `session.describe_block` and `session.own_block`/`disown_block`. Native block ownership arbitrates conflicting client preferences such as terminal size; its description explicitly grants no other rights. It is **not an exclusive input lease**, a controller identity or a human-revocation guarantee. C04's observation identity is implemented; controller/lease attribution remains unestablished rather than populated from the unrelated native owner field.

A disposable terminal ran a synthetic stdin reader, with one held client explicitly owning its block. A **different client successfully wrote 16 bytes**, the program independently printed its acknowledgement, and the held original client remained owner. A separate probe supplied a deliberately nonexistent `if_observation_id` argument inside terminal-write `args`: **the write succeeded and the program read it**. Contrary to an initial test assumption, this build ignored that experimental extra field; a schema-shaped argument does not create an enforced precondition. The inspected terminal `write` binding accepts data and queues bytes, without a supported observation/process/lease condition. A description of queued input is not acknowledgement of program consumption; the test checked the program's response separately.

These findings close V06's specific assumption about native ownership on the tested build. They do not establish every proprietary internal path, every revocation behavior or future version. C05/C07's atomic guarded gestures, C09 `verify_then_write`, and C16/C17's strong human-input clutch therefore cannot honestly be provided by these bindings. No such API was added, and no upstream change or personal-machine action was performed. A cooperative wrapper could constrain only cooperating clients and would need that narrower contract, not a renamed lock that pretends to enforce Rex-wide safety.

## Source contracts

- [Original phase review](../../docs/planning/teerex-pdf-work-inventory.md): P2:p2, C01–C04; supporting API adaptation P2:p7, C25–C28. The review remains a historical assessment rather than a mutable implementation checklist.
- C09 `observe_until_changed` and selected `wait_for_program_status` evidence: P2:p4's named-action list, implemented here as bounded read-only foreground waits. Other C09 actions retain their own boundaries; a guarded write is not implied.
- [Official server API discovery](https://www.superlogical.com/rex/docs/automate/server-api) and [CLI contract](https://www.superlogical.com/rex/docs/reference/cli).
- Actual Mac `0.1.0-preview.16`, API revision 13, method descriptions inspected on 11 November 2026. The `format` request's method-specific options belong under `args`; `max_bytes` bounds JSON-encoded content, and a returned continuation `id` means incomplete output. Vendor schemas/binaries are not republished here.
- C02 uses terminal `process`, `pwd`, and `program_status` with the same explicit session/block wrapper and empty object `args`. Their descriptions were read from the same running release. [Program Status Protocol](https://www.superlogical.com/rex/docs/build/program-status) supplies the report/lifetime/permission distinction; runtime tests above verify the named cases, not every behavior in that rolling document.
