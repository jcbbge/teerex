# Recovery: inspect first, preserve omissions

**Current alpha.5 ships this experimental combined-CLI structural-recovery slice, not complete agent-session or draft recovery or an independent cartridge.** Use [current setup](../../docs/concierge/setup.md) and the [alpha.5 release support guide](../../docs/releases/v0.1.0-alpha.5.md). Dated leaf-only validation below remains distinct from released-byte acceptance. `recovery snapshot` saves inspectable private evidence; `restore` previews by default and requires a separate exact confirmation to create visible panes. `update` inventories running versus installed Rex and hands off the actual update/restart to the operator. It never invokes an installer, closes a pane or restarts a server.

Python 3.9+ stdlib and Rex are explicit prerequisites. Snapshot/restore support API13. Read-only update inventory accepts API10–13; requesting a snapshot on an older API returns the inventory plus an explicit unsupported result, exit 1, without a snapshot or restart. API11 is not certified. Root CLI aliases expose `snapshot`, `restore` and `update`; the canonical module form below is `teerex recovery OP`.

## Snapshot roots and stale references

`teerex snapshot --socket ABS --root ABS` creates a new private timestamped child under the selected root (creating the root when absent). `teerex recovery inspect --root ABS` and `teerex restore --socket ABS --root ABS` select its newest complete timestamped snapshot. An explicit `--directory ABS` retains the existing contract and cannot be combined with `--root`. No snapshot or restore file is overwritten. Root and child directories must be owned by the caller and mode 0700; symlinks are refused.

Named-host records may set `recovery_store` to an absolute command-host root; otherwise it defaults to `HOME/.local/state/teerex-recovery`. Thus `teerex --config ABS --host m5 snapshot` needs no snapshot path. Explicit `--directory` or `--root` overrides that default.

Registry launches and board references whose panes are absent from the snapshot inventory are listed under `omissions.absent_references`, with their target and reason, and are excluded from replay/remapping. A live block ID with a conflicting session identity still refuses. Restore also recognizes absent board references in older snapshots as omissions; `--accept-omissions` is required to apply a partial plan. Detached panes present in inventory still retain the existing unmapped-reference blocker.

## Who

The operator or an authorized setup agent selects one command host and explicit Rex socket. The shared root's named-host transport may invoke this leaf on another machine; all directories, registry paths, board stores, binaries and cwd values then belong to **that command host**. This module does not invent SSH routes, discover personal machines or interpret a label as an execution address.

A recovery file is private operator-owned state, not a portable permission grant. A preview hash binds the snapshot content, live target instance/host/version, existing-session inventory and omission policy. It is a confirmation of that concrete plan, not a security sandbox or exclusive mutation lease.

## What

### Per-field support

| Field | Captured evidence | Restore behavior |
| --- | --- | --- |
| Sessions, tabs, pane labels/order | `session.list`, `session.view`, `session.list_blocks` | New sessions/tabs with corresponding labels; no old pane is closed. |
| Layout and split ratios | Public tiled/floating trees, normalized rectangles and before-share ratios | Compose `surfaces open`, then re-inspect **every final pane**. Nested tiled trees and single-pane floating layers are supported. Floating split trees are explicitly blocked by the current surfaces contract. |
| Host | Server `host_id`/`instance_id` and each block's public `host_id` | Same observed server host only. Attached foreign-host execution is blocked, never moved onto the command host. Host IDs describe shared files/account, not authentication. |
| Cwd | Public foreground-process cwd when available, with provenance | Only explicit private launch cwd is replayed. `cd` failure exits 125 rather than executing in Rex's fallback home. No local existence check is mistaken for foreign-host evidence. |
| Command/argv | Rex intentionally exposes executable identity/argv0, **not full arguments** | Full argv must come from explicit private metadata. Exact positional arguments, including empty strings, quotes and Unicode, are retained; no shell interpolation. |
| Harness/resume ID | Optional explicit metadata only | Stored as **unverified** harness state. No generic Claude/Codex/pi resume adapter is proven; agent argv is never replayed blindly. Historical ACK is not a fresh protocol gate. |
| Reporting/starter/inbox | Explicit full `{host,server,session_id,block_id}` tuples | Exact old/new remap receipt; report/inbox environment references point to newly created panes. Cross-server/unmapped references are blocked. Conflicting host aliases for one Rex pane are refused. |
| Seat | Explicit metadata boolean or `boards state inspect` reference | Remapped receipt and board-map handoff. Never inferred from a label, title or rendered prompt. |
| Inbox cards/messages | Remain in the explicit board store | Snapshot copies routing references only, **not bodies**. After surface verification, optional board `remap-preview`; separate generation/reason-confirmed board apply preserves records in that one store. |
| Unsent drafts | **Unsupported: no authoritative input-buffer API** | No capture or paste-back. Not inferred from grey/dim suggestions, screen text, cursor position, `input_mode` or prompt shapes. Save real drafts separately before any restart. |
| Focus, zoom, minimized layers | Original public view retained | Not reapplied: restored panes remain inspectable. No focus request is made, though Rex necessarily activates a first window in a new session. |
| Detached blocks/nonterminal flavors | Inventoried explicitly | Detached blocks are not recreated as hidden programs. Nonterminal/foreign-host placed blocks are hard blockers. Explicit omission acceptance can skip detached blocks or create holding shells for unknown commands/gated agents. |
| Credentials, environment, briefs, protocol tokens | No environment capture or credential/brief/protocol-file reads | Never recovered. Agent records are whitelisted; token/hook/brief paths are excluded. **Explicit argv can itself contain secrets** and remains private. |

