# Build and regression CI

[The workflow](../.github/workflows/ci.yml) runs on pull requests and pushes to `main`. It does not release, deploy, create tags, install a service or change Rex configuration. Its token has only `contents: read`; checkout credentials are not persisted. No repository secrets or paid/larger/self-hosted runners are required. Standard hosted runners are free for this public repository; changing repository visibility requires reviewing that assumption.

## Required lanes and coverage

| Check | Explicit runner | Selected coverage |
| --- | --- | --- |
| Linux API13 and Apple-silicon cross-build | `ubuntu-24.04`, x86-64 | Static musl CLI, direct child supervision, observe/compare/watch, send, spawn, offline maneuver/filter/doctor, installer and Mac cross-build. |
| Mac API10 (Rex preview.13) | `macos-26`, arm64 | Direct child supervision, observe/compare/watch, run, send, spawn, doctor and offline maneuver/filter. |
| Mac API12 (Rex preview.14) | `macos-26`, arm64 | Same public suites as Mac API10. |
| Mac API13 (Rex preview.16) | `macos-26`, arm64 | Same public suites plus API13-only offstage and installer lifecycle/public-download controls. |

Every lane checks Zig formatting and builds `ReleaseSmall`. Zig **0.15.2** is downloaded from its versioned official archive and checked against the platform-specific SHA-256 from [Zig's download index](https://ziglang.org/download/index.json). Python **3.13** is selected explicitly. GitHub actions use immutable commit pins. There is no `zig build test` interface: CI invokes the listed Python public-CLI suites and `zig test src/child_test.zig` directly.

The four cells continue independently when another fails. Tests are not retried, allowed to fail or skipped for missing dependencies. A failed download, checksum, startup, wrong architecture/OS family or regression fails its lane. Platform/revision-specific steps are deliberately selected; Linux alone is not full integration coverage. Linux run/doctor runtime and API10/12 offstage are unsupported, not covered by a successful cell. Branch-protection settings are unchanged.

The [official runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) lists `macos-26` as standard Apple-silicon/arm64. CI checks arm64 and macOS major version 26 at runtime. These labels avoid `*-latest`, but GitHub updates patch versions and image contents: they are not immutable VM-image pins. Jobs log image metadata, architecture, tools and actual Rex identity. Updated images must pass the tests again.

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
zig fmt --check build.zig src items
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

- **Linux: 91** = child4 + observe28 + separately repeated offline Compare8 + send9 + spawn6 + maneuver10 + filter9 + doctor3 + installer14. Doctor's seven unsupported runtime cases skip explicitly.
- **Mac API10 and API12: 86 each** = child4 + observe28 + send9 + spawn6 + run11 + doctor9 + maneuver10 + filter9. Doctor's one non-Mac guard skips.
- **Mac API13: 107** = those86 + offstage7 + installer14.

The extra Linux eight comparisons intentionally repeat cases contained in observe28 before Rex download; do not count them as new behaviors. CI discovers no unlisted suites. Installer public-download controls deliberately select the historical alpha.1 Mac release and Linux absent-asset case; other versions are native help-only fixtures. Those tests are not public alpha.3-download or live Rex proof. Final release archives receive a separate exact-byte install/upgrade/rollback/remove check.

## Evidence and limits

Local combined alpha.3 runtime validation passed **83** checks on native Debian13/kernel6.1.189+/API13 and **107** on disposable arm64 macOS27.2/API13 using the packaged executable bytes. The Linux total omits CI's repeated eight offline comparisons. Fresh macOS26.3.1 alpha.2 tests passed observe28/run11 on actual API10/12/13; that earlier binary is not evidence for every alpha.3 feature. Final-candidate macOS26 matrix evidence and hosted results must be reported separately, not inferred from compilation or an older run.

The shipping owner must verify checks on the exact pushed commit before reporting hosted CI green. A local result or another commit's green status does not establish that. Combined-runtime and release evidence is recorded in the [direction record](direction.md) and item contracts. Source snapshots, compiler versions and executable hashes distinguish preliminary runs from final-byte tests.

Cross-compilation alone is not Mac runtime coverage. Linux Debian and Ubuntu-userland chroot results do not establish hive, a distinct Ubuntu kernel or a minimum supported kernel. Process-group tests do not establish sandboxing, arbitrary detached-descendant cleanup, all-build compatibility, M5 compatibility or human task completion. Offstage tests demonstrate surviving descendants and owner-crash leaks. Doctor's advertised checks are not behavior certification. Historical research and deferred non-Rex material remain unchanged.
