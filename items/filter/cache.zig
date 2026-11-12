const std = @import("std");

const usage =
    \\Usage: teerex filter cache put --directory /absolute/private-dir --sample FILE --allow-sensitive-storage [--ttl-seconds N]
    \\       teerex filter cache get --directory /absolute/private-dir --expect FILE
    \\       teerex filter cache purge --directory /absolute/private-dir
    \\Offline, opt-in storage of ONE Rex observation, never acquisition or current/fresh evidence.
    \\Put requires explicit sensitive-plaintext consent. TTL defaults to 60 seconds (1..3600).
    \\Directory must be owned 0700 (put may create it); files owned 0600, regular, single-link, no symlinks.
    \\One encoded entry <=1 MiB; atomic replacement may temporarily retain another <=1 MiB pending entry.
    \\Get requires an explicit observation reference with the same target/source/capture budget.
    \\Expiry, backwards wall clock and identity/budget mismatch remove the entry on access, not in background.
    \\Cached data and comparisons stay historical, partial/unknown and untrusted; NEVER permission or completion.
    \\Purge unlinks capture/pending bytes, leaving the directory and empty lock; NOT forensic/backup erasure.
    \\Exit: 0 stored/historical hit/purged/absent, 3 miss/invalidated, 2 usage, 1 unsafe/corrupt/I/O/busy.
    \\Outputs and private files are NOT redacted or encrypted. Plain filter --sample still saves nothing.
    \\
;

const entry_limit = 1024 * 1024;
const entry_name = "observation.json";
const pending_name = ".observation.pending";
const lock_name = ".lock";

fn usageError(message: []const u8) u8 {
    std.debug.print("teerex: {s}\n{s}", .{ message, usage });
    return 2;
}

fn json(allocator: std.mem.Allocator, value: anytype) !void {
    const bytes = try std.json.Stringify.valueAlloc(allocator, value, .{});
    defer allocator.free(bytes);
    try std.fs.File.stdout().writeAll(bytes);
    try std.fs.File.stdout().writeAll("\n");
}

fn privateFile(file: std.fs.File) !void {
    const stat = try std.posix.fstat(file.handle);
    if (!std.posix.S.ISREG(stat.mode) or stat.uid != std.posix.geteuid() or
        stat.mode & 0o7777 != 0o600 or stat.nlink != 1) return error.UnsafeCacheFile;
}

const Cache = struct {
    directory: std.fs.Dir,
    lock: std.fs.File,

    fn open(path: []const u8, create: bool) !Cache {
        if (create) std.posix.mkdir(path, 0o700) catch |err| switch (err) {
            error.PathAlreadyExists => {},
            else => return err,
        };
        const directory: std.fs.Dir = .{ .fd = try std.posix.open(path, .{
            .ACCMODE = .RDONLY,
            .DIRECTORY = true,
            .NOFOLLOW = true,
            .CLOEXEC = true,
            .NONBLOCK = true,
        }, 0) };
        errdefer std.posix.close(directory.fd);
        const stat = try std.posix.fstat(directory.fd);
        if (stat.uid != std.posix.geteuid() or stat.mode & 0o7777 != 0o700) return error.UnsafeCacheDirectory;
        const lock: std.fs.File = .{ .handle = try std.posix.openat(directory.fd, lock_name, .{
            .ACCMODE = .RDWR,
            .CREAT = true,
            .NOFOLLOW = true,
            .CLOEXEC = true,
            .NONBLOCK = true,
        }, 0o600) };
        errdefer lock.close();
        try privateFile(lock);
        if ((try lock.stat()).size != 0) return error.UnsafeCacheLock;
        std.posix.flock(lock.handle, std.posix.LOCK.EX | std.posix.LOCK.NB) catch |err| switch (err) {
            error.WouldBlock => return error.CacheBusy,
            else => return err,
        };
        return .{ .directory = directory, .lock = lock };
    }

    fn close(self: Cache) void {
        self.lock.close();
        std.posix.close(self.directory.fd);
    }

    fn openFile(self: Cache, name: []const u8) !?std.fs.File {
        const file: std.fs.File = .{ .handle = std.posix.openat(self.directory.fd, name, .{
            .ACCMODE = .RDONLY,
            .NOFOLLOW = true,
            .CLOEXEC = true,
            .NONBLOCK = true,
        }, 0) catch |err| switch (err) {
            error.FileNotFound => return null,
            else => return err,
        } };
        errdefer file.close();
        try privateFile(file);
        return file;
    }

    fn remove(self: Cache, name: []const u8) !bool {
        // Check before unlinking: never follow links or delete unrelated unsafe data.
        const file = (try self.openFile(name)) orelse return false;
        defer file.close();
        try self.directory.deleteFile(name);
        try self.directorySync();
        return true;
    }

    fn directorySync(self: Cache) !void {
        try std.posix.fsync(self.directory.fd);
    }

    fn store(self: Cache, bytes: []const u8) !void {
        const file: std.fs.File = .{ .handle = try std.posix.openat(self.directory.fd, pending_name, .{
            .ACCMODE = .WRONLY,
            .CREAT = true,
            .EXCL = true,
            .NOFOLLOW = true,
            .CLOEXEC = true,
        }, 0o600) };
        defer file.close();
        errdefer self.directory.deleteFile(pending_name) catch {};
        try privateFile(file);
        try file.writeAll(bytes);
        try file.sync();
        try std.posix.renameat(self.directory.fd, pending_name, self.directory.fd, entry_name);
        try self.directorySync();
    }
};

