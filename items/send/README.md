# send

**Experimental terminal-input leaf, not a global messaging authority or independently packaged cartridge.** `rex_send.run(allocator, args) !u8` uses the shared `supervised_child` ABI. It owns only `items/send/**`; shared CLI/build integration and release delivery belong to the integrator. No Rex configuration, agent-core files, personal machines, or running personal servers are changed. This leaf is not part of the immediate compatibility-only Mac release.

## Invoke and select deliberately

After shared CLI integration, build with Zig **0.15.2** using `zig build -Doptimize=ReleaseSmall`, then:

```sh
teerex send --socket /absolute/path/to/existing/rex.sock \
  --session session:01234567-89ab-cdef-0123-456789abcdef \
  --block block:fedcba98-7654-3210-fedc-ba9876543210 \
  --from worker --message-file /absolute/path/to/message.txt \
  --timeout-ms 10000
```

An absolute Unix socket, canonical lowercase full session/block IDs, a label, and an absolute regular message file are required. The file is read once, without trimming or shell joining. Its 1–65536 bytes must be valid UTF-8; ASCII controls other than LF/tab, including CR, ESC, NUL and DEL, are refused. The label is 1–128 UTF-8 bytes with no ASCII controls. Those checks are **not** a proof that the text is safe for the recipient. The exact paste text is `FROM <label>: <file bytes>`. One Enter key event follows on the same attached Rex connection.

**Choose a dedicated agent terminal that you are authorized to type into.** The selected session must contain the block as a visible terminal at validation time; detached and nonterminal blocks are refused. No active-pane/focus resolution, new terminal, server autostart, shell execution, Ctrl-U, draft detection, draft restoration, chunk fallback, or retry is performed. Existing pending input is not cleared: a following Enter can submit that input together with the message. A caller-selected agent terminal does not prove prompt/input safety. A terminal without bracketed-paste handling may treat embedded newlines as input submissions. Even a bracketed-paste-aware application may interpret or execute the message. Target validation is a prior read, not a conditional write or lease.

The separately installed `rex` CLI is resolved through PATH. `REX_SERVER`, `REX_SESSION`, `REX_BLOCK`, and `REX_CLIENT` hints are removed; explicit addresses select the connection. A forwarded socket still uses the CLI machine's filesystem, lock directory and inbox markers. It does not share locks with senders on the server host. No SSH/inbox forwarding or physical-host authentication is added.

## Existing agent-core contract and intentional differences

