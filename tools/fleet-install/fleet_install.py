#!/usr/bin/env python3
"""Explicit, foreground fleet installation using teerex's shared named-host resolver."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
WORKER = HERE / "worker.py"
INSTALLER = REPO / "tools/install/teerex-install"
MAX_ASSET = 64 * 1024 * 1024


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        require(newurl.startswith("https://"), "asset redirect must remain HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_host(host):
    # The shared resolver owns the host schema. This checks the fleet prerequisites,
    # not a separate user-facing host registry or discovery mechanism.
    require(isinstance(host, dict), "resolved host must be an object")
    require(all(isinstance(host.get(k), str) and host[k] for k in
                ("name", "host_id", "home", "platform", "teerex")), "incomplete shared resolved host")
    require(host["platform"] in ("macos-arm64", "linux-x86_64"), "unsupported platform")
    require(host.get("transport") in ("local", "ssh"), "explicit transport required")
    if host["transport"] == "ssh":
        require(isinstance(host.get("address"), str) and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.:-]*", host["address"]), "SSH requires explicit user@hostname/IP")
        require(type(host.get("port")) is int and 1 <= host["port"] <= 65535, "invalid SSH port")
        for field in ("identity_file", "known_hosts"):
            require(isinstance(host.get(field), str) and not any(ord(c) < 32 or ord(c) == 127 or c in "%$" for c in host[field]), "SSH paths must be literal, without controls or expansion tokens")
            value = Path(host[field])
            require(value.is_absolute() and value.is_file(), "explicit existing " + field + " required; provision trust/credentials separately")
    install = host.get("install", {})
    require(isinstance(install, dict) and set(install) <= {"prefix", "bin_dir", "expected_hostname", "expected_user"}, "unknown installation-only option")
    return host


def transport_argv(host):
    encoded = base64.b64encode(WORKER.read_bytes()).decode()
    code = "import sys;assert sys.version_info >= (3,9), 'Python 3.9+ required';import base64;exec(compile(base64.b64decode(" + repr(encoded) + "),'<teerex-fleet-worker>','exec'))"
    if host["transport"] == "local":
        return [sys.executable, "-c", code]
    # Ignore implicit SSH aliases, proxies, local commands, forwarding and multiplexers.
    return ["ssh", "-F", "/dev/null", "-T", "-i", host["identity_file"],
            "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "UserKnownHostsFile=\"" + host["known_hosts"].replace("\\", "\\\\").replace('"', '\\"') + "\"", "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", "UpdateHostKeys=no", "-o", "ForwardAgent=no", "-o", "ClearAllForwardings=yes",
            "-o", "PermitLocalCommand=no", "-o", "ControlMaster=no", "-o", "ControlPath=none",
            "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2",
            "-p", str(host["port"]), host["address"], "python3 -c " + shlex.quote(code)]


def invoke(host, request):
    try:
        result = subprocess.run(transport_argv(host), input=json.dumps(request), text=True,
                                capture_output=True, timeout=240)
        try:
            value = json.loads(result.stdout)
        except ValueError:
            return {"ok": False, "error": "transport did not return worker JSON", "exit_code": result.returncode,
                    "stderr": result.stderr[-8192:], "outcome": "unknown" if request["phase"] == "apply" else "not_applied"}
        require(isinstance(value, dict) and type(value.get("ok")) is bool, "invalid worker result")
        if result.returncode and value["ok"]:
            return {"ok": False, "error": "transport exited after success receipt", "receipt": value,
                    "exit_code": result.returncode, "outcome": "unknown"}
        return value
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "transport exceeded 240 seconds; inspect the target before retrying",
                "outcome": "unknown" if request["phase"] == "apply" else "not_applied"}
    except (OSError, ValueError) as error:
        return {"ok": False, "error": str(error),
                "outcome": "unknown" if request["phase"] == "apply" else "not_applied"}


def asset_bytes(name, version, source):
    limit = 1024 * 1024 if name == "SHA256SUMS" else MAX_ASSET
    if source:
        path = Path(source) / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size <= limit, "invalid/oversized local asset: " + name)
        return path.read_bytes()
    url = "https://github.com/jcbbge/teerex/releases/download/" + version + "/" + name
    with urllib.request.build_opener(HTTPSRedirect).open(url, timeout=60) as response:
        data = response.read(limit + 1)
    require(len(data) <= limit, "oversized release asset")
    return data


def bundle(plan, source):
    archive = asset_bytes(plan["asset"], plan["version"], source)
    checksums = asset_bytes("SHA256SUMS", plan["version"], source)
    require(len(checksums) <= 1024 * 1024, "oversized SHA256SUMS")
    matches = [line.split() for line in checksums.decode("utf-8").splitlines()
               if len(line.split()) >= 2 and line.split()[1].lstrip("*") == plan["asset"]]
    require(len(matches) == 1 and len(matches[0]) == 2 and re.fullmatch(r"[a-fA-F0-9]{64}", matches[0][0]),
            "SHA256SUMS must contain exactly one valid entry for " + plan["asset"])
    require(hashlib.sha256(archive).hexdigest() == matches[0][0].lower(), "archive checksum mismatch: " + plan["asset"])
    # The core installer repeats this and validates exact members/native format/help.
    return {plan["asset"]: base64.b64encode(archive).decode(), "SHA256SUMS": base64.b64encode(checksums).decode()}


def run_fleet(resolved_hosts, options):
    """Integration API. options is a dict using the same names as CLI argparse vars."""
    version = options["version"]
    apply = options.get("apply", False)
    operation = options.get("operation", "install")
    require(isinstance(version, str) and re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?", version), "explicit release tag required")
    require(operation in ("install", "rollback"), "unsupported operation")
    require(resolved_hosts and len(resolved_hosts) <= 32, "select 1..32 explicit hosts")
    hosts = [validate_host(h) for h in resolved_hosts]
    require(len({h["name"] for h in hosts}) == len(hosts), "duplicate host name")
    require(len({h["host_id"] for h in hosts}) == len(hosts), "multiple names select the same declared host_id")
    requests, receipts = [], []
    installer = INSTALLER.read_bytes()
    installer_fields = dict(installer=base64.b64encode(installer).decode(), installer_sha256=hashlib.sha256(installer).hexdigest())
    for host in hosts:
        request = {"phase": "plan", "host": host, "version": version, "operation": operation,
                   "path_consent": options.get("path_consent", False),
                   "replace_launcher": options.get("replace_launcher", False), **installer_fields}
        requests.append(request)
        receipts.append({"host": host["name"], "host_id": host["host_id"], "transport": host["transport"], **invoke(host, request)})
    report = {"schema_version": 1, "operation": operation, "requested_apply": apply,
              "fleet_atomic": False, "hosts": receipts, "ok": all(r["ok"] for r in receipts), "applied": False}
    if not apply or not report["ok"]:
        return report
    # Download/verify every required platform asset before the first mutation.
    assets = {}
    try:
        for receipt in receipts:
            plan = receipt["plan"]
            if plan["action"] in ("install", "upgrade") and plan["asset"] not in assets:
                assets[plan["asset"]] = bundle(plan, options.get("source"))
    except Exception as error:
        report.update(ok=False, preflight_error=str(error))
        return report
    stopped = False
    for host, request, receipt in zip(hosts, requests, receipts):
        if stopped:
            receipt.update(ok=False, outcome="skipped_after_failure")
            continue
        request.update(phase="apply", plan=receipt["plan"], assets=assets.get(receipt["plan"]["asset"], {}))
        outcome = invoke(host, request)
        receipt.update(outcome)
        receipt["apply_attempted"] = True
        report["applied"] = True
        if not outcome["ok"]:
            stopped = True
    report["ok"] = all(r["ok"] for r in receipts)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(prog='teerex fleet', description=__doc__, epilog="No discovery, daemon, credential capture, host-key enrollment, profile/config edits, manual-folder adoption or Rex restart. --path verifies only transport PATH; configure shells separately. Partial success is retained, never silently retried.")
    parser.add_argument("operation", choices=("install", "rollback"))
    parser.add_argument("--config", type=Path, required=True, help="absolute shared named-target configuration")
    parser.add_argument("--host", action="append", required=True, help="explicit named host; repeat for m5/hive/m1 or other configured names")
    parser.add_argument("--version", required=True, help="explicit release tag, e.g. v0.1.0-alpha.5")
    parser.add_argument("--apply", action="store_true", help="apply after all-host preflight; default prints read-only plans")
    parser.add_argument("--path", dest="path_consent", action="store_true", help="consent to launcher creation in a directory already on target transport PATH")
    parser.add_argument("--replace-launcher", action="store_true", help="with --path, retain a colliding manual file/symlink as backup; never delete its target")
    parser.add_argument("--from", dest="source", type=Path, help="reviewed local platform archives and SHA256SUMS; still verified")
    args = parser.parse_args(argv)
    try:
        sys.path.insert(0, str(REPO / "src"))
        from targets import resolve_host
        hosts = [resolve_host(str(args.config), name) for name in args.host]
        report = run_fleet(hosts, vars(args))
    except Exception as error:
        report = {"schema_version": 1, "ok": False, "error": str(error)}
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