The saved `snapshot.json` contains raw public layout evidence, per-pane `field_support`, declared launch metadata and a fixed omissions record. `inspect` returns an inventory and support summaries without printing full argv or resume IDs; reading the private file itself reveals those explicitly supplied values. Process observations are not agent death/completion/readiness evidence. No screen capture is used by recovery.

## When

Before an explicitly authorized server restart/update, inventory first and take a fresh snapshot into a **new** private directory. Do not proceed merely because snapshot exits 0: review its omissions, especially real drafts, gated agents and unsupported hosts/layouts. Exit 0 means the requested structural evidence was obtained, not that all lost state is recoverable.

After a restart, preview against the explicitly selected **empty** server. Restore refuses a nonempty target; it does not close existing sessions to make room. Every apply is one attempt. A failure can leave newly created sessions/panes running; inspect the journal and real server instead of retrying.

## Where and private bounds

- Snapshot/store/metadata paths are absolute. Store/registry directory: owned by the invoking UID, exactly 0700. State/metadata files: owned regular files, exactly 0600, one hard link. Final symlinks are refused. Use trusted parent directories and a trusted local filesystem; this is not protection from a malicious same-UID process or a mutation lease.
- `snapshot.json`, `restore.jsonl`, `remap.json` and `board-map.json` are never overwritten. Keep them off Git/public logs and back them up using your own private policy. No automatic retention/deletion is performed.
- Maximum 32 sessions, 128 pane records, split depth 16, 1 MiB per private JSON/transport stdout/journal; argv at most 64 elements/16 KiB encoded and 4096 bytes per element; sanitized launch record at most 32 KiB. Stderr is consumed up to 64 KiB but not echoed in receipts.
- Rex requests/child invocations are bounded by `--timeout-ms` (100–60000, default 5000); the foreground native controller has a 15-minute outer bound. A deadline/uncertain ACK is not permission to retry. No background watcher or hidden agent is created.
- The optional agent registry is read under its established `agents.lock`, a nonblocking shared advisory lock. Contention refuses without retry. Metadata is historical caller evidence, not proof a harness can resume.
- Snapshot rechecks each session's layout, the session inventory and server identity without retries. Cwd/process/cross-session/board observations are not one atomic server-wide snapshot.

## Why

The alpha.5 brief needs auditable restart accounting instead of a shell script that guesses state. Public Rex API13 provides layout facts but intentionally does not expose full process arguments or an authoritative draft buffer. Failing closed on those gaps prevents a plausible-looking reconstruction from silently losing Joshua's text, replaying secrets or starting agents without their protocol gate.

The source references are the full alpha.5 brief; `jcbbge/agent-core-public` at inspected commit `c26bcfc` (`agent-send`, `agent-seat`, `agent-inbox`, `agent-spawn`, `teerex-target`, `rex/init.lua`, `rex/PLAN.md` and `rex/INSTALL.md`); and preview.16's own `rex api describe` / block-creator schemas. `agent-send`'s dim/grey prompt heuristic is **not** an authoritative draft API and is not ported as recovery evidence. Rex's documented process schema explicitly withholds arguments because they may contain secrets.

## How

The following are **operator examples**, not authorization to run on a personal host. Replace the uppercase placeholders with reviewed absolute paths. To select a binary or named host, use the shared root transport; this leaf only consumes its explicit socket and root-selected Rex executable.

### 1. Inventory without modifying Rex

```sh
teerex recovery update --socket /ABS/rex.sock
```

Inspect `running.version`, `running.host_id`, `running.instance_id`, `installed_cli`, `build_differs`, `api_differs`, and each `panes_at_risk` entry. The installed comparison is the **selected CLI on the command host**, not a downloaded GUI bundle, update feed or attached foreign host's installation. Missing build identity yields unknown, not equality. The inventory is not proof that every attached-host process will close during an update.

