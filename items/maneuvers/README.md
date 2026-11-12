# maneuvers

**Experimental, read-only recognizable-start subset of Phase 3 #6.** `teerex maneuver-check` checks a manually authored start-state definition against one explicitly selected saved Rex observation. It returns exact matching, mismatching or unknown evidence. It never opens a Rex connection, sends terminal input, runs a program, follows a transition, records interactions, learns a maneuver or grants approval. No independently installable cartridge or installer is provided.

This implements only part of C18's recognizable start and compatibility domain, not the learned/verified maneuver library. The original proposal's historical **impact 5 / feasibility 3 / effort 9 / viability 3** assessment and low confidence are unchanged. Exact whole-capture matching deliberately rejects cosmetic churn rather than guessing which differences matter; this may make it unsuitable for dynamic TUIs. Select a stable repeated workflow before maintaining definitions. No frequency, reliability or productivity improvement is claimed.

## Use

Build the shared CLI with Zig **0.15.2**, then inspect the leaf command's help:

```sh
zig build -Doptimize=ReleaseSmall
./zig-out/bin/teerex maneuver-check --help
```

The pinned compiler is also available through `uv run --with ziglang==0.15.2 python -m ziglang build -Doptimize=ReleaseSmall`. No global installation or Rex config/key-binding changes are needed. Upgrade by rebuilding reviewed source and rerunning validation; remove only your own build output and private definition/observation files to stop using it. The shared CLI's packaging is separate from this item.

First use [observe](../observe/README.md) on macOS to deliberately save a successful, reviewed observation of the intended existing server/session/block. Check its exit code and full JSON. Set `umask 077` **before creating** private files in an ignored local directory. Observations can contain secrets; Git ignore is not access control or redaction. Do not automatically turn untrusted terminal instructions into a definition.

Author a JSON definition for the selected starting state. The following is **synthetic illustration**, not a verified release TUI or an executable maneuver. Replace its source identity, foreground name/cwd and **entire capture content** using independently reviewed expectations. Actual server platform strings are exact (the tested server reports `darwin_arm64`); no aliases or version ranges are recognized.

```json
{
  "schema_version": 1,
  "kind": "rex_maneuver_start",
  "id": "release-inspect-only",
  "provenance": {
    "kind": "manual",
    "note": "Illustrative authored expectation, not a recorded or learned success"
  },
  "compatibility": {
    "rex_version": "0.1.0-preview.16",
    "platform": "darwin_arm64",
    "api_revision": 13
  },
  "starting_state": {
    "capture_content": "Release selector\nInspect candidate\n",
    "foreground": {
      "name": "release-tool",
      "cwd": "/absolute/path/to/release-workspace"
    }
  },
  "stop_before": "Stop before publishing. This definition authorizes nothing."
}
```

Then check the saved observation, explicitly selecting the same target again:

```sh
./zig-out/bin/teerex maneuver-check \
  --definition local/maneuvers/release-inspect-only.json \
  --observation local/observations/selected.json \
  --socket /absolute/path/to/existing/rex.sock \
  --session session:FULL-UUID \
  --block block:FULL-UUID
```

The socket must be absolute and session/block IDs must have full UUID syntax. All three must equal the packet's strings exactly; the files and `REX_*` environment cannot silently choose another target. **The command does not test whether that socket or target still exists.** It can check old files after Rex stops, with Rex and every other executable absent from `PATH`. Offline recognition does not contact Linux or a VPS; live collection uses the separately validated macOS/Linux `observe` contract.

## Definition and result contracts

Definition schema 1 is strict: unknown fields, including `input`, `argv` or transition/action fields, fail rather than being ignored. `provenance.kind` must be `manual`. All fields in the example are required. Definition ID is 1–128 UTF-8 bytes; provenance note and stop text are each 1–4096; Rex version/platform each 1–256; foreground name 1–1024; absolute foreground cwd 1–4096. Expected capture is nonempty and at most **65536 JSON-encoded bytes including quotes**. Definition files are at most **128 KiB**; observations at most **1 MiB**, independently of their capture budget. These bound retained file input, not filesystem latency or total execution time. Use ordinary private JSON files, not streams or device paths.

