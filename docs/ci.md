# Build and regression CI

[The workflow](../.github/workflows/ci.yml) runs on pull requests and pushes to `main`. It does not release, deploy, create tags, install a service or change Rex configuration. Its token has only `contents: read`; checkout credentials are not persisted. No repository secrets or paid/larger/self-hosted runners are required. Standard hosted runners are free for this public repository; changing repository visibility requires reviewing that assumption.

## Required lanes and coverage

| Check | Explicit runner | Executed checks |
| --- | --- | --- |
| Linux offline and Apple-silicon cross-build | `ubuntu-24.04`, x86-64 | Zig formatting, native `ReleaseSmall` build, existing offline `CompareTest`, `aarch64-macos` cross-build. |
| Mac integration (Rex preview.16) | `macos-26`, arm64 | Zig formatting, native `ReleaseSmall` build, both existing full observation/comparison/watch and execution/cleanup suites against disposable Rex servers. |

Zig **0.15.2** is downloaded from its versioned official archive and checked against the platform-specific SHA-256 from [Zig's download index](https://ziglang.org/download/index.json). Python **3.13** is selected explicitly. GitHub actions use immutable commit pins. There is no new `zig build test` interface: CI invokes the existing Python public-CLI tests unchanged.

The matrix runs both lanes, including when the other fails. Tests are not retried, allowed to fail or conditionally skipped for missing dependencies. A failed Rex download, checksum, startup, unexpected Mac architecture/OS family, or regression fails the Mac lane. Platform-specific steps are intentionally selected by lane; a successful Linux job alone is **not** full integration coverage. Branch-protection requirements are not changed by this workflow.

The [official runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners) lists `macos-26` as standard Apple-silicon/arm64, rather than Intel or a paid larger-runner label. The workflow checks arm64 and macOS major version 26 at runtime. These OS labels are pinned instead of using `*-latest`, but GitHub updates their patch versions and installed image contents: they are **not immutable VM-image pins**. Each job logs its image metadata, architecture and tool versions; the Mac job also logs `sw_vers` and the actual Rex version/API revision. A runner update must pass the same tests, not be treated as preverified compatibility.

## Rex pin and isolation

Rex is proprietary, separately downloaded only in the Mac job, not bundled or uploaded as a CI artifact. Public availability is not a redistribution license. The exercised pin is:

- Version: **0.1.0-preview.16**, API revision **13**.
- Commit: `aa2db1b21261b479a550559fb70e2c3a66c07ba2`.
- Archive: [`rex-darwin-arm64.zip`](https://blob.superlogical.com/download/rex/preview/aa2db1b21261b479a550559fb70e2c3a66c07ba2/rex-darwin-arm64.zip).
- SHA-256: `3055299e4fe881d97e8ca452e33906b8a9c7aedf36b836845ebb587829b29a29`.

There is no rolling-preview lookup or fallback to another installed Rex. The checked executable is prepended to `PATH`; `TEEREX_BIN` selects the absolute path of the CLI built from that checkout. Tests create private directories under `/tmp`, explicit Unix sockets, `/dev/null` config and `--restore=false` servers, and stop their disposable servers afterward. They do not attach to default/personal Rex, Joshua's M5 or a VPS. Execution fixtures run only on the disposable CI machine. No raw terminal captures, vendor binaries or test receipts are published.

## Reproduce the checks

From the repository root, with Zig 0.15.2 and Python 3:

```sh
zig version
zig fmt --check build.zig src items
zig build -Doptimize=ReleaseSmall
TEEREX_BIN="$PWD/zig-out/bin/teerex" python3 items/observe/test_observe.py CompareTest -v
zig build -Doptimize=ReleaseSmall -Dtarget=aarch64-macos --prefix zig-out/mac
```

On a disposable arm64 macOS 26 machine, place **only the deliberately selected, checksum-verified Rex pin** ahead of other executables on `PATH`, rebuild natively, then run:

```sh
zig build -Doptimize=ReleaseSmall
export TEEREX_BIN="$PWD/zig-out/bin/teerex"
rex version
python3 items/observe/test_observe.py -v
python3 items/run/test_run.py -v
```

The Linux offline baseline contains seven tests. The Mac baseline contains **27 observation/comparison/watch checks plus 11 execution checks** (38 total); the seven offline checks are included in the 27, not seven additional Mac tests. New cartridge suites must be added explicitly to this workflow when their source lands; CI does not discover or claim coverage of unlisted suites.

## Evidence and limits

Before enabling this workflow, its commands were exercised from source baseline `83661ee4e5247349888fdc6931c322dc1b08db26`: formatting, native Linux build, seven offline checks and the Apple-silicon cross-build passed with the checksum-verified official Zig 0.15.2 compiler. A fresh real arm64 **macOS 26.3.1** machine then passed the native build and all **38** unchanged integration checks using that compiler and the checksum-verified Rex pin. This establishes a tested macOS 26 runtime family, not an execution on GitHub's current hosted image. The shipping owner must verify both successful checks on the **exact integrated/pushed commit** before reporting hosted CI green; local tests or another commit's green status do not establish that result.

Cross-compilation is not Mac runtime coverage. Native Linux checks do not establish Linux/VPS execution support. The Mac suite's owned-process-group checks do not establish sandboxing, permission enforcement, arbitrary detached-descendant cleanup, full upstream API compatibility, M5 compatibility, offstage coverage or human task completion. See the existing [observation](../items/observe/README.md) and [execution](../items/run/README.md) contracts for their evidence boundaries. No historical research, non-Rex material, release wiring or feature tests are changed by this CI addition.
