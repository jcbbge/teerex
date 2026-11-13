# All items

**Ready-only membership remains zero in current alpha.5.** The [independent cartridge manager](../docs/cartridges.md), first shipped in alpha.4, implements `install --all` through the same individual paths, but every current package is experimental. Explicit `--allow-experimental` admits ten Mac or seven Linux payloads; without it, all selects zero. This does not promote experiments to ready. Use [current setup](../docs/concierge/setup.md) and verify the [alpha.5 release and selected catalog](../docs/releases/v0.1.0-alpha.5.md) first. Surfaces/boards/agents/recovery are in the combined CLI, not members silently added to this catalog.

The implemented `all` option selects every cartridge marked `ready` in the selected catalog unless experiments are explicitly admitted. It composes the same per-cartridge installation paths used for individual installation, not a separate monolithic copy of their code. Selecting all must preserve the ability to add or remove each cartridge independently through the human and agent-facing work surface.

The implemented lifecycle preserves these requirements:

- Keep every item individually selectable and independently uninstallable.
- Exclude proposals and experiments by default. Research documents are not installable members.
- Show the exact selected items, versions, dependencies, destinations, and required permissions before changes.
- Detect incompatible items or conflicting files rather than silently overwriting them. Report partial failure and how to undo completed changes.
- Make installation repeatable; installing one item and then all must not duplicate its hooks or bindings.
- Treat a release's all-items membership as explicit and reviewable. Adding a new ready item changes what a later all-items install selects; it must not silently update an existing installation.
- Leave credentials, server choice, host configuration, and remote deployment explicit. Selecting `all` is not consent to modify a VPS.

The initial preference was a minimal local Zig CLI on Joshua's M5 MacBook; the current brief includes existing Linux/named command hosts, not a new VPS deployment. Shared-dependency and retained-data behavior follow the implemented manager contract; installation is not agent permission or personal-host authorization. See the [product direction](../docs/direction.md).

Alpha.4's manager implements `install --all` with plan-before-apply, native catalog validation and the retention/conflict limits documented above. This is not authorization for personal-machine installation, invocation, a Rex restart or remote deployment.
