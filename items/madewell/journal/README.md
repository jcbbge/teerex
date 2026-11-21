# Made Well's journal on the work engine

`lua/madewell/store_engine.lua` keeps a run's saved returns on the work engine instead of in
`~/.local/state/madewell/runs/`. It has the same interface as `store_file` (`load`, `append`,
`put_blob`, `get_blob`). The file journal stays the default. A run uses the engine when its arguments
say `store=engine`:

```sh
items/madewell/bin/mw items/madewell/demo/josh.lua --args '{"run":"ping-1","store":"engine","auto":true,"inputs":["ping"]}'
```

## How it is built

- **Namespace** `madewell-journal`, pool `journal`, on the engine at `127.0.0.1:7420`. It is separate
  from Made Well's own namespace `madewell`.
- **Node** `node.mjs` (RivetKit 3.1.1) serves one `journal` actor per run, keyed by the run name. Each
  actor keeps its records (one JSON line each, append-only) and the content blobs they point at in its
  own SQLite. A blob is stored only if its bytes hash to its name.
- **Library** calls the actor through the engine gateway with `curl`. The token comes from a header file,
  so it never enters argv. Each blob read is checked against its hash.

## Access

The engine signs both tokens itself (`POST /auth/tokens`). They are scoped to `madewell-journal`, and
each carries only the grants it needs. Every operation was tested by removing it on a throwaway engine
of the same image:

| Token | Grants | File (0600, directory 0700) |
|---|---|---|
| node | `node: create`, `pool: update` (the node upserts its pool on connect) | `~/.local/share/agent-credentials/madewell-journal/node.token` |
| library | `actor: create`, `actor_gateway: read, create` | `~/.local/share/agent-credentials/madewell-journal/library.header` |

The library token is refused (403) for these: listing namespaces, creating a namespace, listing or
deleting actors, writing a pool, minting tokens, and any other namespace through the gateway. The node
token is refused on the gateway.

**Tokens last at most 24 hours** (the engine's limit is `duration must be between 1 and 86400 seconds`).
A connected node keeps serving after its token expires, but it cannot reconnect. A library call with an
expired token fails with `401 token_expired`. `mint.mjs` writes fresh tokens. It reads the admin token
from a file and never prints a token.

## Behaviour measured on a throwaway engine

- Records and blobs survive a `kill -9` of the node and a restart of the engine.
- After the node dies, the engine waits about 35 s before it moves an actor to the restarted node. A
  call waits that long, inside the store's 60 s timeout.
- `test/run-engine.sh` runs the core cases on the engine store, then the WI-1 ping. The ping saves
  through the engine, and a rerun replays it and launches nothing.

## Turning it on (only on Josh's yes)

```sh
cd ~/teerex/items/madewell/journal && npm ci
node mint.mjs --admin-file ~/madewell/.env --provision     # namespace, pool, both tokens
node node.mjs                                              # in a Rex pane, or:
cp systemd/* ~/.config/systemd/user/ && systemctl --user daemon-reload
systemctl --user enable --now madewell-journal.service madewell-journal-mint.timer
```

To turn it off, run `systemctl --user disable --now madewell-journal.service madewell-journal-mint.timer`.
A run that asks for `store=engine` then fails loudly. The file journal is unaffected.
