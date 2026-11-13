const std = @import("std");
const builtin = @import("builtin");
const limit = 1048576;
var started_at: i64 = 0;
var timer: ?std.time.Timer = null;
var elapsed_before_exec: u64 = 0;
var call_id: [32]u8 = undefined;
const friction = @import("friction.zig");
pub var server_uri: ?*const fn (std.mem.Allocator, []const []const u8) anyerror!?[]const u8 = null;

fn pid() i32 {
    return if (builtin.os.tag == .linux) std.os.linux.getpid() else std.c.getpid();
}

fn private(fd: std.posix.fd_t, directory: bool) !void {
    const s = try std.posix.fstat(fd);
    const kind = s.mode & std.posix.S.IFMT;
    if (s.uid != std.posix.getuid() or s.mode & 0o7777 != @as(u32, if (directory) 0o700 else 0o600) or
        kind != @as(u32, if (directory) std.posix.S.IFDIR else std.posix.S.IFREG) or (!directory and s.nlink != 1)) return error.InsecureCallLog;
}

fn append(allocator: std.mem.Allocator, record: anytype) !void {
    const path = if (std.posix.getenv("TEEREX_CALL_LOG_DIR")) |p| p else try std.fmt.allocPrint(allocator, "{s}/.local/state/teerex/calls", .{std.posix.getenv("HOME") orelse return});
    if (!std.fs.path.isAbsolute(path)) return;
    if (std.fs.path.dirname(path)) |parent| try std.fs.cwd().makePath(parent);
    std.posix.mkdir(path, 0o700) catch |err| if (err != error.PathAlreadyExists) return err;
    const dir = try std.posix.open(path, .{ .ACCMODE = .RDONLY, .DIRECTORY = true, .NOFOLLOW = true, .CLOEXEC = true, .NONBLOCK = true }, 0);
    defer std.posix.close(dir);
    try private(dir, true);
    const lock = try std.posix.openat(dir, "lock", .{ .ACCMODE = .RDWR, .CREAT = true, .NOFOLLOW = true, .CLOEXEC = true, .NONBLOCK = true }, 0o600);
    defer std.posix.close(lock);
    try private(lock, false);
    try std.posix.flock(lock, std.posix.LOCK.EX | std.posix.LOCK.NB);
    var fd = try std.posix.openat(dir, "calls.jsonl", .{ .ACCMODE = .WRONLY, .APPEND = true, .CREAT = true, .NOFOLLOW = true, .CLOEXEC = true, .NONBLOCK = true }, 0o600);
    defer std.posix.close(fd);
    try private(fd, false);
    const is_start = @hasField(@TypeOf(record), "verb");
    const captured = if (is_start) friction.collect(allocator, dir, &call_id, @divFloor(started_at, 1000000), record.version, record.verb, record.subverb, server_uri) catch "failed" else null;
    const Packet = struct {
        value: @TypeOf(record),
        state: ?[]const u8,
        pub fn jsonStringify(self: @This(), writer: anytype) !void {
            try writer.beginObject();
            inline for (@typeInfo(@TypeOf(record)).@"struct".fields) |field| {
                try writer.objectField(field.name);
                try writer.write(@field(self.value, field.name));
            }
            if (self.state) |state| {
                try writer.objectField("friction_write");
                try writer.write(state);
            }
            try writer.endObject();
        }
    };
    const raw = try std.json.Stringify.valueAlloc(allocator, Packet{ .value = record, .state = captured }, .{});
    const line = try std.fmt.allocPrint(allocator, "{s}\n", .{raw});
    if ((try std.posix.fstat(fd)).size + @as(i64, @intCast(line.len)) > limit) {
        const name = try std.fmt.allocPrint(allocator, "calls-{d:0>20}-{d}.jsonl", .{ std.time.nanoTimestamp(), pid() });
        // Cooperating writers hold the same lock as the Python board reader.
        try std.posix.renameat(dir, "calls.jsonl", dir, name);
        const next = try std.posix.openat(dir, "calls.jsonl", .{ .ACCMODE = .WRONLY, .APPEND = true, .CREAT = true, .EXCL = true, .NOFOLLOW = true, .CLOEXEC = true, .NONBLOCK = true }, 0o600);
        std.posix.close(fd);
        fd = next;
    }
    // Exactly one append syscall. A failed/partial write never changes command behavior.
    _ = try std.posix.write(fd, line);
}

