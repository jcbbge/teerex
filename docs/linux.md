# Linux x86_64 support

**Current alpha.5** ships Linux x86_64 observe/compare/watch, low-level spawn/send (including bounded stdin), offline filter/cache and maneuver libraries, jobs/API13, read-only adapters/API10–13, seven independent experimental cartridges and onboarding. The combined CLI additionally supplies [surfaces](../items/surfaces/README.md), [boards](../items/boards/README.md), [managed agents](../items/agents/README.md), [structural recovery/manual update inventory](../items/recovery/README.md), named command hosts and [fleet installation](fleet-install.md). Python3.9+ is required by the Python-backed operating layer, not legacy native direct-socket tools. Runtime run/doctor/offstage remain Mac-only. Use [current setup](concierge/setup.md) and the [alpha.5 release support matrix](releases/v0.1.0-alpha.5.md#commands-and-tested-support). Numeric API acceptance and named-host success do not resolve issue #10's attached mixed-host topology or intermittent #12. The older supervisor-only evidence below remains historical, not final-release or hive certification; frozen archives are unchanged by later docs.

The Linux transport implements the same supervised-child contract used by macOS: EOF stdin, explicit environment/argv, separately drained stdout/stderr, at most 4096 retained diagnostic bytes, monotonic deadlines, SIGINT/SIGTERM cancellation and invocation-owned process-group cleanup. Linux uses `poll` and `waitid(WEXITED | WNOHANG | WNOWAIT)` rather than Darwin's kqueue. The leader remains unreaped until the final group signal, reserving its PID/process-group ID against reuse. Readable bytes are drained even when a pipe also reports hangup; only a zero-length read establishes EOF.

The receiver still owns stdout retention and framing. A receiver's `isComplete()` requests cleanup, not command success. Escaped/re-grouped descendants, teerex SIGKILL/crash and kernel stalls are not covered by a whole-tree cleanup guarantee. Unknown stderr byte totals remain null when EOF was not observed. Platform support does not change capture-prefix bounds, process/report provenance, non-atomic snapshots, unknown comparisons or the prohibition on inferring task completion from retained `done` reports.

## Build and asset contract

Use Zig **0.15.2**:

```sh
zig build -Doptimize=ReleaseSmall -Dtarget=x86_64-linux-musl
zig test src/child_test.zig
file zig-out/bin/teerex
readelf -h -l -d zig-out/bin/teerex
```

The Linux release name agreed with the installer is `teerex-TAG-x86_64-linux.tar.gz`, containing only flat regular `teerex`, `README.md` and `RIGHTS.md` files, with an external `SHA256SUMS`. The executable is static ELF64, little-endian, x86-64; there is no ELF interpreter or dynamic section and no host glibc dependency. Rex remains a separate executable on `PATH`, with its own dependencies. No minimum Ubuntu release/kernel is established by these tests; the tested kernel is 6.1.189+. No pidfd support or `/proc` parsing is required by the supervisor itself.

The integrated shared CLI accepts `.linux` alongside `.macos` for `observe`/`watch`, and separately wires `spawn`/`send` through the same supervisor. Linux `run` and doctor runtime remain unavailable. The API10–13 compatibility gates and spawn/send behavior have their own contracts and combined validation; the historical supervisor-only receipt below does not establish them. A successful Linux `--help` or offline `compare` alone is not proof that a live command works. See the [current alpha.5 release](releases/v0.1.0-alpha.5.md) for its final executable identity and coverage; alpha.3 was the earlier combined-toolkit checkpoint.

## Runtime validation — 12 November 2026

Base: `83661ee4e5247349888fdc6931c322dc1b08db26`, plus this supervisor and exactly two scratch-candidate guard edits accepting Linux for `observe` and `watch`. No API gate, Lua, capture, process, report or comparison changes were made. The integrated release must rerun these checks against its final executable; this record does not claim a Linux asset has been published.

Test executable: **214656 bytes**, SHA-256 `092ef219dee32418ff09d8d61f77048697d672027262a649045881472a004d74`. The target is `x86_64-linux-musl`, ReleaseSmall. `file` reports statically linked/stripped; `readelf` reports ELF64/little-endian/AMD x86-64, no `INTERP`, and “There is no dynamic section in this file.”

Real official Rex **0.1.0-preview.16**, API **13**, commit `aa2db1b21261b479a550559fb70e2c3a66c07ba2`, build `2026-11-11T21:35:56Z`, was downloaded from the official preview feed's immutable Linux amd64 archive URL. Archive SHA-256 was verified as `90b2429036d26f317aaac2490d014e07c9351b0b994b1329afce94b8ad4d333c`; the extracted executable is `68dfccc30a398f7215a1455ea5e6aca6c37ddaaf9a4fe84abc54b3d1c8b9e526`. Rex was not bundled or redistributed.

Executed checks:

- Native **Debian 13 x86_64**, Linux **6.1.189+**: all **27** existing public observe/compare/watch tests passed in three fresh disposable-server runs, **13.644 s**, **13.438 s** and **13.737 s**. All four direct supervisor tests passed too.
- A SHA-verified official **Ubuntu Base 24.04.5 LTS amd64** userland in a disposable chroot on that **same orb kernel**: the identical executable passed all **27** public tests in **13.816 s** and **13.763 s**, and all four supervisor tests. Python/procps came from Ubuntu's repositories, and `/proc` and `/dev` were mounted for the real Rex fixtures. This is Ubuntu userland validation, not a separate Ubuntu kernel, VM or hive installation. Rootfs archive SHA-256: `e77b6f10c2590cef872b33ee9f635a0e3fd1f57fb074c0e52b5c7f56147a0c86`.
- Disposable **arm64 macOS 27.2** (verified with `sw_vers`), real verified Rex preview.16/API13: the cross-built Mac executable passed **27** observe/compare/watch checks in **13.733 s** and **13.945 s**, **11** run checks in **15.326 s** and **15.416 s**, and all four direct supervisor regressions. Native Zig's build runner failed to link against the satellite SDK; the runtime checks used the successful Linux-to-Mac cross-build, not an invented native-build success.
- The installer owner independently exercised the exact Linux source binary as an explicitly local three-file archive: checksum/ELF/help validation, all seven installed offline comparison tests, fixture upgrade, rollback to the identical source SHA/help, explicit removal, and unchanged profiles/Rex configuration/launcher sentinels. That test contacted no Rex server and does not imply a public Linux download exists.

The public suite exercises explicit target isolation/read-only behavior, process cwd versus retained directory reports, missing evidence, retained `done` versus actual exit 7, Unicode/encoded-byte boundaries, hidden changed tails, malformed/fragmented/oversized frames, no-autostart, watch predicates, deadline/cancellation including poll gaps, resistant descendants and unchanged observed targets. The four direct ABI regressions cover more-than-pipe-capacity output, exact binary final bytes and nonzero exit, bounded stderr totals, closed pipes with a still-running child, normal leader exit with descendants retaining pipes, cancellation and consuming the signal for bounded cleanup.

To reproduce the public checks on the integrated Linux source, put the verified Rex executable on `PATH` and run:

```sh
python3 -m unittest discover -s items/observe -p test_observe.py -v
```

The suite starts and cleans up its own disposable foreground Rex server with an isolated socket/state directory and `/dev/null` config. It never uses the default/personal server. No new daemon, service, operator configuration or install is needed. The pre-change executable reproducibly refused live Linux observation with `ObserveRequiresMacOS`, despite already building as ELF.

## Evidence boundaries

No command in this validation accessed Joshua's **M5 or hive**. Their versions/results in the setup brief remain agent-reported, not directly validated here. Ubuntu userland testing does not prove hive's wrapper, environment, socket permissions, actual kernel, Rex installation or running terminals. All workers/messages on Joshua's machines must follow his Rex/teerex-only policy; this coding work does not authorize VPS settings/install changes or new headless services there. API10–13 compatibility verification remains separately owned.
