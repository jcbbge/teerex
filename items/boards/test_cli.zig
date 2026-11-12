// Standalone bridge; shared CLI/build are integrator-owned.
const std = @import("std");
pub fn main() void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const args = std.process.argsAlloc(a) catch std.process.exit(1);
    if (args.len < 2 or !std.mem.eql(u8, args[1], "boards")) std.process.exit(2);
    if (args.len >= 3 and std.mem.eql(u8, args[2], "route-then-copy-stdin")) {
        const routed = @import("rex_boards").tryRoute(a, args[3..]) catch std.process.exit(1);
        if (routed) |code| std.process.exit(code);
        const bytes = std.fs.File.stdin().readToEndAlloc(a, 65536) catch std.process.exit(1);
        std.fs.File.stdout().writeAll(bytes) catch std.process.exit(1);
        return;
    }
    const code = @import("rex_boards").run(a, args[2..]) catch std.process.exit(1);
    std.process.exit(code);
}
