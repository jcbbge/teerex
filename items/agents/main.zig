// Python is an explicit runtime prerequisite; all long-lived agent code runs in the created Rex pane.
const std = @import("std");
pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    const self = try std.fs.selfExePathAlloc(allocator);
    var argv: std.ArrayList([]const u8) = .empty;
    defer argv.deinit(allocator);
    try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", try @import("rex_boards").call_log.python(allocator, @import("scoped_channel").source ++ "\n" ++ @embedFile("agents.py")), self });
    try argv.appendSlice(allocator, args);
    // Replace this short-lived CLI rather than orphaning a Python child on cancellation.
    return std.process.execv(allocator, argv.items);
}
