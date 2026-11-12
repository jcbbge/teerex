const std = @import("std");
const builtin = @import("builtin");
const supervised = @import("supervised_child");

const observation_usage =
    \\Usage: teerex observe --socket /absolute/path --session session:UUID --block block:UUID [--max-bytes N] [--timeout-ms N]
    \\       teerex compare --before /path/to/before.json --after /path/to/after.json
    \\       teerex watch --socket /absolute/path --session session:UUID --block block:UUID --baseline FILE --timeout-ms N [--interval-ms N]
    \\                    [--status-state idle|working|done|blocked|error [--status-id RECORD_ID]]
    \\
    \\Read bounded terminal text and process/directory/status evidence from an explicit Rex target.
    \\N defaults to 4096; allowed range: 256..65536 JSON-encoded content bytes.
    \\Output is JSON. Capture includes screen and scrollback; a partial capture is a prefix.
    \\Compare reads two explicit observation files (at most 1 MiB each), without contacting Rex.
    \\Changes describe returned evidence, never activity, completion, freshness, or permission.
    \\Observe/compare do not send input, edit configuration, or save files. No autostart or implicit target.
    \\Observe supports macOS/Linux; its collection budget defaults to 5000 ms (100..60000), plus bounded cleanup.
    \\Watch is a foreground, read-only macOS/Linux wait using the baseline's byte limit and exact target/source.
    \\Watch requires a 100..60000 ms deadline; interval defaults to 250 ms (50..5000) AFTER each collection.
    \\Watch returns evidence/availability changes, or deadline/unknown/error/cancellation, never completion.
    \\With --status-state, wait only for differing matching report evidence relative to the baseline.
    \\No --status-id selects the root report; named IDs match exactly. Retained identical reports do not wake it.
    \\Its monotonic collection deadline includes polling; cleanup may add 500 ms plus scheduling/output time.
    \\Watch exit: 0 change observed, 1 collection/compatibility error, 2 usage, 124 deadline, 130/143 cancellation.
    \\
;

const usage = observation_usage ++
    \\       teerex run --socket /absolute/path --cwd /absolute/path [--timeout-ms N] [--max-bytes N] -- ARGV...
    \\       teerex offstage --socket /absolute/path --session session:UUID --cwd /absolute/path --purpose TEXT --timeout-ms N -- ARGV...
    \\       teerex doctor --socket /absolute/path [--timeout-ms N] [--baseline FILE]
    \\       teerex maneuver-check --definition FILE --observation FILE --socket /absolute/path --session session:UUID --block block:UUID
    \\       teerex maneuver-check --library FILE --list
    \\       teerex maneuver-check --library FILE [--before FILE] --observation FILE --socket /absolute/path --session session:UUID --block block:UUID
    \\       teerex filter --sample FILE --sample FILE [--sample FILE ...]
    \\       teerex filter cache put|get|purge --help
    \\       teerex jobs track|list|inspect|adopt|present|forget --help
    \\       teerex adapters generate|call --help
    \\       teerex send --socket /absolute/path --session session:UUID --block block:UUID --from LABEL --message-file /absolute/path [--timeout-ms N]
    \\       teerex spawn --socket /absolute/path --session session:UUID --name LABEL --cwd /absolute/path
    \\                    --report-to-session session:UUID --report-to-block block:UUID [--timeout-ms N] -- ARGV...
    \\
    \\Run executes supplied argv LOCALLY on macOS, not in a terminal or on the selected server.
    \\Run is not a sandbox: the program can modify files/use your account's authority. See run --help.
    \\
;

const Process = struct {
    pid: i64,
    name: []const u8,
    cwd: ?[]const u8 = null,
};

const ProcessEvidence = struct {
    child: ?Process = null,
    foreground: ?Process = null,
    last_exit: ?struct { exit_code: i64 },
};

const ReportOwner = struct { pid: i64, name: []const u8 };

const DirectoryReport = struct {
    pwd: ?[]const u8 = null,
    owner: ?ReportOwner = null,
};

const StatusRecord = struct {
    state: []const u8,
    updated_at: []const u8,
    id: ?[]const u8 = null,
    app: ?[]const u8 = null,
    effective_app: ?[]const u8 = null,
    kind: ?[]const u8 = null,
    progress: ?u8 = null,
    title: ?[]const u8 = null,
    msg: ?[]const u8 = null,
    owner: ?ReportOwner = null,
};

fn Evidence(comptime T: type) type {
    return struct { method: []const u8, basis: []const u8, freshness: []const u8, data: T };
}

