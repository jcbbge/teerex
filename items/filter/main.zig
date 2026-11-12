const std = @import("std");

const usage =
    \\Usage: teerex filter --sample FILE --sample FILE [--sample FILE ...]
    \\       teerex filter cache put|get|purge --help
    \\Filter 2..128 explicit Rex observation files in supplied order, without contacting Rex.
    \\Only identical returned evidence is omitted; packet IDs/client times are not evidence changes.
    \\Every text, process, directory, status and provenance change remains visible. No cosmetic classifier.
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
    if (args.len < 4 or args.len > 256 or args.len % 2 != 0) return usageError("provide 2..128 --sample FILE pairs");
    var i: usize = 0;
    while (i < args.len) : (i += 2) {
        if (!std.mem.eql(u8, args[i], "--sample") or args[i + 1].len == 0) return usageError("expected --sample FILE");
    }

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
    const samples = args.len / 2;

    for (0..samples) |index| {
        const sample_allocator = current_arena.allocator();
        // Nonblocking open lets us reject a FIFO without waiting for a writer.
        const file: std.fs.File = .{ .handle = try std.posix.open(args[2 * index + 1], .{
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
        const repeated = previous != null and std.mem.eql(u8, previous_normalized, normalized_bytes);
        if (repeated) repeats += 1;

        // Unknown/partial evidence can repeat; that does not make it known. The
        // final checkpoint always carries the latest identity and nullable delta.
        if (!repeated or index + 1 == samples) {
            try writeJson(sample_allocator, .{
                .schema_version = @as(u32, 1),
                .kind = "rex_evidence_filter_sample",
                .reason = if (previous == null) "baseline" else if (repeated) "latest_checkpoint" else "evidence_changed",
                .sample_index = index + 1,
                .interpretation = "none",
                .observation = packet,
                .comparison = comparison,
            });
            emitted += 1;
            evidence_sample_index = index + 1;
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
            });
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
    });
    return 0;
}
