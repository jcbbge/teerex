// Embed the complete leaf so installed CLI execution needs no source checkout.
const std = @import("std");
pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    const self = try std.fs.selfExePathAlloc(allocator);
    var argv: std.ArrayList([]const u8) = .empty;
    defer argv.deinit(allocator);
    try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", try @import("pane_guard").python(allocator, @embedFile("replay.py")), self, @embedFile("wire.py"), @embedFile("facts.py"), @embedFile("player.py") });
    try argv.appendSlice(allocator, args);
    return std.process.execv(allocator, argv.items);
}