pub const Observation = struct {
    schema_version: u32,
    observation_id: []const u8,
    observation_started_at_unix_ms: i64 = 0,
    observed_at_unix_ms: i64 = 0,
    atomic_snapshot: bool = false,
    target: struct { server: []const u8, session_id: []const u8, block_id: []const u8 },
    source: struct { rex_version: []const u8, platform: []const u8, api_revision: u32 },
    capture: struct { scope: []const u8, portion: []const u8, max_bytes: usize, complete: bool, content: []const u8 },
    process: ?Evidence(ProcessEvidence) = null,
    reported_directory: ?struct {
        method: []const u8,
        basis: []const u8,
        freshness: []const u8,
        reported_at: ?[]const u8 = null,
        data: DirectoryReport,
    } = null,
    program_status: ?Evidence(struct { records: []StatusRecord }) = null,
};

const Change = struct {
    before_available: bool,
    after_available: bool,
    availability_changed: bool,
    changed: ?bool,
};

const Comparison = struct {
    schema_version: u32 = 1,
    kind: []const u8 = "observation_changes",
    before_observation_id: []const u8,
    after_observation_id: []const u8,
    target: @FieldType(Observation, "target"),
    source: @FieldType(Observation, "source"),
    interpretation: []const u8 = "none",
    capture: struct {
        scope: []const u8 = "screen_and_scrollback",
        before_complete: bool,
        after_complete: bool,
        before_max_bytes: usize,
        after_max_bytes: usize,
        captured_text_changed: ?bool,
        full_text_changed: ?bool,
    },
    process: struct { foreground: Change, child: Change, last_exit: Change },
    reported_directory: Change,
    program_status: Change,
};

const ObservationOutput = struct {
    allocator: std.mem.Allocator,
    bytes: std.ArrayList(u8) = .empty,

    pub fn receive(self: *ObservationOutput, bytes: []const u8) !void {
        if (bytes.len > 5 * 128 * 1024 + 256 - self.bytes.items.len) return error.ObservationExceedsLimit;
        try self.bytes.appendSlice(self.allocator, bytes);
    }
};

const WatchCollector = struct {
    allocator: std.mem.Allocator,
    baseline: Observation,
    timer: *std.time.Timer,
    timeout_ms: u64,
    status_state: ?[]const u8,
    status_id: ?[]const u8,
    pending: std.ArrayList(u8) = .empty,
    attempts: usize = 1,
    compared: usize = 0,
    collecting: bool = true,
    late: bool = false,
    failure: ?[]const u8 = null,
    last_comparison: ?Comparison = null,
    last_compared_at: ?u64 = null,
    last_after_id: ?[]u8 = null,
    changed_fields: std.ArrayList([]const u8) = .empty,
    availability_fields: std.ArrayList([]const u8) = .empty,
    unknown_fields: std.ArrayList([]const u8) = .empty,
    matched_status: ?struct { record_id: ?[]const u8, state: []const u8, updated_at: []const u8 } = null,

    pub fn isComplete(self: *const WatchCollector) bool {
        return self.failure != null or self.late or self.satisfied();
    }

    fn satisfied(self: *const WatchCollector) bool {
        return if (self.status_state != null) self.matched_status != null else self.changed_fields.items.len != 0 or self.availability_fields.items.len != 0;
    }

    pub fn receive(self: *WatchCollector, bytes: []const u8) !void {
        var remaining = bytes;
        while (remaining.len != 0 and !self.isComplete()) {
            const newline = std.mem.indexOfScalar(u8, remaining, '\n');
            const n = newline orelse remaining.len;
            if (n > 5 * 128 * 1024 + 320 - self.pending.items.len) {
                self.failure = "ObservationExceedsLimit";
                return;
            }
            try self.pending.appendSlice(self.allocator, remaining[0..n]);
            if (newline == null) return;
            self.frame() catch |err| {
                self.failure = @errorName(err);
                return;
            };
            self.pending.clearRetainingCapacity();
            remaining = remaining[n + 1 ..];
        }
    }

    fn frame(self: *WatchCollector) !void {
        // Only one decoded sample and one last comparison survive at any time.
        var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
        defer arena.deinit();
        const allocator = arena.allocator();
        const parsed = try std.json.parseFromSlice(struct { event: []const u8, data: ?std.json.Value = null }, allocator, self.pending.items, .{});
        const event = parsed.value;
        if (std.mem.eql(u8, event.event, "collecting")) {
            if (self.collecting or event.data != null) return error.InvalidObservationFrame;
            self.collecting = true;
            self.attempts += 1;
            return;
        }
        if (!std.mem.eql(u8, event.event, "sample") or !self.collecting or event.data == null) return error.InvalidObservationFrame;
        self.collecting = false;
        const target = self.baseline.target;
        // These internal packets have no per-read timestamp claim. Receipt time
        // below bounds acceptance; returned comparison IDs identify local evidence.
        const after = try observation(allocator, target.server, target.session_id, target.block_id, self.baseline.capture.max_bytes, event.data.?, 0);
        var comparison = try compareObservations(self.baseline, after);
        const compared_at = self.timer.read() / std.time.ns_per_ms;
        if (compared_at >= self.timeout_ms) {
            self.late = true;
            return;
        }
        const after_id = try std.heap.page_allocator.dupe(u8, comparison.after_observation_id);
        if (self.last_after_id) |id| std.heap.page_allocator.free(id);
        self.last_after_id = after_id;
        comparison.after_observation_id = after_id;
        self.last_comparison = comparison;
        self.last_compared_at = compared_at;
        self.compared += 1;
        self.changed_fields.clearRetainingCapacity();
        self.availability_fields.clearRetainingCapacity();
        self.unknown_fields.clearRetainingCapacity();
        inline for (.{ "capture.captured_text", "capture.full_text" }, .{ comparison.capture.captured_text_changed, comparison.capture.full_text_changed }) |field, changed| {
            if (changed == null) {
                try self.unknown_fields.append(self.allocator, field);
            } else if (changed.?) try self.changed_fields.append(self.allocator, field);
        }
        if (comparison.capture.before_complete != comparison.capture.after_complete) try self.availability_fields.append(self.allocator, "capture.full_text");
        inline for (.{ "process.foreground", "process.child", "process.last_exit", "reported_directory", "program_status" }, .{ comparison.process.foreground, comparison.process.child, comparison.process.last_exit, comparison.reported_directory, comparison.program_status }) |field, delta| {
            if (delta.availability_changed) try self.availability_fields.append(self.allocator, field);
            if (delta.changed == null) {
                try self.unknown_fields.append(self.allocator, field);
            } else if (delta.changed.?) try self.changed_fields.append(self.allocator, field);
        }
        if (self.status_state) |state| {
            if (after.program_status) |node| for (node.data.records) |record| {
                if (!equal(record.id, self.status_id) or !std.mem.eql(u8, record.state, state)) continue;
                var identical = false;
                if (self.baseline.program_status) |old| for (old.data.records) |previous| {
                    if (equal(record.id, previous.id)) {
                        identical = equal(record, previous);
                        break;
                    }
                };
                if (!identical) self.matched_status = .{
                    .record_id = self.status_id,
                    .state = state,
                    .updated_at = try self.allocator.dupe(u8, record.updated_at),
                };
                break;
            };
        }
    }
};

