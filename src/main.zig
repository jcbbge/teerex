const std = @import("std");
const version = @import("build_version").version;

const usage =
    \\teerex: guarded input for Rex panes
    \\Usage: teerex [--rex ABS] COMMAND ...
    \\       teerex --version
    \\
    \\  send                              Guarded paste and Enter with a JSON receipt
    \\  clutch take|release|status|queue|drain
    \\                                      Cooperative holds and queued delivery
    \\
    \\Socket: --socket ABS, then unix:// REX_SERVER, then the local runtime path.
    \\Use teerex COMMAND --help for flags and receipts.
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
    args = try withDefaultSocket(allocator, args);
    const command = args[0];
    const rest = args[1..];
    if (eq(command, "clutch")) finish(allocator, try @import("rex_clutch").run(allocator, rest));
    if (eq(command, "send")) finish(allocator, try @import("rex_send").run(allocator, rest));
    std.debug.print("teerex: unknown command {s}; see teerex --help\n", .{command});
    finish(allocator, 2);
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

fn takesSocket(args: []const []const u8) bool {
    if (args.len == 0 or hasOption(args, "--help") or !hasOption(args, "--session")) return false;
    if (eq(args[0], "clutch")) return hasOption(args, "--pane");
    return eq(args[0], "send") and hasOption(args, "--block") and
        hasOption(args, "--from") and hasOption(args, "--message-file");
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
    const env = try std.process.getEnvMap(allocator);
    const selected = try defaultSocket(allocator, &env);
    @import("supervised_child").socket_source = selected.source;
    var resolved: std.ArrayList([]const u8) = .empty;
    var at: usize = 1;
    while (at < args.len and !std.mem.startsWith(u8, args[at], "--")) : (at += 1) {}
    try resolved.appendSlice(allocator, args[0..at]);
    try resolved.appendSlice(allocator, &.{ "--socket", selected.path });
    try resolved.appendSlice(allocator, args[at..]);
    return resolved.items;
}
