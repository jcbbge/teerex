# Install or upgrade the published alpha.5, without restarting Rex

**Current selected release: [v0.1.0-alpha.5](https://github.com/jcbbge/teerex/releases/tag/v0.1.0-alpha.5), source commit `682489d66dfdb39992b1b2e9f05054bcc009e6d7`.** This current-source setup guide supersedes its alpha.3 procedure. Historical release guides and alpha.5's frozen binary README/onboarding archive remain unchanged; a later documentation commit is not a new binary release.

## Who / What / When / Where / Why / How

- **Who:** the account owner or their expressly authorized local installation agent; no sudo or new machine access.
- **What:** install or upgrade the combined experimental CLI, verify exact public bytes and retain a rollback version. Independent catalogs are separate, optional installations.
- **When:** after reviewing the exact published release and the existing managed root; not automatically whenever main changes.
- **Where:** Apple-silicon macOS or Linux x86_64, inside the agreed user-owned root, default `$HOME/.local/opt/teerex`. Never adopt an unmanaged manual directory.
- **Why:** gain inspectable surfaces, boards, seat/decisions, managed launch/responsibility, structural recovery/manual update inventory and named-host fleet tools without disturbing existing agents.
- **How:** use the pinned source installer and checksummed matching core below. Install code only; live reads, palette/config changes, agent-core migration, fleet rollout and server operations need their own explicit scope.

## Source-only follow-ons are not an alpha.5 upgrade

Published alpha.5 is still the release selected below. Later source adds [`run-visible`](../../items/run/VISIBLE.md) and [`targets exec --tty`](../fleet-install.md#source-only-interactive-transport); neither exists in its immutable archives. A source build can still print `teerex 0.1.0-alpha.5`: record the exact source commit and built SHA256, not that string as release-byte proof. #14/#21, #16 nested routing, real Rivet harness/fence/service cutover and fallback deletion are not completed by these additions.

- **Who:** an explicitly authorized source reviewer; this route does not install globally or authorize running commands on a personal server.
- **What:** build a separate inspectable candidate and read its help. Existing managed release, launcher, profiles, Rex and live panes stay untouched.
- **When:** deliberately evaluating newer source, not while following the published-release installation branch below.
- **Where:** a new private checkout/output directory on Mac arm64 or Linux x86_64, with Git, Zig0.15.2 and Python3.9+ already available. Runtime run-visible requires an explicitly selected existing API13 server; child streams are noninteractive pipes.
- **Why:** review the new visible argv/output/exit lifecycle without confusing it with frozen release bytes or prematurely applying the opt-in [Rivet adapter](../../items/run/MIGRATION.md).
- **How:** substitute the exact reviewed pushed40-hex integration commit below. Leave the candidate separate, record its hash and use only its absolute path after any separately authorized runtime review. Missing tools or an unsupported API are blockers, not permission to install packages or restart Rex.

```sh
set -euo pipefail
umask 077
SOURCE_COMMIT=REPLACE_WITH_REVIEWED_40_HEX_INTEGRATION_COMMIT
[[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] # stop until the exact reviewed commit is supplied
WORK=$(mktemp -d)
git clone --quiet --filter=blob:none --no-checkout https://github.com/jcbbge/teerex.git "$WORK/source"
git -C "$WORK/source" fetch --quiet --depth 1 origin "$SOURCE_COMMIT"
git -C "$WORK/source" checkout --quiet --detach "$SOURCE_COMMIT"
test "$(git -C "$WORK/source" rev-parse HEAD)" = "$SOURCE_COMMIT"
test "$(zig version)" = 0.15.2
(
  cd "$WORK/source"
  zig build -Doptimize=ReleaseSmall --prefix "$WORK/build"
)
CANDIDATE="$WORK/build/bin/teerex"
"$CANDIDATE" run-visible --help
"$CANDIDATE" targets exec --help
if [ "$(uname -s)" = Darwin ]; then shasum -a 256 "$CANDIDATE"; else sha256sum "$CANDIDATE"; fi
```

Verification above is offline help/build verification, not a live command or compatibility test. Runtime limits, exact required env/stdin files, output retention, default close/keep-open, cancellation and uncertain cleanup are in the [WWWWW+H contract](../../items/run/VISIBLE.md); only disposable fixtures are authorized by repository tests. To roll back this source evaluation, stop invoking the candidate and keep using the untouched managed release. Do not delete retained launch evidence, close personal panes, replace launchers or rerun an uncertain command as a rollback side effect. Publishing source does not create a checksummed binary release.

## Supported platforms and API boundaries

| Operation | Supported contract / executed coverage |
| --- | --- |
| Core install, inspect, verify, upgrade, retained rollback | Darwin arm64 / Linux x86_64; no running Rex or Zig required. |
| `observe`, `watch`, low-level `send`/argv `spawn`, `adapters` | Numeric API10–13 on Mac/Linux; actual Mac API10/12/13 and Linux API13 tested. Creation/paste ACK is not agent readiness or consumption. |
| `surfaces` and native palette | Actual Mac API10/12/13 and Linux API13 tested; palette apply is a separate authorized config mutation. |
| Managed profiles/agents, `jobs`, snapshot/restore | API13 on Mac/Linux. Snapshot/restore is structural, not authoritative draft recovery or generic harness resume. |
| Seat/inbox/typed decisions; foreground boards | Private typed store works independently; API13 live inventory tested. Unsupported/unavailable hosts stay unknown, never inferred idle/dead. |
| `update` inventory/manual handoff | Numeric API10–13; actual Mac API10/12/13 and Linux API13 tested. No updater, restart or pane closure runs. |
| `run`, `doctor`; `offstage` | Mac API10–13 for run/doctor; Mac API13 for offstage. No Linux runtime support; offstage is not a hidden-agent launcher. |
| Offline compare/filter/cache; maneuver library | Observation schema1/API10–13; maneuvers require API13 saved evidence. No live input/replay follows a match. |

API11 has numeric acceptance, not actual-build certification. Four release-head [CI lanes passed](https://github.com/jcbbge/teerex/actions/runs/43294504395); this does not certify every build, personal m5/hive/m1, exact issue #10 attached-host topology, native Rex.app painting or real paid-harness hooks. [Full release matrix and remaining gates](../releases/v0.1.0-alpha.5.md).

Prerequisites: Git/HTTPS for the pinned checkout; Bash, curl, tar/gzip, file, awk/grep and platform checksum tools ([installer dependencies](../install.md#review-verify-and-install)). Python3.9+ is required for the new operating-layer Python commands and the JSON steps below. Missing tools, permissions or Mac security denial are blockers, not permission to install packages, remove quarantine or disable Gatekeeper. Mac assets are ad-hoc signed, not notarized. Rex is separately acquired and unbundled.

## How: obtain the exact reviewed installer and archive

Run these blocks in Bash, checking each result. Preserve existing checkouts and installations. The new private workspace avoids resetting another agent's files; retain it while its installer/rollback records are needed.

```sh
set -euo pipefail
umask 077
TAG=v0.1.0-alpha.5
RELEASE_COMMIT=682489d66dfdb39992b1b2e9f05054bcc009e6d7
PREFIX="$HOME/.local/opt/teerex" # use the agreed existing root, if different
WORK=$(mktemp -d)
git clone --quiet --branch "$TAG" --depth 1 https://github.com/jcbbge/teerex.git "$WORK/source"
test "$(git -C "$WORK/source" rev-parse HEAD)" = "$RELEASE_COMMIT"
INSTALLER="$WORK/source/tools/install/teerex-install"
BASE="https://github.com/jcbbge/teerex/releases/download/$TAG"
case "$(uname -s)/$(uname -m)" in
  Darwin/arm64) PLATFORM=aarch64-macos ;;
  Linux/x86_64) PLATFORM=x86_64-linux ;;
  *) printf '%s\n' 'Unsupported host; no installation attempted' >&2; exit 1 ;;
esac
ASSET="teerex-$TAG-$PLATFORM.tar.gz"
curl -fLsS "$BASE/SHA256SUMS" -o "$WORK/SHA256SUMS"
curl -fLsS "$BASE/$ASSET" -o "$WORK/$ASSET"
awk -v name="$ASSET" '$2 == name { print; n++ } END { if (n != 1) exit 1 }' \
  "$WORK/SHA256SUMS" > "$WORK/selected.sha256"
(
  cd "$WORK"
  if [ "$PLATFORM" = aarch64-macos ]; then
    shasum -a 256 -c selected.sha256
  else
    sha256sum -c selected.sha256
  fi
)
bash "$INSTALLER" --help
```

Read the pinned installer, `RIGHTS.md` and tagged release guide before applying. Expected selected **archive** SHA256: Mac `7e797d36fc2a1669476bb49ddb29b82dc318e92a373791f64e33e2b7f96453f8`; Linux `90e2cb72f1725e56e3137fcacd62a1f489bb49117cba273c89365d6d1b77848f`. These are not the executable hashes below. Same-release hashes detect changed bytes, not independently authenticate the publisher. The installer rechecks checksum, strict three-file archive shape, architecture and help before activation; do not manually extract unchecked code.

## How: inspect first, then choose exactly one activation

```sh
bash "$INSTALLER" inspect --prefix "$PREFIX" > "$WORK/before.json"
python3 -m json.tool "$WORK/before.json"
PRIOR_TAG=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["ok"] and d["state"] in ("absent","managed") and not d["busy"], "unsafe/unmanaged/busy root; preserve it"; print(d["active_version"] or "")' "$WORK/before.json")
if [ -n "$PRIOR_TAG" ]; then
  bash "$INSTALLER" verify --prefix "$PREFIX" --version "$PRIOR_TAG" > "$WORK/prior-version.json"
fi
```

`unmanaged`, busy/stale locks, malformed layouts or failed verification are blockers: preserve the root and ask for an approved alternative/recovery, not deletion/adoption. Keep the private before/verification records for rollback. Do not run install and upgrade sequentially:

**New root, or valid deactivated root with this tag not yet retained:**

```sh
bash "$INSTALLER" install --version "$TAG" --prefix "$PREFIX" --from "$WORK"
```

**Existing active managed root, this tag not yet retained — use this instead:**

```sh
bash "$INSTALLER" upgrade --version "$TAG" --prefix "$PREFIX" --from "$WORK"
```

If alpha.5 is already retained, verify it and use `rollback --version "$TAG" --prefix "$PREFIX"` only when deliberate reactivation is needed; do not reinstall/overwrite it. If it is already active, verification alone suffices. Stop only your own foreground teerex invocations before switching code; do not stop other agents.

## How: verify installed bytes, without contacting Rex

```sh
bash "$INSTALLER" inspect --prefix "$PREFIX"
bash "$INSTALLER" verify --prefix "$PREFIX" --version "$TAG"
TEEREX="$PREFIX/current/teerex"
"$TEEREX" --version
"$TEEREX" --help
if [ "$PLATFORM" = aarch64-macos ]; then
  shasum -a 256 "$TEEREX"
else
  sha256sum "$TEEREX"
fi
```

Require exit0, `active_version` and `selected_version` equal to `v0.1.0-alpha.5`, version exactly `teerex 0.1.0-alpha.5`, and the correct **executable** SHA256: Mac `1091c39f9273a4a106ee3ab8691e40fcc85a7e8c261bb431c9fb3cc30b39628f` (822392 bytes); Linux `5cfdb12e436367fb3f48ad5903bcb96e5cf3b75eab14bcdd87e2e71ff158c86a` (695680 bytes). Inspect/verify return JSON and do not execute candidate code or contact Rex; explicit version/help do execute the installed CLI. No PATH/profile, launcher, Rex config or running process is changed by installation. Always use the full selected path; cached shell commands may still select an older executable.

## Optional: one separately authorized read-only live check

Installation is complete without a live check. Obtain exact private `SOCKET`, canonical full `SESSION`/`BLOCK` and absolute trusted `REX` executable from the operator's authorized record; never scan neighboring panes or guess from focus/labels. With read/storage authorization, create a private `CHECK_DIR` and run each command separately, checking exit0 before consuming its output:

```sh
CHECK_DIR=$(mktemp -d)
"$REX" --autostart=false --server "unix://$SOCKET" api call server.version > "$CHECK_DIR/version.json"
"$TEEREX" --rex "$REX" observe --socket "$SOCKET" --session "$SESSION" --block "$BLOCK" \
  --max-bytes 600 --timeout-ms 5000 > "$CHECK_DIR/observation.json"
"$TEEREX" compare --before "$CHECK_DIR/observation.json" \
  --after "$CHECK_DIR/observation.json" > "$CHECK_DIR/comparison.json"
```

Parse complete JSON privately: exact target/source/API, capture prefix/completeness/bounds and process/directory/status unknowns must be retained. Self-comparison has no known changes but cannot establish full-text equality for a partial prefix. Do not infer freshness, completion or input permission. This check authorizes no send/spawn/focus/move/close/palette/restore/update/fleet action; do not run integration suites against a personal server. [Feature recipes](features.md) and [current operating-layer guides](../releases/v0.1.0-alpha.5.md#commands-and-tested-support) require their own scope.

## Upgrade / rollback / remove

The upgrade block above retains the prior tag. If an explicit rollback is needed, first review old schema compatibility and preserve new private state. `PRIOR_TAG` must be the actual previously recorded retained tag, not a guessed alpha number:

```sh
test -n "$PRIOR_TAG"
bash "$INSTALLER" verify --prefix "$PREFIX" --version "$PRIOR_TAG"
bash "$INSTALLER" rollback --prefix "$PREFIX" --version "$PRIOR_TAG"
bash "$INSTALLER" inspect --prefix "$PREFIX"
"$PREFIX/current/teerex" --help
```

Rollback downloads nothing, does not contact Rex and does not reverse input, launched processes, jobs/boards data, cartridge selections or schema changes. Older CLIs may not implement `--version`; compare the retained hash with the before record instead. A first install has no automatic prior version: an empty `PRIOR_TAG` is not permission to choose/download one. Review [explicit removal](../install.md#remove-and-finish-uninstalling) separately; active removal requires `--deactivate` and leaves no active CLI.

## Troubleshooting and safe next actions

| Symptom | Check / response |
| --- | --- |
| Unsupported host/tool, checksum/architecture/help failure, Mac security denial | Keep active bytes; report the actual failure. No sudo, package install, platform fallback or validation/security bypass. |
| Unmanaged root, modified version or stale/busy lock | Preserve files; investigate exact ownership/in-flight operation or choose a separately approved root. No recursive deletion or automatic lock removal. |
| Missing socket, unsupported API, source/target mismatch or partial stdout | Check exact authorized endpoint/version and full exit/schema. No Rex autostart/update/restart or pane closure as repair. |
| Unknown/lost mutation ACK | The effect may exist. Inspect only the authorized resource; no automatic retry, recreate, resend or cleanup-close. |

Full restart/draft recovery, real harness/custom-guard parity, arbitrary separate-host replies, exact issue #10 topology and consolidated agent-core deletions remain gated. The reported [intermittent SSH spawn/send failure (#12)](https://github.com/jcbbge/teerex/issues/12) is not established fixed by upgrading; retain the complete failure/attempt evidence and do not blindly retry uncertain mutations. Preserve working stopgaps. Strong host leases, human revocation and isolation are not supplied by client locks. `update` is inventory/manual handoff, not a server updater. Fleet/config/palette changes are not part of this local install.

Return a sanitized receipt: tag and source commit, platform, binary hash, active/retained tags, command exits and decoded checks, limitations and exact rollback command. Keep roots/endpoints/IDs, captures, message bodies, policies and credentials private. Installation success is not personal-machine live compatibility or completion of gated migrations.
