// Python is an explicit runtime prerequisite; all long-lived agent code runs in the created Rex pane.
const std = @import("std");
const source_bootstrap = "import sys\nsource=''.join(sys.argv.pop(1) for _ in range(int(sys.argv.pop(1))))\nexec(compile(source, '<agents>', 'exec'))";

fn appendSource(allocator: std.mem.Allocator, argv: *std.ArrayList([]const u8), source: []const u8) !void {
    // Linux MAX_ARG_STRLEN includes the terminating NUL.
    const chunk_size = 128 * 1024 - 1;
    try argv.append(allocator, try std.fmt.allocPrint(allocator, "{d}", .{std.math.divCeil(usize, source.len, chunk_size) catch unreachable}));
    var offset: usize = 0;
    while (offset < source.len) {
        const end = @min(source.len, offset + chunk_size);
        try argv.append(allocator, source[offset..end]);
        offset = end;
    }
}

pub const input_events_source = @import("input_events.zig").input_events_source;
pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    const self = try @import("rex_boards").stableSelfPath(allocator);
    var argv: std.ArrayList([]const u8) = .empty;
    defer argv.deinit(allocator);
    // fence-probe runs inside a fence: keep it free of the call-log wrapper (its store is unreachable there).
    if (args.len > 0 and std.mem.eql(u8, args[0], "fence-probe")) {
        try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", @embedFile("fence_probe.py"), self });
    } else {
        const bootstrap = try @import("rex_boards").call_log.python(allocator, source_bootstrap);
        const source = "SCRATCH_LIBRARY = True\n" ++ @import("rex_scratch").source ++ "\n" ++ @import("scoped_channel").source ++ "\n" ++ input_events_source ++ "\n" ++ @embedFile("agents.py");
        try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", bootstrap });
        try appendSource(allocator, &argv, source);
        try argv.append(allocator, self);
    }
    try argv.appendSlice(allocator, args);
    // Replace this short-lived CLI rather than orphaning a Python child on cancellation.
    return std.process.execv(allocator, argv.items);
}

test "embedded Python larger than Linux per-argument limit executes" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const allocator = arena.allocator();
    const source = "# padding\n" ** 30000 ++ "print('large source executed')\n";
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", source_bootstrap });
    try appendSource(allocator, &argv, source);
    try std.testing.expect(source.len > 128 * 1024);
    for (argv.items[5..]) |chunk| try std.testing.expect(chunk.len < 128 * 1024);
    const result = try std.process.Child.run(.{ .allocator = allocator, .argv = argv.items });
    try std.testing.expectEqual(std.process.Child.Term{ .Exited = 0 }, result.term);
    try std.testing.expectEqualStrings("large source executed\n", result.stdout);
}
