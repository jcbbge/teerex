# Build and regression CI

[The workflow](../.github/workflows/ci.yml) runs on pull requests and pushes to `main`. It does not release, deploy, create tags, install a service or change Rex configuration. Its token has only `contents: read`; checkout credentials are not persisted. No repository secrets or paid/larger/self-hosted runners are required. Standard hosted runners are free for this public repository; changing repository visibility requires reviewing that assumption.

## Required lanes and coverage

| Check | Explicit runner | Selected coverage |
| --- | --- | --- |
| Linux API13 and Apple-silicon cross-build | `ubuntu-24.04`, x86-64 | Static musl CLI, child supervision, observe/compare/watch, send/spawn, adapters/jobs, offline maneuver/library/filter/cache/doctor, installer, cartridge lifecycle/native payload contracts and Mac cross-build. |
| Mac API10 (Rex preview.13) | `macos-26`, arm64 | Child supervision, observe/compare/watch, run/send/spawn, doctor, adapters and offline maneuver/library/filter/cache. |
| Mac API12 (Rex preview.14) | `macos-26`, arm64 | Same public suites as Mac API10. |
| Mac API13 (Rex preview.16) | `macos-26`, arm64 | Same public suites plus API13 jobs/offstage, installer controls, cartridge lifecycle and native installed-payload offline/runtime suites. |

