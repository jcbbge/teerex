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
# Selectors belong to complete leaves, not command families. Offline leaves receive
# no Rex target; board state/rendering still needs its selected command-host store.
SELECTORS = {("board", "feed"): ("socket",), **{(verb,): ("socket",) for verb in
                ("observe", "watch", "spawn", "run", "run-visible", "doctor", "offstage", "snapshot", "restore", "update")},
             **{("surfaces", op): ("socket",) for op in ("open", "ensure", "resolve", "inspect", "rename", "move", "focus", "close")},
             ("surfaces", "session", "ensure"): ("socket",),
             ("surfaces", "palette", "install"): ("socket",),
             **{("adapters", op): ("socket",) for op in ("generate", "call")},
             **{("jobs", op): ("socket",) for op in ("track", "inspect", "adopt", "present", "forget")},
             **{("recovery", op): ("socket",) for op in ("snapshot", "restore", "update")},
             **{("state", op): ("store",) for op in ("inspect", "remap-preview", "remap-apply")},
             ("fleet",): ("store",), ("probe",): ("socket",),
             **{(verb,): ("socket", "host", "store") for verb in ("send", "ask", "try-route", "inbox")},
             **{(verb, op): ("socket", "host", "store") for verb, operations in
                (("seat", ("register", "inspect", "clear")), ("inbox", ("append", "inspect", "clear")),
                 ("fleet", ("report", "forget"))) for op in operations},
             **{("clutch", op): ("socket",) for op in ("take", "release", "status", "palette")},
             **{("records", op): (("socket", "host", "records_store") if op in ("park", "resume", "navigate") else ("records_store",)) for op in
                ("init", "new", "park", "add", "attach", "set", "close", "show", "resume", "navigate", "list", "lint", "export", "forget", "pin", "decide", "claim-status", "revalidate")},
             ("agents", "launch"): ("socket", "host", "store")}


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
    for field in ("records_store", "recovery_store"):
        if field in host:
            absolute(host[field], field)
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


def ssh_argv(host, *, tty=False):
    # OpenSSH parses -o values again; keep spaces/quotes and percent tokens literal.
    known_hosts = host["known_hosts"].replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
    return ["ssh", "-F", "/dev/null", "-tt" if tty else "-T", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "GlobalKnownHostsFile=/dev/null", "-o", "UpdateHostKeys=no", "-o", "ControlMaster=no", "-o", "ControlPath=none",
            "-o", "IdentitiesOnly=yes", "-o", "ForwardAgent=no", "-o", "ClearAllForwardings=yes",
            "-o", "ConnectTimeout=10", "-o", 'UserKnownHostsFile="' + known_hosts + '"',
            "-i", host["identity_file"], "-p", str(host["port"]), host["address"]]


def command_argv(host, command):
    if not command:
        raise ValueError("a command is required")
    # Only parse options before the literal program-argv delimiter.
    options = command[:command.index("--")] if "--" in command else command
    flags = {option.split("=", 1)[0] for option in options if option.startswith("-")}
    at = next((i for i, arg in enumerate(options) if arg.startswith("-")), len(options))
    leaf = tuple(options[:at])
    # The native board bridge accepts both boards seat OP and root seat OP,
    # as well as boards inbox/fleet renderers. Preserve the user's spelling.
    if leaf[:1] == ("boards",):
        leaf = leaf[1:]
    leaf_config = leaf[:1] == ("agents",) or leaf == ("fleet",)
    if flags.intersection(("--socket", "--server", "-S", "--host", "--rex")) or ("--config" in flags and not leaf_config):
        raise ValueError("named host conflicts with explicit socket/server/host/config/rex")
    result = list(command)
    if "--help" not in flags:
        selectors = SELECTORS.get(leaf, ())
        if leaf == ("spawn",) and "--profile" in flags:
            selectors = ("socket", "host", "store")
        supplied = []
        if leaf in (("snapshot",), ("restore",), ("recovery", "snapshot"), ("recovery", "restore"), ("recovery", "inspect")) and not flags.intersection(("--directory", "--root")):
            supplied += ["--root", host.get("recovery_store", host["home"] + "/.local/state/teerex-recovery")]
        for field in selectors:
            if field in ("store", "records_store") and "--store" in flags:
                continue  # Existing explicit command-host store override remains supported.
            flag = "store" if field == "records_store" else field
            value = host.get("records_store", host["home"] + "/.local/state/teerex-records") if field == "records_store" else host["host_id" if field == "host" else field]
            supplied += ["--" + flag, value]
        result[at:at] = supplied
    return [host["teerex"], "--rex", host["rex"], *result]


def receipt(host, argv):
    # No argv contents: briefs, commands, paths and captured terminal data can be private.
    return {"schema_version": 1, "kind": "target_selection", "host": host["name"],
            "host_id": host["host_id"], "transport": host["transport"],
            "server": "unix://" + host["socket"], "rex_executable": host["rex"],
            "teerex_executable": argv[0], "identity_basis": "explicit_configuration_not_observed_identity",
            "retry": False, "file_paths": "selected_command_host"}


def execute(host, command, *, tty=False):
    argv = command_argv(host, command)
    print(json.dumps(receipt(host, argv), separators=(",", ":")), file=sys.stderr, flush=True)
    if host["transport"] == "ssh":
        # SSH's remote interface is a shell string; quote each literal argument exactly once.
        argv = [*ssh_argv(host, tty=tty), shlex.join(argv)]
    env = dict(os.environ)
    for key in ("REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT", "TEEREX_INTERNAL_REX"):
        env.pop(key, None)
    os.execvpe(argv[0], argv, env)


class ActionParser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: {message}\n" + (f"next: {self.prog} --help\n" if (sys.stdin.isatty() and sys.stderr.isatty()) else ""))


def main(argv=None):
    parser = ActionParser(prog='teerex targets', description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    for operation in ("resolve", "exec"):
        child = sub.add_parser(operation)
        child.add_argument("--config", required=True)
        child.add_argument("--host", required=True)
        if operation == "exec":
            child.add_argument("--tty", action="store_true", help="explicitly force an SSH PTY; local targets retain inherited streams without allocating a PTY; never use for machine-readable callbacks")
            child.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        host = resolve_host(args.config, args.host)
        # The ordinary resolver supplies metadata to the existing in-process hook;
        # standalone use has no hook and never gains a telemetry dependency.
        calls = sys.modules.get("teerex_calls")
        if calls is not None:
            server = "unix://" + host["socket"]
            if host["transport"] == "ssh":
                server = "ssh://" + host["address"] + ":" + str(host["port"]) + host["socket"]
            calls.resolved_target(server)
        if args.operation == "resolve":
            print(json.dumps({"schema_version": 1, "host": host, "identity_basis": "explicit_configuration_not_observed_identity"}, separators=(",", ":")))
        else:
            execute(host, args.command[1:] if args.command[:1] == ["--"] else args.command, tty=args.tty)
        return 0
    except (OSError, ValueError, UnicodeError) as exc:
        print(json.dumps({"schema_version": 1, "kind": "target_error", "error": str(exc), "retry": False}), file=sys.stderr)
        if (sys.stdin.isatty() and sys.stderr.isatty()): print("next: Check the selected host and configuration file; run teerex targets resolve --help for the required flags.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