fn Entry(comptime observation: type) type {
    return struct {
        schema_version: u32 = 1,
        kind: []const u8 = "rex_observation_cache",
        stored_at_unix_ms: i64,
        expires_at_unix_ms: i64,
        observation: observation.Observation,
    };
}

fn readObservation(allocator: std.mem.Allocator, path: []const u8, comptime observation: type) !observation.Observation {
    const file: std.fs.File = .{ .handle = try std.posix.open(path, .{
        .ACCMODE = .RDONLY,
        .NONBLOCK = true,
        .CLOEXEC = true,
    }, 0) };
    defer file.close();
    if ((try file.stat()).kind != .file) return error.CacheSampleRequiresRegularFile;
    const bytes = try file.readToEndAlloc(allocator, entry_limit);
    const raw = try std.json.parseFromSlice(std.json.Value, allocator, bytes, .{});
    try requireIntegerApi(raw.value);
    const parsed = try std.json.parseFromValue(observation.Observation, allocator, raw.value, .{});
    return observation.validateObservation(parsed.value);
}

fn requireIntegerApi(value: std.json.Value) !void {
    if (value != .object) return error.InvalidObservationApiRevision;
    const source = value.object.get("source") orelse return error.InvalidObservationApiRevision;
    if (source != .object) return error.InvalidObservationApiRevision;
    const revision = source.object.get("api_revision") orelse return error.InvalidObservationApiRevision;
    if (revision != .integer) return error.InvalidObservationApiRevision;
}

fn readEntry(allocator: std.mem.Allocator, cache: Cache, comptime observation: type) !?Entry(observation) {
    const file = (try cache.openFile(entry_name)) orelse return null;
    defer file.close();
    const bytes = try file.readToEndAlloc(allocator, entry_limit);
    const raw = try std.json.parseFromSlice(std.json.Value, allocator, bytes, .{});
    if (raw.value != .object) return error.InvalidCacheEnvelope;
    inline for (.{ "schema_version", "stored_at_unix_ms", "expires_at_unix_ms" }) |field| {
        const value = raw.value.object.get(field) orelse return error.InvalidCacheEnvelope;
        if (value != .integer) return error.InvalidCacheEnvelope;
    }
    try requireIntegerApi(raw.value.object.get("observation") orelse return error.InvalidCacheEnvelope);
    const parsed = try std.json.parseFromValue(Entry(observation), allocator, raw.value, .{});
    var entry = parsed.value;
    if (entry.schema_version != 1 or !std.mem.eql(u8, entry.kind, "rex_observation_cache") or
        entry.stored_at_unix_ms < 0 or entry.expires_at_unix_ms <= entry.stored_at_unix_ms or
        entry.expires_at_unix_ms - entry.stored_at_unix_ms > 3600 * 1000) return error.InvalidCacheEnvelope;
    entry.observation = try observation.validateObservation(entry.observation);
    return entry;
}

