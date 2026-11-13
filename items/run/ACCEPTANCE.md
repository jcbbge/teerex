# `run-visible` acceptance — 13 November 2026

**Delivery state:** leaf implementation, help, WWWWW+H contract, dedicated public tests and opt-in Rivet patch, based on public `origin/main` **0da427f1706093c1d216c541d69ce6a80fa81bec**. Root help/dispatch/target injection and combined source shipping are integration-owned. Published alpha.5 is unchanged and does not contain this capability. This record is not a production/fleet certification or claim that issue #20 is already released.

## Combined source integration

The later integration wires root `run-visible` help/dispatch and named-host socket injection, without changing legacy `run` or adding a Zig dependency. Its exact combined executable passes `test_visible.py` **13 tests** and `src/test_targets.py` **10 tests** on Linux/Python3.13.5 and native macOS26.3.1/Python3.14.3; Mac system Python3.9.6 also passes all13. The former combined input/old-API test was split so CI can select `VisibleTest.test_observed_api_gate_precedes_creation` against actual older servers. Checksum-pinned Mac API10/API12 each pass that refusal before creation. Legacy Mac run11, surfaces15 on both, send10/spawn7/child4 on both, unchanged agents12 with both integration gates on both, and fleet11 on both pass as adjacent controls. Exact pushed-head hosted CI remains separate from these local results.

Current setup/changelog/agent handoff explicitly separate this source build and `targets exec --tty` from immutable alpha.5 release bytes. The Rivet adapter is still opt-in/unapplied with fallback/guards retained; #14/#21, #16 deeper routing, native GUI painting and real harness/fence/service/fleet-board cutover are not completed here. The table and12-test record below preserve the initial standalone leaf acceptance, rather than relabeling those runs as the later combined source.

## Real runtimes and executed checks

All Rex servers used private random disposable sockets, `/dev/null` config, private state, restore disabled and only test-created sessions/panes. No personal M5/hive/default socket or running service was accessed or restarted. Rex and Zig archives were SHA256-checked against the existing CI pins; no vendor binaries are committed.

| Runtime | Version | Executed result |
| --- | --- | --- |
| Linux x86_64 orb | Python 3.13, Zig 0.15.2; Rex preview.16/API13, commit aa2db1b21261b479a550559fb70e2c3a66c07ba2 | `python3 items/run/test_visible.py -v`: **12 tests OK** |
| Mac arm64 satellite, macOS 26.3.1 | Python 3.14.3, Zig 0.15.2; same preview.16/API13 | Same **12 tests OK** |
| Same Mac, system Python 3.9.6 | kqueue exit observation (this Python has no `os.waitid`) | Same **12 tests OK**, including real deadlines/signals and group cleanup |
| Same Mac, legacy `run` control | API13, current unchanged run source | `python3 items/run/test_run.py -v`: **11 tests OK** |
| Linux and Mac, public surfaces control | preview.16/API13 | `python3 items/surfaces/test_surfaces.py -v`: **15 tests OK** each |
| Actual older Mac Rex | preview.13/API10 and preview.14/API12, existing CI checksum pins | Explicit `run_visible_requires_observed_api13`, exit1, zero sessions/terminal creation |
| Mac controller → real Linux Rex | Temporary loopback Unix/TCP proxy between disposable hosts, no shared launch directory | `pane_identity_unavailable_or_foreign_host`, actual exit unknown, no argv permit; identified pane closed and absence verified |
| Actual patched Rivet export | Bun 1.4.4 + disposable Linux/API13 | Literal argv/env/cwd/stdin, merged output, exit0/7, 2.1 MB tail and owned-pane absence passed; fallback retained |

