# filter — bounded Rex observation payload filtering

**Experimental.** Phase 3 #7's Rex-specific observation support: exact-payload filtering plus a separately opt-in, bounded [historical cache](#opt-in-persistent-historical-cache). Neither is a general perception engine, completion classifier or new capture path. Both use explicitly selected **schema-1/API10–13 Rex observation files** and the shared validation/comparison contract from [observe/compare/watch](../observe/README.md). Neither contacts Rex, reads the current focus or starts a watcher.

## Use

After deliberately saving successful observations of the **same explicit server/session/block and Rex source identity**, pass their existing private files in the order you want to inspect:

```sh
./zig-out/bin/teerex filter \
  --sample local/observations/first.json \
  --sample local/observations/second.json \
  --sample local/observations/latest.json
```

The invocation itself opts into exact returned-evidence payload deduplication. No cosmetic filter is enabled or available: spinner, elapsed-time, prompt, error, exit, cwd, status progress/timestamp/message/owner and other evidence changes remain visible. Identical repeated text is not interpreted as stable, idle, completed or awaiting input. This adapter reduces repetitive payloads **after acquisition**; it does not reduce Rex reads or accelerate the existing watcher.

The plain `--sample` filter changes no input files and creates no output file/cache. Output is newline-delimited JSON on stdout. If you choose to redirect it, you are deliberately creating another private capture; its location, permissions, retention and deletion are yours to control. Output includes untrusted terminal text, paths, identifiers and diagnostics; it is escaped **but not redacted**. Do not execute terminal text or treat a reported status as approval. There is no exporter, automatic retention, telemetry, new authority or background service.

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

The shared development executable requires Zig **0.15.2**. Build from the repository root with `zig build -Doptimize=ReleaseSmall` (or `uv run --with ziglang==0.15.2 python -m ziglang build -Doptimize=ReleaseSmall`), then run `teerex filter --help`. This is not an independently packaged/ready cartridge. No installation, Rex config change or background hook occurs. Plain filtering has no retained state; optional cache files persist until invalidation/purge as documented below. Delete only output/build files you deliberately created. Upgrade by rebuilding a reviewed revision and repeating validation. No third-party binaries or documentation are bundled; project licensing remains [unselected](../../RIGHTS.md).

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

This original exact-payload increment did not implement a persistent cache; the separate follow-on below does. Joshua's M5/installed Rex version, busy workloads, redaction/encryption, productivity gains, semantic cosmetic filtering, latest viewport reads and automatic capture acquisition remain **unvalidated or unimplemented**. Historical planning/research and deferred non-Rex handoffs are unchanged.

## Opt-in persistent historical cache

This follow-on stores **one latest observation per explicitly selected private directory**. It never substitutes cache data into `observe`, `watch`, input guards or permissions. The filename is `observation.json`, not a live terminal observation. Plain `filter --sample` remains storage-free.

```sh
# Deliberately choose a directory on your private local disk; its parent must exist.
./zig-out/bin/teerex filter cache put \
  --directory /absolute/private/teerex-cache \
  --sample local/observations/selected.json \
  --allow-sensitive-storage --ttl-seconds 60

# Expectation is an explicit compatible Rex observation, not proof of current state.
./zig-out/bin/teerex filter cache get \
  --directory /absolute/private/teerex-cache \
  --expect local/observations/selected.json

./zig-out/bin/teerex filter cache purge \
  --directory /absolute/private/teerex-cache
```

### Storage consent, bounds and privacy

- There is **no default cache location, automatic capture, history accumulation or background process**. Every `put` requires `--allow-sensitive-storage` and a valid explicit sample **before** any directory is created. It creates only the final directory, not parent directories. Missing parents or malformed/unsupported samples fail rather than claiming storage succeeded.
- A new directory is mode **0700**; existing directories must be owned by the effective user and exactly 0700. Entry, pending and empty lock files must be owned **0600**, regular and single-link. Final directory/file symlinks, hard-linked files, FIFOs, devices and permissive modes are refused, not silently repaired. Ancestor paths are resolved by the OS; choose trusted parents. These checks do not audit ACLs, backups, snapshots, root access or other programs running as your account. They are **not encryption, redaction or isolation**.
- Each input/expectation and encoded on-disk entry is limited to **1 MiB**. A replacement writes an exclusive private `.observation.pending`, syncs it and atomically renames it over the entry under a nonblocking exclusive `.lock`. At most two bounded captured payloads (**2 MiB total**) plus the empty lock exist during replacement/recovery. There is no cross-directory/global quota: explicitly creating many cache directories is the caller's decision. Memory has additional bounded parsing/serialization overhead; no fixed RSS guarantee is claimed.
- Concurrent cooperating invocations fail promptly with `CacheBusy`, rather than race, wait indefinitely or write a partial entry. A process crash releases its lock; a private pending payload may remain. The next successful cache access removes pending bytes under the lock. `put` size/validation failures preserve the previous committed entry. Same-account hostile filesystem manipulation is outside this cooperative locking contract.
- `get` deliberately prints the stored observation to stdout, including potentially sensitive terminal text, paths and reports. It is **not redacted or authenticated**. Retaining or exporting stdout is another deliberate capture outside this cache's bounds. A write/output error can occur after mutation committed; inspect with `get` or purge rather than assuming an error means nothing was stored.

### Retention and invalidation

