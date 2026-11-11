# teerex work inventory

The original suggestions form three phases: six personal-workflow utilities, a collaboration runtime, and eight concrete Rex Dexterity proposals. Phase 3 is the strongest fit for teerex; most of Phase 2 belongs in a separate agent-workflow project. Start with Phase 3's terminal proprioception packet, then deterministic run-and-collect, rather than building the entire runtime.

This review inventory uses **only the two PDFs**, following Joshua's latest source selection. The Markdown attachments are excluded; PDF/Markdown comparison is not part of the deliverable. Priorities, dependencies, and future owner roles are recommendations, not authorization to implement or start streams.

There are **23 original proposal groups**: Phase 1 has six; Phase 2 has eight numbered suggestions plus its unnumbered counterfactual ledger; Phase 3 has eight. The existing 62 A/B/C entries remain as finer-grained subrequirements and recap options, not 62 separate products. Two additional bundle assessments cover the original first-build recaps without inventing more phases. Four historical user requests, ten current-direction entries, twelve verification gates, and secondary owner-role proposals remain traceable below.

## How to read the scope flags and scores

**R — Rex-specific:** the proposed utility directly reads, controls, or adapts Rex. **N — not directly Rex-related:** it can operate without Rex; a terminal UI, Lua implementation, or libghostty dependency does not by itself make it a Rex extension. **M — mixed:** the Rex adapter and a non-Rex core are explicitly separated. These are assessments of the proposed work, not claims of exclusive applicability. A general safety rule remains necessary inside a Rex utility even when its standalone tooling is N.

Scores are my candid design assessments for Joshua's **personal, Mac-first, agent-first** teerex, not measured benchmarks or promises of 10× improvement. Each original proposal has **I/F/E/V**, each out of 10:

- **Impact (I), higher is better:** 1 = little benefit; 5 = useful in a narrow or occasional workflow; 10 = substantial daily improvement if it works. Assumes repeated agent-operated terminal work; actual usage frequency is unmeasured.
- **Technical feasibility (F), higher is better:** 1 = blocked by the proposed mechanism; 5 = plausible but material integration/enforcement gaps; 10 = routine with demonstrated interfaces. This rates whether the scoped behavior can be built correctly, not whether it is worth maintaining. Installed Rex schemas, lifetimes, capture, and enforcement have not been tested here, which limits both the score and confidence.
- **Effort (E), higher means MORE work, not better:** 1 = tiny local helper; 3 = small standalone utility; 5 = several interacting components and meaningful integration testing; 7 = a stateful subsystem; 10 = platform-scale engineering and upkeep. This is the utility's own work at its stated prerequisites, not double-counted prerequisite platforms; park/resume's E 3/10 assumes usable observations. No calendar or staffing estimate is implied.
- **Practical viability (V), higher is better:** 1 = poor fit or maintenance sink; 5 = useful only with sufficient recurring demand; 10 = durable daily value with low adoption/maintenance burden. This includes proprietary-host coupling, behavioral friction, false positives, and ongoing operator attention. Something can have F 9/10 yet V 5/10 because making it is easy and keeping it useful is not.

**Confidence:** H = the core boundary/tradeoff is clear from the proposal; M = credible but usage/integration assumptions remain; L = a missing host guarantee or capture path could change the verdict materially. Confidence is not a probability. Even H does not mean the actual installed product was exercised. Scores generally assess a useful standalone version, not an all-purpose platform; any narrower scoring scope is stated in the row. A score is provisional by at least a point, often more for L entries. No weighted total or average hides these tradeoffs.

**Build** means recommend a bounded candidate for selection, not approval. **Handoff** means retain non-Rex work for a separate owner if selected, not start an agent. **Defer** means wait for a concrete dependency or demonstrated need. **Reject** below applies to particular unsafe or disproportionate variants, not a claim that Joshua rejected the whole idea.

Source shorthand throughout: **P1** is the 12-page Rex/libghostty opportunities and collaboration PDF; **P2** is the 8-page Rex/Lua/libghostty dexterity PDF. Page numbers are physical PDF pages. Exact identities and hashes follow the phase review. Original numbered titles are retained below; typographic quotes/ligatures are normalized for readability.

## Phase 1 — the original six personal-workflow utilities

Original order: P1:pp2–5, answering the solo-developer opportunities request. This phase mixes Rex integration with broader personal developer tooling; it was not a list of six inherently Rex-only libraries.

| Original proposal, in source order | Existing IDs / source | Rex boundary | Scores I / F / E / V | Candid assessment and recommendation |
| --- | --- | --- | --- | --- |
| 1. An “abandoned thought” recovery tool | A01–A02; P1:p2 and first-build recap p5 | **M.** R: screen/directory capture and return to Rex context. N: Git evidence, manual hypothesis, next experiment, local investigation record. | **8/10 · 8/10 · 3/10 · 8/10** | **Build a manual park/resume slice** after reliable observation. Strong personal value with little machinery if interrupted investigations are frequent. Keep the two manual answers; automatic summarization would inflate cost before proving usefulness. **Confidence M:** interruption frequency and actual Rex field/navigation behavior are unmeasured. |
| 2. A friction detector that proposes your next internal tool | A03–A05; P1:pp2–3 | **M.** R: selected Rex events/process/pane observations. N: opt-in shell history/wrappers, pattern mining, automation proposals. | **5/10 · 5/10 · 7/10 · 4/10** | **Defer.** It needs trustworthy repeated data before it can distinguish useful patterns from noise. Otherwise it is an invasive activity recorder producing plausible busywork. Validate one recurring annoyance manually before building collection/mining or a weekly proposal system. **Confidence L:** no history feed or useful pattern yield established. |
| 3. Executable support evidence for your own CLI or developer product | A06–A07; P1:p3 | **N.** Bounded PTY/interaction recorder, libghostty replay, and compatibility lab can work independently of Rex. An optional future Rex import does not change that. | **6/10 · 6/10 · 7/10 · 5/10** | **Handoff; defer until a real support problem warrants it.** Potentially valuable for a CLI Joshua ships, but recorder/replay/resize/Unicode compatibility is a separate product surface. Display replay is not machine reproduction. **Confidence L:** supported byte capture, embedding/license details, and actual support demand are unverified. |
| 4. A terminal “flight recorder” for intermittent failures | A08–A09; P1:p4 | **M.** R: current screen/process snapshots and Rex event triggers. N: bounded byte/log capture, Git context, retention, successful-versus-failed-run comparison. | **6/10 · 5/10 · 6/10 · 5/10** | **Defer to one demonstrated flaky workflow.** A rolling recorder is expensive privacy/retention scope if ordinary explicit-run logs suffice. The useful first version may just retain a failed run and its last successful comparator, not watch every terminal. **Confidence L:** trigger quality and complete capture are unproven. |
| 5. A least-authority terminal assistant | A10–A11; P1:p4 | **M.** R: scope Rex observation, execution, and input capabilities. N: policy/broker enforcement, credentials, isolation, untrusted-output and export handling. | **8/10 · 4/10 · 8/10 · 5/10** | **Defer the general assistant/broker; apply narrow authority limits inside selected utilities now.** Meaningful enforcement requires controlling every privileged path. A list of tool names cannot deliver it. Reject a “safe assistant” claim based only on client conventions. **Confidence L:** Rex enforcement/revocation and isolation guarantees are not established. |
| 6. A “shipping receipt” generated from the work itself | A12; P1:p5 | **M.** R: optionally obtain exact Rex-run outputs/status. N: assemble commit/artifact/check identities, skipped checks, caveats, and a local receipt. | **7/10 · 8/10 · 3/10 · 8/10** | **Build a thin receipt when a real run produces the inputs; handoff the generic formatter if separately owned.** Good leverage with a small maintenance surface. It must report what actually ran rather than turn a green exit or screenshot into a feature/deployment guarantee. **Confidence M:** evidence availability and workflow adoption are unmeasured. |

**Phase tradeoff:** park/resume and receipts are small, plausible wins; friction mining, continuous recording, and a general permission broker are much larger commitments. The original p5 recommendation picks **park/resume**, repeating A01–A02 rather than introducing another utility. Nothing in this phase proves a capture SDK or graphical Rex plugin contract.

## Phase 2 — the original collaboration runtime proposals

Original order: P1:pp6–12, following the request for a better shared operator/agent work surface. **All nine top-level suggestions are N as generic collaboration infrastructure.** They can inform teerex's behavior without requiring teerex to become their implementation platform. A physical Rex takeover hook is Phase 3 #5, not proof that the entire task runtime is Rex-specific.

