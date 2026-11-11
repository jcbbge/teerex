# All items

**Planned; unavailable. There are currently zero members and no installer.**

The eventual `all` option will select every cartridge marked `ready` in this release. It will compose the same per-cartridge installation paths used for individual installation; it must not be a separate monolithic copy of their code. Selecting all must preserve the ability to add or remove each cartridge independently through the human and agent-facing work surface.

Before implementing it:

- Keep every item individually selectable and independently uninstallable.
- Exclude proposals and experiments by default. Research documents are not installable members.
- Show the exact selected items, versions, dependencies, destinations, and required permissions before changes.
- Detect incompatible items or conflicting files rather than silently overwriting them. Report partial failure and how to undo completed changes.
- Make installation repeatable; installing one item and then all must not duplicate its hooks or bindings.
- Treat a release's all-items membership as explicit and reviewable. Adding a new ready item changes what a later all-items install selects; it must not silently update an existing installation.
- Leave credentials, server choice, host configuration, and remote deployment explicit. Selecting `all` is not consent to modify a VPS.

The starting preference is a minimal local Zig CLI on Joshua's M5 MacBook, not targeted VPS/Linux support. Work through shared-dependency handling, removal/data behavior, and agent permissions collaboratively as those choices arise; this policy neither settles them nor requires an upfront questionnaire. See the [product direction](../docs/direction.md).

Do not offer a command such as `install --all` until that command, the individual items, and these behaviors are implemented and tested. This file preserves the intended delivery model without claiming it works today.
