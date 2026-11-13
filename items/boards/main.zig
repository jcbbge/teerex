const std = @import("std");

var route_pid: std.atomic.Value(std.posix.pid_t) = .init(0);
var route_signal: std.atomic.Value(u8) = .init(0);
fn routeSignal(sig: i32) callconv(.c) void {
    route_signal.store(@intCast(sig), .seq_cst);
    const pid = route_pid.load(.seq_cst);
    if (pid > 0) std.posix.kill(pid, @intCast(sig)) catch {};
}

/// Args omit try-route. Absence is the only null result; errors never authorize paste.
/// Inherited stdin is not read by Python before exact registration is checked.
pub fn tryRoute(allocator: std.mem.Allocator, args: []const []const u8) !?u8 {
    var argv: std.ArrayList([]const u8) = .empty;
    defer argv.deinit(allocator);
    try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", @embedFile("boards.py"), "try-route" });
    try argv.appendSlice(allocator, args);
    var child = std.process.Child.init(argv.items, allocator);
    child.stdin_behavior = .Inherit;
    child.stdout_behavior = .Pipe;
    child.stderr_behavior = .Pipe;
    var stdout: std.ArrayList(u8) = .empty;
    defer stdout.deinit(allocator);
    var stderr: std.ArrayList(u8) = .empty;
    defer stderr.deinit(allocator);
    var old_int: std.posix.Sigaction = undefined;
    var old_term: std.posix.Sigaction = undefined;
    const action: std.posix.Sigaction = .{ .handler = .{ .handler = routeSignal }, .mask = std.posix.sigemptyset(), .flags = 0 };
    route_signal.store(0, .seq_cst);
    std.posix.sigaction(std.posix.SIG.INT, &action, &old_int);
    std.posix.sigaction(std.posix.SIG.TERM, &action, &old_term);
    defer {
        route_pid.store(0, .seq_cst);
        std.posix.sigaction(std.posix.SIG.INT, &old_int, null);
        std.posix.sigaction(std.posix.SIG.TERM, &old_term, null);
    }
    try child.spawn();
    route_pid.store(child.id, .seq_cst);
    errdefer {
        route_pid.store(0, .seq_cst);
        _ = child.kill() catch {};
    }
    const early_signal = route_signal.load(.seq_cst);
    if (early_signal != 0) std.posix.kill(child.id, early_signal) catch {};
    try child.collectOutput(allocator, &stdout, &stderr, 8192);
    route_pid.store(0, .seq_cst); // Stop forwarding before reaping can release the PID.
    const term = try child.wait();
    const sig = route_signal.load(.seq_cst);
    if (term == .Exited and term.Exited == 3 and sig == 0) {
        const Receipt = struct { kind: []const u8, outcome: []const u8 };
        const parsed = try std.json.parseFromSlice(Receipt, allocator, stdout.items, .{ .ignore_unknown_fields = true });
        defer parsed.deinit();
        if (!std.mem.eql(u8, parsed.value.kind, "inbox_route") or !std.mem.eql(u8, parsed.value.outcome, "not_registered"))
            return error.InvalidInboxRouteReceipt;
        return null;
    }
    try std.fs.File.stdout().writeAll(stdout.items);
    try std.fs.File.stderr().writeAll(stderr.items);
    return if (sig != 0) 128 + sig else if (term == .Exited) term.Exited else if (term == .Signal) @intCast(@min(255, 128 + term.Signal)) else 1;
}

pub const call_log = @import("calls.zig");

/// Foreground Python3.9+ stdlib implementation. exec preserves the visible pane,
/// PID/signal lifetime and terminal; no detached renderer or hidden service.
/// args: inbox|fleet render args, seat OP, inbox OP, fleet report|forget, ask,
/// try-route, or probe. Root aliases prepend their verb before invoking run.
pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    var argv: std.ArrayList([]const u8) = .empty;
    defer argv.deinit(allocator);
    try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", try call_log.python(allocator, @embedFile("boards.py")) });
    const render = args.len > 0 and (std.mem.eql(u8, args[0], "inbox") or std.mem.eql(u8, args[0], "fleet") or std.mem.eql(u8, args[0], "calls")) and
        (args.len == 1 or std.mem.startsWith(u8, args[1], "--"));
    if (render) try argv.append(allocator, "boards");
    try argv.appendSlice(allocator, args);
    if (args.len > 0 and ((render and (std.mem.eql(u8, args[0], "fleet") or std.mem.eql(u8, args[0], "calls"))) or std.mem.eql(u8, args[0], "probe") or std.mem.eql(u8, args[0], "ask"))) {
        var explicit_self = false;
        for (args) |arg| if (std.mem.eql(u8, arg, "--teerex") or std.mem.startsWith(u8, arg, "--teerex=")) {
            explicit_self = true;
        };
        if (!explicit_self) try argv.appendSlice(allocator, &.{ "--teerex", try std.fs.selfExePathAlloc(allocator) });
    }
    const err = std.process.execv(allocator, argv.items);
    std.debug.print("teerex boards: Python3.9+ foreground runtime unavailable: {s}\n", .{@errorName(err)});
    return 1;
}
