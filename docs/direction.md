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

## PDF-only inventory preserved for review

Joshua initially uploaded four attachments, then selected **only the two PDFs** as authoritative: P1 (12 pages) and P2 (8 pages). Markdown sources and PDF/Markdown comparison are excluded. The [transcript planning thread](https://ampcode.com/threads/T-01a1ccbc-8e96-7143-95cc-2469bbc43e3c) performed the extraction, conceptual deduplication, priority/dependency ordering, and proposed-stream analysis; repository preservation did not duplicate that work.

The derived inventory is preserved byte-for-byte. The non-Rex handoff differs from its transfer only by removal of one extra final blank line; the validation record retains its original transfer hash/size alongside the repository hash/size.

- [PDF work inventory](planning/teerex-pdf-work-inventory.md): the original three suggestion phases, names, and order. Phase 1 contains six personal-workflow utilities; Phase 2 contains eight collaboration-runtime suggestions plus an unnumbered counterfactual ledger; Phase 3 contains eight Rex Dexterity suggestions. These 23 groups carry impact, feasibility, effort, and viability scores out of 10, with candid rationale, confidence, and recommendations. Higher effort means **more work**, not better. R/N/M flags distinguish Rex-specific, non-Rex, and mixed responsibilities. Phases are source groupings, not an approved implementation sequence.
- [Non-Rex handoff](planning/teerex-non-rex-handoff.md): eight optional ownership groups (H01–H08), their source-backed scope, and scored parent proposals. General-purpose cores are retained, not discarded or automatically assigned to another agent. Rex adapters and their safety obligations stay separate.
- [Extractor's validation record](planning/teerex-pdf-inventory-validation.json): source identities/hashes, inventory and handoff checksums, counts, structural checks, and limits at handoff, with the whitespace-only preservation adjustment noted above. Its statements about no publication or implementation describe the extraction step, not a claim that this copy is unpublished.
- [Original review artifact, revision 2 at preservation](https://ampcode.com/artifacts/teerex-work-inventory-be8ac399-5274-44c5-8f52-8b322e298866): private and may require Amp access; the repository copy is independently readable.

The 62 stable assistant-candidate entries remain as detailed subrequirements and recap options, not 62 separate products. Four historical requests, 12 verification gates, ten separately sourced current-direction items, source filenames/hashes/page locators, conflicts/non-actions, and dependencies remain attached. The older priority queue and seven stream roles are secondary dependency/ownership views, not replacements for the original phases. Two recap bundles and nine materially different subutility variants have additional scoped scores; aliases, supporting fields, and tests are not invented cartridges.

Preservation verified all three transfer SHA-256 hashes and byte counts, phase-group order/scores against the validation record, unique detailed IDs and R/N/M classifications, candidate/gate PDF citations, explicit page-range bounds, and inclusion of every candidate in the secondary priority queue. Those checks complement the extractor's reported reading of all 20 PDF pages; this step did not independently reread the raw PDFs, revalidate Rex APIs, or prove semantic exhaustiveness. The earlier Rex research and its provenance are unchanged.

**Preserved for review does not mean approved for implementation.** Scores are assessments, not benchmarks; rankings, handoffs, and streams are recommendations. The review recommends Phase 3 #1's terminal proprioception packet first: one bounded, read-only, target-attributed observation on the M5 MacBook, using Phase 3 #8 only to bind the actual installed methods it needs. Phase 3 #3's run-and-collect comes next; Phase 1 #1's manual park/resume is an adjacent personal utility. No generic discovery framework or Phase 2 platform is a prerequisite. None of these has been started. Raw output capture, atomic writes, enforced ownership/human revocation, subprocess lifetime/child cleanup, and isolation still require evidence; the Zig/external-client versus hosted-Lua boundary is not selected.

Only the derived inventory, non-Rex handoff, and validation record are included. Raw PDFs, extracted page text, private source manifest, attachment URLs, and Markdown transcript sources are not published here. No raw-source publication or machine/runner access is authorized by preservation.

The planning workflow retained for future updates is:

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

Those choices will be worked through collaboratively as they arise; this document records them without duplicating questions or choosing answers implicitly. No runner access, destructive removal, installer execution, configuration changes, or VPS deployment is authorized by this direction record. This is planning preservation only; no candidate implementation or new stream has been started.
