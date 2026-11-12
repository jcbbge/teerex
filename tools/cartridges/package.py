#!/usr/bin/env python3
"""Build a local, reviewable catalog of separate native cartridges; never install."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from cartridges import digest, manifest, require, version

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zig", default="zig")
    parser.add_argument("--platform", choices=("aarch64-macos", "x86_64-linux"), required=True)
    parser.add_argument("--version", required=True, help="exact package version without leading v")
    parser.add_argument("--output", type=Path, required=True, help="new destination directory")
    args = parser.parse_args()
    require(version(args.version), "explicit semantic version required")
    require(not args.output.exists() and not args.output.is_symlink(), "output must not already exist")
    require(subprocess.check_output([args.zig, "version"], text=True).strip() == "0.15.2", "requires Zig 0.15.2")
    source = json.loads((HERE / "manifests/source.json").read_text())
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=REPO, text=True))
    target = "aarch64-macos" if args.platform == "aarch64-macos" else "x86_64-linux-musl"
    recipes = [p for p in source["packages"] if args.platform in p["platforms"]]
    # Build in scratch space. Publish the completed catalog with one rename.
    args.output = args.output.absolute()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="teerex-cartridges-build-") as temporary:
        prefix = Path(temporary) / "bin-prefix"
        for recipe in recipes:
            subprocess.run([args.zig, "build", "--build-file", str(HERE / "build.zig"),
                            "--prefix", str(prefix), "-Doptimize=ReleaseSmall", "-Dtarget=" + target,
                            "-Dcartridge=" + recipe["id"]], cwd=REPO, check=True)
        stage = Path(tempfile.mkdtemp(prefix=".catalog-", dir=args.output.parent))
        try:
            entries = []
            for recipe in recipes:
                key = recipe["id"]
                destination = stage / key / args.version
                destination.mkdir(parents=True)
                exe = "teerex-" + key
                shutil.copyfile(prefix / "bin" / exe, destination / exe)
                (destination / exe).chmod(0o700)
                for name, source_path in (("README.md", REPO / "items" / key / "README.md"), ("RIGHTS.md", REPO / "RIGHTS.md")):
                    shutil.copyfile(source_path, destination / name)
                    (destination / name).chmod(0o600)
                value = manifest(dict(schema_version=1, id=key, version=args.version, status="experimental", kind="program",
                    platform=args.platform, entrypoint=[exe], dependencies={}, data_policy="retain",
                    permissions=recipe["permissions"],
                    provenance=dict(repository="https://github.com/jcbbge/teerex", source_commit=revision,
                                    source_tree_dirty=dirty, rights="RIGHTS.md", build="Zig 0.15.2 ReleaseSmall"),
                    compatibility=dict(rex_api_revisions=recipe["rex_api_revisions"], note=recipe["note"]),
                    files=[dict(path=p.name, sha256=digest(p), executable=bool(p.stat().st_mode & 0o111)) for p in sorted(destination.iterdir())]))
                (destination / "manifest.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
                entries.append(dict(path=str(destination.relative_to(stage)), manifest_sha256=digest(destination / "manifest.json")))
            (stage / "catalog.json").write_text(json.dumps(dict(schema_version=1, packages=entries), indent=2) + "\n")
            stage.rename(args.output)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    print(json.dumps(dict(catalog=str(args.output), platform=args.platform, cartridges=[p["id"] for p in recipes], source_commit=revision, source_tree_dirty=dirty)))


if __name__ == "__main__":
    main()
