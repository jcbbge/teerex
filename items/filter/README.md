# filter — bounded Rex observation payload filtering

**Experimental.** Phase 3 #7's small Rex-specific support adapter, not a general perception engine, completion classifier, persistent cache or new capture path. It reads explicitly selected **schema-1/API10–13 Rex observation files**, in caller-supplied order, using the same validation and adjacent comparison contract as [observe/compare/watch](../observe/README.md). It never contacts Rex, reads the current focus or starts a watcher.

## Use

After deliberately saving successful observations of the **same explicit server/session/block and Rex source identity**, pass their existing private files in the order you want to inspect:

```sh
./zig-out/bin/teerex filter \
  --sample local/observations/first.json \
  --sample local/observations/second.json \
  --sample local/observations/latest.json
```

The invocation itself opts into exact returned-evidence payload deduplication. No cosmetic filter is enabled or available: spinner, elapsed-time, prompt, error, exit, cwd, status progress/timestamp/message/owner and other evidence changes remain visible. Identical repeated text is not interpreted as stable, idle, completed or awaiting input. This adapter reduces repetitive payloads **after acquisition**; it does not reduce Rex reads or accelerate the existing watcher.

No input files are changed and no output file/cache is created. Output is newline-delimited JSON on stdout. If you choose to redirect it, you are deliberately creating another private capture; its location, permissions, retention and deletion are yours to control. Output includes untrusted terminal text, paths, identifiers and diagnostics; it is escaped **but not redacted**. Do not execute terminal text or treat a reported status as approval. There is no exporter, automatic retention, telemetry, new authority or background service.

## Human and agent contract

Each input produces exactly one event; a successful invocation then emits one final summary. All events have `schema_version=1` and `interpretation="none"`.

- **`rex_evidence_filter_sample`** contains the supplied observation's **value-preserving typed re-encoding**, its 1-based `sample_index`, and `comparison` against the immediately preceding input (null for the first). `reason` is `baseline`, `evidence_changed`, or `latest_checkpoint`. Every changed payload is included. The final input always includes its payload; a repeated final input is explicitly marked `latest_checkpoint`.
- **`rex_evidence_filter_repeat`** omits only an identical intermediate observation payload. It retains the current `observation_id`, client start/end times, index and **entire adjacent comparison**, including nullable unknowns, exact target and source. `evidence_sample_index` refers to the last full payload event whose returned evidence is identical. It is a reference to historical file evidence, not a newly acquired or fresh observation. Packet IDs and client times are not deduplication keys or freshness guarantees.
- **`rex_evidence_filter_summary`** with `outcome="processed"` means all selected files were processed, not that a terminal/program/task completed. `samples_read` counts inputs; `observation_payloads_emitted` counts full-payload events; `observation_payloads_omitted` counts repeat events. These last two counts sum to `samples_read`. `repeated_evidence_samples` also includes a repeated final checkpoint, whose payload is **not** omitted. `input_bytes` counts actual file bytes read; `latest_observation_id` names the last input. `persistent_cache=false` describes this command's behavior, not what a caller does with stdout.

For four identical returned-evidence inputs with distinct IDs: baseline, repeat referencing sample 1, repeat referencing sample 1, latest checkpoint, summary. Counts are 4 read, 2 payloads emitted, 2 omitted and 3 repeated. No comparison disappears. A change followed by a return to earlier values emits both transitions; comparisons are adjacent, not against a stale retained baseline.

### Evidence is not a byte-for-byte archive

Typed re-encoding may reorder object keys/status records, compact whitespace and materialize optional null/default members. The existing validator sorts status IDs; absent and explicit-null optional values mean the same thing in that contract. The original input files remain byte-for-byte untouched. Keep those files if original bytes matter. Unknown JSON fields, duplicate keys, unsupported schema/API/capture/provenance and mismatched targets/sources are rejected rather than silently ignored or normalized away.

Deduplication excludes only packet identity and the two client-clock timestamps. All other typed observation values participate, including capture budget/completeness, report timestamps, metadata and `atomic_snapshot`. Thus a reported-directory timestamp change can emit a payload even if the existing comparison's narrower value-change flags are false. No new evidence field is silently treated as cosmetic.

Equal partial prefixes may share a payload, but **every** adjacent comparison still has `full_text_changed=null`; unequal budgets retain the shipped captured-text comparability rules. Missing process/directory/status evidence stays unknown; disappearance remains an availability change. Last-reported directory/status freshness remains unknown. A `done` claim, quiet capture, client-clock ordering or repeat count never establishes successful exit, truth, atomicity or authority.

### Failure and resource bounds

