# teerex

Joshua Gantt's personal, opinionated collection of Rex extensions, utilities, scripts, and helpers.

**The alpha.4 experimental distribution combines five follow-ons for Apple-silicon Mac and Linux x86_64:** independently removable native [cartridges](docs/cartridges.md), [jobs and deliberate presentation](items/jobs/README.md), [five read-only adapters/local receipts](items/adapters/README.md), [opt-in historical caching](items/filter/README.md), and [saved-evidence maneuver libraries](items/maneuvers/README.md). The [release guide](docs/releases/v0.1.0-alpha.4.md) gives exact commands, platform/API limits, binary hashes and separate core/catalog/onboarding assets. Confirm the [exact published tag/assets](https://github.com/jcbbge/teerex/releases/tag/v0.1.0-alpha.4) before installation; a branch/source candidate alone is not a release. Frozen [alpha.3](docs/releases/v0.1.0-alpha.3.md) remains available and unchanged. Runtime tests use disposable machines, not Joshua's M5/hive; API11 and every old build are not certified. Rex is not bundled.

These are bounded features, not a claim that every historical proposal is complete. Spawn verifies a new window-attached terminal, not agent readiness; send separates paste/Enter ACKs, not atomic consumption or prompt safety. Strong guarded input/clutch and learned replay remain blocked by the missing host enforcement boundary. Maneuver-check recognizes saved starts/endpoints only, never executed transitions; filter retains every evidence comparison, and opt-in cache hits remain historical/unverified. Independent cartridge packaging and the all-items collection are not in alpha.3; the [follow-on guide](docs/concierge/follow-ons.md) separately documents experimental source packaging and its ready-only selection rule. [CI](docs/ci.md) covers explicitly listed suites; local validation is not hosted success on an untested commit.

[observe/compare/watch](items/observe/README.md) incrementally implements Phase 3 #1 in Zig: bounded terminal text, process/directory/status-report provenance, explicit offline changes and C09's bounded foreground change/status-evidence waits against an explicit baseline, without activity/completion inference. Acquisition uses one supervised Rex/Lua connection; sustained polling reuses it rather than launching clients per sample. [run](items/run/README.md) adds Phase 3 #3's local argv execution, bounded output, real exit/deadline/cancellation evidence and owned-process-group cleanup through supported Rex Lua bindings. It is not terminal input, a sandbox or remote execution. There are no background watchers or working Rex–Rivet integrations. The intended destination is a shared console with isolated **cartridges** that humans and agents can add or remove independently, one or all at a time.

## Install and verify, without disturbing Rex

Use the [operator and setup-agent concierge](docs/concierge/README.md) for the complete **Who, What, When, Where, Why, How** package: [exact alpha.3 installation, non-restarting smoke, update/rollback/remove and troubleshooting](docs/concierge/setup.md), [every shipped feature's purpose, platform/API prerequisites, commands and expected evidence](docs/concierge/features.md), and [copyable local-agent installation/setup metaprompts](docs/concierge/agent-prompts.md). Captures/private storage stay opt-in; real endpoints and other live-agent panes are not public examples or implicit authorization.

[Five alpha.4 follow-on guides](docs/concierge/follow-ons.md) distinguish tagged assets from source candidates; selecting alpha.3 does not install those later commands or cartridges. The separate downloadable onboarding package contains the concierge guides, ready-to-use agent metaprompts, support/release references and reviewed lifecycle tools. Strong guarded input/human revocation, personal M5/hive validation and setup/guard migration remain separate boundaries. The corrected exact-main [hosted workflow at e16302c](https://github.com/jcbbge/teerex/actions/runs/43273134328) passed all four cells after the SDK pin; the original alpha.3-head Mac workflow failed before tests and is not relabeled green.

## Start here

1. [Level one: meet your installed Rex](docs/learning/level-1.md) — a small, read-only walkthrough. No config edits, runner access, VPS changes, or installs.
2. [Research index](research/README.md) — the three completed investigations and their evidence boundaries.
3. [Cartridge organization](items/README.md) — how each future item stays independent.
4. [All-items collection](collections/all.md) — same individual lifecycle paths, ready-only by default; experiments need explicit opt-in.
5. [Product direction and transcript planning](docs/direction.md) — accepted goals, source selection, review status, and unresolved decisions.
6. [PDF-only work inventory](docs/planning/teerex-pdf-work-inventory.md) — the definitive historical review of the original three suggestion phases, 23 scored proposal groups, Rex/non-Rex boundaries, and 62 retained subrequirement/recap entries; current incremental progress is recorded separately in the direction record.
7. [Non-Rex handoff](docs/planning/teerex-non-rex-handoff.md) — eight retained general-purpose ownership groups, separated from Rex adapters; Joshua deferred assignment to another agent until later.
8. [Experimental observation commands](items/observe/README.md) — individual build/use, bounded JSON, offline changes/foreground waiting, safety limits, and disposable-Mac validation.
9. [Experimental run-and-collect](items/run/README.md) — local argv, bounded raw output, deadlines, cancellation and honest process-group cleanup limits; not a terminal or VPS executor.
10. [Offstage terminal lifecycle](items/offstage/README.md) — bounded, explicitly owned hidden terminal jobs; no layout changes, isolation or whole-tree cleanup guarantee.
11. [Compatibility diagnosis](items/doctor/README.md), [saved maneuver start checks](items/maneuvers/README.md), and [evidence filtering](items/filter/README.md) — narrow, documented contracts, not discovery-as-permission, safe replay or completion classifiers.
12. [Install and remove the shared CLI](docs/install.md) — explicit release tags, verified assets, retained versions and rollback; no PATH/profile/Rex edits or independent cartridge selector.
13. [Visible agent spawning](items/spawn/README.md) and [whole-message sending](items/send/README.md) — exact Rex addresses and agent-core metadata; no hidden fallback, retry, prompt safety or atomic-delivery claim.

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
| `items/` | Independent-item contract and experimental observation, execution, offstage, doctor, maneuver-check and filter source/tests; no ready cartridges. |
| `tools/install/` | User-owned, explicit-version shared-CLI installation and lifecycle tests; no Rex or independently packaged cartridges. |
| `collections/` | Future opt-in groups of items; currently the all-items policy. |

The research was checked on **11 November 2026**. Source/API discovery exercised Linux **0.1.0-preview.15**, API revision **13**. That is not a claim about Joshua's installed version. Official website documentation is a separate rolling snapshot, not a checkout of Rex application source.

The original searchable explorer and full capture are recorded in [provenance](research/provenance/README.md). Full vendor documentation, packaging, schemas, and binary data are **not republished here** without established redistribution terms. This repository is neither Rex source nor an official Superlogical distribution.

## Direction, not delivered features

Joshua's initial preference was a **simple, barebones, minimal Zig CLI on his M5 MacBook**. His 12 November setup brief now prioritizes API10–13 compatibility, Linux x86-64 observation for the existing hive/API13 server, visible Rex-tab agent spawning using the existing agent-core contract, then whole-message sending with honest atomicity limits. Offstage work follows only as it serves spawn/send. All agents/workers/sidecars/messages on his machines must go through Rex and teerex; there are no headless Rivet-worker exceptions. This updates the earlier Mac-only scope without rewriting the historical review or authorizing machine/configuration changes. The setup agent owns Rivet/hive guard migration; the teerex implementation does not duplicate it.

Agents are first-class users of the API/work surface alongside humans. Developer experience, lovable human UI/UX, efficient resource use, and speed are product priorities; they do not require a graphical console as the first deliverable. Joshua intends to run the installer on his M5 and eventually load completed cartridges; the source-tree shared-CLI installer has disposable-platform validation, not M5 or independent-cartridge validation, and is not inside the binary archive. This exact release on his M5 remains a separate existing-server validation step. Other decisions will be discussed collaboratively as they arise, not as an upfront questionnaire. See the [direction record](docs/direction.md).

The first candidate workflow is Rex as the terminal workspace/client for Rivet, using a real Rivet interface if one is established. A Lua action, terminal dashboard, or structured status adapter is a possibility to evaluate incrementally — not an implemented item. A status signal is never approval or permission. The preserved Linux/VPS research is historical context; the revised brief separately prioritizes the existing hive/Linux target, not deployment of a new VPS.

No project license has been selected. See [rights and attribution](RIGHTS.md); a future teerex license must not claim third-party material.
