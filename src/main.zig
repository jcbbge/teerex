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
    \\  surfaces resolve|session ensure|ensure|open|inspect|rename|move|focus|close  Visible terminals
    \\  board [--replay FILE] | feed              Live themed stream and machine vitals
    \\  records init|new|park|add|attach|set|close|show|resume|navigate|list|lint|export|forget|forget-scratchpad  Private evidence and reasoning
    \\  recovery snapshot|inspect|restore|update|reconcile      Private snapshots and reviewed restoration
    \\  snapshot|restore|update                       Recovery aliases; update is manual handoff
    \\  fleet install|rollback                       Explicit named-host installation plan/apply
    \\  targets resolve|exec                         Named-host lookup and explicit transport
    \\  run-visible                                  Visible noninteractive argv, output and actual exit
    \\  clutch take|release|status|queue|palette|prune  Cooperative human takeover and hand-back
    \\Existing tools: observe, compare, watch, run, doctor, send,
    \\                jobs
    \\Socket verbs default --socket from percent-decoded REX_SERVER (unix://), then platform home/runtime path.
    \\Defaulted observe/watch/doctor receipts report socket_source. Explicit and named-host calls retain their contracts.
    \\Use COMMAND --help for exact flags, effects, evidence and limits.
    \\Who: operators and agents. What: inspectable programs, not a Rex fork/plugin daemon.
    \\When: explicit invocation; every managed agent/board remains visible and controllable.
    \\Where: configured command host; paths belong there, never silently uploaded.
    \\Why: report actual activity/results and unknowns, not infer readiness or completion.
    \\How: explicit config/host or socket/full IDs; no retries, fallback or autostart.
    \\Python3.9+ is required for targets, recovery, records and fleet.
    \\Guarded Rex transports require Python3.9+ for seat and creator authority. SSH trust/key are explicit.
    \\Personal install/restart/close/config actions need their own authorization.
    \\Guides: docs/agents.md and items/{surfaces,recovery,records}/README.md.
    \\
;

var active_command: []const u8 = "";

fn nextAction(code: u8) void {
    // Hints are for a person at a terminal. A hook, supervisor or agent tool
    // inherits a pane it does not own; writing there paints the harness input row.
    if (!std.posix.isatty(std.posix.STDIN_FILENO) or !std.posix.isatty(std.posix.STDERR_FILENO)) return;
    if (code == 2) {
        std.debug.print("next: teerex {s} --help\n", .{active_command});
        return;
    }
    const action = if (eq(active_command, "send"))
        "Confirm the target pane and whether the message arrived with its owner before sending again."
    else if (eq(active_command, "surfaces"))
        "Inspect the selected session and pane with teerex surfaces resolve before changing it again."
    else if (eq(active_command, "board"))
        "Check the selected hosts with teerex doctor --all; run teerex board --help for command options."
    else if (eq(active_command, "doctor"))
        "Check the selected Rex executable and server socket; run teerex doctor --help for selection flags."
    else
        "teerex --help";
    std.debug.print("next: {s}\n", .{action});
}

pub fn main() void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    run(arena.allocator()) catch |err| {
        std.debug.print("teerex: {s}\n", .{@errorName(err)});
        finish(arena.allocator(), 1);
    };
}

fn finish(_: std.mem.Allocator, code: u8) noreturn {
    if (code != 0) nextAction(code);
    std.process.exit(code);
}

fn python(allocator: std.mem.Allocator, args: []const []const u8) !void {
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", @import("pane_guard").identity_source ++ "\n" ++ @embedFile("targets.py") });
    try argv.appendSlice(allocator, args);
    return std.process.execv(allocator, argv.items);
}