pub fn main() void {
    run() catch |err| {
        std.debug.print("teerex: {s}\n", .{@errorName(err)});
        std.process.exit(1);
    };
}

fn usageError(message: []const u8) noreturn {
    std.debug.print("teerex: {s}\n{s}", .{ message, observation_usage });
    std.process.exit(2);
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

fn run() !void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    const allocator = arena.allocator();
    const args = try std.process.argsAlloc(allocator);
    if (args.len == 2 and std.mem.eql(u8, args[1], "--help")) {
        try std.fs.File.stdout().writeAll(usage);
        return;
    }
    if (args.len >= 2 and std.mem.eql(u8, args[1], "run")) std.process.exit(try @import("rex_run").run(allocator, args[2..]));
    if (args.len >= 2 and std.mem.eql(u8, args[1], "offstage")) std.process.exit(try @import("rex_offstage").run(allocator, args[2..]));
    if (args.len >= 2 and std.mem.eql(u8, args[1], "doctor")) std.process.exit(try @import("rex_doctor").run(allocator, args[2..]));
    if (args.len >= 2 and std.mem.eql(u8, args[1], "jobs")) std.process.exit(try @import("rex_jobs").run(allocator, args[2..]));
    if (args.len >= 2 and std.mem.eql(u8, args[1], "adapters")) std.process.exit(try @import("rex_adapters").run(allocator, args[2..]));
    if (args.len >= 2 and std.mem.eql(u8, args[1], "maneuver-check")) std.process.exit(try @import("rex_maneuvers").run(allocator, args[2..], @This()));
    if (args.len >= 2 and std.mem.eql(u8, args[1], "filter")) std.process.exit(try @import("rex_filter").run(allocator, args[2..], @This()));
    if (args.len >= 2 and std.mem.eql(u8, args[1], "send")) std.process.exit(try @import("rex_send").run(allocator, args[2..]));
    if (args.len >= 2 and std.mem.eql(u8, args[1], "spawn")) std.process.exit(try @import("rex_spawn").run(allocator, args[2..]));
    std.process.exit(try runObservations(allocator, args[1..]));
}

