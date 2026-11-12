const std = @import("std");
const core = @import("main.zig");

const Edge = struct { from: []const u8, to: []const u8 };
const Library = struct {
    schema_version: u32,
    kind: []const u8,
    id: []const u8,
    definitions: []core.Definition,
    transitions: []Edge,
};
const Loaded = struct { library: Library, sha256: [64]u8 };
const Outcome = enum { matched_evidence, mismatch, unknown, ambiguous };
const DefinitionResult = struct { definition_id: []const u8, outcome: core.Outcome, checks: [5]core.Check };
const Recognition = struct {
    outcome: Outcome,
    selected_definition_id: ?[]const u8,
    matched_definition_ids: []const []const u8,
    unknown_definition_ids: []const []const u8,
    definitions: []DefinitionResult,
};
const Metadata = struct {
    id: []const u8,
    provenance: @FieldType(core.Definition, "provenance"),
    compatibility: @FieldType(core.Definition, "compatibility"),
    stop_before: []const u8,
};
const Receipt = struct {
    observation_id: []const u8,
    file_sha256: []const u8,
    observation_started_at_unix_ms: i64,
    observed_at_unix_ms: i64,
    target: core.Target,
    source: @FieldType(core.Definition, "compatibility"),
};
const boundaries = .{
    .recognition_scope = "saved_observation_endpoints",
    .freshness = "unknown",
    .atomic_snapshot = false,
    .execution = "not_implemented",
    .input_sent = false,
    .approval_granted = false,
    .authored_text_authority = "unauthenticated_data",
    .stop_enforcement = "no_execution_path",
};

fn readLibrary(allocator: std.mem.Allocator, path: []const u8) !Loaded {
    const bytes = try std.fs.cwd().readFileAlloc(allocator, path, 1024 * 1024);
    const parsed = try std.json.parseFromSlice(Library, allocator, bytes, .{});
    const library = parsed.value;
    if (library.schema_version != 1 or !std.mem.eql(u8, library.kind, "rex_maneuver_library")) return error.UnsupportedManeuverLibrary;
    if (library.id.len == 0 or library.id.len > 128 or library.definitions.len == 0 or
        library.definitions.len > 16 or library.transitions.len > 64) return error.InvalidManeuverLibrary;
    for (library.definitions, 0..) |definition, index| {
        try core.validateDefinition(definition);
        for (library.definitions[0..index]) |previous| {
            if (std.mem.eql(u8, previous.id, definition.id)) return error.DuplicateDefinitionId;
        }
    }
    for (library.transitions, 0..) |edge, index| {
        const from = findDefinition(library, edge.from) orelse return error.UnknownTransitionEndpoint;
        const to = findDefinition(library, edge.to) orelse return error.UnknownTransitionEndpoint;
        if (std.mem.eql(u8, edge.from, edge.to)) return error.SelfTransitionUnsupported;
        if (!std.mem.eql(u8, from.compatibility.rex_version, to.compatibility.rex_version) or
            !std.mem.eql(u8, from.compatibility.platform, to.compatibility.platform)) return error.IncompatibleTransitionSources;
        for (library.transitions[0..index]) |previous| {
            if (std.mem.eql(u8, previous.from, edge.from) and std.mem.eql(u8, previous.to, edge.to)) return error.DuplicateTransition;
        }
    }
    return .{ .library = library, .sha256 = core.digest(bytes) };
}

fn findDefinition(library: Library, id: []const u8) ?core.Definition {
    for (library.definitions) |definition| if (std.mem.eql(u8, definition.id, id)) return definition;
    return null;
}

fn metadata(allocator: std.mem.Allocator, library: Library) ![]Metadata {
    const result = try allocator.alloc(Metadata, library.definitions.len);
    for (library.definitions, result) |definition, *entry| entry.* = .{
        .id = definition.id,
        .provenance = definition.provenance,
        .compatibility = definition.compatibility,
        .stop_before = definition.stop_before,
    };
    return result;
}

fn recognize(allocator: std.mem.Allocator, library: Library, packet: anytype) !Recognition {
    const results = try allocator.alloc(DefinitionResult, library.definitions.len);
    const matched = try allocator.alloc([]const u8, library.definitions.len);
    const unknown = try allocator.alloc([]const u8, library.definitions.len);
    var matched_count: usize = 0;
    var unknown_count: usize = 0;
    for (library.definitions, results) |definition, *result| {
        const assessment = core.assess(definition, packet);
        result.* = .{ .definition_id = definition.id, .outcome = assessment.outcome, .checks = assessment.checks };
        switch (assessment.outcome) {
            .matched_evidence => {
                matched[matched_count] = definition.id;
                matched_count += 1;
            },
            .unknown => {
                unknown[unknown_count] = definition.id;
                unknown_count += 1;
            },
            .mismatch => {},
        }
    }
    // One positive candidate is not unique evidence when another cannot be ruled out.
    const outcome: Outcome = if (matched_count > 1) .ambiguous else if (unknown_count > 0) .unknown else if (matched_count == 1) .matched_evidence else .mismatch;
    return .{
        .outcome = outcome,
        .selected_definition_id = if (outcome == .matched_evidence) matched[0] else null,
        .matched_definition_ids = matched[0..matched_count],
        .unknown_definition_ids = unknown[0..unknown_count],
        .definitions = results,
    };
}

