"""Prepare frozen native palette menus; registration uses palette install plan/apply."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys


def read_config(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("expected_owned_regular_config")
        raw = f.read(262145)
    if len(raw) > 262144:
        raise ValueError("config_exceeds_262144_bytes")
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("duplicate_config_key")
            result[k] = v
        return result
    cfg = json.loads(raw, object_pairs_hook=unique)
    if cfg.get("schema_version") != 1:
        raise ValueError("schema_version_1_required")
    return cfg


def absolute(value):
    if not isinstance(value, str) or not os.path.isabs(value) or any(ord(c) < 32 for c in value):
        raise ValueError("absolute_path_required")
    return value


def quote(value):
    # JSON Unicode escapes are not Lua string escapes.
    return '"' + ''.join('\\' + c if c in '\\"' else '\\%03d' % ord(c) if ord(c) < 32 or ord(c) == 127 else c for c in value) + '"'


def literal(value):
    return "rex.json.decode(" + quote(json.dumps(value, ensure_ascii=False)) + ")"


def action(name, title, body, args=None):
    return ("rex.action{name=" + quote(name) + ",title=" + quote(title) + ",category=\"teerex\",args="
            + literal(args or {}) + ",run=function(ctx,args)\n" + body + "\nend}\n")


# rex.exec is a synchronous bounded controller, never the worker. agents launch
# creates the visible worker and enforces its own ACK-before-brief protocol.
PROMPT = """import os,subprocess,sys
name=sys.argv[1] or input('Agent name: ').strip()
brief=sys.argv[2] or input('Absolute brief file: ').strip()
if not name or not os.path.isabs(brief):
    raise SystemExit('Name and absolute brief file are required')
argv=sys.argv[3:]+['--name',name,'--brief-file',brief]
code=subprocess.run(argv).returncode
if code:
    input('Launch failed; inspect the receipt above before retrying. Enter to close.')
