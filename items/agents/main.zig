// Python is an explicit runtime prerequisite; all long-lived agent code runs in the created Rex pane.
const std = @import("std");
pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    const self = try @import("rex_boards").stableSelfPath(allocator);
    var argv: std.ArrayList([]const u8) = .empty;
    defer argv.deinit(allocator);
    // fence-probe runs inside a fence: keep it free of the call-log wrapper (its store is unreachable there).
    const source = if (args.len > 0 and std.mem.eql(u8, args[0], "fence-probe")) @embedFile("fence_probe.py") else try @import("rex_boards").call_log.python(allocator, @import("scoped_channel").source ++ "\n" ++ @embedFile("agents.py"));
    try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", source, self });
    try argv.appendSlice(allocator, args);
    // Replace this short-lived CLI rather than orphaning a Python child on cancellation.
    return std.process.execv(allocator, argv.items);
}