| Original proposal, in source order | Existing IDs / source | Rex boundary | Scores I / F / E / V | Candid assessment and recommendation |
| --- | --- | --- | --- | --- |
| 1. Give every task a living contract—not a prompt | B01–B02; P1:pp6–7 | **N.** Task outcome, constraints, permissions, contradiction tracking; no Rex-specific interface required. | **6/10 · 9/10 · 3/10 · 6/10** | **Handoff a small shared record; defer a new orchestration engine.** Useful discipline, but maintaining a second task source of truth can cost more attention than it saves. The score assumes a lightweight record, not automatic compliance enforcement. **Confidence H** on independence; adoption benefit remains unmeasured. |
| 2. Let me fork experiments, not just generate suggestions | B03–B05; P1:p7 | **N.** Disposable workspaces, budgets, credentials, promotion, experiment evidence. Rex blocks can display work but do not provide isolation. | **7/10 · 6/10 · 7/10 · 4/10** | **Handoff/defer the platform; reuse existing isolated workspaces first.** Discriminating experiments are valuable; owning another workspace/agent lifecycle manager is probably poor leverage for one person. Exact-run evidence can be adopted without building that manager. **Confidence M:** no workload or isolation implementation chosen. |
| 3. Give me causal memory, not conversation memory | B06–B07; P1:p8 | **N.** Evidence-backed decisions, applicability, invalidation, revalidation; usable with any agent. | **7/10 · 6/10 · 6/10 · 5/10** | **Handoff a manual evidence/decision store; defer automatic truth maintenance.** The hard part is deciding whether old evidence still applies, not storing it. A large memory system can confidently preserve stale conclusions. **Confidence M:** correctness and retrieval usefulness are untested. |
| 4. Make your interruptions instantly meaningful | B08–B09; P1:pp8–9 | **N.** Agent/task control semantics and invalidation. R extension, if selected: connect take-over to Phase 3 #5's Rex input clutch. | **8/10 · 5/10 · 7/10 · 5/10** | **Handoff the runtime semantics; defer broad implementation.** High potential value, but “pause” must propagate through queued work and owned resources. A button with no reliable cancellation/ownership semantics would be misleading. **Confidence L:** end-to-end agent control is unspecified; Rex enforcement is a separate dependency. |
| 5. Give us a shared view of what is known | B10–B11; P1:p9 | **N.** Evidence/claim navigation, provisional suspicions, contradictions; a terminal is just one presentation choice. | **6/10 · 7/10 · 5/10 · 5/10** | **Handoff; defer a dashboard.** A compact evidence view can help, but maintaining another display of “truth” is not inherently useful. Start from existing records and links rather than a new knowledge graph or internal-monologue feed. **Confidence M:** benefits depend on record quality and actual use. |
| 6. Let me ask questions with the homework already done | B12; P1:pp9–10 | **N.** Question quality, options, recommendation, blocked dependencies, batching; primarily agent behavior. | **6/10 · 9/10 · 2/10 · 7/10** | **Handoff as agent-workflow behavior; reject a dedicated cartridge without a concrete integration gap.** This is mostly how an agent should communicate, not a reason to ship another library. A lightweight checkpoint template is the credible scope. **Confidence H:** no host API is needed. |
| 7. Give me an attention budget, not just a token budget | B13–B14; P1:p10 | **N.** Interruption/escalation policy and explanation; independent of terminal host. | **7/10 · 8/10 · 3/10 · 6/10** | **Handoff a small policy; defer an attention-management service.** Valuable if it reduces avoidable questions without hiding consequential decisions. Rules and recorded exceptions are simpler than trying to infer an operator's attention continuously. **Confidence M:** operator preferences and omission costs need real feedback. |
| 8. Make handoff a first-class artifact | B15–B16; P1:pp10–11 | **N.** Goal/state/changes/evidence/risks/next step/undo and human-run evidence ingestion. Optional Rex resource control remains a separate adapter. | **8/10 · 9/10 · 3/10 · 8/10** | **Handoff/build a plain evidence-linked record outside the Rex core if needed.** Probably the best return in this phase. Do not rebuild artifact storage or demand full runtime adoption just to generate a useful handoff. **Confidence H** for a manual record; automatic completeness is not established. |
| Unnumbered: The fringe feature I'd most want: a counterfactual ledger | B17; P1:p11 | **N.** Rejected alternatives, reasons, revisit conditions; no Rex dependency. | **6/10 · 9/10 · 2/10 · 7/10** | **Handoff as a small decision-log extension.** Cheap if attached to existing decisions; annoying if every minor choice becomes paperwork. Keep consequential alternatives only. Reject building a separate memory platform for this ledger alone. **Confidence H:** storage is simple; future usefulness still depends on disciplined updates. |

**Original recap, not an extra phase:** “What I'd actually build first” proposes a continuity slice and three layers, mapped to **B18, P1:pp11–12**. **N; I 7/10, F 5/10, E 9/10, V 3/10; confidence M. Defer the bundle.** It combines task/evidence state, an execution/permission broker, and isolated workspaces/terminals. The maintenance/adoption burden is disproportionate to a minimal personal Rex utilities library even though several constituent behaviors are worthwhile. This does not mean discarding B01–B17.

**Phase tradeoff:** good collaboration practices are not automatically good new software products. Handoff records, concise task boundaries, and consequential decision logs are feasible; automatic consistency, interruption propagation, and truthful causal memory pull toward a general agent runtime. Keep a separate owner boundary rather than making all of that a prerequisite for teerex.

## Phase 3 — the original eight Rex Dexterity proposals

Original order: P2:pp2–7, after Joshua asks for concrete Rex/Lua/libghostty dexterity. Rex-hosted Lua and example APIs are historical design proposals and claims, not tested installed contracts or a mandate that the CLI be Lua-only.

| Original proposal, in source order | Existing IDs / source | Rex boundary | Scores I / F / E / V | Candid assessment and recommendation |
| --- | --- | --- | --- | --- |
| 1. Give me a terminal proprioception packet | C01–C04; P2:p2 | **R.** One bounded, target-attributed Rex observation with screen, process, reported directory/status, and evidence identity. Generic delta/interpretation and lease-record support are split below. | **9/10 · 7/10 · 4/10 · 9/10** | **Build first as a narrow observation utility.** It directly reduces agent look/guess/re-read work and supports human inspection without controlling input. Return observed facts and explicit unknowns before inferred activity. **Confidence M:** actual field/addressing/staleness semantics and one-call cost need installed validation; no measured savings yet. |
| 2. Give me guarded gestures, not raw keystrokes | C05–C07; P2:pp2–3 | **R.** Rex target/state checks, input and postconditions; noninteractive argv execution is a safer related path. Atomic conditional input may require server/application cooperation. | **8/10 · 4/10 · 8/10 · 5/10** | **Defer live-input automation; build only after the safety boundary is explicit.** Client prechecks are feasible, but the state can change before the write. Reject any claim that a Lua wrapper alone makes this atomic or generally safe. **Confidence L:** the missing conditional-write guarantee materially changes what can honestly be shipped. |
| 3. Put the fast reflexes in Lua, not in my conversation loop | C08–C11; P2:pp3–4 | **R.** Rex action/subprocess/timer lifetimes and local deterministic loops. Chunk buffering is general support code; the language split remains open. | **9/10 · 7/10 · 5/10 · 8/10** | **Build run-and-collect after observation/API binding.** Start process, collect bounded output/status, honor deadline/cancel, and return one structured result. Score covers output/status collection, not the full six-action suite's guarded input. **Confidence M:** callback chunks, action return lifetime, child cleanup, and actual round-trip reduction need testing. |
| 4. Let background terminals exist without becoming your wallpaper | C12–C15; P2:p4 | **R.** Rex detached/off-layout blocks, bounded ownership registry, deliberate presentation. **N boundary:** any sandbox/isolation mechanism. | **7/10 · 6/10 · 5/10 · 7/10** | **Build later if real background jobs clutter Joshua's layouts.** Useful organization, but every invisible process needs a deadline/cleanup rule. Reject using “offstage” to mean isolated or credential-safe. **Confidence M:** detach/close behavior, process survival, and presentation methods are not tested here. |
| 5. Give us an explicit “your hands / my hands” clutch | C16–C17; P2:p5 | **R.** Rex key/action context, control hand-back, pending-input invalidation. Reliable immediate human revocation is server-dependent. | **8/10 · 3/10 · 7/10 · 5/10** | **Defer the strong guarantee pending host support; permit only clearly labeled cooperative semantics if chosen.** A real clutch is valuable. A local flag cannot stop another authorized client or already-issued input. Do not kill running work just to stop agent input. **Confidence L:** native revocation/ownership enforcement is unverified. |
| 6. Build a learned maneuver library—without blindly replaying macros | C18–C20; P2:pp5–6 | **M.** R: dispatch verified maneuvers against observed Rex targets. N: libghostty observer/replay fixtures and disposable live TUI test harness. | **5/10 · 3/10 · 9/10 · 3/10** | **Defer; reject blind replay.** This is the highest maintenance-risk feature: application versions, prompts, focus, and destructive actions undermine reuse. Select one frequent stable maneuver before considering a library. **Confidence L:** capture, recognition, guarded input, and test coverage are all dependencies; replay only validates the observer. |
| 7. Give me a perception cache, not an endless screenshot feed | C21–C24; P2:p6 | **M.** R: bounded Rex screen/process/status reads and target attribution. N: normalization, meaningful-delta filtering, retained observations and state semantics. | **7/10 · 6/10 · 6/10 · 6/10** | **Defer until the observation utility demonstrates costly redundant reads.** A small last-observation cache may help; a semantic classifier can suppress an important prompt or error. Keep raw evidence and distinguish quiet/stable/idle/completed/input-waiting. **Confidence M:** change quality and real CPU/memory/token savings are unknown. |
| 8. Make the installed Rex server teach me how to use it | C25–C28; P2:p7 | **R.** Discover actual connected-server schemas/examples, bind a small allowed method set, track version identity, keep permissions separate. | **8/10 · 7/10 · 4/10 · 8/10** | **Build only the API binding needed by #1/#3 now; defer a generic generator/framework.** This protects concrete utilities from invented/stale calls. Discovery does not grant permission and cannot prove behavioral semantics. **Confidence M:** historical discovery commands/schema completeness have not been exercised against Joshua's installation. |

**Original recap, not an extra phase:** the p7–8 first-build package maps to **C29–C32**: three proposed Lua modules, six-operation vocabulary, a failing-CLI acceptance workflow, and three success measures. **R bundle with N support components; I 9/10, F 4/10, E 9/10, V 5/10; confidence L. Defer the whole bundle; stage #1/#3/#8 first.** Full acceptance also demands input takeover and isolation, whose guarantees remain unresolved. Preserve the module responsibilities and proposed operations without treating names, a daemon, all six tools, or Lua-only implementation as agreed architecture.

