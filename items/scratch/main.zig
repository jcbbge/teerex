const std = @import("std");
pub const source = @embedFile("scratch.py");

pub fn statusBootstrap(allocator: std.mem.Allocator) ![]const u8 {
    const quoted = try std.json.Stringify.valueAlloc(allocator, @import("rex_boards").seat_status_source, .{});
    return std.fmt.allocPrint(allocator, "import types,sys\n_stop_status=types.ModuleType('teerex_seat_status')\n_stop_status.__source__={s}\nexec(_stop_status.__source__,_stop_status.__dict__)\nsys.modules['teerex_seat_status']=_stop_status\n", .{quoted});
}

pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    if (args.len > 0 and std.mem.eql(u8, args[0], "palette")) {
        var palette: std.ArrayList([]const u8) = .empty;
        try palette.appendSlice(allocator, &.{ "python3", "-I", "-c", @embedFile("palette.py"), try std.fs.selfExePathAlloc(allocator) });
        try palette.appendSlice(allocator, args[1..]);
        return std.process.execv(allocator, palette.items);
    }
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", try std.fmt.allocPrint(allocator, "{s}{s}", .{ try statusBootstrap(allocator), source }) });
    try argv.appendSlice(allocator, args);
    return std.process.execv(allocator, argv.items);
}
