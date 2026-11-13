# Teerex asynchronous orchestrator handoff

**Copy the prompt below to the coordinating agent.** It coordinates parallel planning/specification workloads by default; it does not select a proposed feature for implementation. Repository: [jcbbge/teerex](https://github.com/jcbbge/teerex). Required context is public or repository-local; private artifacts and prior conversations are unnecessary.

Joshua approved publishing this package and asked for a handoff to another agent. This publication did not start workers, approve manual park/resume, assign filed issues or authorize outside implementation. When Joshua hands this prompt to an orchestrator, that agent can coordinate the planning workloads described below; later implementation needs its own explicit selected scope.

```text copy Copy Orchestrator Prompt
Coordinate the remaining teerex phased work for Joshua Gantt using parallel asynchronous workloads. Your default deliverable is integrated planning/specification and acceptance-design output, not feature implementation. Do the coordination and integration yourself; workers own bounded, disjoint deliverables.

Repository and required context

Use https://github.com/jcbbge/teerex. In its checkout, read these paths before dispatch:
- docs/roadmap.md: the current phased plan at the top, followed by explicitly preserved historical checkpoints. Old N/I lists are not the active queue.
- docs/planning/teerex-delegation-briefs.md: H01–H08 WWWWW+H scopes, dependencies, acceptance evidence, non-goals and gates.
- docs/planning/teerex-non-rex-handoff.md and docs/planning/teerex-pdf-work-inventory.md: historical group/ID/PDF-page provenance, not blanket implementation approval.
- docs/alpha5.md and the relevant items/*/README.md: supported source contracts and existing migration boundaries.
- docs/cartridges.md and docs/releases/v0.1.0-alpha.5.md: independent payload lifecycle versus frozen release-byte claims.

The latest public main is the source baseline, not an old local checkout, a version string or a private artifact. Inspect existing local edits and fetch the current branch without discarding anyone's work. Record the exact reviewed base commit. Reconcile intervening changes before integration. Do not force-push or overwrite other agents' work. No Amp/private thread access is required; historical private links are optional provenance, not missing task inputs.

Authority and product boundaries

Joshua requested: "ignore the filed issues. im offloading them to other agents" and asked to plan other teerex phases and prepare outside brief/spec/scope work. All filed issues remain externally owned, including ones not listed in the docs. Treat overlap as a dependency; do not reopen, reassign or implement the issue under another phase label. Read accepted public contracts instead of guessing its owner's result.

The proposed product order is manual read-only-first Rex park/resume (U01), minimal cartridge discovery (Q03), explicit Rex evidence attachments (U02), then narrowly selected presentation filtering if measurement justifies it. This is a recommendation, not selection or implementation authorization. Original assistant proposals, historical scores and unchecked boxes are not commissioned features. With no later explicit feature selection, stay in planning/specification and acceptance design.

Outside teerex, H01–H08 authorize preparation of briefs/specs/scopes only. Do not invent a repository, workload, consumer or owner to fill a missing decision. A brief can conclude reuse, defer or do not build. Generic evidence, PTY/replay, security, task runtime, memory, communication policy and processing infrastructure stay outside the Rex product boundary. Teerex still owns its concrete adapters, safety/refusal obligations and product acceptance.

Paired agent-core replacement is teerex product responsibility with an existing external owner; it is not a new H project or a duplicate migration assignment. Keep relay/wrappers/native-owner/inbox/git/fence guards and private restart accounting until real parity and specific cutover approval. The custom Rivet GUI was superseded by Rex as client. A VPS is an eventual rollout destination, not permission to design or alter a live topology.

Strong guarded input/human clutch requires supported host/application enforcement. A fresh observation, native sizing owner, cooperative lock, local lease or saved maneuver does not supply atomic input/revocation. Preserve raw evidence and unknowns; reported status, quiet text, SSH exit and pane closure do not prove completion or descendant death.

Set up ownership before launching

Act as the single integrator. Keep a coordination ledger in docs/planning/workloads/coordination.md, creating it only if absent and extending it if present. Record each workload's existing ID, mode (planning/specification or explicitly approved implementation), authorization source, exact base, worker identifier, owned repository/path set, read-only dependencies, inputs, outputs, acceptance, state and completion route. Distinguish externally owned, proposed, ready, running, blocked, review and integrated work. The ledger tracks execution, not a second product roadmap.

Reserve README.md, docs/roadmap.md, docs/direction.md, docs/planning/teerex-non-rex-handoff.md, docs/planning/teerex-delegation-briefs.md, this prompt and the coordination ledger for your integration edits. Workers do not edit these canonical files concurrently. Reserve source/root/build/config/packaging ownership for the relevant existing owners; this default planning wave has no source edit allowance. Leave .github/workflows/ci.yml and docs/ci.md to the CI owner unless explicitly coordinated otherwise.

Reuse existing matching outputs before creating files. Give every worker one distinct output path and make all other paths read-only. Separate checkouts do not transfer local commits/files automatically: name the repository/base and provide actual commit/patch/file transfer when unpushed state matters. For a shared checkout, use non-overlapping writable paths; do not run conflicting Git checkout/reset/staging operations. Workers return only their scoped patch or exact file path; you integrate it.

Start independent ready work asynchronously

Use your environment's native asynchronous worker/delegation facility. Launch independent ready workers together rather than launching one, waiting for it, then launching the next. Do not claim parallel execution if the facility is unavailable; prepare the same runnable briefs and disclose that limitation. Do not start a new worker for work already running elsewhere, and do not let workers recursively create more workers.

Subject to current ownership and any later Joshua instruction, this is a default PLANNING wave, not a feature build order:
- Q02/C31/C32 acceptance-design worker: own docs/planning/workloads/readiness-acceptance.md. Specify one supported read-only readiness domain and a safe-subset failing-CLI baseline, controls, process/measurement boundaries and remaining unsupported criteria. No runtime suite, personal host or paid-model evaluation is implied.
- Q03 discovery-design worker: own docs/planning/workloads/cartridge-discovery.md. Inspect public CLI/manager contracts and propose the smallest coherent entry plus Q05/Q11 acceptance. Do not implement root dispatch, a GUI, a second manager or change experimental status.
- H01 evidence-spec worker: own docs/planning/workloads/evidence-records.md. Refine the bounded generic record/receipt/handoff contract with sanitized examples and a reuse/no-build alternative. No storage service or Rex capture implementation.
- H07 attention-spec worker: own docs/planning/workloads/attention-policy.md. Compare existing public guidance and propose only missing question/escalation behavior with scenario acceptance. No prompt deployment, agent configuration or model-behavior claims.

These workers can begin from existing contracts independently. H07 may draft against existing evidence fields; optional alignment with H01 follows its accepted report, not a wait before all work starts. Keep H03/H04 gated on a selected workload/threat boundary, H05/H06 on the chosen environment/gap, and H02/H08 on demonstrated recurrence/reuse. Mark missing decisions and finish the useful scope that does not depend on them. Do not fabricate those inputs to launch all eight briefs.

Give each worker a complete brief

Supply Who, What, Why, Where, When and How in full sentences: consumer/owner/reviewer; bounded outcome and mode; recorded reason/source; exact repository/base and writable paths; prerequisites/start trigger; evidence and verification. Include required inputs/outputs, dependencies, explicit non-goals, approval gates and where to send its completion report. State what other workers own and that all other paths are read-only. Include only reachable repository paths/public links, or explicitly supplied approved material.

Choose one completion mechanism supported by your tools: preferably a completion message/event to you, or an asynchronous result handle. Put your actual coordinator route/identifier in the brief before launch; do not leave a placeholder. Ask workers to report completion or a genuine blocker without waiting for you to poll. Do not both request a callback and run a second waiting loop for the same task.

A worker completion report must include:
- Result: exact findings or changed behavior, source references, proposed versus approved status, acceptance evidence and counterexamples.
- Not done: skipped checks, failed checks, limits, assumptions, unresolved inputs and approval gates; do not label partial work complete.
- Where: repository, exact base, branch/commit or patch/file path, owned changed paths and delivery state. Source, branch names and hashes alone do not transfer unpushed files.
- Next: the exact dependency now available, integration action or decision needed, and whether another reply is needed.

For executed checks, include command, decisive output, environment/identities and what the check does not establish. For design-only work, supply an acceptance rubric and say it was not executed. Use synthetic/sanitized examples; no raw transcripts, terminal captures, credentials, private endpoints, private PDFs or proprietary binaries in public outputs. Documentation/API indexing is not proprietary application source and does not imply redistribution rights.

Integrate on completion, not in serial batches

While workers run, reconcile source changes, review existing contracts and prepare link/provenance/scope checks. On each completion, inspect its actual output and evidence, check ownership and authorization, accept or return a specific correction, and release newly ready dependents as soon as their required input is accepted. Do not wait for unrelated workers to finish before releasing a ready dependent. Do not run dependent integration against a worker's unreviewed claim.

One integrator merges canonical documentation and resolves shared interfaces. In particular, H01 owns a selected generic record envelope; H06 or H07 references it rather than designing competing stores/fields. Preserve original A/B/C/H/Q identifiers and physical PDF locators. Keep the historical inventory/validation/research intact; new navigation must label its historical scope instead of rewriting it as shipped work.

Verify relative links/anchors, coverage, scope consistency and absence of private required dependencies. Separate acceptance design from executed runtime evidence; separate source from frozen alpha.5 assets; separate product from acceptance, cutover and machine rollout. Report failures without suppressing checks. Do not promote a cartridge to ready because one subcommand passed or because packaging works.

If a worker is blocked, continue independent authorized work and ask only for the concrete missing decision/input. If no runnable work remains, use the platform's completion event/wait facility for outstanding work rather than polling or sleeping repeatedly. Reassess the ledger when new instructions or completions arrive.

Approval and delivery gates

This handoff is not standing permission to push future work, publish packages/releases, change shared infrastructure, run production writes, delete wrappers/relay/data, install on personal hosts, alter global launchers, close panes or restart Rex. No runner access is authorized. Real harness/private guard/restart sources and actual draft/resume contracts remain explicit missing inputs where applicable. Paid-model evaluations and private-data access need their specific approval. Joshua chooses any outside project/repository and the product license.

If Joshua later explicitly selects a teerex implementation slice, record that narrower authorization and coordinate code ownership before launching implementation workers; outside H work remains specification-only unless separately approved. The current planning-package publication is not that feature selection.

Return one integrated summary with proposed priorities, completed planning outputs, evidence/check failures, external dependencies, unresolved decisions and exact delivery state. Link the canonical repository outputs instead of making the operator reconstruct worker reports. When publication is authorized, reconcile latest main without overwriting other agents, commit only the authorized package, verify the exact public commit/URLs and follow its CI. Otherwise leave reviewed local changes clearly identified and request only the remaining delivery authorization.
```
