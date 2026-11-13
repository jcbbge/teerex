# Presentation view measurement

Synthetic disposable Rex only. No personal pane or harness transcript was read.

False suppression: 0.

Ratios below are A2 divided by the named arm; values below 1 are smaller. Calls and bytes are totals over cold plus warm runs. Wall time is warm median command execution time; A0 caller sleep is excluded.

| Event | Reference | Calls | stdout bytes | Warm wall |
|---|---|---:|---:|---:|
| E1 | A0 | 0.0939 | 0.1508 | 2.9278 |
| E1 | A1 | 0.0371 | 0.0370 | 1.1135 |
| E2 | A0 | 0.1041 | 0.1670 | 3.8517 |
| E2 | A1 | 0.0345 | 0.0344 | 0.9159 |
| E3 | A0 | 0.0950 | 0.1522 | 3.0643 |
| E3 | A1 | 0.0367 | 0.0364 | 1.1114 |
| E4 | A0 | 0.1071 | 0.1816 | 3.4192 |
| E4 | A1 | 0.0323 | 0.0342 | 0.8124 |
| E5 | A0 | 0.1103 | 0.1773 | 3.4568 |
| E5 | A1 | 0.0343 | 0.0342 | 0.9274 |
| hidden | A0 | 0.0338 | 0.0537 | 3.4633 |
| hidden | A1 | 1.0000 | 1.0891 | 1.0000 |

The view is opt-in. Ratios do not establish activity or completion. A2 is not better in fields with ratios ≥1. No benefit is claimed if false suppression is nonzero or contract gates fail.

F0/F1 payload ratios and CPU/RSS, launches, false wakes, detection latencies, hidden-tail unknowns and bytes to detect are in report.json. Hidden-tail events remain unknown and are excluded from false suppression because the event is outside acquired text. A3 and the optional agent arm were not run.

Measured source: `06c5061a81b9ca96323231bd17b5e0317b5d1c80`. Binary and driver SHA-256 values are in report.json.

Warm p95 uses nearest rank. The report was reaggregated from committed per-trial counts with the recorded aggregation-driver digest and the exact 1000 ms event-latency bound. Maximum observed event latency: 509.03 ms. View-arm cosmetic false wakes: 0.