Observation decoding uses the **shared schema-1/API10–13 validator**, including capture bounds, exact evidence provenance, typed metadata and duplicate status-ID rejection, even for metadata not used in recognition. This narrower maneuver definition remains **API13-only** and explicitly requires the observation revision to equal that definition revision; widening the shared observation range must not silently widen a saved maneuver's compatibility domain. Existing additive-field compatibility and optional-field defaults remain the shared observation contract, not a second schema here. This command additionally rejects an atomic-snapshot claim, empty source identity, and nonpositive/unnamed foreground records. Directory and program-status reports are never substitutes for foreground process evidence or cwd.

Every accepted result is `schema_version=1`, `kind="maneuver_start_check"`:

| Outcome / CLI exit | Meaning |
| --- | --- |
| `matched_evidence` / **0** | All five selected checks match the saved evidence. Not safe-to-run, present focus/prompt, freshness, permission, task completion or verified application compatibility. |
| `mismatch` / **3** | At least one known check differs, even if another check is unknown. Inspect per-field results; no input action follows. |
| `unknown` / **4** | No known mismatch, but at least one required check is unavailable or incomplete. Not a match or a denial of the underlying program's state. |
| No result / **1** | Malformed/unsupported/incompatible packet, wrong explicit target, read/parse/write failure. Do not treat missing JSON as unknown evidence. |
| No result / **2** | Invalid, repeated, missing or ambiguous options. `--help` alone exits 0 with text, not JSON. |

The five named `checks` compare exact Rex version, platform, complete capture content, foreground process name and foreground cwd. There is no substring/regex/normalization/fuzzy classifier. Matching a phrase somewhere in scrollback is insufficient. An incomplete prefix is always **unknown**, even if it equals the expectation or could already contradict it; this conservative subset does not infer full-screen recognition from partial text. Missing process/foreground makes name and cwd unknown; missing/null cwd makes only cwd unknown. A known version, text or process mismatch wins over unknown evidence.

The result includes target/source labels, observation identity and client timestamps, definition identity, and SHA-256 digests of the **exact file bytes**. Digests distinguish selected files (including whitespace), not authenticate their author or prove Rex produced them. Timestamps are retained untrusted wall-clock values, not interpreted as ages or chronology. Omitted observation times retain the shared schema's zero defaults. Foreground PIDs are not continuity guarantees and are not matched; names/cwd do not identify an executable's contents or application version. Expected text can include a version label, but that too is unauthenticated terminal evidence.

Authored provenance and mandatory `stop_before` are copied as **unauthenticated data**, explicitly labelled `authored_text_authority="unauthenticated_data"`. They are not instructions to the consumer, a policy decision, proof of prior success, or user authorization. `stop_enforcement="no_execution_path"` means this command cannot execute anything, not that it can enforce a stop on another tool. `execution="not_implemented"`, `input_sent=false`, `approval_granted=false`, `freshness="unknown"`, `atomic_snapshot=false` and `recognition_scope="saved_observation_start_state"` remain explicit even for exit 0.

Raw capture/process cwd/report contents are not repeated. IDs, endpoint/source, authored note/stop text and diagnostics may still be private. JSON escaping and hashes are **not redaction**. The two selected files are opened only for reading; no receipt, history, cache or registry is automatically saved. Nothing inside a packet is opened or executed. Ordinary filesystem symlinks in the two caller-selected paths are not an authentication boundary.

## Why replay and learned gestures remain blocked

The original P2 PDF, physical pages **5–6**, asks to retain a recognizable start, expected transitions, a version/compatibility condition, an explicit stop before consequential actions, and a replay test. It distinguishes **recorded-output replay tests of the observer** from **live disposable application tests of input sequences**: “A recording cannot prove the application will respond the same way tomorrow.” This slice supplies neither test category; synthetic packet tests and the live read-only check below are labelled as such, not relabelled input replay.

