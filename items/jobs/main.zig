const std = @import("std");
const builtin = @import("builtin");
const supervised = @import("supervised_child");

const usage =
    \\Usage: teerex jobs OP --registry ABS [OPTIONS]
    \\OP: list | track | inspect | adopt | present | forget
    \\Every operation except list selects --socket ABS --session session:UUID --block block:UUID.
    \\track: --owner LABEL --kind agent|command --purpose TEXT --deadline-unix-ms N --cleanup manual
    \\adopt: --from-owner LABEL --owner LABEL --generation N --reason TEXT --deadline-unix-ms N
    \\present: --owner LABEL --generation N --reason TEXT --anchor block:UUID --focus yes|no [--label TEXT] [--relocate yes|no]
    \\Relocation defaults no (placed panes stay in place); yes explicitly moves beside anchor at half width.
    \\A focused source requires --focus yes for relocation; no silent focus transfer, retry or recreation.
    \\forget: --owner LABEL --generation N --reason TEXT (local record only; never closes a block)
    \\Live operations optionally take --timeout-ms N (100..60000, default 5000).
    \\Registry must already be an absolute, private 0700 owned directory. Max 32 records/256 KiB.
    \\API13 Mac-arm64/Linux-amd64 only; no autostart, agents, daemon, automatic close or enforced deadlines.
    \\Ownership is recorded responsibility, not authority, native ownership, isolation or process control.
    \\Exit: 0 requested evidence/record verified, 1 error/refusal/unknown, 2 usage, 124 deadline, 130/143 signal.
    \\
;

const Source = struct { rex_version: []const u8, platform: []const u8, api_revision: u32, instance_id: []const u8, host_id: []const u8 };
const Observation = struct {
    placement: []const u8,
    window_id: ?[]const u8 = null,
    block_host_id: []const u8,
    native_owner: ?[]const u8 = null,
    visible_in_view: bool,
    last_exit_code_reported: ?i64 = null,
    process_available: bool,
    revision: u64,
};
const Action = struct { operation: []const u8, reason: []const u8, at_unix_ms: i64, outcome: []const u8 };
const Entry = struct {
    socket: []const u8,
    session_id: []const u8,
    block_id: []const u8,
    source: Source,
    block_host_id: []const u8,
    owner: []const u8,
    kind: []const u8,
    purpose: []const u8,
    deadline_unix_ms: i64,
    cleanup: []const u8 = "manual",
    generation: u64 = 1,
    registered_at_unix_ms: i64,
    last_action: ?Action = null,
};
const State = struct { schema_version: u8, next_generation: u64, entries: []Entry };
const Options = struct {
    operation: []const u8,
    registry: ?[]const u8 = null,
    socket: ?[]const u8 = null,
    session: ?[]const u8 = null,
    block: ?[]const u8 = null,
    owner: ?[]const u8 = null,
    from_owner: ?[]const u8 = null,
    kind: ?[]const u8 = null,
    purpose: ?[]const u8 = null,
    cleanup: ?[]const u8 = null,
    reason: ?[]const u8 = null,
    anchor: ?[]const u8 = null,
    label: ?[]const u8 = null,
    focus: ?[]const u8 = null,
    relocate: ?[]const u8 = null,
    deadline_unix_ms: ?i64 = null,
    generation: ?u64 = null,
    timeout_ms: ?u64 = null,
};

