// Exec the embedded stdio service: preserve its streams, PID and cancellation.
const std = @import("std");
pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    const self = try std.fs.selfExePathAlloc(allocator);
    var argv: std.ArrayList([]const u8) = .empty;
    defer argv.deinit(allocator);
    try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", @embedFile("server.py"), self });
    try argv.appendSlice(allocator, args);
    return std.process.execv(allocator, argv.items);
}