Every lane checks Zig formatting and builds `ReleaseSmall`. Zig **0.15.2** is downloaded from its versioned official archive and checked against the platform-specific SHA-256 from [Zig's download index](https://ziglang.org/download/index.json). Python **3.13** is selected explicitly. GitHub actions use immutable commit pins. There is no `zig build test` interface: CI invokes the listed Python public-CLI suites and `zig test src/child_test.zig` directly.

The four cells continue independently when another fails. Tests are not retried, allowed to fail or skipped for missing dependencies. A failed download, checksum, startup, wrong architecture/OS family or regression fails its lane. Platform/revision-specific steps are deliberately selected; Linux alone is not full integration coverage. Linux run/doctor runtime and API10/12 offstage are unsupported, not covered by a successful cell. Branch-protection settings are unchanged.

The [official runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) lists `macos-26` as standard Apple-silicon/arm64. CI checks arm64 and macOS major version 26 at runtime. These labels avoid `*-latest`, but GitHub updates patch versions and image contents: they are not immutable VM-image pins. Jobs log image metadata, architecture, tools and actual Rex identity. Updated images must pass the tests again.

Mac jobs explicitly select installed **Xcode26.1.1** through per-job `DEVELOPER_DIR=/Applications/Xcode_26.1.1.app/Contents/Developer` and log its SDK. This does not change the machine-wide Xcode selection. The first hosted alpha.3 API10 job on image20261102.0473.1 failed before tests: its default Xcode26.6/SDK26.5 uses arm64e-only system-library stubs that Zig0.15.2 cannot match when linking its native build runner. The previously successful disposable macOS26 environment used Xcode26.1.1/SDK26.1; OS-family parity alone did not establish SDK parity. An absent selected Xcode fails explicitly rather than falling back or skipping native tests. See Zig upstream issues [31658](https://github.com/ziglang/zig/issues/31658), [31669](https://github.com/ziglang/zig/issues/31669) and [31673](https://github.com/ziglang/zig/issues/31673).

## Rex pins and isolation

Rex is proprietary and downloaded separately in every runtime lane. It is not bundled or uploaded as an artifact. Public availability is not redistribution permission. Each URL uses `https://blob.superlogical.com/download/rex/preview/COMMIT/ARCHIVE` with these immutable selections:

| Lane | Preview / API | Commit | Archive SHA-256 |
| --- | --- | --- | --- |
| Mac API10 | preview.13 / 10 | `1b6654811346488b696ded8f3c7e6701c57242f1` | `dfc3c5d57c9637ac21f41a7fa425a453fed64d68152b90772afb2d815b028977` |
| Mac API12 | preview.14 / 12 | `7e460d02f51573990bfcdc6c44a5606d11c7d47a` | `728df49b2cefcd62b7dde14cfcbd238cac69ec1524d71c19e6a389728ebe5374` |
| Mac API13 | preview.16 / 13 | `aa2db1b21261b479a550559fb70e2c3a66c07ba2` | `3055299e4fe881d97e8ca452e33906b8a9c7aedf36b836845ebb587829b29a29` |
| Linux API13 | preview.16 / 13 | `aa2db1b21261b479a550559fb70e2c3a66c07ba2` | `90b2429036d26f317aaac2490d014e07c9351b0b994b1329afce94b8ad4d333c` |

Mac archives are `rex-darwin-arm64.zip`; Linux is `rex-linux-amd64.tar.gz`. Preview numbers are not API revisions. API11 remains actual-build unverified; numeric acceptance is not all-build certification.

There is no rolling-preview lookup or fallback to another installed Rex. The verified executable is prepended to `PATH`; `TEEREX_BIN` selects the absolute checkout-built CLI. Tests use private temporary directories, explicit sockets, `/dev/null` config and `--restore=false` servers, then stop their fixtures. They never attach to default/personal Rex, Joshua's M5 or hive. Execution fixtures run only on the disposable machine. No raw terminal captures, vendor binaries or private receipts are published.

## Reproduce the checks

From the repository root with Zig 0.15.2, Python 3 and a deliberately selected checksum-verified Rex on PATH:

```sh
zig version
zig fmt --check build.zig src items tools/cartridges
# Linux; use aarch64-macos on an arm64 Mac instead.
zig build -Doptimize=ReleaseSmall -Dtarget=x86_64-linux-musl
zig test src/child_test.zig
export TEEREX_BIN="$PWD/zig-out/bin/teerex"
export REX_BIN="$(command -v rex)"
rex version
python3 items/observe/test_observe.py -v
python3 items/send/test_send.py -v
python3 items/spawn/test_spawn.py -v
python3 items/maneuvers/test_maneuvers.py -v
python3 items/filter/test_filter.py -v
python3 items/filter/test_cache.py -v
python3 items/adapters/test_adapters.py -v
# API13 only:
python3 items/jobs/test_jobs.py -v
```

On Linux, also run:

```sh
TEEREX_OFFLINE_ONLY=1 python3 items/doctor/test_doctor.py -v
python3 tools/install/test_install.py --public -v
zig build -Doptimize=ReleaseSmall -Dtarget=aarch64-macos --prefix zig-out/mac
```

On a disposable arm64 macOS 26 machine, run the common commands with the Mac target, then:

```sh
python3 items/run/test_run.py -v
python3 items/doctor/test_doctor.py -v
# Only the API13 cell:
python3 items/offstage/test_offstage.py -v
python3 tools/install/test_install.py --public -v
```

Selected executions per cell:

- **Linux combined CLI: 138** = child4 + observe28 + separately repeated offline Compare8 + send9 + spawn6 + maneuver21 + filter9 + cache12 + adapters11 + jobs13 + doctor3 + installer14. Doctor's seven unsupported runtime cases skip explicitly.
- **Mac API10 and API12 combined CLI: 120 each** = child4 + observe28 + send9 + spawn6 + run11 + doctor9 + maneuver21 + filter9 + cache12 + adapters11. Doctor's one non-Mac guard skips; jobs/offstage runtime are not selected.
- **Mac API13 combined CLI: 154** = those120 + jobs13 + offstage7 + installer14.
- **Additional Linux/API13 and Mac/API13 packaging checks:** cartridge lifecycle14 each; installed managed-payload offline51 each (filter9 + cache12 + maneuver21 + compare8 + adapter offline1), plus each payload's help/cross-dispatch/retirement/retained-data/inactive-restore checks. Native installed payload runtime suites execute109 Linux /136 Mac checks; the Mac doctor guard additionally skips. These repeat public behavior through separately built payloads, not additional unique product behaviors.

The runtime payload suite uses direct installed executable paths to preserve deliberate HOME changes and concurrent senders; direct invocation bypasses manager leases. Managed help/offline acceptance and lifecycle14 test the manager separately. Its short registry mutex is nonblocking, and a selected root remains HOME-bound; concurrent manager starts can refuse before payload dispatch. Do not describe direct payload success as managed concurrent-start coverage.

The extra Linux eight comparisons intentionally repeat cases contained in observe28 before Rex download; do not count them as new behaviors. CI discovers no unlisted suites. Installer public-download controls deliberately select the historical alpha.1 Mac release and Linux absent-asset case; other versions are native help-only fixtures. Those tests are not public alpha.4-download or live Rex proof. Final release archives receive a separate exact-byte install/upgrade/rollback/remove check.

## Evidence and limits

Local combined alpha.3 runtime validation passed **83** checks on native Debian13/kernel6.1.189+/API13 and **107** on disposable arm64 macOS27.2/API13 using the packaged executable bytes. The Linux total omits CI's repeated eight offline comparisons. A separate final-byte matrix on disposable arm64 macOS26.3.1 passed **86/86/107** executions on actual API10/API12/API13; Linux passed91 including the eight repeats. All27 runtime/test/installer source files matched published alpha.3 commit8b282786. The Mac matrix deliberately executed the packaged `99679a4f…61cd0` candidate, not its different-hash native rebuild; native compilation and child tests were exercised separately. These results do not establish hosted-image success, API11, M5 or hive compatibility.

The shipping owner must verify checks on the exact pushed commit before reporting hosted CI green. A local result or another commit's green status does not establish that. Combined-runtime and release evidence is recorded in the [direction record](direction.md) and item contracts. Source snapshots, compiler versions and executable hashes distinguish preliminary runs from final-byte tests.

Cross-compilation alone is not Mac runtime coverage. Linux Debian and Ubuntu-userland chroot results do not establish hive, a distinct Ubuntu kernel or a minimum supported kernel. Process-group tests do not establish sandboxing, arbitrary detached-descendant cleanup, all-build compatibility, M5 compatibility or human task completion. Offstage tests demonstrate surviving descendants and owner-crash leaks. Doctor's advertised checks are not behavior certification. Historical research and deferred non-Rex material remain unchanged.
