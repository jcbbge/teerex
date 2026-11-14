const std = @import("std");
const EventSource = if (@import("builtin").os.tag == .linux) @import("child_linux.zig") else DarwinEvents;

const Event = struct { stream: u8, available: usize, eof: bool };

const DarwinEvents = struct {
    fd: std.posix.fd_t,

    fn init(pid: std.posix.pid_t, child: *std.process.Child, exited: *bool) !DarwinEvents {
        const fd = try std.posix.kqueue();
        errdefer std.posix.close(fd);
        const pipes = [_]std.posix.Kevent{
            .{ .ident = @intCast(child.stdout.?.handle), .filter = std.c.EVFILT.READ, .flags = std.c.EV.ADD, .fflags = 0, .data = 0, .udata = 1 },
            .{ .ident = @intCast(child.stderr.?.handle), .filter = std.c.EVFILT.READ, .flags = std.c.EV.ADD, .fflags = 0, .data = 0, .udata = 2 },
        };
        _ = try std.posix.kevent(fd, &pipes, &.{}, null);
        const process = [_]std.posix.Kevent{.{ .ident = @intCast(pid), .filter = std.c.EVFILT.PROC, .flags = std.c.EV.ADD | std.c.EV.ONESHOT, .fflags = std.c.NOTE.EXIT, .data = 0, .udata = 0 }};
        _ = std.posix.kevent(fd, &process, &.{}, null) catch |err| blk: {
            if (err != error.ProcessNotFound) return err;
            exited.* = true;
            break :blk 0;
        };
        return .{ .fd = fd };
    }

    fn deinit(self: DarwinEvents) void {
        std.posix.close(self.fd);
    }

    fn wait(self: DarwinEvents, _: *std.process.Child, events: *[3]Event) !usize {
        var raw: [3]std.posix.Kevent = undefined;
        const tick: std.posix.timespec = .{ .sec = 0, .nsec = 50 * std.time.ns_per_ms };
        const count = try std.posix.kevent(self.fd, &.{}, &raw, &tick);
        for (raw[0..count], events[0..count]) |event, *out| {
            if (event.flags & std.c.EV.ERROR != 0) return error.RunEventFailed;
            out.* = .{ .stream = @intCast(event.udata), .available = @intCast(@max(0, event.data)), .eof = event.flags & std.c.EV.EOF != 0 };
        }
        return count;
    }
};

var cancellation: std.atomic.Value(u8) = .init(0);

fn signalHandler(sig: i32) callconv(.c) void {
    _ = cancellation.cmpxchgStrong(0, @intCast(sig), .seq_cst, .seq_cst);
}

// One scope surrounds the entire command, including gaps between child invocations.
pub const Signals = struct {
    old_int: std.posix.Sigaction,
    old_term: std.posix.Sigaction,

    pub fn init() Signals {
        var scope: Signals = undefined;
        const action: std.posix.Sigaction = .{ .handler = .{ .handler = signalHandler }, .mask = std.posix.sigemptyset(), .flags = 0 };
        cancellation.store(0, .seq_cst);
        std.posix.sigaction(std.posix.SIG.INT, &action, &scope.old_int);
        std.posix.sigaction(std.posix.SIG.TERM, &action, &scope.old_term);
        return scope;
    }

    pub fn deinit(self: Signals) void {
        std.posix.sigaction(std.posix.SIG.TERM, &self.old_term, null);
        std.posix.sigaction(std.posix.SIG.INT, &self.old_int, null);
    }
};

pub fn requestedSignal() u8 {
    return cancellation.load(.seq_cst);
}

// A caller can retain the stop request while giving its cleanup phase a bounded
// attempt. Atomic consumption cannot erase a newer signal between read/reset.
pub fn takeRequestedSignal() u8 {
    return cancellation.swap(0, .seq_cst);
}

pub const GroupSignal = enum { sent, not_found, no_signalable_member_or_permission_denied };

