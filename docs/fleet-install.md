# Fleet install — explicit named machines, retained manual installs

Capability 10 is a foreground, opt-in core installer orchestrator. Its source entry is `python3 tools/fleet-install/fleet_install.py`; the alpha.5 console bridge is `teerex fleet install|rollback`. It imports the shared `src/targets.py` resolver rather than discovering machines, interpreting Rex host labels as SSH aliases, or keeping a second host registry. `m5`, `hive`, and `m1` are examples of operator-configured names, not built-in endpoints.

**Shipped in current alpha.5.** Use [current inspect-first setup](concierge/setup.md) and the [alpha.5 release guide](releases/v0.1.0-alpha.5.md) before selecting published bytes. The alpha.5 native executable embeds the controller, worker, resolver and installer support sources, so its fleet bridge works outside the source checkout; it still requires Python3.9+ and installer tools. The separate source-script entry requires those full source files (including `src/targets.py`); the onboarding archive is not a complete developer checkout. An older executable cannot bootstrap a subcommand it lacks: first install verified alpha.5 using current setup, or use reviewed full source. Three-file archives contain no separate Python source files; newer docs do not rebuild their frozen README.

## Who, what, when, where, why, how

- **Who:** a human or agent with explicit authorization to change each selected account. `--apply` is a mutation request, not a permission service or a human-approval mechanism. Building or testing this command does not authorize touching Joshua's personal m5/hive/m1.
- **What:** inspect every named machine, select one exact teerex release, verify platform assets/checksums, install or upgrade the managed core, optionally publish a consented PATH launcher, and verify both fixed-version bytes and `teerex VERSION` output. Independently packaged cartridges remain separate; no implicit `--all` or cartridge installation occurs.
- **When:** run deliberately for an install/upgrade or retained-version rollback. Nothing checks for updates or retries in the background. Stop foreground teerex invocations before switching versions; this is not process supervision, an in-use lease, or running-agent migration.
- **Where:** a new user-owned `HOME/.local/opt/teerex-managed` on each target, unless `install.prefix` explicitly selects another canonical root strictly inside that target's HOME. The configured `teerex` path is the optional launcher destination. No sudo or global install runs on targets.
- **Why:** one reviewed operation and one per-host receipt instead of hand-copying binaries, refusing to reuse an unknown manual folder rather than deleting/adopting it.
- **How:** shared explicit host selection → all-host read-only preflight → bounded platform asset/checksum acquisition → sequential one-shot target workers → core installer validation/atomic activation → fixed-path integrity and version check → optional launcher and transport-PATH verification. The worker exits after its JSON receipt; no daemon, agent or Rex pane is launched.

## Shared configuration and identity

Use the same absolute `--config` path and names as other named-target commands. A Linux SSH example in that configuration's `hosts` object is:

```json
{
  "hive": {
    "host_id": "hive",
    "transport": "ssh",
    "address": "operator@example.invalid",
    "port": 22,
    "identity_file": "/absolute/controller/key",
    "known_hosts": "/absolute/controller/reviewed_known_hosts",
    "home": "/home/operator",
    "platform": "linux-x86_64",
    "socket": "/run/user/1000/rex/server.sock",
    "rex": "/absolute/target/rex",
    "teerex": "/home/operator/.local/bin/teerex",
    "store": "/home/operator/.local/state/teerex",
    "install": {
      "prefix": "/home/operator/.local/opt/teerex-managed",
      "bin_dir": "/home/operator/.local/bin",
      "expected_hostname": "reviewed-hostname",
      "expected_user": "operator"
    }
  }
}
```

The enclosing file has `schema_version: 1` and `hosts`. Other platforms use `macos-arm64`; mapping to `aarch64-macos`/`x86_64-linux` archive names occurs only at the installer boundary. Local hosts use `transport: "local"` and omit SSH fields. A local record means this executing machine, not a fallback if SSH fails.

The optional `install` fields are installation-only additions, not another host registry. `prefix` defaults as above; `bin_dir`, if supplied, must match the configured `teerex` parent. `expected_hostname` and `expected_user` bind additional observed facts. HOME and platform must match on every invocation; SSH also checks the observed user against the explicit `user@hostname/IP` destination. Fleet deliberately requires an explicit SSH user and literal hostname/IP, not an alias depending on user SSH configuration. It ignores SSH config, disables forwarding/multiplexing/local commands, and uses batch authentication with only the configured identity and strict pre-existing known-host entries. Enroll/review host keys separately; it never accepts a new/changed key or captures credentials.

Configured `host_id` is a declaration, **not an independently measured machine identity**. Receipts say so and record observed hostname/user/HOME/platform separately. SSH authenticates the selected endpoint against the operator's trusted file; it cannot prove the human's nickname matches the intended physical machine. Configured socket/rex/store are shared target data but are not contacted, installed or modified by fleet installation.

