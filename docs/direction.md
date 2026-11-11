# Product direction and transcript planning

teerex is intended to become a shared console for independently addable and removable **cartridges**, with agents as first-class users alongside humans. Today it preserves research and planning only: there are no completed cartridges, lifecycle API, console implementation, or installer.

This record preserves Joshua's direction as relayed by the [Space conversation](https://ampcode.com/threads/T-01a1cc2c-d343-7288-8315-f3d06e3dae32) on 11 November 2026. It is not an authorization to start every candidate project or a substitute for the pending design decisions.

## Accepted direction

- Each isolated distro/helper is a cartridge in the shared console. Users should be able to add or remove individual cartridges at any time, including agents using the API/work surface. An all-items option must not make cartridges inseparable.
- Agents are first-class users. Design their work surface deliberately alongside the human experience, rather than treating automation as an afterthought or assuming it requires GUI imitation.
- Developer experience, lovable human UI/UX, efficient resource use, and speed all matter. No numerical performance budgets, UI design, or resource architecture have been selected yet.
- Joshua intends to run an installer on his M5 and load completed cartridges. That is a future delivery goal, not an implemented installer or verified platform-support claim.
- Rex as a client/workspace for Rivet remains a goal. No Rivet interface, working adapter, or remote deployment is established by this plan.
- Keep the work incremental: preserve the research, observe the installed Rex contract, and choose small useful next steps. The [level-one guide](learning/level-1.md) does not need machine access or VPS changes by an agent.

The [item organization](../items/README.md) and [all-items policy](../collections/all.md) reserve the repository boundaries without claiming a Rex plugin SDK, hot-unload implementation, or working package manager.

## Initial preference: a minimal local Zig CLI

Joshua's initial thinking is a **simple, barebones, minimal Zig CLI tool on his M5 MacBook**. This is the starting preference, not a finalized language/architecture design or an instruction to implement it now. The shared-console/cartridge direction does not require building a graphical console for the first step.

Joshua reports that Rex is already downloaded and acts as his VPS client. This repository work has not inspected that installation or his connection setup. The initial teerex target is the MacBook; **targeted VPS/Linux support is not needed**. Adding a Rex server on the VPS is a possible later choice, not committed scope. Linux/VPS material in the preserved research remains evidence and future context, not a delivery requirement.

Discuss other choices collaboratively when a concrete next step needs them. The open-decision list below is context, not an upfront questionnaire or a requirement to finalize the whole system before learning or planning can continue.

## Transcript intake has not started

Joshua plans to upload conversation transcripts for exhaustive actionable-item extraction. **No transcripts have arrived.** There is no extracted backlog, deduplicated task count, ranking, dependency graph, or started parallel work stream to report.

When those transcripts are supplied, the intended planning sequence is:

1. **Inventory sources.** Give every supplied transcript a stable source identity and retain its original ordering and available dates/participants. Establish what may be committed before publishing raw transcripts; they may contain private details or secrets.
2. **Extract exhaustively.** Capture actionable requests, candidate work, constraints, and unresolved questions. Preserve an exact source locator and enough quoted context to distinguish an explicit request from an inference. Do not present extracted suggestions as approved implementation work.
3. **Deduplicate with provenance.** Merge genuinely equivalent actions while retaining every supporting transcript/message reference. Preserve conflicting requirements and chronological changes instead of silently picking a convenient interpretation.
4. **Rank the candidates.** Record the reasons for relative priority using usefulness, the human/agent experience, enabling value, effort, risk, speed/resource implications, and evidence strength. Specific weights and final priorities are not decided.
5. **Order by dependency.** Identify prerequisites, blocked decisions, and the smallest useful milestones. Distinguish a real dependency from work that merely seems convenient to do first.
6. **Group parallel async work streams.** Group independent work by ownership, interfaces, dependencies, and verification boundaries. Keep dependent/shared-file work ordered; parallelism must not hide conflicts or manufacture approval to start it.

The planning output should make each action traceable to its sources, show what was merged and why, distinguish approved direction from proposals/open questions, and make sequencing and potential concurrency reviewable. No extraction framework or task schema is being implemented in this preservation step.

## Decisions still open

| Decision | What is not established |
| --- | --- |
| Initial design details | Minimal Zig CLI on the M5 MacBook is the initial preference, not a finalized design. Exact macOS/toolchain compatibility and CLI behavior will be discussed as needed; targeted VPS/Linux support is outside initial scope. |
| Shared dependencies | Isolation does not choose whether dependencies are bundled, shared, versioned centrally, or reference-counted. |
| Removal and data | Removing code does not decide whether configuration, user data, background work, or shared dependencies are retained, migrated, or deleted. In-use removal behavior is unspecified. |
| Agent permissions | First-class use does not grant unrestricted install/remove/control authority. Authentication, authorization, confirmations, auditability, and human override are not selected. |

Those choices will be worked through collaboratively as they arise; this document records them without duplicating questions or choosing answers implicitly. No runner access, destructive removal, installer execution, configuration changes, or VPS deployment is authorized by this direction record. No implementation is requested yet; transcript intake is still pending.
