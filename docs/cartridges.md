# Independent cartridges — current alpha.5 contract

**The core embeds the local cartridge manager; native payload catalogs remain separate.** Independent catalogs were first delivered in alpha.4. Use [current setup](concierge/setup.md) for the core and the [alpha.5 release guide](releases/v0.1.0-alpha.5.md) for exact separate catalog/onboarding assets. Alpha.3 had no independent packages; its tag/archive remains unchanged. New surfaces/boards/agents/recovery commands are combined-CLI composition, not additional independent cartridges. Do not put cartridge files in the core installer's managed tree. No personal installation, Rex change, PATH/profile edit or feature-use permission follows from packaging; source-only doc corrections do not rebuild frozen assets.

The primary entry is `teerex cartridges`; `python3 tools/cartridges/cartridges.py` is the equivalent direct source entry. The core embeds that same source and execs Python in isolated mode, then execs payloads without changing their arguments or environment. It requires Python **3.9+**, a non-root user, a canonical user-owned HOME, and Apple-silicon macOS or Linux x86_64. Python is an explicit prerequisite, not silently installed. It uses only the Python standard library. The separate native payloads require no Python themselves; bypassing the manager also bypasses its cooperative in-use protection.

## Payloads and honest readiness

`tools/cartridges/package.py` builds each selected item into its **own native executable** using Zig 0.15.2/ReleaseSmall. It never wraps or copies the combined `teerex` executable. The observation item retains its three related commands; the other executables take that item's options directly, without the combined CLI's leading verb.

| Cartridge ID | Standalone invocation | Catalog platforms |
| --- | --- | --- |
| `observe` | `teerex-observe observe …`, `compare …`, `watch …` | Apple silicon, Linux x86_64 |
| `run` | `teerex-run --socket … --cwd … -- ARGV…` | Apple silicon only |
| `spawn` | `teerex-spawn --socket …` | Apple silicon, Linux x86_64 |
| `send` | `teerex-send --socket …` | Apple silicon, Linux x86_64 |
| `offstage` | `teerex-offstage --socket …` | Apple silicon only |
| `doctor` | `teerex-doctor --socket …` | Apple silicon only |
| `maneuvers` | `teerex-maneuvers --definition … --observation …` | Apple silicon, Linux x86_64 |
| `filter` | `teerex-filter --sample … --sample …`, `cache put|get|purge …` | Apple silicon, Linux x86_64 |
| `jobs` | `teerex-jobs track|list|inspect|adopt|present|forget …` | Apple silicon, Linux x86_64; API13 only |
| `adapters` | `teerex-adapters generate|call …` | Apple silicon, Linux x86_64; API10–13 acceptance |

Readiness is evidence-gated per item and platform through [readiness records](../tools/acceptance/README.md). **Observe is ready on x86_64-linux and aarch64-macos for evidenced Rex API13**, proved by the [independent records and hashes](../tools/acceptance/results/observe-independent.sha256). All other items remain experimental. Readiness records pin the exact covered input bytes, including tests and the manager; `source_commit` is provenance only. Unrelated later commits retain readiness, while changed input paths are listed as stale. No item is promoted without an independently executed, current record; absent, non-ready or stale records remain **experimental**. Default `--all` selects only evidence-ready items; the additive `excluded_experimental` plan/apply field lists the sorted excluded IDs (empty for explicit IDs or `--allow-experimental`); explicit `--allow-experimental` admits experiments, including experimental dependencies. This does not mark them ready or supersede the historical ready-only collection policy. A future catalog changes membership only when explicitly selected; existing installations do not update themselves. `source.json` is a build recipe, not a claim that all listed APIs/builds are behavior-certified. Item READMEs and rights are copied into each payload. The narrower Mac-only run/doctor/offstage and API13-only offstage/maneuver domains remain intact. No Rex executable is bundled.

The observation standalone build uses the integrated `pub fn runObservations(allocator, args) !u8` boundary in `items/observe/main.zig`; `args` starts with `observe`, `compare`, or `watch`, not an executable name. That boundary contains no other cartridge dispatch. It is a follow-on to frozen alpha.3, not present in the alpha.3 tag. Filter/maneuvers statically include the observation evidence validator/comparator; other shared code is also statically linked. There is **no runtime dependency on the combined core executable**. Static source reuse does not make payload installation/removal inseparable.

## Build, review, install

For development, build reviewed source into a new output directory. The example labels a local alpha.5-source catalog; it does not reproduce the published asset identity. Never reuse an installed version with changed bytes; use published catalogs for release installation. Linux builds target `x86_64-linux-musl`; Mac builds target `aarch64-macos`.

