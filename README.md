# teerex

Guarded input for [Rex](https://www.superlogical.com/rex) panes.

- `send` checks for a draft or hold before it pastes a message and submits it.
- `clutch take`, `release`, `status`, `queue` and `drain` manage cooperative
  holds and pending messages.

See [usage](docs/usage.md) for commands and receipts. Rex owns pane management,
capture, events and session persistence. rexconfig owns agent messaging policy
and the versioned installation on hive.

Build with Zig 0.15.2 from the checkout root.

```sh
uv run --with ziglang==0.15.2 python -m ziglang build -Doptimize=ReleaseSmall -Dtarget=x86_64-linux-musl
```

The build reports the Git revision unless `-Dversion` overrides it. On hive,
`~/rexconfig/bin/install-teerex-build` builds and activates the revision in
`~/rexconfig/teerex.version`. [CI](docs/ci.md) documents the regression suites.

Licensed under [Apache-2.0](LICENSE) for teerex's original material. See
[RIGHTS.md](RIGHTS.md) for third-party rights.
