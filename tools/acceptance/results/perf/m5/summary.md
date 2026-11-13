# Performance qualification: m5

One cold plus 20 warm invocations per workload; no OS cache flush. Native local execution, private API13 server and state. SSH/setup/teardown excluded.

| Workload | Cold ms | Warm p50 ms | Warm p95 ms | Max RSS KiB | >500ms p50 |
|---|---:|---:|---:|---:|---|
| observe | 21.01 | 20.91 | 22.34 | 36624.00 | no |
| watch_to_change | 282.90 | 286.40 | 287.60 | 36704.00 | no |
| send_ignore | 44.38 | 20.78 | 24.38 | 37744.00 | no |
| send_guard | 22.63 | 22.62 | 23.60 | 38048.00 | no |
| send_guard_saved_draft | 2088.41 | 2103.45 | 2119.34 | 38448.00 | yes |
| surfaces_open | 59.32 | 32.24 | 33.18 | 38096.00 | no |
| surfaces_close | 22.56 | 22.78 | 23.64 | 37824.00 | no |
| run_visible_small | 437.65 | 295.90 | 329.64 | 38352.00 | no |
| agents_prune_plan | 101.60 | 96.06 | 96.92 | 24352.00 | no |
| boards_calls | 104.27 | 102.60 | 117.84 | 23392.00 | no |
| cartridges_list | 93.90 | 92.61 | 94.98 | 20560.00 | no |

## Findings

- send_guard_saved_draft: Intentional 1500ms draft quiet window plus 400ms post-submit restoration timer; verified restored synthetic draft. No suggestion/draft content retained in results.

These are the stated fixture workloads, not production-agent productivity, energy, throughput, large registries or remote RTT qualification. Full per-invocation measurements and exact build identity are in report.json.
