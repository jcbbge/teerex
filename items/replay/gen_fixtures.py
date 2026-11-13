"""Author deterministic synthetic byte fixtures, never real terminal captures.

Bytes/expected facts are independently declared here and facts files respectively.
Run --check to regenerate in isolation and compare every committed file. Replay
acceptance then feeds these bytes through its private Rex terminal, not an emulator.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def generate(root):
    scenes = {
        "utf8-split": [(b"na\xc3\xafve \xe2", 0), (b"\x9c\x93 \xe6\x97\xa5\xe6\x9c\xac\r\n", 50)],
        "multiline-error": [(b'\x1b[31merror: config invalid\r\n  at line 3\r\n  expected "="\x1b[0m\r\n\x1b]7501;state=done\x07', 0)],
        "progress": [(f"\r[{'#' * bars}{' ' * (8-bars)}] {percent}%\x1b]7501;state=working;progress={percent}\x07".encode(), t)
                     for bars, percent, t in ((2, 25, 0), (4, 50, 200), (8, 100, 400))],
        "confirm": [(b"Delete 3 files? [y/N]", 0), (b"\r\nAborted.\r\n", 100)],
        "resize-prompt": [(b"\x1b[2J\x1b[H+" + b"-" * 78 + b"+\x1b[24;1H" + "❯ ".encode(), 0),
                          (b"\x1b[2J\x1b[H+" + b"-" * 58 + b"+\x1b[20;1H" + "❯ ".encode(), 100)]}
    for name, segments in scenes.items():
        destination = root / name
        destination.mkdir(mode=0o700, parents=True)
        chunks = []
        checkpoints = []
        data = b""
        for index, (segment, elapsed) in enumerate(segments):
            chunks.append([len(data), len(segment), elapsed])
            data += segment
            checkpoints.append(dict(id="part-" + str(index), offset=len(data)))
        checkpoints.append(dict(id="end", offset=len(data)))
        events = [dict(type="resize", columns=80, rows=24, offset=0, t_ms=0)]
        if name == "resize-prompt":
            events.append(dict(type="resize", columns=60, rows=20, offset=chunks[1][0], t_ms=100))
        events.append(dict(type="child_exited", exit_code=2 if name == "multiline-error" else 0, offset=len(data), t_ms=segments[-1][1]))
        value = dict(schema_version=1, kind="teerex_tty_fixture", id="synthetic-" + name,
            provenance=dict(basis="synthetic", captured_by="authored synthetic generator", generator="items/replay/gen_fixtures.py",
                            rex=dict(version="not_acquired", platform="not_acquired", api_revision=None)),
            application=dict(name="fake_tui.py", version="v1", version_basis="declared"),
            terminal=dict(start="blank_verified", initial=dict(columns=80, rows=24)),
            stream=dict(bytes=len(data), sha256=sha(data), snapshot_sha256=sha(b""), complete=True, end="child_exited"),
            chunks=chunks, events=events, checkpoints=checkpoints, omissions=[dict(what="snapshot", why="authored bytes, not a capture")])
        for filename, content in (("stream.bin", data), ("snapshot.bin", b""), ("fixture.json", (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())):
            path = destination / filename
            path.write_bytes(content)
            path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("fixtures"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        with tempfile.TemporaryDirectory(prefix="replay-regenerate-") as temporary:
            fresh = Path(temporary)
            generate(fresh)
            expected = {p.relative_to(fresh): p.read_bytes() for p in fresh.rglob("*") if p.is_file()}
            actual = {p.relative_to(args.out): p.read_bytes() for p in args.out.rglob("*") if p.is_file()}
            if expected != actual:
                raise SystemExit("synthetic fixture regeneration differs")
            print("5 synthetic fixtures regenerate byte-identically")
    else:
        generate(args.out)


if __name__ == "__main__":
    main()