/// Observation-only CLI entry point. Args start with observe, compare, or watch,
/// not the executable name; no other feature module is required by this path.
pub fn runObservations(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    if ((args.len == 1 and std.mem.eql(u8, args[0], "--help")) or
        (args.len == 2 and (std.mem.eql(u8, args[0], "observe") or std.mem.eql(u8, args[0], "compare") or std.mem.eql(u8, args[0], "watch")) and std.mem.eql(u8, args[1], "--help")))
    {
        try std.fs.File.stdout().writeAll(observation_usage);
        return 0;
    }
    if (args.len >= 1 and std.mem.eql(u8, args[0], "compare")) {
        try compare(allocator, args[1..]);
        return 0;
    }
    if (args.len >= 1 and std.mem.eql(u8, args[0], "watch")) return watch(allocator, args[1..]);
    if (args.len == 0 or !std.mem.eql(u8, args[0], "observe")) usageError("expected observe, compare, or watch");

    var socket: ?[]const u8 = null;
    var session: ?[]const u8 = null;
    var block: ?[]const u8 = null;
    var byte_limit: ?usize = null;
    var timeout: ?u64 = null;
    var i: usize = 1;
    while (i < args.len) : (i += 2) {
        if (i + 1 == args.len) usageError("every option needs a value");
        const name = args[i];
        const value = args[i + 1];
        if (std.mem.eql(u8, name, "--socket") and socket == null) {
            socket = value;
        } else if (std.mem.eql(u8, name, "--session") and session == null) {
            session = value;
        } else if (std.mem.eql(u8, name, "--block") and block == null) {
            block = value;
        } else if (std.mem.eql(u8, name, "--max-bytes") and byte_limit == null) {
            byte_limit = std.fmt.parseUnsigned(usize, value, 10) catch usageError("invalid byte limit");
        } else if (std.mem.eql(u8, name, "--timeout-ms") and timeout == null) {
            timeout = std.fmt.parseUnsigned(u64, value, 10) catch usageError("invalid observation deadline");
        } else usageError("unknown or repeated option");
    }
    const socket_path = socket orelse usageError("--socket is required");
    const session_id = session orelse usageError("--session is required");
    const block_id = block orelse usageError("--block is required");
    const max_bytes = byte_limit orelse 4096;
    const timeout_ms = timeout orelse 5000;
    if (!std.fs.path.isAbsolute(socket_path)) usageError("--socket must be an absolute Unix socket path");
    if (!fullId(session_id, "session:")) usageError("--session must be a full session:UUID, not a label or suffix");
    if (!fullId(block_id, "block:")) usageError("--block must be a full block:UUID, not a label or suffix");
    if (max_bytes < 256 or max_bytes > 65536) usageError("--max-bytes must be between 256 and 65536");
    if (timeout_ms < 100 or timeout_ms > 60000) usageError("--timeout-ms must be between 100 and 60000");
    if (builtin.os.tag != .macos and builtin.os.tag != .linux) return error.UnsupportedObservationPlatform;

    const endpoint = try std.fmt.allocPrint(allocator, "unix://{s}", .{socket_path});
    const argv = try observationArgv(allocator, endpoint, session_id, block_id, max_bytes, null);
    var env = try std.process.getEnvMap(allocator);
    for ([_][]const u8{ "REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT" }) |key| env.remove(key);
    const signals = supervised.Signals.init();
    defer signals.deinit();
    var capture: ObservationOutput = .{ .allocator = allocator };
    const result = try supervised.collect(allocator, argv, &env, timeout_ms, &capture);
    if (result.stopped) {
        std.debug.print("teerex: observation {s}; no complete observation emitted\n", .{if (result.stop_signal != 0) "cancelled" else "deadline exceeded"});
        return if (result.stop_signal != 0) 128 + result.stop_signal else 124;
    }
    if (result.term != .Exited or result.term.Exited != 0) {
        std.debug.print("teerex: Rex observation failed: {s}\n", .{std.mem.trim(u8, result.stderr, "\r\n")});
        observationTargetHint(endpoint, session_id, block_id);
        return error.ObservationCommandFailed;
    }
    const parsed = try std.json.parseFromSlice(std.json.Value, allocator, capture.bytes.items, .{});
    const packet = try observation(allocator, endpoint, session_id, block_id, max_bytes, parsed.value, result.started_at_unix_ms);
    const output = try std.json.Stringify.valueAlloc(allocator, packet, .{ .whitespace = .indent_2 });
    try std.fs.File.stdout().writeAll(output);
    try std.fs.File.stdout().writeAll("\n");
    return 0;
}

