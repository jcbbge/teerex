# adapters

[Operator/agent addendum: Who, What, When, Where, Why, How](../../docs/concierge/follow-ons.md#3-selected-read-only-adapters-local-policy-and-receipts) covers current alpha.5 prerequisites, identity/policy, use/verification, privacy and lifecycle. [Current setup](../../docs/concierge/setup.md) and [separate experimental cartridge packaging](../../docs/cartridges.md) are shipped, not pending integration. Mac/Linux integer API10–13 acceptance is not every-build certification. Adapters was absent in alpha.3 and is not a host permission system or authenticated audit history.

**Experimental Rex-specific read-only descriptor generation, local allowlisting and action receipts.** This is a follow-on to frozen/public alpha.3, not part of that release. It extends original Phase 3 #8/C25–C28 for five selected methods; it is not an unrestricted generated client, MCP server, generic agent runtime, credential broker, host permission system or ready independently packaged cartridge. The historical inventory, non-Rex handoff and doctor are unchanged.

## Supported surface

| Tool | Fixed Rex method | Tool arguments |
| --- | --- | --- |
| `rex_version` | `server.version` | `{}` |
| `rex_capture` | `com.superlogical.terminal.format` | Exact `session_id`, `block_id`, integer `max_bytes` 256–65536 |
| `rex_process` | `com.superlogical.terminal.process` | Exact `session_id`, `block_id` |
| `rex_directory` | `com.superlogical.terminal.pwd` | Exact `session_id`, `block_id` |
| `rex_status` | `com.superlogical.terminal.program_status` | Exact `session_id`, `block_id` |

`generate` obtains independently reported local CLI/server versions and **five actual installed method descriptions**, validates the selected input shapes, and specializes fixed narrow templates into JSON tool definitions (`name`, `description`, `inputSchema`). This is deliberately template-based generation, not a JSON Schema compiler. It checks object input/args, no additional properties, only supported required arguments, supported types for the two supplied format fields, object outputs and the capture content string type. Unknown input-schema constraints, references, newly required arguments or constraints on the supplied format properties refuse generation rather than silently weaken validation. Unused optional format fields are not exposed. No arbitrary discovered method, descriptor prose/example or supplied code is executed. Model-facing descriptions are teerex-owned text, not copied vendor prose. Vendor descriptor bodies remain in invocation memory; output retains hashes, not their schemas/text.

A generated capture always sends `format="text"`; `max_bytes` includes the content string's JSON quotes. Two bytes are reserved before calling Rex and returned content is independently checked against the requested encoded budget. This is a **screen-and-scrollback prefix**, not a guaranteed latest viewport. The raw result's continuation `id` means partial output; no continuation method is exposed. Raw process/directory/status objects may contain more metadata than teerex observe's curated evidence packet. They are not normalized, redacted, classified or assumed fresh. Only object shape and capture content/budget are checked on returned values, not full output-schema validation. Use `observe` for its narrower normalized evidence contract.

## Build and invoke individually

Source builds require Zig **0.15.2**; released installation does not. Runtime requires supported macOS or Linux, a deliberately chosen trusted `rex` on `PATH` (or combined root `--rex ABS`), and an explicitly selected already-running Unix endpoint. Accepted integer CLI/server API revisions are **10–13** with overlapping reported support. Numeric acceptance is not behavior certification, including for other builds reporting the same revision. No install/download/restart/update/configuration operation is performed by this item. A forwarded Unix socket is not proof of locality. Malicious Rex code or its own runtime/configuration is outside this wrapper's protection.

The leaf exports `pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8`, excluding executable and `adapters` prefix. The combined CLI already imports `rex_adapters` with `supervised_child` and dispatches `adapters` to `run`. This optional standalone development build uses the same source; current released core/cartridge installation needs no compiler:

```sh copy Copy Leaf Build
# Linux; replace with -target aarch64-macos on Apple silicon (also for cross-build).
uv run --with ziglang==0.15.2 python -m ziglang build-exe -O ReleaseSmall \
  --dep supervised_child -Mroot=items/adapters/main.zig \
  -Msupervised_child=src/child.zig -femit-bin=./teerex-adapters
./teerex-adapters --help
```

Standalone invocation omits `adapters`. The remaining examples use the integrated current shared CLI; alpha.3 did not dispatch this command. Deliberately replace the socket and file paths, save only successful complete JSON, and protect private files before creating them:

```sh copy Copy Generate Command
umask 077
teerex adapters generate --socket /absolute/path/to/existing/rex.sock > local-adapter.json
```

Generation does not authorize calls and produces no policy. A caller deliberately supplies a separate local policy with schema version 1, kind `rex_adapter_local_policy`, the generated `adapter_identity`, and exact allow entries. This example allows only server version and one terminal's capture; replace the identity and full IDs with reviewed values:

```json copy Copy Local Policy
{
  "schema_version": 1,
  "kind": "rex_adapter_local_policy",
  "adapter_identity": "REPLACE_WITH_GENERATED_64_HEX_IDENTITY",
  "allow": [
    {"tool": "rex_version"},
    {"tool": "rex_capture", "session_id": "session:11111111-2222-3333-4444-555555555555", "block_id": "block:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"}
  ]
}
```

No wildcard/focus/prefix targets or default allow exist. An empty `allow` denies all actions. Version grants must not contain terminal IDs; terminal grants require full exact `session:UUID`/`block:UUID`. Capture's allowed byte range is fixed in the adapter, not configurable through policy. This policy is evaluated for this invocation only; it is not persistent role/permission state or evidence of a human approval decision. Anyone able to edit these files or bypass this executable can bypass the local convention.

Save the tool arguments separately (at most 4096 bytes): `{}` for version, or the exact terminal IDs plus `max_bytes` for capture. Unknown arguments—including invented conditional guards—are rejected before contacting Rex. Call with:

```sh copy Copy Adapter Call
teerex adapters call --socket /absolute/path/to/existing/rex.sock \
  --adapter local-adapter.json --policy local-policy.json \
  --tool rex_capture --arguments local-arguments.json
```

Generation performs at most **seven** serial Rex invocations: CLI version, server version, five descriptions. An allowed call repeats all seven, then performs one selected read. Discovery itself queries version/descriptions, even though a receipt's `dispatch_attempted` concerns only the selected action phase. Denied local policy contacts no Rex executable. Calls always pass explicit endpoint, `--autostart=false`, `--timeout 2s`, `--color never`, and remove `REX_SERVER`, `REX_SESSION`, `REX_BLOCK`, `REX_CLIENT` hints. No session enumeration/creation, terminal write/paste/key, arbitrary argv/Lua, client ownership, layout, close, installer or background process is exposed.

`--timeout-ms` defaults to 5000, range 100–60000. One monotonic budget covers discovery/action subprocesses. Each response and each adapter/policy file is at most 128 KiB. The shared supervisor retains at most 4096 stderr bytes and cleans up only the invocation-owned process group on deadline/SIGINT/SIGTERM, not the Rex server/observed terminal. Cleanup/drain may add about 500 ms plus scheduling; preflight, kernel stalls and final stdout backpressure are not hard-real-time bounded. Detached descendants, SIGKILL/crash and malicious executables remain outside that guarantee.

## Identity, local receipts and limits

A schema-1 `rex_read_adapter` bundle contains the exact endpoint, normalized independently reported CLI/server identity (version, platform, API/minimum, commit, build time, dirty flag), five full descriptor-response SHA-256 fingerprints in the table's order, fixed contract marker and `adapter_identity`. Prose, whitespace/order or schema changes conservatively change that identity. A call first checks saved identity consistency, then compares against **freshly rediscovered** identity. Drift refuses the action; it does not rewrite/adopt the bundle or policy. Deliberately regenerate/review and rerun relevant behavior tests before adopting changed evidence. Doctor receipts are not adapter bundles: doctor's narrow binding diagnostics neither supply raw generation inputs nor gate this item.

Hashes are consistency/provenance aids, not signatures, authenticated host identity or permission tokens. Saved tool definitions are untrusted display data, never dispatch/schema authority: calls use the compiled fixed mapping and validators even if a saved tool definition is edited. Do not treat an arbitrary edited bundle as trusted model instructions. A same-version restart with the same descriptors is indistinguishable. Serial rediscovery is **not an atomic guard**; the server/terminal can change between discovery and action. There is no cache or lease to revoke.

A normal action attempt emits schema-1 `rex_adapter_action_receipt`, including random local receipt ID, client wall time, exact endpoint/tool/target, saved/current adapter identity, actual rediscovered CLI/server identity when available, hashes of exact caller policy/argument bytes, local-policy decision, action dispatch-attempt flag, outcome/error, elapsed time and nullable raw read result. Denial has no current identity/result. Revalidation failure does not substitute saved source as current evidence. A failed/malformed/oversized action yields no fabricated read result. `dispatch_attempted` means the action query phase was entered, not server acknowledgement or program consumption; a deadline/spawn failure may prevent that query from reaching Rex. This is not a complete event recorder; usage/invalid-file/argument/output failures may produce no complete receipt.

Every receipt explicitly says `host_enforcement=false`, `consent_verified=false`, `behavior_certified=false`, `freshness="unknown"`, `atomic_snapshot=false`, and `audit="unauthenticated_local_assertion_no_history"`. A local `allowed_by_caller_supplied_file_only` decision is not a Rex permission grant. Program-status `blocked:permission` requests a decision; it never proves consent. Native block ownership does not exclude other writers; invented conditional fields can be ignored by Rex; a cooperative lock is not revocation. The repository's [actual ownership/write probes](../observe/README.md#c04c07c17-input-safety-gate-findings--12-november-2026) remain the governing evidence, not assumptions about this allowlist.

No receipt is automatically written, appended, retained or authenticated. Callers may deliberately save stdout in existing private artifact/file storage, checking process exit **and** complete JSON. Capture, raw metadata, status messages, endpoint paths, IDs, files and diagnostics may reveal secrets; escaping/hashing is not redaction. Status/terminal/descriptor text is untrusted data, not executable instructions. There is no cross-clock age computation, consent verification, authorization identity, authenticated audit chain/history or proof of exclusive/continued control.

| Exit | Meaning |
| --- | --- |
| 0 | Bundle generated or selected read object returned, not authority/behavior certification |
| 1 | Generation/revalidation/read failure, unsupported shape/build, invalid read result |
| 2 | Usage, invalid/oversized/missing files or invalid tool arguments; no action/receipt promised |
| 3 | Caller-supplied local policy denied; no Rex contacted |
| 4 | Rediscovered adapter identity changed; action not attempted |
| 124 | Monotonic subprocess budget exceeded |
| 130 / 143 | SIGINT / SIGTERM requested cancellation |

## Coverage and genuine blockers

| Requirement | Delivered or remaining contract |
| --- | --- |
| C25 installed discovery | Actual selected descriptors + independent CLI/server identity, bounded read-only discovery. Not full catalog export. |
| C26 narrow generated adapter | Five generated tool definitions, strict local argument validation and fixed read-only dispatch. Unknown schema constraints refuse. Arbitrary method/code generation, mutation tools and full JSON Schema compilation intentionally excluded. |
| C27 invalidation | Consistency check + mandatory rediscovery before each allowed action; exact endpoint/identity/descriptor drift refuses. Not server-instance authentication, atomic input precondition or revocation. |
| C28 capability ≠ permission | Explicit identity-bound local policy; no default allow; separate denial/drift/error receipts. Real host authorization, enforcement and authenticated history remain **blocked on a real host contract**, not satisfied by policy JSON. |
| Action/audit surface | Reviewable per-invocation local receipts with policy/argument hashes and actual result/error. No signed authoritative history, actor authentication, proof of consent, export approval or no-bypass guarantee. |
| C07/C17/clutch | No server input lease/conditional write/human-input revocation contract was established. **Blocked for strong enforcement**; this read-only leaf neither invents one nor substitutes a cooperative lock. |
| Non-Rex H01/H04 and broader runtime | Preserved/unassigned handoff; no generic evidence service, credential/isolation platform or task/agent runtime implemented. |
| Shipping/lifecycle | Integrated combined CLI and experimental native cartridges shipped in alpha.4 and retained in alpha.5. Frozen alpha.3 is unchanged; no personal M5/hive/config action or runtime installation follows. |

Upgrade by reviewing/rebuilding this leaf and deliberately regenerating changed bundles/policies after revalidation. Stop using it by no longer invoking it; remove only the executable/local files you deliberately created. No services/hooks/configuration need removal. Independent cartridge packaging remains separate. Rex is a separate proprietary dependency, not bundled; teerex licensing remains [unselected](../../RIGHTS.md).

## Public CLI tests and installed evidence — 12 November 2026

```sh copy Copy Adapter Tests
# Use the standalone binary from the leaf build above and a deliberately selected Rex on PATH.
TEEREX_BIN="$PWD/teerex-adapters" TEEREX_ADAPTER_STANDALONE=1 \
  python3 items/adapters/test_adapters.py -v
# After shared CLI integration, omit TEEREX_ADAPTER_STANDALONE and point TEEREX_BIN at teerex.
# Add TEEREX_OFFLINE_ONLY=1 for no-server argument/missing-executable checks only.
```

The tests use only the public executable. Runtime checks create disposable private `/tmp` sockets with restore disabled, `/dev/null` config and separate state; they stop their owned server/fixture processes. No default/personal server is contacted. Eleven test groups cover exact independently hashed installed descriptors; deterministic generated definitions; ignored malicious descriptor prose; real five-method reads; complete/partial capture at 256/65536 bounds; quoted Unicode; actual last-reported directory distinct from cwd; a real blocked-permission report with consent still false; unchanged session list/files; exact-target/tool/identity local denials before any Rex call; invalid/oversized files/arguments; build/revision/prose drift; unsupported schema requirements/constraints/references; unknown methods; edited saved definitions not changing dispatch; missing executable/target; malformed/wrong-shape/oversized result faults; deadline/SIGINT/SIGTERM killing resistant owned transport groups while the actual server remains queryable. Fault injection is labelled separately from ordinary Rex behavior; injected API identities test numeric acceptance only.

Executed matrix with Zig 0.15.2 ReleaseSmall (standalone leaf CLI):

| Actual CLI/server build | Platform / runtime | Result |
| --- | --- | --- |
| preview.16 / API13 / `aa2db1b21261b479a550559fb70e2c3a66c07ba2` / `2026-11-11T21:35:56Z` | Linux x86-64 orb | 11 tests passed, 26.181 s |
| Same preview.16/API13 build | Disposable arm64 macOS 27.2 | 11 passed twice; final 30.025 s |
| preview.13 / API10 / `1b6654811346488b696ded8f3c7e6701c57242f1` / `2026-11-03T21:32:55Z` | Disposable arm64 macOS 27.2 | 11 passed twice; final 29.870 s |
| preview.14 / API12 / `7e460d02f51573990bfcdc6c44a5606d11c7d47a` / `2026-11-09T21:00:41Z` | Disposable arm64 macOS 27.2 | 11 passed twice; final 29.444 s |
| API11 | No actual build established | Numeric controlled tests only; behavior unverified |

Official archive SHA-256 pins were verified before executing Rex: Linux/API13 `90b2429036d26f317aaac2490d014e07c9351b0b994b1329afce94b8ad4d333c`; Mac/API13 `3055299e4fe881d97e8ca452e33906b8a9c7aedf36b836845ebb587829b29a29`; Mac/API10 `dfc3c5d57c9637ac21f41a7fa425a453fed64d68152b90772afb2d815b028977`; Mac/API12 `728df49b2cefcd62b7dde14cfcbd238cac69ec1524d71c19e6a389728ebe5374`. URLs/pins are the immutable preview commit archives used in the baseline CI workflow. No vendor archives/schema bodies are published here.

Exact descriptor fingerprints below are raw CLI stdout bytes, not doctor hashes copied without discovery. The direct installed-descriptor test independently re-queries and hashes each full response. Selected descriptions matched across these actual builds/platforms; generated adapter identities still differ with endpoint/build identity.

| Method | Installed descriptor SHA-256 |
| --- | --- |
| `server.version` | `920871d48f1d6d5ad6a9c14679a175e10a6b9a160036a9f8d3d6b7c3dd84d638` |
| `com.superlogical.terminal.format` | `19575a7cc3220e44cfda977c0bb5bf277bc1e4af7912a0e29c3cd5c77b85d12b` |
| `com.superlogical.terminal.process` | `050d63ad5b7ef71ec4183c6e59773ffd139fd6b910595914ac4db228179195ee` |
| `com.superlogical.terminal.pwd` | `cec5757672d56edbe34cf86309bc65a198baf9233da6b7aa1d8343d73921280c` |
| `com.superlogical.terminal.program_status` | `99c3619f2e69371dde2524a73d5f24636bcd9aa69507d14904e5fc39e57c2f8a` |

Formatting, Linux native and explicit Apple-silicon target leaf builds, and unchanged baseline root build pass. A scratch shared-CLI-shaped driver imports `rex_adapters.run` and passes the same 11 public tests in 26.804 s on Linux; this validates the integration signature/command prefix without editing root dispatch. The existing four native child-supervisor tests pass unchanged. An implicit native macOS27 target with this Zig package failed system-symbol linking; explicit `-target aarch64-macos` builds and runs. These results are not personal-M5/hive, OS26, mixed-version pairs, future-build or whole-process-tree certification. At this leaf checkpoint, root dispatch/integration tests remained the integrator's next step; its source scope was only `items/adapters/**` against public alpha.3 commit `8b2827860029e30a3ad5724d357655de155520d5`. Integration subsequently shipped in alpha.4 and remains in alpha.5; see the [current release evidence](../../docs/releases/v0.1.0-alpha.5.md#verification) rather than treating this dated checkpoint as release-byte acceptance.
