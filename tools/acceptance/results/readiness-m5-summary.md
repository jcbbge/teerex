# Safe-subset failing-CLI baseline

Measured binaries (SHA-256): teerex `1aef5bb3e96e83f100046e8b7064377788e9483e67ac592863f0174a3bdf40f7`; Rex `c7b025c436ff28034589a81a4e697fa325dff8eb19a7f8c0582a18a55fa4dac0`. These identify the measured pre-U05 workload, independently of current readiness.

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
| teerex | F1 | 40 | 9 | 9 | 21234.5 | 149 | 72586 | 482.663 | 37864.0 | 1059.492 / 1019.659 / 1036.209 |
| teerex | F4 | 40 | 9 | 9 | 21228 | 149 | 72544 | 483.796 | 37808.0 | 1117.197 / 1017.133 / 1049.989 |
| reference | F1 | 40 | 6 | 6 | 11193 | 0 | 0 | 229.059 | 35848.0 | 361.635 / 357.595 / 364.132 |
| reference | F4 | 40 | 6 | 6 | 11131 | 0 | 0 | 229.107 | 35976.0 | 371.314 / 357.402 / 366.360 |

- F1: n=40; excluded=rex_server, gui, neighbour_panes, whole_machine_energy
  - wall_ms.cold teerex/reference: 2.9297
  - wall_ms.warm_median teerex/reference: 2.8514
  - wall_ms.warm_p95 teerex/reference: 2.8457
  - calls teerex/reference: 1.5000
  - rex_client_launches teerex/reference: 1.5000
  - stdout_bytes teerex/reference: 1.8971
  - stderr_bytes teerex/reference: unknown (zero reference)
  - cpu_ms teerex/reference: 2.1072
  - maxrss_kib teerex/reference: 1.0562

- F4: n=40; excluded=rex_server, gui, neighbour_panes, whole_machine_energy
  - wall_ms.cold teerex/reference: 3.0088
  - wall_ms.warm_median teerex/reference: 2.8459
  - wall_ms.warm_p95 teerex/reference: 2.8660
  - calls teerex/reference: 1.5000
  - rex_client_launches teerex/reference: 1.5000
  - stdout_bytes teerex/reference: 1.9071
  - stderr_bytes teerex/reference: unknown (zero reference)
  - cpu_ms teerex/reference: 2.1117
  - maxrss_kib teerex/reference: 1.0509

No improvement claim is made unless every B row passed. Pane-side CPU is null when exit-time process evidence was unreadable.
