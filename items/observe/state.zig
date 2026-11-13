const std = @import("std");
const supervised = @import("supervised_child");
const Output = struct {
    allocator: std.mem.Allocator,
    bytes: std.ArrayList(u8) = .empty,
    pub fn receive(self: *Output, bytes: []const u8) !void {
        if (bytes.len > 262144 - self.bytes.items.len) return error.AgentStateOutputExceedsLimit;
        try self.bytes.appendSlice(self.allocator, bytes);
    }
};
pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.appendSlice(allocator, &.{ "python3", "-c", @embedFile("state.py"), @import("state_sources").draft, @embedFile("state_collect.lua") });
    try argv.appendSlice(allocator, args);
    var env = try std.process.getEnvMap(allocator);
    for ([_][]const u8{ "REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT" }) |key| env.remove(key);
    if (supervised.socket_source) |source| {
        try env.put("TEEREX_SOCKET_SOURCE", source);
    } else env.remove("TEEREX_SOCKET_SOURCE");
    const signals = supervised.Signals.init();
    defer signals.deinit();
    // Python validates the requested 100..60000ms collection budget. The native
    // bound also covers its startup/error path and owns descendant cleanup.
    var output: Output = .{ .allocator = allocator };
    const result = try supervised.collect(allocator, argv.items, &env, 61000, &output);
    try std.fs.File.stdout().writeAll(output.bytes.items);
    if (result.stderr.len != 0) try std.fs.File.stderr().writeAll(result.stderr);
    if (result.stopped) return if (result.stop_signal != 0) 128 + result.stop_signal else 124;
    return if (result.term == .Exited) @intCast(@min(result.term.Exited, 255)) else 1;
}
