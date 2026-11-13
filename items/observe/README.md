# observe

[Operator/agent addendum: Who, What, When, Where, Why, How](../../docs/concierge/features.md) covers current alpha.5 use, platform/API support, verification, privacy and lifecycle. [Install/upgrade current alpha.5](../../docs/concierge/setup.md); [release support](../../docs/releases/v0.1.0-alpha.5.md) and the [independent experimental observation cartridge](../../docs/cartridges.md) are separate from dated increment evidence below.

**Experimental incremental implementation of Phase 3 #1.** A small Zig CLI returns bounded terminal text plus C02 process, last-reported-directory and program-status evidence as JSON. C03 adds an explicit offline comparison of two observation files, not activity/completion interpretation. C09's `watch` adds a bounded foreground wait for changes or selected status-report evidence against an explicit baseline, reusing those same evidence rules. This is still not the complete proprioception packet, a ready cartridge, an installer, or a general Rex client. Phase 3 #8 contributes only the five concrete bindings observation needs: `server.version` and terminal `format`, `process`, `pwd`, `program_status`.

API10–13 acceptance without server restart/update first shipped in the compatibility-only [v0.1.0-alpha.2](../../docs/releases/v0.1.0-alpha.2.md); alpha.1 required API13. The alpha.2 guide preserves39 checks per actual API10/12/13 disposable build and separately attributed M5/API10 evidence. Current alpha.5 also supports Linux live observation; API11 and the exact mixed-host issue #10 topology remain uncertified. Dated validation sections below retain their original builds/results.

## Contract and limits

- Select full `session:UUID` / `block:UUID` explicitly. The combined root defaults a missing `--socket` from percent-decoded `REX_SERVER` (`unix://` only), then the platform path. `--socket ABS` overrides both. No current-focus, label or ID-suffix fallback selects session/block.
- One explicitly attached `rex do --session FULL --block FULL` runs fixed embedded Lua and five serial supported reads, using `--autostart=false`, an explicit endpoint and a three-second Rex connection/request timeout. Values arrive as JSON arguments, never interpolated source; no configuration is installed. Each response is re-encoded and checked against 128 KiB at the Lua boundary, not before Rex allocates/decodes it. A bounded aggregate buffer independently caps collector output; stderr retention is 4096 bytes. Required RPC/decode/size-limit failures produce no success packet, not fabricated empty evidence.
- Live `observe` and `watch` support Apple-silicon macOS and Linux x86_64. Standalone `observe --timeout-ms N` defaults to **5000 ms**, range **100–60000**. Its supervisor bounds collection, including a stalled executable, then applies the same TERM/KILL/drain limits as `watch`. Deadline exits **124**, SIGINT/SIGTERM **130/143**, with no success JSON from an interrupted sample. Preflight, final serialization/stdout backpressure and kernel stalls are outside a hard real-time promise. Offline `compare` still needs neither Rex nor macOS.
- Output includes an observation ID, client observation time, exact requested target, actual server version/platform/API revision, and bounded capture. Integer API revisions10–13 are accepted; an out-of-range refusal names the found revision. Missing bindings/invalid evidence still fail. Revision acceptance does not authenticate the server or certify every old-build behavior. Exact source identity, including revision, is still required for comparison/waiting; no baseline crosses a server revision change silently.
- The capture is **screen and scrollback**, not necessarily the visible viewport. Rex returns a **prefix** when limited; this may omit the latest prompt. `capture.complete=false` makes that omission explicit. `observe --tail` (API13) instead returns the longest newest suffix that fits the encoded byte budget, using the original capture’s stable blob ID and total when continuation is needed. `capture.portion="tail"`, `view="latest"` and `incomplete_at="start"` identify omitted older text. Complete latest captures have null `incomplete_at`. Prefix captures retain their original five-field shape, with no additional capture members. Neither partial view establishes unseen content.
- `--max-bytes` limits the JSON-encoded **content string**, including its two quotes, not the whole JSON packet or Rex's internal capture memory. Default 4096; range 256–65536. Unicode and escaping count toward this budget. The tested Rex counts the escaped string body without the quotes, so teerex reserves those two bytes before requesting and independently checks the returned string. `atomic_snapshot=false`: no atomicity, ownership, completion, process-state, or permission inference is made.
- Reads only: no input, session creation, focus/layout changes, configuration edits, background service, or file writes by teerex. The Rex CLI still opens/attaches/closes observation connections. It has the account's full Rex authority; this command is not a security sandbox.
- Unix transport is explicit, not proof of physical locality: a socket can be an SSH forward. Direct invocation uses the selected Unix socket, not a raw HTTP/SSH URL. Alpha.5's shared named-host route executes teerex on an explicitly configured command host; it does not configure socket forwarding, change hosts files, deploy a VPS or certify attached foreign-block observation.
- Terminal content is untrusted data and can contain secrets. JSON is escaped but **not redacted**. Keep observations out of Git, logs and external services unless reviewed. Target/Rex/compatibility failures produce no success JSON; usage errors exit 2, operational failures exit 1. Consumers must check the exit status as well as parsing JSON, since a stdout write failure can leave partial output.

