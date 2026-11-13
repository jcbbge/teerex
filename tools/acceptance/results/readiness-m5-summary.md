# Safe-subset failing-CLI baseline

Measured binaries (SHA-256): teerex `d621d76177dbe8b31a936bd16c92ce59c6c4b77e1676456aab12646d71cf7d79`; Rex `c7b025c436ff28034589a81a4e697fa325dff8eb19a7f8c0582a18a55fa4dac0`. Supervised fixtures and reference calls use disposable HOME with bytecode writes disabled.

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
| teerex | F1 | 40 | 9 | 9 | 21216 | 146 | 72628 | 485.538 | 37904.0 | 1095.067 / 1024.769 / 1055.953 |
| teerex | F4 | 40 | 9 | 9 | 21209 | 146 | 72586 | 484.348 | 37896.0 | 1079.758 / 1021.711 / 1051.222 |
| reference | F1 | 40 | 6 | 6 | 11193 | 0 | 0 | 228.940 | 35816.0 | 356.568 / 359.278 / 363.570 |
| reference | F4 | 40 | 6 | 6 | 11131 | 0 | 0 | 229.494 | 35848.0 | 358.116 / 360.620 / 370.566 |

- F1: n=40; excluded=rex_server, gui, neighbour_panes, whole_machine_energy
  - wall_ms.cold teerex/reference: 3.0711
  - wall_ms.warm_median teerex/reference: 2.8523
  - wall_ms.warm_p95 teerex/reference: 2.9044
  - calls teerex/reference: 1.5000
  - rex_client_launches teerex/reference: 1.5000
  - stdout_bytes teerex/reference: 1.8955
  - stderr_bytes teerex/reference: unknown (zero reference)
  - cpu_ms teerex/reference: 2.1208
  - maxrss_kib teerex/reference: 1.0583

- F4: n=40; excluded=rex_server, gui, neighbour_panes, whole_machine_energy
  - wall_ms.cold teerex/reference: 3.0151
  - wall_ms.warm_median teerex/reference: 2.8332
  - wall_ms.warm_p95 teerex/reference: 2.8368
  - calls teerex/reference: 1.5000
  - rex_client_launches teerex/reference: 1.5000
  - stdout_bytes teerex/reference: 1.9054
  - stderr_bytes teerex/reference: unknown (zero reference)
  - cpu_ms teerex/reference: 2.1105
  - maxrss_kib teerex/reference: 1.0571

No improvement claim is made unless every B row passed. Pane-side CPU is null when exit-time process evidence was unreadable.
