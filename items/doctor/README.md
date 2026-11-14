# doctor

[Operator/agent addendum: Who, What, When, Where, Why, How](../../docs/concierge/features.md#6-doctor-narrow-advertised-compatibility-and-drift) covers current alpha.5 use, platform/API support, verification, privacy and lifecycle. [Install/upgrade current alpha.5](../../docs/concierge/setup.md); runtime supports macOS and Linux x86_64 with API10–13. A separate [experimental doctor cartridge](../../docs/cartridges.md) ships on Mac. Discovery remains distinct from permission and behavior certification.

**Experimental, read-only compatibility diagnosis for observe/watch/run with numeric API acceptance 10–13 and concrete selected-shape checks.** Numeric acceptance is not certification of every build in that range. This is the narrow Phase 3 #8, C25–C28 slice, not a generated client, a generic schema validator, a ready independently packaged cartridge or permission to use discovered methods. Historical review and non-Rex material are unchanged.

## Invoke and interpret

The shared CLI includes this module. Build with Zig **0.15.2** from the repository root:

```sh
zig build -Doptimize=ReleaseSmall
./zig-out/bin/teerex doctor --help
./zig-out/bin/teerex doctor --socket /absolute/path/to/existing/rex.sock
```

The socket is absolute. The combined root can supply an omitted socket using the [shared defaults](../observe/README.md#socket-defaults-and-latest-capture); defaulted diagnosis includes `socket_source`. Explicit sockets retain the original packet shape. Standalone doctor still requires its explicit socket. There is no implicit terminal selection or missing-server autostart. `REX_SERVER`, `REX_SESSION`, `REX_BLOCK` and `REX_CLIENT` hints are removed from child environments. All Rex calls explicitly pass `--autostart=false`, the selected Unix endpoint, `--timeout 2s` and `--color never`. The CLI is resolved once through `PATH`, or selected with global `teerex --rex /absolute/rex doctor ...` or `TEEREX_REX=/absolute/rex`. Every diagnostic packet includes `rex_executable` (null when resolution fails), and `cli` contains its discovered version or null with diagnostics. Use a deliberately selected, trusted Rex executable. A malicious executable or Rex's own runtime/configuration is outside teerex's guarantee.

Doctor performs at most eight serial Rex invocations:

1. `version --json` records the **CLI's** version, platform, API revision, commit/build identity and dirty flag.
2. `api call server.version` records the independently reported **server** identity and behavior-tests only this version query.
3. `api describe METHOD --json` inspects **only five** descriptions: `server.version`, `com.superlogical.terminal.format`, `.process`, `.pwd` and `.program_status`.
4. One fixed `do -e` script checks the types of `rex.call`, `rex.json.encode`, `rex.sleep` and `rex.exec.start`. It never calls `rex.exec.start`/`rex.sleep`, supplies arbitrary code, starts an argv or reads terminal content. Executing fixed introspection and encoding JSON is not execution-behavior validation.

Descriptions are inspected only after both identities report integer API revisions **10–13**, with overlapping reported minimum/maximum API support. Missing revision means 0, per the observed version contract; outside-range or nonoverlapping support is refused with the **actual CLI/server revisions and minimums** in `api_revision_refusal`. Different CLI/server versions/builds set `cli_server_mismatch=true` and `client_server_check="mismatch_review_selected_client_and_server"`; they are not automatically treated as incompatible if the range and selected shapes match. No restart, downgrade, download, installation, config edit, terminal input, ownership change, session enumeration/creation or upgrade is attempted or recommended by doctor. Tests separately create disposable servers; the command does not. There is no update/restart prerequisite: updating Joshua's current API10 server would close existing panes, and is not authorized by compatibility discovery.

The explicit checks cover the selected invocation method, top-level argument/output object types, absence of additional required arguments the shipped collectors do not supply, and advertised field types actually consumed by those collectors. Nullable process/report owners and last-exit evidence are checked. This deliberately does **not** evaluate arbitrary schemas, resolve references, interpret prose/examples as code, validate all JSON Schema constraints, or certify data/behavior on a real terminal. It does not inspect `session.view`, write/ownership/layout APIs, unrelated creator methods or generic help/catalog exports.

## JSON and exits

Every normal diagnostic result is one JSON object with `schema_version=1`, `kind="rex_compatibility_doctor"`. Usage errors return **2** with no JSON; unsupported platforms other than macOS/Linux and exceptional allocator/output failures can return **1** without a packet. Always check the exit status and parse the entire object. Runtime diagnosis runs on macOS and Linux. `operation_platform_support` marks the Mac-only `run` operation `not_applicable` on Linux with a reason; binding discovery remains a shape check, not Linux execution support. Offline help/argument/baseline rejection works on other targets.

- `cli` and `source` distinguish the local CLI from the reported server, with null for unavailable identities. `cli_server_same_build` compares reported fields, not authenticated host/process identity. An explicit or forwarded socket is not proof of locality.
- `accepted_api_revisions={"min":10,"max":13}` states numeric policy. `api_revision_matches` is false for unsupported/legacy revisions or nonoverlapping support, null if either identity could not be obtained. `api_revision_refusal` names found revisions/minimums and the accepted range; it is null when no range refusal is established.
- `methods` contains only the five selected methods, each with `advertised`, `schema_status`, `descriptor_sha256`, `behavior_tested` and `error_name`. A successful method description is advertised evidence; failed discovery remains **unknown**, not a fabricated assertion that a method is absent. `selected_shape_matches` is limited to the explicit checks above, not full schema validation.
- `lua_bindings="shape_matches_not_executed"` means the four values were functions. `lua_binding_shapes` reports each function's actual inspected type, including a missing execution table/binding as `nil`. It proves neither that `rex.exec.start` works nor that callbacks, timeout, process groups or cleanup behave correctly.
- `operation_advertised_requirements_met` separates `observe`, `watch` and `run`: observation needs the five selected descriptors plus `rex.call`/JSON encoding; watch additionally needs `rex.sleep`; run needs the version descriptor, call/encoding and `rex.exec.start`. An absent execution binding does not falsely invalidate observation; a bad terminal descriptor does not falsely invalidate local execution's advertised requirements.
- `advertised_requirements_met=true` and exit **0** mean only that the numeric range and all selected advertised shapes/bindings matched, with no supplied baseline drift. **`behavior_certified=false` always.** The version query alone has `behavior_tested=true`; terminal methods do not. `observe_watch_behavior="not_tested_no_terminal_reads"` and `run_behavior="not_tested_no_program_started"` make this boundary machine-readable. `recorded_build_behavior` points to the exact tested-build matrix below rather than deriving behavior coverage from a revision number.
- `permission="not_assessed_discovery_is_not_authorization"` always. Method availability, program status, owner fields or exit zero never grant input, execution, takeover, filesystem/network/credential or export authority. Doctor supplies no enforcement broker or sandbox.
- `offstage="not_assessed_contract_not_included"` deliberately excludes offstage from this combined first release's doctor checks, as agreed with its owner. Its known create/identity/reconnect/close/absence-verification requirements are not covered by an observe/run pass; they require a separate additive compatibility check. Doctor does not probe them or imply that a hidden PTY is isolated or descendant-safe.
- `diagnostics` gives a stage and error name without copying terminal contents, bulk vendor schemas or raw backend diagnostics. Descriptors remain in memory and only hashes are emitted. Endpoint paths, version/build identities and caller-saved packets can still be sensitive; they are escaped, **not redacted**.

Other exits: **1** incompatible/unknown or changed baseline; **124** total deadline; **130** SIGINT; **143** SIGTERM. No output silence or closed pipe becomes success. Missing Rex, missing server, invalid/truncated/oversized discovery and binding failures return truthful unknown/incompatible packets without remediation.

`--timeout-ms` defaults to **5000**, range **100–60000**. One monotonic budget spans all subprocesses, including CLI version discovery. Each stdout response is capped at **128 KiB**; the shared supervisor bounds backend stderr separately to 4096 bytes. Parsed descriptions and buffers are finite across eight calls, not streaming unbounded retention. The budget is not a hard real-time guarantee: owned-group cleanup/drain can add about 500 ms plus scheduling, final stdout backpressure and exceptional OS waits. SIGINT/TERM use `src/child.zig` to stop only the invocation's owned Rex process group; they do not stop the selected Rex server or any existing terminal. Detached descendants, SIGKILL/crash of teerex and a malicious Rex implementation are outside that cleanup contract.

## Version/schema identity and revalidation

`adapter_identity` hashes the selected API10–13 contract marker, exact selected endpoint, normalized CLI/server version fields, the five full descriptor-response hashes and binding result, only when all selected checks complete. The marker deliberately invalidates older API13-only doctor receipts even on an otherwise unchanged API13 endpoint. No identity is invented for partial/incompatible evidence. Description hashes deliberately include prose and byte ordering/whitespace: even a nonsemantic descriptor change conservatively invalidates a receipt. The identity is not a signature, unique server-instance ID, permission token, cache or behavior certificate. A server restart with identical reported identity/descriptions is indistinguishable, and discovery is serial rather than an atomic snapshot.

To compare with an explicitly saved earlier receipt:

```sh
./zig-out/bin/teerex doctor --socket /absolute/path/to/existing/rex.sock \
  --baseline /absolute/path/to/prior-doctor.json
```

Doctor reads at most 128 KiB, validates the doctor packet kind/schema and complete identity, and never modifies that file. `identity_status` is `not_compared`, `unchanged` or `changed_or_unknown`. Drift/unknown evidence sets `adapter_revalidation_required=true` and exit **1**, even if today's selected advertised requirements match. Without a baseline, a completed advertised check is not a claim that old receipts remain valid. Revalidation means reviewing the drift and rerunning the relevant behavior suites on the intended environment before deliberately adopting a new receipt; doctor never rewrites adapters or blesses a new build by saving a cache. It is a diagnostic, not an automatic gate around other subcommands. The shipped collectors retain their own API/target checks.

## Integration and lifecycle

`items/doctor/main.zig` exports `pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8`; args excludes executable/subcommand. The shared CLI already imports `rex_doctor`, connects its `supervised_child` import to `src/child.zig`, and dispatches `doctor` to `run`. No other module imports, generated assets, embedded vendor material or external library dependency is required. The caller provides an invocation-lifetime allocator, as for `run`; leaf allocations remain valid until that invocation ends. Shared sources/build wiring are not owned or edited here.

This source follows the repository's development build/review workflow, not a global installation or Rex plugin hook. To upgrade, review/build the new teerex source and rerun the tests; never upgrade Rex automatically to make a check pass. To stop using doctor, stop invoking it; it creates no service, cache, file or config entry to uninstall. Individual experimental cartridge installation/removal uses the separate cartridge manager; it changes code selection, not diagnosis scope or permission. Rex remains a separately acquired proprietary dependency, not bundled. Project licensing remains [unselected](../../RIGHTS.md).

## Tests and validation — 12 November 2026

Public tests consume only the CLI via `TEEREX_BIN`:

```sh
# Native argument/baseline/platform checks; never launch Rex.
TEEREX_BIN=/absolute/path/to/teerex TEEREX_OFFLINE_ONLY=1 python3 items/doctor/test_doctor.py -v
# Disposable macOS/Linux server and controlled transport/schema faults. Explicit test Rex on PATH.
TEEREX_BIN=/absolute/path/to/teerex python3 items/doctor/test_doctor.py -v
```

Runtime tests start a private `/tmp` Unix server with restore disabled, `/dev/null` config and separate state, then stop it. No Joshua machine, default/personal server or VPS is contacted. Tests verify the unchanged session list and narrow read-only call surface, poisoned target hints, unchanged/changed baseline identity with file preservation, CLI/server/legacy revision mismatch and nonoverlapping support, missing executable/server, wrong method/field type/new required arg, independently absent execution/sleep bindings, malformed/oversized descriptions, and a closed-pipe TERM-resistant owned transport group under deadline/SIGINT/SIGTERM. Injected API10/11/12/13 identities test numeric acceptance only, **not** actual old-build behavior; the actual binaries below supply the independent runtime matrix. Synthetic faults are not claims about ordinary Rex failures.

### Exact disposable-build matrix

All builds are **darwin_arm64**, tested on disposable **macOS 27.2**, not Joshua's M5. Official archives were checksum-verified before execution. Source of older pins/checksums is each immutable `https://pkgs.superlogical.com/rex/nix/preview/VERSION.tar.gz` archive's `rex/sources.json`; preview.16 also matched official release-channel metadata.

| Rex build / API | Exact commit / build timestamp | doctor suite | Immediate candidate observation / execution suites |
| --- | --- | --- | --- |
| `0.1.0-preview.13` / **10** | `1b6654811346488b696ded8f3c7e6701c57242f1`, `2026-11-03T21:32:55Z` | **9 executed**, 16.783 s | **28 + 11**, passed twice |
| `0.1.0-preview.14` / **12** | `7e460d02f51573990bfcdc6c44a5606d11c7d47a`, `2026-11-09T21:00:41Z` | **9 executed**, 16.848 s | **28 + 11**, passed twice |
| `0.1.0-preview.16` / **13** | `aa2db1b21261b479a550559fb70e2c3a66c07ba2`, `2026-11-11T21:35:56Z` | **9 executed**, 16.902 s | **28 + 11**, passed twice |
| **11** | No actual API11 binary established | Numeric fault controls only | **Unverified** |

Each Mac doctor run has one additional skipped non-Mac guard. Native Linux executes **3 offline checks**, with **7 explicitly skipped runtime checks**; this is not Linux runtime support. Linux portability is a separately assigned implementation, not a platform-preference question or a reason to change machines/settings here. Zig 0.15.2 native and arm64-macOS doctor leaf builds and formatting pass. Leaf runtime checks use a temporary CLI entrypoint matching the integration signature; the shared owner must rerun after integration. Doctor is not included in the immediate compatibility-only release candidate.

Targeted **mixed-pair smoke** also passes CLI12 → server10, CLI13 → server10 and CLI10 → server12: exact Unicode argv output/real exit, target observation, quiet watch deadline, actual server revision propagation and independently reported doctor CLI/server identities. Those are focused cross-version smoke checks, **not** full mixed-pair lifetime regressions. On the same actual API10 server the original API13-only doctor exits1 while this leaf exits0; on API13 both pass without a baseline, while the new contract correctly invalidates the old doctor receipt. Doctor's final test binary SHA-256 is `cb11045480b0f49a2e7aaec604c0bb4b8b121bbfaa94ad71ccf3e8dbb610bbd4`. These three doctor logs, before/after/baseline controls, mixed-pair results and file hashes were retained privately as `doctor-api10-13-evidence.tar.gz`, SHA-256 `ae7f837e1ff3098815aef49169c2a7c49a685ef7f2727384b1fd47c229ed40e3`.

The immediate candidate is the integrator's exact **300888-byte** executable, SHA-256 `551243190d91d529fd551a39c38c3b1fbfb62cc6f4dd90b44baff83ab7ced8af`, transferred with archive SHA-256 `4412e177195015896ee0aba1ea42a168355c65e80226e07f9dff654aa7fff84e`. It preserves actual revision10/12/13 instead of fabricating13. All observation/compare/watch and execution suites passed on each matched CLI/server build above. Run coverage exercises actual `rex.exec.start` callbacks, literal argv/cwd/EOF, binary/Unicode/retention boundaries, actual zero/nonzero/signalled exits, command timeout, cancellation and scoped owned-group cleanup—not merely `type(...)` introspection. The recorded six logs plus CLI/server version identities, archive hashes, selected descriptor fingerprints/type metadata and log hashes were transferred privately as `compat-api10-12-13-evidence.tar.gz`, SHA-256 `588a8d8d83c7fb65f710079aa3bcdfef8446aac80d11acd98c354e6efdf6aa0f`. No vendor binary/schema bodies are bundled with that evidence or source.

The setup agent's **supplied actual M5 observation evidence** is separate: `0.0.1793645657-gd018d2`, API10, returned all five reads with only the old pin removed. This is not the preview.13 build tested here, nor independent M5 run/exec validation. Joshua reports current Rex Beta app build1925 bundles preview.14/API12; preview.16/API13 is a separate CLI-channel build, not an app-update prerequisite. No existing personal server was restarted, updated or reconfigured. API11, other builds with the same revision, actual M5/hive execution, offstage and installation remain outside this validation.

Source mapping: [original Phase 3 #8/C25–C28 and V02/V03/V08](../../docs/planning/teerex-pdf-work-inventory.md), [observe collector](../observe/collect.lua), [run executor](../run/execute.lua), and [original API provenance](../../research/provenance/README.md). No historical scores or non-Rex assignments were altered.

## Linux and executable receipt update

The current source executes the full doctor suite on a private Linux Rex server as well as macOS. The historical matrix above records earlier Mac-only source; it does not describe the current Linux gate. Client/server build mismatch is an explicit diagnostic flag, independent of advertised compatibility. Missing identity stays unknown. No new macOS-only probe is attempted on Linux; the existing fixed descriptor and binding queries are portable, while run's platform applicability is reported separately.

## Configured-host health

`teerex doctor --all [--config ~/.config/teerex/hosts.json] [--json]`
checks each configured host independently. It reports the installed managed build
against `<home>/rexconfig/<host_id>/teerex/build-pin.txt`, the selected Rex server
version/API, `rexconfig/install --check`, and enabled Claude/Codex per-launch hook
profiles plus the installed hook adapter. It does not inspect private transcripts
or require global harness hooks; teerex injects these adapters at launch.

Each failed check includes a suggested command; nothing is repaired automatically.
An unreachable or invalid host produces one red host check and does not suppress
other hosts. JSON emits `kind: fleet_doctor`, `ok`, and `hosts[].checks[]` with
`check`, `ok`, `detail`, and `fix`. Exit 1 means at least one red check.
A host may set an absolute `rexconfig` path to check a separate configuration
checkout; the default is `<home>/rexconfig`. Pin-only drift appears once, under
the build check. Configuration drift is reported separately.