raise SystemExit(code)
"""

CONTROLLER = '''local function invoke(argv)
    local r=rex.exec(argv,{timeout=20})
    if type(r)~="table" or not r.ok then error("teerex menu command failed: "..rex.json.encode(r),0) end
    local v=rex.json.decode(r.stdout)
    if type(v)~="table" then error("teerex menu receipt unavailable",0) end
    return v
end
'''


def generate(o):
    absolute(o.file)
    binary = absolute(o.teerex)
    actions = []
    if o.operation == "agents":
        config = absolute(o.profiles)
        cfg = read_config(config)
        profiles = cfg.get("profiles")
        if not isinstance(profiles, dict) or not 1 <= len(profiles) <= 128:
            raise ValueError("profiles_object_1_to_128_required")
        for profile in sorted(profiles):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", profile) or not isinstance(profiles[profile], dict):
                raise ValueError("invalid_profile")
            name = "teerex_agent_" + hashlib.sha256(profile.encode()).hexdigest()[:16]
            command = [binary, "--rex", absolute(o.rex), "agents", "launch", "--config", config, "--profile", profile,
                       "--launch-wait-ms", "0"]
            body = '''if not ctx.session_id or not ctx.block_id then error("invoke from an attached terminal pane",0) end
local argv=''' + literal(command) + '''
for _,v in ipairs({"--session",ctx.session_id,"--starter-session",ctx.session_id,"--starter-block",ctx.block_id,
"--report-to-session",ctx.session_id,"--report-to-block",ctx.block_id}) do argv[#argv+1]=v end
if not args.name or not args.brief_file then
    local form=''' + literal([sys.executable, "-c", PROMPT]) + '''
    form[#form+1]=args.name or ""; form[#form+1]=args.brief_file or ""
    for _,v in ipairs(argv) do form[#form+1]=v end
    local made=rex.call("session.new_window",{session_id=ctx.session_id,window_label="Start an agent",focus=true,
        layout={block={flavor="com.superlogical.terminal.shell",label="Agent name and brief",options={command=form,exit={on_completion=true}}}}})
    if type(made)~="table" or not made.window_id then error("agent form creation uncertain; inspect before retry",0) end
    local view=rex.call("session.view",{session_id=ctx.session_id})
    if type(view)~="table" or view.active_window_id~=made.window_id then error("agent form focus unverified",0) end
    return {outcome="agent_form_opened",created=made,agent_launch="not_yet_attempted"}
end
if args.name=="" or args.brief_file:sub(1,1)~="/" then error("supply name and absolute brief_file",0) end
for _,v in ipairs({"--name",args.name,"--brief-file",args.brief_file}) do argv[#argv+1]=v end
return invoke(argv)'''
            actions.append((name, action(name, "Start an agent: " + profile, body, {"name": "string?", "brief_file": "string?"})))
    else:
        config = absolute(o.config)
        cfg = read_config(config)
        hosts = cfg.get("hosts")
        if not isinstance(hosts, dict) or not 1 <= len(hosts) <= 128:
            raise ValueError("hosts_object_1_to_128_required")
        for host, settings in sorted(hosts.items()):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", host) or not isinstance(settings, dict):
                raise ValueError("invalid_host")
            # Workspace definitions are opt-in extensions of a named-host record.
            workspaces = settings.get("workspaces", {"Terminal": {"cwd": settings.get("home"), "argv": ["/bin/sh"]}})
            if not isinstance(workspaces, dict) or not 1 <= len(workspaces) <= 128:
                raise ValueError("workspaces_object_1_to_128_required")
            for label, workspace in sorted(workspaces.items()):
                if not isinstance(label, str) or not 1 <= len(label.encode()) <= 128 or any(ord(c) < 32 for c in label):
                    raise ValueError("invalid_workspace_label")
                cwd = absolute(workspace.get("cwd"))
                argv = workspace.get("argv", ["/bin/sh"])
                if not isinstance(argv, list) or not argv or any(not isinstance(v, str) or '\0' in v for v in argv):
                    raise ValueError("workspace_argv_required")
                absolute(argv[0])
                session = workspace.get("session", host)
                if not isinstance(session, str) or not 1 <= len(session.encode()) <= 128:
                    raise ValueError("invalid_workspace_session_label")
                name = "teerex_host_" + hashlib.sha256((host + "\0" + label).encode()).hexdigest()[:16]
                base = [binary, "--config", config, "--host", host]
                body = "local s=invoke(" + literal(base + ["surfaces", "session", "ensure", "--label", session]) + ")\n"
                body += "local argv=" + literal(base + ["surfaces", "open", "--session"]) + "\nargv[#argv+1]=s.resolved.session_id\n"
                body += "for _,v in ipairs(" + literal(["--layout", "tab", "--label", label, "--cwd", cwd, "--", *argv]) + ") do argv[#argv+1]=v end\nreturn invoke(argv)"
                actions.append((name, action(name, host + ": " + label, body)))
    if len(actions) > 128:
        raise ValueError("menu_action_limit_128")
    source = "".join("-- teerex-surface-action:" + n + "\n" for n, _ in actions) + CONTROLLER + "".join(s for _, s in actions)
    data = source.encode()
    if len(data) > 262144:
        raise ValueError("menu_exceeds_262144_bytes")
    fd = os.open(o.file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return dict(schema_version=1, kind="surface_palette_result", outcome="fragment_written", file=o.file,
                names=[n for n, _ in actions], registered_in_running_server=False,
                next="Use surfaces palette install with this file to plan/apply registration")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("operation", choices=("agents", "hosts"))
    p.add_argument("--file", required=True)
    p.add_argument("--profiles", default=str(Path.home() / ".config/teerex/profiles.json"))
    p.add_argument("--config", default=str(Path.home() / ".config/teerex/hosts.json"))
    p.add_argument("--rex", help="absolute Rex executable for managed agent launch")
    p.add_argument("--teerex", required=True, help="absolute installed controller on the palette server's host")
    o = p.parse_args()
    try:
        result = generate(o)
        code = 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        result = dict(schema_version=1, kind="surface_palette_result", outcome="refused", failure_reason=str(e), registered_in_running_server=False)
        code = 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