fn receipt(allocator: std.mem.Allocator, packet: anytype, bytes: []const u8) !Receipt {
    const hash = core.digest(bytes);
    return .{
        .observation_id = packet.observation_id,
        .file_sha256 = try allocator.dupe(u8, &hash),
        .observation_started_at_unix_ms = packet.observation_started_at_unix_ms,
        .observed_at_unix_ms = packet.observed_at_unix_ms,
        .target = .{ .server = packet.target.server, .session_id = packet.target.session_id, .block_id = packet.target.block_id },
        .source = .{ .rex_version = packet.source.rex_version, .platform = packet.source.platform, .api_revision = packet.source.api_revision },
    };
}

fn write(allocator: std.mem.Allocator, value: anytype) !void {
    const output = try std.json.Stringify.valueAlloc(allocator, value, .{ .whitespace = .indent_2 });
    try std.fs.File.stdout().writeAll(output);
    try std.fs.File.stdout().writeAll("\n");
}

pub fn catalog(allocator: std.mem.Allocator, path: []const u8) !u8 {
    const loaded = try readLibrary(allocator, path);
    try write(allocator, .{
        .schema_version = 1,
        .kind = "maneuver_library_catalog",
        .library_id = loaded.library.id,
        .library_sha256 = loaded.sha256[0..],
        .definitions = try metadata(allocator, loaded.library),
        .transitions = loaded.library.transitions,
        .boundaries = boundaries,
    });
    return 0;
}

pub fn run(allocator: std.mem.Allocator, path: []const u8, observation_path: []const u8, before_path: ?[]const u8, target: core.Target, comptime observations: type) !u8 {
    const loaded = try readLibrary(allocator, path);
    const bytes = try std.fs.cwd().readFileAlloc(allocator, observation_path, 1024 * 1024);
    const packet = try core.parseObservation(allocator, bytes, target, 13, observations);
    const after = try recognize(allocator, loaded.library, packet);
    const definitions = try metadata(allocator, loaded.library);
    if (before_path) |first| {
        const before_bytes = try std.fs.cwd().readFileAlloc(allocator, first, 1024 * 1024);
        const before_packet = try core.parseObservation(allocator, before_bytes, target, 13, observations);
        const before = try recognize(allocator, loaded.library, before_packet);
        var outcome: enum { declared_edge_evidence, mismatch, unknown, ambiguous } = .unknown;
        var reason: []const u8 = "endpoint_evidence_unknown";
        var edge: ?Edge = null;
        var declared: ?bool = null;
        if (before.outcome == .mismatch or after.outcome == .mismatch) {
            outcome = .mismatch;
            reason = "unrecognized_endpoint";
        } else if (before.outcome == .ambiguous or after.outcome == .ambiguous) {
            outcome = .ambiguous;
            reason = "ambiguous_endpoint";
        } else if (before.selected_definition_id != null and after.selected_definition_id != null) {
            edge = .{ .from = before.selected_definition_id.?, .to = after.selected_definition_id.? };
            declared = false;
            for (loaded.library.transitions) |expected| {
                if (std.mem.eql(u8, expected.from, edge.?.from) and std.mem.eql(u8, expected.to, edge.?.to)) {
                    declared = true;
                    break;
                }
            }
            if (!declared.?) {
                outcome = .mismatch;
                reason = "undeclared_endpoint_relation";
            } else if (std.mem.eql(u8, before_packet.observation_id, packet.observation_id)) {
                reason = "reused_observation_identity";
            } else {
                outcome = .declared_edge_evidence;
                reason = "caller_ordered_endpoints_match_declared_relation";
            }
        }
        try write(allocator, .{
            .schema_version = 1,
            .kind = "maneuver_transition_check",
            .library_id = loaded.library.id,
            .library_sha256 = loaded.sha256[0..],
            .outcome = outcome,
            .reason = reason,
            .before = try receipt(allocator, before_packet, before_bytes),
            .after = try receipt(allocator, packet, bytes),
            .before_recognition = before,
            .after_recognition = after,
            .selected_edge = edge,
            .declared_edge_present = declared,
            .definitions = definitions,
            .sample_order = "caller_supplied",
            .process_continuity = "not_verified",
            .intermediate_states = "not_observed",
            .boundaries = boundaries,
        });
        return switch (outcome) {
            .declared_edge_evidence => 0,
            .mismatch => 3,
            .unknown => 4,
            .ambiguous => 5,
        };
    }
    try write(allocator, .{
        .schema_version = 1,
        .kind = "maneuver_library_check",
        .library_id = loaded.library.id,
        .library_sha256 = loaded.sha256[0..],
        .observation = try receipt(allocator, packet, bytes),
        .recognition = after,
        .definitions = definitions,
        .boundaries = boundaries,
    });
    return switch (after.outcome) {
        .matched_evidence => 0,
        .mismatch => 3,
        .unknown => 4,
        .ambiguous => 5,
    };
}
