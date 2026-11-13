#!/usr/bin/env python3
"""Fetch only the previous documented alpha.5 binary and verify its release hash."""
import argparse
import hashlib
import io
from pathlib import Path
import tarfile
import urllib.request

BASE = "https://github.com/jcbbge/teerex/releases/download/v0.1.0-alpha.5/"


def download(name, maximum):
    with urllib.request.urlopen(BASE + name, timeout=60) as response:
        value = response.read(maximum + 1)
    if len(value) > maximum:
        raise ValueError("release_download_limit")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, choices=("x86_64-linux", "aarch64-macos"))
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if not args.out.is_absolute() or args.out.exists():
        parser.error("new absolute output required")
    name = "teerex-v0.1.0-alpha.5-" + args.platform + ".tar.gz"
    sums = download("SHA256SUMS", 65536).decode().splitlines()
    matches = [line.split()[0] for line in sums if len(line.split()) == 2 and line.split()[1].lstrip("*") == name]
    archive = download(name, 32 * 1024 * 1024)
    if len(matches) != 1 or hashlib.sha256(archive).hexdigest() != matches[0]:
        raise ValueError("previous_release_checksum_mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        matches = [entry for entry in tar.getmembers() if entry.name == "teerex" and entry.isfile() and 0 < entry.size <= 32 * 1024 * 1024]
        if len(matches) != 1:
            raise ValueError("previous_binary_not_unique_regular_file")
        value = tar.extractfile(matches[0]).read()
    with args.out.open("xb") as output:
        args.out.chmod(0o700)
        output.write(value)


if __name__ == "__main__":
    main()