The actual source inspected was [`agent-send`](https://github.com/jcbbge/agent-core-public/blob/80c13e4c8d58a851fcab1085437d51f10080c831/primitives/tools/agent-messaging/agent-send) at commit `80c13e4c8d58a851fcab1085437d51f10080c831`. Its terminal branch acquires `${TMPDIR:-/tmp}/agent-send.${blockUUID}.lock` using mkdir, pastes `FROM <from>: <message>`, then presses Enter. Its other behavior includes inbox routing, input-clearing, heuristic draft restoration, and a numbered-chunk fallback. The source was read and exercised, not copied into teerex or modified.

teerex uses that **same mkdir/rmdir lock name** and exact envelope, but deliberately does not clear input or restore guessed drafts. It never falls back after a failed/uncertain paste, because the paste may already have taken effect. The file interface avoids Bash `$*` joining and preserves trailing newlines. The current bridge's inbox routing remains separate: teerex refuses a local `${AGENT_INBOX_DIR:-$HOME/.local/state/agent-inbox}/${blockUUID}.inbox` marker, including a marker naming a remote host. It checks before acquisition, during waits and after acquisition. Creation/removal of markers by noncooperating processes can still race these checks. Empty environment values use the same Bash `:-` defaults. Unknown lookup permissions fail closed.

**Only cooperating processes on the same host and effective temp directory serialize.** The lock covers the entire teerex Rex invocation and child cleanup, not just paste. Two sockets using the same block UUID conservatively contend. Different temp directories, hosts/users with different namespaces, direct Rex clients, humans, and clients ignoring the lock bypass it. A direct Rex write succeeded while this lock was held in validation. Native Rex block ownership is not an exclusive input lease; it is not used as one. There is no server-enforced atomic paste-plus-Enter operation, no conditional observation token, and no promise of atomic delivery across arbitrary clients.

The default overall monotonic deadline is **10000 ms**, range **100–60000**. It includes input reading, lock wait, startup and RPC work; polling waits at most 20 ms between attempts. The remaining budget supervises the Rex child. Shared process-group cancellation/cleanup can add bounded drain/escalation time, and filesystem/kernel operations, scheduling and final stdout backpressure are not hard real-time bounded. SIGINT/TERM request cancellation. SIGKILL/crash can strand a lock or leave uncertain terminal effects; no stale-lock stealing is implemented. Remove a stranded lock only after checking that its sender is gone and deciding how to handle possible prior input. A shared, attacker-controlled TMPDIR is not a security boundary.

## Encoded bounds, not just raw-message size

Rex preview.16 caps control messages at **65536 bytes**. A 65536-byte message plus escaped JSON cannot fit. Before spawning Rex, teerex rejects a JSON arguments object over **60000 bytes**, which also avoids Linux's per-argument exec limit for LF-heavy input. Before paste, fixed Lua uses **Rex's own JSON encoder** to size a conservative JSON-RPC-shaped envelope containing the exact session/block IDs and paste event. Values over **60000** are refused; more than 5 KiB remains for protocol framing/request-ID differences. `encoded_rpc_bytes` is that preflight encoding size, **not a wire capture**; it is null if Zig rejected before Rex ran. `encoded_argument_bytes` separately records the outer arguments size. No message is truncated or split.

With label `worker` and canonical IDs, the measured preflight overhead is 234 bytes. Boundary tests accepted 59766 printable ASCII bytes, 29883 α characters (59766 raw UTF-8 bytes), 29883 LF characters, 29883 quotes, and 9961 `<` characters, each at exactly **60000 encoded bytes**. One more ASCII byte was refused at **60001**, before paste. Full raw 65536-byte printable, Unicode and LF-heavy files were explicitly rejected before paste. Limits change with the label and escaping; these are synthetic test sizes, not universal raw payload allowances.

## Receipt and unknowns

Normal controller outcomes emit one `schema_version=1`, `kind="send_result"` JSON object. Usage failures exit 2 without JSON. Input-file/OS/allocation/output failures can exit 1 without a complete receipt. Always inspect exit status and parse the whole packet; never automatically retry a missing or unsuccessful receipt.

- `events_acknowledged` / exit **0**: both paste and Enter were acknowledged and the Rex invocation completed successfully. **Not “delivered,” consumed, safe, or task-complete.** On one Rex connection the calls are ordered; acknowledgement may precede completion of event effects.
- `refused`, `inbox_refused` / exit **1**: encoded-size, revision/target or local inbox refusal. `failure_reason` and the reported source revision identify the refusal where available. API10–13 is the accepted integer range; revision 11 has not been exercised here. A numeric range alone does not establish every server's capability.
- `uncertain`, `backend_error` / exit **1**: command/transport/framing failed. Input effects may have occurred, including when no attempt frame reached the controller. Backend diagnostics are bounded by the shared supervisor and printed on stderr. A paste ACK followed by failed/missing Enter remains `paste.acknowledged=true`, `enter.acknowledged=false`; no invented success or retry follows.
- `deadline_exceeded` / exit **124**, `cancel_requested` / exit **130/143**: work stopped by deadline/SIGINT/SIGTERM. Already reported attempts/ACKs remain in the packet; stopping the CLI does not retract queued input or prove recipient cancellation.

`paste.attempted` / `enter.attempted` mean **received local pre-call frames**, not verified server dispatch. False means “not reported,” not always “definitely never attempted.” `backend_invoked=false` means the Rex invocation was not made; true is not proof it connected. Source can be null. `cooperative_lock.acquired` reports actual local acquisition. Lock cleanup failures are non-successful even if both ACKs were seen. `server_enforced_atomic_delivery=false`, `exclusive_input_lease=false`, `application_consumption="not_assessed"`, `prompt_safety="not_assessed"`, and `retry_safe=false` remain explicit.

Message contents are omitted from the receipt, but the Rex JSON arguments can appear in process listings or diagnostics. Paths, labels, messages and returned diagnostics may contain private data; nothing is redacted. Use only trusted binaries and review evidence before sharing it.

## Validation — 12 November 2026

Run `TEEREX_BIN=/absolute/tested/teerex REX_BIN=/absolute/tested/rex python3 items/send/test_send.py`. The public suite creates private disposable servers with explicit sockets, `/dev/null` configuration, private state, and restore disabled. A raw, no-echo terminal program records consumed PTY bytes independently of teerex's ACK receipt. This proves the synthetic fixture's bytes, not arbitrary applications' consumption. No M5/hive server was accessed or restarted.

| Runtime actually exercised | Result on final behavior |
| --- | --- |
| macOS arm64, Rex preview.13 / API10, `1b6654811346488b696ded8f3c7e6701c57242f1` | 9 tests, 2.742 s, OK |
| macOS arm64, Rex preview.14 / API12, `7e460d02f51573990bfcdc6c44a5606d11c7d47a` | 9 tests, 2.824 s, OK |
| macOS arm64, Rex preview.16 / API13, `aa2db1b21261b479a550559fb70e2c3a66c07ba2` | 9 tests, 2.538 s, OK |
| Linux x86_64 orb, Rex preview.16 / API13, same commit | 9 tests, 2.487 s, OK |

Archives were SHA-256 checked: Mac preview.13 `dfc3c5d57c9637ac21f41a7fa425a453fed64d68152b90772afb2d815b028977`, Mac preview.14 `728df49b2cefcd62b7dde14cfcbd238cac69ec1524d71c19e6a389728ebe5374`, Mac preview.16 `3055299e4fe881d97e8ca452e33906b8a9c7aedf36b836845ebb587829b29a29`, Linux preview.16 tar.gz `90b2429036d26f317aaac2490d014e07c9351b0b994b1329afce94b8ad4d333c`. Rex remains a separate proprietary dependency and is not bundled. teerex licensing remains [unselected](../../RIGHTS.md).

Cases cover exact UTF-8/quotes/backslashes/LF/tab/trailing LF and injection-looking text, deliberate target versus poisoned hints, unchanged other terminal, existing input not cleared, encoded 60000/60001 boundaries, full-size rejected inputs, eight concurrent cooperative senders, an externally held bridge-compatible lock, direct-client bypass, custom/default/empty inbox marker configuration, lock-wait SIGINT/TERM/deadline, malformed/over-limit/nonregular/FIFO input, wrong-target/missing-server refusal, and lock cleanup. **Fault-injected backend tests**, not real Rex failures, exercise paste ACK plus failed Enter, interrupted transport and malformed frames, including source metadata split across reads. These tests distinguish retained evidence from success.

A separate Linux disposable-server probe ran the **unmodified actual agent-send bridge at `80c13e4`** concurrently with teerex, observed the bridge's lock before starting teerex, and independently verified whole ordered payloads and final lock removal. This is observed interoperability, not permission to change agent-core or a guarantee against bypassing clients.

Linux testing imports the Linux owner's byte-transferred supervisor directly from scratch, without editing shared source: `linux-child.zig` SHA-256 `cdc1299d19b5b3de737d78d7912379e3d3219aba363c1d2e03d3e288f34c0587`, sibling `child_linux.zig` SHA-256 `3bdd456196033032dad22f2798a7c87503ad185f01ca0c5329b083076d3447f3`. Mac testing uses the published supervisor. Both builds use a minimal standalone send dispatcher because shared main/build wiring is owned elsewhere; combined-executable verification remains with integration. No package/global install is performed. Upgrade by rebuilding reviewed integrated source and rerunning tests; uninstall by stopping use/removing only the executable/build output. Normal sends leave no persistent service or configuration, only the caller's intended terminal effects. Agent-core/Rivet routing and system-wide enforcement are outside this leaf.
