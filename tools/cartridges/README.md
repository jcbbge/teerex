# Cartridge recovery inspection

The [cartridge contract](../../docs/cartridges.md) describes installation, leases and retained data. These recovery commands use the same embedded/source manager, HOME-bound root, marker and ownership checks. They do not run payloads or contact Rex.

```sh
teerex cartridges doctor
teerex cartridges --root /absolute/path/inside/HOME doctor
teerex cartridges --root /absolute/path/inside/HOME repair --plan
teerex cartridges --root /absolute/path/inside/HOME repair --apply --older-than-minutes 30
```

`doctor` opens an existing lifecycle lock read-only with a nonblocking shared lock; it creates no directories, lock files, registry files or leases. An absent root produces an empty report. A busy lifecycle refuses with JSON/exit 1. It reports interrupted `packages/ID/.stage-*` directories, pending `.state-*` files, invalid committed state, registry/code mismatches, missing or modified package bytes (manifest and payload SHA-256 checks), inactive versions, and retained data without installed code. Invalid state is reported explicitly; it is never adopted or rewritten. Findings have `next_command` argv arrays for deliberate follow-up. An inspection receipt is not a healthy-root assertion: inspect `registry_valid` and `findings`. The report is historical, not an atomic filesystem snapshot against same-account programs bypassing locks.

`repair` requires exactly one of `--plan` or `--apply`. It only removes old interrupted staging trees directly under `packages/ID/`. The positive `--older-than-minutes` threshold defaults to **30**, applied to the newest modification time of the directory and every member. A recently written member makes an old directory ineligible. The plan returns `selected`, `skipped` reasons and the exact `apply_command`. Apply rechecks eligibility and identity under the lock and returns `removed`; it does not promise the filesystem stayed unchanged since a previous invocation's plan. Empty selections are successful no-ops.

Both modes require the existing stable lifecycle lock exclusively and nonblockingly; missing/unsafe/busy locks refuse. All existing version leases are checked for in-use holders while the lifecycle lock prevents new cooperating launches. Every selected tree, its package parents and every member must be owned by the current user. Linked paths, hardlinked files, nonprivate directories and recent trees are skipped, never forced. Deletion requires Python's descriptor-based symlink-resistant `shutil.rmtree`; unsupported runtimes refuse. A live invocation, foreign owner or ambiguous tree is never treated as abandoned.

Repair never changes `state.json`, adopts unregistered code, removes installed or retired versions, deletes retained data, promotes pending registry files, stops processes or retries automatically. Modified/missing payloads, invalid/pending state, and unregistered code have **no safe automatic repair here**; preserve evidence and review privately. The doctor reinspection command on those findings does not claim to resolve them. Inactive versions can be explicitly activated with dependency checks; retired data remains retained. Normal lifecycle commands continue to own activation, removal and restore.

Stage deletion is not an atomic transaction. Cancellation, I/O failure or process loss may leave a partially removed staging tree; rerun doctor, review its age and bytes, then request a fresh plan. Installed code, registry and `data/ID` are outside the repair selection. Same-account programs that ignore the cooperative locks remain outside the lifetime/identity guarantee. No watcher, adoption, kill, purge or queued retry is installed.

The existing `test_cartridges.py` suite exercises disposable crash trees, malformed state, hashes, data retention, plan/no-mutation, apply boundaries, locks, age, links and owner refusal. `test_root_entry.py` inherits those same cases through the embedded manager. Both suites already run in the cartridge CI lanes.
