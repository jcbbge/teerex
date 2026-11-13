const std = @import("std");
pub const source = @embedFile("scratch.py");

pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    if (args.len > 0 and std.mem.eql(u8, args[0], "palette")) {
        var palette: std.ArrayList([]const u8) = .empty;
        try palette.appendSlice(allocator, &.{ "python3", "-I", "-c", @embedFile("palette.py"), try std.fs.selfExePathAlloc(allocator) });
        try palette.appendSlice(allocator, args[1..]);
        return std.process.execv(allocator, palette.items);
    }
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", source });
    try argv.appendSlice(allocator, args);
    return std.process.execv(allocator, argv.items);
}