const verbs = " pin decide claim-status revalidate records new park add attach set show resume navigate lint export init targets resolve exec surfaces open inspect rename move focus close palette boards inbox fleet calls friction enable disable status forget label report probe state seat register clear append ask agents launch profiles shell ack deliver stop present exited channel spawn recovery snapshot restore update install rollback run-visible observe compare watch run offstage doctor send jobs adapters maneuver-check filter remap-preview remap-apply try-route list plan apply cartridges session ensure hook human prune track adopt generate call activate remove --version --help ";
const flags = " --rex --config --host --socket --session --block --window --pane --store --registry --from --message-file --card-file --title --ask --context --option --recommend --id --resolve --answer --draft --draft-wait-ms --timeout-ms --once --json --limit --help --version --tty --profile --profiles --owner --purpose --state --detail --generation --reason --archive --interval-ms --hosts --targets-file --jobs-registry --apply --all --allow-experimental --catalog --root --deactivate --map-file --kind --deadline-unix-ms --cleanup ";
fn known(allocator: std.mem.Allocator, words: []const u8, word: []const u8) !bool {
    return std.mem.indexOf(u8, words, try std.fmt.allocPrint(allocator, " {s} ", .{word})) != null;
}
fn canonicalId(value: []const u8) bool {
    const at = std.mem.indexOfScalar(u8, value, ':') orelse return false;
    const kind = value[0..at];
    if (!(std.mem.eql(u8, kind, "session") or std.mem.eql(u8, kind, "block") or std.mem.eql(u8, kind, "window"))) return false;
    const uuid = value[at + 1 ..];
    if (uuid.len != 36) return false;
    for (uuid, 0..) |c, i| {
        if (i == 8 or i == 13 or i == 18 or i == 23) {
            if (c != '-') return false;
        } else if (!std.ascii.isDigit(c) and !(c >= 'a' and c <= 'f')) return false;
    }
    return true;
}

