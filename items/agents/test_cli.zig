// Standalone dispatcher; shared integration remains the root CLI owner's responsibility.
const std = @import("std");
pub fn main() void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const args = std.process.argsAlloc(a) catch std.process.exit(1);
    if (args.len < 2) std.process.exit(2);
    const code = dispatch(a, args[1], args[2..]) catch |err| {
        std.debug.print("agents bridge: {s}\n", .{@errorName(err)});
        std.process.exit(1);
    };
    std.process.exit(code);
}
fn dispatch(a: std.mem.Allocator, command: []const u8, args: []const []const u8) !u8 {
    if (std.mem.eql(u8, command, "agents")) return @import("rex_agents").run(a, args);
    if (std.mem.eql(u8, command, "spawn")) return @import("rex_spawn").run(a, args);
    if (std.mem.eql(u8, command, "send")) return @import("rex_send").run(a, args);
    if (std.mem.eql(u8, command, "jobs")) return @import("rex_jobs").run(a, args);
    return 2;
}
