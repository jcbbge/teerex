# Select and verify teerex

For hive and the M5, use the single
[rexconfig build and install procedure](https://github.com/jcbbge/rexconfig#readme).
It owns the build pin, cross-compilation, verified managed installation and live
checks. Read it before changing either machine. A manually copied binary is not
a complete managed release.

For the general installer contract, archive checks, retained-version rollback and
removal, see [install.md](../install.md). For named-host deployment receipts, see
[fleet-install.md](../fleet-install.md). Select an exact build and verify its
archive and installed inventory; preserve the currently active build when
validation fails. Historical release pages describe their frozen bytes, not the
current source interface.

After installation, inspect the selected executable:

```sh
teerex --version
teerex --help
teerex doctor --all
```

`doctor --all` checks configured builds, Rex connectivity, guarded surface
resolution, rexconfig drift and harness-hook presence. It reports what it checked;
it does not certify every utility workflow. Run the focused live check for the
operation being changed. Installation does not restart Rex.

## Read a pane

Use the selected named host and exact pane identity from the authorized task:

```sh
teerex --config /absolute/hosts.json --host NAME observe --session SESSION --block BLOCK --tail
```

Read the complete receipt, including source identity, completeness and unknowns.
An observation is evidence about the pane, not proof that its work succeeded.
Use [the feature contracts](features.md) and each command’s help for the next
operation.

## Earlier installation instructions

The [release archive](../releases/) preserves version-specific hashes, support
matrices and receipts. Those records do not select a build for a new installation.
