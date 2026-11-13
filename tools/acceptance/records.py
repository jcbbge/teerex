"""Readiness schema and verdict shared by the executor and native packager.

Rows are acquired evidence, never inferred from packaging or nominal API support.
A caller-supplied executor label is attribution, not authentication.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RUBRIC = "docs/planning/workloads/readiness-acceptance.md"
ROWS = tuple("R" + str(n) for n in range(1, 12))
HEX = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read_json(path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 1048576, "invalid_readiness_file")
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "duplicate_readiness_key")
            value[key] = item
        return value
    return json.loads(path.read_text(), object_pairs_hook=unique)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contract(item, root=ROOT):
    value = read_json(root / "tools/acceptance/contracts" / (item + ".json"))
    # Managed execution is part of readiness, alongside the native payload.
    value["covered_paths"] = list(dict.fromkeys([*value["covered_paths"], "tools/cartridges/cartridges.py",
        "tools/cartridges/package.py", "tools/cartridges/manifests/source.json"]))
    return value


def inputs_hash(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def input_snapshot(paths, root=ROOT):
    names = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", *paths], cwd=root).decode().split("\0")
    files = {}
    for name in sorted(set(filter(None, names))):
        path = root / name
        require(not path.is_symlink(), "symlink_readiness_input")
        if path.exists():
            require(path.is_file(), "nonregular_readiness_input")
            files[name] = sha(path)
    return dict(covered_files_sha256=files, covered_inputs_sha256=inputs_hash(files))


def verdict(record):
    failed = set()
    runs = record.get("runs", [])
    revisions = set()
    counts = {}
    if not runs:
        failed.update(ROWS)
    instances = set()
    for run in runs:
        instance = run.get("server_instance_sha256")
        if not instance or instance in instances:
            failed.add("R3")
        instances.add(instance)
        rows = run.get("rows", {})
        for row in ROWS:
            if rows.get(row, {}).get("pass") is not True:
                failed.add(row)
        revision = run.get("rex", {}).get("api_revision")
        if all(rows.get(row, {}).get("pass") is True for row in ROWS):
            revisions.add(revision)
            counts[revision] = counts.get(revision, 0) + 1
        if not run.get("executor") or run.get("independent_executor") is not True:
            failed.add("R12")
    if not counts or any(n < 3 for n in counts.values()):
        failed.add("R3")
    if record.get("source_tree_dirty") is not False:
        failed.add("source_tree_dirty")
    return dict(verdict="not_ready" if failed else "ready", failed_rows=sorted(failed),
                evidenced_api_revisions=sorted(revisions))


def validate(record, item=None, platform=None, expected_paths=None):
    require(isinstance(record, dict) and record.get("schema_version") == 1 and record.get("kind") == "cartridge_readiness", "not_a_readiness_run")
    require(isinstance(record.get("id"), str) and re.fullmatch(r"[a-z][a-z0-9-]{0,47}", record["id"]), "invalid_readiness_id")
    require(record.get("platform") in ("x86_64-linux", "aarch64-macos"), "invalid_readiness_platform")
    require(item is None or record["id"] == item, "readiness_id_mismatch")
    require(platform is None or record["platform"] == platform, "readiness_platform_mismatch")
    require(isinstance(record.get("source_commit"), str) and COMMIT.fullmatch(record["source_commit"]), "invalid_readiness_commit")
    require(type(record.get("source_tree_dirty")) is bool, "invalid_readiness_dirty_flag")
    require(record.get("rubric") == RUBRIC and isinstance(record.get("rubric_sha256"), str) and HEX.fullmatch(record["rubric_sha256"]), "invalid_readiness_rubric")
    require(isinstance(record.get("payload_sha256"), str) and HEX.fullmatch(record["payload_sha256"]), "invalid_readiness_payload_hash")
    paths = record.get("covered_paths")
    require(isinstance(paths, list) and paths and all(isinstance(p, str) for p in paths) and len(paths) == len(set(paths)), "invalid_readiness_paths")
    for path in paths:
        require(isinstance(path, str) and not PurePosixPath(path).is_absolute() and str(PurePosixPath(path)) == path and ".." not in PurePosixPath(path).parts, "unsafe_readiness_path")
    require(expected_paths is None or paths == expected_paths, "readiness_coverage_mismatch")
    if "covered_files_sha256" in record or "covered_inputs_sha256" in record:
        files = record.get("covered_files_sha256")
        require(isinstance(files, dict) and files, "invalid_readiness_input_files")
        for name, digest in files.items():
            require(isinstance(name, str) and any(name == p or name.startswith(p + "/") for p in paths)
                    and ".." not in PurePosixPath(name).parts and not PurePosixPath(name).is_absolute()
                    and isinstance(digest, str) and HEX.fullmatch(digest), "invalid_readiness_input_file")
        require(record.get("covered_inputs_sha256") == inputs_hash(files), "readiness_input_hash_mismatch")
    runs = record.get("runs")
    require(isinstance(runs, list) and len(runs) <= 128, "invalid_readiness_runs")
    for run in runs:
        require(isinstance(run, dict) and isinstance(run.get("rows"), dict) and set(run["rows"]) == set(ROWS), "invalid_readiness_rows")
        require(isinstance(run.get("executor"), str) and (not run["executor"] or re.fullmatch(r"(?:ci:https://[^\s]+|local:[a-zA-Z0-9_.-]+:[a-zA-Z0-9_.-]+)", run["executor"])), "invalid_readiness_executor")
        require(type(run.get("independent_executor")) is bool, "invalid_readiness_independence")
        require(isinstance(run.get("server_instance_sha256"), str) and HEX.fullmatch(run["server_instance_sha256"]), "invalid_readiness_server_identity")
        rex = run.get("rex")
        require(isinstance(rex, dict) and type(rex.get("api_revision")) is int and 10 <= rex["api_revision"] <= 13, "invalid_readiness_api")
        require(isinstance(rex.get("sha256"), str) and HEX.fullmatch(rex["sha256"]), "invalid_readiness_rex_hash")
        require(isinstance(rex.get("version"), str) and isinstance(rex.get("commit"), str), "invalid_readiness_rex_identity")
        require(all(isinstance(run.get(k), str) and run[k] for k in ("os", "arch", "started_at", "finished_at")), "invalid_readiness_run_identity")
        for row in run["rows"].values():
            require(isinstance(row, dict) and type(row.get("pass")) is bool and isinstance(row.get("detail"), str) and len(row["detail"]) <= 512, "invalid_readiness_row")
    computed = verdict(record)
    require(all(record.get(k) == v for k, v in computed.items()), "readiness_verdict_mismatch")
    return record


def readiness(item, platform, revision, root=ROOT, payload_hash=None):
    path = root / "tools/cartridges/readiness" / (item + "-" + platform + ".json")
    if not path.exists():
        return "absent", None
    mapping = contract(item, root)
    record = validate(read_json(path), item, platform)
    if "covered_inputs_sha256" not in record:
        return "stale:missing_content_hash", None
    require(record["covered_paths"] == mapping["covered_paths"], "readiness_coverage_mismatch")
    if record["verdict"] != "ready":
        return "experimental", None
    current = input_snapshot(record["covered_paths"], root)
    if current["covered_inputs_sha256"] != record["covered_inputs_sha256"]:
        before, after = record["covered_files_sha256"], current["covered_files_sha256"]
        changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
        return "stale:" + ",".join(changed), None
    if sha(root / RUBRIC) != record["rubric_sha256"]:
        return "stale:" + RUBRIC, None
    # Artifact bytes and source commit describe the measured run. Covered
    # input content is the staleness authority, including across rebuilds.
    return "ready", dict(record=str(path.relative_to(root)), source_commit=record["source_commit"], covered_inputs_sha256=record["covered_inputs_sha256"],
                         measured_payload_sha256=record["payload_sha256"], evidenced_api_revisions=record["evidenced_api_revisions"])