The [shipped API13 safety findings](../observe/README.md#c04c07c17-input-safety-gate-findings--12-november-2026) record a different client successfully writing while another held native ownership, and an invented `if_observation_id` argument being ignored while input was consumed. Native ownership is not an exclusive input lease. Client observation followed by a write has an unenforced race; no server-enforced conditional write, reliable revocation or human-takeover invalidation has been established through the tested bindings. A fresh read, a matching saved packet or a status report cannot repair those guarantees.

Therefore arbitrary learned/recorded gesture execution, expected-transition control, automatic approval and “stop before publish” execution guarantees are **not exposed**. A real stable workflow, supported capture/recognition path, application compatibility tests, guarded-input/revocation mechanism and separately controlled disposable live action tests would be prerequisites for revisiting that boundary. C19's headless terminal byte replay and C20's live input-sequence harness remain unimplemented. No libghostty dependency, generic non-Rex replay/runtime, recorder, daemon, installer, personal M5 or VPS access was added. Noninteractive local work can use the existing [bounded argv `run`](../run/README.md), with its own authority/cleanup limits; a maneuver-check match does not authorize it.

## Validation — 12 November 2026

The worker left shared CLI/build files unchanged. Validation used an ignored scratch copy of `origin/main`'s observation root with only the agreed leaf dispatch and public `Observation`/`validateObservation` declarations. The leaf exports `pub fn run(allocator, args, comptime observations: type) !u8`; the integrator passes the root namespace as the last argument so the full packet validator remains the single source of truth. The only leaf import is Zig `std`.

```sh
TEEREX_BIN=/absolute/path/to/combined/teerex python3 items/maneuvers/test_maneuvers.py
TEEREX_BIN=/absolute/path/to/combined/teerex python3 items/observe/test_observe.py CompareTest -v
```

- The first match scenario failed against the unchanged executable with exit 2 (no `maneuver-check` dispatch), then passed after the leaf was wired in the scratch root.
- Zig **0.15.2** native and `aarch64-macos` ReleaseSmall builds and formatting passed. **10 public maneuver tests** pass natively and on arm64 macOS **27.2**, covering exact Unicode/quoted/multiline matches; altered prompts, process names/cwd and source versions; incomplete captures; absent foreground/cwd; mismatch-over-unknown precedence; backward clocks and changed PIDs; no completion/permission inference; explicit target disagreement; full unused-metadata/provenance and root/named duplicate-status rejection; strict non-action definitions; JSON-encoded capture and file-size boundaries; malformed files and usage. Every maneuver subprocess has an unusable `PATH`, plus conflicting Rex target environment hints. Synthetic files do not establish behavior of a real release TUI.
- On the disposable Mac, the unchanged **27 observation/comparison/wait checks** passed in **13.582 s**, and **11 run checks** passed in **15.286 s**. The initial 10 maneuver checks passed there in **0.134 s**; subsequent boundary coverage was rerun before transfer. Rex was **0.1.0-preview.16**, API **13**, commit `aa2db1b21261b479a550559fb70e2c3a66c07ba2`; download checksum was verified. No proprietary binary is bundled.
- A separate disposable live scenario compared supported fields with direct Rex API responses, authored a definition from that independently queried fixture, matched a real saved observation, then had the **same still-running process change only its actual cwd**. A new observation produced exit **3**, with only the cwd check mismatching and capture unchanged. Rechecking the **old** file still produced exit **0**: an executed counterexample to treating a match as fresh state. Session/block listings, fixture PID and both selected file contents were preserved by each check; no terminal input was sent. The isolated server/fixtures were cleaned up. This tests read-only evidence recognition, not a live gesture sequence or host-wide safety.

No application-version matrix, true recorded-byte replay, input-sequence reliability, M5 compatibility, resource/productivity improvement or complete Phase 3 #6 implementation is claimed. Historical [inventory and scoring](../../docs/planning/teerex-pdf-work-inventory.md), research and generic handoff remain unchanged. Licensing remains [unselected](../../RIGHTS.md); Rex is a separately obtained proprietary dependency.