## Target-routing diagnostics

When Rex exits unsuccessfully, observation retains its bounded error and prints the **requested** server/session/block plus a same-executable, explicit-`--server` comparison hint. This is not an authenticated report of where a wrapper actually connected. Observation runs the trusted `rex` selected by `PATH` unless combined root `--rex ABS` pins an explicit executable; it removes `REX_SERVER`, `REX_SESSION`, `REX_BLOCK`, `REX_CLIENT`, and supplies `--server unix://…` explicitly. No alternate host, SSH route, focus target or retry is requested. No extra discovery RPCs or successful observation fields are added. Watch keeps its existing failed/unknown result and any last accepted comparison, not invented current evidence.

For [issue #10](https://github.com/jcbbge/teerex/issues/10), a successful `REX_SERVER=… rex block capture` is not yet proof of the same route: a wrapper can treat environment-only selection differently from `--server`. The public [agent-core wrapper change](https://github.com/jcbbge/agent-core-public/commit/7632b9c4c2ed86e14eafe62cee2076ef5286fc15) contains exactly that distinction. Its presence in the reporter's failing invocation has **not** been verified. Nor does unspecified adapter success prove capture of the exact failing target.

With separately authorized read access, compare on the CLI host using one reviewed absolute `REX` executable and the exact private `SOCKET`, `SESSION`, `BLOCK`. The executable must be the one selected by teerex's `PATH` or combined root `--rex ABS`; inspect any wrapper rather than assuming it honors either selector. Keep diagnostics, host/instance IDs and any captures private. Do not install, restart, reconfigure or mutate a live pane for this check:

```sh copy Copy Routing Checks
# Supply REX, SOCKET, SESSION and BLOCK from the authorized target record.
# Record the PATH selection and inspect any alias/function/wrapper first.
command -V rex
"$REX" version
shasum -a 256 "$REX"
# Match teerex's cleared target hints; aliases/functions are not its PATH executable.
rex_at() { env -u REX_SERVER -u REX_SESSION -u REX_BLOCK -u REX_CLIENT "$REX" --autostart=false --server "unix://$SOCKET" --timeout 3s "$@"; }
rex_at api call server.version
rex_at api call server.status
rex_at session ls --json
rex_at block ls --session "$SESSION" --json
# Fixed full IDs only; this JSON must not contain labels or user-supplied source.
TARGET=$(printf '{"session_id":"%s","block_id":"%s","max_bytes":256}' "$SESSION" "$BLOCK")
READS='local a=rex.args; for _,m in ipairs({"format","process","pwd","program_status"}) do local v,e=rex.call("com.superlogical.terminal."..m,{session_id=a.session_id,block_id=a.block_id,args=m=="format" and {format="text",max_bytes=254} or {}}); if not v then error(m..": "..tostring(e)) end; print(m,rex.json.encode(v)) end'
# Both collect the exact target; output may include private terminal content.
rex_at do --session "$SESSION" --block "$BLOCK" -e "$READS" --args "$TARGET"
# Bypass CLI target resolution, but still explicitly attach the same session.
rex_at do -e 'local v,e=rex.call("session.attach",{session_id=rex.args.session_id}); if not v then error(e) end;'"$READS" --args "$TARGET"
# Also compare individual explicit-ID RPCs; api call performs its own attachment.
for method in format process pwd program_status; do
    if [ "$method" = format ]; then ARGS='{"format":"text","max_bytes":254}'; else ARGS='{}'; fi
    RPC=$(printf '{"session_id":"%s","block_id":"%s","args":%s}' "$SESSION" "$BLOCK" "$ARGS")
    rex_at api call "com.superlogical.terminal.$method" "$RPC" || break
done
```

Check every exit and retain the exact failing method, executable path/hash/version, server version/host/instance identity, and selected block's `host_id` privately. If both attached Lua routes and direct RPC fail against that endpoint, removing CLI scopes does not make the target readable. If explicit-ID RPC **and explicit-attach Lua** succeed while scoped Lua fails for the same executable/endpoint/IDs, preserve that distinction as Rex target-resolution evidence. A `host_id` difference alone neither proves unsupported observation nor identifies the server/API of the terminal host. Numeric API acceptance is not mixed-host certification.

Disposable Linux/API13 investigation on 12 November 2026 used checksum-pinned Rex preview.16 (`aa2db1b21261b479a550559fb70e2c3a66c07ba2`). Both same-server targets passed scoped Lua, explicit-attach Lua and all four direct RPCs. Removing scope **without attachment** failed even for a valid target with `conflict: stream is not attached to session`. Cross-server absent targets failed through all attached/direct routes. Two distinct server/state directories and a synthetic local wrapper with the public wrapper's environment-versus-flag selection boundary reproduced successful environment-only capture plus teerex's session-scope error; poisoned environment still observed the explicit selected target. This is a controlled routing counterexample, **not reproduction of an attached Mac/API10 block on Linux/API13**. No supported-domain routing defect has been established. The diagnostic change does **not** resolve #10: the reporter's exact PATH executable and same-explicit-endpoint comparison, or an equivalent attached-host fixture, remain necessary.

The new regression fails on the unchanged alpha.4 source executable because failures omit the requested endpoint/routing hint. After the diagnostic change, `python3 items/observe/test_observe.py -v` passed **29 tests** on Linux/API13 and on disposable arm64 macOS **26.3.1** with official preview.13/API10 and preview.16/API13. Those Mac controls are not the reporter's `d018d2` build or the reported mixed-host topology. Existing bounded capture, baseline/source checks, serial collection, later-failure evidence and cancellation behavior are unchanged.

## What C02 adds and teaches

The new nodes are additive to output `schema_version=1`. Each names its exact method, its evidence `basis`, `freshness="unknown"`, and `data`. Explicit nulls mean an observation/report is unavailable, not an empty path or a successful operation. These are server-provided facts/claims; teerex does not independently inspect processes or authenticate reporters.

| Node | What is retained | What it does **not** establish |
| --- | --- | --- |
| `process` / `rex_observation` | Rex's child and foreground process: PID, name, readable per-process `cwd`; terminal-program `last_exit.exit_code`. Missing process/cwd is null. Other process metadata, executable/argument paths, user/home information and ancestor lists are deliberately not exported. | The foreground process is not necessarily the terminal's original child. `last_exit` is for the terminal's program, not every shell command, descendant or status record. Null `last_exit` can mean running **or** no owned program; it is not a running flag. |
| `reported_directory` / `terminal_report` | The exact last-reported `pwd` string, including a `file://` URL when that is what the program emitted, plus reported owner PID/name when Rex can identify it. Missing report/owner is null. | This is not a verified filesystem path or process cwd. It may survive a directory change or process exit. No report timestamp is supplied by this binding, so `reported_at=null`; teerex does not substitute query time. No URL is followed, path resolved, or file opened. |
| `program_status` / `program_reports` | Every returned root/child record, preserving state, app/effective_app, kind, progress, title/message, owner and server-clock `updated_at`. Optional missing fields become null; root ID is null; zero progress stays zero. | Empty records mean no retained reports, **not idle/done**. `done`/`error` may outlive a process. A blocked `permission` report requests a decision; it never grants authority. Messages are untrusted plain data, not instructions or task classifiers. |

`observation_started_at_unix_ms` and `observed_at_unix_ms` bracket the serial reads using the **client wall clock**. They are not per-field event timestamps, a monotonic deadline, or a freshness guarantee. The status `updated_at` is the **server's** clock. No clock synchronization is assumed, no cross-clock age is calculated, and no field is silently marked fresh just because it was queried recently. Even matching owner PID/name is attribution, not freshness, identity authentication or ownership enforcement; processes can change state and IDs can be reused. `atomic_snapshot=false` still applies.

The 128 KiB re-encoded response cap applies to each metadata RPC and initial capture. A tail continuation alone allows at most 512 KiB transiently, then emits only the requested encoded-content budget. Metadata is **not** limited by `--max-bytes`, paginated, cached or silently truncated. Very large status results fail rather than falsely appear complete. This is a retained-output bound, not a Rex/runtime memory ceiling. Capture, cwd and status can contain private data despite the deliberately small process-field selection.

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

The command requires matching exact server/session/block strings and matching Rex version/platform/API revision. Schema version 1, integer API10–13, prefix/screen-and-scrollback capture, and the current evidence method/basis/unknown-freshness labels are required. Unsupported/malformed/incompatible/oversized inputs fail without success JSON. Compared fields are typed; unrelated additive fields are ignored. Object-key order and top-level observation IDs/client timestamps do not create evidence changes. Status timestamps **are** retained report data and are compared as strings, not interpreted as ages.

`before` and `after` are **caller-supplied order**, not independently verified chronology. Wall clocks can move backwards. Matching labels/IDs do not authenticate files, prove they came from Rex, prove the server never restarted, or establish shared observation time. The five live reads remain non-atomic; no continuous observation or no-intermediate-change guarantee follows from equality. `interpretation="none"` is explicit: no activity, phase, confidence, success/completion, freshness or permission classifier is implemented. Generic semantic interpretation remains deferred. The separate [filter and opt-in historical cache](../filter/README.md) preserve these evidence/unknown boundaries; neither turns a comparison into a fresh-state or permission verdict.

Saving observations is an explicit caller choice, not automatic history. If redirecting stdout, use owner-only files (for example, set `umask 077` **before creating them**) in an ignored local location and check each observe command's success before comparison. Git ignore rules do not protect secrets. Comparison output still contains target/observation identifiers and is **not a redaction or authenticity boundary**; review it before sharing too. No paths or URLs inside a packet are opened or followed.

## What C09's bounded observation wait adds and teaches

`watch --socket PATH --session session:UUID --block block:UUID --baseline FILE --timeout-ms N [--interval-ms N]` implements the read-only `observe_until_changed` portion of Phase 3 #3's C09, using Phase 3 #1's observations/C03 comparisons. Its optional status predicate is described below. It is a single foreground invocation, not a daemon, subscription, completion detector, input controller or new cartridge. It never runs a command in or sends input to the observed terminal.

Status watches accept `--timeout-ms` from **100..86400000 ms** (24 hours), or `--no-deadline` instead. `--no-deadline` requires a status predicate and is mutually exclusive with `--timeout-ms`; it waits until matching evidence, a collection error, or SIGINT/SIGTERM. Its `limits.timeout_ms` is null. Exit 124 occurs only for a real deadline; cancellation remains 130/143 and collection errors remain 1. Plain change watches retain the **100..60000 ms** cap.

The baseline must be a valid observation file of at most **1 MiB**. The separately supplied socket/session/block must match it exactly **before contacting Rex**; file contents cannot silently select a different endpoint. Every live sample must match the baseline's target, source version/platform/API revision and supported provenance. Each sample uses the baseline's capture budget. No implicit baseline, focus fallback, byte-budget override or rolling-baseline reset is added. Identifiers/labels are not authentication, authorization or server-instance identity; a server restart with the same labels/version is not detected.

Every sample compares against the **original baseline**, not the previous poll. A known field-value change **or an evidence-availability change** wakes the wait. A newly available exit report is not inferred success; a disappearing process record is not an invented completion transition. A change in capture completeness is an availability change for full text. A retained status timestamp can wake the wait even when its state/message is unchanged; it is changed report evidence, not proof of useful activity. Unavailable evidence and equal incomplete prefixes stay unknown where C03 says unknown. No sampled equality proves that no intermediate changes occurred.

The monotonic collection budget follows the limits above; `--no-deadline` disables it for status watches. When present, it covers polling delays and collection, including stalled Rex subprocesses. The interval defaults to **250 ms**, range **50–5000 ms**, **after each collection finishes**, not a fixed sampling frequency. One persistent, supervised Rex/Lua connection performs the same five serial reads for every sample; API revision is checked each time. This removes five client launches plus a teerex collector per sample, not the reads or their non-atomic/staleness limitations. No direct socket protocol or server subscription is added. One baseline, one bounded frame buffer and one last accepted comparison survive; each decoded sample's arena is freed. No private capture is automatically saved or repeated in the wait result.

The shared platform-specific process-group supervisor owns only the persistent collector and its subprocesses, **not the observed terminal/process or Rex server**. At a deadline or cancellation, a stalled collection gets TERM then KILL after at most 250 ms, or immediately when its leader exits; pipe drain is limited to 500 ms. A satisfied predicate also requests collector cleanup, not termination of the observed program. Signals remain handled during poll gaps. Cleanup may extend the requested deadline by 500 ms plus scheduling. Baseline/file/environment preflight, kernel stalls, final JSON serialization/stdout backpressure and SIGKILL/crash of teerex are not a hard real-time guarantee. Detached/re-grouped collection descendants remain outside the cleanup scope. `all_descendants_verified_gone=false` is explicit, and `last_collection_cleanup` reports the collector group's signal results, not whole-tree verification. Current live support includes Apple-silicon macOS and Linux x86_64; `run` remains Mac-only.

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

Add `--status-state idle|working|done|blocked|error` to wait for one report, not any change. Repeat the option for OR matching, for example `--status-state done --status-state error`; duplicate states are usage errors. All states select the same record. `condition.states` lists the requested states and `condition.matched_state` names the accepted state (null without a match). The existing `condition.state` remains the selected state for one-state watches and is null for multiple states. `matched_status_report` retains the matching record evidence. Without `--status-id`, the selected record is the **root (null ID)**; a supplied ID matches exactly, so the literal ID `root` selects a named child, not the root. IDs must be nonempty and at most 1024 bytes. A status ID without a state is a usage error.

An identical retained matching record in the baseline does **not** satisfy the condition. A different report for the selected ID that matches the state does; unrelated records, text/cwd changes, disappearing reports and nonmatching states do not. Equality includes every retained record field and the server-clock timestamp, not just its state. Newly available matching evidence can qualify even when the baseline had no report: this proves neither when the program emitted it nor that it is fresh. There is no cross-clock age calculation, owner authentication or same-process continuity guarantee.

A deadline with no matching evidence is still `deadline_exceeded`, with explicit condition, last comparison and nullable unknowns. No retained report does not prove that the program is unsupported: teerex cannot distinguish “never reports” from “hasn't reported yet.” `done` remains a program claim even while its process runs, and `blocked:permission` grants no authority. No status interpreter or completion detector is added.

## Build and invoke individually

Building requires Zig **0.15.2**; released installation needs no compiler. Live observation requires an existing compatible Rex CLI on `PATH` (or combined root `--rex ABS`) and an already-running selected server; offline comparison needs neither Rex nor a server. Current native targets are Apple-silicon macOS and Linux x86_64; exact dated validation results are recorded below. No system-wide installation or Rex configuration is required.

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

## Declared presentation views

`compare` and `watch` accept either `--view progress-v1` or `--view-rules FILE`, explicitly per invocation. Audit the compiled rules with `teerex compare --view progress-v1 --print-view`. No view is selected through configuration or the environment. The same engine serves [filter](../filter/README.md).

A view adds `view` beside raw comparison evidence. `captured_text` and `full_text` verdicts are `unchanged`, `cosmetic_only`, `changed` or `unknown`. Raw flags retain their meaning. Every differing matched span carries its exact before/after strings, zero-based line and byte offset. At most 64 spans are returned; overflow forces `changed`. Protected error, prompt, permission and confirmation lines are never masked. A partial capture always has `full_text: unknown`; views cannot see a hidden tail.

`progress-v1` declares braille/star spinners, `(Ns`/`(Nm Ns` elapsed counters and numeric token counters. Other shapes fail safe as text changes. Custom rules are strict UTF-8 JSON, at most 16 KiB, with `schema_version:1`, `kind:"rex_presentation_view"`, an `id`, optional `note`/`protect_also`, and 1–32 unique rules `{id,position,pattern}`. IDs use 1–64 bytes from `[a-z0-9._-]`. Positions are `anywhere` or `line_start` after spaces/tabs. Patterns have at most eight tokens and 256 bytes: literal text, escaped braces `{{`/`}}`, `{digits}` (1–12), `{number}` (optional fraction up to six digits and k/K/m/M suffix), or `{one_of:CHARS}` (1–32 distinct Unicode code points). Variables need a literal between them. Two non-whitespace literal code points anchor a rule; a single wholly non-ASCII glyph set plus whitespace is the sole exception. Matches use declaration order, greedy tokens without backtracking, and never cross a line. Protected substrings are fixed and extendable through `protect_also`; terminal `?`, `:` and `>` also protect a line. Canonical fixed-order compact typed rules JSON defines `rules_sha256` (optional fields receive their null/empty defaults).

`watch --view progress-v1` keeps the same baseline through cosmetic comparisons. A meaningful text or non-text change, or unknown whole evidence method, wakes it. An optional value absent in both samples with unchanged availability (for example `process.last_exit`) is no new non-text evidence; a missing whole process/directory/status method remains unknown and wakes. An availability transition always wakes. Raw changed/availability/unknown lists are retained. The receipt adds `view`, `cosmetic_only_comparisons`, `last_cosmetic_spans` and `view_rules_sha256`.

Views exclude `--status-state` and `--no-deadline` (usage error). Exit 124 remains `deadline_exceeded`; cosmetic counts are evidence, not busy, working, idle or done state. A quiet deadline is not completion. No new Rex reads or writes, focus, input, cache mutation or recognition behavior is introduced. Prefix captures retain their existing boundary; a future latest-view capture needs its own comparability contract.

Invalid rules exit 2 before Rex contact, without JSON: `teerex: view refused: REASON`. Reasons are `view_flags_exclusive`, `builtin_unknown`, `rules_unreadable`, `rules_too_large`, `rules_schema`, `rule_id_duplicate`, `rule_pattern_invalid`, `rule_unanchored`, `rule_token_limit`, `view_not_applicable_to_status_wait` and `print_view_requires_builtin`. Other verb exits are unchanged.

## Socket defaults and latest capture

```sh
# REX_SERVER supplies the endpoint; session/block still require full IDs.
teerex observe --session session:FULL-UUID --block block:FULL-UUID --tail --max-bytes 4096
```

The combined root selects a socket once for socket-taking leaves. It exports `TEEREX_SOCKET_SOURCE=REX_SERVER|platform_default` only when it supplies a default. Observe/watch/doctor and boards probe include that default source as `socket_source` in their JSON. Explicit-socket invocations keep their original output, without an added source field. Other leaves currently omit the field. The environment URI is percent-decoded, rejects NUL/relative paths and non-Unix schemes, and does not silently fall back when invalid. Without that variable, defaults are `~/Library/Application Support/rex/server.sock` on macOS and `/run/user/<uid>/rex/server.sock` on Linux. Explicit sockets override even an invalid environment URI. Offline leaves get no socket, and named-host routing retains its configured endpoint. Root help and each item's own explicit-socket entrypoint remain available; standalone cartridges do not inherit combined-root defaults.

`--tail` requires observed API13; prefix remains the default on API10–13. Initial `format` reports a stable blob ID and raw byte total for incomplete captures. Tail reads once near that blob's end, with four bytes of overlap and a JSON-encoded response allowance bounded by six times the requested raw window. The overlap excludes replacement artifacts from an unaligned UTF-8 start; final trimming preserves whole characters and counts JSON encoding, including escaped control/HTML bytes. The blob ID, total, byte count and EOF must agree. No recapture, newest-blob implicit ID, unbounded continuation loop or full-scrollback retention is used. Process, directory and status queries remain serial and non-atomic.

Watch inherits the baseline's prefix/tail mode. Comparisons of incomplete captures with different portions or budgets report captured-text change as unknown; complete captures remain comparable. Full-text change remains unknown whenever either capture is partial. Tests for these additions run in the existing observe suite on all CI lanes; actual continuation tests select API13 explicitly.

Socket defaulting changes argv in the running process. It does not re-execute teerex, create a supervisor, pipe stdout or rewrite output. Existing `finish()` call-log handling remains in place. The native receipt helper uses the original serializer unchanged unless this root invocation supplied a default; Python probe receipts use the exported source. Standalone cartridge entrypoints still require their original explicit arguments.

Compatibility: a saved latest capture requires the explicit `capture.view="latest"` marker as well as its portion and omission metadata. A legacy packet with only `portion="tail"` remains invalid. Shared validation, filter/cache round trips, maneuvers and replay therefore retain the original prefix schema and refusal rules. Root defaults do not override managed-agent configuration or the optional selector in `jobs doctor`. Bare doctor/adapters invocations and incomplete live-target arguments retain leaf usage errors; request defaulted doctor discovery with an option such as `doctor --timeout-ms 5000`.

## Agent state (U05)

`teerex observe --state --socket /absolute/server.sock --session session:FULL-ID --block block:FULL-ID` returns a read-only JSON interpretation. Python 3 is required. `--max-bytes` defaults to 65536 (256–65536); `--timeout-ms` defaults to 5000 (100–60000). Targets are explicit canonical lowercase IDs. Combined-root socket defaults also apply to `--state`, with `socket_source` recorded when defaulted. `--tail` and `--state` are separate modes; their combination is refused. State retains its bounded complete-VT requirement rather than treating a partial tail as complete evidence. Normal `observe`, `compare` and `watch` retain their contracts.

The receipt names `harness` (`claude`, `codex`, `pi`, `shell`, `unknown`), `state` (`idle_prompt`, `working`, `awaiting_choice`, `awaiting_text`, `error`, `exited`, `unknown`), nullable `draft_present`, `evidence_lines`, `state_basis`, `reason`, `capture_complete` and the unmodified `osc7501` records. It includes collection times and marks `atomic_snapshot:false`, `read_only:true`, `freshness:"unknown"`, and `completion:"not_inferred"`. No input, focus, acknowledgement, hooks or files in the target are changed.

This is a conservative heuristic, not task completion detection. Complete bounded VT, nearby recognized prompts/interrupt indicators, menu headings plus options plus navigation keys, process identity and recorded process exit supply evidence. Conflicting harness identity or a partial prefix returns `unknown`; long real panes will therefore often be unknown. An OSC root working/error/permission/question report can supply otherwise missing state, with explicitly unknown freshness. An idle/done report alone never proves an idle screen or completed task. Recorded process exit describes the process, not success of its assignment.

Draft detection embeds the **same source** as [send's guard](../send/draft.lua), including dim/grey suggestions, NBSP and styled cursor movement. Pi's horizontal editor lines pass through that parser too. Evidence masks prompt drafts; `draft_present:null` means the relevant editor was not established. Other displayed evidence and preserved program status can contain application text; this is not a transcript redactor. Screen heuristics can be fooled by application output imitating its UI and remain observations, never authorization to send.

Fixtures draw Claude and Codex styled prompts, busy/permission/error states, and Pi 1.4.0's installed horizontal editor/status/trust UI. Pi UI shapes were read from its installed `custom-editor.js`, `status-indicator.js`, `trust-selector.js` and pi-tui `editor.js`; these are fixture shapes, not a claim that all versions render identically. Run `python3 items/observe/test_state.py -v` with a disposable Rex available on PATH. The suite also covers partial captures, ambiguity, real drafts, recorded exit and OSC done without inferred completion.

A read-only hive API-13 check on 13 November 2026 found the real Codex replay pane idle with a dim placeholder and no draft. The lead Claude pane rendered `· Gesticulating… (3h 31m 1s · ↓ 200.2k tokens)` above its input; that observed elapsed/token spinner shape is covered alongside its Esc-to-interrupt shape. No live Pi process was exercised; Pi coverage is installed-source-derived fixtures. Mac behavior remains for the Mac CI lane to establish.
Cartridge readiness covers observe, compare and watch together. The [readiness runner and contract map](../../tools/acceptance/README.md) record actual whole-contract evidence per platform; build success alone leaves the item experimental.
