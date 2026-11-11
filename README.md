# teerex

Joshua Gantt's personal, opinionated collection of Rex extensions, utilities, scripts, and helpers.

**Today this is an organized research collection, not an installable distribution.** There are no shipped extensions, installers, or working Rex–Rivet integrations. The intended destination is a shared console with isolated **cartridges** that humans and agents can add or remove independently, one or all at a time. The first step is understanding the Rex version Joshua actually has.

## Start here

1. [Level one: meet your installed Rex](docs/learning/level-1.md) — a small, read-only walkthrough. No config edits, runner access, VPS changes, or installs.
2. [Research index](research/README.md) — the three completed investigations and their evidence boundaries.
3. [Cartridge organization](items/README.md) — how each future item stays independent.
4. [All-items collection](collections/all.md) — the planned opt-in way to install every ready item, **not available yet**.
5. [Product direction and transcript planning](docs/direction.md) — accepted goals, source selection, review status, and unresolved decisions.
6. [PDF-only work inventory](docs/planning/teerex-pdf-work-inventory.md) — the original three suggestion phases, 23 scored proposal groups, Rex/non-Rex boundaries, and 62 retained subrequirement/recap entries; **not approved features or started implementation**.
7. [Non-Rex handoff](docs/planning/teerex-non-rex-handoff.md) — eight optional ownership groups for general-purpose work, separated from Rex adapters; no new assignments.

## What is preserved

| Location | Content |
| --- | --- |
| `research/lua.md` | Lua runtime, configuration/actions, scripts, events, subprocesses, remote execution, and limits. |
| `research/libghostty.md` | Terminal-engine boundary, Rex extension hooks, OSC 7501, and missing native-view contracts. |
| `research/source-api.md` | Official sources, custom-client protocol, captured API version, source availability, and unresolved contracts. |
| `research/api/catalog.json` | 524 indexed names/topics and provenance locations, without copied descriptions or full schemas. |
| `research/provenance/` | Original acquisition manifest and capture checksums; explains what is and is not included. |
| `docs/learning/` | Small learning steps, beginning with the installed version and available API. |
| `docs/direction.md` | Cartridge/console direction, PDF-only review status, and the transcript-to-workstream planning process. |
| `docs/planning/` | Phase-based PDF review, non-Rex handoff, and extractor's validation record; no raw transcripts or private manifest. |
| `items/` | Future self-contained cartridges; currently only the organization contract. |
| `collections/` | Future opt-in groups of items; currently the all-items policy. |

The research was checked on **11 November 2026**. Source/API discovery exercised Linux **0.1.0-preview.15**, API revision **13**. That is not a claim about Joshua's installed version. Official website documentation is a separate rolling snapshot, not a checkout of Rex application source.

The original searchable explorer and full capture are recorded in [provenance](research/provenance/README.md). Full vendor documentation, packaging, schemas, and binary data are **not republished here** without established redistribution terms. This repository is neither Rex source nor an official Superlogical distribution.

## Direction, not delivered features

Joshua's initial preference is a **simple, barebones, minimal Zig CLI on his M5 MacBook**, where he already has Rex downloaded as his VPS client. This is not a finalized design or a request to implement it yet. Targeted VPS/Linux support is outside initial scope; adding a Rex server on the VPS may be considered later.

Agents are first-class users of the API/work surface alongside humans. Developer experience, lovable human UI/UX, efficient resource use, and speed are product priorities; they do not require a graphical console as the first deliverable. Joshua intends to run a future installer on his M5 and load completed cartridges; no installer or M5 compatibility has been implemented or verified. Other decisions will be discussed collaboratively as they arise, not as an upfront questionnaire. See the [direction record](docs/direction.md).

The first candidate workflow is Rex as the terminal workspace/client for Rivet, using a real Rivet interface if one is established. A Lua action, terminal dashboard, or structured status adapter is a possibility to evaluate incrementally — not an implemented item. A status signal is never approval or permission. The preserved Linux/VPS research is historical context, not an initial platform-support commitment.

No project license has been selected. See [rights and attribution](RIGHTS.md); a future teerex license must not claim third-party material.
