# Install, upgrade, roll back, and remove teerex

The reviewed source-tree installer manages one shared experimental CLI inside your home directory on **Darwin arm64** or **Linux x86_64**. [Alpha.3](releases/v0.1.0-alpha.3.md) provides both platform archives. Rex is separately obtained and never bundled, installed, upgraded or restarted by this tool. Earlier alpha.1/alpha.2 releases have only a Mac asset; selecting an absent platform asset fails without replacing the active version.

This is **not independent cartridge packaging**. The commands share one executable and cannot yet be individually installed/removed; no `--all` or cartridge selector exists. Source-tree features newer than a selected tag do not appear in its binary. Installation needs no Zig, running Rex or administrator privileges.

## Review, verify and install

Run from a reviewed checkout containing `tools/install/teerex-install`; do not pipe a remote script into a shell. The installer is a source-tree tool, not included inside the binary archive.

```sh
bash tools/install/teerex-install --help
bash tools/install/teerex-install install --version v0.1.0-alpha.3
"$HOME/.local/opt/teerex/current/teerex" --help
bash tools/install/teerex-install list
```

The explicit tag is mandatory; nothing guesses `latest`, polls or autoupdates. Downloads use HTTPS release assets from `github.com/jcbbge/teerex`:

- Mac: `teerex-TAG-aarch64-macos.tar.gz`, an arm64 Mach-O executable.
- Linux: `teerex-TAG-x86_64-linux.tar.gz`, an ELF64 little-endian x86-64 executable.
- External `SHA256SUMS`, with exactly one entry for the selected archive; entries for other assets may coexist.