## Plans, apply, and PATH consent

Current reviewed public tag is `v0.1.0-alpha.5`. Replace `TAG` below with that exact tag after setup verification, not a branch or release resolver; there is no `latest`.

```sh
# Read-only per-host plans; no download, binary execution, root or launcher creation.
teerex fleet install --config /absolute/targets.json \
  --host m5 --host hive --host m1 --version TAG --path

# One explicit command installs/upgrades and verifies every selected host.
teerex fleet install --config /absolute/targets.json \
  --host m5 --host hive --host m1 --version TAG --path --apply
```

For first deployment replace `teerex fleet` with `python3 tools/fleet-install/fleet_install.py`. Repeat `--host` for every intended machine; there is no implicit "all configured" target. Plans disclose observed/declared identity, previous active/installed versions, integrity receipts for existing selections, planned action, archive, executable, launcher identity/action, backup destination when applicable, and undo information. Plans never execute an existing manual launcher. `--apply` makes a fresh all-host plan; each worker rechecks it before mutation and refuses a stale plan. Save stdout privately for audit if wanted; no automatic history files are created. Plans/results include paths and account/host identities.

`--path` is separate consent to create a symlink at configured `teerex`, and requires that path be named `teerex` inside HOME and its canonical directory already be on the **worker transport environment's PATH**. The command verifies `which teerex` selects that exact launcher and checks its version. Without `--path`, only the fixed installed executable is verified; no PATH claim or launcher creation follows. If the directory is absent from PATH or an earlier executable shadows it, the command refuses or rolls back and says why. It does not edit `.zshrc`, `.zprofile`, `.profile`, shell caches or any configuration. Set PATH through your existing reviewed shell/account workflow, then retry. SSH and interactive shells may have different PATHs: transport-PATH success is not certification of a login shell, every Rex pane or every agent environment. Rehash/reopen those shells and check `command -v teerex; teerex --version` there yourself.

## Existing manual installs: preserve, do not adopt

The default separate `teerex-managed` root intentionally avoids the historical manual `teerex` folder. An unmarked folder at the chosen prefix is refused without deleting, renaming, adopting or writing into it. Select a different `install.prefix`; there is no force-adopt or recursive cleanup option.

A colliding configured launcher is a different, narrowly consented action. Review its file SHA-256/mode or symlink target in the plan, then use both flags if you want replacement:

```sh
teerex fleet install --config /absolute/targets.json \
  --host m5 --host hive --host m1 --version TAG \
  --path --replace-launcher --apply
```

Only that exact owned regular file or symlink is renamed to the plan's sibling `teerex.before-fleet-HASH`; its target/manual tree is not removed. Directories, unowned paths, symlink ancestors, group/world-writable installation ancestors, and pre-existing backup collisions are refused. The receipt retains the exact backup path. Backups are never garbage-collected. The managed launcher then points at the managed `current/teerex` link. To return to manual routing later, inspect that the launcher still points to the receipt's exact managed executable, remove **that symlink only**, and rename the recorded backup back to the configured launcher. Do not remove a newly changed user file or any manual folder. Restoring the old launcher does not remove managed releases.

## Validation, rollback, and partial failure

All hosts must pass preflight before any install is attempted. The controller acquires at most 64 MiB per asset and 1 MiB of checksums, checks exactly one matching SHA-256 entry, then transfers only the chosen platform archive and sums to a short-lived private target directory. `--from /absolute/reviewed-assets` uses local controller files without weakening checks. Different platforms' archives and one common `SHA256SUMS` may coexist there.

The unchanged core lifecycle owns its three-regular-file archive contract, checksum, native-format/architecture check, help check, immutable tags and atomic `current` link switch. Fleet does not extract arbitrary archive content or infer integrity from a version string. It calls read-only core `verify` on the fixed selected version path before executing `--version`, verifies integrity again, then checks the active tag. Hashes supplied alongside assets detect byte changes, not authentic publisher identity or malicious code from a trusted source. No quarantine removal, Gatekeeper bypass, signing claim, OS upgrade or Rex restart is performed.

On install/verification/launcher failure, a connected worker attempts to restore its previous active managed tag and undo only its own launcher change. A failed first activation is explicitly deactivated and removed only through the core's verified known-file removal path. A failed upgrade can retain the newly installed inactive release. Old versions, manual folders, user data, profiles and Rex configuration remain. Rollback failure is a separate receipt with the error and any retained backup: it is never disguised as success.

Hosts are applied sequentially in the requested order. The first apply failure stops later hosts; earlier verified successes remain selected. This is **not a fleet-wide transaction**. A dropped SSH connection/timeout produces `outcome: unknown`, never an assumption that the operation did not run, a retry or an automatic remote rollback. Inspect that machine before another apply. SIGKILL/power loss may leave core staging directories or `.teerex-fleet-install.lock`; inspect running processes and recorded paths before deliberately cleaning stale state. No journal/crash recovery is promised. Core and fleet locks are separate point-in-time coordination, not protection against another process with the same account's write authority.