fn observation(allocator: std.mem.Allocator, endpoint: []const u8, session_id: []const u8, block_id: []const u8, max_bytes: usize, responses: std.json.Value, started_at: i64) !Observation {
    if (responses != .object) return error.InvalidRexResponse;
    const version = responses.object.get("version") orelse return error.InvalidVersionResponse;
    if (version != .object) return error.InvalidVersionResponse;
    const revision = version.object.get("api_revision") orelse return error.UnsupportedApiRevision;
    if (revision != .integer) return error.UnsupportedApiRevision;
    if (revision.integer < 10 or revision.integer > 13) {
        std.debug.print("teerex: unsupported Rex API revision {d} (accepted: 10..13)\n", .{revision.integer});
        return error.UnsupportedApiRevision;
    }
    const rex_version = version.object.get("rex_version") orelse return error.InvalidVersionResponse;
    const platform = version.object.get("platform") orelse return error.InvalidVersionResponse;
    if (rex_version != .string or platform != .string) return error.InvalidVersionResponse;

    const capture = responses.object.get("capture") orelse return error.InvalidCaptureResponse;
    if (capture != .object) return error.InvalidCaptureResponse;
    const content = capture.object.get("content") orelse return error.InvalidCaptureResponse;
    if (content != .string) return error.InvalidCaptureResponse;
    const more = capture.object.get("id");
    if (more) |id| {
        if (id != .integer or id.integer < 0) return error.InvalidCaptureResponse;
    }
    const complete = more == null;
    if (capture.object.get("eof")) |eof| {
        if (eof != .bool or eof.bool != complete) return error.InvalidCaptureResponse;
    }

    const process_method = "com.superlogical.terminal.process";
    const directory_method = "com.superlogical.terminal.pwd";
    const status_method = "com.superlogical.terminal.program_status";
    const process = try std.json.parseFromValue(ProcessEvidence, allocator, responses.object.get("process") orelse return error.InvalidProcessResponse, .{ .ignore_unknown_fields = true });
    const directory = try std.json.parseFromValue(DirectoryReport, allocator, responses.object.get("directory") orelse return error.InvalidDirectoryResponse, .{ .ignore_unknown_fields = true });
    const status = try std.json.parseFromValue(struct { records: []StatusRecord }, allocator, responses.object.get("status") orelse return error.InvalidStatusResponse, .{ .ignore_unknown_fields = true });

    var random: [16]u8 = undefined;
    std.crypto.random.bytes(&random);
    const observation_id = std.fmt.bytesToHex(random, .lower);
    return validateObservation(.{
        .schema_version = 1,
        .observation_id = try allocator.dupe(u8, &observation_id),
        .observation_started_at_unix_ms = started_at,
        .observed_at_unix_ms = std.time.milliTimestamp(),
        .atomic_snapshot = false,
        .target = .{ .server = endpoint, .session_id = session_id, .block_id = block_id },
        .source = .{ .rex_version = rex_version.string, .platform = platform.string, .api_revision = @intCast(revision.integer) },
        .capture = .{
            .scope = "screen_and_scrollback",
            .portion = "prefix",
            .max_bytes = max_bytes,
            .complete = complete,
            .content = content.string,
        },
        .process = .{
            .method = process_method,
            .basis = "rex_observation",
            .freshness = "unknown",
            .data = process.value,
        },
        .reported_directory = .{
            .method = directory_method,
            .basis = "terminal_report",
            .freshness = "unknown",
            .reported_at = null,
            .data = directory.value,
        },
        .program_status = .{
            .method = status_method,
            .basis = "program_reports",
            .freshness = "unknown",
            .data = .{ .records = status.value.records },
        },
    });
}

fn readObservation(allocator: std.mem.Allocator, path: []const u8) !Observation {
    const bytes = try std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024);
    return parseObservation(allocator, bytes);
}

fn parseObservation(allocator: std.mem.Allocator, bytes: []const u8) !Observation {
    const parsed = try std.json.parseFromSlice(Observation, allocator, bytes, .{ .ignore_unknown_fields = true });
    return validateObservation(parsed.value);
}

pub fn validateObservation(packet: Observation) !Observation {
    if (packet.schema_version != 1) return error.UnsupportedObservationVersion;
    if (packet.source.api_revision < 10 or packet.source.api_revision > 13) {
        std.debug.print("teerex: unsupported Rex API revision {d} (accepted: 10..13)\n", .{packet.source.api_revision});
        return error.UnsupportedObservationVersion;
    }
    if (packet.observation_id.len == 0 or !fullId(packet.target.session_id, "session:") or !fullId(packet.target.block_id, "block:")) return error.InvalidObservationIdentity;
    if (!std.mem.eql(u8, packet.capture.scope, "screen_and_scrollback") or !std.mem.eql(u8, packet.capture.portion, "prefix")) return error.UnsupportedCaptureScope;
    if (packet.capture.max_bytes < 256 or packet.capture.max_bytes > 65536) return error.InvalidCaptureLimit;
    var buffer: [256]u8 = undefined;
    var count: std.Io.Writer.Discarding = .init(&buffer);
    try std.json.Stringify.value(packet.capture.content, .{}, &count.writer);
    if (count.fullCount() > packet.capture.max_bytes) return error.CaptureExceedsLimit;
    inline for (.{ "process", "reported_directory", "program_status" }, .{ "process", "pwd", "program_status" }, .{ "rex_observation", "terminal_report", "program_reports" }) |field, method, basis| {
        if (@field(packet, field)) |node| {
            if (!std.mem.eql(u8, node.method, "com.superlogical.terminal." ++ method) or !std.mem.eql(u8, node.basis, basis) or !std.mem.eql(u8, node.freshness, "unknown")) return error.UnsupportedEvidenceProvenance;
        }
    }
    if (packet.program_status) |node| {
        const records = node.data.records;
        std.mem.sort(StatusRecord, records, {}, struct {
            fn lessThan(_: void, a: StatusRecord, b: StatusRecord) bool {
                return std.mem.order(u8, a.id orelse "", b.id orelse "") == .lt;
            }
        }.lessThan);
        for (records, 0..) |record, index| {
            if (index > 0 and std.mem.eql(u8, record.id orelse "", records[index - 1].id orelse "")) return error.DuplicateStatusId;
        }
    }
    return packet;
}

