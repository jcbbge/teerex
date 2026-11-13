# Q03 minimal cartridge discovery — implementation spec

**Build `teerex cartridges ARGS…` as a root exec passthrough into the existing manager.** It embeds the same manager source, makes three small changes to the manager, and adds one recovery table to the docs. There is no new manager, manifest, selector, catalog-browse verb or GUI. Plans, JSON, exit codes, the HOME-bound root, leases and independent removal behave exactly as they do with `python3 tools/cartridges/cartridges.py ARGS…` today.

**Status (supplied):** Joshua approved Q03 for implementation via the seat on 13 November 2026. Under his overnight standing authority (`~/rivet/work/seat-2026-11-13/overnight-2026-11-13.md`), it is built, landed and installed on hive and the M5 tonight. The teerex lead (`block:01a1d34f-9a09-7392-b8e8-17046462c623`) builds from this spec; this document is spec only.

That authority replaces the roadmap's "choose the entry shape after first-use observation": Q05 runs right after install (§6) and can only *refine* the shape. Every former open decision is now **chosen** by Josh's rubric (10X developer, agentic and user experience). **Host-blocked parts: none.** Q03 needs no Rex API at all; it is a local CLI and manager change. No upstream Rex request is filed.

Labels: **observed** means read or run this session at base `244d893`; **inferred** means from reading code, not run; **chosen** means a spec decision.

## 1. Why this shape