```sh
python3 tools/cartridges/package.py --platform x86_64-linux --version 0.1.0-alpha.5 --output /canonical/new/catalog-directory
# Or --platform aarch64-macos. Add --zig /path/to/zig if needed.
```

The output is a reviewable directory, not an executable installer or downloaded archive: `catalog.json` pins the SHA-256 of each `<id>/<version>/manifest.json`, which pins all payload bytes and executable bits. It records the actual source commit and whether the source tree was dirty. No signatures, remote repository resolver, registry trust service, downloaded tools, or authentic upstream identity are implied by these hashes. Review the source/catalog and its trusted delivery channel before applying or running it. There are no lifecycle hooks and **installation never executes package code**, even `--help`.

The root defaults to `~/.local/opt/teerex-cartridges`; `--root` must precede the subcommand. Roots must be strictly inside HOME, have no symlink ancestors, and be user-owned and not group/world-writable. An existing nonempty unmarked root is refused. Use canonical paths on macOS: for example `/private/var/…`, not its `/var/…` alias. Package paths are relative, bounded, unique regular files: no symlinks, hard links, traversal, duplicate JSON keys, extra files, or install scripts.

```sh
# Discover ready items (currently observe on both platforms, API13):
teerex cartridges install --all --catalog /canonical/catalog

# Plans disclose selected IDs/versions, dependencies, provenance/compatibility,
# code/data destinations, permissions and undo. They do not install or execute.
teerex cartridges install filter --catalog /canonical/catalog --allow-experimental
teerex cartridges install --all --catalog /canonical/catalog --allow-experimental

# Apply the same resolver and individual lifecycle paths, once for the selection.
teerex cartridges install filter --catalog /canonical/catalog --allow-experimental --apply
teerex cartridges list
teerex cartridges run filter -- --help
```

Lifecycle output is schema-1 JSON (`ok`, `operation`, `applied`, selected package records); contract/filesystem failures are JSON on stderr with exit 1. SIGINT returns schema-1 JSON on stderr with exit 130 after existing rollback cleanup. Missing or too-old Python returns an explicit JSON refusal with exit 1. Named-host `--config/--host` routing is refused: log in and run `teerex cartridges` on that machine. Argument-usage errors use argparse's stderr/exit 2. `run` passes through the payload's stdout/stderr, arguments and exact exit/signal behavior by `exec`; output after that is the item's contract, not a fabricated lifecycle receipt. Shell metacharacters are literal argv, not evaluated. Human and agent callers use the same interface. `kind=agent` uses exactly the same install/run/lease/remove rules as scripts, programs and extensions; no privileged agent path or implicit agent startup exists. Current production manifests are programs, not bundled autonomous agents.

`--apply` explicitly requests the described local mutation. It is **not** an authentication mechanism or a human-approval service: an agent running as the same OS user has that user's authority. Manifest `permissions` are disclosures, not sandbox enforcement. Review/approval for terminal input, local commands, credentials, remote deployment and other consequential effects remains the caller's responsibility. Installation alone never authorizes invocation or personal-machine access.

## Refusals and recovery

Common refusals include an additive `next_step` string. Never delete locks or edit `state.json` to bypass them.

| Error | Next step |
| --- | --- |
| Experimental cartridge requires flag | Review the plan; add `--allow-experimental` if intended. |
| Choose explicit IDs or `--all` | Supply one selection form. |
| Cartridge root does not exist | Check HOME and `--root`, then install first. |
| Unsafe, symlinked, or unmarked root | Choose an empty canonical user-owned path strictly inside HOME. |
| Active removal requires `--deactivate` | Add the flag to leave the ID inactive. |
| Active dependent blocks removal | Remove or switch that dependent first. |
| In use or concurrent lifecycle operation | Wait for the holder to finish, then retry manually. |
| Changed hashes, manifest, or package membership | Copy out edits and inspect; the manager will not delete them. |
| Installed version identity differs | Use a new version for changed bytes. |
| Unregistered or retired version exists | Restore it or inspect manually. |
| Interrupted | Run `list`, inspect `.stage-*` directories and registry before retrying. |

## Manifest and dependency contract

The executable validator in `tools/cartridges/cartridges.py` owns schema 1. Unknown top-level fields fail instead of being treated as unimplemented hooks. A concrete package manifest contains exactly:

