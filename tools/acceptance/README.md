# Evidence before readiness

`readiness.py` executes the [accepted rubric](../../docs/planning/workloads/readiness-acceptance.md) against installed observe bytes, fresh private HOME directories and disposable Rex servers. It never changes the personal server or promotes a record by hand.

```
python3 tools/acceptance/readiness.py --item observe --catalog ABS --rex ABS \
  --previous-teerex ABS --teerex ABS --runs 3 --long \
  --executor local:hive:independent-executor --author-executor local:hive:codex-replay \
  --out ABS
```

Root-only controls (socket defaults, doctor routing and state defaulting) execute the combined CLI, as their test guards and README explicitly scope them to that root. The observation and state public suites share their existing private-server fixtures. All explicit observation/state/compare/watch payload tests execute installed bytes.

The executor requires a catalog from the current clean checkout to attribute new runs accurately; packaging readiness itself is based on content, not commit identity. `--merge OLD` accepts only matching covered-content, payload and rubric identities. Missing or author-identical executor labels remain `not_ready` (R12); labels attribute an execution and do not authenticate it. Public records contain sanitized row details and hashes. Packet evidence is private and discarded after each run. Manager lease/data/retired paths are seeded before the exact N6 file-listing control.

`package.py` validates records in `tools/cartridges/readiness/<id>-<platform>.json`. Absent, non-ready or stale evidence ships experimental; malformed records refuse packaging. Ready manifests narrow API revisions to the measured list and link the proving record through `compatibility.readiness`. `source_commit` is provenance only: later commits and rebases do not expire evidence. `covered_files_sha256` pins every tracked or unignored file under the covered paths; `covered_inputs_sha256` hashes that sorted path/digest map. The manager, packager and build recipe are mandatory coverage. Packaging hashes current bytes using the same algorithm; added, changed and deleted paths are all listed in `stale:PATH,…`. Timestamps alone do not invalidate evidence. The rubric must still match. The measured payload hash is provenance, not a rebuild staleness test; each generated manifest separately pins its actual built artifact hash.

`baseline.py --teerex ABS --rex ABS --out NEW_DIR` runs synthetic F1–F6 controls and alternating teerex/plain-Rex F1/F4 measurements (40 warm samples, two excluded warmups by default). `--warm-runs` and `--warmups` support bounded development runs. `report.json` and `summary.md` are private (0600); directories are 0700. Full files, raw prefixes, true exits and status reports remain separate evidence. X1 uses one pane with equal captured prefixes and a changed hidden tail; compare's same-pane refusal remains intact. F1/F4 prefixes and exits are retained side by side.

Run the evidence unit suite with `python3 -m unittest discover -s tools/acceptance -p 'test_*.py' -v`. Synthetic fixtures do not represent model productivity; excluded server, GUI, neighbouring-pane and energy costs must accompany measurements.

`baseline.py --agent-arm --profiles ABS --agent-profiles codex,claude --agent-runs 1 --teerex ABS --rex ABS --out NEW_DIR` runs the minimum actual-agent acceptance (default five runs per profile and condition). Profiles must be local, hook-enabled and use existing subscriptions. Task tools are counted through PATH wrappers; plain Rex blocks teerex with exit 127, and interruption shims record without delivery. One labelled, inert notification sink is explicitly approved alongside the managed visible agent tab; both owned panes are closed with native absence verification. Task panes use disposable servers. Public summaries contain counts and correctness flags, never model text. Private registries remain 0700/0600 evidence. The shims measure cooperative tool use and are not an isolation or authentication boundary.

CI uses the checksum-verified binary from the documented alpha.5 release for compatibility packets. The artifact uploader is pinned to the official [v4.6.2 release](https://github.com/actions/upload-artifact/releases/tag/v4.6.2), verified against its upstream Git tag; only sanitized records and summaries are uploaded.

The executor warms the exact missing-server refusal before N6: the macOS Rex client retains a per-route `start.lock` even with autostart disabled. File-listing equality remains exact. Child Python bytecode writes are disabled, and the existing fault suites use their own private HOME. `--evidence-dir NEW_ABS` retains private before/after diagnostics when investigating a control failure.

Phase B launches its harness at the exact already-trusted workspace parent and puts fixture commands/files in an owned scratch child. It never answers trust prompts or edits personal trust configuration. A non-repository child does not inherit Codex's parent trust; this distinction was observed during acceptance. All owned scratch children are removed after their condition.

Actual-agent tasks name the absolute paths inside the counting PATH directory because Codex login shells can reset PATH. A correct answer with zero counted calls fails measurement acceptance; the uninstrumented probe is not evidence for round-trip ratios.

The U05 state interpretation is part of the current whole-cartridge contract. Its public suite and `--state` help option are mapped; embedded `items/send/draft.lua` is an additional covered compilation input. Earlier pre-U05 records are superseded by the rebased run.


Records without measured content hashes remain stale until fresh independent evidence is acquired; old evidence is never enrolled retrospectively.
