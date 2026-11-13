# Observation terms

This is the shared vocabulary for teerex CLI consumers. Evidence is bounded and
non-atomic; none of these terms assesses whether the operator's task succeeded.

| Term | Exact meaning and public fields | Does not establish |
| --- | --- | --- |
| equal | Comparable values are identical: compare `changed:false`, or `capture.captured_text_changed:false`. | No intermediate change, idle, done. |
| changed | A comparable value differs: `changed:true`, `changed_fields`. | Progress or success. |
| availability changed | Evidence appeared or disappeared: `availability_changed`, `availability_changed_fields`. | Exit, success or stop. |
| unknown | Evidence cannot be compared: `changed:null`, `capture.full_text_changed:null`, `unknown_fields`; replay fact `value:"unknown"`. | Unchanged or false. |
| incomplete | Capture is a bounded prefix: `capture.complete:false`. | Anything about the hidden tail. |
| quiet | No qualifying change before the deadline: watch `outcome:"deadline_exceeded"`, exit 124. | Idle, finished or waiting for input. |
| cosmetic | A chosen, named view declares a difference ignorable. No such view ships today. | Implicitly ignoring progress or spinner changes. |
| reported done | Program's OSC 7501 claim: `status_report_matched`, `status_state`, observation `program_status.data.records[].state`. | Process exit or task success. |
| exited | Immediate child terminated: run-visible `exit_report.exit_code`/`signal`, replay stream `child_exited`. | A status report, vanished pane, or another program's retained `last_exit`. |
| completed | Task completion; replay/run-visible always report `task_completion:"not_assessed"`. | Anything measured by teerex. |
| historical | Read from storage: cache `outcome:"historical_hit"`, `evidence_freshness:"historical_unverified"`. | Fresh acquisition. |

Equal bounded prefixes can have different tails. Their captured text can compare
equal while full text remains unknown. A found positive display fact is true even
in an incomplete prefix; a missing positive fact or any negative fact on that
prefix is unknown. Missing process/status evidence is also unknown.

`replay play` proves byte fidelity and checks independently authored display
facts. `replay live` checks an actual program and filesystem effects. A play pass
never satisfies a live test; neither result establishes task completion.

Measurement records use readiness's existing `report.json.measurements[arm][mode]`
contract. They must name `measured_processes` (roles, identity basis, quantities)
and `sampling_domain` (clock, CPU, RSS, pane-side method, n and warmups). A missing
field invalidates the record. Report improvements only as ratios of named
quantities with the same host, binary hashes and Rex version, and print `n` and
`excluded`. Model turns, interruptions and user errors require the Phase B shim
logs, never byte/call proxies. No separate H08 metrics format or library exists.

Sources: H03/H08 implementation spec §4, public compare/watch/filter-cache and
run-visible contracts in this repository. Executable conformance lives in
`items/replay/test_terms.py`; it reuses public packet builders and private-server
fixtures rather than copying their schemas.
