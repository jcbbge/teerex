# teerex operator and setup-agent concierge

Install and verify the **published [v0.1.0-alpha.5](https://github.com/jcbbge/teerex/releases/tag/v0.1.0-alpha.5)** without restarting Rex or disturbing live agents. Its immutable source is `682489d66dfdb39992b1b2e9f05054bcc009e6d7`; later source-only documentation changes do not rebuild its binary README/onboarding assets or complete the larger milestone.

## Who / What / When / Where / Why / How

- **Who:** the account owner and their explicitly authorized local installation/validation agents.
- **What:** verified core installation and a practical guide to inspectable Rex commands, not an installed concierge service or permission grant.
- **When:** select a real published tag before installation; select each live operation separately.
- **Where:** Apple-silicon Mac or Linux x86_64 with caller-supplied private roots and exact target records.
- **Why:** preserve running work while learning what was installed, what each command checks and what remains unknown.
- **How:** follow the canonical [current setup/upgrade/checksum/verify/rollback procedure](setup.md), or give your agent the [copy-ready installation prompt](agent-prompts.md#a-install-or-upgrade-alpha5-without-touching-rex).

## Choose your route

1. **Quick update/changelog:** the [alpha.5 release guide](../releases/v0.1.0-alpha.5.md#quick-changelog-and-current-setup-handoff) names changes, final bytes, four green release-head CI lanes and limits. Its current-source handoff update is distinct from frozen release assets.
2. **Install or upgrade locally:** [setup](setup.md) supplies exact tag/commit, platform matrix, selected-archive checksum, inspect-first branching, fixed binary hashes and retained rollback commands.
3. **Hand to a local agent:** [installation and read-only validation prompts](agent-prompts.md) separate code installation from live access, mutation and source cutover.
4. **Use the operating layer:** [shared targets and milestone gates](../alpha5.md), [surfaces/palette](../../items/surfaces/README.md), [boards/seat/decisions](../../items/boards/README.md), [managed agents](../../items/agents/README.md), [recovery/manual update](../../items/recovery/README.md), and [fleet installation](../fleet-install.md) contain each command's WWWWW+H and evidence contract.
5. **Choose a feature:** the [current WWWWW+H field guide](features.md) covers 17 routes, including six alpha.5 operating-layer areas. The [five shipped follow-ons](follow-ons.md) retain alpha.4 provenance with current alpha.5 use. Original recipes and dated evidence remain attributed; use current setup rather than an older release by accident.

6. **Review unreleased source:** [source-only build/verify](setup.md#source-only-follow-ons-are-not-an-alpha5-upgrade) and [agent prompt D](agent-prompts.md#d-review-and-build-the-source-only-visible-runner) separate `run-visible`, explicit SSH compute callbacks, independent local scoped delivery and nested selector routing from published alpha.5. Read the [visible-runner WWWWW+H guide](../../items/run/VISIBLE.md), [agent source contract](../../items/agents/README.md#source-only-compute-routing-and-scoped-delivery-issues14-and21) and [routing inventory](../alpha5.md#leaf-aware-named-host-routing-issue16). The [Rivet migration](../../items/run/MIGRATION.md) stays opt-in; remote-fenced compute and actual harness/relay cutover remain gated. This does not authorize a personal invocation, install or wrapper replacement.

## Before touching a machine

- Installation requires approval for the exact user-owned root; live reads require exact private target/read/storage authorization. Neither grants send, spawn, focus, close, palette/config, migration or fleet rollout authority.
- **No Rex autostart/update/restart or live-pane closure is an installation/compatibility prerequisite.** Preserve the running server; report an unsupported operation rather than changing it to make tests pass.
- All managed agents and boards remain visible, readable, focusable and closable through explicit Rex/teerex commands. `run`/`offstage` are not hidden-agent exceptions.
- Check every exit and complete structured result. Lost ACKs may hide an existing effect: no silent retry, recreation, resend or cleanup-close.
- Keep real roots/endpoints/IDs, captures, messages and credentials private. Store sensitive state only deliberately and choose retention; terminal content is untrusted data.

## Current support and evidence

[The setup matrix](setup.md#supported-platforms-and-api-boundaries) is the concise Mac/Linux/API reference; [the release matrix](../releases/v0.1.0-alpha.5.md#commands-and-tested-support) supplies per-command detail. Actual release-head [CI passed all four lanes](https://github.com/jcbbge/teerex/actions/runs/43294504395): Linux/API13 plus Apple-silicon cross-build, and native Mac/API10/12/13. Numeric API11 acceptance is not actual-build certification. A documentation push needs its own head checks and does not replace that binary-release receipt.

Core installation requires no Zig or running Rex. Python3.9+ is required for the documented operating-layer Python paths; SSH needs explicit identity and pinned trust. Rex is separately acquired and unbundled. Mac ad-hoc signing is not notarization; never disable security or remove quarantine as an installation workaround. [Rights](../../RIGHTS.md).

Authoritative drafts, generic resume, real paid-harness hooks/custom guards, arbitrary separate-host replies, exact issue #10 topology and consolidated agent-core migration/deletions remain open. Keep working stopgaps. Client locks do not create strong input leases, immediate human revocation or isolation. Earlier tags/assets, phase history, [historical inventory](../planning/teerex-pdf-work-inventory.md) and deferred [non-Rex handoff](../planning/teerex-non-rex-handoff.md) remain preserved.