fn send(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    var socket: ?[]const u8 = null;
    var sender: ?[]const u8 = null;
    var session: ?[]const u8 = null;
    var block: ?[]const u8 = null;
    var index: usize = 0;
    while (index < args.len) {
        const arg = args[index];
        if (std.mem.eql(u8, arg, "--no-queue")) {
            index += 1;
            continue;
        }
        if (index + 1 >= args.len) break;
        if (std.mem.eql(u8, arg, "--socket")) socket = args[index + 1];
        if (std.mem.eql(u8, arg, "--from")) sender = args[index + 1];
        if (std.mem.eql(u8, arg, "--session")) session = args[index + 1];
        if (std.mem.eql(u8, arg, "--block")) block = args[index + 1];
        index += 2;
    }
    if (socket != null and sender != null) {
        const endpoint = try std.fmt.allocPrint(allocator, "unix://{s}", .{socket.?});
        if (try @import("pane_guard").checkSender(allocator, endpoint, sender.?)) |reason| {
            try std.fs.File.stderr().writeAll(reason);
            const packet = try std.json.Stringify.valueAlloc(allocator, .{
                .schema_version = 1,
                .kind = "send_result",
                .target = .{ .server = endpoint, .session_id = session, .block_id = block },
                .outcome = "refused",
                .failure_reason = std.mem.trim(u8, reason, "\r\n"),
                .backend_invoked = false,
                .paste = .{ .attempted = false, .acknowledged = false },
                .enter = .{ .attempted = false, .acknowledged = false },
                .draft = .{ .cleared = @as(?bool, null) },
                .retry_safe = false,
            }, .{});
            try std.fs.File.stdout().writeAll(packet);
            try std.fs.File.stdout().writeAll("\n");
            return 1;
        }
    }
    return @import("rex_send").run(allocator, args);
}

fn run(allocator: std.mem.Allocator) !void {
    const all = try std.process.argsAlloc(allocator);
    var args: []const []const u8 = all[1..];
    if (args.len > 0) active_command = args[0];
    if (args.len == 1 and std.mem.eql(u8, args[0], "--version")) {
        try std.fs.File.stdout().writeAll("teerex " ++ version ++ "\n");
        return;
    }
    if (args.len == 0 or (args.len == 1 and std.mem.eql(u8, args[0], "--help"))) {
        try std.fs.File.stdout().writeAll(usage);
        return;
    }
    if (eq(args[0], "doctor") and hasOption(args, "--all")) {
        const source = @embedFile("doctor_all.py");
        const resolver = try std.json.Stringify.valueAlloc(allocator, @import("pane_guard").identity_source ++ "\n" ++ @embedFile("targets.py"), .{});
        const worker = try std.json.Stringify.valueAlloc(allocator, source, .{});
        const script = try std.fmt.allocPrint(allocator, "import types,sys\ntargets=types.ModuleType('targets')\nexec({s},targets.__dict__)\nWORKER_SOURCE={s}\n{s}\nsys.exit(main())", .{ resolver, worker, source });
        var forwarded: std.ArrayList([]const u8) = .empty;
        try forwarded.appendSlice(allocator, &.{ "python3", "-I", "-c", script });
        try forwarded.appendSlice(allocator, args[1..]);
        return std.process.execv(allocator, forwarded.items);
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
        const self = try std.fs.selfExePathAlloc(allocator);
        var forwarded: std.ArrayList([]const u8) = .empty;
        try forwarded.append(allocator, self);
        try forwarded.appendSlice(allocator, args[2..]);
        std.debug.print("teerex: explicit Rex executable {s}; selected by --rex, not authenticated\n", .{args[1]});
        return std.process.execve(allocator, forwarded.items, &env);
    }
    args = try withOperator(allocator, args);
    args = try withDefaultSocket(allocator, args);
    const command = args[0];
    const rest = args[1..];
    if (std.mem.eql(u8, command, "board")) {
        if (rest.len > 0 and std.mem.eql(u8, rest[0], "feed")) finish(allocator, try @import("rex_boardfeed").run(allocator, rest[1..]));
        finish(allocator, try @import("rex_board").run(allocator, rest));
    }
    if (std.mem.eql(u8, command, "fleet") and rest.len > 0 and (std.mem.eql(u8, rest[0], "install") or std.mem.eql(u8, rest[0], "rollback"))) {
        const sources = @import("fleet_sources");
        var forwarded: std.ArrayList([]const u8) = .empty;
        try forwarded.appendSlice(allocator, &.{ "python3", "-I", "-c", @embedFile("fleet_bridge.py"), sources.controller, sources.worker, sources.installer, sources.resolver });
        try forwarded.appendSlice(allocator, rest);
        return std.process.execv(allocator, forwarded.items);
    }
    if (std.mem.eql(u8, command, "records")) finish(allocator, try @import("rex_records").run(allocator, rest));
    if (std.mem.eql(u8, command, "recovery")) finish(allocator, try @import("rex_recovery").run(allocator, rest));
    if (std.mem.eql(u8, command, "snapshot") or std.mem.eql(u8, command, "restore") or std.mem.eql(u8, command, "update")) finish(allocator, try @import("rex_recovery").run(allocator, args));
    if (std.mem.eql(u8, command, "surfaces")) finish(allocator, try @import("rex_surfaces").run(allocator, rest));
    if (std.mem.eql(u8, command, "run")) finish(allocator, try @import("rex_run").run(allocator, rest));
    if (std.mem.eql(u8, command, "run-visible")) finish(allocator, try @import("rex_run").runVisible(allocator, rest));
    if (std.mem.eql(u8, command, "doctor")) finish(allocator, try @import("rex_doctor").run(allocator, rest));
    if (std.mem.eql(u8, command, "jobs")) finish(allocator, try @import("rex_jobs").run(allocator, rest));
    if (std.mem.eql(u8, command, "clutch")) finish(allocator, try @import("rex_clutch").run(allocator, rest));
    if (std.mem.eql(u8, command, "send")) finish(allocator, try send(allocator, rest));
    if (eq(command, "observe") or eq(command, "compare") or eq(command, "watch")) finish(allocator, try @import("rex_observe").runObservations(allocator, args));
    std.debug.print("teerex: unknown command {s}; see teerex --help\n", .{command});
    finish(allocator, 2);
}

