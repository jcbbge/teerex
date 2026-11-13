# Replay

P0 wire contract probe: `REX_BIN=/absolute/rex python3 items/replay/test_wire.py -v`.
It starts a private disposable server (`--config /dev/null`, `--restore=false`),
opens a persistent API13 control connection and a `rex.data.terminal.v1` data
connection, and checks WELCOME, an opaque nonempty snapshot, initial resize,
`/bin/echo` bytes and its `child_exited` marker. It stops only its own server.

The wire contract comes from the selected server's `/llms.txt` (control/data
connections). The probe reports the server identity; a hive pass does not certify
another Rex build. Tickets and reconnect tokens are never logged.