// Typed evidence contains structs, nullable values and slices. Compare contents,
// not slice addresses (std.meta.eql), without allocating two JSON copies per field.
fn equal(before: anytype, after: @TypeOf(before)) bool {
    switch (@typeInfo(@TypeOf(before))) {
        .@"struct" => |info| {
            inline for (info.fields) |field| {
                if (!equal(@field(before, field.name), @field(after, field.name))) return false;
            }
            return true;
        },
        .optional => {
            if (before == null or after == null) return (before == null) == (after == null);
            return equal(before.?, after.?);
        },
        .pointer => |info| {
            if (info.size != .slice) @compileError("evidence pointers must be slices");
            if (info.child == u8) return std.mem.eql(u8, before, after);
            if (before.len != after.len) return false;
            for (before, after) |a, b| if (!equal(a, b)) return false;
            return true;
        },
        else => return before == after,
    }
}

fn change(before: anytype, after: @TypeOf(before)) Change {
    return .{
        .before_available = before != null,
        .after_available = after != null,
        .availability_changed = (before != null) != (after != null),
        .changed = if (before != null and after != null)
            !equal(before.?, after.?)
        else
            null,
    };
}

fn compare(allocator: std.mem.Allocator, args: []const []const u8) !void {
    var before_path: ?[]const u8 = null;
    var after_path: ?[]const u8 = null;
    var i: usize = 0;
    while (i < args.len) : (i += 2) {
        if (i + 1 == args.len) usageError("every comparison option needs a value");
        if (std.mem.eql(u8, args[i], "--before") and before_path == null) {
            before_path = args[i + 1];
        } else if (std.mem.eql(u8, args[i], "--after") and after_path == null) {
            after_path = args[i + 1];
        } else usageError("unknown or repeated comparison option");
    }
    const before_file = before_path orelse usageError("--before is required");
    const after_file = after_path orelse usageError("--after is required");
    const before = try readObservation(allocator, before_file);
    const after = try readObservation(allocator, after_file);
    const output = try std.json.Stringify.valueAlloc(allocator, try compareObservations(before, after), .{ .whitespace = .indent_2 });
    try std.fs.File.stdout().writeAll(output);
    try std.fs.File.stdout().writeAll("\n");
}

pub fn compareObservations(before: Observation, after: Observation) !Comparison {
    if (!equal(before.target, after.target)) return error.DifferentObservationTargets;
    if (!equal(before.source, after.source)) return error.DifferentObservationSources;

    const both_complete = before.capture.complete and after.capture.complete;
    const text_comparable = both_complete or before.capture.max_bytes == after.capture.max_bytes;
    const text_changed = !std.mem.eql(u8, before.capture.content, after.capture.content);
    const before_foreground = if (before.process) |node| node.data.foreground else null;
    const after_foreground = if (after.process) |node| node.data.foreground else null;
    const before_directory: ?DirectoryReport = if (before.reported_directory) |node| (if (node.data.pwd != null) node.data else null) else null;
    const after_directory: ?DirectoryReport = if (after.reported_directory) |node| (if (node.data.pwd != null) node.data else null) else null;
    return .{
        .before_observation_id = before.observation_id,
        .after_observation_id = after.observation_id,
        .target = before.target,
        .source = before.source,
        .capture = .{
            .before_complete = before.capture.complete,
            .after_complete = after.capture.complete,
            .before_max_bytes = before.capture.max_bytes,
            .after_max_bytes = after.capture.max_bytes,
            .captured_text_changed = if (text_comparable) @as(?bool, text_changed) else null,
            .full_text_changed = if (both_complete) @as(?bool, text_changed) else null,
        },
        .process = .{
            .foreground = change(before_foreground, after_foreground),
            .child = change(if (before.process) |node| node.data.child else null, if (after.process) |node| node.data.child else null),
            .last_exit = change(if (before.process) |node| node.data.last_exit else null, if (after.process) |node| node.data.last_exit else null),
        },
        .reported_directory = change(before_directory, after_directory),
        .program_status = change(if (before.program_status) |node| @as(?@TypeOf(node.data), node.data) else null, if (after.program_status) |node| @as(?@TypeOf(node.data), node.data) else null),
    };
}

