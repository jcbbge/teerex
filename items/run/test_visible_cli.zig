// Standalone acceptance entry; combined root/help wiring belongs to integration.
const std = @import("std");
pub fn main() !void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const args = (try std.process.argsAlloc(a))[1..];
    if (args.len == 0) return error.CommandRequired;
    if (std.mem.eql(u8, args[0], "--rex")) {
        if (args.len < 3) return error.RexAndCommandRequired;
        var env = try std.process.getEnvMap(a);
        try env.put("TEEREX_INTERNAL_REX", args[1]);
        try env.put("TEEREX_REX", args[1]);
        const self = try std.fs.selfExePathAlloc(a);
        var forwarded: std.ArrayList([]const u8) = .empty;
        try forwarded.append(a, self);
        try forwarded.appendSlice(a, args[2..]);
        return std.process.execve(a, forwarded.items, &env);
    }
    const code = if (std.mem.eql(u8, args[0], "run-visible"))
        try @import("rex_run").runVisible(a, args[1..])
    else if (std.mem.eql(u8, args[0], "run"))
        try @import("rex_run").run(a, args[1..])
    else if (std.mem.eql(u8, args[0], "surfaces"))
        try @import("rex_surfaces").run(a, args[1..])
    else
        return error.UnknownCommand;
    std.process.exit(code);
}
