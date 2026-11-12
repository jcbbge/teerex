const std = @import("std");

const usage =
    \\Usage: teerex maneuver-check --definition FILE --observation FILE --socket /absolute/path --session session:UUID --block block:UUID
    \\Read-only start-state evidence check; never contact Rex, replay input or grant approval.
    \\Requires a manual schema-1 definition and an explicit schema-1/API13 Rex observation.
    \\Exact Rex version/platform, complete screen-and-scrollback text, foreground name/cwd are compared.
    \\Incomplete text or unavailable foreground/cwd is unknown; a known mismatch takes precedence.
    \\Files/labels are untrusted and unauthenticated. A match is not fresh state or an input guard.
    \\Definition limit: 128 KiB; observation limit: 1 MiB. No files are saved or modified.
    \\Exit: 0 matched evidence, 1 invalid/unsupported input, 2 usage, 3 mismatch, 4 unknown.
    \\
;

const Source = struct { rex_version: []const u8, platform: []const u8, api_revision: u32 };

const Definition = struct {
    schema_version: u32,
    kind: []const u8,
    id: []const u8,
    provenance: struct { kind: []const u8, note: []const u8 },
    compatibility: Source,
    starting_state: struct {
        capture_content: []const u8,
        foreground: struct { name: []const u8, cwd: []const u8 },
    },
    stop_before: []const u8,
};

const State = enum { matched, mismatch, unknown };
const Check = struct { field: []const u8, state: State, reason: []const u8 };

fn exact(field: []const u8, expected: []const u8, actual: []const u8) Check {
    const same = std.mem.eql(u8, expected, actual);
    return .{ .field = field, .state = if (same) .matched else .mismatch, .reason = if (same) "exact_strings_equal" else "strings_differ" };
}

