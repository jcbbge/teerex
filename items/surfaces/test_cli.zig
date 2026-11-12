// Standalone test entry until the integrator wires the shared CLI.
const std = @import("std");
pub fn main() void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const args = std.process.argsAlloc(a) catch std.process.exit(1);
    if (args.len < 2 or !std.mem.eql(u8, args[1], "surfaces")) std.process.exit(2);
    const code = @import("rex_surfaces").run(a, args[2..]) catch |err| {
        std.debug.print("surfaces: {s}\n", .{@errorName(err)});
        std.process.exit(1);
    };
    std.process.exit(code);
}
