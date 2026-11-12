#!/usr/bin/env python3
"""Explicit named command hosts. No discovery, environment target, or retry."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import sys

MAX_CONFIG = 1024 * 1024
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
PATH_FIELDS = ("home", "socket", "rex", "teerex", "store")
REX_COMMANDS = {"observe", "watch", "send", "spawn", "run", "doctor", "offstage", "jobs", "adapters", "surfaces", "boards", "agents", "snapshot", "restore", "update", "recovery"}


def absolute(value, field):
    if not isinstance(value, str) or not value.startswith("/") or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(field + " must be an explicit absolute path without controls")
    return value


def load_config(config_path):
    path = absolute(config_path, "config")
    with open(path, "rb") as stream:
        raw = stream.read(MAX_CONFIG + 1)
    if len(raw) > MAX_CONFIG:
        raise ValueError("config exceeds 1 MiB")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate config key: " + key)
            result[key] = value
        return result
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=unique)
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("hosts"), dict):
        raise ValueError("config requires schema_version 1 and hosts object")
    if len(data["hosts"]) > 128:
        raise ValueError("at most 128 named hosts")
    return data


def resolve_host(config_path, name):
    if not isinstance(name, str) or not NAME.fullmatch(name):
        raise ValueError("invalid configured host name")
    config = load_config(config_path)
    if name not in config["hosts"]:
        raise ValueError("unknown configured host: " + name)
    source = config["hosts"][name]
    if not isinstance(source, dict):
        raise ValueError("host must be an object")
    host = dict(source, name=name)
    if not isinstance(host.get("host_id"), str) or not NAME.fullmatch(host["host_id"]):
        raise ValueError("host_id must be an explicit identifier")
    for field in PATH_FIELDS:
        absolute(host.get(field), field)
    if host.get("platform") not in ("macos-arm64", "linux-x86_64"):
        raise ValueError("platform must be macos-arm64 or linux-x86_64")
    if host.get("transport") not in ("local", "ssh"):
        raise ValueError("transport must be local or ssh")
    if host["transport"] == "ssh":
        address = host.get("address")
        if not isinstance(address, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}@[A-Za-z0-9][A-Za-z0-9.:-]{0,190}", address):
            raise ValueError("address must be a literal SSH destination, not options or a URL")
        if type(host.get("port")) is not int or not 1 <= host["port"] <= 65535:
            raise ValueError("port must be 1..65535")
        for field in ("known_hosts", "identity_file"):
            absolute(host.get(field), field)
    return host


def ssh_argv(host):
    # OpenSSH parses -o values again; keep spaces/quotes and percent tokens literal.
    known_hosts = host["known_hosts"].replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
    return ["ssh", "-F", "/dev/null", "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "GlobalKnownHostsFile=/dev/null", "-o", "UpdateHostKeys=no", "-o", "ControlMaster=no", "-o", "ControlPath=none",
            "-o", "IdentitiesOnly=yes", "-o", "ForwardAgent=no", "-o", "ClearAllForwardings=yes",
            "-o", "ConnectTimeout=10", "-o", 'UserKnownHostsFile="' + known_hosts + '"',
            "-i", host["identity_file"], "-p", str(host["port"]), host["address"]]


def command_argv(host, command):
    if not command:
        raise ValueError("a command is required")
    # Only parse options before the literal program-argv delimiter.
    options = command[:command.index("--")] if "--" in command else command
    if any(option in options for option in ("--socket", "--server", "-S", "--host", "--rex")) or ("--config" in options and command[0] != "agents"):
        raise ValueError("named host conflicts with explicit socket/server/host/config/rex")
    result = list(command)
    verb = result[0]
    if "--help" not in options:
        if verb in {"seat", "inbox", "ask", "send"} or (verb == "spawn" and "--profile" in options) or (verb == "agents" and result[1:2] == ["launch"]):
            at = 2 if verb in {"seat", "inbox", "agents"} else 1
            supplied = ["--socket", host["socket"], "--host", host["host_id"]]
            if "--store" not in options:
                supplied += ["--store", host["store"]]
            result[at:at] = supplied
        elif verb in REX_COMMANDS and not ((verb == "surfaces" and result[1:2] == ["palette"]) or (verb == "recovery" and result[1:2] == ["inspect"]) or verb == "agents"):
            # Existing nested commands expect their operation before options.
            at = 2 if verb in {"jobs", "adapters", "surfaces", "boards", "agents", "recovery"} else 1
            result[at:at] = ["--socket", host["socket"]]
    return [host["teerex"], "--rex", host["rex"], *result]


def receipt(host, argv):
    # No argv contents: briefs, commands, paths and captured terminal data can be private.
    return {"schema_version": 1, "kind": "target_selection", "host": host["name"],
            "host_id": host["host_id"], "transport": host["transport"],
            "server": "unix://" + host["socket"], "rex_executable": host["rex"],
            "teerex_executable": argv[0], "identity_basis": "explicit_configuration_not_observed_identity",
            "retry": False, "file_paths": "selected_command_host"}


def execute(host, command):
    argv = command_argv(host, command)
    print(json.dumps(receipt(host, argv), separators=(",", ":")), file=sys.stderr, flush=True)
    if host["transport"] == "ssh":
        # SSH's remote interface is a shell string; quote each literal argument exactly once.
        argv = [*ssh_argv(host), shlex.join(argv)]
    env = dict(os.environ)
    for key in ("REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT", "TEEREX_INTERNAL_REX"):
        env.pop(key, None)
    os.execvpe(argv[0], argv, env)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    for operation in ("resolve", "exec"):
        child = sub.add_parser(operation)
        child.add_argument("--config", required=True)
        child.add_argument("--host", required=True)
        if operation == "exec":
            child.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        host = resolve_host(args.config, args.host)
        if args.operation == "resolve":
            print(json.dumps({"schema_version": 1, "host": host, "identity_basis": "explicit_configuration_not_observed_identity"}, separators=(",", ":")))
        else:
            execute(host, args.command[1:] if args.command[:1] == ["--"] else args.command)
        return 0
    except (OSError, ValueError, UnicodeError) as exc:
        print(json.dumps({"schema_version": 1, "kind": "target_error", "error": str(exc), "retry": False}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