- `schema_version: 1`; stable lowercase `id`; exact semantic `version` without `v`; `status: ready|experimental`; `kind: program|script|extension|agent`.
- One exact `platform: aarch64-macos|x86_64-linux`, checked against the host. A platform label is not a native-format or minimum-OS certification; the shipped builder selects the target and native acceptance tests execute the bytes.
- `entrypoint`: an argv array whose first entry names an executable payload file. Optional fixed arguments precede caller arguments. The runtime/interpreter for a script is an explicit external prerequisite, not downloaded by the manager.
- `files`: 1..128 relative file records, each with `path`, lowercase `sha256`, and boolean `executable`. JSON is capped at 1 MiB; each payload file at 64 MiB. The manifest itself is separately pinned by the catalog/installed registry.
- `dependencies`: an ID → exact-version map, not version ranges or arbitrary filesystem/installer paths. Missing pins, cycles, host mismatches and active-version conflicts fail before activation. One catalog contains at most 128 IDs and one version per ID.
- `provenance`, `compatibility`: JSON objects disclosing source/build/rights and the item's narrower runtime/API requirements. They are not automatically proven by discovery or installation.
- `permissions`: textual disclosures; `data_policy: retain` is the only supported data policy.

Dependencies are resolved in dependency order by the same installer as explicitly selected items. The final **active** graph must satisfy every exact pin. Installing/activating a version that would break an active dependent fails rather than silently updating that dependent. Old inactive versions remain; their dependencies are rechecked when activated. Active dependents block dependency removal. Removing a dependent **never garbage-collects dependencies**; shared ownership stays explicit and users remove now-unneeded versions themselves. No reference-count heuristic chooses whether user code/data is disposable.

During `run`, `TEEREX_CARTRIDGE_DEPENDENCIES` is a JSON map of transitive dependency IDs to their exact selected code directories, not mutable core `current` links. `TEEREX_CARTRIDGE_DATA` names the selected item's retained data directory. Runtime dependencies share the user's environment and authority; they are not sandboxes. Existing native teerex payloads have no runtime cartridge dependencies: their common code is statically linked.

## Upgrade, removal, in-use and retention

The managed layout separates immutable code, active selection and mutable data:

```text
ROOT/.teerex-cartridges          manager-owned root marker
ROOT/state.json                 active versions and pinned installed/retired identities
ROOT/packages/ID/VERSION/       separately installed immutable payload
ROOT/retired/ID/VERSION/        removed payload, retained for explicit undo
ROOT/data/ID/                   user-owned mutable data, shared across versions, never removed
ROOT/leases/ID/VERSION          stable cooperative advisory-lock inode
ROOT/.lock                     short lifecycle transaction mutex
```

Installing an explicit new version activates it and retains older versions; the same catalog/version/hash is repeatable. Reusing a version with different bytes fails. `activate` is explicit rollback/selection, not a migration. `remove` retires exactly one verified payload out of the install/run namespace; active removal needs `--deactivate`, leaves that ID inactive, and never chooses a fallback. `restore` verifies the recorded retired hash, restores that version **inactive**, and does not start it. There is no purge, force-remove, automatic data migration, or code/data garbage collection.

```sh
# Set PACKAGE_VERSION to the exact installed/retired version shown by list.
teerex cartridges activate filter --version "$PACKAGE_VERSION" --apply
teerex cartridges remove filter --version "$PACKAGE_VERSION" --deactivate --apply
teerex cartridges restore filter --version "$PACKAGE_VERSION" --apply
# Reactivation is a separate explicit activate command after restore.
```

Before removal, activation, or reuse, the manager verifies registered manifests, exact payload membership, hashes and executable flags. Missing/modified/extra/linked code is refused without deleting it; copy user edits out and inspect/recover manually. User data and configuration under `data/ID` stay byte-for-byte in place through removal/restore. They are not untrusted disposable package files. Data elsewhere, Rex windows/jobs, background agents, shell profiles and core installation are untouched. Because versions share `data/ID`, rolling back code does not roll back data an invoked program changed; callers must manage version-specific data compatibility themselves.

A run acquires shared per-version locks for itself and all dependencies before releasing the short registry mutex, then inherits those file descriptors across exec. Removal and changing an active version fail while the affected version is leased; unrelated cartridge lifecycles remain available. There is no wait/kill/force/stale-lock deletion path. OS locks release when all holders close them; empty lock files are retained deliberately. Starting a run takes the same short nonblocking registry mutex: simultaneous launch/management operations can refuse before exec rather than queue. Keep HOME stable for the selected HOME-bound root. This is **cooperative invocation lifetime**, not hot-unload, process discovery, a Rex input lease, immediate human revocation, or all-descendant cleanup. Direct executable invocation, programs that close inherited FDs, detached work and externally started agents are outside that guarantee. Removing code does not stop such work or claim it stopped.

The independent core installer has **no cartridge dependency/refcount/lease protocol**. Cartridge locks do not stop an explicit core install/upgrade/removal. Its internal mutex and human-readable `list` are not supported resolver APIs. If a future custom cartridge needs the core, the caller must select and verify an explicit core-version executable and fail closed if it disappears; repeatedly resolving mutable/possibly absent `current` is not pinning. No such implicit core dependency is created here.