Archives must contain exactly three regular, top-level files: `teerex`, `README.md` (that release's guide), and `RIGHTS.md`. Validation checks the archive checksum before extraction, rejects extra/duplicate paths and links, checks executable format/architecture, and runs `--help` before activation. Rollback also verifies host architecture. Download, checksum, archive, binary or help failure does not replace the active version, and there is no cross-platform fallback. A failed first install can leave an empty managed root, reusable by `install`.

Mac uses system Bash 3.2 and stock tools. Linux requires Bash, GNU coreutils (`sha256sum`, `mv`), `tar`, `gzip`, `file`, `awk`, `grep`, and `curl` with usable HTTPS certificates. Missing tools produce a diagnostic, never package installation. To use explicitly reviewed local assets, place archive and checksums in one directory:

```sh
bash tools/install/teerex-install install --version v0.1.0-alpha.3 \
  --from "$HOME/Downloads/teerex-alpha.3"
```

`--from` avoids downloads, not checksum/executable validation or the requirement to trust that source. Same-release checksums detect changed bytes, not independently authenticate a publisher. The Mac binary is **not Developer-ID-signed or notarized**; browser-quarantine/Gatekeeper acceptance remains unverified. The installer does not remove quarantine, disable security or bypass a denial.

The Linux CLI is built with Zig 0.15.2, `ReleaseSmall`, `x86_64-linux-musl`. `file`/`readelf` inspection verifies static ELF64 x86-64 with no interpreter/dynamic section, hence no host glibc dependency. The installer checks host format/architecture and actual help, not libc linkage or minimum kernel compatibility. Debian 13/kernel 6.1.189+ and Ubuntu 24.04.5 userland on that same kernel have runtime evidence; this is not an independent Ubuntu-kernel or hive guarantee. See [Linux evidence](linux.md).

## Managed layout and concurrent operations

```text
~/.local/opt/teerex/
  .teerex-install-root
  versions/v0.1.0-alpha.3/
    teerex
    README.md
    RIGHTS.md
    .files.sha256
  current -> versions/v0.1.0-alpha.3
```

For a custom location, pass `--prefix "$HOME/somewhere/teerex"` on **every** lifecycle command. It must be a new, user-owned path inside HOME, with no symlink ancestors or dot components; an existing unmanaged directory is not adopted or overwritten. Spaces work. Keep roots host-local, not shared between Mac/Linux. The executable is account-private; no global launcher is installed.

A short-lived lock and staging directory live under the root. Concurrent installer operations refuse rather than race. After a crash/SIGKILL, verify that no installer is running before deliberately removing its stale `.installer-lock` or interrupted `.stage.*` directories. No daemon, service, watcher or automatic command history is created.

## PATH, compatibility and operator machines

Use the full executable path above. Deliberately add `$HOME/.local/opt/teerex/current` through your own shell workflow only if desired. No `.zshrc`, `.zprofile`, profile, Rex `init.lua`, key binding, existing binary or setting is edited. Remove any PATH change you made yourself when uninstalling.

Integrity/help success is **not live compatibility**. Alpha.3 has per-command OS/API limits: observe/watch/send/spawn accept integer API10–13; run and doctor runtime remain Mac-only; offstage remains Mac/API13-only; maneuver definitions remain API13-only. See the selected [release guide](releases/v0.1.0-alpha.3.md) and item contracts. API11 numeric acceptance is not actual-build certification. Historical alpha.1 is API13-only and has no doctor; alpha.2 adds the compatibility fix but no newer commands.

**Never update, restart or auto-start Rex as an installation prerequisite.** Updates can close panes. Choose a compatible release while preserving the existing server. Joshua's setup agent supplied M5/API10 and hive/API13 observations; installer/disposable-platform tests do not constitute personal-machine validation. Every agent/worker/sidecar/message on his machines must remain visible through authorized Rex/teerex routing, including Rivet; installation creates no hidden-worker exception. Setup/guard migration remains separate ownership. This installer never connects to a server, launches an agent, accesses hive or changes agent-core/Rivet configuration.

## Upgrade and rollback

Choose a real reviewed release tag, not the literal `TAG`:

```sh
bash tools/install/teerex-install upgrade --version TAG
"$HOME/.local/opt/teerex/current/teerex" --help
bash tools/install/teerex-install rollback --version v0.1.0-alpha.3
```

Upgrade requires an active, integrity-checked installation, stages/validates the chosen version, and atomically replaces `current`. Explicit selection, not semantic-version ordering, determines the destination. Previous versions stay installed. A repeated tag is never overwritten. Rollback activates only a retained, integrity/architecture-checked version, without downloading or invoking Rex. `.files.sha256` detects accidental modification, not another process with your account's write authority.

Stop foreground teerex invocations before switching/removing versions. This installer is not a supervisor and does not stop existing workers, terminals or invocations. Programs using a fixed version path or shell command caches may still select the old binary; verify through `current/teerex`.

## Remove and finish uninstalling

```sh
# Inactive version:
bash tools/install/teerex-install remove --version v0.1.0-alpha.3
# Or deliberately deactivate and remove the active version:
bash tools/install/teerex-install remove --version v0.1.0-alpha.3 --deactivate
bash tools/install/teerex-install list
```

`--deactivate` leaves no active executable; no older version is silently selected. Removal deletes only the four known, integrity-checked version files and their directory. Modified, missing, symlinked or extra files cause refusal before deletion. No explicit captures, user data, program-created files or Rex configuration are removed.

After explicitly removing every listed version, inspect the remaining marker and empty directories, then use your actual root:

```sh
rmdir "$HOME/.local/opt/teerex/versions"
rm "$HOME/.local/opt/teerex/.teerex-install-root"
rmdir "$HOME/.local/opt/teerex"
```

`rmdir` refuses nonempty directories; do not substitute recursive removal. Source checkouts, installer scripts and downloaded assets are separate files you may retain or remove yourself. Independent cartridges remain future work; no license has been selected ([rights](../RIGHTS.md)).

## Validation boundaries

`python3 tools/install/test_install.py --public -v` runs 14 tests on disposable Darwin arm64 and Linux x86_64, using temporary HOME/roots and native help-only fixtures. It exercises install/upgrade/rollback/remove, wrong architecture, malformed/checksum/archive failures, refusal to replace user files and unchanged shell/Rex/launcher sentinels. Python/native C compiler are test dependencies, not installer dependencies. Historical public controls intentionally retain immutable alpha.1: Mac genuinely downloads/executes its 300712-byte binary, SHA256 `c39108dc3bfedf240c62c4f7b0c683f6f06b5ef59fa78cd377aa8b38b007abe9`, then upgrades to a local fixture and rolls back to identical bytes; Linux verifies the real absent-alpha.1-Linux-asset failure preserves the active fixture. These are not relabelled alpha.3 checks.

Both platforms passed all 14 controls; Mac used system Bash 3.2 on macOS27.2 and Linux used Debian13. ShellCheck0.10.0 and Bash syntax passed. A separately labelled pre-integration local-source Linux receipt installed the exact 214656-byte worker candidate SHA256 `092ef219dee32418ff09d8d61f77048697d672027262a649045881472a004d74`, ran seven offline comparisons, upgraded to a help-only fixture, rolled back to identical source bytes and removed both versions without changing sentinels. Its temporary archives were deleted, not published. That receipt predates the final integrated binary; final-asset validation is recorded separately in the release evidence. Neither fixture nor source-only installation establishes personal-M5/hive behavior, a minimum kernel, live API compatibility or independent cartridge readiness.
