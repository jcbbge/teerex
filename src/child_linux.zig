const std = @import("std");
const linux = std.os.linux;
const Self = @This();

pid: std.posix.pid_t,
exited: bool = false,

pub fn init(pid: std.posix.pid_t, _: *std.process.Child, _: *bool) !Self {
    return .{ .pid = pid };
}

pub fn deinit(_: Self) void {}

pub fn wait(self: *Self, child: *std.process.Child, events: anytype) !usize {
    var count: usize = 0;
    if (!self.exited) {
        // Keep the zombie leader until collect's final group signal. waitpid
        // with WNOHANG would reap it and allow PID/process-group ID reuse.
        var info: linux.siginfo_t = std.mem.zeroes(linux.siginfo_t);
        while (true) {
            const rc = linux.waitid(.PID, self.pid, &info, linux.W.EXITED | linux.W.NOHANG | linux.W.NOWAIT);
            switch (linux.E.init(rc)) {
                .SUCCESS => break,
                .INTR => continue,
                else => |err| return std.posix.unexpectedErrno(err),
            }
        }
        if (info.signo != 0) {
            self.exited = true;
            events[count] = .{ .stream = 0, .available = 0, .eof = false };
            count += 1;
        }
    }
    var pipes = [_]std.posix.pollfd{
        .{ .fd = if (child.stdout) |f| f.handle else -1, .events = std.posix.POLL.IN, .revents = 0 },
        .{ .fd = if (child.stderr) |f| f.handle else -1, .events = std.posix.POLL.IN, .revents = 0 },
    };
    _ = try std.posix.poll(&pipes, if (count > 0) 0 else 50);
    for (pipes, 1..) |pipe, stream| {
        if (pipe.revents & std.posix.POLL.NVAL != 0) return error.RunEventFailed;
        if (pipe.revents & (std.posix.POLL.IN | std.posix.POLL.HUP | std.posix.POLL.ERR) != 0) {
            // HUP can accompany unread bytes. Drain one chunk per ready stream
            // per tick; only read()==0 establishes EOF, not HUP itself.
            events[count] = .{ .stream = @intCast(stream), .available = 8192, .eof = false };
            count += 1;
        }
    }
    return count;
}
