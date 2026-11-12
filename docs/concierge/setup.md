# Install, verify, update and recover

## Who / What / When / Where / Why

- **Who:** the account owner or their local setup agent, within explicit installation and target authorization. No administrator privileges are required or requested.
- **What:** install one versioned shared teerex executable and keep an explicit rollback path. Installation does not install Rex, independent cartridges or a launcher.
- **When:** after reviewing an exact published tag and its per-command platform/API limits; not whenever main changes or an agent proposes a flag.
- **Where:** a user-owned root under HOME, default `$HOME/.local/opt/teerex`. Keep roots local to one host/platform. Never adopt an unmanaged directory.
- **Why:** avoid replacing unrelated binaries, changing shell/Rex settings or losing the prior release when a new version fails validation.

## How: prepare an exact source checkout

Prerequisites: Git and trusted HTTPS access for the checkout; Bash and the tools listed in [installer prerequisites](../install.md#review-verify-and-install) for installation. Darwin arm64 uses stock tools/Bash3.2. Linux x86_64 needs Bash, coreutils, tar/gzip, file, awk/grep and curl with working certificates. Missing tools are a blocker, not authorization to install packages. Neither Zig nor a running Rex is needed to install a release binary. A source build instead requires Zig0.15.2 and is not the published asset.

Use a new directory you own; the example destination must not already exist. Read commands before executing. This tag is deliberately fixed, not `latest`:

```sh
umask 077
git clone --branch v0.1.0-alpha.3 --depth 1 https://github.com/jcbbge/teerex.git "$HOME/teerex-alpha.3-source"
git -C "$HOME/teerex-alpha.3-source" rev-parse HEAD
```

Expected commit: `8b2827860029e30a3ad5724d357655de155520d5`. Review `docs/releases/v0.1.0-alpha.3.md`, `docs/install.md`, `RIGHTS.md` and `tools/install/teerex-install` in that checkout. Do not pipe an unaudited download into a shell. If that directory already exists, verify its origin, commit and local changes or choose a new directory; never reset/overwrite it merely to follow this example.

From the reviewed source root:

```sh
bash tools/install/teerex-install --help
bash tools/install/teerex-install list
```

For a first install, `list` reports no managed installation and exits1; that is expected, not a request to fix/create arbitrary directories. For an existing managed root it shows tags and the active tag. Use `--prefix "$HOME/chosen/teerex"` on **every** lifecycle operation if a custom root was agreed.

```sh
# New managed root only:
bash tools/install/teerex-install install --version v0.1.0-alpha.3
# Existing managed active root, instead:
# bash tools/install/teerex-install upgrade --version v0.1.0-alpha.3
TEEREX="$HOME/.local/opt/teerex/current/teerex"
"$TEEREX" --help
bash tools/install/teerex-install list
```

Run exactly one install/upgrade branch. An already retained identical tag is not overwritten; inspect `list` and use explicit rollback to reactivate a retained verified tag when appropriate. Installer success means checksum, strict archive shape, host executable format and help passed before activation. It does not prove live compatibility. It creates no PATH/profile/config edit, service, watcher or server. Retain the selected source installer separately: binary archives contain only teerex, release README and RIGHTS.

Expected alpha.3 binary SHA256: Linux `8467c5acfc92ad6ee4c8f726b7dc33e25cb73722b8a19c62ea78bb68af848dd7`; Mac `99679a4ff95119e74cac900ce10af9b4be35f3073a6aaab2f8c76f3a80261cd0`. Use `sha256sum "$TEEREX"` on Linux or `shasum -a 256 "$TEEREX"` on Mac. Release checksums detect modified bytes, not independently authenticate the publisher. For reviewed offline assets use `install --version v0.1.0-alpha.3 --from /absolute/private/asset-directory`; the directory must contain the matching archive and external SHA256SUMS. Validation is not bypassed. See [manual archive validation](../releases/v0.1.0-alpha.3.md#download-and-validate) if not using the installer.

## Optional: verify one authorized existing target, without restarting

Installation can finish without endpoint access. Obtain private `SOCKET`, `SESSION`, `BLOCK` values from the local operator's authorized target record, and select a trusted separately installed `rex` on PATH. The socket must be absolute; IDs must be canonical full lowercase UUID addresses, not suffixes or window names. Do not discover endpoints by scanning other agents' panes. All files below are deliberately private; `mktemp` chooses a local temporary directory, not a public repository:

```sh
umask 077
CHECK_DIR=$(mktemp -d)
rex --autostart=false --server "unix://$SOCKET" api call server.version > "$CHECK_DIR/version.json"
"$TEEREX" observe --socket "$SOCKET" --session "$SESSION" --block "$BLOCK" \
  --max-bytes 600 --timeout-ms 5000 > "$CHECK_DIR/observation.json"
"$TEEREX" compare --before "$CHECK_DIR/observation.json" \
  --after "$CHECK_DIR/observation.json" > "$CHECK_DIR/comparison.json"
```

Run each command separately and check exit0 **before** using its output. A shell redirection can leave a partial/empty file even on failure. Decode the complete JSON privately: the observation must carry the exact target and actual server version/platform/API revision; capture budget/prefix/completeness and process/directory/status provenance/unknowns must be retained. Self-comparison should have no known value or availability changes, with unknown full text when capture is partial. IDs and timestamps do not prove authenticity or freshness. JSON syntax alone is not a successful smoke.

Then, if a foreground wait is authorized:

```sh
"$TEEREX" watch --socket "$SOCKET" --session "$SESSION" --block "$BLOCK" \
  --baseline "$CHECK_DIR/observation.json" --timeout-ms 1000 > "$CHECK_DIR/watch.json"
```

An idle designated pane normally yields exit124 / `deadline_exceeded`; exit0 means changed evidence, **not completion**. Exit1,2,130,143 are not a pass. Inspect the complete wait packet and source/target. `doctor --socket "$SOCKET"` is an optional Mac-only advertised-requirements check, always `behavior_certified=false`; it cannot substitute for observe or certify other commands. No Linux runtime doctor or run probe is supported.

Execution, spawning or sending is not part of this read-only smoke. Only if separately authorized, use the per-feature recipes on the expressly designated disposable execution pane/server. All other panes are live-agent boundaries. Do not run integration suites against a personal endpoint; suites create their own disposable servers and some deliberately exercise surviving descendants.

## Upgrade / rollback / remove

Stop your own foreground teerex invocations before switching versions; do not stop other agents. Read the new **published** tag's release/feature/schema notes first and preserve current private data. No follow-on version is selected in this guide. After setting `NEXT_TAG` to an approved real release and `PRIOR_TAG` to the verified retained version:

```sh
bash tools/install/teerex-install upgrade --version "$NEXT_TAG"
"$HOME/.local/opt/teerex/current/teerex" --help
bash tools/install/teerex-install list
# If verification fails, explicitly restore the retained known version:
bash tools/install/teerex-install rollback --version "$PRIOR_TAG"
"$HOME/.local/opt/teerex/current/teerex" --help
```

Check status, hash, help and the scoped smoke again. Upgrade retains previous versions; rollback does not download. Fixed version paths and shell command caches can continue using old bytes: verify through `current/teerex`. Binary rollback does not roll back program side effects, terminal input, launched workers or private schemas/data; do not feed new schemas to an old release without checking compatibility.

To remove exactly alpha.3, select **one** appropriate branch after checking `list`:

```sh
# Inactive release:
bash tools/install/teerex-install remove --version v0.1.0-alpha.3
# Active release, instead (leaves no active binary):
# bash tools/install/teerex-install remove --version v0.1.0-alpha.3 --deactivate
bash tools/install/teerex-install list
```

Removal refuses modified/extra/symlinked version files before deletion. It removes neither captures nor source/download directories nor existing workers. Close/stop only explicitly owned resources with separate authorization, not as a binary removal side effect. Remove only named private capture/message files you elected to retain; choose retention before deletion. For an entirely empty managed root, use the nonrecursive final cleanup in [uninstall](../install.md#remove-and-finish-uninstalling). Remove any PATH entry you personally added; none was installed automatically.

## Troubleshooting and safe next actions

| Symptom | Check / response |
| --- | --- |
| Unsupported host, missing tool, missing release asset | Verify uname and selected release matrix. Report the unsupported operation. Do not sudo, install packages, switch architectures or substitute an unreleased binary without authorization. |
| Checksum, archive, architecture or help failure | Keep the active version. Reacquire exact assets from the chosen source and investigate mismatch; never skip validation. Mac security denial is a blocker, not a quarantine/Gatekeeper bypass recipe. |
| Unmanaged root / modified version / stale installer lock | Preserve files. Choose another approved root, or inspect modifications. For stale locks verify no installer is running before deliberately removing only that lock/stage; do not recursively delete the root. |
| Missing socket / API refusal / absent consumed binding | Check the already-approved absolute socket and independently queried server version. Keep actual API in the report. Never restart/update/autostart Rex or close panes as repair. |
| Empty, malformed or partial stdout | Check exit code/stderr, permissions and storage/output limits. Do not promote partial evidence to a successful observation or retry a mutation blindly. |
| Source/target mismatch / retained baseline drift | Stop that comparison/wait. Confirm correct source/target; take a new baseline only with read/storage authorization. Do not rewrite old evidence to make labels agree. |
| Truncated capture / null process or reports / watch deadline | Preserve unknowns. Increase capture budget only within limits and read authorization; do not infer idle, done, failure or input safety. |
| Spawn/send/offstage lost ACK or cancellation | Effects may already exist. Inspect only the selected authorized resource and known IDs; never automatically retry, close by a guessed label, resend or retract queued bytes. |

A useful sanitized handoff reports selected tag/commit, OS/architecture, binary hash, CLI/server versions/API, each exit code, decoded-node checks, unsupported/skipped work and retained rollback tag. Do not share raw terminal content, messages, endpoint/session/block values, private filenames or credentials. Installation success, disposable-platform evidence and exact personal-machine feature verification are separate claims.