### 2. Snapshot and inspect

```sh
mkdir -m 700 /ABS/new-recovery-directory
teerex recovery snapshot --socket /ABS/rex.sock --directory /ABS/new-recovery-directory \
  --registry /ABS/agent-registry --board-store /ABS/board-store
teerex recovery inspect --directory /ABS/new-recovery-directory
```

`--registry` and `--board-store` are optional and explicit. Registry input is schema1 `agents-LAUNCHID.json`; tokens, briefs, hook details and arbitrary fields are discarded. `protocol_outcome`, `protocol_acknowledged` and measured immediate-child exit codes remain historical declared evidence, never new readiness/death claims. No token-bearing protocol argument is copied from the live process: the agents registry's argv is the pre-protocol profile argv.

For independently owned non-agent panes, an optional private `--metadata /ABS/metadata.json` has this shape (illustrative IDs only):

```json
{
  "schema_version": 1,
  "entries": [
    {
      "target": {
        "host": "disposable",
        "server": "unix:///ABS/rex.sock",
        "session_id": "session:00000000-0000-0000-0000-000000000001",
        "block_id": "block:00000000-0000-0000-0000-000000000002"
      },
      "name": "review-shell",
      "argv": ["/bin/sh"],
      "cwd": "/ABS/project",
      "harness": null,
      "resume_session_id": null,
      "report_to": null,
      "inbox": null,
      "seat": false
    }
  ]
}
```

Only provide reviewed argv you own and authorize to run. Declaring `harness: null` is not a way to bypass an agent's protocol requirements. Metadata for absent panes, duplicate/conflicting addresses, malformed argv and unbounded files is refused.

The combined read-only update/snapshot step is:

```sh
teerex recovery update --socket /ABS/rex.sock --snapshot --directory /ABS/new-recovery-directory \
  --registry /ABS/agent-registry --board-store /ABS/board-store
```

This still performs **no update, restart or restore**. There is no public updater API in the inspected Rex release. Use that selected server's documented installer/app restart control only after separately approving target/impact, preserving drafts and accounting for every unsupported field. There is no invented universal one-click action.

### 3. Preview restore after the separately authorized restart

```sh
teerex recovery restore --socket /ABS/rex.sock --directory /ABS/new-recovery-directory
```

No server mutation occurs in this preview. Read `context.target`, `existing_sessions`, `hard_blockers`, `omissions` and `can_apply`. If agents or unknown commands exist, normal apply is blocked. To explicitly choose **holding shells instead of agent/unknown-command recovery**, preview again with `--accept-omissions`; its confirmation hash differs. This does not turn missing draft/resume support into a capability.

### 4. Confirm the exact reviewed plan, never a blind retry

Only after the operator authorizes this specific target and impact:

```sh
teerex recovery restore --socket /ABS/rex.sock --directory /ABS/new-recovery-directory \
  --apply --confirm EXACT_PREVIEW_HASH --board-store /ABS/board-store
```

Use the same `--accept-omissions` choice as the preview, if any. The token is revalidated against snapshot and live identity/inventory before mutation. `restore.jsonl` is created exclusively **before** the first session-creation attempt; it records mutation attempts and every verified mapping durably. An existing journal interlocks another apply, including after a crash. There is no resume/retry mode or automatic cleanup/close.

Each new surface initially runs a visible fixed recovery shim. All final pane rectangles/layers/hosts/labels are re-inspected before any original command is released. Remapped report/inbox/starter lines are sent only to those new recovery-owned readers as data, not shell source or unsent drafts. They set `AGENT_REPORT_TO`, `TEEREX_INBOX` and `AGENT_STARTER` (plus the applicable agent-core `LC_` forms). A queued-byte ACK does not prove the program consumed them or started successfully. Programs remain visible/retained in Rex; no hidden fallback exists. Argv stays literal: embedded pane IDs or viewer flags inside arbitrary arguments are **not** rewritten. Reopen board/viewer programs through their owning command with the new address rather than claiming application-internal references recovered.

`remap.json` contains full old/new pane addresses, old/new session IDs, final measured geometry and remapped launch references. It is **not** an importable replacement for the agents lifecycle registry, and its old `launch_id`/ACK facts do not authorize relaunch. Relaunch an agent through an explicitly configured fresh `agents launch` gate; operator-authored resume flags in a profile are not measured harness-recovery support.

### 5. Review and apply the separate inbox/seat remap

If snapshot captured board references, recovery writes a private `board-map.json`. Supplying `--board-store` during restore runs the public board `remap-preview` **after all surfaces pass inspection**, but never applies it. Existing messages/cards stay in the board store.

