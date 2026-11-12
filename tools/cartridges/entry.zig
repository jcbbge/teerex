const std = @import("std");

pub fn main() void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const allocator = arena.allocator();
    const args = std.process.argsAlloc(allocator) catch |err| fail(err);
    const result = if (@import("options").observation_entry)
        @import("cartridge").runObservations(allocator, args[1..])
    else if (@import("options").uses_observations)
        @import("cartridge").run(allocator, args[1..], @import("observations"))
    else
        @import("cartridge").run(allocator, args[1..]);
    std.process.exit(result catch |err| fail(err));
}

fn fail(err: anyerror) noreturn {
    std.debug.print("teerex cartridge: {s}\n", .{@errorName(err)});
    std.process.exit(1);
}
