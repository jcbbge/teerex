# agent-core seat/inbox/ask cutover — gated source patch

Baseline inspected: `jcbbge/agent-core-public` commit **c26bcfc0e87f82a78ce7993a97bd63033ca131fd**. This is a source migration package, **not authorization to operate m5/hive/m1, change a login shell, remove installed links, or restart a server**. Preserve alpha.4 and existing history. The accompanying `agent-core-delete-stopgaps.patch` is deliberately **not applied**: apply only after the combined cutover gates below, not merely because a teerex branch compiles.

## What has parity and what deliberately changes

Actual original `agent-ask` was executed in a disposable directory with a capture-only `agent-send` fixture. Actual `agent-inbox.fold` was executed against its emitted decision/resolution. Confirmed complete ask/context/recommendation, >=2 options with independent gain/loss fields, pinning, explicit answer resolution, and missing-context refusal. New CLI tests exercise the same behaviors plus stricter validation, bounded storage, exact tuple routing, source provenance, and unchanged operator input on real disposable Rex. The old code's unbounded log, UUID-only routing, automatic active-pane registration, fallback splits, resize retries, implicit grey-draft clearing/restoration and label-based viewer lookup are **not compatibility promises**.

| Old stopgap | Replacement (full explicit form) | Acceptance evidence / boundary |
| --- | --- | --- |
| `agent-seat` marker creation | `teerex boards seat register --store ABS --host HOST_ID --socket ABS --session ID --block ID --owner operator` | Exact-address durable registration tested. Does not infer active pane, open a viewer automatically, inspect authorization, or auto-run on login. |
| `agent-seat` viewer geometry | `teerex surfaces open ... --layout tiled|float|tab ... -- ABS_TEEREX boards inbox ...` | Public surfaces composition ran actual visible pane programs and geometry readback. Choose exactly one requested layout; no fallback/retry. |
| `agent-inbox` | `teerex boards inbox --store ABS --host HOST_ID --socket ABS --session ID --block ID` | Full card, empty, resolved,40/72-column terminal HTML captures inspected; foreground refresh tested against actual Rex. No hidden sender filters, no unbounded log. |
| `agent-ask ... --title/--ask/...` | `teerex boards ask [same store/target] --from NAME --card-file ABS|-` | Typed strict JSON card in README; all fields/gain/loss/option count tested. Caller supplies ID explicitly, with duplicate retained IDs refused rather than overwritten. |
| `agent-ask ... --resolve ID --answer TEXT` | `teerex boards ask [same store/target] --from operator --resolve ID --answer TEXT` | Unknown/duplicate resolutions refuse; full answer retained. Does not execute choice or automatically reply to worker. |
| `agent-send` seat branch | Root `teerex send --store ABS --host HOST_ID --socket ABS --session ID --block ID --from NAME --message-file ABS|-` | Integrator-owned root routing calls tryRoute before paste; failures refuse. Leaf raw-input fixture receives0 bytes and displayed draft stays intact. Combined root tests are integrator-owned. |
| UUID-only `.inbox`/`.log` files | Explicit private board store + authoritative `state inspect` | No guessed-address or silent bulk import. Existing logs remain private until reviewed/replayed explicitly. |
| Old seat IDs after restore | `state remap-preview`, then deliberate `remap-apply --generation N --reason TEXT` | Exact mapping, collision/generation refusal, card preservation tested. Recovery does not auto-apply. |

A resolved card remains retained until explicit inbox clear; it is no longer pinned. Native agent-terminal sends retain whole-paste/Enter ACK semantics, not a global atomicity, consumption, prompt-safety, or draft-preservation guarantee. `agent-send`'s guard must not be preserved as a misleading safety promise. Named-host command execution uses the shared root config, not the old search-local-then-m5 fallback.

## Required cutover order (integrator/operator owns acceptance)

1. Build the exact combined alpha.5 source and run the public boards, native send, root named-host dispatch, surfaces and agents suites on disposable supported Mac/Linux. Confirm help and Python3.9+ prerequisite in packaging. Verify one root send receipt, registered stdin deadlines/signals, and unregistered stdin forwarded exactly once into a real raw PTY.
2. Supply a private shared host config for **each intended m5/hive/m1 name**, pinned binaries, explicit command-host store location, exact full addresses, and permissions. The source tests did not contact those private machines; this package does not certify them.
3. Review old log content privately. Register each intended seat from its authoritative address, replay only reviewed ordinary text/complete typed cards with deliberate IDs, and reconcile already-resolved records. There is no automatic import of arbitrary malformed lines, forged answers, hidden proof/ACK senders, or UUID-only host ambiguity. Keep originals until cutover acceptance; don't erase logs as part of code removal.
4. Replace all active source callers of the three stopgaps and the seat branch of send. The discovered references include `primitives/rules/agent-messaging/RULE.md`, `primitives/directives/global/DIRECTIVE.md`, `primitives/directives/estate/DIRECTIVE.md`, `primitives/skills/rex/SKILL.md`, `rex/init.lua`, relay sender/relay documentation, and tests. Launch/ACK/stop-alert and shared `agent-send` replacements are owned by the integrator/agents worker, not independently deleted by this leaf. Old `rex/PLAN.md` and `rex/INSTALL.md` should be explicitly historical, not silently re-described as alpha.5 support. Login-shell `agent-seat` invocation is private setup outside the public source; its owner must replace it only after acceptance. No source label/host guessing may fill that missing configuration.
5. Update `rex/tests/run.sh`'s syntax inventory/old inbox fixture along with the consolidated source migration; it currently names agent-seat/agent-inbox and accepts an incomplete legacy card. Replace that fixture with the actual combined teerex typed-card contract, not a mock claiming old CLI parity. Coordinate root/shared migration first so deletion does not break a runnable intermediate state.
6. Only after all callers/tests use the accepted combined CLI, run `git apply --check` on the deletion patch, review exactly those3 removed stopgap files, then apply in agent-core. Remove installed links only under separate operator authorization. Delete neither private logs nor state. Retain source history for rollback and document the exact accepted version.

## Source patch provenance and verification

The patch deletes only:

- `primitives/tools/agent-messaging/agent-seat`
- `primitives/tools/agent-messaging/agent-inbox`
- `primitives/tools/agent-messaging/agent-ask`

`git apply --check` passed against the exact baseline in a disposable clone. It is a **post-acceptance deletion patch**, not a complete standalone agent-core upgrade: shared caller/rules/test migration must land together. `agent-send`, `teerex-target`, launch/stop hooks, palette and restart scripts are intentionally not removed by this leaf. This explicit gate prevents premature deletion while the integrator assembles the larger alpha.5 operating layer.

The new source remains under `items/boards/**`; shared CLI/build/transport/packaging and all existing send edits are integrator-owned. No private-machine commands, installs, restarts, hidden daemons, release publication, or deployment ran here. No legacy private data was cleared.

### License for the source reproduced in the deletion patch

The deletion-only patch reproduces MIT-licensed agent-core source at the commit named above. Its notice follows; this does not select a license for the rest of teerex.

MIT License

Copyright (c) 2026 Josh Gantt

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
