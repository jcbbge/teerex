const std = @import("std");
const supervised = @import("supervised_child");

const Output = struct {
    pub const inherit_stdin = true;
    allocator: std.mem.Allocator,
    bytes: std.ArrayList(u8) = .empty,

    pub fn receive(self: *Output, bytes: []const u8) !void {
        if (bytes.len > 67108864 - self.bytes.items.len) return error.RecordsOutputExceedsBound;
        try self.bytes.appendSlice(self.allocator, bytes);
    }
};

// Python 3.9+ is an explicit runtime prerequisite, not a hidden worker.
// Foreground only: bounded reads/control calls, no relaunch or background worker.
pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", try @import("rex_boards").call_log.python(allocator, @embedFile("records.py")) });
    try argv.appendSlice(allocator, args);
    var env = try std.process.getEnvMap(allocator);
    try env.put("TEEREX_RECORDS_EXECUTABLE", try std.fs.selfExePathAlloc(allocator));
    const signals = supervised.Signals.init();
    defer signals.deinit();
    var output = Output{ .allocator = allocator };
    const result = try supervised.collect(allocator, argv.items, &env, 900000, &output);
    try std.fs.File.stdout().writeAll(output.bytes.items);
    if (result.stderr.len != 0) try std.fs.File.stderr().writeAll(result.stderr);
    const signal = supervised.requestedSignal();
    if (signal != 0) return 128 + signal;
    if (result.deadline_exceeded) return 124;
    return switch (result.term) {
        .Exited => |code| code,
        else => 1,
    };
}
