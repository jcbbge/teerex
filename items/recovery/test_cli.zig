// Public CLI composition driver until the integrator wires the shared root.
const std = @import("std");
pub fn main() void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const args = std.process.argsAlloc(a) catch std.process.exit(1);
    if (args.len < 2) std.process.exit(2);
    const code = if (std.mem.eql(u8, args[1], "recovery"))
        @import("rex_recovery").run(a, args[2..])
    else if (std.mem.eql(u8, args[1], "surfaces"))
        @import("rex_surfaces").run(a, args[2..])
    else if (std.mem.eql(u8, args[1], "boards"))
        @import("rex_boards").run(a, args[2..])
    else
        return std.process.exit(2);
    std.process.exit(code catch |err| {
        std.debug.print("recovery test CLI: {s}\n", .{@errorName(err)});
        return std.process.exit(1);
    });
}
