const std = @import("std");
const version = @import("build_version").version;

const usage =
    \\teerex: an inspectable Rex operating layer
    \\Usage: teerex [--rex ABS] COMMAND ...
    \\       teerex --config ABS --host NAME COMMAND ...
    \\       teerex targets resolve --config ABS --host NAME
    \\       teerex targets exec --config ABS --host NAME [--tty] -- COMMAND ...
    \\       teerex --version
    \\
    \\Operating-layer commands:
    \\  surfaces resolve|session ensure|ensure|open|inspect|rename|move|focus|close|palette  Visible terminals and native palette plans
    \\  boards inbox|fleet|calls|friction|probe|state                Live boards, typed store and remap plans
    \\  seat register|inspect|clear              Exact-address operator seat
    \\  inbox append|inspect|clear                    Private retained messages
    \\  ask                                          Complete typed decisions or explicit resolution
    \\  agents launch|profiles|shell|ack|deliver|inspect|stop|present
    \\         exec|exited|channel|fence-probe       Compute callbacks / local delivery / fence checks
    \\  spawn --profile NAME --profiles ABS           Managed protocol-ACK-before-brief launch
    \\  records init|new|park|add|attach|set|close|show|resume|navigate|list|lint|export|forget  Private evidence and reasoning
    \\  recovery snapshot|inspect|restore|update      Private snapshots and reviewed restoration
    \\  snapshot|restore|update                       Recovery aliases; update is manual handoff
    \\  fleet install|rollback                       Explicit named-host installation plan/apply
    \\  cartridges install|list|run|activate|remove|restore  Independent native payloads
    \\  cartridges doctor|repair                     Read-only findings; explicit old-stage cleanup plans
    \\  mcp [--print-config claude|codex|pi]           Local stdio MCP tools; registration snippets only
    \\  targets resolve|exec                         Named-host lookup and explicit transport
    \\  run-visible                                  Visible noninteractive argv, output and actual exit
    \\  replay record|play|live                       Capture bytes, faithful replay and independent live checks
    \\  clutch take|release|status|palette  Cooperative human takeover and hand-back
    \\Existing tools: observe, compare, watch, run, offstage, doctor, send, spawn,
    \\                jobs, adapters, maneuver-check, filter
    \\Socket verbs default --socket from percent-decoded REX_SERVER (unix://), then platform home/runtime path.
    \\Defaulted observe/watch/doctor and boards probe receipts report socket_source. Explicit and named-host calls retain their contracts.
    \\Use COMMAND --help for exact flags, effects, evidence and limits.
    \\Who: operators and agents. What: inspectable programs, not a Rex fork/plugin daemon.
    \\When: explicit invocation; every managed agent/board remains visible and controllable.
    \\Where: configured command host; paths belong there, never silently uploaded.
    \\Why: report actual activity/results and unknowns, not infer readiness or completion.
    \\How: explicit config/host or socket/full IDs; no retries, fallback or autostart.
    \\Python3.9+ is required for targets, boards, agents, recovery, records, fleet, cartridges, replay, mcp and palette install.
    \\Legacy direct-socket native tools do not require Python. SSH trust/key are explicit.
    \\Native call history adds no runtime dependency; missing end records stay unknown.
    \\Personal install/restart/close/config actions need their own authorization.
    \\Guides: docs/alpha5.md and items/{surfaces,boards,agents,recovery,records}/README.md.
    \\
;

pub fn main() void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    @import("rex_boards").call_log.server_uri = frictionServer;
    @import("rex_boards").call_log.start(arena.allocator(), version);
    run(arena.allocator()) catch |err| {
        std.debug.print("teerex: {s}\n", .{@errorName(err)});
        finish(arena.allocator(), 1);
    };
    @import("rex_boards").call_log.end(arena.allocator(), 0);
}

fn finish(allocator: std.mem.Allocator, code: u8) noreturn {
    @import("rex_boards").call_log.end(allocator, code);
    std.process.exit(code);
}

fn python(allocator: std.mem.Allocator, args: []const []const u8) !void {
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", try @import("rex_boards").call_log.namedHostPython(allocator, @embedFile("targets.py")) });
    try argv.appendSlice(allocator, args);
    return std.process.execv(allocator, argv.items);
}

