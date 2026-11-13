const std = @import("std");

pub fn run(allocator: std.mem.Allocator, args: []const []const u8, resolver_source: []const u8) !u8 {
    const resolver = try std.json.Stringify.valueAlloc(allocator, resolver_source, .{});
    const script = try std.fmt.allocPrint(allocator, "import types,sys\ntargets=types.ModuleType('targets')\nexec({s},targets.__dict__)\n{s}", .{ resolver, @embedFile("decide.py") });
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", try @import("rex_boards").call_log.python(allocator, script), try std.fs.selfExePathAlloc(allocator) });
    try argv.appendSlice(allocator, args);
    return std.process.execv(allocator, argv.items);
}