These are the facts at base `244d893`; details are in the [original design notes](#appendix-baseline-evidence).

- **observed:** `teerex cartridges …` currently falls through to the observation parser, prints observe/compare/watch usage and exits 2. The root help never mentions cartridges.
- **observed:** the manager is not in the installed core. It ships in source and onboarding only, so a user holding `teerex` cannot find it.
- **observed:** the manager already discloses everything Q03 needs in its plan: status, exact version, dependency closure, code and data paths, `data_policy`, permissions, provenance, compatibility, `active_before`, `hooks_executed` and `undo`.
- **observed:** ready-only `--all` against an all-experimental catalog returns `ok: true`, `selected: []`, `packages: []`, exit 0, without saying why. This is correct, but it is silent.
- **observed:** refusals are schema-1 JSON with exit 1, naming the problem but not the next step.
- **inferred:** an interrupt during `--apply` rolls back staged code, but surfaces as a Python traceback, not JSON.

Passthrough fixes the first two problems without forking the manager. One extra output field fixes the silent empty selection, and a documentation table fixes the missing next steps. A `doctor`-style listing was rejected: it would be a second readiness view that can drift from `install`.

## 2. Command surface (chosen)

```text
teerex cartridges [--root ABS] install ID… --catalog ABS [--allow-experimental] [--apply]
teerex cartridges [--root ABS] install --all --catalog ABS [--allow-experimental] [--apply]
teerex cartridges [--root ABS] list
teerex cartridges [--root ABS] run ID [-- ARGS…]
teerex cartridges [--root ABS] activate ID --version V [--apply]
teerex cartridges [--root ABS] remove ID --version V [--deactivate] [--apply]
teerex cartridges [--root ABS] restore ID --version V [--apply]
teerex cartridges --help | teerex cartridges SUBCOMMAND --help
```

These are exactly the manager's existing subcommands and flags. Nothing is added, renamed or parsed by the root.

**Discovery is the plan, not a new verb.** The documented way to see "what is in this catalog, and what is ready" is:

```sh
teerex cartridges install --all --catalog "$CATALOG"                        # ready-only: what --all would take
teerex cartridges install --all --catalog "$CATALOG" --allow-experimental   # every item, with status
teerex cartridges list                                                      # what is installed/active/retired here
```

Neither plan mutates anything without `--apply`; this was observed for the plan path on an absent root.

## 3. Changes, files and owners

All four changes below are owned by the teerex lead, who owns root, build and manager source.

### 3a. `build.zig`: embed the manager

Add a module-options block mirroring `fleet_sources` (`build.zig` lines 17–22):

```zig
const cartridge_sources = b.addOptions();
const manager = b.build_root.handle.readFileAlloc(b.allocator, "tools/cartridges/cartridges.py", 1024 * 1024) catch @panic("cartridge manager source unavailable");
cartridge_sources.addOption([]const u8, "manager", manager);
exe.root_module.addOptions("cartridge_sources", cartridge_sources);
```

This is one source with two deliveries: onboarding keeps shipping the file, and the core embeds the same bytes at build time. No copy is committed.

### 3b. `src/main.zig`: dispatch and help

Place the dispatch before the observation fall-through, next to the other `command` checks (for example after the `fleet install|rollback` branch):

```zig
if (std.mem.eql(u8, command, "cartridges")) {
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", @import("cartridge_sources").manager });
    try argv.appendSlice(allocator, rest);
    std.process.execv(allocator, argv.items) catch |err| {
        var buf: [256]u8 = undefined;
        const line = std.fmt.bufPrint(&buf, "{{\"error\": \"cannot execute python3 ({s}): teerex cartridges requires Python 3.9+\", \"ok\": false, \"schema_version\": 1}}\n", .{@errorName(err)}) catch unreachable;
        std.fs.File.stderr().writeAll(line) catch {};
        std.process.exit(1);
    };
}
```

Requirements, all chosen:

- **Use exec, never spawn-and-wait.** The process chain is teerex → python3 → payload on the same PID. Exit status and signals stay exact, and the manager's lease descriptors pass through its own `execve`.
- **Use `-I` (isolated mode).** `python3 -c` otherwise puts the current directory first on `sys.path`, so a planted `json.py` in the caller's cwd would run inside the manager. `-I` also ignores `PYTHONPATH` and the user site. It does not strip `os.environ`, so payloads still receive the caller's environment (HOME included) as today.
- **Leave argv and the environment alone:** no injected `--root`, no change to HOME.
- **Python is not found:** the refusal above, exit 1. Never fall back to the observation parser.

Add this line to the root `usage` under "Operating-layer commands":

```text
  cartridges install|list|run|activate|remove|restore  Independent native payloads via the embedded manager
```

Also change the Python line to: `Python3.9+ is required for targets, boards, agents, recovery, fleet, cartridges and palette install.`

**Named hosts (chosen, no code).** `teerex --config C --host H cartridges …` already reaches the remote `teerex --rex REX cartridges …` through `targets exec`. `cartridges` is not in `SELECTORS`, so no socket is injected. It is plain transport: the remote HOME and root apply, `--catalog` is a path on that host and nothing is uploaded, and stderr gains the existing `target_selection` receipt and `--rex` note lines. Document this as transport only. It is excluded from byte-parity (D6). Not tested here.

### 3c. `tools/cartridges/cartridges.py`: three small changes

1. **Usage name.**
   - Change: `argparse.ArgumentParser(prog="teerex cartridges" if sys.argv[0] == "-c" else None, description=__doc__)`.
   - Effect: direct invocation is unchanged; the passthrough shows `usage: teerex cartridges …`.
2. **Explain ready-only exclusions.** `install` output (plan and apply) gains one key, always present:
   - `excluded_experimental` is the sorted list of catalog IDs with `status: experimental` that `--all` skipped because `--allow-experimental` was absent. It is `[]` for explicit IDs, or when the flag is given.
   - Implementation: `sorted(k for k, (m, _, _) in available.items() if args.all and not args.allow_experimental and m["status"] == "experimental")`.
   - It never changes `selected`, `packages` or the refusal for an experimental dependency of a ready item.
   - It is purely additive: existing tests index keys rather than compare key sets (observed: `test_cartridges.py` line 86 and others). Manifest "unknown fields fail" applies to manifests, not output.
3. **Interrupt and version refusals as JSON**, in the `__main__` block:
   - `if sys.version_info < (3, 9)`: emit `{"error": "Python 3.9+ required, found X.Y", "ok": false, "schema_version": 1}` on stderr, exit 1.
   - Add `except KeyboardInterrupt`: emit `{"error": "interrupted: run list and inspect the root for .stage-* directories before retrying", "ok": false, "schema_version": 1}` on stderr, exit 130.
   - The existing `except BaseException` rollbacks still run first, because the interrupt propagates through them.
   - **SIGTERM/SIGKILL handling is unchanged.** There is no handler, so no rollback, as already documented in the "not a power-loss/SIGKILL transaction journal" clause.

### 3d. Tests

| File | Change |
| --- | --- |
| `tools/cartridges/test_cartridges.py` (existing; CI already runs it) | Cover `excluded_experimental` in the existing all-excludes test, and the `prog` name under `python3 -I -c "$(cat cartridges.py)" --help`. For the interrupt, put the `__main__` handling in a small `entry()` function that wraps `main()`. The test imports the module, patches `main` to raise `KeyboardInterrupt`, and asserts the JSON line and exit 130 (`SystemExit.code`). A real SIGINT mid-copy is racy, so it is acceptance case D7(b), not a unit test. |
| New `tools/cartridges/test_root_entry.py` | A script with `--catalog ABS` (same shape as `test_payloads.py`) that reads `TEEREX_BIN` (convention of `src/test_targets.py` line 13). It runs D1–D9 and M1–M8 from §5, with M1/M2 against the real native catalog passed in. It needs no Rex and no network. |
| `.github/workflows/ci.yml` (**chosen:** the teerex lead owns it tonight) | In the existing "Run cartridge lifecycle and native installed-payload contracts" step, after the `test_payloads.py` line, add the block below. Add one matching line to `docs/ci.md`'s suite list. |

```yaml
        env:
          TEEREX_BIN: ${{ github.workspace }}/zig-out/bin/teerex
```

The step gets that `env:` block, and its `run:` list gains this line:

```sh
          python3 tools/cartridges/test_root_entry.py --catalog "$RUNNER_TEMP/cartridge-catalog" -v
```

The same step runs on Linux and the Mac API13 lane, so both platforms are covered with the catalog the step already builds.

### 3e. Documentation (teerex lead; coordinator integrates canonical docs)

- `docs/cartridges.md`:
  - Make `teerex cartridges` the primary spelling, keeping `python3 tools/cartridges/cartridges.py` as the equivalent direct form.
  - Add the discovery recipe from §2.
  - Document `excluded_experimental`.
  - Add the recovery table in §4 and the new exit codes 130/1.
- `docs/concierge/follow-ons.md` §1: switch the commands to `teerex cartridges`, and note that the core now embeds the manager.
- Next release notes: say the core embeds the manager and that a core rollback rolls back the embedded manager too; installed roots and data are untouched.
- The roadmap Q03 checklist and the coordination ledger are updated by the coordinator, not the lead.

**Packaging:** none. The core archive stays three files, and onboarding still carries the manager file.

### 3f. `src/main.zig`: same isolation for the fleet bridge (chosen, separate commit)

`fleet install|rollback` launches `python3 -c fleet_bridge.py` without `-I`, so it has the same exposure: a planted module in the working directory gets imported. Change its argv to `"python3", "-I", "-c", @embedFile("fleet_bridge.py")` (and the same for `python()` / `targets.py` at the top of `main.zig`).

Gate: `TEEREX_BIN=… python3 src/test_targets.py -v` passes unchanged. If `-I` breaks a fleet or targets case, drop this commit only; Q03 does not depend on it.

### 3g. agent-core rex skill (owner: codex · agent-core native, `block:01a1d372-e6db-7abe-8048-55203533aa2f`)

After the teerex install lands, add one row to `primitives/skills/rex/SKILL.md` §7's command table, after the `fleet install` row, then sync both machines:

```markdown
| `cartridges` | List, preview, install, run or remove the separately packaged native payloads. Plan first; `--apply` mutates; `run` holds the in-use lease (calling a payload directly does not). | `teerex cartridges install --all --catalog "$CATALOG" --allow-experimental` |
```

## 4. Contract: output, exit codes, refusals

| Outcome | Stream | Exit |
| --- | --- | --- |
| Lifecycle success (`install`/`list`/`activate`/`remove`/`restore`, plan or apply) | stdout: one schema-1 JSON line, `ok: true`, `operation`, `applied` and existing fields; `install` adds `excluded_experimental` | 0 |
| `run` | the payload's own stdout/stderr, exactly; no manager receipt after exec | payload's exit or signal |
| Contract/filesystem refusal | stderr: `{"error": …, "ok": false, "schema_version": 1}` | 1 |
| `python3` missing or not executable (root) | stderr: the JSON line in §3b | 1 |
| Python older than 3.9 | stderr: JSON refusal | 1 |
| Usage error (bare `teerex cartridges`, unknown flag, missing `--catalog`) | stderr: argparse usage naming `teerex cartridges` | 2 |
| Interrupted (SIGINT) | stderr: JSON refusal | 130 |

**Recovery table**, documentation only. Error strings are the existing manager messages, observed or read in source.

| `error` contains | Meaning | Next step (never force, delete locks or edit `state.json`) |
| --- | --- | --- |
| `experimental cartridge requires --allow-experimental` | the item or a dependency is experimental | review the plan, then add `--allow-experimental` only if experiments are intended |
| `choose explicit IDs or --all` | both or neither were given | pass IDs **or** `--all` |
| `cartridge root does not exist` | nothing is installed under this HOME/root | check HOME and `--root`; install first |
| `root must be strictly inside HOME`, `symlink or non-directory ancestor`, `refusing unmarked/nonempty cartridge root` | unsafe or foreign root | choose a canonical user-owned path inside HOME |
| `active removal requires --deactivate` | the version is active | re-run with `--deactivate`; the ID becomes inactive with no fallback |
| `active dependent blocks removal: X` | X pins this version | remove or switch X first |
| `in use or concurrent lifecycle operation` | a lease or the short registry mutex is held | wait for the running cartridge or the other operation to finish, then retry by hand; nothing queues |
| `payload checksum mismatch`, `package contains missing or additional files`, `manifest identity changed` | installed bytes differ from the registry | copy out any edits and inspect; the manager will not delete them |
| `installed version identity differs; no overwrite` | same version, different bytes | use a new version number |
| `unregistered or retired version exists` | leftover or retired directory | `restore` it, or inspect manually |
| `interrupted: …` | apply was interrupted | `list`, then inspect `.stage-*`; retry only after reading the state |

## 5. Acceptance cases the lead runs

Every case uses a disposable, canonical, user-owned `HOME` (for example `mktemp -d`, `chmod 700`, resolved path) on a disposable supported host. Use synthetic fixtures except where a real payload is named, and never personal M5/hive state. `T` is the built `teerex`, `C` a catalog path, `R` the root. "Unchanged" means the recursive HOME listing plus file hashes match before and after.

**Entry (Q03)**

| ID | Steps | Pass |
| --- | --- | --- |
| D1 Preview | Catalog of sentinel payloads that `touch $HOME/EXECUTED` if run. `T cartridges install --all --catalog C --allow-experimental`, then `… install filter --catalog C --allow-experimental`. | exit 0; `applied: false`; each package shows `status`, `version`, `dependencies`, `code`, `data`, `permissions`, `undo`; HOME unchanged; no `EXECUTED`. |
| D2 Counterexample | All-experimental catalog: `T cartridges install --all --catalog C`, and the same with `--apply`. | Both exit 0, `selected: []`, `packages: []`, `excluded_experimental` lists every ID. The plan leaves HOME unchanged. The apply, on an absent root, creates only `R/.teerex-cartridges`, `R/.lock` and a `state.json` with empty maps (inferred from `Store(create=True)` + `save()`); nothing under `packages/` or `data/`. **Fail** if anything is admitted, marked ready, or the exit is non-zero. |
| D3 Retained data | Apply `filter`; write `R/data/filter/user.txt`; plan then apply `remove filter --version V --deactivate`; `restore`; `list`. | The remove plan shows `data_retained: true` and the data path; `user.txt` is byte-identical after remove and after restore; restore leaves the item inactive (`active` lacks `filter`). |
| D4 Refusals | One case per row of the recovery table that can be produced with fixtures (all except `interrupted`, which is D7). | Exit 1, schema-1 JSON on stderr, `error` contains the listed text, HOME unchanged, and the documented next step succeeds. |
| D5 Independence | Apply one ID, then experimental `--all --apply`, then remove one. | The first item is not reinstalled; the others stay active; dependencies are not garbage-collected. |
| D6 Parity | For D1–D5 plus `--help`, `install --help`, bare `cartridges`, an unknown flag and `list`, run `T cartridges ARGS` and `python3 -I tools/cartridges/cartridges.py ARGS` (same HOME, same source commit). | stdout, stderr and exit are byte-identical except the `prog` token in usage text; the observation usage never appears. |
| D7 Cancel | (a) a plan without `--apply`; (b) SIGINT during `--apply` of a large synthetic payload (about 60 MiB). If the signal lands after completion, the result is a normal success: repeat until it is interrupted in flight, and record the attempts. | (a) HOME unchanged. (b) exit 130 with JSON `error` starting `interrupted`; `list` shows the previous selection; no newly registered version; record any leftover `.stage-*` (allowed, reported). |
| D8 No Python | `PATH` without `python3`: `T cartridges list`. | exit 1; stderr is exactly the §3b line; nothing else runs. |
| D9 Root help | `T --help`. | Contains the `cartridges` line and the updated Python line. |

**Managed runtime (Q11).** Direct payload invocation never counts toward Q11.

| ID | Steps | Pass |
| --- | --- | --- |
| M1 Real managed launch | Real native catalog for the host (published or a reviewed build). `T cartridges install filter --catalog C --allow-experimental --apply`, then `T cartridges run filter -- --help` and one offline filter invocation with a known non-zero exit. | Payload stdout, stderr and exit are unmodified; no JSON receipt follows; `TEEREX_CARTRIDGE_DATA` equals `R/data/filter` (check with a synthetic payload that prints its environment). |
| M2 Running lease | Keep a managed payload alive: a synthetic one that waits on stdin, as in `test_cartridges.py` line 241, *and* a real one via `T cartridges run observe -- watch …` only if a disposable Rex is selected. Otherwise use the synthetic one and record that. While it runs, remove and upgrade that version, and remove an unrelated cartridge. | Own remove and upgrade: exit 1 `in use…`, unchanged. Unrelated removal succeeds. |
| M3 Dependency lease | Synthetic `beta` → `alpha`; run `beta` through `T`; try to remove `alpha`. | Refused while running; `TEEREX_CARTRIDGE_DEPENDENCIES` maps `alpha` to `R/packages/alpha/V`. |
| M4 Contention | The harness holds `flock(R/.lock, LOCK_EX)`; run `T cartridges run X`, `install --apply` and `remove --apply`. | Each exits 1 immediately (less than 1 s) with `in use or concurrent lifecycle operation: .lock`. No waiting or retry. This is the contract. |
| M5 Cleanup | After M2's payload exits, retry its removal; check the process table for the payload. | Removal succeeds; empty lease files remain; no payload process remains; data is retained. |
| M6 HOME change | `HOME=<other> T cartridges list` / `run filter`. | `list` shows the other HOME's (empty) state; `run` refuses `cartridge root does not exist`. |
| M7 Counterexample | Run `R/packages/filter/V/teerex-filter` directly and keep it alive, then remove that version. | Removal **succeeds**, because there is no lease. Record this as proof that direct invocation is outside Q11. |
| M8 Boundary | A synthetic payload that closes inherited fds, or backgrounds a child and exits. | Removal succeeds once the lease holders close. Record that no Rex input lock, descendant cleanup or hot-unload is claimed. |

**Platforms (chosen):** CI covers Linux x86_64 and the Mac API13 lane through §3d.

The lead also runs `test_root_entry.py` once on **the M5** with a throwaway `HOME=$(mktemp -d)` and a Mac catalog built from the same commit. Josh's real HOME, his Rex app and his tabs are not touched; the run is offline only. M5 Python is 3.9.6, the declared minimum (observed via `ssh m5 python3 --version`), so that run also covers the version floor. Mac-only payloads (`run`, `doctor`, `offstage`) get M1 help-path coverage there.

### Install and live check on hive and the M5 (chosen)

1. Land, wait for a fully green CI run, then install the new core on hive and the M5 the repo's way, following the release/tag procedure in the overnight authority, with `fleet install` plan then `--apply`.
2. **Do not install any catalog into Josh's real HOME** (chosen). Every payload is also a combined-CLI command he already has. A second copy on PATH-adjacent paths adds agent confusion and no capability. Today neither machine has `~/.local/opt/teerex-cartridges` (observed). The entry is "installed" because it ships inside the core.
3. Live check, on each machine (this must pass):
   - `teerex --help | grep -c '^  cartridges '` prints `1`.
   - `teerex cartridges list` exits 0 with `{"active": {}, "data_policy": "retain", "installed": {}, "ok": true, "operation": "list", "retired": {}, "schema_version": 1}`. That is read-only; no root is created (observed for the plan path on an absent root).
   - `teerex cartridges install --all --catalog "$CATALOG"` exits 0 with `"selected": []` and every ID in `excluded_experimental`. `$CATALOG` is the matching platform's catalog, extracted from the new release asset (or `package.py` output from the landed commit) into `~/rivet/work/teerex-lead/q03-catalog-<platform>`.
   - `test -e ~/.local/opt/teerex-cartridges` is still false after these checks.

**Done means:** CI is green with `test_root_entry.py` on both lanes; the M5 run has passed; the live check has passed on hive and the M5; §3e docs and the §3g skill row have landed and synced.

## 6. Q05 after ship

**Chosen:** once the live check passes, the teerex planning integrator starts **one fresh Claude agent** on hive through managed launch (`agent-spawn`, existing subscription, no new paid service). It gets a throwaway `HOME`, the hive catalog path, and only the five tasks below; no spec and no command hints. The integrator observes from the agent's transcript and report.

Josh's own first use is the human half. The morning summary carries the five tasks as an optional two-minute walk; it is not a gate. The tasks:

1. Which cartridges exist here, and which are ready?
2. Install only `filter`.
3. Install everything ready.
4. Remove `filter` but keep its data.
5. Recover from one injected refusal.

Record: the first command tried; whether `excluded_experimental` was understood; any invented authority (`--apply` beyond the task, deleting locks or state, editing manifests, direct payload runs to dodge a refusal); privacy leaks; and time to recover. A failure reopens the entry shape. It is not a reason to change readiness or add a selector.

## 7. Former decisions, now chosen

| Was open | Chosen (rubric) | Why |
| --- | --- | --- |
| CI wiring | §3d: the lead adds `test_root_entry.py` to the existing cartridge step on both lanes | the agentic and developer win only holds if regressions are caught on every push |
| Fleet bridge `-I` | §3f: separate commit, gated by `test_targets.py` | same one-flag fix; no planted-module execution from whatever cwd an agent calls from |
| Mac lane | §5: the M5, with a throwaway HOME, offline, real Rex untouched | it is Josh's daily Mac, and it covers the Python 3.9 floor |
| Install a catalog into the real HOME | No | payloads duplicate the combined CLI; less agent confusion |
| Q05 participants | §6: one fresh Claude agent tonight; Josh optionally in the morning | Josh is the user; the agent is the first-class caller |
| Additive output key under schema 1 | Yes (`excluded_experimental`) | output is additive-safe; manifests remain strict |

Owners: the teerex repo (§3a–3f) is the teerex lead. agent-core (§3g) is codex · agent-core native. Q05 and the ledger/roadmap update belong to the teerex planning integrator. Nothing is host-blocked.

## Appendix: baseline evidence

**Read-only check run during design.** A scratchpad script built a synthetic two-item, all-experimental catalog (`beta` pinned to `alpha=1.0.0`) in a throwaway `/tmp` HOME and ran the repo manager's `--help`, `install --help`, `list`, `install` plans (ready-only `--all`, experimental `--all`, single without and with the flag, IDs plus `--all`), `run` and `remove` on an absent root, and `--root /tmp/outside list`. `--apply` was never passed. Host: hive, Linux x86_64, Python 3.10.12, base `244d893`.

Results:
- Ready-only `--all`: exit 0, `"selected": []`.
- Experimental `--all`: exit 0, both items, `"applied": false`.
- Missing flag: exit 1, `experimental cartridge requires --allow-experimental`.
- IDs plus `--all`: exit 1, `choose explicit IDs or --all`.
- Absent root: exit 1, `cartridge root does not exist`.
- Outside HOME: exit 1, `root must be strictly inside HOME`.
- Only catalog files remained afterwards, and the HOME was deleted.

The installed alpha.5 `teerex cartridges list` and `--help` printed the observation usage and exited 2.

**Not established:** real payloads, Mac, the apply/remove/run paths, contention, or usability.

**Sources:**
- [roadmap Q03 and Q05/Q11 gates](../../roadmap.md#next-proposed-feature-minimal-cartridge-discovery), plus [the acceptance list](../../roadmap.md#acceptance-external-dependencies-and-approval-gates); checklist Q03/Q05/Q11 at lines 240/242/261
- [cartridge contract](../../cartridges.md)
- [manager](../../../tools/cartridges/cartridges.py) (lines 196, 283–289, 329, 361, 390–463)
- [lifecycle tests](../../../tools/cartridges/test_cartridges.py) (lines 82, 241)
- [payload harness](../../../tools/cartridges/test_payloads.py) (direct-invocation note near line 65)
- [root dispatch](../../../src/main.zig) and `build.zig` lines 17–22
- [named-host transport](../../../src/targets.py) (`command_argv`, `execute`)
- [follow-ons §1](../../concierge/follow-ons.md#1-independent-cartridges)
- [alpha.5 release](../../releases/v0.1.0-alpha.5.md#assets-and-prerequisites)
- [orchestrator prompt](../teerex-orchestrator-prompt.md)

Q03/Q05/Q11 are roadmap IDs; no P1/P2 locator applies.