fn signalGroup(pid: std.posix.pid_t, sig: u8) !GroupSignal {
    std.posix.kill(-pid, sig) catch |err| {
        return switch (err) {
            error.ProcessNotFound => .not_found,
            // Darwin returns EPERM even for our own group containing only a zombie.
            // It cannot establish that all descendants are gone; retain the ambiguity.
            error.PermissionDenied => .no_signalable_member_or_permission_denied,
            else => err,
        };
    };
    return .sent;
}

// The leader must remain UNREAPED until the final group signal: its PID reserves
// the group ID, preventing this cleanup from signalling an unrelated reused ID.
fn killOwned(pid: std.posix.pid_t) !GroupSignal {
    const result = try signalGroup(pid, std.posix.SIG.KILL);
    // Also covers cancellation before the child has established its process group.
    std.posix.kill(pid, std.posix.SIG.KILL) catch |err| {
        if (err != error.ProcessNotFound) return err;
    };
    return result;
}

pub const Result = struct {
    term: std.process.Child.Term,
    started_at_unix_ms: i64,
    elapsed_ms: u64,
    stopped: bool,
    stop_signal: u8,
    deadline_exceeded: bool,
    stderr: []const u8,
    stderr_seen: ?u64,
    group_term: ?GroupSignal,
    group_kill: ?GroupSignal,
};