fn invalidation(entry: anytype, now: i64) ?[]const u8 {
    if (now < entry.stored_at_unix_ms) return "wall_clock_before_storage";
    if (now >= entry.expires_at_unix_ms) return "retention_expired";
    return null;
}

pub fn run(allocator: std.mem.Allocator, args: []const []const u8, comptime observation: type) !u8 {
    if ((args.len == 1 and std.mem.eql(u8, args[0], "--help")) or
        (args.len == 2 and std.mem.eql(u8, args[1], "--help")))
    {
        try std.fs.File.stdout().writeAll(usage);
        return 0;
    }
    if (args.len == 0) return usageError("expected cache put, get, or purge");
    const put = std.mem.eql(u8, args[0], "put");
    const get = std.mem.eql(u8, args[0], "get");
    const purge = std.mem.eql(u8, args[0], "purge");
    if (!put and !get and !purge) return usageError("expected cache put, get, or purge");
    var directory: ?[]const u8 = null;
    var sample: ?[]const u8 = null;
    var expect: ?[]const u8 = null;
    var ttl: ?u32 = null;
    var consent = false;
    var i: usize = 1;
    while (i < args.len) {
        const flag = args[i];
        i += 1;
        if (put and std.mem.eql(u8, flag, "--allow-sensitive-storage") and !consent) {
            consent = true;
            continue;
        }
        if (i == args.len) return usageError("cache option requires a value");
        const value = args[i];
        i += 1;
        if (value.len == 0) return usageError("cache option requires a nonempty value");
        if (std.mem.eql(u8, flag, "--directory") and directory == null) {
            directory = value;
        } else if (put and std.mem.eql(u8, flag, "--sample") and sample == null) {
            sample = value;
        } else if (get and std.mem.eql(u8, flag, "--expect") and expect == null) {
            expect = value;
        } else if (put and std.mem.eql(u8, flag, "--ttl-seconds") and ttl == null) {
            ttl = std.fmt.parseUnsigned(u32, value, 10) catch return usageError("invalid cache TTL");
        } else return usageError("unknown, repeated or inapplicable cache option");
    }
    const path = directory orelse return usageError("explicit --directory is required");
    if (!std.fs.path.isAbsolute(path) or path.len <= 1 or path[path.len - 1] == '/' or
        std.mem.eql(u8, std.fs.path.basename(path), ".") or std.mem.eql(u8, std.fs.path.basename(path), "..")) return usageError("cache directory must be an absolute path without trailing slash/dot");
    if (put and (!consent or sample == null)) return usageError("put requires --sample and --allow-sensitive-storage");
    if (get and expect == null) return usageError("get requires --expect observation FILE");
    const ttl_seconds = ttl orelse 60;
    if (ttl_seconds < 1 or ttl_seconds > 3600) return usageError("cache TTL must be 1..3600 seconds");

    // Validate explicit input before creating directories, storing or invalidating.
    const selected = if (sample orelse expect) |input| try readObservation(allocator, input, observation) else null;
    const cache = Cache.open(path, put) catch |err| switch (err) {
        error.FileNotFound => {
            if (put) return err;
            try json(allocator, .{ .schema_version = @as(u32, 1), .kind = "rex_observation_cache_result", .outcome = if (get) "miss" else "absent", .reason = "no_cache_directory", .interpretation = "none" });
            return if (get) 3 else 0;
        },
        else => return err,
    };
    defer cache.close();
    const pending_removed = try cache.remove(pending_name);
    if (purge) {
        const removed = try cache.remove(entry_name);
        try json(allocator, .{ .schema_version = @as(u32, 1), .kind = "rex_observation_cache_result", .outcome = if (removed or pending_removed) "purged" else "absent", .interpretation = "none", .secure_erasure = false });
        return 0;
    }
    const previous = try readEntry(allocator, cache, observation);
    const now = std.time.milliTimestamp();
    if (put) {
        var reason: ?[]const u8 = null;
        if (previous) |entry| {
            reason = invalidation(entry, now);
            _ = observation.compareObservations(entry.observation, selected.?) catch |err| switch (err) {
                error.DifferentObservationTargets => {
                    reason = "target_changed";
                    return store(allocator, cache, selected.?, ttl_seconds, now, true, reason, observation);
                },
                error.DifferentObservationSources => {
                    reason = "source_changed";
                    return store(allocator, cache, selected.?, ttl_seconds, now, true, reason, observation);
                },
                else => return err,
            };
            if (entry.observation.capture.max_bytes != selected.?.capture.max_bytes) reason = "capture_budget_changed";
        }
        return store(allocator, cache, selected.?, ttl_seconds, now, previous != null, reason, observation);
    }
    const entry = previous orelse {
        try json(allocator, .{ .schema_version = @as(u32, 1), .kind = "rex_observation_cache_result", .outcome = "miss", .reason = "no_entry", .interpretation = "none" });
        return 3;
    };
    var reason = invalidation(entry, now);
    const comparison = observation.compareObservations(entry.observation, selected.?) catch |err| switch (err) {
        error.DifferentObservationTargets => return invalidate(allocator, cache, "target_changed"),
        error.DifferentObservationSources => return invalidate(allocator, cache, "source_changed"),
        else => return err,
    };
    if (entry.observation.capture.max_bytes != selected.?.capture.max_bytes) reason = "capture_budget_changed";
    if (reason) |why| return invalidate(allocator, cache, why);
    try json(allocator, .{
        .schema_version = @as(u32, 1),
        .kind = "rex_observation_cache_result",
        .outcome = "historical_hit",
        .interpretation = "none",
        .evidence_freshness = "historical_unverified",
        .permission = "none",
        .stored_at_unix_ms = entry.stored_at_unix_ms,
        .expires_at_unix_ms = entry.expires_at_unix_ms,
        .read_at_unix_ms = now,
        .observation = entry.observation,
        .comparison_to_expectation = comparison,
    });
    return 0;
}

