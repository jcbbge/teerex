// Python is an explicit runtime prerequisite; all long-lived agent code runs in the created Rex pane.
const std = @import("std");
pub const input_events_source = @embedFile("input_events.py");
pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    const self = try @import("rex_boards").stableSelfPath(allocator);
    var argv: std.ArrayList([]const u8) = .empty;
    defer argv.deinit(allocator);
    // fence-probe runs inside a fence: keep it free of the call-log wrapper (its store is unreachable there).
    if (args.len > 0 and std.mem.eql(u8, args[0], "fence-probe")) {
        try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", @embedFile("fence_probe.py"), self });
    } else {
        // Separate libraries stay below Linux's per-argument limit.
        const bootstrap = try @import("rex_boards").call_log.python(allocator, "import sys\nsource=''.join(sys.argv.pop(1) for _ in range(4))\nexec(compile(source, '<agents>', 'exec'))");
        try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", bootstrap, "SCRATCH_LIBRARY = True\n" ++ @import("rex_scratch").source ++ "\n", @import("scoped_channel").source ++ "\n", input_events_source ++ "\n", @embedFile("agents.py"), self });
    }
    try argv.appendSlice(allocator, args);
    // Replace this short-lived CLI rather than orphaning a Python child on cancellation.
    return std.process.execv(allocator, argv.items);
}