Retained releases that implement the version contract can be selected explicitly:

```sh
teerex fleet rollback --config /absolute/targets.json \
  --host m5 --host hive --host m1 --version RETAINED_TAG --path --apply
```

The same path/integrity/version checks apply; no download occurs. Older releases without `--version` cannot satisfy fleet's version proof. Use the reviewed core `rollback --prefix ... --version ...` for such a legacy release, verify its fixed bytes via core `verify`, and do not call that a self-reported version check. No semver ordering or silent fallback chooses a release.

Output is schema-1 JSON; success exits 0, refusal/partial failure exits 1, argparse usage exits 2. Each host retains its plan and result (`verified_installation`, `verified_version`, optional launcher backup, or exact error/rollback/unknown/skipped outcome). `applied` means at least one apply was attempted, not that every host changed or succeeded. All same-version hosts are integrity/version-verified without downloading or overwriting the tag. Rerun only after assessing any unknown result; no hidden retry occurs.

## Prerequisites and evidence boundaries

Both controller and targets explicitly require Python **3.9+**. The controller also needs OpenSSH for SSH targets; each target needs the [core installer's stock Bash/tools](install.md), a canonical owned HOME and Darwin arm64 or Linux x86_64. No Python, key, trust file, package, service or missing dependency is silently installed. Receipts prove selected bytes/version and bounded PATH scope, not live Rex/API compatibility, minimum OS/kernel support, running-process replacement or personal-machine acceptance.

```sh
python3 tools/fleet-install/test_fleet_install.py -v
python3 tools/install/test_install.py -v
```

Fleet tests use disposable HOME roots and real native help/version fixtures, not a relabelled teerex release. They cover plans, lifecycle/repeat/retained rollback, checksum/archive/architecture/integrity refusals, manual launcher/file retention, exact hostname/platform/user and PATH boundaries, stale plans, busy roots, version mismatch recovery, three controlled named transports, all-host preflight and unknown/skip partial failure. The controlled SSH executable checks invocation policy but is not real SSH authentication evidence.

Optional **disposable-machine-only** real transport acceptance requires an already installed `/usr/sbin/sshd`, working SSH runtime directories, a native C compiler and passwordless test sudo. Unlike the installer, this test deliberately starts a temporary privileged loopback-only sshd with freshly generated keys, then stops it and discards the keys. It does not enable the machine's normal SSH service or edit its SSH configuration:

```sh
python3 tools/fleet-install/test_ssh.py
```

`test_ssh.loopback_ssh()` is also a context-manager fixture for other disposable named-host acceptance: it yields `(ssh_fields, trusted_public_host_line, wrong_public_host_line)`. `ssh_fields` contains the shared `transport/address/port/identity_file/known_hosts` fields; the caller supplies its own explicit home/platform/teerex/socket/rex/store. Trust starts pinned. The key files stay inside the fixture lifetime; do not retain them or use this fixture for a personal endpoint.

On 12 November 2026, all **11 fleet tests** passed on Debian 13/Linux x86_64 with Python 3.13.5, Linux with the declared minimum Python **3.9.25**, and disposable macOS **26.3.1/arm64** with Python 3.14.3/system Bash 3.2. The combined core suite passed 20 tests on each native platform, with its opt-in historical public-download control explicitly skipped in these combined runs (the installer owner's separate `--public` evidence is in the core guide). The real loopback OpenSSH test passed on **both Linux and Mac**: pinned-key native install/upgrade/retained rollback, exact SHA/version receipts, known-hosts filename containing spaces, observed hostname refusal, and actual SSH exit255/host-key diagnostics for unknown and changed keys. An initial stale-plan test over-specified an error message despite a correct earlier refusal; the corrected test asserts the unchanged user file and absent managed install. The first Mac SSH harness accidentally selected the inherited `USER=root`; the product refused root, and the corrected harness selects the actual OS-account username. These are disclosed harness corrections, not hidden product-success claims.

Those versioned native fixtures are not final teerex binaries. Alpha.5 now ships the embedded bridge; [released-byte identity and combined acceptance](releases/v0.1.0-alpha.5.md#verification) are recorded separately, not inferred from these fixtures. Same-OS loopback transport is not real m5↔hive mixed-host acceptance. None of this authorizes or claims a personal m5/hive/m1 install.

## agent-core migration

There is no standalone agent-core fleet-install script to delete in the inspected stopgaps: the brief describes manual installation. The migration is to replace operator/agent hand-copy/install recipes with this named-host command **after** final bridge packaging and disposable transport acceptance. Leave `teerex-target`, Rex config, launch profiles, palette entries and messaging stopgaps to their respective capability owners. No deletion of those unrelated files, private profiles or personal setup is part of capability 10.
