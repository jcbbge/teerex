const std = @import("std");
const builtin = @import("builtin");
const supervised = @import("supervised_child");

const usage =
    \\Usage: teerex run --socket /absolute/path --cwd /absolute/path [--timeout-ms N] [--max-bytes N] -- ARGV...
    \\Run argv LOCALLY through Rex Lua exec; never type into a terminal or run on the selected server.
    \\Requires macOS, Rex on PATH, and an existing API-13 server. No autostart or implicit target.
    \\Explicit cwd and -- are required; no implicit shell. Stdin is EOF; no interactive input.
    \\Timeout defaults to 10000 ms (100..60000); combined stdout/stderr retention defaults to 4096 bytes (1..65536).
    \\Rex enforces the command timeout; an outer monotonic deadline adds 5000 ms for transport/cleanup.
    \\SIGINT/TERM request cancellation; group KILL follows after at most 250 ms plus scheduling/drain time.
    \\Cleanup covers only the owned process group, not detached processes or a security sandbox.
    \\The program inherits your environment (except Rex target hints) and can change files/use account authority.
    \\JSON preserves output as UTF-8 or base64, bounded raw-byte prefixes, real exit and unknown evidence.
    \\Exit: 0 successful command, 1 failure, 2 usage, 124 deadline, 130 SIGINT, 143 SIGTERM.
    \\
;

const Source = struct { rex_version: []const u8, platform: []const u8, api_revision: u32 };
const ExitReport = struct { code: i32, signal: ?[]const u8, timed_out: bool, ok: bool };
const Frame = struct {
    event: []const u8,
    source: ?Source = null,
    pid: ?i32 = null,
    hex: ?[]const u8 = null,
    code: ?i32 = null,
    signal: ?[]const u8 = null,
    timed_out: bool = false,
    ok: ?bool = null,
    stdout_seen: ?u64 = null,
    stderr_seen: ?u64 = null,
};

const Capture = struct {
    encoding: []const u8,
    content: []const u8,
    retained_bytes: usize,
    bytes_seen: ?u64,
    complete: bool,
};

