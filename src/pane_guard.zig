const std = @import("std");
pub const source = @embedFile("pane_guard.py");

pub fn python(allocator: std.mem.Allocator, script: []const u8) ![]const u8 {
    const encoded = try std.json.Stringify.valueAlloc(allocator, source, .{});
    return std.fmt.allocPrint(allocator, "import types,sys\n_pane_guard=types.ModuleType('teerex_pane_guard')\nexec({s},_pane_guard.__dict__)\n_pane_guard.SOURCE={s}\nsys.modules['teerex_pane_guard']=_pane_guard\n{s}", .{ encoded, encoded, script });
}

pub fn prelude(allocator: std.mem.Allocator, endpoint: []const u8, message: bool) ![]const u8 {
    const result = try std.process.Child.run(.{ .allocator = allocator, .argv = &.{ "python3", "-I", "-c", source, endpoint, if (message) "message" else "control" }, .max_output_bytes = std.math.maxInt(usize) });
    if (result.term != .Exited or result.term.Exited != 0) {
        try std.fs.File.stderr().writeAll(result.stderr);
        return error.PaneGuardUnavailable;
    }
    return result.stdout;
}

pub fn checkTake(allocator: std.mem.Allocator, socket: []const u8, session: []const u8, pane: []const u8) !void {
    const endpoint = try std.fmt.allocPrint(allocator, "unix://{s}", .{socket});
    const prefix = try prelude(allocator, endpoint, false);
    const script = try std.mem.concat(allocator, u8, &.{ prefix, "\nreturn rex.call('teerex.guard.take',rex.args)" });
    const args = try std.json.Stringify.valueAlloc(allocator, .{ .session_id = session, .block_id = pane }, .{});
    var env = try std.process.getEnvMap(allocator);
    for ([_][]const u8{ "REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT" }) |key| env.remove(key);
    const result = try std.process.Child.run(.{ .allocator = allocator, .argv = &.{ env.get("TEEREX_INTERNAL_REX") orelse "rex", "--autostart=false", "--server", endpoint, "--timeout", "3s", "do", "-e", script, "--args", args, "--json" }, .env_map = &env });
    if (result.term != .Exited or result.term.Exited != 0) {
        try std.fs.File.stderr().writeAll(result.stderr);
        return error.PaneControlRefused;
    }
}
