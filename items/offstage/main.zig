const std = @import("std");
const builtin = @import("builtin");
const supervised = @import("supervised_child");

const usage =
    \\Usage: teerex offstage --socket /absolute/path --session session:UUID --cwd /absolute/path --purpose TEXT --timeout-ms N [--max-bytes N] -- ARGV...
    \\Create ONE detached terminal on the explicitly selected existing API13 Rex server (macOS or Linux).
    \\A foreground owner waits for terminal-program exit, deadline or cancellation, then requests block close.
    \\No existing block is adopted/closed, no window/layout/focus is changed, and no input is typed.
    \\NDJSON: offstage_started gives the target for concurrent observe/watch; offstage_result is the final receipt.
    \\Required deadline: 100..60000 ms; cleanup adds up to 5500 ms plus scheduling/output time.
    \\Capture defaults to 4096 (256..65536) JSON-encoded text bytes; partial text is a screen/scrollback PREFIX.
    \\Execution uses the SELECTED SERVER'S terminal host/environment, unlike local teerex run.
    \\Select a known LOCAL macOS or Linux server; a Unix socket alone does not establish physical locality.
    \\This is NOT a sandbox. Closing a block is not process-tree verification; resistant descendants may survive.
    \\SIGKILL/crash or lost create acknowledgement can leave a block; inspect the reported target/label manually.
    \\No persistent registry, background daemon, process-tree kill guarantee, installer or automatic presentation.
    \\Exit: 0 reported zero exit AND verified block absence; 1 failure/unknown; 2 usage; 124 deadline; 130/143 cancellation.
    \\
;

const Source = struct { rex_version: []const u8, platform: []const u8, api_revision: u32, instance_id: []const u8, host_id: []const u8 };
const Frame = struct {
    event: []const u8,
    source: ?Source = null,
    block_id: ?[]const u8 = null,
    exit_code: ?i64 = null,
    content: ?[]const u8 = null,
    complete: ?bool = null,
    instance_matched: ?bool = null,
    close_acknowledged: ?bool = null,
    block_absent: ?bool = null,
};

fn emit(value: anytype) !void {
    const output = try std.json.Stringify.valueAlloc(std.heap.page_allocator, value, .{});
    defer std.heap.page_allocator.free(output);
    try std.fs.File.stdout().writeAll(output);
    try std.fs.File.stdout().writeAll("\n");
}

fn fullId(value: []const u8, prefix: []const u8) bool {
    if (!std.mem.startsWith(u8, value, prefix) or value.len != prefix.len + 36) return false;
    for (value[prefix.len..], 0..) |c, i| {
        if (i == 8 or i == 13 or i == 18 or i == 23) {
            if (c != '-') return false;
        } else if (!std.ascii.isHex(c)) return false;
    }
    return true;
}

const Collector = struct {
    allocator: std.mem.Allocator,
    endpoint: []const u8,
    session: []const u8,
    id: []const u8,
    purpose: []const u8,
    label: []const u8,
    max_bytes: usize,
    timeout_ms: u64,
    source: ?Source = null,
    creating: bool = false,
    block: ?[]const u8 = null,
    exit_code: ?i64 = null,
    content: ?[]const u8 = null,
    complete: ?bool = null,
    pending: std.ArrayList(u8) = .empty,

    pub fn receive(self: *Collector, bytes: []const u8) !void {
        try self.pending.appendSlice(self.allocator, bytes);
        if (self.pending.items.len > 2 * self.max_bytes + 8192) return error.InvalidOffstageFrame;
        while (std.mem.indexOfScalar(u8, self.pending.items, '\n')) |end| {
            const parsed = try std.json.parseFromSlice(Frame, std.heap.page_allocator, self.pending.items[0..end], .{});
            defer parsed.deinit();
            const f = parsed.value;
            if (std.mem.eql(u8, f.event, "source") and self.source == null and !self.creating) {
                const source = f.source orelse return error.InvalidOffstageFrame;
                if (source.api_revision != 13 or (!std.mem.eql(u8, source.platform, "darwin_arm64") and !std.mem.eql(u8, source.platform, "linux_amd64")) or source.instance_id.len == 0 or source.host_id.len == 0) return error.InvalidOffstageSource;
                self.source = .{ .rex_version = try self.allocator.dupe(u8, source.rex_version), .platform = try self.allocator.dupe(u8, source.platform), .api_revision = source.api_revision, .instance_id = try self.allocator.dupe(u8, source.instance_id), .host_id = try self.allocator.dupe(u8, source.host_id) };
            } else if (std.mem.eql(u8, f.event, "creating") and self.source != null and !self.creating) {
                self.creating = true;
            } else if (std.mem.eql(u8, f.event, "created") and self.creating and self.block == null) {
                const block = f.block_id orelse return error.InvalidOffstageFrame;
                if (!fullId(block, "block:")) return error.InvalidOffstageFrame;
                self.block = try self.allocator.dupe(u8, block);
                try emit(.{ .schema_version = 1, .kind = "offstage_started", .invocation_id = self.id, .purpose = self.purpose, .label = self.label, .lifecycle_owner = "this_foreground_invocation", .collection_budget_ms = self.timeout_ms, .cleanup_policy = "close_created_block_on_exit_deadline_or_cancel", .target = .{ .server = self.endpoint, .session_id = self.session, .block_id = self.block }, .source = self.source, .execution_location = "selected_rex_terminal_host", .placement_at_creation = "detached", .all_processes_verified_gone = false });
            } else if (std.mem.eql(u8, f.event, "exited") and self.block != null and self.exit_code == null) {
                self.exit_code = f.exit_code orelse return error.InvalidOffstageFrame;
                const content = f.content orelse return error.InvalidOffstageFrame;
                const encoded = try std.json.Stringify.valueAlloc(self.allocator, content, .{});
                if (encoded.len > self.max_bytes) return error.OffstageCaptureExceedsLimit;
                self.content = try self.allocator.dupe(u8, content);
                self.complete = f.complete orelse return error.InvalidOffstageFrame;
            } else return error.InvalidOffstageFrame;
            try self.pending.replaceRange(self.allocator, 0, end + 1, &.{});
        }
    }
};

