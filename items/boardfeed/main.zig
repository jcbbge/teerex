const std = @import("std");
pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", @embedFile("feed.py"), try std.fs.selfExePathAlloc(allocator) });
    try argv.appendSlice(allocator, args);
    return std.process.execv(allocator, argv.items);
}
