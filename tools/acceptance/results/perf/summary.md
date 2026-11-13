# Q11/Q12 qualification on hive and M5

Q11: eight managed-runtime cases passed on each machine, with seven Linux and ten Mac native cartridges. Every normal payload runtime call used the embedded manager. M1 direct byte-parity comparisons and M7 direct-launch/no-lease behavior are explicit counterexamples. Cooperative leases are not Rex input locks, detached-descendant protection or hot unload.

Q12: 11 workloads, each one cold plus 20 warm invocations per host (231 measured calls per host). Cold is first fixture invocation, not an OS cache flush. Source revision, exact core/driver SHA-256, Python/Rex/kernel/architecture, per-call timings, bytes and per-invocation wait4 RSS are in each report. The catalogs were locally reviewed cross-builds from product source 0acdf99 with the then-dirty acceptance work recorded in provenance; no release/catalog installation into personal HOME occurred.

| Highest-latency workload | hive warm p50 ms | M5 warm p50 ms | Cause and scope |
|---|---:|---:|---|
| send_guard_saved_draft | 2122.08 | 2103.45 | Only >500ms finding: 1500ms quiet window plus 400ms restoration timer, with native VT/key calls around them. Receipts measured 1510/1504ms wait and verified restored drafts. |
| run_visible_small | 351.42 | 295.90 | Below 500ms: visible pane placement, Python controller/helper, identity/permit handshake, child exit and verified pane cleanup. The child is the system true executable, so there is no substantive command work. |
| watch_to_change | 304.07 | 286.40 | Below 500ms: includes a controlled 100ms fixture event delay and default 250ms polling. Baseline collection is excluded; this is not zero-delay event transport latency. |

The empty-draft guard path measured 56/23ms; it skips the quiet/restoration timers. The saved-draft latency is intentional current contract behavior, not evidence that all sends take two seconds. No product behavior was changed to improve the measurements.

Limits: local host only, private server/HOME/calls/clutch/registry. SSH transport and resident Rex server CPU/RSS are excluded. Prune uses an empty registry, calls reads at most 32 fixture metadata entries, and cartridge list uses an absent root. Large live registries, remote RTT, energy/throughput, real agent productivity, arbitrary mounts/ACLs and release-wide UX remain unqualified. RSS is the per-invocation maximum from wait4, not aggregate simultaneous memory across the resident server and descendants.

## Failures encountered and corrected

- Initial managed hive run failed its unchanged-HOME assertion because fixture Rex logs were inside that HOME. The disposable server was moved outside the cartridge HOME; both final managed runs passed all eight cases.
- Initial performance smoke failed `KeyError: block_ids`: current surfaces receipts use `created.block_id`. The harness was corrected.
- Initial M5 full run and isolated probe failed `run-visible` exit 1 / `launch_error: [Errno 2] No such file or directory: /bin/true`. The host has its executable elsewhere; the driver now resolves system true. Final full runs passed every invocation.

## Reproduce

```sh
TEEREX_BIN=/absolute/teerex REX_BIN=/absolute/rex python3 tools/cartridges/test_payloads.py --catalog /absolute/native-catalog --managed-runtime --with-rex
python3 tools/acceptance/perf_measure.py --rex /absolute/rex --teerex /absolute/teerex --machine hive-or-m5 --source-revision COMMIT --output OUTPUT --warm-runs 20
```

CI now runs the managed cases in its existing Linux/Mac API13 native-catalog lanes, plus the all-workload zero-warm-run performance smoke. Hosted CI has not been run from this unpushed branch.
