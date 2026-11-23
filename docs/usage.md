# teerex usage

Use full session and block IDs from `rex session ls --json` and
`rex block ls -s SESSION --json`. The local socket comes from
`REX_SERVER` (a Unix URL) or the local runtime path. An explicit
`--socket /absolute/path` selects a different local socket.

## Send

```sh
printf '%s' 'Message body' |
  teerex send --session SESSION --block BLOCK --from NAME --message-file -
```

When someone is typing or a pane is held, the default send queues the message.
The JSON receipt reports either the queue ID or Rex's paste and Enter
acknowledgments. For agent messages, `agent-send` in rexconfig adds the sender
address and verifies application consumption. Inspect an uncertain receipt
before sending again. See [send](../items/send/README.md) for receipt fields.

## Clutch

```sh
teerex clutch take --session SESSION --pane BLOCK --reason 'Editing input'
teerex clutch status --session SESSION --pane BLOCK
teerex clutch queue --session SESSION --pane BLOCK --json
teerex clutch release --session SESSION --pane BLOCK
teerex clutch drain --session SESSION --pane BLOCK --json
```

Release removes the hold and tries pending messages. Drain tries messages without
changing the hold. Both use the draft guard. Queue inspection leaves the queue
intact unless you explicitly resolve an uncertain delivery. See
[clutch](../items/clutch/README.md) for queue state and receipts.