**Phase tradeoff:** observation and deterministic output collection offer the clearest teerex value. Input/clutch guarantees are not equally ready; replay and learned maneuvers are substantial separate commitments. Avoid turning every supporting mechanism into another cartridge or library.

### Subutility scores where a phase item bundles materially different work

The 23 original groups stay intact. These subordinate assessments make the six named actions and the broader recorder/generator variants visible instead of assigning the safe output collector's score to unsafe input or a whole framework. Scores are **I/F/E/V**, each out of 10. The action names are historical proposals; the brief scope interpretations below are assessment assumptions, not verified Rex APIs. Supporting fields, tests, safety rules, and filenames are not separate products needing artificial scores.

| Parent / subutility / source | Rex boundary | Scores I / F / E / V | Scope, recommendation and uncertainty |
| --- | --- | --- | --- |
| Phase 1 #3: bounded support recorder/replay, A06; P1:p3 | N | **6/10 · 6/10 · 6/10 · 5/10** | **Handoff/defer.** Capture one product interaction plus metadata and replay its display. Avoid a full compatibility lab in the first recorder. **L:** supported byte capture and embedding conditions unverified. |
| Phase 1 #3: compatibility lab, A07; P1:p3 | N | **6/10 · 5/10 · 8/10 · 4/10** | **Handoff/defer.** Adds controlled resize, Unicode, prompts, confirmations and live product fixtures. More moving parts than replay alone; only worth maintaining for a product with recurring terminal regressions. **L:** no fixture workload or capture/live-test stack chosen. |
| Phase 3 #3: `run_and_collect`, C08/C09; P2:pp3–4 | R | **9/10 · 7/10 · 5/10 · 8/10** | **Build selected slice.** One argv-run's bounded output, actual exit/deadline/cancel result, cleanup evidence. **M:** verify handle/action lifetime, chunk boundaries and exit semantics. This repeats the scoped parent score, not a second feature. |
| Phase 3 #3: `wait_for_program_status`, C09; P2:p4 | R | **7/10 · 6/10 · 3/10 · 7/10** | **Build only for a selected status-aware program.** Await an explicitly defined reported state with deadline; report unsupported/no-status distinctly. **M:** a terminal-reported status is not proof that an arbitrary program or task completed. |
| Phase 3 #3: `observe_until_changed`, C09; P2:p4 | R | **7/10 · 7/10 · 3/10 · 7/10** | **Build after packet if repeated polling costs matter.** Bound the wait and state the compared fields. **M:** exact subscription/event versus polling path and cost are untested; detecting any change is easier than semantic relevance. |
| Phase 3 #3: `capture_on_exit`, C09; P2:p4 | R | **7/10 · 7/10 · 3/10 · 8/10** | **Build as part of run-and-collect before a separate cartridge.** Capture a controlled process's final evidence from a real exit signal. **M:** process association and final-output drain must be verified; quiet screen is not exit. |
| Phase 3 #3: `verify_then_write`, C09 plus C05/C07; P2:pp3–4 | R | **8/10 · 4/10 · 8/10 · 5/10** | **Defer.** Inherits Phase 3 #2's precheck/write race and conditional-input dependencies. **L:** no server guarantee demonstrated. Reject treating it like another harmless polling helper. |
| Phase 3 #3: `cancel_and_collect`, C09/C11; P2:p4 | R | **8/10 · 5/10 · 6/10 · 7/10** | **Build only for an explicitly owned job with tested limits.** Stop that job, retain partial evidence, distinguish requested cancellation from observed exit and report surviving work. **L:** actual cancellation/child cleanup/lifetime behavior is untested. Do not promise a whole-process-tree kill from an unverified handle. |
| Phase 3 #8: general generated adapter/framework variant, C26; P2:p7 | R | **7/10 · 5/10 · 7/10 · 5/10** | **Defer; keep the parent's small direct binding.** Full generation/version/policy coverage creates a framework to maintain before there is a selected utility. **L:** descriptor completeness and semantic coverage are unverified; schema validation alone cannot establish safe behavior. |

**Recap aliases do not multiply features:** C30's `observe` maps to Phase 3 #1; `run` to #3/run-and-collect; `gesture` to #2/verify-then-write; `watch` to the chosen status/change waiter; `present` to #4; `yield` to #5. C29's three proposed module filenames partition those same responsibilities. Their applicable scores are those referenced above; they are not nine additional cartridges. C31's acceptance exercise and C32's metrics are verification of selected work, not products.

## Next Rex-specific continuation: the packet, not a generic discovery project

1. **Phase 3 #1, C01–C04:** define and exercise one bounded observation of a selected Rex target, with explicit target/evidence identity, supported screen/process/directory/status fields, observed-versus-derived distinctions, and unknown/unavailable values. Human and agent results must describe the same facts. Use supported fields first; do not invent a raw-output feed, inferred process completion, or enforced ownership.
2. **Phase 3 #8, C25–C28, only as #1's dependency:** obtain the actual installed method/field schemas needed for that packet, bind that small set, and record server/schema identity and permission limits. This is part of delivering the original observation utility, not a detached capability-discovery roadmap or full client generator. V02/V03/V08 are the narrow checks.
3. **Phase 3 #3, C08–C11, then C06:** add one argv-based run-and-collect path with bounded output, deadline, exit/cancel/cleanup evidence, split-chunk handling, and verified process lifetime. Use #8 only for the methods that path needs. A quiet screen is not an exit signal. Defer `verify_then_write`, live-input clutch, background orchestration, recorder, and replay from this slice.
4. **First adjacent personal workflow: Phase 1 #1, A01–A02.** Once reliable read-only observations exist, a manual park/resume utility can reuse them without waiting for the Phase 2 runtime. Shipping receipts can likewise consume exact-run results rather than require a generic evidence platform.

This is a ranked recommendation for the next Rex work, not implementation or approval of all four steps. Initial Zig CLI preference remains tentative. Verification must establish supported behavior and real overhead on Joshua's Mac; this review has no such runtime evidence.

## Separate non-Rex handoff set

This set is ready for a different owner to evaluate; **no new agent was started and no non-Rex implementation was approved**. Handoff the reusable core, not authority over teerex's Rex adapter. A possible extraction is not a requirement to create another package. Public-preservable planning includes these paraphrased IDs/page locators; raw transcripts and private excerpts stay excluded.

| Handoff unit | Original phase / exact inventory coverage | Non-Rex responsibility; teerex boundary |
| --- | --- | --- |
| H01 — investigation/evidence records and receipts | Phase 1 #1/#4/#6: N portions of A01/A02/A08/A12; A09. Phase 2 #2/#8: B05/B15/B16. | Local manual context, Git/exact-run evidence, compare runs, concise receipts/handoff. Rex capture/navigation/status remain in teerex. Reuse existing artifact/file storage before inventing a general evidence service. |
| H02 — opt-in instrumentation and friction proposals | Phase 1 #2: A04/A05 and N analysis portion of A03. | Selected shell/command wrappers, explicit consent, repeated-sequence analysis. No assumed Rex command-history feed; Rex event adapter remains separate. Defer absent a manually confirmed repeated problem. |
| H03 — recorder, replay, compatibility and maneuver test harness | Phase 1 #3/#4: A06/A07 and N capture portion of A08. Phase 3 #6: C19/C20 and N recognizer/test portion of C18. | Bounded PTY capture, libghostty observer replay, resize/Unicode fixtures, disposable live TUI tests. No claim of reproducing a whole machine or validating future live responses through replay. Rex dispatch remains C05/C18. |
| H04 — generic authority and isolation | Phase 1 #5: N policy/broker portion of A10; A11. Phase 2 #1/#2: B01 permissions/B03/B04. Phase 3 #4/#8: C15 and N policy portion of C28. | Credential/isolation/enforcement design and reusable privacy rules. Retain those rules inside every selected Rex utility; handoff does not defer its safety obligations. Native Rex conditional-input/revocation questions remain C07/C17, not solvable by a generic broker alone. |
| H05 — task/experiment runtime | Phase 2 #1/#2/#4: B01/B02/B03/B04/B08/B09; B18 aggregate. | Living contracts, disposable workspaces, resource lifecycle, interruption propagation, invalidation. Existing tools first; no mandatory full runtime under teerex. A Rex resource-control bridge can consume the generic semantics after its own review. |
| H06 — causal memory, knowledge view and decision ledger | Phase 2 #3/#5/ledger: B06/B07/B10/B11/B17. | Evidence applicability, claims, navigation, contradictions, consequential alternatives/revisit conditions. Rex is only an optional evidence source, not the host or truth authority. |
| H07 — prepared questions and attention policy | Phase 2 #6/#7: B12/B13/B14. | Agent communication/checkpoint policy. Prefer behavior/templates over standalone software; do not package a cartridge merely to ask better questions. |
| H08 — generic observation processing and execution support | Phase 3 #1/#3/#7: N portions of C03/C04/C21/C23; C10/C22/C24; generic metric portion of C32. | Delta/phase interpretation, optional lease record, line-chunk buffering, cache/filters, distinct state semantics and metric definitions. Keep these as support code unless actual independent reuse justifies a library. Rex readers, process handles, server identity, and concrete measurements remain teerex responsibilities. |