fn eq(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}
fn textValid(s: []const u8, max: usize) bool {
    if (s.len == 0 or s.len > max or !std.unicode.utf8ValidateSlice(s)) return false;
    for (s) |c| if (c < 32 or c == 127) return false;
    return true;
}
fn fullId(value: []const u8, prefix: []const u8) bool {
    if (!std.mem.startsWith(u8, value, prefix) or value.len != prefix.len + 36) return false;
    for (value[prefix.len..], 0..) |c, i| {
        if (i == 8 or i == 13 or i == 18 or i == 23) {
            if (c != '-') return false;
        } else if (!std.ascii.isHex(c) or std.ascii.isUpper(c)) return false;
    }
    return true;
}
fn validSource(s: Source) bool {
    return s.api_revision == 13 and (eq(s.platform, "darwin_arm64") or eq(s.platform, "linux_amd64")) and
        textValid(s.rex_version, 128) and textValid(s.instance_id, 128) and textValid(s.host_id, 128);
}
fn validEntry(e: Entry) bool {
    return std.fs.path.isAbsolute(e.socket) and textValid(e.socket, 4096) and fullId(e.session_id, "session:") and
        fullId(e.block_id, "block:") and validSource(e.source) and textValid(e.block_host_id, 128) and
        textValid(e.owner, 128) and (eq(e.kind, "agent") or eq(e.kind, "command")) and textValid(e.purpose, 256) and
        e.deadline_unix_ms > 0 and eq(e.cleanup, "manual") and e.generation > 0 and e.generation < std.math.maxInt(u64) and
        e.registered_at_unix_ms > 0 and (if (e.last_action) |a| textValid(a.operation, 16) and textValid(a.reason, 256) and
        textValid(a.outcome, 64) and a.at_unix_ms > 0 else true);
}

// Private operator-selected directory, stable flock inode, atomic bounded state.
// The lock coordinates this registry only; it is never a Rex or process lease.
const Registry = struct {
    dir: std.fs.Dir,
    lock: std.fs.File,
    state: State,

    fn privateStat(fd: std.posix.fd_t, directory: bool) !void {
        const s = try std.posix.fstat(fd);
        if (s.uid != std.posix.getuid() or (s.mode & 0o7777) != (if (directory) @as(u32, 0o700) else @as(u32, 0o600)) or
            (s.mode & std.posix.S.IFMT) != (if (directory) @as(u32, std.posix.S.IFDIR) else @as(u32, std.posix.S.IFREG)) or
            (!directory and s.nlink != 1)) return error.RegistryNotPrivateOwnedRegular;
    }
    fn file(dir: std.fs.Dir, name: []const u8, create: bool) !std.fs.File {
        const fd = try std.posix.openat(dir.fd, name, .{ .ACCMODE = .RDWR, .CREAT = create, .NOFOLLOW = true, .CLOEXEC = true, .NONBLOCK = true }, 0o600);
        errdefer std.posix.close(fd);
        try privateStat(fd, false);
        return .{ .handle = fd };
    }
    fn open(allocator: std.mem.Allocator, path: []const u8) !Registry {
        var dir = try std.fs.openDirAbsolute(path, .{ .no_follow = true, .iterate = true });
        errdefer dir.close();
        try privateStat(dir.fd, true);
        const lock = try file(dir, "lock", true);
        errdefer lock.close();
        try std.posix.flock(lock.handle, std.posix.LOCK.EX | std.posix.LOCK.NB);
        var state: State = .{ .schema_version = 1, .next_generation = 1, .entries = &.{} };
        const saved = file(dir, "state.json", false) catch |err| switch (err) {
            error.FileNotFound => null,
            else => return err,
        };
        if (saved) |f| {
            defer f.close();
            const raw = try f.readToEndAlloc(allocator, 262144);
            state = (try std.json.parseFromSlice(State, allocator, raw, .{ .allocate = .alloc_always })).value;
            if (state.schema_version != 1 or state.entries.len > 32 or state.next_generation == 0 or state.next_generation >= std.math.maxInt(u64) - 1) return error.InvalidRegistry;
            for (state.entries, 0..) |entry, i| {
                if (!validEntry(entry) or entry.generation >= state.next_generation) return error.InvalidRegistry;
                for (state.entries[0..i]) |old| {
                    if (eq(entry.session_id, old.session_id) and eq(entry.block_id, old.block_id) and
                        (eq(entry.socket, old.socket) or (eq(entry.source.instance_id, old.source.instance_id) and eq(entry.source.host_id, old.source.host_id)))) return error.DuplicateRegistryTarget;
                }
            }
        }
        return .{ .dir = dir, .lock = lock, .state = state };
    }
    fn generation(self: *Registry) !u64 {
        if (self.state.next_generation >= std.math.maxInt(u64) - 2) return error.GenerationExhausted;
        const value = self.state.next_generation;
        self.state.next_generation += 1;
        return value;
    }
    fn close(self: *Registry) void {
        self.lock.close();
        self.dir.close();
    }
    fn save(self: *Registry, allocator: std.mem.Allocator) !void {
        const raw = try std.json.Stringify.valueAlloc(allocator, self.state, .{ .whitespace = .indent_2 });
        if (raw.len > 262144) return error.RegistryFull;
        // Fixed name bounds crash debris to one file; never overwrite an unreconciled staged write.
        const next = try self.dir.createFile("state.next", .{ .exclusive = true, .mode = 0o600 });
        var renamed = false;
        defer {
            next.close();
            if (!renamed) self.dir.deleteFile("state.next") catch {};
        }
        try privateStat(next.handle, false);
        try next.writeAll(raw);
        try next.sync();
        try self.dir.rename("state.next", "state.json");
        renamed = true;
        try std.posix.fsync(self.dir.fd);
    }
};

