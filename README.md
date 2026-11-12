# teerex

Joshua Gantt's personal, opinionated collection of Rex extensions, utilities, scripts, and helpers.

**An experimental Apple-silicon Mac CLI is available as [v0.1.0-alpha.1](https://github.com/jcbbge/teerex/releases/tag/v0.1.0-alpha.1).** The release includes the executable and checksums, not Rex. See [download, verification and use](docs/releases/v0.1.0-alpha.1.md). It was tested on disposable arm64 macOS 27.2 with Rex preview.16/API 13; Joshua's installed Rex version and M5 setup remain unverified. There is no installer, independently packaged cartridge distribution, or ready all-items collection.

[observe/compare/watch](items/observe/README.md) incrementally implements Phase 3 #1 in Zig: bounded terminal text, process/directory/status-report provenance, explicit offline changes and C09's bounded foreground change/status-evidence waits against an explicit baseline, without activity/completion inference. Acquisition uses one supervised Rex/Lua connection; sustained polling reuses it rather than launching clients per sample. [run](items/run/README.md) adds Phase 3 #3's local argv execution, bounded output, real exit/deadline/cancellation evidence and owned-process-group cleanup through supported Rex Lua bindings. It is not terminal input, a sandbox or remote execution. There are no background watchers or working Rex–Rivet integrations. The intended destination is a shared console with isolated **cartridges** that humans and agents can add or remove independently, one or all at a time.

## Start here

1. [Level one: meet your installed Rex](docs/learning/level-1.md) — a small, read-only walkthrough. No config edits, runner access, VPS changes, or installs.
2. [Research index](research/README.md) — the three completed investigations and their evidence boundaries.
3. [Cartridge organization](items/README.md) — how each future item stays independent.
4. [All-items collection](collections/all.md) — the planned opt-in way to install every ready item, **not available yet**.
5. [Product direction and transcript planning](docs/direction.md) — accepted goals, source selection, review status, and unresolved decisions.
6. [PDF-only work inventory](docs/planning/teerex-pdf-work-inventory.md) — the definitive historical review of the original three suggestion phases, 23 scored proposal groups, Rex/non-Rex boundaries, and 62 retained subrequirement/recap entries; current incremental progress is recorded separately in the direction record.
7. [Non-Rex handoff](docs/planning/teerex-non-rex-handoff.md) — eight retained general-purpose ownership groups, separated from Rex adapters; Joshua deferred assignment to another agent until later.
8. [Experimental observation commands](items/observe/README.md) — individual build/use, bounded JSON, offline changes/foreground waiting, safety limits, and disposable-Mac validation.
9. [Experimental run-and-collect](items/run/README.md) — local argv, bounded raw output, deadlines, cancellation and honest process-group cleanup limits; not a terminal or VPS executor.

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
| `items/` | Independent-item contract and experimental `observe`/`run` source/tests; no ready cartridges. |
| `collections/` | Future opt-in groups of items; currently the all-items policy. |

The research was checked on **11 November 2026**. Source/API discovery exercised Linux **0.1.0-preview.15**, API revision **13**. That is not a claim about Joshua's installed version. Official website documentation is a separate rolling snapshot, not a checkout of Rex application source.

The original searchable explorer and full capture are recorded in [provenance](research/provenance/README.md). Full vendor documentation, packaging, schemas, and binary data are **not republished here** without established redistribution terms. This repository is neither Rex source nor an official Superlogical distribution.

## Direction, not delivered features

Joshua's initial preference is a **simple, barebones, minimal Zig CLI on his M5 MacBook**, where he already has Rex downloaded as his VPS client. He has since approved proceeding through the review's suggested order in small, built-and-validated increments; this does not finalize the whole design or approve every historical suggestion. Targeted VPS/Linux support is outside initial scope; adding a Rex server on the VPS may be considered later.

Agents are first-class users of the API/work surface alongside humans. Developer experience, lovable human UI/UX, efficient resource use, and speed are product priorities; they do not require a graphical console as the first deliverable. Joshua intends to run a future installer on his M5 and load completed cartridges; no installer or M5 compatibility has been implemented or verified. Other decisions will be discussed collaboratively as they arise, not as an upfront questionnaire. See the [direction record](docs/direction.md).

The first candidate workflow is Rex as the terminal workspace/client for Rivet, using a real Rivet interface if one is established. A Lua action, terminal dashboard, or structured status adapter is a possibility to evaluate incrementally — not an implemented item. A status signal is never approval or permission. The preserved Linux/VPS research is historical context, not an initial platform-support commitment.

No project license has been selected. See [rights and attribution](RIGHTS.md); a future teerex license must not claim third-party material.
