# Independent cartridges

**No installable items exist yet.** This directory defines the intended boundary, not a plugin API or a functioning package manager.

Each future helper is a **cartridge** in the shared console, with its own `items/<item-id>/` directory. A cartridge can be a Lua script, configuration action, terminal program, or another supported extension. Do not create empty item directories just to make the catalogue look populated.

A cartridge must be independently addable and removable at any time, without requiring installation of the all-items collection. Humans and agents are first-class users through the supported API/work surface. This is a product requirement, not a claim of hot-loading support in Rex or of an implemented lifecycle API. Shared-dependency ownership, in-use removal, retained data, and agent permissions remain undecided; see the [direction record](../docs/direction.md).

## What a real item must provide

Keep this in the item's README and implementation, without introducing a manifest format until an installer actually needs one:

- A stable item ID, purpose, lifecycle status, and exact supported Rex/runtime/OS versions. Use `proposed`, `experimental`, or `ready` honestly.
- Its own source/configuration and provenance/license/dependency information. Do not bundle Rex itself without permission.
- Individual install, invocation, verification, upgrade, and uninstall instructions. Explain destination paths, required permissions, and every persistent change.
- No silent replacement of `init.lua`, key bindings, server configuration, or another item's files. Back up and explain any intentional integration.
- Observable verification on the claimed Rex version and environment. A copied example or schema match is not an end-to-end test.
- Explicit treatment of secrets, remote hosts, process lifetime, and user approval for consequential controls.
- A usable human workflow and documented agent-facing contract. Work through permissions and lifecycle behavior collaboratively when the relevant operation needs them; do not require an upfront system-wide questionnaire or equate first-class agent use with unrestricted authority.

Only a tested, independently installable item can be marked `ready` and enter the [all-items collection](../collections/all.md). Record compatibility conflicts and exclusions rather than treating bulk installation as permission to overwrite files.

The first item should solve one small need established after [level one](../docs/learning/level-1.md), not assume that a Rivet API, native graphical plugin SDK, or VPS deployment already exists. The initial preference is a minimal Zig CLI on Joshua's M5 MacBook, not targeted VPS/Linux support; this is planning, not a finalized design or an implementation request.