const Collector = struct {
    allocator: std.mem.Allocator,
    limit: usize,
    source: ?Source = null,
    pid: ?i32 = null,
    result: ?ExitReport = null,
    stdout: std.ArrayList(u8) = .empty,
    stderr: std.ArrayList(u8) = .empty,
    pending: std.ArrayList(u8) = .empty,
    stdout_seen: ?u64 = null,
    stderr_seen: ?u64 = null,

    pub fn receive(self: *Collector, bytes: []const u8) !void {
        try self.pending.appendSlice(self.allocator, bytes);
        while (std.mem.indexOfScalar(u8, self.pending.items, '\n')) |end| {
            if (end > 2 * self.limit + 4096) return error.InvalidRunFrame;
            try self.line(self.pending.items[0..end]);
            try self.pending.replaceRange(self.allocator, 0, end + 1, &.{});
        }
        if (self.pending.items.len > 2 * self.limit + 4096) return error.InvalidRunFrame;
    }

    fn line(self: *Collector, bytes: []const u8) !void {
        // Free every frame, rather than accumulating parser arenas for long output streams.
        const parsed = try std.json.parseFromSlice(Frame, std.heap.page_allocator, bytes, .{});
        defer parsed.deinit();
        const f = parsed.value;
        if (self.result != null) return error.InvalidRunFrame;
        if (std.mem.eql(u8, f.event, "source")) {
            const source = f.source orelse return error.InvalidRunFrame;
            if (self.source != null or source.api_revision != 13) return error.InvalidRunFrame;
            self.source = .{
                .rex_version = try self.allocator.dupe(u8, source.rex_version),
                .platform = try self.allocator.dupe(u8, source.platform),
                .api_revision = source.api_revision,
            };
        } else if (self.source == null) {
            return error.InvalidRunFrame;
        } else if (std.mem.eql(u8, f.event, "started")) {
            const pid = f.pid orelse return error.InvalidRunFrame;
            if (self.pid != null or pid <= 0) return error.InvalidRunFrame;
            self.pid = pid;
        } else if (std.mem.eql(u8, f.event, "stdout") or std.mem.eql(u8, f.event, "stderr")) {
            const hex = f.hex orelse return error.InvalidRunFrame;
            if (hex.len % 2 != 0 or hex.len / 2 > self.limit - self.stdout.items.len - self.stderr.items.len) return error.InvalidRunFrame;
            const buffer = if (std.mem.eql(u8, f.event, "stdout")) &self.stdout else &self.stderr;
            const offset = buffer.items.len;
            try buffer.resize(self.allocator, offset + hex.len / 2);
            _ = try std.fmt.hexToBytes(buffer.items[offset..], hex);
        } else if (std.mem.eql(u8, f.event, "result")) {
            if (self.pid == null) return error.InvalidRunFrame;
            const out_seen = f.stdout_seen orelse return error.InvalidRunFrame;
            const err_seen = f.stderr_seen orelse return error.InvalidRunFrame;
            if (out_seen < self.stdout.items.len or err_seen < self.stderr.items.len) return error.InvalidRunFrame;
            self.result = .{
                .code = f.code orelse return error.InvalidRunFrame,
                .signal = if (f.signal) |signal| try self.allocator.dupe(u8, signal) else null,
                .timed_out = f.timed_out,
                .ok = f.ok orelse return error.InvalidRunFrame,
            };
            self.stdout_seen = out_seen;
            self.stderr_seen = err_seen;
        } else return error.InvalidRunFrame;
    }

    fn capture(self: *const Collector, bytes: []const u8, seen: ?u64) !Capture {
        const utf8 = std.unicode.utf8ValidateSlice(bytes);
        const content = if (utf8) bytes else blk: {
            const encoded = try self.allocator.alloc(u8, std.base64.standard.Encoder.calcSize(bytes.len));
            break :blk std.base64.standard.Encoder.encode(encoded, bytes);
        };
        return .{ .encoding = if (utf8) "utf8" else "base64", .content = content, .retained_bytes = bytes.len, .bytes_seen = seen, .complete = if (seen) |n| n == bytes.len else false };
    }
};

fn usageError(message: []const u8) noreturn {
    std.debug.print("teerex run: {s}\n{s}", .{ message, usage });
    std.process.exit(2);
}

pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    if (args.len == 1 and std.mem.eql(u8, args[0], "--help")) {
        try std.fs.File.stdout().writeAll(usage);
        return 0;
    }
    var socket: ?[]const u8 = null;
    var cwd: ?[]const u8 = null;
    var timeout: ?u64 = null;
    var limit: ?usize = null;
    var i: usize = 0;
    while (i < args.len and !std.mem.eql(u8, args[i], "--")) : (i += 2) {
        if (i + 1 >= args.len) usageError("every option needs a value");
        const name = args[i];
        const value = args[i + 1];
        if (std.mem.eql(u8, name, "--socket") and socket == null) {
            socket = value;
        } else if (std.mem.eql(u8, name, "--cwd") and cwd == null) {
            cwd = value;
        } else if (std.mem.eql(u8, name, "--timeout-ms") and timeout == null) {
            timeout = std.fmt.parseUnsigned(u64, value, 10) catch usageError("invalid timeout");
        } else if (std.mem.eql(u8, name, "--max-bytes") and limit == null) {
            limit = std.fmt.parseUnsigned(usize, value, 10) catch usageError("invalid byte limit");
        } else usageError("unknown or repeated option");
    }
    const path = socket orelse usageError("--socket is required");
    const directory = cwd orelse usageError("--cwd is required");
    const timeout_ms = timeout orelse 10000;
    const max_bytes = limit orelse 4096;
    if (!std.fs.path.isAbsolute(path) or !std.fs.path.isAbsolute(directory)) usageError("socket and cwd must be absolute paths");
    if (timeout_ms < 100 or timeout_ms > 60000 or max_bytes < 1 or max_bytes > 65536) usageError("timeout or byte limit out of range");
    if (i + 1 >= args.len or args[i + 1].len == 0) usageError("-- and a nonempty executable are required");
    if (builtin.os.tag != .macos) return error.RunRequiresMacOS;
    return supervise(allocator, path, directory, args[i + 1 ..], timeout_ms, max_bytes);
}

