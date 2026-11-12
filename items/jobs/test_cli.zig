// Standalone public-CLI test bridge while shared dispatch/build wiring is integrated.
const std = @import("std");
pub fn main() void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const args = std.process.argsAlloc(a) catch std.process.exit(1);
    if (args.len < 2 or !std.mem.eql(u8, args[1], "jobs")) std.process.exit(2);
    const code = @import("rex_jobs").run(a, args[2..]) catch |err| {
        std.debug.print("jobs test bridge: {s}\n", .{@errorName(err)});
        std.process.exit(1);
    };
    std.process.exit(code);
}