Overlapping handoff rows are deliberate conceptual reuse, not duplicate implementations or simultaneous file ownership. A future integrator must assign one owner per shared record/helper. Proposed independent async work, only if selected: Rex observation/API-binding owner (#1/#8); non-Rex evidence/handoff owner (H01); non-Rex replay feasibility owner (H03); read-only input-enforcement research owner (C07/C17). Separate outputs can proceed without changing the same adapter or controlling the same terminal. Execution (#3) consumes the selected method/result contract; none of H02–H08 is a prerequisite platform to build first.

## Boundary register for every existing candidate entry

The phase tables restore original groupings; this register prevents the finer-grained 62-entry inventory from hiding mixed boundaries. Source passages and full subrequirements are retained in the A/B/C tables below. Scores belong to the original proposal groups, not artificially independent scores for each supporting field/test. Aggregate B18 and C29–C32 have explicit bundle assessments above. Every A/B/C entry appears exactly once here.

| ID | Flag | Boundary rationale |
| --- | --- | --- |
| A01 | M | R screen/directory capture; N manual/Git investigation record. |
| A02 | M | R session/layout return; N reasoning-first resume view. |
| A03 | M | R events/process/pane inputs; N repeated-friction analysis. |
| A04 | N | Explicit shell instrumentation/wrappers do not require Rex. |
| A05 | N | Pattern-to-script proposals operate on generic history. |
| A06 | N | Interaction recorder and libghostty replay are independent of Rex. |
| A07 | N | CLI/TUI compatibility lab tests products, not Rex's API. |
| A08 | M | R event/screen/process snapshots; N capture, retention and Git/log bundle. |
| A09 | N | Exact-run success/failure comparison is backend-independent. |
| A10 | M | R allowed Rex operations; N enforcing broker/credential policy. |
| A11 | N | Untrusted-output/redaction rule applies to any host; still required in teerex. |
| A12 | M | R optional run evidence source; N receipt assembly/storage. |
| B01 | N | Task contracts and permission records are agent-runtime state. |
| B02 | N | Collaborative edits and contradiction tracking are not host APIs. |
| B03 | N | Disposable filesystem environments are not Rex terminal blocks. |
| B04 | N | Generic experiment budgets, credentials, cancellation and promotion. |
| B05 | N | Evidence/experiment record can be produced by any runner. |
| B06 | N | Causal decision/claim model has no Rex requirement. |
| B07 | N | Evidence revalidation is generic memory lifecycle. |
| B08 | N | Agent interruption semantics; concrete Rex clutch is C16/C17. |
| B09 | N | Plan invalidation is generic task dependency management. |
| B10 | N | Shared knowledge display can use any surface. |
| B11 | N | Evidence navigation/contradiction semantics do not require Rex. |
| B12 | N | Prepared questions are agent behavior, not a terminal extension. |
| B13 | N | Attention/escalation policy is independent of terminal host. |
| B14 | N | Explaining interruptions is generic operator communication. |
| B15 | N | Handoff record does not require resource-control APIs. |
| B16 | N | Human evidence ingestion/provenance is backend-independent. |
| B17 | N | Counterfactual decision ledger can be an ordinary file. |
| B18 | N | Generic collaboration-runtime bundle; terminals are only one resource. |
| C01 | R | Bounded observation explicitly addresses a Rex server/session/block. |
| C02 | R | Field provenance depends on what Rex actually observes/reports. |
| C03 | M | R observed Rex deltas; N optional activity/phase interpretation. |
| C04 | M | R target/snapshot attribution; N optional ownership/lease bookkeeping, not enforcement. |
| C05 | R | Target-checked Rex input/postconditions; atomicity remains a host issue. |
| C06 | R | Use actual Rex argv execution/process handles rather than typed input. |
| C07 | R | Conditional input/application cooperation concerns the Rex write path. |
| C08 | R | Deterministic loops run against Rex process/action/timer interfaces. |
| C09 | R | Six named actions wrap Rex observation/process/input methods; only a subset is proposed first. |
| C10 | N | Partial-line buffering is general stream correctness, retained as support code. |
| C11 | R | Rex action/handler return and detachment semantics govern lifetime. |
| C12 | R | Off-layout/detached blocks are Rex resources. |
| C13 | R | Purpose/owner/deadline/cleanup registry here manages hidden Rex blocks. |
| C14 | R | Move/float/label/focus behavior is Rex presentation control. |
| C15 | N | Filesystem/network/credential isolation needs a separate boundary; still a teerex constraint. |
| C16 | R | Rex key/action context and input-yield behavior implement the clutch. |
| C17 | R | Native revocation/ownership would need Rex server enforcement. |
| C18 | M | R verified target maneuvers; N recognizers/version domains/test fixtures. |
| C19 | N | Headless libghostty observer replay does not require Rex. |
| C20 | N | Disposable live TUI action tests are generic; a Rex input driver is a separate adapter. |
| C21 | M | R source/target reads; N normalization/cache/retention processing. |
| C22 | N | Cosmetic-versus-meaningful change filtering is a generic algorithm. |
| C23 | M | R supported selective reads first; N optional captured-byte interpretation sidecar. |
| C24 | N | Quiet/stable/idle/completed/input-waiting distinction is host-independent correctness. |
| C25 | R | Discover the installed/connected Rex server's API descriptions. |
| C26 | R | Bind only selected Rex methods to their actual schemas. |
| C27 | R | Invalidate a Rex adapter against server/schema version identity. |
| C28 | M | R allowed Rex surface; N policy remains separate from API availability. |
| C29 | R | Original three-module proposal partitions Rex observation/supervision/actions. |
| C30 | R | Original six operations are proposed Rex work-surface tools. |
| C31 | R | Acceptance exercises a selected Rex-controlled CLI workflow; generic isolation is not assumed. |
| C32 | M | R measure the chosen Rex workload; N generic metric definitions/methodology. |

## Detailed evidence, subrequirements and earlier priority views

The remaining sections preserve the original stable IDs, page coverage, detailed conditions, historical requests, and current direction. The phase tables and recommendations above are the primary review. The older P0–P3 queue and S0–S6 roles below are secondary dependency/ownership views, **not the original three phases**, product approvals, or a mandate to build non-Rex infrastructure.

## Read the status before treating an item as work

- **Joshua request (U)**: a historical user turn. Asking for ideas does not approve the returned ideas.
- **Current direction (D)**: explicit context supplied with this analysis, kept separate from transcript evidence.
- **Candidate (A/B/C)**: an assistant-authored suggestion, including example interfaces, filenames, acceptance tests, and cautions. None is approved merely because it appears here.
- **Verification gate (V)**: a historical claim or dependency to check before relying on it. An assistant saying it checked documentation is not fresh verification.
- **Deferred/conflicting**: an approach requiring a later choice or outside initial scope. This is not evidence Joshua rejected it.

Completed here: PDF reading, extraction, conceptual deduplication, source-backed organization, ranking, and stream proposals. Not performed: installed-Rex/API testing, cartridge/installer implementation, or repository edits/publication.

## The two authoritative PDFs have stable identities

`P1:p2` means the second physical page of P1; `P2:pp5–6` means physical pages 5 and 6 of P2. Candidate IDs such as A01 and B01 identify inventory entries, not additional source documents. Page plus the named feature/section in each row locates the supporting passage.

| Source | Exact downloaded filename | Extent / historical turns |
| --- | --- | --- |
| P1 | `5c718d7e-is-the-rex-multiplexer-from-super-logical-built-us.pdf` | 12 pages. Three user turns: implementation-language question on p1; non-obvious solo-dev opportunities on p1; agent/operator collaboration on p6. |
| P2 | `d07903d2-hmm.you-can-t-experience-joy-but-what-if-your-se.pdf` | 8 pages. One follow-up user turn on p1 requesting concrete Rex/Lua/libghostty dexterity ideas; answer continues through p8. |

| Source | SHA-256 of unchanged original |
| --- | --- |
| P1 | `8b873b839934d5123d30691ce93c99a3d117ed4a4f9470ac0a10121f144ececf` |
| P2 | `87aac215494df7bd66ed3602caa989def6cd8d9cebb64ca412a0bc607584b9a0` |

Both PDFs were downloaded using authenticated `amp files get`, opened with the media reader, and extracted page by page with Python `pypdf` in layout mode. All 20 extracted pages were read. Nonprinting NUL artifacts were removed only from derived inspection copies; original PDFs were unchanged. Page/turn checks from the media reader agree with extraction. Minor typography/ligature extraction losses do not supply new work items.

Chronology follows turn continuity: P1's three turns, then P2's follow-up. No reliable conversation date is established. The PDFs are not duplicates: P1 contains six personal-workflow concepts plus a shared-runtime proposal; P2 supplies eight more concrete dexterity directions. Overlapping concerns are cross-referenced below rather than counted as separate runtime implementations. Raw sources and private attachment URLs are not included in this repository-review copy; a private handoff manifest identifies retrieval locations.

## Joshua requested exploration, then greater technical specificity

| ID | Historical request | PDF locator / interpretation |
| --- | --- | --- |
| U01 | Determine whether Rex is implemented in Zig like Ghostty. | P1:p1, first user turn and answer. Research question, not teerex language selection; answer distinguishes engine from application implementation. |
| U02 | Explore non-obvious opportunities for an indie solo developer using the Rex/libghostty split; acknowledge conventional uses without stopping there. | P1:p1, second user turn; p2, entry-point distinction. Tailored exploration, not adoption of every suggested feature or permanent rejection of conventional uses. |
| U03 | Explore an agent's ideal collaborative work surface with high efficiency, optimization, and operator/agent quality of life. | P1:p6, third user turn. Positive reception followed by another ideation request, not approval of the ensuing runtime architecture. |
| U04 | Make the ideas concrete to Rex, Lua, and libghostty and improve terminal dexterity. | P2:p1, opening user turn and refocusing response. Corrects abstraction level; does not approve the subsequent Dexterity name, modules, or APIs. |

There is **no historical selection of a first cartridge, approved runtime architecture, chosen Lua-only implementation, authorization for terminal input, or abandonment of a named cartridge by Joshua** in these PDFs. The subjective-experience aside on P2:p1 is conversational framing, not teerex work.

## Current direction governs the historical suggestions

D items come from the explicit coordinating brief and repository updates, not inferred PDF decisions.

| ID | Current direction | Planning consequence |
| --- | --- | --- |
| D01 | Personal, opinionated Rex extensions/utils/helpers library for Joshua. | Start with his real workflow, not a generic platform. |
| D02 | Eventual console of independently installable/removable cartridges, individually or all together. | Keep utilities separable; no mandatory full runtime. Exact packaging/lifecycle remains undecided. |
| D03 | Agents are first-class API/work-surface users. | Design structured machine access alongside human commands. |
| D04 | Polished human UX and developer experience. | Minimal scope still needs clear results/errors, handoff, and documentation. |
| D05 | Speed and resource efficiency matter. | Measure real cost and latency rather than infer performance from language. |
| D06 | Barebones minimal Zig CLI on Joshua's M5 MacBook is the initial preference, not finalized design. Rex is already downloaded. | Determine external-client versus Rex-hosted Lua responsibilities from verified contracts. Downloaded does not establish configured/running server state. |
| D07 | No initial targeted VPS/Linux support; future VPS Rex server optional. | No initial remote deployment, fleet, or Linux-portability stream. |
| D08 | Other design decisions are collaborative when relevant, not an upfront questionnaire. | Bring specific tradeoffs when dependencies demand them; continue independent investigation. |
| D09 | Rex is proprietary; previous research verifies terminal-first Lua/API capabilities, not arbitrary renderer/plugin contracts. | Begin with supported external interfaces; do not assume internal or graphical extension access. |
| D10 | Repository preservation/publication belongs to the separate repository thread. Public `jcbbge/teerex` initial main is reported published. | No access blocker remains; this analysis does not edit its separate checkout or publish raw sources. |

The remote-publication update and current direction were supplied by coordinating threads; this analysis did not independently inspect the remote or its direction document. They constrain planning but are not new Rex product evidence.

## Rank by safety, useful small scope, and dependency cost

- **P0 — contract/safety first:** prevent unsafe input, data exposure, unsupported capability assumptions, and avoidable integration churn. A gate applies when its dependent feature is attempted; it is not permission to build a large security platform first.
- **P1 — smallest useful local slice:** bounded observation and deterministic execution useful to both agents and humans, without a byte tap, replay engine, GUI, remote server, or whole runtime.
- **P2 — adjacent workflow value:** park/resume, evidence, receipts, handoff, and offstage management, each independently useful after its necessary small contracts are credible.
- **P3 — conditional expansion:** broad telemetry, learned maneuvers, full orchestration, and headless replay need additional evidence, complexity, and maintenance. Their safety gates remain P0 whenever attempted.

Within a priority, satisfy dependencies first and favor direct daily value with fewer moving parts. This ranking assumes terminal dexterity is the initial focus because U04 requests concrete machinery. If recovering interrupted investigations is more valuable to Joshua, A01–A02 can become the first utility after the same read-only checks. Priorities are not effort estimates. The 10× framing is aspirational; neither PDF supplies a measured improvement or concrete performance acceptance threshold.

### Secondary cross-scope consideration queue

This older dependency queue is retained for stable-ID coverage, not as the primary review or an all-teerex backlog. Apply the R/N/M flags and phase-level recommendations above: an N record/policy can be reused or handed off without building its platform. A dual-priority item has an early safety/baseline portion and a later feature portion, not two implementations. Within each row, semicolons separate dependency or responsibility groups rather than assert a strict total order.

| Priority | Candidate IDs, ordered into useful work groups | Scheduling meaning |
| --- | --- | --- |
| P0 | C25/C28; A10/A11; C07/C17; C15; safety portions of B04/C05/C16 | Verify discovery/privacy first for observation. Research input/isolation limits independently; do not delay a read-only utility for unrelated mutation capabilities. V02/V03/V08 are first-stream gates; V06/V07 apply to their dependent features. |
| P1 | C01/C02/C04/C23 baseline; C03/C26/C27; B05; C06/C08/C09 selected subset/C10/C11/C24; C31 staged/C32 | Observation contract, then evidence/execution contracts, then an exercised small slice and measurements. C03 interpretation may be omitted until useful; raw observed fields remain sufficient. |
| P2 | A01/A02/A12; B01/B02/B06/B07/B17; B08/B09/B10/B11/B12/B13/B14/B15/B16; C12/C13/C14/C21/C22; feature portions of C05/C09/C16; C29/C30 | Choose actual utility value; no obligation to build all continuity features or proposed module/API options. Input portions remain gated by P0 findings. |
| P3 | A03/A04/A05; A06/A07/A08/A09; B03/B04 tooling/B18; C18/C19/C20; C23 byte-stream extension | Conditional telemetry, capture/replay, orchestration, and learned maneuvers. Each needs a concrete use case before investment. |

## Verification gates protect against historical assumptions

All capabilities below remain to be checked against the installed build before reliance. Documentation references are research starting points, not newly validated facts. These are supporting checks, not independently scored utilities. Boundary flags: **R:** V01/V02/V03/V05/V06/V10; **N:** V09's standalone libghostty feasibility; **M:** V04's Rex capture versus external instrumentation, V07's Rex visibility versus general isolation, V08's adapter versus policy, and V11/V12's Rex acceptance versus general evidence/measurement methodology.

| ID | Check and decisive evidence | Source / dependency |
| --- | --- | --- |
| V01 | Distinguish terminal-engine language/relationship from Rex application implementation and teerex's language choice. Research proprietary internals only if a real dependency requires it. | P1:p1, initial answer. Nonblocking for a CLI. |
| V02 | Record installed client/server versions, available schemas/examples, and actual discovery behavior. Verify historical `rex api list --json` and `rex api describe session.view --json` examples before using them as contracts. | P2:p7, API discovery. Gates C25–C27 and S1. |
| V03 | Verify session/block addressing, screen format, foreground-process and last-reported-directory semantics, program status, action context/keybindings, and events/timers. Separate raw, derived, and possibly stale fields. | P1:p2, entry points; p3, history limitation. P2:pp1–2, 4–5. V02; gates C01–C04/C08/C12/C16. |
| V04 | Establish a supported capture path before claiming raw output subscription, complete command history, replay, or continuous recording. Evaluate explicit command/shell or separate PTY instrumentation if needed. | P1:pp3–4, friction/support/recorder limitations; P2:p6, capture paragraph. Gates A03–A09/C19/C23. |
| V05 | Verify argv execution, output/status capture, partial streaming chunks, wait/running/kill/stdin handles, deadlines, detachment, process lifetime on action return, and cancellation/child cleanup. | P1:p5, receipts; P2:pp3–4, exec/reflexes. V02; gates C06/C08–C11/B04. |
| V06 | Determine whether the server enforces ownership, immediate human revocation, and conditional writes. Establish the observe/write race and limits of a cooperative lease. Consider a focused upstream request or application cooperation only if needed. | P2:p3, final paragraph; p5, clutch. Gates C05/C07/C16/C17 and full takeover acceptance. |
| V07 | Verify detaching versus closing, visibility operations, and process survival. Separately verify filesystem/network/credential isolation; offstage blocks are not sandboxes. | P2:p4, offstage section. V03/V05; gates B03/C12–C15. |
| V08 | Define permission/credential boundaries and capture/export privacy. Verify redaction, untrusted terminal-content handling, and denied operations, not only allowed ones. | P1:p4, least authority; pp6–7, task/experiment permissions. P2:p7, policy distinction. Gates A10/A11/B01/B04/C28. |
| V09 | Check libghostty-vt ABI/version/platform, embedding/redistribution/license suitability only when justified. Validate a capture-to-replay path and observer-versus-live-action boundaries. | P1:pp2–3, entry point/support; p5, Rex-first. P2:pp1, 5–6. V04; gates A06/A07/C19/C20. |
| V10 | Do not assume arbitrary graphical renderer/plugin or internal Rex extension contracts. Find a supported integration only if a chosen utility needs it. | P1:p2, SDK distinction; D09. No graphical plugin contract established by these PDFs. |
| V11 | Select a real failing local CLI workflow; independently establish baseline failure, useful observations, exact-run evidence, cancellation and takeover limits. Record unsupported acceptance criteria rather than manufacture success. | P1:p5, screenshot-as-proof caution; P2:pp7–8, acceptance/metrics. Relevant V02–V08; C31. |
| V12 | Baseline model round trips, operator interruptions, and unverified/misdirected inputs; compare the chosen slice. Add latency, memory/CPU, output-size/background-work bounds to operationalize current D05. | P2:pp7–8, three success measures; D05 supplies added resource metrics, not a historical commitment. |

Historical first-party lookup targets: `https://www.superlogical.com/rex/docs/reference/lua`, `https://www.superlogical.com/rex/docs/automate/server-api`, `https://www.superlogical.com/rex/docs/automate/lua-events`, `https://www.superlogical.com/rex/docs/automate/lua-scripts`, `https://www.superlogical.com/rex/docs/reference/cli`, `https://lib.ghostty.org/vt/`, and `https://mitchellh.com/writing/libghostty-1-0`. Presence in the PDFs' references is not verification of route availability or installed-version compatibility.

## Detailed Phase 1 subrequirements: A candidates

Every row is an **assistant suggestion**. Dependencies identify necessary checks or reusable outputs, not a requirement to install all earlier cartridges. Subrequirements are kept together where they form one coherent utility.

| ID / proposed priority | Actionable candidate and retained subrequirements | PDF locator / dependencies |
| --- | --- | --- |
| A01 / P2 | **Park an investigation manually:** selected screens/directories; Git commit, diff, untracked-file names; user-entered hypothesis and next discriminating experiment; local save. Test the two manual answers before automatic summarization. | P1:p2, abandoned-thought section; p5, first-build steps. V03/V08. |
| A02 / P2 | **Resume reasoning before layout:** show unresolved question/next experiment, then evidence, then navigate to relevant session/layout. Test whether reasoning recovery beats pane-arrangement recovery. | P1:pp2, 5, recovery and first-build sections. A01; V03 navigation. |
| A03 / P3 | **Instrument repeated friction selectively:** recurring environment repairs, small command variations, repeated diagnostic file pairs, or pane habits after service exits. Keep local and opt in per project. | P1:pp2–3, friction detector. V04/V08; capture consent. |
| A04 / P3 | **Obtain reliable command sequences:** explicit shell instrumentation or selected-command wrappers when events/screens cannot supply complete history. Do not silently introduce general activity recording. | P1:p3, friction limitations. V04/V08; supports A03/A05, not a baseline requirement. |
| A05 / P3 | **Propose automation periodically:** observed recurring sequence, draft script, and cases where applicable. The suggested weekly cadence is not an enabled schedule or obligation. | P1:p3, weekly-proposal passage. A03/A04 and useful repeated evidence. |
| A06 / P3 | **Capture bounded support evidence:** interaction, dimensions, timestamps, tool versions, checkpoints, and optional libghostty replay controls. Display replay does not recreate the original machine/filesystem. | P1:p3, support-evidence section. V04/V08/V09. |
| A07 / P3 | **Test developer-interface compatibility:** narrow widths, resize during prompts, Unicode, multiline errors, progress indicators, visible destructive confirmations. Judge interface behavior, not only exit status. | P1:p3, compatibility lab. A06/equivalent fixtures; V09/live runs. |
| A08 / P3 | **Retain an intermittent-failure flight record:** bounded rolling capture; trigger retains screen, process, Git, selected logs, trigger note. Separate byte capture if needed; start on one flaky migration/release/service startup, not every terminal. | P1:p4, flight recorder. V04/V05/V08; selected workflow. |
| A09 / P3 | **Compare selected successes and failures:** retain useful successful-run evidence and compare exact runs instead of diagnosing one failure in isolation. | P1:p4, recorder's closing paragraphs. A08/equivalent explicit-run evidence. |
| A10 / P0 | **Define progressive authority:** selected-screen read, diagnosis proposal, exact-command proposal, approved isolated diagnostic, explicitly approved live input. Broker/credentials/environment must enforce boundaries; tool names alone cannot. | P1:p4, least-authority section. V08/V06 for input. |
| A11 / P0 | **Treat terminal text as untrusted; redact before export:** output that resembles instructions is still data. Apply secret handling to observations, support bundles, memory, and receipts. | P1:p4, final safety paragraph. V08; constraint if dependent utility is selected. |
| A12 / P2 | **Generate a shipping receipt:** commit/artifact identity; named checks and actual results; selected output; skipped checks; human caveat; assemble/store. Screenshot supports but does not prove success. Customer-facing deployment evidence is optional later use. | P1:p5, shipping-receipt section. V05/V08; B05-style record optional. |

## Detailed Phase 2 subrequirements: B candidates

These are assistant suggestions from the collaboration-runtime answer. A small record or separate utility may capture value without adopting the full runtime.

| ID / proposed priority | Actionable candidate and retained subrequirements | PDF locator / dependencies |
| --- | --- | --- |
| B01 / P2 | **Living task contract:** outcome, done-when conditions, constraints, autonomy permissions, escalation triggers. Example payment requirements are illustrative, not teerex rules. | P1:pp6–7, task-contract section. V08; may be a local record. |
| B02 / P2 | **Collaborative edits with contradiction visibility:** avoid silently choosing boundaries or replacing all context with the latest message. Track changed assumptions and expose conflicts. | P1:p7, contract conclusion. B01/B09. |
| B03 / P3 | **Fork bounded experiments:** few disposable environments, independent filesystem state, one hypothesis each, cheap creation/teardown. Seek discriminating evidence, not many competing agent implementations. | P1:p7, fork-experiments section. V07/V08; existing isolation may suffice. |
| B04 / P0 gate, P3 tooling | **Constrain lifecycle:** resource/time budgets, no production credentials by default, child-process cancellation, cleanup reporting, promotion of successful experiments into reviewable changes. | P1:p7, experiment requests. B03/V05/V07/V08. Required limits if attempted; broad tooling deferred. |
| B05 / P1 | **Explicit experiment/evidence record:** question, change made, observation, what supported, what not established, cost, cleanup status. Separate observation from inference and attribute exact run. | P1:p7, experiment-result fields. V05 if execution-generated. |
| B06 / P2 | **Causal decisions/claims:** decision, reason, evidence, scope, revisit condition; source, observed/inferred/chosen status, invalidator, confirmation state. Preserve why, not merely what was said. | P1:p8, causal-memory section. B05/other evidence; V08. |
| B07 / P2 | **Expire/revalidate stale memory:** prevent dated failures or changed circumstances becoming permanent beliefs; decide which memories still apply. A universal TTL is not specified. | P1:p8, memory conclusion. B06. |
| B08 / P2 | **Precise interruption semantics:** pause stops new work/preserves state; wrong direction preserves evidence/abandons approach; explain shows concise work summary without changing task; take over releases relevant resource; continue stays within permission. | P1:pp8–9, interruption table. B01/V06 for enforced terminal control. No hidden reasoning disclosure implied. |
| B09 / P2 | **Invalidate dependent plans after changes:** show stale/unnecessary work instead of resuming old assumptions. The offline-to-online example is not a teerex network requirement. | P1:p9, interruption conclusion. B01/B02 and dependency links. |
| B10 / P2 | **Compact shared knowledge view:** established, suspected, trying, needs-operator; visibly provisional suspicions, not internal-monologue feed. Terminal rendering may suffice. | P1:p9, shared-view section. B05/B06. |
| B11 / P2 | **Evidence navigation and contradictions:** link claims to commands/output/diffs/observations; expose contradictory evidence; preserve what a check actually establishes. A successful command is not feature correctness. | P1:p9, shared-view conclusion. B05/B06/B10; no automatic truth guarantee. |
| B12 / P2 | **Informed questions at checkpoints:** explain options, tradeoffs, recommendation, blocked dependency; batch questions and continue useful independent work. | P1:pp9–10, homework-before-question section. B01/B09; aligns with D08. |
| B13 / P2 | **Attention budget:** operator sets interruption policy for security, irreversible actions, or decisions blocking all useful work; record other issues and continue within scope. Example hour is not fixed default. | P1:p10, attention-budget section. B01/B08/V08. |
| B14 / P2 | **Justify interruption:** why now, what settings/prior decisions checked, default if no response, and useful work continuing elsewhere. | P1:p10, interruption-explanation fields. B12/B13/dependency state. |
| B15 / P2 | **Handoff record:** goal, current state, changes, evidence, risks, exact next action, undo path. Produce from available work state rather than make the operator reconstruct a transcript. | P1:pp10–11, handoff section. B01/B05/B06; C16 for terminal control. |
| B16 / P2 | **Bidirectional evidence handoff:** accept a human-run experiment and its evidence; continue without needless repetition or treating an unexplained conclusion as authority. | P1:p11, handoff continuation. B05/B15/provenance rules. |
| B17 / P2 | **Counterfactual ledger:** important alternatives deliberately not taken, reason, revisit condition; avoid selling rejected choices back later. Queue/parser/test examples are not tasks. | P1:p11, counterfactual section. B06; can work without automatic memory. |
| B18 / P3 | **Evaluate one continuity slice:** outcome/boundaries/interruption contract; one isolated environment; experiment evidence; persistent choices/rejections; pause/inspect/takeover; reviewable diff, verification, caveats. Proposed layers: task/evidence state, permission/execution broker, isolated workspaces/terminals. | P1:pp11–12, first-build proposal. B01/B03/B05/B08/B17/V06–V08. Aggregate, not duplicate platform tasks. |

## Detailed Phase 3 subrequirements: C candidates

All originate in P2's assistant answer. Proposed operation names, pseudocode, and module filenames are not claimed Rex built-ins or final teerex architecture.

| ID / proposed priority | Actionable candidate and retained subrequirements | PDF locator / dependencies |
| --- | --- | --- |
| C01 / P1 | **Bounded attributed observation:** one request with explicit server/session/block target, not an unattributed screen. | P2:p2, observation packet. V02/V03/V08. |
| C02 / P1 | **Raw process/directory/status provenance:** foreground-process observation and last terminal-reported directory; not independently verified directory of every program. | P2:p2, packet and following paragraph. C01/V03. |
| C03 / P1 | **Separate deltas from interpretation:** screen/process change flags plus proposed activity/phase/confidence distinct from facts. Avoid rereading a whole screen for trivial progress increments. | P2:p2, packet/conclusion. C01/C02; C21/C22 optional later. |
| C04 / P1 | **Ownership/evidence attribution:** snapshot/observation identity, controller, lease metadata. These fields belong to the proposed layer; only claim enforcement after verification. | P2:p2, ownership/evidence fields and attribution. C01/V06/V08. |
| C05 / P0 gate, P2 feature | **Guard interactive operations:** exact target, foreground program, expected prompt/state, ownership; postcondition/deadline; mismatch stops and captures. Preserve the precheck/write race limitation. | P2:pp2–3, guarded-gesture section. C01–C04/V06/V08; not atomic through client checks alone. |
| C06 / P1 | **Noninteractive argv execution:** captured output/process handles rather than simulated typing when no terminal interaction is needed. | P2:p3, execution paragraph. V05/V08. |
| C07 / P0 research | **Atomic cooperation where needed:** verify server-side conditional writes/application cooperation; consider focused upstream capability request. Lua alone cannot remove the observe/write race. | P2:p3, final paragraph. V06; independent of client language. |
| C08 / P1 | **Local deterministic loops:** run build/process, consume output, detect completion, enforce deadline, capture failure, return one structured result instead of repeated model wait/inspect turns. Keep interpretation/decisions outside the loop. | P2:pp3–4, Lua reflexes. V05/B05; Lua is historical proposal, not final language requirement. |
| C09 / P1 subset, P2 remainder | **Evaluate all six named actions separately:** `run_and_collect`, `wait_for_program_status`, `observe_until_changed`, `capture_on_exit`, `verify_then_write`, `cancel_and_collect`. Implement only a selected subset; input safety differs from output collection. | P2:p4, opening action list. C08/V03/V05; V06 for input. Proposed names only. |
| C10 / P1 | **Buffer partial streaming chunks:** preserve split lines rather than interpret each callback as a complete message. Validate split boundaries with nontrivial output. | P2:p4, first implementation detail. C08/V05. |
| C11 / P1 | **Own subprocess lifetime:** verify action/handler/timer/script lifetime and deliberate detachment/supervision; do not accidentally kill work when a short action returns. Evaluate a supervisor rather than mandate a daemon. | P2:p4, second implementation detail. C08/V05. |
| C12 / P2 | **Offstage workspace:** addressable blocks outside layouts for checks/reproductions/builds/experiments; distinguish detach from close. Example jobs are uses, not four required cartridges. | P2:p4, offstage section. V03/V05/V07. |
| C13 / P2 | **Offstage registry:** purpose, owner, deadline, cleanup rule for every hidden block; prevent invisible resource waste. | P2:p4, registry sentence. C12/B04-style bounds. |
| C14 / P2 | **Intentional presentation:** offer relevant block with a reason; verify move/float/label/focus operations; preserve the human layout rather than continually rearrange panes. | P2:p4, visibility/presentation passages. C12/C13/V03/V07. |
| C15 / P0 gate | **Visibility is not isolation:** use a separate verified filesystem/network/credential boundary when sandboxing is required. | P2:p4, closing paragraph. V07/V08/B03; not a second sandbox implementation. |
| C16 / P0 gate, P2 feature | **Human/agent clutch:** key-bound take-control action invalidates queued gestures but preserves running processes; separate hand-back action; verified session/block/client/origin context. | P2:p5, clutch section. V03/V06/B08. Stopping input is not killing work. |
| C17 / P0 research | **Server-enforced ownership:** human input immediately revokes agent lease; without enforcement, label it a convention, not protection. | P2:p5, native-capability request. V06/C07; upstream-dependent, not promised. |
| C18 / P3 | **Verified maneuver library:** recognizable start, expected transitions, version/compatibility domain, explicit stop before consequential action, replay test. Reuse verified parts, not blind macros. | P2:p5, maneuver section. C05/C07/C17/V08; sample release publishing not authorized. |
| C19 / P3 | **Replay tests observer:** headless libghostty state from supported captured bytes tests state recognizers. | P2:pp5–6, first test. V04/V09; C18 or independent observer fixtures. |
| C20 / P3 | **Live disposable tests verify actions:** separately test whether input sequence still works; recording cannot prove future application responses or reproduce a machine. | P2:p6, second test; P1:p3, replay boundary. C18/C19/V07/V08. |
| C21 / P2 | **Perception cache:** latest normalized/previous screens, meaningful text deltas, process/status changes, last stable observation, known phase; keep original evidence. | P2:p6, cache fields. C01–C03/V08; bounded retention. |
| C22 / P2 | **Filter cosmetic churn:** suppress spinner/elapsed-time updates; deliver errors, exits, prompts, reported phase changes; retain raw evidence and test both cosmetic and meaningful changes. | P2:p6, suppression example. C21. |
| C23 / P1 baseline, P3 bytes | **Selective supported reads first:** screen/process/program status; byte interpretation only after supported capture path and real need. No imaginary raw-output subscription. | P2:p6, capture-path paragraph. V03/V04/V09. |
| C24 / P1 | **Distinct terminal conditions:** stable screen, idle process, completed command, awaiting input. Quiet output is not completion. | P2:p6, final distinction. V03/V05/C08/C21. |
| C25 / P0 | **Discover installed API descriptions:** use connected server schemas/examples rather than assume a hand-written integration remains correct. | P2:p7, discovery section. V02; first-stream gate. |
| C26 / P1 | **Narrow allowed-method adapter:** validate calls against real schemas; small precise tools instead of giant unrestricted client. Generation is one proposal; small direct adapter may suffice. No literal ten-tool requirement. | P2:p7, adapter paragraph. C25/V08. |
| C27 / P1 | **Version invalidation:** retain server/schema identity and invalidate/revalidate adapter on server changes rather than issue stale calls. | P2:p7, adapter paragraph. C25/C26. |
| C28 / P0 | **Capability is not permission:** discovered API availability does not authorize agent use; explicit policy boundary remains. | P2:p7, policy paragraph. V08/A10/C26. |
| C29 / P2 design option | **Three-module proposal:** `dexterity_observe.lua` for observations, `dexterity_supervisor.lua` for loops/lifetimes, `dexterity_actions.lua` for controls/guarded operations. Preserve responsibilities, not mandatory filenames/Lua-only design. | P2:p7, first-build module list. C01/C08/C16/D06; choose a slice first. |
| C30 / P2 design option | **Six-operation vocabulary:** `observe(target)`, `run(argv, cwd, limits)`, `gesture(target, precondition, input, postcondition)`, `watch(target, condition, deadline)`, `present(target, reason)`, `yield(target)`. Optional proposed interface; may be smaller. | P2:p7, tool list. C01/C05/C06/C08/C14/C16/D03/D04. |
| C31 / P1 staged validation | **One failing CLI acceptance workflow:** bounded offstage experiments, meaningful-change notices, respect takeover immediately, exact-run evidence. Validate supported subset first; explicitly record server-enforcement/isolation limits. | P2:p7, acceptance paragraph. V11/selected C items/V06/V07. |
| C32 / P1 | **Measure dexterity:** fewer model round trips/operation and interruptions/task without more unverified/misdirected inputs. Need baseline/workload before claiming improvement. | P2:pp7–8, three measures. V12/C31; no measured result in source. |

## Conceptual deduplication preserves different utilities

- **Evidence core:** B05's experiment record can support A08/A09, A12, B11/B15/B16, and C31. That does not require identical retention or capture mechanisms, nor merge receipts with continuous recording.
- **Continuity:** A01/A02 recover an investigation; B06/B07 remember causal decisions; B17 records rejected paths. They can share provenance but are not the same feature.
- **Authority:** A10/A11, B01/B04/B08, C05/C15–C17/C28 share V06–V08. One reviewed boundary should avoid contradictory ownership rules; every utility need not install a full broker/runtime.
- **Observation:** C01–C04 supply facts; C21/C22 cache/filter them; C19 replays bytes to test recognition. Supported reads do not require raw capture or libghostty.
- **Execution:** B03/B04 specify experiment isolation/lifecycle; C08–C11 specify terminal/process control. Offstage blocks C12–C14 change visibility, not isolation.
- **Aggregate proposals:** B18, C29, and C30 recap composition/interface options. Their child capabilities are listed once, not counted again as mandatory platform tasks.

## Conflicts, rejected approaches, and examples stay explicit

| Issue | Evidence and disposition |
| --- | --- |
| Three first-build recommendations | P1:p5 favors park/resume; P1:pp11–12 a continuity slice; P2:p7 three dexterity modules. All are assistant picks. Choose one useful slice after common capability checks, not three foundations. |
| Refocusing versus abandonment | U04/P2:p1 requests concrete machinery; assistant acknowledges abstraction. This does not establish Joshua abandoned memory/handoff or approved Dexterity. No named user-abandoned cartridge is evidenced. |
| Lua versus Zig | P2:p7 proposes Lua modules; current D06 tentatively prefers minimal Zig CLI. Verify hosted-Lua/external-client responsibilities; neither requires rewriting Rex or embedding libghostty. |
| Optional headless library versus assumed plugin | P1:p2 distinguishes automation from internal SDK; p5 recommends Rex first unless replay/headless/custom UI is needed. Keep libghostty optional and graphical/internal contracts unassumed. |
| Cooperative guard versus protection | P2:pp3, 5 names non-atomic writes and unenforced ownership. These are safety limits, not minor implementation details; V06 gates guarantees. |
| Hidden work versus sandbox | P2:p4 explicitly separates offstage blocks from filesystem/network/credential isolation. Verify each separately. |
| Assistant cautions/rejected approaches | P1:p2 defers automatic summarization; p3 requires local opt-in instrumentation; P2:pp5–6 rejects blind macros and conflating replay/live tests. Preserve if related utility is selected; these are not Joshua's recorded rejections. |
| Weak success evidence | P1:p5 rejects screenshot-as-proof; p9 scopes claims; P2:p6 separates quiet/stable/idle/completed/input-waiting. Use actual checks and semantic state. |
| Conventional applications | P1:p1 acknowledges persistent workspaces, remote access, embedded terminals, agent dashboards; p6 rejects dashboard-only runtime framing. Not adopted tasks or permanent bans. D07 separately excludes initial VPS/Linux work. |
| Full runtime/installer scope | D02's eventual cartridges do not authorize a package manager/installer or mandatory broker. B18 is an assistant architecture option, not required platform scope. |
| Illustrative application tasks | Payments/retries, pooling/caching, polling choices, offline changes, queue/parser/test choices, sample session IDs/paths, progress counters, release/publish selector demonstrate shapes/hazards (P1:pp2, 6–11; P2:pp2–5). They are not teerex fixes, migrations, deployment tasks, or real customer records. |
| Non-actionable passages | Subjective experience (P2:p1), separators/pagination, closing metaphors, and bibliographies (P1:p12/P2:p8) do not create features. References are historical research pointers, not verified capabilities. |

## Secondary ownership view: proposed parallel async streams

These are future owner packages, **not the three original phases and not newly started threads**. Their R/N/M boundaries now follow the phase review and separate H01–H08 handoff set. Roles are proposed, not assigned people. Research/drafts can overlap; implementation needs a selected contract and reviewed authority boundary. One integration owner accepts shared contract changes so parallel owners do not invent incompatible IDs/results/leases.

| Stream / owner role | Exclusive scope | Dependencies / reviewable exit |
| --- | --- | --- |
| S0 — existing repository preservation owner | Integrate derived inventory/provenance into separate repo checkout; preserve proposal labels/public-private split. No cartridge implementation. | This package. Review derived material before public commit; keep raw PDFs/private manifest out by default. |
| S1 — Rex observation utility owner | **R:** Phase 3 #1/#8, C01–C04/C23/C25–C28; V02/V03. Own the bounded observation packet and only its installed-method bindings, not a general capability framework or supervisor/input code. | Installed Mac/Rex access, V08 privacy baseline. Attributed bounded result with supported field semantics and version identity; terse human and structured agent output describe the same facts. No keystrokes. |
| S2 — non-Rex evidence/continuity owner | **N:** B05/B06/B15/B17 and the H01 record portions of A01/A02. Own manually supplied record examples/provenance/tradeoff note; no Rex capture/navigation/adapter/supervisor edits. | Can start independently if selected. Small usable evidence record with exact-run identity/scope/limits and clear optional versus required fields. Not a prerequisite evidence platform for S1/S4. |
| S3 — safety/authority research owner | V06–V08/C05/C07/C15–C17/C28. Own enforcement/limitations note and denial/race scenarios, not mutation code. | Docs initially; consume S1 captures rather than concurrently control the same terminal. Enforced/cooperative distinction, takeover/process preservation, credential/isolation boundary, focused upstream gap only if needed. |
| S4 — Rex deterministic execution owner | **R with N support code:** Phase 3 #3, V05/C06/C08–C11/C24. Own process/output/lifetime contract and any selected run-and-collect slice; consume shared contracts rather than edit concurrently. | Selected Rex method bindings, V08; agree minimal exact-run fields without requiring S2's generic runtime. argv/cwd/limits/result, chunk boundaries, deadlines, lifetime, cancel/cleanup, failure/success evidence. Can overlap continuing S3 research. |
| S5 — non-Rex capture/replay feasibility owner, optional later | **N core / M integration:** H03, V04/V09/A06–A08/C18–C20. Own feasibility/compatibility/cost note; no new terminal or S1/S4 Rex code. | Selected use case and evidence existing reads are insufficient. Supported path or explicit gap; replay/live distinction, embedding/license/resource cost. Not prerequisite for S1–S4. |
| S6 — cartridge lifecycle/UX owner, when relevant | D02 and chosen utility's independent use/remove/all-together boundary; human/agent UX proposal only. No installer or renderer implementation. | First utility selected and S1 contract known. One reversible proposal with concrete UX/DX tradeoffs; no broad upfront architecture questionnaire. |

S1, S2, and S3 can proceed asynchronously with independent outputs if authorized. S4 follows capability capture; S5 and S6 are conditional. These streams are ranked by dependency rather than a promise to run all of them.

### Exit checks for Phase 3 #1's bounded observation utility

This is S1's implementation-neutral review contract for the original terminal proprioception packet, not a replacement phase or detached discovery effort. On Joshua's M5 MacBook, exercise one read-only, target-attributed observation with bounded data and honest provenance; use Phase 3 #8 only to establish the methods/fields it needs. Zig CLI remains the tentative preference; decide the Lua/external boundary from evidence rather than historical module filenames.

Proposed exit checks:

- [ ] Capture installed client/server identity and discovery results; record unavailable methods rather than assume support.
- [ ] Observe one selected terminal with stable target attribution, evidence identity, and directory/process/status provenance.
- [ ] Bound output/capture privacy; no hidden general activity recorder or external export.
- [ ] Do not equate quiet output with completion; separate derived interpretations from observed fields.
- [ ] Human/machine results express the same facts without requiring a console or renderer.
- [ ] Exclude live input, broad permissions, supervisor, installer, replay engine, Linux/VPS deployment, or monolithic runtime from this first stream.

No implementation occurred during transcript analysis. The phase review recommends run-and-collect C06/C08–C11 next, then manual park/resume A01/A02 as an adjacent personal utility. These named original utilities, not completion of every stream or every possible capability check, determine the scope of further Rex work.

## Page-by-page coverage ledger

This accounts for every substantive PDF section, including intentional non-actions. Repeated mentions map to existing IDs; examples do not become domain tasks.

| PDF passage | Inventory coverage |
| --- | --- |
| P1:p1, first question/answer | U01/V01; language uncertainty preserved. |
| P1:pp1–2, opportunity question and two entry points | U02/V02–V04/V09/V10; automation/library versus internal SDK; conventional applications acknowledged. |
| P1:p2, abandoned-thought section | A01/A02; manual hypothesis/next experiment, capture and resume ordering. |
| P1:pp2–3, friction detector | A03–A05/V04/V08; all four pattern examples, periodic proposal, explicit instrumentation and opt-in. |
| P1:p3, support evidence/compatibility lab | A06/A07/V09; capture metadata, width/resize/Unicode/errors/progress/confirmation checks, display-versus-machine boundary. |
| P1:p4, flight recorder | A08/A09; bounded retention, trigger bundle, selective success comparison and one-workflow scope. |
| P1:p4, least-authority assistant | A10/A11/V08; all five authority levels and untrusted/redacted content. |
| P1:p5, shipping receipt | A12; explicit results, identity/output/skips/caveat, optional customer use, screenshot limitation. |
| P1:p5, first-build recommendation | A01/A02; local park/resume steps, reasoning-value hypothesis, Rex-first/libghostty-optional. |
| P1:p6, user prompt/runtime framing | U03; suggestions labeled, no dashboard-only or literal agent-joy feature inferred. |
| P1:pp6–7, task contract | B01/B02; field groups, collaborative edits/contradictions; payment example not requirements. |
| P1:p7, experiments | B03–B05; independent environment, all result fields and lifecycle requests. |
| P1:p8, causal memory | B06/B07; source/scope/type/invalidator/confirmation, revisit and expiration. Polling example not decision. |
| P1:pp8–9, interruptions | B08/B09; all five controls, stale-assumption/dependent-plan invalidation. |
| P1:p9, shared view | B10/B11; four categories, claim/evidence links, contradictions and evidence scope. |
| P1:pp9–10, informed questions | B12; options/tradeoffs/recommendation/dependency, batching and continued unblocked work. |
| P1:p10, attention budget | B13/B14; policy, why now/checked/default explanation. |
| P1:pp10–11, handoff | B15/B16; seven fields and bidirectional evidence. |
| P1:p11, counterfactual ledger | B17; rejections/revisit condition; queue/parser/test examples excluded as domain work. |
| P1:pp11–12, first slice and architecture | B18; six slice elements and layer relationships; aggregate proposal rather than duplicate platform commitment. |
| P1:p12, bibliography | Historical research pointers only; not 25 verified product facts or tasks. |
| P2:p1, user prompt/stack split | U04/V02/V03/V09; concrete refocusing and conditional headless interpretation. Philosophy aside excluded. |
| P2:p2, observation packet/start of gesture | C01–C05; all target/observed/interpretation/ownership/evidence groups, directory caveat, bounded delta request. |
| P2:p3, gesture/execution/local reflexes | C05–C08; checks, timeout, mismatch, postcondition, argv preference, non-atomic limitation, local deterministic waits. |
| P2:p4, action list/lifetime/offstage | C09–C15; all six action names, chunks, lifetime, visible/offstage uses, registry/presentation and non-sandbox limit. |
| P2:p5, clutch/maneuver | C16–C19; take/return control, queued gestures/process preservation, server enforcement, maneuver validity and consequential stop. |
| P2:p6, tests/cache/capture/state distinction | C19–C24; observer/live split, all cache fields and meaningful/cosmetic examples, raw-capture gap, four different conditions. |
| P2:p7, discovery/first build/acceptance | C25–C32; schemas/adapter/version/policy, three modules/six operations, exact-run acceptance and first metric. |
| P2:p8, metrics/recap/references | C32/V12; remaining metrics and guarded-operation recap. Fifteen references are research pointers, not independently verified capabilities. |

## Publication and delivery boundaries

This paraphrased inventory is intended for repository review. It contains source filenames/hashes/page locators but no private attachment URLs, verbatim transcript blocks, credentials, or actual customer records. This analysis found no apparent credentials/customer records in the PDFs, but that is not authorization to publish raw sources or a guarantee against all personal/confidential material.

Raw PDFs, extracted page text, and the private handoff manifest stay private by default. Markdown attachments are excluded from this package and should not be preserved as authoritative transcript sources. Review the derived text against repository direction/publication policy before committing or pushing it.

No repository checkout was cloned/edited here; no commit, push, cartridge, installer, or API probe was created. The existing repository thread owns preservation. Remaining product decisions are the first user-facing utility, Zig-versus-hosted-Lua boundary, supportable input guarantees, and later capture/packaging choices when relevant, not an upfront questionnaire.