fn supervise(allocator: std.mem.Allocator, socket: []const u8, cwd: []const u8, argv: []const []const u8, timeout_ms: u64, max_bytes: usize) !u8 {
    const endpoint = try std.fmt.allocPrint(allocator, "unix://{s}", .{socket});
    const json_args = try std.json.Stringify.valueAlloc(allocator, .{
        .argv = argv,
        .cwd = cwd,
        .timeout_ms = timeout_ms,
        .max_bytes = max_bytes,
    }, .{});
    const rex_argv = [_][]const u8{ "rex", "--autostart=false", "--server", endpoint, "--timeout", "3s", "--color", "never", "do", "-e", @embedFile("execute.lua"), "--args", json_args };
    var env = try std.process.getEnvMap(allocator);
    for ([_][]const u8{ "REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT" }) |key| env.remove(key);
    const signals = supervised.Signals.init();
    defer signals.deinit();
    var collector: Collector = .{ .allocator = allocator, .limit = max_bytes };
    const result = try supervised.collect(allocator, &rex_argv, &env, timeout_ms + 5000, &collector);
    const transport_ok = result.term == .Exited and result.term.Exited == 0 and collector.pending.items.len == 0;
    const known_exit = collector.result;
    const success = !result.stopped and transport_ok and known_exit != null and
        known_exit.?.ok and known_exit.?.code == 0 and known_exit.?.signal == null and !known_exit.?.timed_out;
    const timed_out = result.deadline_exceeded or (known_exit != null and known_exit.?.timed_out);
    const exit_code: u8 = if (result.stop_signal != 0) 128 + result.stop_signal else if (timed_out) 124 else if (success) 0 else 1;
    var random: [16]u8 = undefined;
    std.crypto.random.bytes(&random);
    const id = std.fmt.bytesToHex(random, .lower);
    const output = try std.json.Stringify.valueAlloc(allocator, .{
        .schema_version = 1,
        .kind = "run_result",
        .execution_id = id[0..],
        .execution_location = "cli_local",
        .client_platform = @tagName(builtin.os.tag) ++ "/" ++ @tagName(builtin.cpu.arch),
        .server = endpoint,
        .source = collector.source,
        .requested_cwd = cwd,
        .started_at_unix_ms = result.started_at_unix_ms,
        .elapsed_ms = result.elapsed_ms,
        .limits = .{ .command_timeout_ms = timeout_ms, .outer_deadline_ms = timeout_ms + 5000, .max_retained_output_bytes = max_bytes },
        .program_pid_reported = collector.pid,
        .outcome = if (result.stop_signal != 0) "cancel_requested" else if (result.deadline_exceeded) "outer_deadline_exceeded" else if (known_exit != null and known_exit.?.timed_out) "command_timed_out" else if (transport_ok and known_exit != null) "exit_reported" else "backend_error",
        .cancellation_signal = if (result.stop_signal == 0) @as(?u8, null) else result.stop_signal,
        .success = success,
        .exit_report = known_exit,
        .task_completion = "not_assessed",
        .capture_scope = "rex_exec_callbacks",
        .retention_policy = "combined_first_arrivals_per_stream_prefix",
        .stdout = try collector.capture(collector.stdout.items, collector.stdout_seen),
        .stderr = try collector.capture(collector.stderr.items, collector.stderr_seen),
        .backend_stderr = try collector.capture(result.stderr, result.stderr_seen),
        .cleanup = .{ .scope = "owned_process_group", .group_sigterm = result.group_term, .group_sigkill = result.group_kill, .final_sigkill_requested = true, .detached_descendants = "not_covered", .all_descendants_verified_gone = false },
    }, .{ .whitespace = .indent_2 });
    try std.fs.File.stdout().writeAll(output);
    try std.fs.File.stdout().writeAll("\n");
    return exit_code;
}