const Cleanup = struct {
    allocator: std.mem.Allocator,
    pending: std.ArrayList(u8) = .empty,
    instance_matched: ?bool = null,
    close_acknowledged: ?bool = null,
    block_absent: ?bool = null,
    received: bool = false,

    pub fn receive(self: *Cleanup, bytes: []const u8) !void {
        try self.pending.appendSlice(self.allocator, bytes);
        if (self.pending.items.len > 4096) return error.InvalidOffstageCleanup;
        if (std.mem.indexOfScalar(u8, self.pending.items, '\n')) |end| {
            if (self.received) return error.InvalidOffstageCleanup;
            const parsed = try std.json.parseFromSlice(Frame, self.allocator, self.pending.items[0..end], .{});
            const f = parsed.value;
            if (!std.mem.eql(u8, f.event, "closed") or f.instance_matched == null) return error.InvalidOffstageCleanup;
            self.instance_matched = f.instance_matched;
            self.close_acknowledged = f.close_acknowledged;
            self.block_absent = f.block_absent;
            self.received = true;
            try self.pending.replaceRange(self.allocator, 0, end + 1, &.{});
        }
    }
};

fn arguments(allocator: std.mem.Allocator, endpoint: []const u8, session: []const u8, values: anytype) ![]const []const u8 {
    const json = try std.json.Stringify.valueAlloc(allocator, values, .{});
    return allocator.dupe([]const u8, &.{ "rex", "--autostart=false", "--server", endpoint, "--timeout", "3s", "--color", "never", "do", "--session", session, "-e", @embedFile("terminal.lua"), "--args", json });
}

fn usageError() noreturn {
    std.debug.print("{s}", .{usage});
    std.process.exit(2);
}

pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    if (args.len == 1 and std.mem.eql(u8, args[0], "--help")) {
        try std.fs.File.stdout().writeAll(usage);
        return 0;
    }
    var socket: ?[]const u8 = null;
    var session: ?[]const u8 = null;
    var cwd: ?[]const u8 = null;
    var purpose: ?[]const u8 = null;
    var timeout: ?u64 = null;
    var limit: ?usize = null;
    var i: usize = 0;
    while (i < args.len and !std.mem.eql(u8, args[i], "--")) : (i += 2) {
        if (i + 1 >= args.len) usageError();
        const key = args[i];
        const value = args[i + 1];
        if (std.mem.eql(u8, key, "--socket") and socket == null) socket = value else if (std.mem.eql(u8, key, "--session") and session == null) session = value else if (std.mem.eql(u8, key, "--cwd") and cwd == null) cwd = value else if (std.mem.eql(u8, key, "--purpose") and purpose == null) purpose = value else if (std.mem.eql(u8, key, "--timeout-ms") and timeout == null) timeout = std.fmt.parseUnsigned(u64, value, 10) catch usageError() else if (std.mem.eql(u8, key, "--max-bytes") and limit == null) limit = std.fmt.parseUnsigned(usize, value, 10) catch usageError() else usageError();
    }
    const path = socket orelse usageError();
    const sid = session orelse usageError();
    const directory = cwd orelse usageError();
    const why = purpose orelse usageError();
    const budget = timeout orelse usageError();
    const max_bytes = limit orelse 4096;
    if (!std.fs.path.isAbsolute(path) or !fullId(sid, "session:") or !std.fs.path.isAbsolute(directory) or why.len == 0 or why.len > 256 or !std.unicode.utf8ValidateSlice(why) or budget < 100 or budget > 60000 or max_bytes < 256 or max_bytes > 65536 or i + 1 >= args.len or args[i + 1].len == 0) usageError();
    if (builtin.os.tag != .macos and builtin.os.tag != .linux) return error.OffstageRequiresMacOSOrLinux;
    const endpoint = try std.fmt.allocPrint(allocator, "unix://{s}", .{path});
    var random: [16]u8 = undefined;
    std.crypto.random.bytes(&random);
    const id = std.fmt.bytesToHex(random, .lower);
    const label = try std.fmt.allocPrint(allocator, "teerex-offstage-{s}", .{id});
    const argv = try arguments(allocator, endpoint, sid, .{ .operation = "create", .session_id = sid, .cwd = directory, .argv = args[i + 1 ..], .label = label, .max_bytes = max_bytes });
    var env = try std.process.getEnvMap(allocator);
    for ([_][]const u8{ "REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT" }) |key| env.remove(key);
    const signals = supervised.Signals.init();
    defer signals.deinit();
    var collector: Collector = .{ .allocator = allocator, .endpoint = endpoint, .session = sid, .id = &id, .purpose = why, .label = label, .max_bytes = max_bytes, .timeout_ms = budget };
    var failure: ?[]const u8 = null;
    const result: ?supervised.Result = supervised.collect(allocator, argv, &env, budget, &collector) catch |err| blk: {
        failure = @errorName(err);
        break :blk null;
    };
    var stop_signal = supervised.takeRequestedSignal();
    const deadline = result != null and result.?.deadline_exceeded;
    if (result) |r| {
        if (!r.stopped and (r.term != .Exited or r.term.Exited != 0 or collector.pending.items.len != 0 or collector.exit_code == null)) failure = "OffstageCollectionFailed";
        if (r.stderr.len != 0) std.debug.print("teerex offstage: {s}\n", .{r.stderr});
    }
    var cleanup: Cleanup = .{ .allocator = allocator };
    var cleanup_failure: ?[]const u8 = null;
    if (collector.block) |block| {
        // Retain the original request, while allowing a second signal to stop
        // the bounded cleanup attempt. No handler-reset race between phases.
        const close_argv = try arguments(allocator, endpoint, sid, .{ .operation = "close", .session_id = sid, .block_id = block, .instance_id = collector.source.?.instance_id, .host_id = collector.source.?.host_id });
        const closed: ?supervised.Result = supervised.collect(allocator, close_argv, &env, 5000, &cleanup) catch |err| blk: {
            cleanup_failure = @errorName(err);
            break :blk null;
        };
        if (closed) |r| {
            if (r.stopped or r.term != .Exited or r.term.Exited != 0 or !cleanup.received or cleanup.pending.items.len != 0) cleanup_failure = "OffstageCleanupUnknown";
            if (r.stderr.len != 0) std.debug.print("teerex offstage cleanup: {s}\n", .{r.stderr});
        }
    }
    if (stop_signal == 0) stop_signal = supervised.requestedSignal();
    const success = stop_signal == 0 and !deadline and failure == null and collector.exit_code != null and collector.exit_code.? == 0 and cleanup_failure == null and cleanup.instance_matched == true and cleanup.block_absent == true;
    try emit(.{
        .schema_version = 1,
        .kind = "offstage_result",
        .invocation_id = &id,
        .purpose = why,
        .label = label,
        .lifecycle_owner = "this_foreground_invocation",
        .target = .{ .server = endpoint, .session_id = sid, .block_id = collector.block },
        .source = collector.source,
        .execution_location = "selected_rex_terminal_host",
        .requested_cwd = directory,
        .timeout_ms = budget,
        .creation_dispatch_observed = collector.creating,
        // Absence of a transport frame does not prove creation never ran.
        .creation_request_may_have_run = if (collector.creating) @as(?bool, true) else null,
        .creation_acknowledged = collector.block != null,
        .outcome = if (stop_signal != 0) "cancel_requested" else if (deadline) "deadline_exceeded" else if (failure != null) "observation_failed" else "exit_reported",
        .failure_reason = failure,
        .cancellation_signal = if (stop_signal == 0) @as(?u8, null) else stop_signal,
        .success = success,
        .task_completion = "not_assessed",
        .exit_code_reported = collector.exit_code,
        .elapsed_collection_ms = if (result) |r| @as(?u64, r.elapsed_ms) else null,
        .capture = .{ .scope = "screen_and_scrollback", .portion = "prefix", .max_bytes = max_bytes, .content = collector.content, .complete = collector.complete },
        .cleanup = .{
            .attempted = collector.block != null,
            .server_instance_matched = cleanup.instance_matched,
            .close_acknowledged = cleanup.close_acknowledged,
            .block_absent = cleanup.block_absent,
            .failure_reason = cleanup_failure,
            .process_effect = "not_verified",
            .all_processes_verified_gone = false,
            .sigkill_or_crash_of_owner = "not_covered",
        },
    });
    return if (stop_signal != 0) 128 + stop_signal else if (deadline) 124 else if (success) 0 else 1;
}
