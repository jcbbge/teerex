const std = @import("std");

const usage =
    \\Usage: teerex filter --sample FILE --sample FILE [--sample FILE ...]
    \\       teerex filter cache put|get|purge --help
    \\Opt in: --view progress-v1 or --view-rules FILE; exclusive, declared cosmetic spans only.
    \\Cosmetic omissions carry exact reconstruction spans; raw adjacent comparisons remain.
    \\Filter 2..128 explicit Rex observation files in supplied order, without contacting Rex.
    \\Only identical returned evidence is omitted; packet IDs/client times are not evidence changes.
    \\Every text, process, directory, status and provenance change remains visible. No cosmetic view unless --view/--view-rules is given.
    \\Baseline, changes and the latest checkpoint retain observations and adjacent comparisons as NDJSON.
    \\Equal partial prefixes/missing fields remain unknown, not full-screen stability or completion.
    \\Files must be regular files, at most 1 MiB each and 16 MiB combined. No files are written.
    \\Output may contain secrets; it is escaped, NOT redacted. Save/export only deliberately.
    \\Require exit 0 AND the final processed summary; earlier lines alone are not a complete result.
    \\Exit: 0 processed, 1 file/evidence/output error, 2 usage. Plain --sample saves nothing.
    \\The separate cache commands require explicit private storage/consent; see filter cache --help.
    \\
;

const file_limit = 1024 * 1024;
const total_limit = 16 * 1024 * 1024;

fn usageError(message: []const u8) u8 {
    std.debug.print("teerex: {s}\n{s}", .{ message, usage });
    return 2;
}

fn writeJson(allocator: std.mem.Allocator, value: anytype) !void {
    const bytes = try std.json.Stringify.valueAlloc(allocator, value, .{});
    defer allocator.free(bytes);
    try std.fs.File.stdout().writeAll(bytes);
    try std.fs.File.stdout().writeAll("\n");
}