fn send(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    var native: std.ArrayList([]const u8) = .empty;
    var route: std.ArrayList([]const u8) = .empty;
    var store: ?[]const u8 = null;
    var host: ?[]const u8 = null;
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--store") or std.mem.eql(u8, args[i], "--host")) {
            if (i + 1 >= args.len) return error.SendRouteOptionNeedsValue;
            if (std.mem.eql(u8, args[i], "--store")) {
                if (store != null) return error.RepeatedSendStore;
                store = args[i + 1];
            } else {
                if (host != null) return error.RepeatedSendHost;
                host = args[i + 1];
            }
            i += 1;
        } else {
            try native.append(allocator, args[i]);
        }
    }
    if (store != null or host != null) {
        if (store == null or host == null) return error.SendStoreAndHostRequiredTogether;
        try route.appendSlice(allocator, &.{ "--store", store.?, "--host", host.? });
        try route.appendSlice(allocator, native.items);
        if (try @import("rex_boards").tryRoute(allocator, route.items)) |code| return code;
    }
    return @import("rex_send").run(allocator, native.items);
}

fn run(allocator: std.mem.Allocator) !void {
    const all = try std.process.argsAlloc(allocator);
    var args: []const []const u8 = all[1..];
    if (args.len == 1 and std.mem.eql(u8, args[0], "--version")) {
        try std.fs.File.stdout().writeAll("teerex " ++ version ++ "\n");
        return;
    }
    if (args.len == 0 or (args.len == 1 and std.mem.eql(u8, args[0], "--help"))) {
        try std.fs.File.stdout().writeAll(usage);
        return;
    }
    if (std.mem.eql(u8, args[0], "targets")) return python(allocator, args[1..]);
    if (std.mem.eql(u8, args[0], "--config") or std.mem.eql(u8, args[0], "--host")) {
        var config: ?[]const u8 = null;
        var host: ?[]const u8 = null;
        var i: usize = 0;
        while (i < args.len and std.mem.startsWith(u8, args[i], "--")) : (i += 2) {
            if (i + 1 >= args.len) return error.GlobalOptionNeedsValue;
            if (std.mem.eql(u8, args[i], "--config") and config == null) {
                config = args[i + 1];
            } else if (std.mem.eql(u8, args[i], "--host") and host == null) {
                host = args[i + 1];
            } else return error.UnknownOrRepeatedGlobalOption;
        }
        if (i < args.len and std.mem.eql(u8, args[i], "cartridges")) {
            try std.fs.File.stderr().writeAll("{\"error\": \"cartridges cannot use named-host routing; run teerex cartridges on that machine\", \"next_step\": \"Log in to the selected machine and run teerex cartridges there.\", \"ok\": false, \"schema_version\": 1}\n");
            finish(allocator, 1);
        }
        var forwarded: std.ArrayList([]const u8) = .empty;
        try forwarded.appendSlice(allocator, &.{ "exec", "--config", config orelse return error.ExplicitConfigRequired, "--host", host orelse return error.ExplicitHostRequired, "--" });
        try forwarded.appendSlice(allocator, args[i..]);
        return python(allocator, forwarded.items);
    }
    if (std.mem.eql(u8, args[0], "--rex")) {
        if (args.len < 3 or !std.fs.path.isAbsolute(args[1])) return error.ExplicitRexExecutableRequired;
        var env = try std.process.getEnvMap(allocator);
        try env.put("TEEREX_INTERNAL_REX", args[1]);
        try env.put("TEEREX_REX", args[1]);
        try env.put("TEEREX_CALL_START", try @import("rex_boards").call_log.context(allocator));
        const self = try std.fs.selfExePathAlloc(allocator);
        var forwarded: std.ArrayList([]const u8) = .empty;
        try forwarded.append(allocator, self);
        try forwarded.appendSlice(allocator, args[2..]);
        std.debug.print("teerex: explicit Rex executable {s}; selected by --rex, not authenticated\n", .{args[1]});
        return std.process.execve(allocator, forwarded.items, &env);
    }
    args = try withDefaultSocket(allocator, args);
    const command = args[0];
    const rest = args[1..];
    if (std.mem.eql(u8, command, "mcp")) finish(allocator, try @import("rex_mcp").run(allocator, rest));
    if (std.mem.eql(u8, command, "replay")) finish(allocator, try @import("rex_replay").run(allocator, rest));
    if (std.mem.eql(u8, command, "fleet") and rest.len > 0 and (std.mem.eql(u8, rest[0], "install") or std.mem.eql(u8, rest[0], "rollback"))) {
        const sources = @import("fleet_sources");
        var forwarded: std.ArrayList([]const u8) = .empty;
        try forwarded.appendSlice(allocator, &.{ "python3", "-I", "-c", try @import("rex_boards").call_log.python(allocator, @embedFile("fleet_bridge.py")), sources.controller, sources.worker, sources.installer, sources.resolver });
        try forwarded.appendSlice(allocator, rest);
        return std.process.execv(allocator, forwarded.items);
    }
    if (std.mem.eql(u8, command, "cartridges")) {
        var argv: std.ArrayList([]const u8) = .empty;
        try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", try @import("rex_boards").call_log.python(allocator, @import("cartridge_sources").manager) });
        try argv.appendSlice(allocator, rest);
        const err = std.process.execv(allocator, argv.items);
        var buf: [512]u8 = undefined;
        const line = std.fmt.bufPrint(&buf, "{{\"error\": \"cannot execute python3 ({s}): teerex cartridges requires Python 3.9+\", \"next_step\": \"Install Python 3.9+ on this machine and retry.\", \"ok\": false, \"schema_version\": 1}}\n", .{@errorName(err)}) catch unreachable;
        std.fs.File.stderr().writeAll(line) catch {};
        finish(allocator, 1);
    }
    if (std.mem.eql(u8, command, "records")) finish(allocator, try @import("rex_records").run(allocator, rest));
    if (std.mem.eql(u8, command, "recovery")) finish(allocator, try @import("rex_recovery").run(allocator, rest));
    if (std.mem.eql(u8, command, "snapshot") or std.mem.eql(u8, command, "restore") or std.mem.eql(u8, command, "update")) finish(allocator, try @import("rex_recovery").run(allocator, args));
    if (std.mem.eql(u8, command, "surfaces")) finish(allocator, try @import("rex_surfaces").run(allocator, rest));
    if (std.mem.eql(u8, command, "run")) finish(allocator, try @import("rex_run").run(allocator, rest));
    if (std.mem.eql(u8, command, "run-visible")) finish(allocator, try @import("rex_run").runVisible(allocator, rest));
    if (std.mem.eql(u8, command, "offstage")) finish(allocator, try @import("rex_offstage").run(allocator, rest));
    if (std.mem.eql(u8, command, "doctor")) finish(allocator, try @import("rex_doctor").run(allocator, rest));
    if (std.mem.eql(u8, command, "jobs")) finish(allocator, try @import("rex_jobs").run(allocator, rest));
    if (std.mem.eql(u8, command, "adapters")) finish(allocator, try @import("rex_adapters").run(allocator, rest));
    if (std.mem.eql(u8, command, "clutch")) finish(allocator, try @import("rex_clutch").run(allocator, rest));
    if (std.mem.eql(u8, command, "send")) finish(allocator, try send(allocator, rest));
    if (std.mem.eql(u8, command, "boards")) finish(allocator, try @import("rex_boards").run(allocator, rest));
    if (std.mem.eql(u8, command, "seat") or std.mem.eql(u8, command, "inbox") or std.mem.eql(u8, command, "ask") or std.mem.eql(u8, command, "fleet")) finish(allocator, try @import("rex_boards").run(allocator, args));
    if (std.mem.eql(u8, command, "agents")) finish(allocator, try @import("rex_agents").run(allocator, rest));
    if (std.mem.eql(u8, command, "spawn")) {
        var managed = false;
        for (rest) |arg| {
            if (std.mem.eql(u8, arg, "--")) break;
            if (std.mem.eql(u8, arg, "--profile")) managed = true;
        }
        if (managed) {
            var forwarded: std.ArrayList([]const u8) = .empty;
            try forwarded.append(allocator, "launch");
            for (rest) |arg| try forwarded.append(allocator, if (std.mem.eql(u8, arg, "--profiles")) "--config" else arg);
            finish(allocator, try @import("rex_agents").run(allocator, forwarded.items));
        }
        finish(allocator, try @import("rex_spawn").run(allocator, rest));
    }
    if (std.mem.eql(u8, command, "maneuver-check")) finish(allocator, try @import("rex_maneuvers").run(allocator, rest, @import("rex_observe")));
    if (std.mem.eql(u8, command, "filter")) finish(allocator, try @import("rex_filter").run(allocator, rest, @import("rex_observe")));
    finish(allocator, try @import("rex_observe").runObservations(allocator, args));
}

