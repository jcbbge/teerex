# Select and verify teerex

On hive, use the
[rexconfig build and install procedure](https://github.com/jcbbge/rexconfig#readme).
It owns the build pin, verified managed installation and live checks.

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
```

Run the focused live check for the operation being changed. Installation leaves Rex running.

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
