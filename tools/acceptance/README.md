# Evidence before readiness

`readiness.py` executes the [accepted rubric](../../docs/planning/workloads/readiness-acceptance.md) against installed observe bytes, fresh private HOME directories and disposable Rex servers. It never changes the personal server or promotes a record by hand.

```
python3 tools/acceptance/readiness.py --item observe --catalog ABS --rex ABS \
  --previous-teerex ABS --teerex ABS --runs 3 --long \
  --executor local:hive:independent-executor --author-executor local:hive:codex-replay \
  --out ABS
```

The catalog must identify the current clean source commit. `--merge OLD` accepts only matching source, payload and rubric identities. Missing or author-identical executor labels remain `not_ready` (R12); labels attribute an execution and do not authenticate it. Public records contain sanitized row details and hashes. Packet evidence is private and discarded after each run. Manager lease/data/retired paths are seeded before the exact N6 file-listing control.

`package.py` validates records in `tools/cartridges/readiness/<id>-<platform>.json`. Absent, non-ready or stale evidence ships experimental; malformed records refuse packaging. Ready manifests narrow API revisions to the measured list and link the proving record through `compatibility.readiness`. Source ancestry, covered inputs, rubric and payload bytes must still match.

`baseline.py --teerex ABS --rex ABS --out NEW_DIR` runs synthetic F1–F6 controls and alternating teerex/plain-Rex F1/F4 measurements (40 warm samples, two excluded warmups by default). `--warm-runs` and `--warmups` support bounded development runs. `report.json` and `summary.md` are private (0600); directories are 0700. Full files, raw prefixes, true exits and status reports remain separate evidence. X1 uses one pane with equal captured prefixes and a changed hidden tail; compare's same-pane refusal remains intact. F1/F4 prefixes and exits are retained side by side.

Run the evidence unit suite with `python3 -m unittest discover -s tools/acceptance -p 'test_*.py' -v`. Synthetic fixtures do not represent model productivity; excluded server, GUI, neighbouring-pane and energy costs must accompany measurements.
