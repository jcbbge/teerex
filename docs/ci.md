# Build and regression CI

[The workflow](../.github/workflows/ci.yml) is started manually with
`workflow_dispatch`. Pushes and pull requests do not start it. It is a background
check, not an estate installation gate. Changes are checked locally on hive and
the M5; the estate build and installation procedure is linked below.

The workflow does not release, deploy, create tags, install a service or change
personal Rex configuration. Its token has `contents: read`, and checkout does
not persist credentials. It uses GitHub-hosted runners. This page describes the
workflow source, not a claim that the current commit has passed a hosted run.

## Active lanes

| Lane | Runner | Target |
| --- | --- | --- |
| Linux API13 and Apple-silicon cross-build | `ubuntu-24.04`, x86-64 | `x86_64-linux-musl`; also cross-build `aarch64-macos` |
| Mac API13 (Rex preview.16) | `macos-26`, arm64 | `aarch64-macos` |

The Mac API10 and API12 lanes were removed. The workflow still contains
conditional older-API refusal steps, but neither active matrix entry selects
them. API11 and other Rex builds are not certified by this matrix.

Both lanes check Zig formatting, build `ReleaseSmall`, and run the native child
supervisor regressions. They select Python 3.13 and checksum-pinned Zig 0.15.2.
The Mac lane selects Xcode 26.1.1 through its per-job `DEVELOPER_DIR`; an absent
selection fails rather than falling back. The workflow records tool versions,
runner image metadata and the actual Rex commit/API. Runner labels select an OS
family; they do not freeze subsequent image updates.

The matrix has `fail-fast: false`. A failed dependency download, checksum,
platform check, server startup or regression fails that lane. A newer dispatch
for the same workflow/ref cancels an older run through the concurrency setting.
The workflow does not configure branch protection.

## Selected regression suites

The workflow's commands are the source of truth for suite selection. Current
runtime selections on both API13 lanes are:

- observation, comparison, watch and inferred state:
  `items/observe/test_observe.py`, `items/observe/test_state.py`;
- guarded send and cooperative holds: `items/send/test_send.py`,
  `items/clutch/test_clutch.py`;
- public help and named-host routing: `src/test_help.py`, `src/test_targets.py`;
- surfaces: `items/surfaces/test_surfaces.py`;
- recovery and fleet installation: `items/recovery/test_recovery.py`,
  `tools/fleet-install/test_fleet_install.py`;
- records and decisions: `items/records/test_records.py`,
  `items/records/test_decisions.py`;
- installer lifecycle and public-release controls:
  `tools/install/test_install.py --public`.

These are file selections, not fixed test counts. Individual suites can select
platform-specific cases; the workflow source and test decorators show those
limits. The removed agent controller's launch/callback/channel/fence suites are
not part of this workflow.

Linux additionally runs the comparison class before downloading Rex, checks the
static executable, and cross-builds for Mac. The comparison class repeats
cases in the later full observation suite. The Linux preparation step installs disposable SSH/fence dependencies
and a fixture-specific bubblewrap AppArmor profile; it does not disable the
system-wide user-namespace restriction.

The separate [loopback SSH acceptance](../tools/fleet-install/test_ssh.py) is an
opt-in check requiring disposable sshd/sudo and generated keys. The workflow
prepares SSH dependencies, but does not directly invoke that script. Preparation
alone must not be counted as an executed SSH acceptance result.

## Rex pins and isolation

Each runtime lane downloads Rex separately. The workflow matrix owns the exact
Rex commit, archive names and SHA-256 values; read those there rather than
substituting an installed or rolling preview. Both current entries select
preview.16/API13. The Mac archive is `rex-darwin-arm64.zip`; Linux uses
`rex-linux-amd64.tar.gz`. Preview numbers are not API revisions.

The downloaded executable is checked for its expected commit/API and prepended
to `PATH`; `TEEREX_BIN` selects the absolute checkout-built CLI. Test fixtures use
private temporary state and explicit disposable sockets. See each selected
suite for its setup, skips and cleanup. Hosted jobs do not attach to the
operator's live Rex on hive or the M5. Rex is not uploaded as a workflow artifact.

## Reproducing a selected check

Use the exact command and environment from the relevant workflow step, in a
disposable environment with its toolchain and checksum-verified Rex already
provisioned. Preserve that step's platform and API conditions. Run the suite
needed for the change; this page is not an instruction to run every suite.

For example, after building the selected commit for the execution host, a
public-help check needs only that executable:

```sh
TEEREX_BIN="$PWD/zig-out/bin/teerex" python3 src/test_help.py -v
```

A source snapshot without `zig-out/bin/teerex` must build it with the workflow's
selected target/toolchain first, or use `TEEREX_BIN` pointing to an already-built
executable of that same commit. Do not treat another commit's binary as proof.
A runtime suite also needs the deliberately selected Rex and any step-specific
prerequisites. A cross-build alone does not establish Mac runtime coverage.

## Evidence and limits

Historical release evidence lives in the [alpha.5 release guide](releases/v0.1.0-alpha.5.md)
and the [direction record](direction.md). Historical four-lane results do not
make API10/API12 active lanes today. Release acceptance, local machine checks and
hosted CI are distinct evidence; one does not establish another's result.
The owner reporting hosted success must inspect the run for the exact pushed
commit. This page's source inventory is not such a success report.

Process-group cleanup tests do not prove arbitrary detached-descendant cleanup,
all-build compatibility, graphical painting or human task completion. See the
individual contracts and receipts for what each check establishes.

## Estate builds (hive and M5)

Use the [rexconfig build and install procedure](https://github.com/jcbbge/rexconfig#readme)
for the estate. It owns the pinned build and verified installation on hive. Disposable CI commands are not
an M5 native-build or estate-install procedure.
