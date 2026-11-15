# Current Rex utilities

The installed `teerex COMMAND --help` defines the available interface. The links
below carry detailed effects and evidence contracts; [usage.md](../usage.md)
provides examples. Paths and endpoints belong to the selected command host.

| Need | Utility and contract |
| --- | --- |
| Read a pane or inspect its reported state | [observe](../../items/observe/README.md): attributed screen/process/status evidence and explicit unknowns |
| Compare observations or wait for change | [compare and watch](../../items/observe/README.md): retain source identity and distinguish a change from successful completion |
| Run a visible command and recover its actual exit/output | [run-visible](../../items/run/VISIBLE.md): explicit argv, environment, working directory and receipt |
| Deliver one guarded message | [send](../../items/send/README.md): typing guard, input evidence and cooperative hold handling |
| Open, resolve, move, focus or close terminals | [surfaces](../../items/surfaces/README.md): visible Rex objects and exact target receipts |
| View live panes, tasks and machine vitals | [board](../../items/board/README.md) and [board feed](../../items/boardfeed/README.md): read projections from their current sources |
| Keep evidence, decisions or a parked handoff | [records](../../items/records/README.md): private structured records and attached evidence |
| Hold and hand back a pane | [clutch](../../items/clutch/README.md): cooperative takeover and queued delivery |
| Snapshot or review restoration | [recovery](../../items/recovery/README.md): explicit snapshots and reviewed restore operations |
| Select another command host | [named hosts](../alpha5.md): explicit target configuration and transport |
| Install a selected build or activate a retained build | [fleet](../fleet-install.md) and [setup](setup.md): verified per-host installation receipts |
| Inspect configuration and connectivity | `doctor --all`: configured build, Rex, rexconfig and hook checks |

## Agent lifecycle

Agent lifecycle is owned by [rexconfig](https://github.com/jcbbge/rexconfig#agent-commands).
The retired teerex launch, callback, profile, protocol-acknowledgement and channel
interfaces are not current utility commands. Current teerex guides do not
prescribe harness launches or scratchpad workflow.

## Evidence and cleanup

Check both the command exit and its structured result. Unknown evidence stays
unknown; a pane changing or reporting idle does not establish successful work.
Close only the temporary surfaces the task created, and retain records the task
requires. Snapshot and restore require their own explicit invocation; no utility
result implies permission to restart Rex.
