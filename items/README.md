# Independent cartridges

**Two experimental items exist: [observe/compare/watch](observe/README.md) and [run](run/README.md).** They currently share a development executable, not independent install/removal packaging. No item is marked ready; this directory does not define a Rex plugin API or a functioning package manager.

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

The first item addresses Phase 3 #1's bounded, target-attributed observation, with Phase 3 #8 limited to the method bindings it needs. It does not assume that a Rivet API, native graphical plugin SDK, or VPS deployment exists. Joshua approved small build-and-validate increments after accepting the phase review as definitive history. The initial preference remains a minimal Zig CLI on his M5 MacBook, not targeted VPS/Linux support or a finalized system-wide design; see the [current increment](../docs/direction.md#incremental-build-approval-and-first-slice).

Its `watch` command adds C09's read-only `observe_until_changed` and selected status-report predicate without inventing another cartridge: a caller-selected baseline/target, bounded foreground polling, separate value/availability/unknown evidence and deadline/cancellation/error outcomes. It shares tested process-group supervision with `run`, not terminal-input authority or a background service. One persistent Rex/Lua connection performs the same five non-atomic reads per sample. A retained matching status report does not satisfy the predicate unless its evidence differs from the original baseline; a match never proves completion or freshness. The [observation contract](observe/README.md#acquisition-sustained-polling-and-status-evidence--12-november-2026) records measured acquisition/CPU gains and limitations, including the concrete finding that native Rex ownership is not an input lease.

The next item addresses Phase 3 #3's selected run-and-collect slice through Rex's local Lua subprocess interface: explicit argv/cwd, bounded captured bytes, real exit/timeout evidence and scoped cancellation/cleanup. It does not grant authority to type into an existing terminal, run on the selected server, or kill arbitrary jobs. The [run contract](run/README.md) records actual child-lifetime findings and limits rather than claiming a sandbox or whole-process-tree guarantee. Non-Rex ownership groups remain preserved and unassigned.