fn eq(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}

fn hasOption(args: []const []const u8, flag: []const u8) bool {
    for (args) |arg| {
        if (eq(arg, "--")) break;
        if (eq(arg, flag)) return true;
    }
    return false;
}

// Defaults fill required live targets. Configuration-backed and optional socket
// selectors retain their own precedence; incomplete invocations reach leaf usage.
fn takesSocket(args: []const []const u8) bool {
    if (args.len == 0 or hasOption(args, "--help")) return false;
    const command = args[0];
    if (eq(command, "agents")) return false;
    if (eq(command, "jobs") and args.len > 1 and (eq(args[1], "doctor") or eq(args[1], "list"))) return false;
    if (eq(command, "doctor")) return args.len > 1 and (hasOption(args, "--baseline") or hasOption(args, "--timeout-ms"));
    if (eq(command, "adapters")) return args.len > 2 and (eq(args[1], "generate") or (eq(args[1], "call") and hasOption(args, "--adapter") and hasOption(args, "--policy") and hasOption(args, "--tool") and hasOption(args, "--arguments")));
    if (eq(command, "boards")) return args.len > 1 and eq(args[1], "probe");
    if (eq(command, "surfaces")) {
        if (args.len > 2 and eq(args[1], "session") and eq(args[2], "ensure")) return hasOption(args, "--label");
        if (args.len > 1 and eq(args[1], "palette")) return args.len > 2 and eq(args[2], "install") and hasOption(args, "--init") and hasOption(args, "--file") and hasOption(args, "--plan");
        return hasOption(args, "--session");
    }
    if (eq(command, "snapshot") or eq(command, "restore") or eq(command, "update") or eq(command, "recovery")) {
        if (eq(command, "recovery") and (args.len < 2 or eq(args[1], "inspect"))) return false;
        return hasOption(args, "--directory") or hasOption(args, "--timeout-ms");
    }
    if (eq(command, "run")) return hasOption(args, "--cwd") and hasCommand(args);
    if (!hasOption(args, "--session")) return false;
    if (eq(command, "spawn")) return !hasOption(args, "--profile") and hasOption(args, "--name") and hasOption(args, "--report-to-session") and hasOption(args, "--report-to-block");
    if (eq(command, "run-visible") or eq(command, "offstage")) return hasOption(args, "--cwd");
    if (!hasOption(args, "--block")) return false;
    if (eq(command, "observe")) return true;
    if (eq(command, "watch")) return hasOption(args, "--baseline") and (hasOption(args, "--timeout-ms") or hasOption(args, "--no-deadline"));
    if (eq(command, "send")) return hasOption(args, "--from") and hasOption(args, "--message-file");
    if (eq(command, "jobs")) return hasOption(args, "--registry");
    if (eq(command, "maneuver-check")) return hasOption(args, "--observation") and !hasOption(args, "--list");
    return false;
}