// The integration owner supplies the shipped observation contract. There is no
// second Rex adapter, alternate schema or private completion/state classifier.
pub fn run(allocator: std.mem.Allocator, args: []const []const u8, comptime observation: type) !u8 {
    if (args.len > 0 and std.mem.eql(u8, args[0], "cache")) return @import("cache.zig").run(allocator, args[1..], observation);
    if (args.len == 1 and std.mem.eql(u8, args[0], "--help")) {
        try std.fs.File.stdout().writeAll(usage);
        return 0;
    }
    var view_options: observation.presentation.Options = .{};
    var paths: std.ArrayList([]const u8) = .empty;
    var i: usize = 0;
    while (i < args.len) : (i += 2) {
        if (i + 1 == args.len) return usageError("every option requires a value");
        if (view_options.set(args[i], args[i + 1])) continue;
        if (!std.mem.eql(u8, args[i], "--sample") or args[i + 1].len == 0) return usageError("expected --sample FILE");
        try paths.append(allocator, args[i + 1]);
    }
    const rules = try view_options.load(allocator);
    if (paths.items.len < 2 or paths.items.len > 128) return usageError("provide 2..128 --sample FILE pairs");
    var reference_arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer reference_arena.deinit();
    var reference: ?observation.Observation = null;
    var reference_without_text: []const u8 = "";
    var cosmetic_repeats: usize = 0;
    var repeat_omissions: usize = 0;
    var payload_bytes_emitted: usize = 0;
    var previous_arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer previous_arena.deinit();
    var current_arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer current_arena.deinit();
    var previous: ?observation.Observation = null;
    var previous_normalized: []const u8 = "";
    var input_bytes: usize = 0;
    var emitted: usize = 0;
    var repeats: usize = 0;
    var omitted: usize = 0;
    var evidence_sample_index: usize = 0;
    const samples = paths.items.len;

    for (0..samples) |index| {
        const sample_allocator = current_arena.allocator();
        // Nonblocking open lets us reject a FIFO without waiting for a writer.
        const file: std.fs.File = .{ .handle = try std.posix.open(paths.items[index], .{
            .ACCMODE = .RDONLY,
            .NONBLOCK = true,
            .CLOEXEC = true,
        }, 0) };
        defer file.close();
        const stat = try file.stat();
        if (stat.kind != .file) return error.FilterRequiresRegularFile;
        if (stat.size > file_limit) return error.FilterSampleExceedsLimit;
        if (stat.size > total_limit - input_bytes) return error.FilterInputExceedsLimit;
        const bytes = try file.readToEndAlloc(sample_allocator, @min(file_limit, total_limit - input_bytes));
        input_bytes += bytes.len;

        // Reject unknown extensions rather than silently deduplicating fields
        // that this version does not understand. Validation also sorts status IDs.
        const parsed = try std.json.parseFromSlice(observation.Observation, sample_allocator, bytes, .{});
        const packet = try observation.validateObservation(parsed.value);
        const comparison = if (previous) |before| try observation.compareObservations(before, packet) else null;

        var normalized = packet;
        normalized.observation_id = "";
        normalized.observation_started_at_unix_ms = 0;
        normalized.observed_at_unix_ms = 0;
        const normalized_bytes = try std.json.Stringify.valueAlloc(sample_allocator, normalized, .{});
        const adjacent_view = if (rules) |r| (if (previous) |before| try observation.presentation.computeView(sample_allocator, r, before, packet, comparison.?) else null) else null;
        const repeated = previous != null and std.mem.eql(u8, previous_normalized, normalized_bytes);
        if (repeated) repeats += 1;

        var without_text = normalized;
        without_text.capture.content = "";
        const without_text_bytes = try std.json.Stringify.valueAlloc(sample_allocator, without_text, .{});
        var reconstruction: ?observation.presentation.Result = null;
        const comparable = if (adjacent_view) |v| v.captured_text != .unknown and v.full_text != .unknown else true;
        if (rules != null and reference != null and comparable and std.mem.eql(u8, reference_without_text, without_text_bytes)) {
            const raw = try observation.compareObservations(reference.?, packet);
            const v = try observation.presentation.computeView(sample_allocator, rules.?, reference.?, packet, raw);
            if (v.captured_text == .cosmetic_only and v.full_text == .cosmetic_only and !v.spans_truncated) reconstruction = v;
        }
        const cosmetic = reconstruction != null and index + 1 != samples;
        const omit_repeat = repeated and comparable and index + 1 != samples;
        if (!cosmetic and !omit_repeat) {
            try writeJson(sample_allocator, .{
                .schema_version = @as(u32, 1),
                .kind = "rex_evidence_filter_sample",
                .reason = if (previous == null) "baseline" else if (index + 1 == samples and (repeated or rules != null)) "latest_checkpoint" else "evidence_changed",
                .sample_index = index + 1,
                .interpretation = "none",
                .observation = packet,
                .comparison = comparison,
                .view = adjacent_view,
            });
            emitted += 1;
            payload_bytes_emitted += (try std.json.Stringify.valueAlloc(sample_allocator, packet, .{})).len;
            evidence_sample_index = index + 1;
            _ = reference_arena.reset(.free_all);
            const ref_allocator = reference_arena.allocator();
            reference = (try std.json.parseFromSlice(observation.Observation, ref_allocator, normalized_bytes, .{ .allocate = .alloc_always })).value;
            reference_without_text = try ref_allocator.dupe(u8, without_text_bytes);
        } else if (cosmetic) {
            try writeJson(sample_allocator, .{
                .schema_version = @as(u32, 1),
                .kind = "rex_evidence_filter_cosmetic_repeat",
                .sample_index = index + 1,
                .evidence_sample_index = evidence_sample_index,
                .observation_id = packet.observation_id,
                .observation_started_at_unix_ms = packet.observation_started_at_unix_ms,
                .observed_at_unix_ms = packet.observed_at_unix_ms,
                .interpretation = "none",
                .comparison = comparison,
                .view = adjacent_view,
                .reconstruction = .{ .from_sample_index = evidence_sample_index, .spans = reconstruction.?.spans },
            });
            cosmetic_repeats += 1;
            omitted += 1;
        } else {
            try writeJson(sample_allocator, .{
                .schema_version = @as(u32, 1),
                .kind = "rex_evidence_filter_repeat",
                .sample_index = index + 1,
                .evidence_sample_index = evidence_sample_index,
                .observation_id = packet.observation_id,
                .observation_started_at_unix_ms = packet.observation_started_at_unix_ms,
                .observed_at_unix_ms = packet.observed_at_unix_ms,
                .interpretation = "none",
                .comparison = comparison,
                .view = adjacent_view,
            });
            repeat_omissions += 1;
            omitted += 1;
        }

        previous = packet;
        previous_normalized = normalized_bytes;
        std.mem.swap(std.heap.ArenaAllocator, &previous_arena, &current_arena);
        _ = current_arena.reset(.free_all);
    }

    try writeJson(allocator, .{
        .schema_version = @as(u32, 1),
        .kind = "rex_evidence_filter_summary",
        .outcome = "processed",
        .samples_read = samples,
        .observation_payloads_emitted = emitted,
        .repeated_evidence_samples = repeats,
        .observation_payloads_omitted = omitted,
        .input_bytes = input_bytes,
        .latest_observation_id = previous.?.observation_id,
        .interpretation = "none",
        .persistent_cache = false,
        .cosmetic_repeats = cosmetic_repeats,
        .repeats = repeat_omissions,
        .payload_bytes_emitted = payload_bytes_emitted,
        .view_rules_sha256 = if (rules) |r| r.sha256 else null,
    });
    return 0;
}
