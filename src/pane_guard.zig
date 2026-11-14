const std = @import("std");
pub const source = @embedFile("pane_guard.lua");

// A private script file avoids OS per-argument and total argv limits. The caller
// owns its lifetime through the complete Rex invocation, including cleanup.
pub const ScriptFile = struct {
    path: []const u8,
    allocator: std.mem.Allocator,

    pub fn init(allocator: std.mem.Allocator, script: []const u8) !ScriptFile {
        var random: [16]u8 = undefined;
        std.crypto.random.bytes(&random);
        const path = try std.fmt.allocPrint(allocator, "/tmp/teerex-guard-{s}.lua", .{std.fmt.bytesToHex(random, .lower)});
        errdefer allocator.free(path);
        var file = try std.fs.createFileAbsolute(path, .{ .exclusive = true, .mode = 0o600 });
        defer file.close();
        errdefer std.fs.deleteFileAbsolute(path) catch {};
        try file.writeAll(script);
        return .{ .path = path, .allocator = allocator };
    }

    pub fn deinit(self: ScriptFile) void {
        std.fs.deleteFileAbsolute(self.path) catch |err| {
            std.debug.print("removing private pane guard script: {s}\n", .{@errorName(err)});
        };
        self.allocator.free(self.path);
    }
};
