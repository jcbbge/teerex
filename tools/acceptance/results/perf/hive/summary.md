# Performance qualification: hive

One cold plus 20 warm invocations per workload; no OS cache flush. Native local execution, private API13 server and state. SSH/setup/teardown excluded.

| Workload | Cold ms | Warm p50 ms | Warm p95 ms | Max RSS KiB | >500ms p50 |
|---|---:|---:|---:|---:|---|
| observe | 49.96 | 46.44 | 61.51 | 40784.00 | no |
| watch_to_change | 300.70 | 304.07 | 330.42 | 41468.00 | no |
| send_ignore | 117.26 | 47.27 | 62.66 | 41728.00 | no |
| send_guard | 57.70 | 56.33 | 72.57 | 41996.00 | no |
| send_guard_saved_draft | 2121.31 | 2122.08 | 2141.02 | 42596.00 | yes |
| surfaces_open | 60.72 | 55.94 | 75.84 | 42088.00 | no |
| surfaces_close | 54.44 | 54.42 | 64.24 | 41852.00 | no |
| run_visible_small | 332.56 | 351.42 | 408.37 | 41928.00 | no |
| agents_prune_plan | 90.93 | 78.81 | 104.75 | 23540.00 | no |
| boards_calls | 107.41 | 79.63 | 100.00 | 21572.00 | no |
| cartridges_list | 76.67 | 60.05 | 73.97 | 18320.00 | no |

## Findings

- send_guard_saved_draft: Intentional 1500ms draft quiet window plus 400ms post-submit restoration timer; verified restored synthetic draft. No suggestion/draft content retained in results.

These are the stated fixture workloads, not production-agent productivity, energy, throughput, large registries or remote RTT qualification. Full per-invocation measurements and exact build identity are in report.json.