```sh
teerex boards state remap-preview --store /ABS/board-store \
  --map-file /ABS/new-recovery-directory/board-map.json
teerex boards state remap-apply --store /ABS/board-store \
  --map-file /ABS/new-recovery-directory/board-map.json \
  --generation EXACT_BOARD_PREVIEW_GENERATION --reason 'Reviewed restored pane mapping'
```

The board owns generation/collision/unknown-source checks. Seat/fleet target references change together in **one** local private store; this is not remote/global atomicity or live validity. Historical board references absent from the captured placed-pane inventory remain inspectable in the snapshot, but are hard restore blockers even with `--accept-omissions`: recovery never drops history or guesses a replacement target. Restore receipts keep `board_state_applied:false` because recovery does not own that apply.

## Exit codes and uncertainty

- **0:** requested snapshot/inspect/update inventory or supported structural restore verified. Not full recovery, program consumption, agent readiness, paint/pixel verification or authorization.
- **1:** refusal, unsupported requested snapshot, mismatch, I/O/transport failure or uncertain result. Inspect any existing journal/server before another action.
- **2:** CLI usage.
- **3:** explicitly accepted partial restore completed with holding shells/skipped detached panes. Read omissions; original agents did not resume.
- **124:** native controller outer deadline; partial server effects may exist.
- **130/143:** cancellation; partial server effects may exist.

An individual request timeout is a structured exit-1 uncertainty, not a server-side rollback. Journal attempts can be dispatched even when their replies are lost. No quiet retry, rollback, automatic close, credential recovery, input lease or whole-tree cleanup is promised.

## Reproduce the disposable acceptance checks

From the source tree with checksum-verified Zig 0.15.2, Rex preview.16 and Python3.9+:

```sh
zig build-exe --dep rex_recovery --dep rex_surfaces --dep rex_boards \
  -Mroot=items/recovery/test_cli.zig \
  --dep supervised_child -Mrex_recovery=items/recovery/main.zig \
  --dep supervised_child -Mrex_surfaces=items/surfaces/main.zig \
  -Mrex_boards=items/boards/main.zig -Msupervised_child=src/child.zig \
  -lc -O ReleaseSmall -femit-bin=/ABS/teerex-recovery-test
REX_BIN=/ABS/rex TEEREX_BIN=/ABS/teerex-recovery-test python3 items/recovery/test_recovery.py -v
```

The suite creates/stops only its own disposable Unix-socket servers and uses controlled argv, canonical unsent-input/grey-suggestion fixtures and opaque resume metadata. It checks nested asymmetric geometry, exact arguments/cwd, report/inbox remapping, no blind agent resume, per-field omissions, ownership/modes/links/bounds, agent registry locking/sanitization, board preview/apply preservation, wrong host/nonempty target/confirmation refusals, one-attempt uncertainty with retained journal, and read-only update behavior. Cross-host refusal uses an explicitly foreign-host snapshot fixture; it is not a certification of attached-host execution. These are public API/CLI checks, not a rendered Rex.app/pixel test or personal-machine validation.

### Validation recorded 12 November 2026

| Disposable platform | Rex | Executed result |
| --- | --- | --- |
| Linux x86_64, Python 3.13.5 | preview.16 / API13 | `python3 items/recovery/test_recovery.py -v`: **11 tests, OK** |
| macOS 26.3.1 arm64, Python 3.14.3 | preview.16 / API13 | Same full suite: **11 tests, OK** |
| macOS 26.3.1 arm64 | preview.13 / API10 | Update inventory/snapshot-refusal test: **1 test, OK**; no snapshot/restore certification |
| macOS 26.3.1 arm64 | preview.14 / API12 | Update inventory/snapshot-refusal test: **1 test, OK**; no snapshot/restore certification |

Zig 0.15.2 compiled the native composition driver on both platforms. Vendor archives were SHA-256 checked against the repository's existing CI pins before execution. Local source validation is not a published alpha.5 release, hosted CI success or personal-machine permission. API11, live foreign-host creation, graphical painting, real harness resume and updater execution were not tested or claimed.

## agent-core migration boundary — preserve the stopgap

The inspected public agent-core checkout has the messaging/Rex files cited above, **not** `~/briefs/rex-restart-tabs.sh` or its handwritten restart accounting. The brief mentions those private external files; it is not their source. No deletion patch is justified or supplied, and no existing history is rewritten.

Migration is therefore **blocked**, not completed: obtain the actual private script/accounting through an approved private source; inventory each behavior; compare it against the support table and controlled Mac/Linux acceptance evidence; prove parity for the supported operations and obtain explicit acceptance of each unsupported one; only then prepare the source migration/deletion patch. Do not delete personal files, run a local restore, restart/update Joshua's servers or substitute this structural subset for full agent/draft recovery on the strength of this brief alone.
