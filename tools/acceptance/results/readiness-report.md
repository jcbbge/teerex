# Readiness acceptance outcome

Observe remains experimental on both platforms. The committed author-run records each contain three fresh API13 runs with R1–R11 passing; R12 remains unproven until the lead executes the supplied commands independently. Other cartridges have no readiness record and remain experimental. Ready-only installation currently selects zero items; no personal installation or ready promotion was performed. API10/12 CI results are unproven, and API11 is uncertified.

- [Linux record](../../cartridges/readiness/observe-x86_64-linux.json)
- [Mac record](../../cartridges/readiness/observe-aarch64-macos.json)
- [Hive baseline](readiness-hive-summary.md): 14/14 controls, 40 warm samples per arm and F1/F4 fixture.
- [Mac baseline](readiness-m5-summary.md): 14/14 controls, same sampling.
- [Actual-agent baseline](readiness-agent-summary.md): Codex and Claude, one run per condition; four correct reports, zero recorded interruptions/misdirected inputs, all owned panes and the inert sink closed. This is the minimum acceptance, not the default five-run sample.

The records were regenerated after rebasing U05: `--state`, its complete public suite and the embedded `items/send/draft.lua` input are included. Historical dated live observations are provenance, not fixture-certified behavior.

The baseline summaries identify their measured pre-U05 binary hashes; the new state contract is proven separately by the regenerated records.

The synthetic results establish explicit output, direct-child exit, cancellation, unknown-state and cleanup boundaries. They do not establish a performance or productivity improvement: the corrected F1/F4 arms count nine teerex-arm CLI/Rex execs versus six reference-arm execs, including diagnostic and cleanup calls. Both arms use the same counting wrapper. Server, GUI, neighbouring panes and whole-machine energy are excluded.

Verification on the reviewed source:

- `zig fmt --check build.zig src items tools/cartridges`: passed with Zig 0.15.2.
- `zig build -Doptimize=ReleaseSmall -Dtarget=x86_64-linux-musl`: passed; aarch64-macos cross-build passed.
- `python3 -m unittest discover -s tools/acceptance -p 'test_*.py' -v`: 7/7 on hive and M5.
- `python3 -m unittest discover -s tools/cartridges -p test_cartridges.py -v`: 25/25 on both machines.
- `python3 src/test_targets.py -v`: 15/15 on hive.
- Fresh-catalog `test_payloads.py --with-rex`: Linux 171 tests, 2 explicit skips; Mac 182 tests, 3 explicit skips. All applicable tests passed. Select the test Rex through PATH/REX_BIN; the first Mac invocation without that selection failed setup and was corrected.
- Three fresh `readiness.py --runs 3 --long` runs per platform: all 59 observation/state public tests pass per run (three explicitly root-only control methods use the combined CLI), exact N1–N6 equality, and zero peak sampled RSS growth after warmup in the 60-second wait. Both commands exit 1 with `failed_rows=["R12"]`, as required for author-run evidence.

Resolutions for planning:

- X1 retains compare's same-pane refusal. A separate same-pane equal-prefix/changed-tail fixture proves captured equality leaves full text unknown. Private evidence also keeps F1/F4 raw prefixes and true exits side by side.
- R6 pre-seeds manager lease/data/retired paths and warms the intentional missing-server route, whose Mac Rex client retains a start lock. Exact equality is retained. Nested public suites own separate private HOME directories; Python bytecode writes are disabled.
- R12 requires an independent lead execution before promotion. Executor labels attribute runs; they do not authenticate a caller.
- Phase B uses the explicitly approved, labelled, inert notification sink beside the visible agent tab. Task panes stay on private servers. The harness starts at the exact trusted workspace parent; fixture files/commands use an owned scratch child that is removed. No trust prompts are answered by the delivered runner. The personal trust-config checksum stayed unchanged during the final runs.
- Codex login shells reset PATH. Tasks therefore name the absolute counting wrappers; correct answers with zero counted calls fail acceptance. The preliminary zero-count probe is excluded from published measurements.

Raw packets, captures, registry tokens, model reports, local paths and pane IDs are private evidence and are not published here. Existing installed-payload skips retain their original reasons. The upstream request and still-unsupported guarantees remain in [the accepted rubric](../../../docs/planning/workloads/readiness-acceptance.md#9-host-blocked-upstream-rex-request-one-paragraph-for-rex-upstreammd).