- Accepts **2..128** `--sample FILE` pairs; no implicit ordering by timestamps, directory scans, stdin, glob expansion inside the program or background polling.
- Requires regular files, at most **1 MiB each** and **16 MiB combined**. FIFO/device/directory inputs are rejected; nonblocking open avoids waiting for a FIFO writer. File reads remain bounded if a file grows. This is not a filesystem isolation boundary or a wall-clock guarantee for slow storage/concurrent writers.
- Only previous/current parsed observations, their source bytes, canonical comparison bytes and one output serialization are retained. Per-sample arenas are released rather than accumulating history. Parser/serialization overhead is additional to file-byte bounds; no exact peak-RSS guarantee is claimed.
- Exit **0** means processed; **1** means file/evidence/output failure; **2** means invalid usage. `--help` exits 0. **Require both exit 0 and the final processed summary.** A late failure can leave earlier valid NDJSON events but never emits a processed summary. A failed/truncated stream is not a complete filtered result.
- Metadata-heavy, small or changing samples may **grow**, not shrink, because every comparison remains explicit. This is a bounded opt-in representation, not a token/CPU/productivity optimization claim.

## Build, lifecycle and verification

The shared development executable requires Zig **0.15.2**. Build from the repository root with `zig build -Doptimize=ReleaseSmall` (or `uv run --with ziglang==0.15.2 python -m ziglang build -Doptimize=ReleaseSmall`), then run `teerex filter --help`. This is not an independently packaged/ready cartridge. No installation, Rex config change or persistent hook occurs: stop invoking it to remove its runtime effect. Delete only output/build files you deliberately created. Upgrade by rebuilding a reviewed revision and repeating validation. No third-party binaries or documentation are bundled; project licensing remains [unselected](../../RIGHTS.md).

The leaf's integration ABI is `run(allocator, args, comptime observation) !u8`, where args exclude executable/subcommand and the shared root supplies `@This()`. It requires public `Observation`, `validateObservation`, and `compareObservations`; it does not duplicate their validation or introduce another adapter schema. The integration owner controls shared CLI dispatch/build/release wiring. Scratch wiring was used for the validation below; these results are not themselves a released build.

```sh
TEEREX_BIN=/absolute/path/to/teerex python3 items/filter/test_filter.py -v
```

Nine public-CLI tests use synthetic observation files with Rex removed from the subprocess `PATH`. They cover changed IDs/client times/object-key and record ordering, all retained unknown comparisons, final duplicate checkpoints/auditable counts, prompts/errors/spinners and metadata/process/status transitions, return-to-earlier values, adjacent equality with the public `compare`, missing/partial/mixed-budget evidence, strict unsupported-field/target/source/provenance rejection, late-error output without a summary, malformed/duplicate JSON, FIFO/regular-file rejection, 128/129 samples, and exact 1 MiB/16 MiB boundaries. The 128-sample 60000-byte partial-prefix case reduced **7850898 input bytes to 298396 output bytes (96.20%)**, retaining all 127 comparisons; it is synthetic, not a Rex performance benchmark.

### Disposable-Mac validation — 12 November 2026

- Zig formatting, native Linux validation build and `aarch64-macos` `ReleaseSmall` cross-build passed. Nine filter tests passed natively in **0.205 s** and on disposable **arm64 macOS 27.2** in **0.252 s**. Native tests validate an offline file adapter, not Linux/VPS product support. The scratch-wired Mac executable was **302968 bytes**, SHA-256 `848b63071879882fab98a9e86724a4fe4677a7220e9dc0430194643688cc9b46`; its checksum matched on the Mac before execution.
- All **27 existing observation/comparison/watch** checks passed in **13.274 s** and all **11 existing run** checks in **15.261 s**, using separately downloaded/checksum-verified **Rex preview.16/API 13**, commit `aa2db1b21261b479a550559fb70e2c3a66c07ba2`. Fixtures used private disposable servers, never a default/user server. The old unmodified executable rejects `filter` with usage exit 2; the new repeat/checkpoint scenario passes with scratch wiring.
- A separate real-Rex exercise acquired **32 distinct observations** of one unchanged **4096-byte partial prefix**, then filtered the existing files with Rex removed from `PATH`. **177472 source-file bytes → 56354 NDJSON bytes (68.25% smaller)**, with 2 full payloads, 30 repeat events, every adjacent comparison exactly matching public `compare`, every full-text change still null and input files untouched. Source files were formatted JSON; this byte comparison includes JSON compaction, not just deduplication. `/usr/bin/time -l` reported **1835008 bytes maximum RSS** for a second offline processing of those files; this is a single measured workload, not a peak-memory bound or M5 benchmark.
- Further real fixtures changed `working` to `done` while process evidence stayed unchanged and `last_exit` remained null, then separately reported `done` and exited **7**. The changed reports, disappeared foreground evidence, actual exit 7 and unknown freshness all survived with `interpretation="none"`. Fixtures were stopped and cleaned up. These are concrete counterexamples to treating filtering as completion detection.

Joshua's M5/installed Rex version, busy workloads, privacy/redaction, productivity gains, semantic cosmetic filtering, a persistent cache, latest viewport reads and automatic capture retention are **not** implemented or validated here. Historical planning/research and deferred non-Rex handoffs are unchanged.
