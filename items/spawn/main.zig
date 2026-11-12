const std = @import("std");
const builtin = @import("builtin");
const supervised = @import("supervised_child");

const usage =
    \\Usage: teerex spawn --socket ABS --session session:UUID --name LABEL --cwd ABS
    \\                    --report-to-session session:UUID --report-to-block block:UUID [--timeout-ms N] -- ARGV...
    \\Create one window-attached agent terminal on the explicit existing Rex server, without switching focus.
    \\Requires macOS/Linux, Rex on PATH, API10..13 and canonical lowercase IDs. No autostart or detached fallback.
    \\Exports agent-core address/name/report-to and LC_ metadata through a fixed sh shim; argv is never interpolated.
    \\Creation ACK is not agent readiness/completion. This is not a sandbox or an input lease.
    \\Timeout defaults to 5000 ms (100..60000), plus bounded transport cleanup. No creation retry or automatic close.
    \\After an uncertain result, inspect the session before retrying: a terminal may already exist and keep running.
    \\Exit: 0 created and attached location verified, 1 refusal/uncertain/error, 2 usage, 124 deadline, 130/143 cancellation.
    \\
;

const Source = struct { rex_version: []const u8, platform: []const u8, api_revision: i64 };
const Created = struct { window_id: []const u8, block_id: []const u8, revision: u64 };
const Frame = struct { event: []const u8, source: ?Source = null, created: ?Created = null, reason: ?[]const u8 = null };
const Collector = struct {
    allocator: std.mem.Allocator,
    pending: std.ArrayList(u8) = .empty,
    source: ?Source = null,
    created: ?Created = null,
    attempt_seen: bool = false,
    verified: bool = false,
    finished: bool = false,
    reason: ?[]const u8 = null,
    frames: u8 = 0,

    pub fn receive(self: *Collector, bytes: []const u8) !void {
        if (bytes.len > 8192 - self.pending.items.len) return error.InvalidSpawnFrame;
        try self.pending.appendSlice(self.allocator, bytes);
        while (std.mem.indexOfScalar(u8, self.pending.items, '\n')) |end| {
            if (self.finished or self.frames >= 5) return error.InvalidSpawnFrame;
            self.frames += 1;
            // Frame identities must survive compaction of the transport buffer.
            const f = (try std.json.parseFromSlice(Frame, self.allocator, self.pending.items[0..end], .{ .allocate = .alloc_always })).value;
            if (std.mem.eql(u8, f.event, "source") and self.source == null and !self.attempt_seen) {
                self.source = f.source orelse return error.InvalidSpawnFrame;
            } else if (std.mem.eql(u8, f.event, "attempt") and self.source != null and !self.attempt_seen) {
                self.attempt_seen = true;
            } else if (std.mem.eql(u8, f.event, "created") and self.attempt_seen and self.created == null) {
                const c = f.created orelse return error.InvalidSpawnFrame;
                if (!fullId(c.window_id, "window:") or !fullId(c.block_id, "block:")) return error.InvalidSpawnFrame;
                self.created = c;
            } else if (std.mem.eql(u8, f.event, "verified") and self.created != null) {
                self.verified = true;
                self.finished = true;
            } else if ((std.mem.eql(u8, f.event, "refused") and !self.attempt_seen) or std.mem.eql(u8, f.event, "failed")) {
                self.reason = f.reason orelse return error.InvalidSpawnFrame;
                self.finished = true;
            } else return error.InvalidSpawnFrame;
            try self.pending.replaceRange(self.allocator, 0, end + 1, &.{});
        }
    }
};

fn fullId(value: []const u8, prefix: []const u8) bool {
    if (!std.mem.startsWith(u8, value, prefix) or value.len != prefix.len + 36) return false;
    for (value[prefix.len..], 0..) |c, i| {
        if (i == 8 or i == 13 or i == 18 or i == 23) {
            if (c != '-') return false;
        } else if (!std.ascii.isHex(c) or std.ascii.isUpper(c)) return false;
    }
    return true;
}

fn usageError(message: []const u8) u8 {
    std.debug.print("teerex spawn: {s}\n{s}", .{ message, usage });
    return 2;
}

pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    if (args.len == 1 and std.mem.eql(u8, args[0], "--help")) {
        try std.fs.File.stdout().writeAll(usage);
        return 0;
    }
    var socket: ?[]const u8 = null;
    var session: ?[]const u8 = null;
    var name: ?[]const u8 = null;
    var cwd: ?[]const u8 = null;
    var report_session: ?[]const u8 = null;
    var report_block: ?[]const u8 = null;
    var timeout: ?u64 = null;
    var i: usize = 0;
    while (i < args.len and !std.mem.eql(u8, args[i], "--")) : (i += 2) {
        if (i + 1 >= args.len) return usageError("every option needs a value");
        if (std.mem.eql(u8, args[i], "--socket") and socket == null) {
            socket = args[i + 1];
        } else if (std.mem.eql(u8, args[i], "--session") and session == null) {
            session = args[i + 1];
        } else if (std.mem.eql(u8, args[i], "--name") and name == null) {
            name = args[i + 1];
        } else if (std.mem.eql(u8, args[i], "--cwd") and cwd == null) {
            cwd = args[i + 1];
        } else if (std.mem.eql(u8, args[i], "--report-to-session") and report_session == null) {
            report_session = args[i + 1];
        } else if (std.mem.eql(u8, args[i], "--report-to-block") and report_block == null) {
            report_block = args[i + 1];
        } else if (std.mem.eql(u8, args[i], "--timeout-ms") and timeout == null) {
            timeout = std.fmt.parseUnsigned(u64, args[i + 1], 10) catch return usageError("invalid timeout");
        } else return usageError("unknown or repeated option");
    }
    const path = socket orelse return usageError("--socket is required");
    const sid = session orelse return usageError("--session is required");
    const label = name orelse return usageError("--name is required");
    const directory = cwd orelse return usageError("--cwd is required");
    const parent_session = report_session orelse return usageError("--report-to-session is required");
    const parent_block = report_block orelse return usageError("--report-to-block is required");
    const budget = timeout orelse 5000;
    if (i >= args.len or i + 1 >= args.len) return usageError("-- and a nonempty command are required");
    const command = args[i + 1 ..];
    if (command[0].len == 0) return usageError("command must not be empty");
    if (!std.fs.path.isAbsolute(path) or !std.fs.path.isAbsolute(directory)) return usageError("socket and cwd must be absolute");
    if (!fullId(sid, "session:") or !fullId(parent_session, "session:") or !fullId(parent_block, "block:")) return usageError("canonical lowercase full session/block IDs are required");
    if (label.len == 0 or label.len > 128 or !std.unicode.utf8ValidateSlice(label)) return usageError("name must be 1..128 UTF-8 bytes");
    for (label) |c| if (c < 32 or c == 127) return usageError("name must not contain controls");
    if (budget < 100 or budget > 60000) return usageError("timeout must be 100..60000 ms");
    if (!std.unicode.utf8ValidateSlice(directory)) return usageError("cwd must be UTF-8");
    for (command) |arg| if (!std.unicode.utf8ValidateSlice(arg)) return usageError("argv must be UTF-8");
    const request = try std.json.Stringify.valueAlloc(allocator, .{
        .session_id = sid,
        .name = label,
        .cwd = directory,
        .report_session = parent_session,
        .report_block = parent_block,
        .argv = command,
    }, .{});
    if (request.len > 48000) return usageError("encoded spawn arguments exceed 48000 bytes");
    if (builtin.os.tag != .macos and builtin.os.tag != .linux) return error.SpawnRequiresUnix;
    var env = try std.process.getEnvMap(allocator);
    for ([_][]const u8{ "REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT" }) |key| env.remove(key);
    const endpoint = try std.fmt.allocPrint(allocator, "unix://{s}", .{path});
    const argv = [_][]const u8{ "rex", "--autostart=false", "--server", endpoint, "--timeout", "3s", "--color", "never", "do", "--session", sid, "-e", @embedFile("spawn.lua"), "--args", request };
    const signals = supervised.Signals.init();
    defer signals.deinit();
    var timer = try std.time.Timer.start();
    var c: Collector = .{ .allocator = allocator };
    var failure: ?[]const u8 = null;
    const result: ?supervised.Result = supervised.collect(allocator, &argv, &env, budget, &c) catch |err| blk: {
        failure = @errorName(err);
        break :blk null;
    };
    const signal = supervised.requestedSignal();
    const deadline = result != null and result.?.deadline_exceeded;
    const transport_ok = result != null and !result.?.stopped and result.?.term == .Exited and result.?.term.Exited == 0 and c.pending.items.len == 0;
    const success = transport_ok and c.verified and signal == 0;
    const outcome: []const u8 = if (signal != 0) "cancel_requested" else if (deadline) "deadline_exceeded" else if (success) "created_and_attached" else if (transport_ok and c.finished and !c.attempt_seen) "refused" else "uncertain";
    const output = try std.json.Stringify.valueAlloc(allocator, .{
        .schema_version = 1,
        .kind = "spawn_result",
        .target = .{ .server = endpoint, .session_id = sid },
        .source = c.source,
        .created = c.created,
        .attached_location_verified = c.verified,
        .creation_attempt_frame_seen = c.attempt_seen,
        .attempt_evidence = "received_local_frame_not_server_dispatch_proof",
        .outcome = outcome,
        .failure_reason = failure orelse c.reason,
        .environment_contract = "agent_core_spawn_address_v1",
        .program_start = "not_assessed",
        .agent_readiness = "not_assessed",
        .task_completion = "not_assessed",
        .focus_requested = false,
        .retry_safe = false,
        .automatic_close = false,
        .exclusive_input_lease = false,
        .elapsed_ms = timer.read() / std.time.ns_per_ms,
        .timeout_ms = budget,
    }, .{ .whitespace = .indent_2 });
    try std.fs.File.stdout().writeAll(output);
    try std.fs.File.stdout().writeAll("\n");
    return if (signal != 0) 128 + signal else if (deadline) 124 else if (success) 0 else 1;
}
