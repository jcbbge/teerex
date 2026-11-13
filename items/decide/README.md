# decide — default with veto

Josh pulls decisions; opening one sends no input, changes no pane status and starts no timer or background worker. The asker proceeds on the recommended default unless Josh chooses otherwise. This tool records and delivers a choice; it never executes an option.

```sh
teerex decide open --id timing --title 'Release timing' --ask 'Ship today?' \
  --option 'go::Ship today' --option 'hold::Wait' --default hold --expires-in 24h
teerex decide list --config /absolute/hosts.json --hosts hive,m5 --json
teerex decide answer --config /absolute/hosts.json --host hive --id timing --option go
teerex decide answer --config /absolute/hosts.json --host hive --id timing --default
```

`open` accepts 2–9 unique `KEY::LABEL` options, a required matching `--default`, optional `--context`, and `--asker-name`, `--asker-session`, `--asker-block`. The address defaults to `REX_SESSION`/`REX_BLOCK` (then `LC_REX_*`); name defaults to `AGENT_NAME` or `asker`. IDs/keys are 1–64 ASCII letters, digits, dots, underscores or hyphens, starting with a letter or digit. Title is at most 256 UTF-8 bytes, ask/context 4096, option labels 512. Control characters other than LF/tab refuse. Expiry defaults to 24h; positive integer seconds/minutes/hours/days (`s/m/h/d`) up to 30d are accepted.

Store: `~/.local/state/teerex/decisions/<id>.json`, private owned directory 0700, single-link regular files 0600. `--store /ABS` or `TEEREX_DECISIONS_DIR` selects an isolated command-host store. The store holds at most 512 retained decisions, each at most 64 KiB. IDs are never reused, including after closure. A nonblocking lock serializes mutation; busy, unsafe ownership/mode, symlinks, malformed records and exceeded limits refuse. Writes are atomic and synced. Records include closure history; no cleanup daemon or automatic deletion exists.

`list` returns `complete`, `sources` and open `decisions`, oldest first. Each decision has `id`, `host`, `title`, `ask`, `context`, `options` (`key`/`label`), `default`, `asker` (`name`/`session`/`block`), `opened_at_ms`, `expires_at_ms`. Without `--hosts`, it lists the local store with host `local`. With `--hosts`, it uses the validated hosts.json named-host local/SSH transport, including strict host-key checking. At most 16 unique hosts; failed hosts appear as `outcome:unknown`, make `complete:false` and exit 1 while preserving successfully read rows. Each host invocation has a 30s deadline and 1 MiB output limit. Explicit named-host reads use that host's configured home directory; local `--store` does not silently select a remote store.

`answer --host H` uses the configured host (config defaults to `~/.config/teerex/hosts.json`). Omit `--host` to answer locally; local `--socket /ABS` selects the asker's Rex server, otherwise `REX_SERVER` or the platform socket applies. Answer sends exactly `DECISION [ID] Josh chose: <label>` to the recorded asker, through guarded `teerex send`, from `Josh`. No current/answering-pane address is used as a delivery target. Guarded send never overwrites a draft; it checks immediately (`--draft-wait-ms 0`). Only acknowledged delivery closes the decision as answered.

An attempted delivery is persisted before calling send. If delivery fails or its receipt is lost, the decision remains open but another answer refuses: inspect the asker and stored record; never retry uncertain input. `retry_safe:false` is deliberate. An expired decision closes as `default_stood` (outcome `default stood`) on the next list or answer, with no message to the asker. There is no background expiry service.

Security boundary: this is a trusted local-user CLI, not a network endpoint or authenticated proof that Josh pressed a key. The configured SSH transport controls remote access; local file ownership/mode controls store access. Decision text is data passed on stdin, never a shell command; SSH argv uses the existing resolver's literal quoting. Invariants: opening/expiry cannot type, answer targets only the saved asker, uncertain send cannot be repeated, partial host failure cannot look complete.

Tests: `TEEREX_BIN=/ABS/teerex REX_BIN=/ABS/rex python3 items/decide/test_decide.py -v`. Fixtures use disposable API13 servers and temporary stores/config only. CI runs this on Linux API13 and Mac API13; a Linux run does not establish Mac runtime behavior.

Sources: board2-contract.md section 2 and spec-teerex-board.md Revision 2/2b, read 2026-11-13; existing `src/targets.py` validated named-host transport and `items/boards/boards.py` fleet transport, read in this implementation session.