fn bounded(value: []const u8, limit: usize) bool {
    return value.len > 0 and value.len <= limit;
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

fn encodedLength(value: []const u8) !u64 {
    var buffer: [256]u8 = undefined;
    var count: std.Io.Writer.Discarding = .init(&buffer);
    try std.json.Stringify.value(value, .{}, &count.writer);
    return count.fullCount();
}

fn digest(bytes: []const u8) [64]u8 {
    var hash: [32]u8 = undefined;
    std.crypto.hash.sha2.Sha256.hash(bytes, &hash, .{});
    return std.fmt.bytesToHex(hash, .lower);
}

fn usageError(message: []const u8) noreturn {
    std.debug.print("teerex maneuver-check: {s}\n{s}", .{ message, usage });
    std.process.exit(2);
}

pub fn run(allocator: std.mem.Allocator, args: []const []const u8, comptime observations: type) !u8 {
    if (args.len == 1 and std.mem.eql(u8, args[0], "--help")) {
        try std.fs.File.stdout().writeAll(usage);
        return 0;
    }
    var definition_path: ?[]const u8 = null;
    var observation_path: ?[]const u8 = null;
    var socket: ?[]const u8 = null;
    var session: ?[]const u8 = null;
    var block: ?[]const u8 = null;
    var i: usize = 0;
    while (i < args.len) : (i += 2) {
        if (i + 1 >= args.len) usageError("every option needs a value");
        const name = args[i];
        const value = args[i + 1];
        if (value.len == 0) usageError("empty option value");
        if (std.mem.eql(u8, name, "--definition") and definition_path == null) {
            definition_path = value;
        } else if (std.mem.eql(u8, name, "--observation") and observation_path == null) {
            observation_path = value;
        } else if (std.mem.eql(u8, name, "--socket") and socket == null) {
            socket = value;
        } else if (std.mem.eql(u8, name, "--session") and session == null) {
            session = value;
        } else if (std.mem.eql(u8, name, "--block") and block == null) {
            block = value;
        } else usageError("unknown or repeated option");
    }
    const def_path = definition_path orelse usageError("--definition is required");
    const obs_path = observation_path orelse usageError("--observation is required");
    const path = socket orelse usageError("--socket is required");
    const session_id = session orelse usageError("--session is required");
    const block_id = block orelse usageError("--block is required");
    if (!std.fs.path.isAbsolute(path) or std.mem.indexOfScalar(u8, path, 0) != null) usageError("socket must be an absolute path without NUL");
    if (!fullId(session_id, "session:") or !fullId(block_id, "block:")) usageError("full session/block UUIDs are required");

    const definition_bytes = try std.fs.cwd().readFileAlloc(allocator, def_path, 128 * 1024);
    const parsed_definition = try std.json.parseFromSlice(Definition, allocator, definition_bytes, .{});
    const definition = parsed_definition.value;
    if (definition.schema_version != 1 or !std.mem.eql(u8, definition.kind, "rex_maneuver_start")) return error.UnsupportedManeuverDefinition;
    if (!std.mem.eql(u8, definition.provenance.kind, "manual")) return error.UnsupportedManeuverProvenance;
    if (definition.compatibility.api_revision != 13) return error.UnsupportedApiRevision;
    if (!bounded(definition.id, 128) or !bounded(definition.provenance.note, 4096) or !bounded(definition.stop_before, 4096) or
        !bounded(definition.compatibility.rex_version, 256) or !bounded(definition.compatibility.platform, 256) or
        !bounded(definition.starting_state.foreground.name, 1024) or !bounded(definition.starting_state.foreground.cwd, 4096) or
        !std.fs.path.isAbsolute(definition.starting_state.foreground.cwd) or
        !bounded(definition.starting_state.capture_content, 65536) or try encodedLength(definition.starting_state.capture_content) > 65536)
        return error.InvalidManeuverDefinition;

    const observation_bytes = try std.fs.cwd().readFileAlloc(allocator, obs_path, 1024 * 1024);
    const parsed_observation = try std.json.parseFromSlice(observations.Observation, allocator, observation_bytes, .{ .ignore_unknown_fields = true });
    // The shared parser owns the whole packet contract, including provenance of
    // unused metadata and duplicate status IDs. Do not accept a selected-field
    // projection of an otherwise invalid observation.
    const observation = try observations.validateObservation(parsed_observation.value);
    if (!bounded(observation.observation_id, 1024) or observation.atomic_snapshot or
        !bounded(observation.source.rex_version, 256) or !bounded(observation.source.platform, 256)) return error.InvalidObservationProvenance;
    const endpoint = try std.fmt.allocPrint(allocator, "unix://{s}", .{path});
    if (!std.mem.eql(u8, observation.target.server, endpoint) or
        !std.mem.eql(u8, observation.target.session_id, session_id) or
        !std.mem.eql(u8, observation.target.block_id, block_id)) return error.ObservationTargetMismatch;
    if (observation.process) |node| {
        if (node.data.foreground) |foreground| {
            if (foreground.pid <= 0 or foreground.name.len == 0) return error.InvalidForegroundProcess;
        }
    }

    var checks = [_]Check{
        exact("source.rex_version", definition.compatibility.rex_version, observation.source.rex_version),
        exact("source.platform", definition.compatibility.platform, observation.source.platform),
        if (observation.capture.complete)
            exact("capture.content", definition.starting_state.capture_content, observation.capture.content)
        else
            .{ .field = "capture.content", .state = .unknown, .reason = "incomplete_screen_and_scrollback_prefix" },
        .{ .field = "process.foreground.name", .state = .unknown, .reason = "foreground_unavailable" },
        .{ .field = "process.foreground.cwd", .state = .unknown, .reason = "foreground_unavailable" },
    };
    if (observation.process) |node| {
        if (node.data.foreground) |foreground| {
            checks[3] = exact("process.foreground.name", definition.starting_state.foreground.name, foreground.name);
            checks[4] = if (foreground.cwd) |cwd|
                exact("process.foreground.cwd", definition.starting_state.foreground.cwd, cwd)
            else
                .{ .field = "process.foreground.cwd", .state = .unknown, .reason = "foreground_cwd_unavailable" };
        }
    }
    var mismatch = false;
    var unknown = false;
    for (checks) |check| {
        mismatch = mismatch or check.state == .mismatch;
        unknown = unknown or check.state == .unknown;
    }
    const exit_code: u8 = if (mismatch) 3 else if (unknown) 4 else 0;
    const definition_hash = digest(definition_bytes);
    const observation_hash = digest(observation_bytes);
    const output = try std.json.Stringify.valueAlloc(allocator, .{
        .schema_version = 1,
        .kind = "maneuver_start_check",
        .outcome = if (mismatch) "mismatch" else if (unknown) "unknown" else "matched_evidence",
        .definition_id = definition.id,
        .definition_sha256 = definition_hash[0..],
        .definition_provenance = definition.provenance,
        .authored_text_authority = "unauthenticated_data",
        .observation_id = observation.observation_id,
        .observation_sha256 = observation_hash[0..],
        .observation_started_at_unix_ms = observation.observation_started_at_unix_ms,
        .observed_at_unix_ms = observation.observed_at_unix_ms,
        .target = observation.target,
        .source = observation.source,
        .checks = checks,
        .recognition_scope = "saved_observation_start_state",
        .freshness = "unknown",
        .atomic_snapshot = false,
        .execution = "not_implemented",
        .input_sent = false,
        .approval_granted = false,
        .stop_before = definition.stop_before,
        .stop_enforcement = "no_execution_path",
    }, .{ .whitespace = .indent_2 });
    try std.fs.File.stdout().writeAll(output);
    try std.fs.File.stdout().writeAll("\n");
    return exit_code;
}