const SocketSelection = struct { path: []const u8, source: []const u8 };

fn defaultSocket(allocator: std.mem.Allocator, env: *const std.process.EnvMap) !SocketSelection {
    if (env.get("REX_SERVER")) |server| {
        if (!std.mem.startsWith(u8, server, "unix://")) return error.RexServerMustBeUnix;
        const encoded = server[7..];
        var path: std.ArrayList(u8) = .empty;
        var i: usize = 0;
        while (i < encoded.len) : (i += 1) {
            const byte = if (encoded[i] == '%') blk: {
                if (i + 2 >= encoded.len or !std.ascii.isHex(encoded[i + 1]) or !std.ascii.isHex(encoded[i + 2])) return error.InvalidRexServerEscape;
                const decoded = std.fmt.parseUnsigned(u8, encoded[i + 1 .. i + 3], 16) catch return error.InvalidRexServerEscape;
                i += 2;
                break :blk decoded;
            } else encoded[i];
            if (byte == 0) return error.InvalidRexServerPath;
            try path.append(allocator, byte);
        }
        if (!std.fs.path.isAbsolute(path.items)) return error.InvalidRexServerPath;
        return .{ .path = path.items, .source = "REX_SERVER" };
    }
    const builtin = @import("builtin");
    const path = switch (builtin.os.tag) {
        .linux => try std.fmt.allocPrint(allocator, "/run/user/{d}/rex/server.sock", .{std.os.linux.getuid()}),
        .macos => try std.fs.path.join(allocator, &.{ env.get("HOME") orelse return error.HomeRequired, "Library/Application Support/rex/server.sock" }),
        else => return error.UnsupportedSocketPlatform,
    };
    return .{ .path = path, .source = "platform_default" };
}