fn store(allocator: std.mem.Allocator, cache: Cache, packet: anytype, ttl: u32, now: i64, replaced: bool, reason: ?[]const u8, comptime observation: type) !u8 {
    const entry: Entry(observation) = .{ .stored_at_unix_ms = now, .expires_at_unix_ms = now + @as(i64, ttl) * 1000, .observation = packet };
    const bytes = try std.json.Stringify.valueAlloc(allocator, entry, .{});
    if (bytes.len > entry_limit) return error.CacheEntryExceedsLimit;
    try cache.store(bytes);
    try json(allocator, .{
        .schema_version = @as(u32, 1),
        .kind = "rex_observation_cache_result",
        .outcome = "stored",
        .interpretation = "none",
        .evidence_freshness = "historical_unverified",
        .replaced_entry = replaced,
        .previous_invalidation_reason = reason,
        .stored_at_unix_ms = now,
        .expires_at_unix_ms = entry.expires_at_unix_ms,
        .entry_bytes = bytes.len,
        .observation_id = packet.observation_id,
        .target = packet.target,
        .source = packet.source,
    });
    return 0;
}

fn invalidate(allocator: std.mem.Allocator, cache: Cache, reason: []const u8) !u8 {
    _ = try cache.remove(entry_name);
    try json(allocator, .{ .schema_version = @as(u32, 1), .kind = "rex_observation_cache_result", .outcome = "invalidated", .reason = reason, .interpretation = "none" });
    return 3;
}