fn eq(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}

// Explicit human control is local to this interactive invocation. Managed agents
// never inherit the marker, and the registered seat is still an agent pane.
fn withOperator(allocator: std.mem.Allocator, args: []const []const u8) ![]const []const u8 {
    var clean: std.ArrayList([]const u8) = .empty;
    var requested = false;
    var program = false;
    for (args) |arg| {
        if (eq(arg, "--")) program = true;
        if (!program and eq(arg, "--operator")) {
            if (requested) return error.RepeatedOperatorFlag;
            requested = true;
        } else try clean.append(allocator, arg);
    }
    if (!requested) return args;
    var env = try std.process.getEnvMap(allocator);
    if (!eq(env.get("TEEREX_OPERATOR") orelse "", "1") or
        !std.posix.isatty(std.posix.STDIN_FILENO) or !std.posix.isatty(std.posix.STDERR_FILENO) or
        env.get("AGENT_LAUNCH_ID") != null or env.get("LC_AGENT_LAUNCH_ID") != null or
        env.get("AGENT_NAME") != null or env.get("LC_AGENT_NAME") != null)
    {
        try std.fs.File.stderr().writeAll("--operator requires TEEREX_OPERATOR=1 in an interactive human terminal; managed agents cannot use it.\n");
        return error.OperatorTerminalRequired;
    }
    try env.put("TEEREX_OPERATOR_ACTIVE", try std.fmt.allocPrint(allocator, "{d}", .{if (@import("builtin").os.tag == .linux) std.os.linux.getpid() else std.c.getpid()}));
    const environ = try std.process.createNullDelimitedEnvMap(allocator, &env);
    if (@import("builtin").link_libc) std.c.environ = environ.ptr else std.os.environ = @as([*][*:0]u8, @ptrCast(environ.ptr))[0..environ.len];
    return clean.items;
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
    if (eq(command, "jobs") and args.len > 1 and (eq(args[1], "doctor") or eq(args[1], "list"))) return false;
    if (eq(command, "doctor")) return args.len > 1 and (hasOption(args, "--baseline") or hasOption(args, "--timeout-ms"));
    if (eq(command, "surfaces")) {
        if (args.len > 2 and eq(args[1], "session") and eq(args[2], "ensure")) return hasOption(args, "--label");
        return hasOption(args, "--session");
    }
    if (eq(command, "snapshot") or eq(command, "restore") or eq(command, "update") or eq(command, "recovery")) {
        if (eq(command, "recovery") and (args.len < 2 or eq(args[1], "inspect"))) return false;
        return hasOption(args, "--directory") or hasOption(args, "--timeout-ms");
    }
    if (eq(command, "run")) return hasOption(args, "--cwd") and hasCommand(args);
    if (!hasOption(args, "--session")) return false;
    if (eq(command, "run-visible")) return hasOption(args, "--cwd");
    if (!hasOption(args, "--block")) return false;
    if (eq(command, "observe")) return true;
    if (eq(command, "watch")) return hasOption(args, "--baseline") and (hasOption(args, "--timeout-ms") or hasOption(args, "--no-deadline"));
    if (eq(command, "send")) return hasOption(args, "--from") and hasOption(args, "--message-file");
    if (eq(command, "jobs")) return hasOption(args, "--registry");
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
