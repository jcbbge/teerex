const std = @import("std");
pub const identity_source = @embedFile("caller_identity.py");
pub const source = identity_source ++ "\n" ++ @embedFile("pane_guard.py");

pub fn python(allocator: std.mem.Allocator, script: []const u8) ![]const u8 {
    const encoded = try std.json.Stringify.valueAlloc(allocator, source, .{});
    return std.fmt.allocPrint(allocator, "import types,sys\n_pane_guard=types.ModuleType('teerex_pane_guard')\nexec({s},_pane_guard.__dict__)\n_pane_guard.SOURCE={s}\nsys.modules['teerex_pane_guard']=_pane_guard\n{s}", .{ encoded, encoded, script });
}

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

pub fn checkSender(allocator: std.mem.Allocator, endpoint: []const u8, sender: []const u8) !?[]const u8 {
    const result = try std.process.Child.run(.{ .allocator = allocator, .argv = &.{ "python3", "-I", "-c", source, endpoint, "sender", sender }, .max_output_bytes = std.math.maxInt(usize) });
    if (result.term != .Exited or result.term.Exited != 0) {
        return if (result.stderr.len != 0) result.stderr else "sender_check_failed";
    }
    return null;
}

pub fn prelude(allocator: std.mem.Allocator, endpoint: []const u8, message: bool, session: ?[]const u8) ![]const u8 {
    const result = try std.process.Child.run(.{ .allocator = allocator, .argv = &.{ "python3", "-I", "-c", source, endpoint, if (message) "message" else "control", session orelse "" }, .max_output_bytes = std.math.maxInt(usize) });
    if (result.term != .Exited or result.term.Exited != 0) {
        try std.fs.File.stderr().writeAll(result.stderr);
        return error.PaneGuardUnavailable;
    }
    return result.stdout;
}

pub fn checkTake(allocator: std.mem.Allocator, socket: []const u8, session: []const u8, pane: []const u8) !void {
    const endpoint = try std.fmt.allocPrint(allocator, "unix://{s}", .{socket});
    const prefix = try prelude(allocator, endpoint, false, session);
    const script = try std.mem.concat(allocator, u8, &.{ prefix, "\nreturn rex.call('teerex.guard.take',rex.args)" });
    const args = try std.json.Stringify.valueAlloc(allocator, .{ .session_id = session, .block_id = pane }, .{});
    var env = try std.process.getEnvMap(allocator);
    for ([_][]const u8{ "REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT" }) |key| env.remove(key);
    const script_file = try ScriptFile.init(allocator, script);
    defer script_file.deinit();
    const result = try std.process.Child.run(.{ .allocator = allocator, .argv = &.{ env.get("TEEREX_INTERNAL_REX") orelse "rex", "--autostart=false", "--server", endpoint, "--timeout", "3s", "do", script_file.path, "--args", args, "--json" }, .env_map = &env });
    if (result.term != .Exited or result.term.Exited != 0) {
        try std.fs.File.stderr().writeAll(result.stderr);
        return error.PaneControlRefused;
    }
}
