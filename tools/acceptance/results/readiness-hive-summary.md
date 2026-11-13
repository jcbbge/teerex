# Safe-subset failing-CLI baseline

Measured binaries (SHA-256): teerex `3b87f6552ac7d55bc93d4f851235a8fdf7b33527a19e2b3fd9560e491fcbd203`; Rex `d09d824f5cadc348c156d3d7579fda5889747c69100c72b607cfd94dfb2e3679`. Supervised fixtures and reference calls use disposable HOME with bytecode writes disabled.

Readiness and task completion are separate. Hidden full text remains unknown.

| Row | Pass | Detail |
| --- | --- | --- |
| B1 | true | F1 real exit3 and full assertion stderr |
| B10 | true | existing run-visible lost-ack and controller-SIGKILL tests executed |
| B11 | true | setsid survivor observed and only its PID killed; same group stopped |
| B12 | true | N1_N6 exact controls; delta= |
| B2 | true | F4 real exit0 differs from F1 |
| B3 | true | F5 status claim and child exit stored separately |
| B4 | true | terminal_program_exit is separate; never substituted |
| B5 | true | known raw prefixes/full files and completeness flags |
| B6 | true | X1 same-pane equal captured prefix; full text unknown |
| B7 | true | F2 deadline/KILL/partial output/absence; quiet sentinel watch deadline |
| B8 | true | INT130 and TERM143 override keep-open and close owned panes |
| B9 | true | cwd/executable/env/FIFO/mismatched baseline refused |
| X2 | true | retained F4 done does not rematch; fresh F5 done is not its exit1 |
| default_close | true | default close independently verified |

Ratios below name the measured quantity; lower is smaller. They are workload-specific, not productivity claims.

Waited-exec CPU includes reaped descendants; RSS is the largest single waited child, not a sum. Wall uses monotonic task time. Rex execs are counted by an argument-free wrapper; wrapper overhead is included. Pane-side CPU is sampled from the started child at exit when readable. Server, GUI, neighbours and energy are excluded.

| Arm | Fixture | n | Calls | Rex execs | stdout bytes | stderr bytes | output-dir bytes | CPU ms | max RSS KiB | Wall cold / median / p95 ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| teerex | F1 | 40 | 9 | 9 | 21046 | 145 | 72408 | 739.834 | 65364.0 | 1094.393 / 1042.588 / 1143.680 |
| teerex | F4 | 40 | 9 | 9 | 21039 | 145 | 72366 | 754.557 | 65364.0 | 965.294 / 1039.784 / 1115.291 |
| reference | F1 | 40 | 6 | 6 | 11185 | 0 | 0 | 417.000 | 65364.0 | 382.033 / 385.282 / 433.057 |
| reference | F4 | 40 | 6 | 6 | 11123 | 0 | 0 | 406.409 | 65364.0 | 409.927 / 374.071 / 442.374 |

- F1: n=40; excluded=rex_server, gui, neighbour_panes, whole_machine_energy
  - wall_ms.cold teerex/reference: 2.8647
  - wall_ms.warm_median teerex/reference: 2.7060
  - wall_ms.warm_p95 teerex/reference: 2.6409
  - calls teerex/reference: 1.5000
  - rex_client_launches teerex/reference: 1.5000
  - stdout_bytes teerex/reference: 1.8816
  - stderr_bytes teerex/reference: unknown (zero reference)
  - cpu_ms teerex/reference: 1.7742
  - maxrss_kib teerex/reference: 1.0000

- F4: n=40; excluded=rex_server, gui, neighbour_panes, whole_machine_energy
  - wall_ms.cold teerex/reference: 2.3548
  - wall_ms.warm_median teerex/reference: 2.7796
  - wall_ms.warm_p95 teerex/reference: 2.5212
  - calls teerex/reference: 1.5000
  - rex_client_launches teerex/reference: 1.5000
  - stdout_bytes teerex/reference: 1.8915
  - stderr_bytes teerex/reference: unknown (zero reference)
  - cpu_ms teerex/reference: 1.8566
  - maxrss_kib teerex/reference: 1.0000

No improvement claim is made unless every B row passed. Pane-side CPU is null when exit-time process evidence was unreadable.