pub fn start(allocator: std.mem.Allocator, version: []const u8) void {
    startInner(allocator, version) catch {};
}
fn startInner(allocator: std.mem.Allocator, version: []const u8) !void {
    started_at = @intCast(std.time.nanoTimestamp());
    timer = std.time.Timer.start() catch null;
    var random: [16]u8 = undefined;
    std.crypto.random.bytes(&random);
    call_id = std.fmt.bytesToHex(random, .lower);
    if (std.posix.getenv("TEEREX_CALL_START")) |saved| {
        var parts = std.mem.splitScalar(u8, saved, ':');
        const saved_pid = std.fmt.parseInt(i32, parts.next() orelse "", 10) catch 0;
        const saved_at = std.fmt.parseInt(i64, parts.next() orelse "", 10) catch 0;
        const saved_id = parts.next();
        if (saved_pid == pid() and saved_at > 0 and parts.next() == null) {
            if (saved_id) |id| {
                if (id.len != 32) return;
                for (id) |c| if (!(std.ascii.isDigit(c) or (c >= 'a' and c <= 'f'))) return;
                @memcpy(&call_id, id);
            }
            elapsed_before_exec = @intCast(@max(0, @divFloor(std.time.nanoTimestamp() - saved_at, 1000000)));
            started_at = saved_at;
            return;
        }
    }
    const all = try std.process.argsAlloc(allocator);
    const args = all[1..];
    var words: std.ArrayList([]const u8) = .empty;
    var selected_flags: std.ArrayList([]const u8) = .empty;
    var ids: std.ArrayList([]const u8) = .empty;
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const arg = args[i];
        if (std.mem.eql(u8, arg, "--")) break;
        if (std.mem.startsWith(u8, arg, "--")) {
            var split = std.mem.splitScalar(u8, arg, '=');
            const flag = split.next().?;
            if (try known(allocator, flags, flag)) try selected_flags.append(allocator, flag);
            const inline_value = split.next();
            const value = inline_value orelse if (i + 1 < args.len) args[i + 1] else "";
            if (std.mem.eql(u8, flag, "--session") or std.mem.eql(u8, flag, "--block") or std.mem.eql(u8, flag, "--window") or std.mem.eql(u8, flag, "--pane")) {
                if (canonicalId(value) and ids.items.len < 16) try ids.append(allocator, value);
            }
            if (inline_value == null and !std.mem.eql(u8, flag, "--help") and !std.mem.eql(u8, flag, "--version") and !std.mem.eql(u8, flag, "--once") and !std.mem.eql(u8, flag, "--json") and !std.mem.eql(u8, flag, "--archive") and !std.mem.eql(u8, flag, "--tty")) i += 1;
        } else if (words.items.len < 2) {
            try words.append(allocator, if (try known(allocator, verbs, arg)) arg else "unknown");
        }
        if (selected_flags.items.len >= 64) break;
    }
    try append(allocator, .{ .schema_version = 1, .call_id = &call_id, .caller = .{ .via = friction.name(std.posix.getenv("TEEREX_CALLER")), .via_invalid = std.posix.getenv("TEEREX_CALLER") != null and friction.name(std.posix.getenv("TEEREX_CALLER")) == null, .agent_name = friction.name(std.posix.getenv("AGENT_NAME")) }, .phase = "start", .at = @divFloor(started_at, 1000000), .start_at = started_at, .pid = pid(), .version = version, .verb = if (words.items.len > 0) words.items[0] else if (args.len == 1 and std.mem.eql(u8, args[0], "--version")) "--version" else "help", .subverb = if (words.items.len > 1) @as(?[]const u8, words.items[1]) else null, .flags = selected_flags.items, .ids = ids.items });
}

pub fn end(allocator: std.mem.Allocator, code: u8) void {
    if (started_at == 0) return;
    const elapsed = elapsed_before_exec + if (timer) |*t| t.read() / std.time.ns_per_ms else 0;
    append(allocator, .{ .schema_version = 1, .call_id = &call_id, .phase = "end", .at = std.time.milliTimestamp(), .start_at = started_at, .pid = pid(), .exit = code, .elapsed_ms = elapsed }) catch {};
}

pub fn context(allocator: std.mem.Allocator) ![]const u8 {
    return std.fmt.allocPrint(allocator, "{d}:{d}:{s}", .{ pid(), started_at, call_id });
}

/// Runs in the existing helper process; execs of foreign programs have no invented end.
pub fn python(allocator: std.mem.Allocator, source: []const u8) ![]const u8 {
    const calls_source = try std.json.Stringify.valueAlloc(allocator, @embedFile("calls.py"), .{});
    const helper_source = try std.json.Stringify.valueAlloc(allocator, source, .{});
    return std.fmt.allocPrint(allocator, "import types,sys\n_calls=types.ModuleType('teerex_calls')\nexec({s}, _calls.__dict__)\nsys.modules['teerex_calls']=_calls\n_calls.run_helper({s}, {d}, {d}, '{s}')", .{ calls_source, helper_source, pid(), started_at, call_id });
}

/// The normal named-host resolver supplies its already validated endpoint to the
/// same log hook. Keep administration/atomic I/O in the existing friction module.
pub fn namedHostPython(allocator: std.mem.Allocator, source: []const u8) ![]const u8 {
    const friction_source = try std.json.Stringify.valueAlloc(allocator, @embedFile("friction.py"), .{});
    const helper = try std.fmt.allocPrint(allocator, "import types,sys\n_friction=types.ModuleType('teerex_friction')\nexec({s},_friction.__dict__)\nsys.modules['teerex_friction']=_friction\n{s}", .{ friction_source, source });
    return python(allocator, helper);
}