// macOS and Linux. Caller owns Signals and the receiver's stdout retention policy.
// An optional isComplete() requests owned-group cleanup, not command success.
// EOF stdin by default; a receiver may explicitly opt into inherited stdin.
// Diagnostics remain bounded and each invocation owns its process group.
pub fn collect(allocator: std.mem.Allocator, argv: []const []const u8, env: *const std.process.EnvMap, deadline_ms: ?u64, receiver: anytype) !Result {
    var timer = try std.time.Timer.start();
    const started_at = std.time.milliTimestamp();
    const selected_argv = if (argv.len != 0 and std.mem.eql(u8, argv[0], "rex") and env.get("TEEREX_INTERNAL_REX") != null) blk: {
        const executable = env.get("TEEREX_INTERNAL_REX").?;
        if (!std.fs.path.isAbsolute(executable)) return error.RexExecutableMustBeAbsolute;
        const selected = try allocator.dupe([]const u8, argv);
        selected[0] = executable;
        break :blk selected;
    } else argv;
    defer if (selected_argv.ptr != argv.ptr) allocator.free(selected_argv);
    // All native Lua transports share the guard, including cleanup paths.
    const guarded_argv = try allocator.dupe([]const u8, selected_argv);
    defer allocator.free(guarded_argv);
    var guard_source: ?[]const u8 = null;
    defer if (guard_source) |s| allocator.free(s);
    var endpoint: ?[]const u8 = null;
    var lua = false;
    for (selected_argv, 0..) |arg, i| {
        if (std.mem.eql(u8, arg, "--server") and i + 1 < selected_argv.len) endpoint = selected_argv[i + 1];
        if (std.mem.eql(u8, arg, "do")) lua = true;
    }
    if (endpoint != null and lua) {
        for (selected_argv, 0..) |arg, i| {
            if (std.mem.eql(u8, arg, "-e") and i + 1 < selected_argv.len) {
                const script = selected_argv[i + 1];
                const prefix = try @import("pane_guard").prelude(allocator, endpoint.?, std.mem.startsWith(u8, script, "-- teerex-guarded-message\n"));
                defer allocator.free(prefix);
                guard_source = try std.mem.concat(allocator, u8, &.{ prefix, script });
                guarded_argv[i + 1] = guard_source.?;
            }
        }
    }
    var child = std.process.Child.init(guarded_argv, allocator);
    child.stdin_behavior = if (@hasDecl(@TypeOf(receiver.*), "inherit_stdin") and @TypeOf(receiver.*).inherit_stdin) .Inherit else .Ignore;
    child.stdout_behavior = .Pipe;
    child.stderr_behavior = .Pipe;
    child.env_map = env;
    child.pgid = 0;
    try child.spawn();
    const pid = child.id;
    var reaped = false;
    defer if (!reaped) {
        _ = killOwned(pid) catch null;
        _ = child.wait() catch {
            // Zig's spawn-error path has not reaped the forked child or closed streams.
            _ = std.posix.waitpid(pid, 0);
            if (child.stdout) |file| file.close();
            if (child.stderr) |file| file.close();
        };
    };
    var exited = false;
    var source = try EventSource.init(pid, &child, &exited);
    defer source.deinit();
    var stderr: std.ArrayList(u8) = .empty;
    var stderr_seen: u64 = 0;
    var stopped_at: ?u64 = null;
    var stop_signal: u8 = 0;
    var deadline_exceeded = false;
    var group_term: ?GroupSignal = null;
    var group_kill: ?GroupSignal = null;
    while (true) {
        const elapsed_ms = timer.read() / std.time.ns_per_ms;
        const requested_signal = requestedSignal();
        const complete = if (@hasDecl(@TypeOf(receiver.*), "isComplete")) receiver.isComplete() else false;
        if (stopped_at == null and (requested_signal != 0 or (deadline_ms != null and elapsed_ms >= deadline_ms.?) or complete)) {
            stopped_at = elapsed_ms;
            stop_signal = requested_signal;
            deadline_exceeded = requested_signal == 0 and !complete;
            group_term = try signalGroup(pid, std.posix.SIG.TERM);
        }
        if (group_kill == null and (exited or (stopped_at != null and elapsed_ms - stopped_at.? >= 250))) {
            group_kill = try killOwned(pid);
        }
        if (exited and child.stdout == null and child.stderr == null) break;
        // An escaped descendant could retain our pipes. Do not wait forever for EOF.
        if (stopped_at != null and elapsed_ms - stopped_at.? >= 500) break;
        var events: [3]Event = undefined;
        const count = try source.wait(&child, &events);
        for (events[0..count]) |event| {
            if (event.stream == 0) {
                exited = true;
                continue;
            }
            const file = if (event.stream == 1) &child.stdout else &child.stderr;
            if (event.available > 0) {
                var buffer: [8192]u8 = undefined;
                const n = try std.posix.read(file.*.?.handle, buffer[0..@min(event.available, buffer.len)]);
                if (n == 0) {
                    file.*.?.close();
                    file.* = null;
                } else if (event.stream == 1) {
                    try receiver.receive(buffer[0..n]);
                } else {
                    stderr_seen += n;
                    try stderr.appendSlice(allocator, buffer[0..@min(n, 4096 - stderr.items.len)]);
                }
            } else if (event.eof) {
                file.*.?.close();
                file.* = null;
            }
        }
    }
    if (group_kill == null) group_kill = try killOwned(pid);
    const stderr_eof = child.stderr == null;
    const term = try child.wait();
    reaped = true;
    return .{
        .term = term,
        .started_at_unix_ms = started_at,
        .elapsed_ms = timer.read() / std.time.ns_per_ms,
        .stopped = stop_signal != 0 or deadline_exceeded,
        .stop_signal = stop_signal,
        .deadline_exceeded = deadline_exceeded,
        .stderr = stderr.items,
        .stderr_seen = if (stderr_eof) stderr_seen else null,
        .group_term = group_term,
        .group_kill = group_kill,
    };
}

// Only the combined root sets this after resolving an omitted socket. Explicit
// and standalone invocations retain their original serializer and exact bytes.
pub var socket_source: ?[]const u8 = null;

pub fn receiptJson(allocator: std.mem.Allocator, value: anytype, options: std.json.Stringify.Options) ![]u8 {
    const source = socket_source orelse return std.json.Stringify.valueAlloc(allocator, value, options);
    var output: std.Io.Writer.Allocating = .init(allocator);
    errdefer output.deinit();
    var stream: std.json.Stringify = .{ .writer = &output.writer, .options = options };
    try stream.beginObject();
    try stream.objectField("socket_source");
    try stream.write(source);
    inline for (@typeInfo(@TypeOf(value)).@"struct".fields) |field| {
        try stream.objectField(field.name);
        try stream.write(@field(value, field.name));
    }
    try stream.endObject();
    return output.toOwnedSlice();
}
