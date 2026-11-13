# Install, upgrade, roll back, and remove teerex

The reviewed installer manages one shared experimental CLI inside your home directory on **Darwin arm64** or **Linux x86_64**. The current published [v0.1.0-alpha.5](releases/v0.1.0-alpha.5.md) provides both platform archives. Start with the canonical [WWWWW+H setup, exact checksum/install/upgrade/verify/rollback commands and support matrix](concierge/setup.md), or the [copy-ready local-agent handoff](concierge/agent-prompts.md#a-install-or-upgrade-alpha5-without-touching-rex). This contract describes the installer; historical releases remain in their tagged guides. Rex is separately obtained and never installed, upgraded or restarted by this tool.

This **core installer does not manage independent cartridges**; the separate [catalog manager](cartridges.md) supplies that already-delivered lifecycle. The new operating-layer composition is combined-CLI only. Source-only documentation pushes do not rebuild immutable alpha.5 assets or complete gated migrations. Installation needs no Zig, running Rex or administrator privileges; Python3.9+ is needed for the documented operating-layer Python paths.

## Review, verify and install

Use the reviewed pinned source installer or frozen onboarding root; it is not inside the three-file core archive. Current setup instructions are in source, not a replacement for older packaged docs. Do not pipe a remote script into a shell. For a new root, after the setup guide's checksum/preflight steps:

```sh
bash tools/install/teerex-install --help
bash tools/install/teerex-install install --version v0.1.0-alpha.5
bash tools/install/teerex-install inspect
bash tools/install/teerex-install verify --version v0.1.0-alpha.5
"$HOME/.local/opt/teerex/current/teerex" --version
```

For an active managed root use `upgrade` **instead of** `install`; for an already retained tag verify and deliberately reactivate with `rollback` only when needed. Preserve the actual prior active tag, and repeat an agreed custom `--prefix` on every lifecycle command.

The explicit tag is mandatory; nothing guesses `latest`, polls or autoupdates. Downloads use HTTPS release assets from `github.com/jcbbge/teerex`:

- Mac: `teerex-TAG-aarch64-macos.tar.gz`, an arm64 Mach-O executable.
- Linux: `teerex-TAG-x86_64-linux.tar.gz`, an ELF64 little-endian x86-64 executable.
- External `SHA256SUMS`, with exactly one entry for the selected archive; entries for other assets may coexist.

Archives must contain exactly three regular, top-level files: `teerex`, `README.md` (that release's guide), and `RIGHTS.md`. Validation checks the archive checksum before extraction, rejects extra/duplicate paths and links, checks executable format/architecture, and runs `--help` before activation. Rollback also verifies host architecture. Download, checksum, archive, binary or help failure does not replace the active version, and there is no cross-platform fallback. A failed first install can leave an empty managed root, reusable by `install`.

Mac uses system Bash 3.2 and stock tools. Linux requires Bash, GNU coreutils (`sha256sum`, `mv`), `tar`, `gzip`, `file`, `awk`, `grep`, and `curl` with usable HTTPS certificates. Missing tools produce a diagnostic, never package installation. To use explicitly reviewed local assets, place archive and checksums in one directory:

```sh
bash tools/install/teerex-install install --version v0.1.0-alpha.5 \
  --from "$HOME/Downloads/teerex-alpha.5"
```

`--from` avoids downloads, not checksum/executable validation or the requirement to trust that source. Same-release checksums detect changed bytes, not independently authenticate a publisher. The Mac binary is **not Developer-ID-signed or notarized**; browser-quarantine/Gatekeeper acceptance remains unverified. The installer does not remove quarantine, disable security or bypass a denial.

The Linux CLI is built with Zig 0.15.2, `ReleaseSmall`, `x86_64-linux-musl`. `file`/`readelf` inspection verifies static ELF64 x86-64 with no interpreter/dynamic section, hence no host glibc dependency. The installer checks host format/architecture and actual help, not libc linkage or minimum kernel compatibility. Debian 13/kernel 6.1.189+ and Ubuntu 24.04.5 userland on that same kernel have runtime evidence; this is not an independent Ubuntu-kernel or hive guarantee. See [Linux evidence](linux.md).

## Managed layout and concurrent operations

```text
~/.local/opt/teerex/
  .teerex-install-root
  versions/v0.1.0-alpha.5/
    teerex
    README.md
    RIGHTS.md
    .files.sha256
  current -> versions/v0.1.0-alpha.5
```

For a custom location, pass `--prefix "$HOME/somewhere/teerex"` on **every** lifecycle command. It must be a new, user-owned path inside HOME, with no symlink ancestors or dot components; an existing unmanaged directory is not adopted or overwritten. Spaces work. Keep roots host-local, not shared between Mac/Linux. The executable is account-private; no global launcher is installed.

A short-lived lock and staging directory live under the root. Concurrent installer operations refuse rather than race. After a crash/SIGKILL, verify that no installer is running before deliberately removing its stale `.installer-lock` or interrupted `.stage.*` directories. No daemon, service, watcher or automatic command history is created.

## Read-only machine contract (schema 1)

Automation uses these commands rather than parsing human `list` output or private directory/lock details:

```sh
bash tools/install/teerex-install inspect --prefix "$HOME/.local/opt/teerex"
bash tools/install/teerex-install verify --prefix "$HOME/.local/opt/teerex" --version v0.1.0-alpha.5
```

Each returns one newline-terminated JSON object on stdout. `inspect` takes no version; `verify` requires an explicit installed tag. Neither accepts `--from` or `--deactivate`. Both retain the user/HOME/path/platform checks, create no root, lock or stage, download nothing, and **never execute the selected binary or contact Rex**. Reading may update filesystem access times. Error details may also appear on stderr from system tools; stdout is the machine interface. `--help` remains human-readable.

An absent root is a successful classification, not an instruction to adopt anything. Example (illustrative path, not a release/download claim):

```json
{"schema_version":1,"operation":"inspect","ok":true,"state":"absent","root":"/home/operator/.local/opt/teerex","platform":"x86_64-linux","active_version":null,"installed_versions":[],"busy":false,"reason":null}
```

An existing owned directory without the marker has `state:"unmanaged"`, `reason:"missing_marker"`; an owned regular marker with unknown contents has `reason:"unrecognized_marker"`. Both are exit 0, with null active version, empty installed versions and busy false. They cause no adoption, execution or writes. Select a new root rather than modifying a manual tree. Unsafe paths, symlinked/non-owned markers, and recognized-but-broken managed layouts fail instead of becoming unmanaged classifications.

An idle managed example:

```json
{"schema_version":1,"operation":"inspect","ok":true,"state":"managed","root":"/Users/operator/.local/opt/teerex","platform":"aarch64-macos","active_version":"v0.1.0-alpha.5","installed_versions":["v0.1.0-alpha.3","v0.1.0-alpha.5"],"busy":false,"reason":null}
```

`root` is the canonical absolute requested root (including physical HOME normalization, such as `/private/var` on Mac). `platform` is the host asset platform, not an inventory integrity assertion. `installed_versions` is a C-locale lexical list of safe owned tag directories, **not semantic-version ordering, verification, or a latest-version recommendation**. An absent `current` is a valid deactivated state with `active_version:null`; a malformed link, missing target, symlinked target or non-link collision is an error. Inspect does not hash release contents; call verify before trusting/executing a selected version.

If any installer lock entry exists, including a stale file/directory/dangling symlink, inspect reports managed with `busy:true`, `active_version:null`, `installed_versions:[]`, `reason:null`. That null/empty inventory is intentionally non-authoritative; callers must refuse/retry, not infer deactivation or absence. Verify refuses with `busy`. Neither command removes stale locks.

Verification success returns exactly these fields (the zero hash below is an illustration, not an asset hash):

```json
{"schema_version":1,"operation":"verify","ok":true,"root":"/Users/operator/.local/opt/teerex","platform":"aarch64-macos","active_version":"v0.1.0-alpha.5","selected_version":"v0.1.0-alpha.3","executable":"/Users/operator/.local/opt/teerex/versions/v0.1.0-alpha.3/teerex","sha256":"0000000000000000000000000000000000000000000000000000000000000000"}
```

`selected_version` can differ from `active_version`; `executable` is a **fixed absolute version path**, never the moving `current` link. `sha256` is the lowercase SHA-256 of that executable. Verification requires the marker/layout, safe inventory/current link, exactly four owned regular version files, executable permission, matching `.files.sha256`, and host binary architecture. The hash/record detects modification, not malicious writes by another process with the same account. It does not attest self-reported CLI version, signing/notarization, independent cartridge version or live Rex compatibility. Fleet must independently execute the verified path's `--version` when needed; root CLI version support belongs to the selected release, not this installer.

Failures exit 1 and use this shape:

```json
{"schema_version":1,"operation":"verify","ok":false,"error":{"code":"integrity_mismatch","message":"installed files changed in v0.1.0-alpha.5; leaving them untouched"}}
```

Stable schema-1 error codes are `invalid_arguments`, `unsupported_platform`, `missing_tool`, `unsafe_path`, `missing_root`, `unmanaged_root`, `invalid_root`, `busy`, `invalid_current`, `invalid_release`, `integrity_mismatch`, and `architecture_mismatch`. Match `code`, not human `message`. Inspect uses the same failure envelope with `operation:"inspect"`. Refusals never fix, overwrite or delete the offending entries.

These are point-in-time observations, **not leases or protection against a later switch/removal**; do not run lifecycle mutations concurrently with a fleet decision or invocation. The core installer still refuses immutable-tag duplicate installs: after idle inspection, select a retained tag with rollback, or install/upgrade a new tag, then verify. Any launcher consent/backup belongs to the fleet workflow; inspect/verify never creates or replaces one.

## PATH, compatibility and operator machines

Use the full executable path above. Deliberately add `$HOME/.local/opt/teerex/current` through your own shell workflow only if desired. No `.zshrc`, `.zprofile`, profile, Rex `init.lua`, key binding, existing binary or setting is edited. Remove any PATH change you made yourself when uninstalling.

Integrity/help success is **not live compatibility**. Alpha.5 retains numeric API10–13 for observe/watch/low-level send/spawn/adapters; surfaces have actual Mac10/12/13 and Linux13 coverage. Managed launch/jobs/snapshot/restore require API13; update is read-only inventory/manual handoff. Run/doctor runtime remain Mac-only and offstage Mac/API13-only. See the current [setup matrix](concierge/setup.md#supported-platforms-and-api-boundaries), [release guide](releases/v0.1.0-alpha.5.md) and item contracts. API11 numeric acceptance, configured host execution and package/help success do not certify actual API11, personal hosts, exact issue #10 topology or real harness hooks. Historical alpha.1–4 guides remain unchanged.

**Never update, restart or auto-start Rex as an installation prerequisite.** Updates can close panes. Choose a compatible release while preserving the existing server. Joshua's setup agent supplied M5/API10 and hive/API13 observations; installer/disposable-platform tests do not constitute personal-machine validation. Every agent/worker/sidecar/message on his machines must remain visible through authorized Rex/teerex routing, including Rivet; installation creates no hidden-worker exception. Setup/guard migration remains separate ownership. This installer never connects to a server, launches an agent, accesses hive or changes agent-core/Rivet configuration.

## Upgrade and rollback

Follow [setup preflight](concierge/setup.md#how-inspect-first-then-choose-exactly-one-activation) to record and verify the actual prior active `PRIOR_TAG` before upgrading. Repeat an agreed custom `--prefix` everywhere. Choose upgrade only when the destination is not already retained:

```sh
bash tools/install/teerex-install upgrade --version v0.1.0-alpha.5
"$HOME/.local/opt/teerex/current/teerex" --version
# Only if an explicit rollback is needed and the before record names a retained tag:
test -n "$PRIOR_TAG"
bash tools/install/teerex-install verify --version "$PRIOR_TAG"
bash tools/install/teerex-install rollback --version "$PRIOR_TAG"
```

Upgrade requires an active, integrity-checked installation, stages/validates the chosen version, and atomically replaces `current`. Explicit selection, not semantic-version ordering, determines the destination. Previous versions stay installed. A repeated tag is never overwritten. Rollback activates only a retained, integrity/architecture-checked version, without downloading or invoking Rex. `.files.sha256` detects accidental modification, not another process with your account's write authority.

Stop foreground teerex invocations before switching/removing versions. This installer is not a supervisor and does not stop existing workers, terminals or invocations. Programs using a fixed version path or shell command caches may still select the old binary; verify through `current/teerex`.

## Remove and finish uninstalling

```sh
# Inactive version (select one branch, not both):
bash tools/install/teerex-install remove --version v0.1.0-alpha.5
# Or deliberately deactivate and remove the active version:
# bash tools/install/teerex-install remove --version v0.1.0-alpha.5 --deactivate
bash tools/install/teerex-install list
```

`--deactivate` leaves no active executable; no older version is silently selected. Removal deletes only the four known, integrity-checked version files and their directory. Modified, missing, symlinked or extra files cause refusal before deletion. No explicit captures, user data, program-created files or Rex configuration are removed.

After explicitly removing every listed version, inspect the remaining marker and empty directories, then use your actual root:

```sh
rmdir "$HOME/.local/opt/teerex/versions"
rm "$HOME/.local/opt/teerex/.teerex-install-root"
rmdir "$HOME/.local/opt/teerex"
```

`rmdir` refuses nonempty directories; do not substitute recursive removal. Source checkouts, installer scripts and downloaded assets are separate files you may retain or remove yourself. Independent cartridges have their own [existing lifecycle](cartridges.md); removing the core neither removes nor rolls back them or their data. No project license has been selected ([rights](../RIGHTS.md)).

## Validation boundaries

`python3 tools/install/test_install.py --public -v` runs 20 tests on disposable Darwin arm64 and Linux x86_64, using temporary HOME/roots and native help-only fixtures. It exercises install/upgrade/rollback/remove, wrong architecture, malformed/checksum/archive failures, refusal to replace user files and unchanged shell/Rex/launcher sentinels. The six added machine-contract cases cover absent/unmanaged/managed/deactivated roots, fixed retained-version selection, stale/busy locks, path/current/inventory/refusal errors, independently computed hashes, escaped Unicode/control-character paths, and JSON failure codes. Each machine invocation compares filesystem bytes/links/metadata before and after (excluding access times; unreadable entries retain metadata checks). An execution-probe fixture, including a positive launch control, confirms inspect/verify never execute the candidate. Python/native C compiler are test dependencies, not installer dependencies. Historical public controls intentionally retain immutable alpha.1: Mac genuinely downloads/executes its 300712-byte binary, SHA256 `c39108dc3bfedf240c62c4f7b0c683f6f06b5ef59fa78cd377aa8b38b007abe9`, then upgrades to a local fixture and rolls back to identical bytes; Linux verifies the real absent-alpha.1-Linux-asset failure preserves the active fixture. These are not relabelled alpha.3 checks.

Both platforms passed all 20 controls, including the retained 14 lifecycle/public controls; Mac used system Bash 3.2 on macOS27.2 and Linux used Debian13. The public Mac binary also passed the new read-only verify API with its independently known hash. No alpha.5 binary or fleet integration is claimed by these installer checks. ShellCheck0.10.0 and Bash syntax passed. A separately labelled pre-integration local-source Linux receipt installed the exact 214656-byte worker candidate SHA256 `092ef219dee32418ff09d8d61f77048697d672027262a649045881472a004d74`, ran seven offline comparisons, upgraded to a help-only fixture, rolled back to identical source bytes and removed both versions without changing sentinels. Its temporary archives were deleted, not published. That receipt predates the final integrated binary; final-asset validation is recorded separately in the release evidence. Neither fixture nor source-only installation establishes personal-M5/hive behavior, a minimum kernel, live API compatibility or independent cartridge readiness.