// Share target selection with the consent-gated collector without probing or
// reading configuration. Named-host resolution remains unknown at this hook.
fn frictionServer(allocator: std.mem.Allocator, original: []const []const u8) !?[]const u8 {
    var args = original;
    if (args.len > 2 and eq(args[0], "--rex")) args = args[2..];
    if (args.len == 0 or eq(args[0], "--config") or eq(args[0], "--host") or eq(args[0], "targets")) return null;
    for (args, 0..) |arg, i| {
        if (eq(arg, "--")) break;
        if (eq(arg, "--socket") and i + 1 < args.len and std.fs.path.isAbsolute(args[i + 1]))
            return try std.fmt.allocPrint(allocator, "unix://{s}", .{args[i + 1]});
        if (std.mem.startsWith(u8, arg, "--socket=") and std.fs.path.isAbsolute(arg[9..]))
            return try std.fmt.allocPrint(allocator, "unix://{s}", .{arg[9..]});
    }
    if (!takesSocket(args)) return null;
    var env = try std.process.getEnvMap(allocator);
    const selected = try defaultSocket(allocator, &env);
    return try std.fmt.allocPrint(allocator, "unix://{s}", .{selected.path});
}

// A borrowed argv remains untouched for explicit sockets and offline leaves.
fn withDefaultSocket(allocator: std.mem.Allocator, args: []const []const u8) ![]const []const u8 {
    for (args) |arg| {
        if (eq(arg, "--")) break;
        if (eq(arg, "--socket")) return args;
    }
    if (!takesSocket(args)) return args;
    var env = try std.process.getEnvMap(allocator);
    const selected = try defaultSocket(allocator, &env);
    try env.put("TEEREX_SOCKET_SOURCE", selected.source);
    // The invocation owns this arena for its lifetime. Publish one complete,
    // null-terminated environment for both native leaf snapshots and execv.
    const environ = try std.process.createNullDelimitedEnvMap(allocator, &env);
    if (@import("builtin").link_libc) {
        std.c.environ = environ.ptr;
    } else {
        std.os.environ = @as([*][*:0]u8, @ptrCast(environ.ptr))[0..environ.len];
    }
    @import("supervised_child").socket_source = selected.source;
    var resolved: std.ArrayList([]const u8) = .empty;
    var at: usize = 1;
    while (at < args.len and !std.mem.startsWith(u8, args[at], "--")) : (at += 1) {}
    try resolved.appendSlice(allocator, args[0..at]);
    try resolved.appendSlice(allocator, &.{ "--socket", selected.path });
    try resolved.appendSlice(allocator, args[at..]);
    return resolved.items;
}

fn hasCommand(args: []const []const u8) bool {
    for (args, 0..) |arg, i| if (eq(arg, "--")) return i + 1 < args.len;
    return false;
}