fn watch(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    var socket: ?[]const u8 = null;
    var session: ?[]const u8 = null;
    var block: ?[]const u8 = null;
    var baseline_path: ?[]const u8 = null;
    var timeout: ?u64 = null;
    var interval: ?u64 = null;
    var status_state: ?[]const u8 = null;
    var status_id: ?[]const u8 = null;
    var i: usize = 0;
    while (i < args.len) : (i += 2) {
        if (i + 1 == args.len) usageError("every watch option needs a value");
        const name = args[i];
        const value = args[i + 1];
        if (std.mem.eql(u8, name, "--socket") and socket == null) {
            socket = value;
        } else if (std.mem.eql(u8, name, "--session") and session == null) {
            session = value;
        } else if (std.mem.eql(u8, name, "--block") and block == null) {
            block = value;
        } else if (std.mem.eql(u8, name, "--baseline") and baseline_path == null) {
            baseline_path = value;
        } else if (std.mem.eql(u8, name, "--timeout-ms") and timeout == null) {
            timeout = std.fmt.parseUnsigned(u64, value, 10) catch usageError("invalid watch deadline");
        } else if (std.mem.eql(u8, name, "--interval-ms") and interval == null) {
            interval = std.fmt.parseUnsigned(u64, value, 10) catch usageError("invalid watch interval");
        } else if (std.mem.eql(u8, name, "--status-state") and status_state == null) {
            status_state = value;
        } else if (std.mem.eql(u8, name, "--status-id") and status_id == null) {
            status_id = value;
        } else usageError("unknown or repeated watch option");
    }
    const socket_path = socket orelse usageError("--socket is required");
    const session_id = session orelse usageError("--session is required");
    const block_id = block orelse usageError("--block is required");
    const baseline_file = baseline_path orelse usageError("--baseline is required");
    const timeout_ms = timeout orelse usageError("--timeout-ms is required");
    const interval_ms = interval orelse 250;
    if (status_id) |id| {
        if (status_state == null or id.len == 0 or id.len > 1024) usageError("--status-id needs a status condition and a nonempty ID of at most 1024 bytes");
    }
    if (status_state) |state| {
        var supported = false;
        inline for (.{ "idle", "working", "done", "blocked", "error" }) |known| {
            supported = supported or std.mem.eql(u8, state, known);
        }
        if (!supported) usageError("--status-state must be idle, working, done, blocked, or error");
    }
    if (!std.fs.path.isAbsolute(socket_path) or !fullId(session_id, "session:") or !fullId(block_id, "block:")) usageError("watch needs an absolute socket and full session/block IDs");
    if (timeout_ms < 100 or timeout_ms > 60000 or interval_ms < 50 or interval_ms > 5000) usageError("watch deadline or interval out of range");
    if (builtin.os.tag != .macos and builtin.os.tag != .linux) return error.UnsupportedObservationPlatform;

    const baseline = try readObservation(allocator, baseline_file);
    const endpoint = try std.fmt.allocPrint(allocator, "unix://{s}", .{socket_path});
    if (!std.mem.eql(u8, baseline.target.server, endpoint) or !std.mem.eql(u8, baseline.target.session_id, session_id) or !std.mem.eql(u8, baseline.target.block_id, block_id)) return error.DifferentObservationTargets;
    // One explicitly attached Lua connection runs the same five supported reads.
    // Supervise it directly; no self-subprocess or observation JSON round trip.
    const argv = try observationArgv(allocator, endpoint, session_id, block_id, baseline.capture.max_bytes, interval_ms);
    var env = try std.process.getEnvMap(allocator);
    for ([_][]const u8{ "REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT" }) |key| env.remove(key);
    const signals = supervised.Signals.init();
    defer signals.deinit();
    var timer = try std.time.Timer.start();
    const started_at = std.time.milliTimestamp();
    var collector: WatchCollector = .{ .allocator = allocator, .baseline = baseline, .timer = &timer, .timeout_ms = timeout_ms, .status_state = status_state, .status_id = status_id };
    defer if (collector.last_after_id) |id| std.heap.page_allocator.free(id);
    const result: ?supervised.Result = supervised.collect(allocator, argv, &env, timeout_ms, &collector) catch |err| blk: {
        collector.failure = if (err == error.FileNotFound) "ObservationCommandFailed" else @errorName(err);
        break :blk null;
    };
    if (result) |r| {
        if (!r.stopped and !collector.isComplete()) {
            std.debug.print("teerex watch: observation failed: {s}\n", .{std.mem.trim(u8, r.stderr, "\r\n")});
            observationTargetHint(endpoint, session_id, block_id);
            collector.failure = if (collector.pending.items.len != 0 and r.term == .Exited and r.term.Exited == 0) "InvalidObservationFrame" else "ObservationCommandFailed";
        }
    }
    const stop_signal = supervised.requestedSignal();
    const satisfied = collector.satisfied();
    const outcome: []const u8 = if (stop_signal != 0) "cancel_requested" else if (collector.failure != null) "observation_failed" else if (collector.matched_status != null) "status_report_matched" else if (satisfied) "change_observed" else "deadline_exceeded";
    var random: [16]u8 = undefined;
    std.crypto.random.bytes(&random);
    const id = std.fmt.bytesToHex(random, .lower);
    const output = try std.json.Stringify.valueAlloc(allocator, .{
        .schema_version = 1,
        .kind = "observation_wait",
        .wait_id = id[0..],
        .baseline_observation_id = baseline.observation_id,
        .target = baseline.target,
        .baseline_source = baseline.source,
        .started_at_unix_ms = started_at,
        .elapsed_ms = timer.read() / std.time.ns_per_ms,
        .limits = .{ .timeout_ms = timeout_ms, .interval_after_collection_ms = interval_ms, .max_encoded_content_bytes = baseline.capture.max_bytes, .max_sample_bytes = 1024 * 1024 },
        .condition = if (status_state) |state| @as(?struct { record_id: ?[]const u8, state: []const u8, requirement: []const u8 }, .{
            .record_id = status_id,
            .state = state,
            .requirement = "different_report_evidence_from_baseline",
        }) else null,
        .matched_status_report = collector.matched_status,
        .outcome = outcome,
        .cancellation_signal = if (stop_signal == 0) @as(?u8, null) else stop_signal,
        .failure_reason = collector.failure,
        .collector_invocations = 1,
        .collection_attempts = collector.attempts,
        .observations_compared = collector.compared,
        .last_comparison_elapsed_ms = collector.last_compared_at,
        .last_sample_interrupted = if (result) |r| r.stopped and collector.collecting else false,
        .last_sample_discarded_at_deadline = collector.late,
        .changed_fields = if (collector.last_comparison == null) @as(?[]const []const u8, null) else collector.changed_fields.items,
        .availability_changed_fields = if (collector.last_comparison == null) @as(?[]const []const u8, null) else collector.availability_fields.items,
        .unknown_fields = if (collector.last_comparison == null) @as(?[]const []const u8, null) else collector.unknown_fields.items,
        .last_comparison = collector.last_comparison,
        .last_collection_cleanup = if (result) |r| @as(?struct { group_sigterm: ?supervised.GroupSignal, group_sigkill: ?supervised.GroupSignal }, .{ .group_sigterm = r.group_term, .group_sigkill = r.group_kill }) else null,
        .cleanup_scope = "collection_process_group_not_observed_terminal",
        .detached_descendants = "not_covered",
        .all_descendants_verified_gone = false,
        .interpretation = "none",
    }, .{ .whitespace = .indent_2 });
    try std.fs.File.stdout().writeAll(output);
    try std.fs.File.stdout().writeAll("\n");
    return if (stop_signal != 0) 128 + stop_signal else if (collector.failure != null) 1 else if (satisfied) 0 else 124;
}

fn observationTargetHint(endpoint: []const u8, session: []const u8, block: []const u8) void {
    std.debug.print("teerex: requested observation target: server={s} session={s} block={s}\n", .{ endpoint, session, block });
    std.debug.print("teerex: compare using the same trusted PATH rex with explicit --server, not only REX_SERVER; observation ignores REX_SERVER/REX_SESSION/REX_BLOCK/REX_CLIENT. No alternate host or focus target was requested by teerex.\n", .{});
}

fn observationArgv(allocator: std.mem.Allocator, endpoint: []const u8, session: []const u8, block: []const u8, max_bytes: usize, interval_ms: ?u64) ![]const []const u8 {
    // Scope also attaches the Lua connection; explicit IDs alone do not attach it.
    const request = try std.json.Stringify.valueAlloc(allocator, .{ .session_id = session, .block_id = block, .max_bytes = max_bytes, .interval_ms = interval_ms }, .{});
    return allocator.dupe([]const u8, &.{ "rex", "--autostart=false", "--server", endpoint, "--timeout", "3s", "--color", "never", "do", "--session", session, "--block", block, "-e", @embedFile("collect.lua"), "--args", request });
}