const Frame = struct { event: []const u8, source: ?Source = null, observation: ?Observation = null, reason: ?[]const u8 = null };
const Collector = struct {
    allocator: std.mem.Allocator,
    pending: std.ArrayList(u8) = .empty,
    source: ?Source = null,
    observation: ?Observation = null,
    reason: ?[]const u8 = null,
    attempt: bool = false,
    verified: bool = false,
    finished: bool = false,
    frames: u8 = 0,
    pub fn receive(self: *Collector, bytes: []const u8) !void {
        if (bytes.len > 8192 - self.pending.items.len) return error.InvalidJobsFrame;
        try self.pending.appendSlice(self.allocator, bytes);
        while (std.mem.indexOfScalar(u8, self.pending.items, '\n')) |end| {
            if (self.finished or self.frames >= 4) return error.InvalidJobsFrame;
            self.frames += 1;
            const f = (try std.json.parseFromSlice(Frame, self.allocator, self.pending.items[0..end], .{ .allocate = .alloc_always })).value;
            if (eq(f.event, "source") and self.frames == 1) {
                self.source = f.source orelse return error.InvalidJobsFrame;
                if (!validSource(self.source.?)) return error.InvalidJobsFrame;
            } else if (eq(f.event, "observed") and self.source != null and self.observation == null and !self.attempt) {
                const o = f.observation orelse return error.InvalidJobsFrame;
                if (!textValid(o.placement, 32) or !textValid(o.block_host_id, 128) or
                    (if (o.window_id) |w| !fullId(w, "window:") else false)) return error.InvalidJobsFrame;
                self.observation = o;
            } else if (eq(f.event, "attempt") and self.observation != null and !self.attempt) {
                self.attempt = true;
            } else if (eq(f.event, "verified") and self.observation != null) {
                self.verified = true;
                self.finished = true;
            } else if (eq(f.event, "refused") and !self.attempt) {
                self.reason = f.reason orelse return error.InvalidJobsFrame;
                if (!textValid(self.reason.?, 128)) return error.InvalidJobsFrame;
                self.finished = true;
            } else return error.InvalidJobsFrame;
            try self.pending.replaceRange(self.allocator, 0, end + 1, &.{});
        }
    }
};
const Live = struct { collector: Collector, outcome: []const u8, code: u8, failure: ?[]const u8, backend_term: ?std.process.Child.Term };
fn query(allocator: std.mem.Allocator, o: Options, entry: ?Entry) !Live {
    const request = try std.json.Stringify.valueAlloc(allocator, .{
        .operation = o.operation,
        .session_id = o.session.?,
        .block_id = o.block.?,
        .kind = if (entry) |e| e.kind else o.kind.?,
        .instance_id = if (entry) |e| @as(?[]const u8, e.source.instance_id) else null,
        .host_id = if (entry) |e| @as(?[]const u8, e.source.host_id) else null,
        .block_host_id = if (entry) |e| @as(?[]const u8, e.block_host_id) else null,
        .anchor = o.anchor,
        .label = o.label,
        .focus = if (o.focus) |f| eq(f, "yes") else false,
        .relocate = if (o.relocate) |r| eq(r, "yes") else false,
    }, .{});
    var env = try std.process.getEnvMap(allocator);
    for ([_][]const u8{ "REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT" }) |key| env.remove(key);
    const endpoint = try std.fmt.allocPrint(allocator, "unix://{s}", .{o.socket.?});
    const argv = [_][]const u8{ "rex", "--autostart=false", "--server", endpoint, "--timeout", "3s", "--color", "never", "do", "--session", o.session.?, "-e", @embedFile("jobs.lua"), "--args", request };
    var c: Collector = .{ .allocator = allocator };
    var failure: ?[]const u8 = null;
    const r = supervised.collect(allocator, &argv, &env, o.timeout_ms orelse 5000, &c) catch |err| blk: {
        failure = @errorName(err);
        break :blk null;
    };
    const sig = supervised.requestedSignal();
    const deadline = r != null and r.?.deadline_exceeded;
    const ok = r != null and !r.?.stopped and r.?.term == .Exited and r.?.term.Exited == 0 and c.pending.items.len == 0;
    const success = ok and c.verified and sig == 0;
    const outcome: []const u8 = if (sig != 0) "cancel_requested" else if (deadline) "deadline_exceeded" else if (success) "verified" else if (ok and c.finished and c.reason != null) "refused" else "uncertain";
    if (!success) {
        if (r) |result| if (result.stderr.len != 0) std.debug.print("teerex jobs: Rex backend: {s}\n", .{result.stderr});
    }
    return .{
        .collector = c,
        .outcome = outcome,
        .code = if (sig != 0) 128 + sig else if (deadline) 124 else if (success) 0 else 1,
        .failure = failure orelse c.reason orelse if (!success) @as(?[]const u8, "rex_transport_incomplete") else null,
        .backend_term = if (r) |result| result.term else null,
    };
}
fn output(allocator: std.mem.Allocator, value: anytype) !void {
    const raw = try std.json.Stringify.valueAlloc(allocator, value, .{ .whitespace = .indent_2 });
    try std.fs.File.stdout().writeAll(raw);
    try std.fs.File.stdout().writeAll("\n");
}
fn usageError() u8 {
    std.debug.print("teerex jobs: invalid, missing or repeated option\n{s}", .{usage});
    return 2;
}
fn parse(args: []const []const u8) !Options {
    if (args.len == 0) return error.Usage;
    var o: Options = .{ .operation = args[0] };
    const allowed: []const []const u8 = if (eq(o.operation, "list")) &.{} else if (eq(o.operation, "track"))
        &.{ "owner", "kind", "purpose", "deadline-unix-ms", "cleanup", "timeout-ms" }
    else if (eq(o.operation, "inspect")) &.{"timeout-ms"} else if (eq(o.operation, "adopt"))
        &.{ "from-owner", "owner", "generation", "reason", "deadline-unix-ms", "timeout-ms" }
    else if (eq(o.operation, "present")) &.{ "owner", "generation", "reason", "anchor", "focus", "label", "relocate", "timeout-ms" } else if (eq(o.operation, "forget"))
        &.{ "owner", "generation", "reason" }
    else
        return error.Usage;
    var i: usize = 1;
    while (i < args.len) : (i += 2) {
        if (i + 1 >= args.len or !std.mem.startsWith(u8, args[i], "--")) return error.Usage;
        const key = args[i][2..];
        const value = args[i + 1];
        if (!textValid(value, 4096)) return error.Usage;
        for (args[1..i], 1..) |old, at| if (at % 2 == 1 and eq(old, args[i])) return error.Usage;
        if (eq(key, "registry")) {
            o.registry = value;
            continue;
        }
        if (!eq(o.operation, "list")) {
            if (eq(key, "socket")) {
                o.socket = value;
                continue;
            }
            if (eq(key, "session")) {
                o.session = value;
                continue;
            }
            if (eq(key, "block")) {
                o.block = value;
                continue;
            }
        }
        var found = false;
        for (allowed) |option| if (eq(option, key)) {
            found = true;
            break;
        };
        if (!found) return error.Usage;
        if (eq(key, "deadline-unix-ms")) {
            o.deadline_unix_ms = std.fmt.parseInt(i64, value, 10) catch return error.Usage;
        } else if (eq(key, "generation")) {
            o.generation = std.fmt.parseUnsigned(u64, value, 10) catch return error.Usage;
        } else if (eq(key, "timeout-ms")) {
            o.timeout_ms = std.fmt.parseUnsigned(u64, value, 10) catch return error.Usage;
        } else {
            inline for (.{ "owner", "kind", "purpose", "cleanup", "reason", "anchor", "focus", "label", "relocate" }) |field| {
                if (eq(key, field)) @field(o, field) = value;
            }
            if (eq(key, "from-owner")) o.from_owner = value;
        }
    }
    if (o.registry == null or !std.fs.path.isAbsolute(o.registry.?)) return error.Usage;
    if (!eq(o.operation, "list")) {
        if (o.socket == null or !std.fs.path.isAbsolute(o.socket.?) or o.session == null or !fullId(o.session.?, "session:") or
            o.block == null or !fullId(o.block.?, "block:")) return error.Usage;
    }
    if (o.timeout_ms) |n| if (n < 100 or n > 60000) return error.Usage;
    if (o.generation) |n| if (n == 0 or n >= std.math.maxInt(u64) - 1) return error.Usage;
    for ([_]?[]const u8{ o.owner, o.from_owner, o.label }) |value| if (value) |s| if (!textValid(s, 128)) return error.Usage;
    for ([_]?[]const u8{ o.purpose, o.reason }) |value| if (value) |s| if (!textValid(s, 256)) return error.Usage;
    if (o.deadline_unix_ms) |deadline| {
        const now = std.time.milliTimestamp();
        if (deadline <= now or deadline - now > 30 * std.time.ms_per_day) return error.Usage;
    }
    if (eq(o.operation, "track") and (o.owner == null or o.kind == null or (!eq(o.kind.?, "agent") and !eq(o.kind.?, "command")) or
        o.purpose == null or o.deadline_unix_ms == null or o.cleanup == null or !eq(o.cleanup.?, "manual"))) return error.Usage;
    if ((eq(o.operation, "adopt") or eq(o.operation, "present") or eq(o.operation, "forget")) and
        (o.owner == null or o.generation == null or o.reason == null)) return error.Usage;
    if (eq(o.operation, "adopt") and (o.from_owner == null or eq(o.from_owner.?, o.owner.?) or o.deadline_unix_ms == null)) return error.Usage;
    if (eq(o.operation, "present") and (o.anchor == null or !fullId(o.anchor.?, "block:") or eq(o.anchor.?, o.block.?) or
        o.focus == null or (!eq(o.focus.?, "yes") and !eq(o.focus.?, "no")))) return error.Usage;
    if (o.relocate) |value| if (!eq(value, "yes") and !eq(value, "no")) return error.Usage;
    return o;
}

pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    if (args.len == 1 and eq(args[0], "--help")) {
        try std.fs.File.stdout().writeAll(usage);
        return 0;
    }
    const o = parse(args) catch return usageError();
    return execute(allocator, o) catch |err| {
        try output(allocator, .{ .schema_version = 1, .kind = "jobs_result", .operation = o.operation, .outcome = "error", .failure_reason = @errorName(err), .remote_effect = "not_established_check_target_and_registry_before_retry" });
        return 1;
    };
}
fn execute(allocator: std.mem.Allocator, o: Options) !u8 {
    if (builtin.os.tag != .macos and builtin.os.tag != .linux) return error.JobsRequiresUnix;
    var registry = try Registry.open(allocator, o.registry.?);
    defer registry.close();
    const now = std.time.milliTimestamp();
    if (eq(o.operation, "list")) {
        try output(allocator, .{ .schema_version = 1, .kind = "jobs_list", .entries = registry.state.entries, .evaluated_at_unix_ms = now, .live_state = "not_checked", .owner_liveness = "not_checked", .deadline_enforced = false, .automatic_cleanup = false });
        return 0;
    }
    var index: ?usize = null;
    for (registry.state.entries, 0..) |e, at| {
        if (eq(e.socket, o.socket.?) and eq(e.session_id, o.session.?) and eq(e.block_id, o.block.?)) index = at;
    }
    const track = eq(o.operation, "track");
    if (track and index != null) return error.TargetAlreadyTracked;
    if (!track and index == null) return error.TargetNotTracked;
    if (track and registry.state.entries.len == 32) return error.RegistryFull;
    var entry: ?Entry = if (index) |at| registry.state.entries[at] else null;
    if (entry) |e| {
        if (o.generation) |g| if (g != e.generation) return error.GenerationConflict;
        if (o.owner) |owner| {
            const expected = if (eq(o.operation, "adopt")) o.from_owner.? else owner;
            if (!eq(e.owner, expected)) return error.RecordedOwnerMismatch;
        }
    }
    if (eq(o.operation, "forget")) {
        const at = index.?;
        const e = entry.?;
        std.mem.copyForwards(Entry, registry.state.entries[at .. registry.state.entries.len - 1], registry.state.entries[at + 1 ..]);
        registry.state.entries = registry.state.entries[0 .. registry.state.entries.len - 1];
        try registry.save(allocator);
        try output(allocator, .{ .schema_version = 1, .kind = "jobs_result", .operation = "forget", .outcome = "record_forgotten", .entry = e, .reason = o.reason, .resource_closed = false, .process_lifetime = "unchanged_not_verified" });
        return 0;
    }
    const signals = supervised.Signals.init();
    defer signals.deinit();
    if (eq(o.operation, "present")) {
        // Persist intent before any remote dispatch. A crash/lost ACK never becomes a false success.
        entry.?.generation = try registry.generation();
        entry.?.last_action = .{ .operation = "present", .reason = o.reason.?, .at_unix_ms = now, .outcome = "uncertain" };
        registry.state.entries[index.?] = entry.?;
        try registry.save(allocator);
    }
    const live = try query(allocator, o, entry);
    if (live.code == 0 and track) {
        for (registry.state.entries) |existing| {
            if (eq(existing.session_id, o.session.?) and eq(existing.block_id, o.block.?) and
                eq(existing.source.instance_id, live.collector.source.?.instance_id) and
                eq(existing.source.host_id, live.collector.source.?.host_id)) return error.TargetAlreadyTrackedThroughAnotherEndpoint;
        }
        entry = .{ .socket = o.socket.?, .session_id = o.session.?, .block_id = o.block.?, .source = live.collector.source.?, .block_host_id = live.collector.observation.?.block_host_id, .owner = o.owner.?, .kind = o.kind.?, .purpose = o.purpose.?, .deadline_unix_ms = o.deadline_unix_ms.?, .generation = try registry.generation(), .registered_at_unix_ms = now };
        registry.state.entries = try std.mem.concat(allocator, Entry, &.{ registry.state.entries, &.{entry.?} });
        try registry.save(allocator);
    } else if (live.code == 0 and eq(o.operation, "adopt")) {
        entry.?.owner = o.owner.?;
        entry.?.deadline_unix_ms = o.deadline_unix_ms.?;
        entry.?.generation = try registry.generation();
        entry.?.last_action = .{ .operation = "adopt", .reason = o.reason.?, .at_unix_ms = now, .outcome = "recorded_responsibility_transferred" };
        registry.state.entries[index.?] = entry.?;
        try registry.save(allocator);
    } else if (eq(o.operation, "present")) {
        entry.?.last_action.?.outcome = live.outcome;
        registry.state.entries[index.?] = entry.?;
        try registry.save(allocator);
    }
    try output(allocator, .{ .schema_version = 1, .kind = "jobs_result", .operation = o.operation, .outcome = live.outcome, .failure_reason = live.failure, .backend_term = live.backend_term, .entry = entry, .source_observed = live.collector.source, .observation = live.collector.observation, .observed_at_unix_ms = std.time.milliTimestamp(), .observation_is_atomic = false, .mutation_attempt_frame_seen = live.collector.attempt, .retry_safe = !eq(o.operation, "present"), .deadline_passed = if (entry) |e| std.time.milliTimestamp() >= e.deadline_unix_ms else false, .deadline_enforced = false, .automatic_cleanup = false, .recorded_owner_is_process_owner = false, .owner_liveness = "not_checked", .task_completion = "not_assessed", .all_processes_verified_gone = false, .exclusive_control = false });
    return live.code;
}