A bulk install prevalidates the entire selection and existing active graph, stages verified payloads, then atomically replaces one registry file for activation. Normal copy/verification/registry-write failures clean up newly staged code and leave previous selection intact; removal/restore rename failures roll back before returning an error. This is not a power-loss/SIGKILL transaction journal: interruption can leave `.stage-*` or an unregistered code/retired directory. Such paths are never silently adopted, overwritten or purged; inspect registry and bytes and recover manually. The manager supplies no automatic crash repair. Installed and retired code both consume disk until a user deliberately reclaims it outside this API.

## Verification and delivery boundary

```sh
python3 -m unittest discover -s tools/cartridges -p test_cartridges.py -v
TEEREX_BIN="$PWD/zig-out/bin/teerex" python3 tools/cartridges/test_root_entry.py -v
python3 tools/cartridges/test_payloads.py --catalog /canonical/native/catalog
# Optional real-Rex acceptance: explicitly selected disposable API13 Rex on PATH/REX_BIN.
python3 tools/cartridges/test_payloads.py --catalog /canonical/native/catalog --with-rex
zig fmt --check tools/cartridges/*.zig
```

The first command exercises disposable HOME roots, individual/all composition, experiment gating, exact dependency conflict/cycle/missing rejection, upgrade/rollback, retirement/restore, retained data, modified/extra/linked payload refusal, malicious paths/JSON, in-use refusal with unrelated removal, no install-time execution, and untouched shell/Rex/core sentinels. Agent/script/extension kinds use real fixture entrypoints but are not claims of a production agent/service ecosystem.

The root-entry suite repeats lifecycle tests through the embedded manager and checks exact process/exit/signal passthrough, help, Python isolation, missing Python, named-host refusal and direct-manager parity (allowing argparse program-name alignment). Set `TEEREX_BIN` for native payload acceptance too to exercise install/help/removal through the core. Offline suites that deliberately remove Python from PATH retain their absolute-Python adapter.

Native payload acceptance installs the **real separately built native payloads**, executes each help path, rejects cross-cartridge dispatch, reuses existing filter/cache/maneuver/observation/adapter offline public tests through a temporary test-only argv adapter, and exercises removal/data retention/inactive restore for every payload. It does not contact Rex unless `--with-rex` is explicitly selected. That option also runs each packaged item's public runtime tests against fresh isolated API13 fixtures, selecting Mac-only suites only when their payloads are present. Runtime suites invoke the actual installed payloads directly to preserve deliberate HOME changes and concurrent callers; they do not claim the manager's cooperative leases cover direct invocation. Offline mode and lifecycle tests exercise the managed launcher separately. The argv adapter is validation code, never a shipped cartridge wrapper. No test here restarts a personal server or claims M5/hive validation.

On 12 November 2026, all **14 lifecycle tests** passed on Linux x86_64/Python 3.13.5, Linux/Python **3.9.25** (the declared minimum), and disposable Apple-silicon macOS 27.2/Python 3.15.2. Separately built native catalogs contained **five Linux** and **eight Mac** executables. Installed-payload acceptance passed all **27 existing offline contracts on each platform**, plus each payload's help, cross-dispatch refusal, retirement/data retention/inactive restore. Mac executables were cross-built on Linux with pinned Zig 0.15.2, then actually executed on the disposable Mac; `file` identified arm64 Mach-O on Mac and static x86-64 ELF on Linux. A real permission-denied registry-write case after staging both upgrades preserved the prior registry and removed both staged versions. No public release or hosted-CI success is claimed by this local evidence.

Integrated alpha.4 catalogs expand that initial leaf to **seven Linux/ten Mac** native payloads by adding jobs/adapters. On disposable Linux/API13 and arm64 macOS27.2/API13, managed installed acceptance passed51 offline checks each; direct installed payload runtime acceptance passed109 Linux/136 Mac checks, plus one inapplicable Mac doctor guard skipped. Each catalog also passed native help, cross-dispatch refusal, retirement, byte-preserved user data and inactive restore for every payload. Initial managed runtime harness failures were preserved: concurrent senders hit the short nonblocking registry mutex, and an intentionally changed HOME invalidated its selected root. Corrected runtime validation uses direct installed paths, not a weakened product check or a claim those manager constraints disappeared.

The original definitive planning/scoring, source history and research are unchanged. These dated acceptance results record earlier milestones; current alpha.5 includes root CLI wiring, hosted CI and published native catalogs. See the [current release evidence](releases/v0.1.0-alpha.5.md#verification), not this earlier leaf checkpoint, for release-byte acceptance. No item is marked ready, and no publication silently upgrades alpha.3 assets.
