# Alpha.4 follow-on concierge

**These five streams belong to v0.1.0-alpha.4, not frozen alpha.3.** The [final release guide](../releases/v0.1.0-alpha.4.md) supplies command/API domains, exact binary identities and distribution layout. Confirm the [published tag and assets](https://github.com/jcbbge/teerex/releases/tag/v0.1.0-alpha.4) before installation; branch/source candidates and scratch binaries are not release assets. This guide was prepared against transferred source and the clean combined candidate, then included in the shipment. It is not installation authorization. The [alpha.3 guide](features.md) remains a version-pinned baseline; do not use `latest` or silently install main over a working binary.

## Delivery gate for every follow-on

The shipping owner must identify the integrated commit, published tag/assets and hashes, final platform/API matrix, integrated tests and any schema/data changes before a local setup agent upgrades. First check that **that exact executable's help** contains the command. The shared [install/update/rollback/remove procedure](setup.md) applies only once that real release exists; candidate source builds below are developer validation, not personal-machine installation. Keep current binaries/private state unchanged while inspecting candidates. Cartridge tooling has a separate code/data root and is not the core installer.

For each feature the sections below give Who/What/When/Where/Why/How, private state, verification, troubleshooting and lifecycle. `TEEREX` below denotes the explicitly selected verified alpha.4 binary; before publication it denotes only an integrated candidate in a disposable test environment. Private variables come from an operator's explicit target authorization; `SOCKET`, `SESSION`, `BLOCK`, `CHECK_DIR` and `WORKSPACE` have the [same meanings as the alpha.3 guide](features.md#recipe-inputs-and-common-checks). No restart/autostart/update or access to another live-agent pane is authorized. A candidate test pass does not grant execution, input, export or machine access.

## Alpha.4 delivery layout and upgrade

Use this layout only after verifying the exact public release page, selected checksums and executable identity. Source and documentation alone do not establish asset availability:

- Core archives `teerex-v0.1.0-alpha.4-aarch64-macos.tar.gz` / `teerex-v0.1.0-alpha.4-x86_64-linux.tar.gz` keep exactly three top-level regular files: teerex, README.md release guide, RIGHTS.md. They do not contain the installer/manager/concierge source.
- Separate `teerex-v0.1.0-alpha.4-onboarding.tar.gz` preserves source-relative guide/tool paths, including `docs/concierge`, installation/cartridge guides, item READMEs, root README/RIGHTS, `tools/install/teerex-install`, and `tools/cartridges/cartridges.py`. Use this reviewed root or tagged source as the working directory, not the three-file binary extraction root. Source builds/tests require the actual source checkout, not just onboarding files. Secondary research/implementation links refer to the tagged repository if those files are not included.
- Separate native catalogs: `teerex-v0.1.0-alpha.4-cartridges-aarch64-macos.tar.gz` and `teerex-v0.1.0-alpha.4-cartridges-x86_64-linux.tar.gz`. The manager remains in source/onboarding, not inside the core binary or implied by the catalog. Review the extracted `catalog.json` root and exact manifest hashes before selecting items.

After publication, obtain the matching core, onboarding, optional catalog and external SHA256SUMS from the exact v0.1.0-alpha.4 release. Verify every selected archive using `shasum -a 256 -c` on Mac or `sha256sum -c` on Linux, selecting its exact entry as in the [alpha.3 download recipe](../releases/v0.1.0-alpha.3.md#download-and-validate); absent/duplicate/mismatched entries are blockers. Inspect archive members and extract only into new private owned directories. No pipe-to-shell or security bypass. The final release guide must supply identities and any archive-layout differences; these docs do not invent future hashes.

Once the later release is verified, from its reviewed source/onboarding root, with an **existing active** managed core and alpha.3 retained:

```sh
bash tools/install/teerex-install upgrade --version v0.1.0-alpha.4
TEEREX="$HOME/.local/opt/teerex/current/teerex"
"$TEEREX" --help
"$TEEREX" jobs --help
"$TEEREX" adapters --help
"$TEEREX" filter cache --help
"$TEEREX" maneuver-check --help
bash tools/install/teerex-install list
```

For a new root use `install` instead of `upgrade`; use the same approved custom `--prefix` everywhere if applicable. Help must expose the four new surfaces and the retained alpha.3 commands; help alone does not prove runtime behavior. Repeat the [non-restarting authorized smoke](setup.md#optional-verify-one-authorized-existing-target-without-restarting) and only separately approved per-feature checks below. Jobs live checks are API13-only; do not run them on the API10 M5 server. Independent cartridge installation is optional and separate; no automatic agents, catalogs, cache writes or machine/Rivet migration.

If validation fails, stop your foreground invocations, deal explicitly with any intended private-cache retention/removal using a cache-capable binary, then `bash tools/install/teerex-install rollback --version v0.1.0-alpha.3` and recheck hash/help. An active alpha.4 can later be removed with `remove --version v0.1.0-alpha.4 --deactivate` only after deliberate deactivation; an inactive version uses `remove` without that flag. Neither changes jobs/workers/input/data. Keep the older binary and private state; core rollback does not roll back cartridge selections or new schemas. No alpha.4 installation is claimed here before publication.

## 1. Independent cartridges

- **Who:** the account owner/local setup agent after source/catalog review and explicit selection; never root/sudo.
- **What:** standalone native item payloads, exact dependency resolution, plan/apply, retained code versions, explicit activation and reversible retirement. Not wrappers around the combined CLI.
- **When:** choose individual items or ready-only `--all`; current manifests are all experimental, so default `--all` selects **zero**. `--allow-experimental` is explicit opt-in, not ready certification.
- **Where:** Python3.9+ standard-library manager, Darwin arm64/Linux x86_64, canonical user-owned HOME. Default root `$HOME/.local/opt/teerex-cartridges`; custom `--root` precedes the subcommand and must remain inside HOME without symlink ancestors. Keep it separate from the core root.
- **Why:** genuinely independent add/remove with dependencies and user data retained, without mutating Rex/shell/config or a mutable core executable.
- **How:** actual source manager help is `python3 tools/cartridges/cartridges.py --help`. A reviewed explicit-version native catalog is required, not downloaded implicitly. Builders need Zig0.15.2; setup agents receiving a reviewed catalog do not need Zig. Developer build recipe (`CATALOG_VERSION` is an explicitly chosen package semver without `v`, **not a release announcement**; `CATALOG` must be a new canonical output path):

```sh
python3 tools/cartridges/package.py --zig "$ZIG_BIN" --platform x86_64-linux \
  --version "$CATALOG_VERSION" --output "$CATALOG"
# On/for Apple silicon select --platform aarch64-macos instead.
```

Catalog manifests pin hashes/entrypoints/permissions/compatibility/dependencies and report source identity/dirty state; hashes do not authenticate the publisher. The pending combined catalog adds standalone jobs/adapters to the initial leaf payload set: **10 Mac** (observe/run/spawn/send/offstage/doctor/maneuvers/filter/jobs/adapters), **7 Linux** (observe/spawn/send/maneuvers/filter/jobs/adapters). Verify this membership in the final selected catalog; alpha.3 has no such catalog. API domains remain each item's contract, including jobs API13-only; payload count is not a certification matrix.

Plan before applying, then verify actual standalone help and list:

```sh
python3 tools/cartridges/cartridges.py --root "$CARTRIDGE_ROOT" install filter \
  --catalog "$CATALOG" --allow-experimental
# Only after approving that plan:
python3 tools/cartridges/cartridges.py --root "$CARTRIDGE_ROOT" install filter \
  --catalog "$CATALOG" --allow-experimental --apply
python3 tools/cartridges/cartridges.py --root "$CARTRIDGE_ROOT" list
python3 tools/cartridges/cartridges.py --root "$CARTRIDGE_ROOT" run filter -- --help
```

The filter payload takes its own flags directly; observation retains its three verbs (`run observe -- compare --before FILE --after FILE`). Other standalone payloads omit the combined CLI verb. Lifecycle success is exit0/schema1 JSON `ok`, `operation`, `applied`; plan has no mutation. After `run` exec, stdout/stderr/status are the real payload contract, not a manager receipt. Verify the selected version/hashes and help; installation deliberately does **not** execute package code. Live feature tests remain separate. [Full source contract](../cartridges.md).

**Update / rollback / remove / undo:** install from an explicitly reviewed newer catalog using the same plan/apply flow; old versions remain. To roll back, set `PACKAGE_VERSION` to an actual retained version. These operations have dry plans when `--apply` is omitted:

```sh
python3 tools/cartridges/cartridges.py --root "$CARTRIDGE_ROOT" activate filter \
  --version "$PACKAGE_VERSION" --apply
python3 tools/cartridges/cartridges.py --root "$CARTRIDGE_ROOT" remove filter \
  --version "$PACKAGE_VERSION" --deactivate --apply
python3 tools/cartridges/cartridges.py --root "$CARTRIDGE_ROOT" restore filter \
  --version "$PACKAGE_VERSION" --apply
# Restore is INACTIVE; deliberately activate separately if desired.
```

Removal retires verified code and leaves the item inactive, no fallback. `ROOT/data/ID` survives all code changes/removal/restore; rollback does not roll back data. No purge/garbage collection, hooks, autostart or data migration. Active dependents block removal; pins/cycles/missing/conflicting dependency versions refuse before activation. Never garbage-collect a shared dependency merely because one dependent was removed.

**In-use / recovery / safety:** per-version advisory leases inherited by `run` and its dependencies refuse affected changes; unrelated items remain removable. Direct execution, closed inherited FDs, detached work or other agents bypass this cooperative boundary. It is neither an input lease nor whole-descendant protection; the core installer has no matching lease protocol. Manifest permissions disclose rather than enforce authority. Modified/extra/linked payloads refuse, not delete. Exit1 carries JSON error on stderr; argparse errors2. Preserve state/code on corruption, in-use refusal or crash orphan `.stage-*`/unregistered directories; inspect registry and bytes manually, never auto-adopt/purge or kill a process to force removal. Normal staged-write rollback is not SIGKILL/power-loss transaction recovery. Mac/Linux native payload help/offline contracts were tested by the owner; personal M5/hive and final release assets are not thereby verified.

## 2. Durable jobs and deliberate presentation

- **Who:** an operator recording responsibility for one authorized existing resource; `owner` is a label, not authenticated identity or native/process authority.
- **What:** `jobs track/list/inspect/adopt/present/forget`, durable bounded local registry, explicit generation/reason/targets; no launch, daemon or process-stop operation.
- **When:** retain responsibility across CLI exit, explicitly hand it off or present a known result. Lost ACK/expired deadline/offline owner is not permission to adopt or stop.
- **Where:** live **API13 only**, `darwin_arm64`/`linux_amd64`; `list`/`forget` offline. Existing operator-chosen UID-owned0700 registry; single-link regular/no-follow files0600. Trusted local parents/filesystem required.
- **Why:** distinguish durable responsibility and presentation intent from resource existence, freshness and actual cleanup.
- **How:** first check `"$TEEREX" jobs --help`. Create exactly the approved new registry directory with private permissions (`umask 077; mkdir -m 700 "$REGISTRY"`); parents must already exist. Never chmod/adopt an unknown existing directory to make validation pass. Choose a future absolute Unix-ms review deadline ≤30 days ahead. Example registration of a **visible** agent:

```sh
"$TEEREX" jobs track --registry "$REGISTRY" \
  --socket "$SOCKET" --session "$SESSION" --block "$BLOCK" \
  --owner operator --kind agent --purpose 'review this visible worker' \
  --deadline-unix-ms "$REVIEW_DEADLINE_MS" --cleanup manual
"$TEEREX" jobs list --registry "$REGISTRY"
"$TEEREX" jobs inspect --registry "$REGISTRY" \
  --socket "$SOCKET" --session "$SESSION" --block "$BLOCK"
```

Exit0 plus complete JSON means requested record/evidence checks succeeded, not task completion. List is saved metadata with `live_state=not_checked`; inspect sequentially revalidates server instance/host/block host/existence/placement/native owner and reported last exit. Missing terminal/transport is not proof of process death. Registry schema1 stores `next_generation` and entries, max32/262144bytes, one latest action not an audit log; no screen/output/argv/env, but target/owner/purpose/reason are private. Nonblocking flock is cooperative, not distributed or an authorization lock. [Full schema and source commands](../../items/jobs/README.md).

Read the actual current `GENERATION` from the latest result. Explicit separately authorized handoff:

```sh
"$TEEREX" jobs adopt --registry "$REGISTRY" \
  --socket "$SOCKET" --session "$SESSION" --block "$BLOCK" \
  --from-owner operator --owner successor --generation "$GENERATION" \
  --reason 'explicitly agreed handoff' --deadline-unix-ms "$NEW_REVIEW_DEADLINE_MS"
```

Adoption changes recorded responsibility only, requires exact identity/previous owner/generation/different new owner, refuses native ownership and never calls take. Generation rises per registry and never recycles on forget/re-register. It does not transfer offstage's original cleanup or a process handle. Deadlines are **advisory review dates**, not timers/enforced shutdown; owner must arrange the review and separately verify effects.

Presentation has a distinct visible-layout effect and requires its own consent and explicit same-session anchor:

```sh
"$TEEREX" jobs present --registry "$REGISTRY" \
  --socket "$SOCKET" --session "$SESSION" --block "$BLOCK" \
  --owner successor --generation "$GENERATION" --reason 'inspect this result now' \
  --anchor "$ANCHOR_BLOCK" --focus no --label 'review requested'
```

Use the latest generation **after adoption**, not the one used to adopt. Detached **commands** attach after the anchor in a horizontal50/50 split; anchor area changes deliberately. Already placed targets stay in their window and require same-window anchor. Hidden agents/native owners/zoomed anchor refuse. `--focus no` verifies returned focus identities, not a physical screen or exclusive control; it does not fight other clients to restore focus. Optional label/focus are separately verified; no pane is automatically closed/rearranged as rollback. Agents must remain visibly placed; `spawn` remains launcher, `offstage` not an agent path.

**Verify/recover:** inspect full result and exact server view/postconditions, latest owner/generation and saved action. Intent is persisted `uncertain` **before** dispatch; lost ACK/crash/deadline may leave partial/full changes. Never retry, roll back layouts, close or adopt automatically. Re-read registry and inspect only the exact authorized resource first. Default budget5000ms,100–60000;0 verified evidence,1 refused/error/uncertain,2 usage,124 deadline,130/143 signals. File-sync/output errors can occur after a mutation.

**Update / rollback / remove:** binary changes never stop jobs or delete/migrate registry. Preserve schema compatibility and private state; alpha.3 cannot read this registry. To remove only a deliberately reviewed record, set `OWNER`/`GENERATION` to actual current values:

```sh
"$TEEREX" jobs forget --registry "$REGISTRY" \
  --socket "$SOCKET" --session "$SESSION" --block "$BLOCK" \
  --owner "$OWNER" --generation "$GENERATION" --reason 'explicit record-only removal'
```

Forget is offline/local, not cleanup or undo. Keep registered responsibility until authorized work/resource cleanup is dealt with; removing the record proves nothing stopped. Registry crash file `state.next` is never promoted automatically and blocks saves; preserve it privately and reconcile exact resources while no operation is active. Committed state is authoritative. Do not delete stable lock files under a running process or recursively remove unreviewed state. No isolation/descendant-proof cleanup, hard deadline, API10–12 or personal-machine certification.

## 3. Selected read-only adapters, local policy and receipts

- **Who:** an operator allowed to discover the chosen server and read the exact allowlisted target; caller-supplied policy is not proof of human consent.
- **What:** `adapters generate/call`, five fixed descriptor-derived tool definitions with mandatory identity revalidation and one local action receipt; no arbitrary generated client or mutation.
- **When:** expose a narrowly selected read interface to an agent and distinguish policy denial, drift, error and result; not a host permission/audit authority.
- **Where:** Mac/Linux, independent CLI/server integer API10–13 with overlapping support. Actual Mac API10/12/13 and Linux13 tests; API11 numeric-only. Runtime requires trusted separate Rex and an existing explicit socket.
- **Why:** stop on descriptor/build/endpoint drift and record what a local invocation actually checked without copying vendor schemas or claiming host enforcement.
- **How:** first check `"$TEEREX" adapters --help`, then after discovery/storage consent:

```sh
"$TEEREX" adapters generate --socket "$SOCKET" --timeout-ms 5000 > "$CHECK_DIR/adapter.json"
```

Require exit0 and complete schema1 `kind=rex_read_adapter` with exact endpoint, independent `cli`/`source`, five raw descriptor hashes, identity, `behavior_certified=false`. It generates **no policy**. Tools are only `rex_version`→server.version, `rex_capture`→terminal.format, `rex_process`, `rex_directory`, `rex_status`→their selected terminal reads. Version args `{}`; terminal args exact full `session_id`/`block_id`, capture also integer `max_bytes`256–65536. Capture is a fixed text prefix, not latest viewport; raw metadata may contain more private fields than observe's curated packet.

Create private files manually from reviewed expectations: policy schema1/kind `rex_adapter_local_policy`, exact generated `adapter_identity`, and `allow` entries with a tool plus exact terminal IDs (no IDs for version). No wildcard/default allow. Minimal version-only policy shape (replace the identity with the successful generated64-hex value, not this literal placeholder):

```json
{"schema_version":1,"kind":"rex_adapter_local_policy","adapter_identity":"REPLACE_WITH_GENERATED_64_HEX_IDENTITY","allow":[{"tool":"rex_version"}]}
```

Put `{}` in the private `ARGUMENTS` file for that version-only call. The complete target-specific policy/argument examples are in [the adapter source contract](../../items/adapters/README.md). Check each selected file's purpose, permissions and contents before use:

```sh
"$TEEREX" adapters call --socket "$SOCKET" --adapter "$CHECK_DIR/adapter.json" \
  --policy "$POLICY" --tool rex_version --arguments "$ARGUMENTS" --timeout-ms 5000
```

Expected exit0 / `kind=rex_adapter_action_receipt`, local allowed decision and actual returned object. Validate exact tool/target, saved/current identity, actual current CLI/source, policy/argument hashes and result/error. Empty allow denies with exit3 before **any** Rex invocation; drift exits4 before selected action and must not be papered over by editing identity. Generation failure1 emits `rex_adapter_generation_failure`; usage/invalid files/args2 may have no receipt; timeout124/signals130/143 are not a read success. Generation rediscovery is serial and non-atomic; selected-action dispatch marker is not server ACK or application consumption.

**Bounds / privacy:** default5000ms,100–60000 plus bounded client cleanup; response/bundle/policy≤128KiB, arguments≤4096. No automatic files/history/retention/export; stdout may hold raw capture/metadata/paths/status. Receipt is `unauthenticated_local_assertion_no_history`, `host_enforcement=false`, `consent_verified=false`, freshness unknown, `atomic_snapshot=false`. Same-version restarts may be indistinguishable; policy edits/bypass defeat the local convention. No input lease, mutation tool, auth/sandbox/credential broker or revocation.

**Update / rollback / remove / troubleshoot:** on drift/unsupported shape preserve old files, review the new descriptor/build and rerun relevant authorized behavior checks before deliberately generating a new bundle **and reviewing a matching policy**. Never automatically grant new tools or regenerate allowlists to clear denial. Software rollback does not undo reads/exports or authenticate old receipts; old alpha.3 has no adapter command. Stop invoking/remove only chosen private bundles/policies/arguments/receipts and executable; no service/config cleanup. No raw vendor descriptor publication or personal M5/hive certification.

## 4. Explicit bounded historical cache

- **Who:** an operator explicitly consenting to store sensitive observation content for **each write**; an agent's convenience is not consent.
- **What:** `filter cache put/get/purge`, one latest plaintext typed observation per explicit private root, bounded replacement/TTL/domain validation and historical comparison.
- **When:** deliberate historical reuse/storage; ordinary `filter --sample` remains storage-free. A hit never replaces a live authorized acquisition.
- **Where:** offline Mac/Linux, schema1/API10–13 files. Absolute root in trusted existing parents, exactly0700/effective-user-owned; regular single-link files0600, no final symlinks/FIFOs/devices. No implicit root or global cache.
- **Why:** retain useful historical evidence without silently calling it current, fresh, complete or authorized.
- **How:** after exact root/retention/storage consent, `CACHE_DIR` names a new final directory (parents must exist), `SAMPLE` is a successful saved observation, `EXPECTATION` is a separately selected validated packet. First check `"$TEEREX" filter cache --help`:

```sh
"$TEEREX" filter cache put --directory "$CACHE_DIR" --sample "$SAMPLE" \
  --allow-sensitive-storage --ttl-seconds 60
"$TEEREX" filter cache get --directory "$CACHE_DIR" --expect "$EXPECTATION"
# Only after deliberate deletion consent for this exact cache:
"$TEEREX" filter cache purge --directory "$CACHE_DIR"
```

Put validates input before creating only the last directory; consent flag is required every time. It writes `observation.json`, transient `.observation.pending`, stable empty `.lock`, no history. Each sample/expectation/envelope≤1MiB, at most2MiB captured payload during replacement/recovery plus lock, no global quota. Typed re-encoding is not original-byte archival; keep input files outside reserved filenames. Nonblocking flock fails busy rather than stealing locks. Exclusive pending0600, file sync/rename/directory sync bound replacement. A post-commit error may still mean storage happened; inspect, do not assume no effect.

Expected schema1/`kind=rex_observation_cache_result`, `interpretation=none`: put0/`stored`; get0/`historical_hit`, **`evidence_freshness=historical_unverified`, `permission=none`**, original observation/time data and full `comparison_to_expectation`. Ordinary capture/process/status differences do not invalidate identity; returned cached evidence stays old. Get requires exact server/session/block/source version/platform/API and capture budget equal to expectation. Domain mismatch unlinks entry and exits3/`invalidated` without payload; miss3 has no observation. Unsupported/corrupt/unsafe/busy/I/O is1, usage2. Require exit and full JSON; stderr-only errors are possible. A stale expectation cannot prove current state.

**TTL / crash / troubleshooting:** default60s, integer1–3600 from **storage wall time**, not observation age. Replacing even an old sample resets storage TTL; get never slides it. At expiry or a read clock earlier than stored_at, access unlinks entry/returns invalidated. **Expiry occurs on access only**: plaintext can remain indefinitely without access/purge. Other wall-clock shifts can distort retention. Crashes release OS lock but may leave pending plaintext; next successful access removes pending under lock. Malformed committed cache fails, not hit; explicitly purge it before writing again. Unsafe modes/links can block purge too: inspect/recover manually, never silently fix unknown files. Trusted parents/ACL/backups/same-account/root access are outside protection. No encryption/redaction/secure erasure.

**Update / rollback / remove:** upgrading CLI does not purge/migrate caches or make hits current. Before returning to alpha.3 (which cannot purge), use a cache-capable binary to purge **each exact selected root if data removal is intended**. Purge0/`purged` or `absent` is idempotent, nonrecursive, removes only reserved entry/pending without parsing payload and retains directory/lock/unrelated files. Missing root is absent and is not created. Once no cache invocation uses it, remove only the known empty lock then `rmdir` the empty directory if desired. Purge is deletion, not undo; `secure_erasure=false`, backups/snapshots/open descriptors/copies remain possible. [Complete cache source contract](../../items/filter/README.md).

## 5. Manual maneuver library and saved endpoint relations

- **Who:** an authorized reader of a deliberately curated manual library and selected saved observation files, not an input controller.
- **What:** the existing `maneuver-check` gains library validation/catalog, multi-definition recognition and optional caller-ordered saved-endpoint relation checks. Alpha.3 [single-definition mode](features.md#10-maneuver-check-saved-recognizable-start) stays unchanged.
- **When:** inspect exact recognizable states or declared relations between independently saved endpoints; never learn, execute or replay a gesture.
- **Where:** offline Mac/Linux; schema1/API13 definitions/observations, exact target/source version/platform, complete screen-and-scrollback and foreground name/cwd evidence. No Rex connection or current-target existence check.
- **Why:** preserve mismatch, unknown and ambiguity instead of choosing the first matching definition or pretending two endpoint files prove a transition.
- **How:** check actual `"$TEEREX" maneuver-check --help`. `LIBRARY` is one reviewed private JSON file, with the complete schema/example in [the maneuver source contract](../../items/maneuvers/README.md#bounded-definition-libraries-and-saved-endpoints):

```json
{
  "schema_version": 1,
  "kind": "rex_maneuver_library",
  "id": "synthetic-inspect-only",
  "definitions": [{
    "schema_version": 1,
    "kind": "rex_maneuver_start",
    "id": "synthetic-ready",
    "provenance": {"kind": "manual", "note": "Synthetic example, not learned success"},
    "compatibility": {"rex_version": "0.1.0-preview.16", "platform": "darwin_arm64", "api_revision": 13},
    "starting_state": {"capture_content": "Synthetic ready\n", "foreground": {"name": "fixture", "cwd": "/fixture"}},
    "stop_before": "No action is authorized."
  }],
  "transitions": []
}
```

This is a **valid synthetic-only catalog example**, not a detected real workflow. Replace expectations only from independent review, not terminal instructions. Embed1–16 [complete manual definitions](../../items/maneuvers/README.md#use), including manual provenance/stop text/exact source/capture/foreground. Library≤1MiB, relations0–64 `{from,to}` entries naming existing different definitions with identical source compatibility. Duplicate IDs/edges, self/cross-compatibility edges, unknown/action fields fail. No file includes/scanner/default library. Standalone definition remains≤128KiB; each selected observation≤1MiB. All definitions/relations and unused packet provenance/status duplicates are validated, not just the matching case.

```sh
# Validate/catalog only, with no observation or target arguments:
"$TEEREX" maneuver-check --library "$LIBRARY" --list
# Recognize one saved observation:
"$TEEREX" maneuver-check --library "$LIBRARY" --observation "$OBSERVATION" \
  --socket "$SOCKET" --session "$SESSION" --block "$BLOCK"
# Compare directed caller-ordered saved endpoints, not a replay:
"$TEEREX" maneuver-check --library "$LIBRARY" --before "$BEFORE_OBSERVATION" \
  --observation "$OBSERVATION" --socket "$SOCKET" --session "$SESSION" --block "$BLOCK"
```

**Expected outputs / verify:** require full JSON and status. Catalog0/`kind=maneuver_library_catalog` means validation only, not recognition. Recognition `maneuver_library_check`:0/`matched_evidence` requires exactly one match and no unresolved candidate;3/`mismatch` all definitions known mismatch;4/`unknown` has an unresolved candidate;5/`ambiguous` multiple known matches. Inspect every definition's checks and selected ID; never rank or pick first. Partial capture/missing foreground/cwd remain unknown; per-definition known mismatch wins only within that definition.

Pair `maneuver_transition_check`:0/`declared_edge_evidence` means uniquely recognized endpoints and a declared directed edge, **not that the transition happened**.3 means known mismatched endpoint/undeclared relation,4 unresolved or reused observation ID on an otherwise declared edge,5 ambiguity. Known endpoint mismatch takes precedence over ambiguity/unknown; ambiguity over unknown. Swapping input files reverses the checked edge. `sample_order=caller_supplied`, process continuity not verified, intermediate states not observed. Backward clocks, changed PIDs, saved IDs, file hashes and matching text prove neither chronology nor freshness/authenticity/application identity. Invalid/missing/incompatible packet/target/API is1 without a result; usage2. `--definition`/`--library` mutually exclude; `--list` accepts no observation/target, `--before` only library recognition.

**Privacy / limitations:** output omits raw capture/cwd/report values, but IDs/source/target/manual notes/stops/diagnostics can still be private. Set `umask 077` before deliberate capture/library writes; hashing/escaping is not redaction. Boundaries keep `input_sent=false`, `approval_granted=false`, `freshness=unknown`, no execution path and authored text unauthenticated. Definitions, stop text and relations are **data**, not consumer instructions or a host-enforced safety policy. No learning, recorded-byte replay, live input sequence, application-version reliability or completion of all Phase3#6.

**Update / rollback / remove / troubleshoot:** review new source/binary and rerun offline tests/library `--list` before deliberate use. New library mode is unavailable after rollback to alpha.3, but old single-definition files retain their established schema; retain source data rather than silently migrating/widening source identities. Stop invoking/remove only your own build and selected private library/observation files when approved; no registry, service, config or implicit retention to uninstall. On mismatch inspect exact expectations/source/full-capture boundaries; on unknown retain unknown; on ambiguity clarify definitions explicitly, not by ordering them. Malformed/partial output is failure, not unknown recognition. Strong guarded input/revocation remain blockers to replay; an old saved file can continue matching an old state after the real program changes.