Standalone build/test invocation is in [VISIBLE.md](VISIBLE.md#development-and-integration). It uses the same run module and unchanged public surfaces module, without touching shared root/build/targets. Combined CI on the integration head remains a separate check.

## What the 12 public tests establish

1. Literal asymmetric argv: empty, quotes, newlines, Unicode and injection-looking text; exact cwd/env and binary stdin through EOF; actual pane metadata instead of poisoned inherited target hints; only the new pane closes, unrelated pane/focus remain.
2. Anchored right-hand 23% placement uses public measured geometry; `--keep-open` leaves the exited terminal attached; actual OSC7501 `done`/app/title read back through `program_status`.
3. Actual exit0, exit7 and SIGTERM remain separate facts. 3.2 seconds of silence does not become a synthetic exit.
4. Split UTF-8, NUL, invalid binary stderr, trailing newlines and final drain are byte-exact. A four-byte retained prefix split inside a Unicode scalar is base64, not lossy replacement. Five MB emitted with only257 retained raw bytes remains bounded and correctly counted.
5. Full-output files are readable **after return**, with private modes, separate stdout/stderr contents and complete flags. Crossing64 MiB stops the child and marks full files incomplete; total retained full-file data remains at the cap.
6. Deadline and controller INT/TERM stop TERM-resistant fixtures, retain partial output, record actual SIGKILL, override keep-open, and verify owned-pane absence. Actual `working`/app/title is read back while the child is still running.
7. Missing cwd, missing executable, malformed/reserved env, FIFO stdin and unsupported version refuse without shell/cwd fallback. Usage and launch refusal remain distinct. Old-version refusal is also exercised against real older Mac builds outside the API13 suite.
8. A real creation request with **all ACK frames dropped** leaves one real pane, no known created ID, no execution permit, no retry or unsafe guessed close. Earlier-created-ID/final-frame loss retains the ID and requests one close; requested argv never starts. A real close with all ACKs dropped keeps cleanup unknown even though an independent read sees the pane absent; no second close.
9. A changed observed kernel identity, injected at the real pane's readiness boundary, refuses before argv and requests exactly one owned close. This fault injection is separate from the actual Mac→Linux host refusal above; no adversarial host-authentication claim is made.
10. Closed pipes with a live child do not establish exit. Normal exit cleanup stops a same-process-group child while a deliberately detached child survives; the harness verifies and explicitly kills only its detached fixture. An unrelated sentinel remains.
11. Actual helper SIGKILL leaves the command's actual exit **unknown**; closing its pane does not kill the escaped child. The test proves that survivor exists, then kills only its known fixture. No process-tree/remote-death guarantee is invented.
12. Actual controller SIGKILL yields no fabricated final receipt or cleanup. The launch directory retains known IDs and unattempted cleanup intent. The surviving in-pane helper enforces its own deadline and records actual SIGKILL, while the pane remains for reconciliation.

## Visual inspection and limits

Actual `com.superlogical.terminal.format` HTML for retained success and exit7 fixtures was rendered in Chromium at2× and inspected. It showed the command's live terminal text and independently read OSC `done`/`error`/app metadata; raw receipts separately established actual exit0/7. Captures are attached to the implementation thread. These are **API terminal-content readbacks, not Rex.app GUI-placement screenshots**; the CLI/server satellite did not include the separately distributed tester GUI. Public API layout attachment, rectangles, labels and focus were checked, not native GUI painting/palette click interaction. No pointer/keyboard UI behavior was added by this noninteractive argv command.

## Issue #20 coverage and remaining delivery

The implemented boundary covers visible tab/anchor lifecycle, explicit literal argv/cwd/env/stdin, OSC status with app/title, real exit/signal, bounded raw prefixes, deliberately retained full-file lifetime, deadlines/cancellation, default identified-pane close, keep-open and honest lost-ACK/controller-loss semantics on tested Mac/Linux API13. Legacy run remains unchanged and passed its real Mac suite.

**Not claimed:** published root support/release, actual Rivet fleet cutover, removal of `rex-tab.ts` or its polling, real harness/fence parity, every API/build, remote child death, authentication against same-account code, personal-host certification, fleet board/#13 call-record integration, or automatic Rex restart/update. The [migration candidate](MIGRATION.md) is checked and exercised against the actual reference export but still needs the owning integrator's combined checks and the Rivet owner's disposable service/fence acceptance before any cutover/deletion.