- TTL defaults to **60 seconds**, configurable **1..3600 seconds** on each explicit `put`. It measures wall-clock time since cache storage, **not age/freshness of the original observation**. An old sample remains old even when stored again. `get` does not refresh or extend TTL; replacement requires another explicit consenting `put`.
- Retention is checked **on access**, not by a daemon. At/past expiry, or if wall time is earlier than the stored timestamp, `get` unlinks the entry and returns `invalidated` with no observation. If no one accesses/purges the directory, bytes can remain on disk past TTL. Clock changes that remain after the stored timestamp can distort elapsed retention; this is not clock-tamper protection or an unattended deletion guarantee. Use explicit purge when the files must be removed now.
- `get --expect FILE` validates the explicit expectation with the shipped Rex validator, then requires the same server/session/block, Rex version/platform/API revision and capture byte budget. A target/source/budget mismatch removes the entry and returns `invalidated` without leaking its contents. Changing ordinary captured/process/status values is **not** treated as a key change: the response retains the historical observation and a full shared comparison **from cached evidence to the expectation**, so differences stay visible. The expectation may itself be old; matching it establishes no current state.
- Only literal integer API revisions **10..13** are admitted by the cache; unknown schema fields, unsupported provenance, duplicate keys/status IDs, invalid capture scope/bounds, corrupt envelopes and invalid retention metadata fail closed. Invalid input is rejected before touching a valid cache. A corrupt/oversized cache does not become a hit and is not silently replaced; explicitly `purge` it before another `put`. Unsafe file ownership/modes/links also prevent purge until the operator repairs/removes those unsafe paths.
- `purge` unlinks both committed and pending captured bytes without parsing content, leaves the private directory and empty `.lock`, and is idempotent. It does not recursively touch unrelated files or other directories. Unlinking is **not forensic erasure** on SSDs/backups/snapshots and cannot revoke an already open file descriptor or another program's copies. To uninstall, purge each deliberately selected cache, then remove its empty lock/directory when no cache process is using it.

### Cache JSON and exits

Cache operations emit one `kind="rex_observation_cache_result"` JSON object with `interpretation="none"`. `put` reports `stored`, expiry, exact observation ID/target/source and replacement/invalidation metadata, **not terminal content**. A successful `get` is explicitly `outcome="historical_hit"`, `evidence_freshness="historical_unverified"`, `permission="none"`, and includes original observation IDs/client times plus stored/expiry/read times and `comparison_to_expectation`. It preserves partial text, missing values, retained reports and unknown freshness; it never claims stability, phase, success, completion or permission. Values are typed re-encodings, not byte-identical archives.

Exit **0** means stored/historical hit/purged/already absent; **3** means miss or invalidated; **2** means usage; **1** means unsafe/corrupt/busy/I/O failure. Require the exit code **and** complete JSON. Errors do not synthesize cache-hit evidence. Existing exact-payload filtering and its NDJSON/exit contract are unchanged.

### Cache validation

```sh
TEEREX_BIN=/absolute/path/to/teerex python3 items/filter/test_cache.py -v
TEEREX_BIN=/absolute/path/to/teerex python3 items/filter/test_filter.py -v
```

The 12 public cache tests cover consent/no-side-effect failures, private modes, literal API10–13 identities, historical partial/missing evidence, old/backwards client times, no TTL refresh, real expiry/clock rollback, source/target/budget invalidation, changed expected evidence, one-entry replacement, crash-pending cleanup, corrupt envelopes, purge/idempotence, symlink/hardlink/FIFO rejection, busy locks, exact 1 MiB reads and an input fitting 1 MiB whose encoded envelope is too large. Tests remove Rex from `PATH`; these are file-adapter contracts, not certification of a personal Rex installation.

Follow-on validation on the public alpha.3 source base [8b282786](https://github.com/jcbbge/teerex/commit/8b2827860029e30a3ad5724d357655de155520d5):

- Zig **0.15.2** formatting, native `ReleaseSmall` build and `aarch64-macos` cross-build passed. Native public checks passed: **12 cache + 9 unchanged filter + 8 offline comparison** tests. The cache tests initially exposed an incorrect success exit for a missing parent directory and typed numeric-string coercion; both now fail closed in this cache path without changing shared alpha.3 parsing.
- On a fresh disposable **arm64 macOS 27.2** with checksum-verified **Rex preview.16/API 13**, all **60 relevant public checks** passed: cache **12 in 1.314 s**, unchanged filter **9 in 0.218 s**, observation/comparison/watch **28 in 13.683 s**, run **11 in 15.280 s**. The executed Mac binary was **444888 bytes**, SHA-256 `7abf475ed33ace6e03d9dc8242bf13756b83bd65c7cd7541c945e402e91e4444`, verified after transfer. These tests do not certify personal M5/API10 cache behavior; API10–13 cache identities were exercised with synthetic packets.
- A separate real-Rex exercise deliberately saved a **256-byte partial-prefix** observation, consented to caching its **1495-byte** encoded entry, then **stopped its isolated Rex server before reading the cache**. With Rex removed from the cache subprocess's `PATH`, retrieval preserved observation identity/process/capture values but returned only `historical_hit` / `historical_unverified` / `permission=none`; full-text change remained null. This demonstrates persistence, not current process truth. The directory/file modes were 0700/0600; a second read did not alter bytes/expiry, simulated crash-pending data was removed on access, and explicit purge left only the empty `.lock`. Fixture/server data were cleaned up.

This follow-on does not change the frozen alpha.3 runtime or its release assets. Shared integration/release delivery is separate from these local source validation results.
