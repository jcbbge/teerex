const std = @import("std");
const flag_names = @import("flagnames.zig");
pub const limit = 4 * 1024 * 1024;

// Invariants: private consent gates every append; argv/values never enter a
// record. Only compiled names, counts, validated caller names and HMAC keys do.
pub fn name(value: ?[]const u8) ?[]const u8 {
    const s = value orelse return null;
    if (s.len == 0 or s.len > 64 or !(std.ascii.isLower(s[0]) or std.ascii.isDigit(s[0]))) return null;
    for (s) |c| if (!(std.ascii.isLower(c) or std.ascii.isDigit(c) or c == '.' or c == '_' or c == '-')) return null;
    return s;
}

fn private(fd: std.posix.fd_t) !void {
    const s = try std.posix.fstat(fd);
    if (s.uid != std.posix.getuid() or s.mode & 0o7777 != 0o600 or s.mode & std.posix.S.IFMT != std.posix.S.IFREG or s.nlink != 1) return error.InsecureFrictionFile;
}
fn read(allocator: std.mem.Allocator, dir: std.posix.fd_t, path: []const u8, cap: usize) ![]u8 {
    const fd = try std.posix.openat(dir, path, .{ .ACCMODE = .RDONLY, .NOFOLLOW = true, .CLOEXEC = true, .NONBLOCK = true }, 0);
    defer std.posix.close(fd);
    try private(fd);
    return (std.fs.File{ .handle = fd }).readToEndAlloc(allocator, cap);
}
fn key(allocator: std.mem.Allocator, salt: []const u8, value: []const u8) ![]const u8 {
    var digest: [32]u8 = undefined;
    std.crypto.auth.hmac.sha2.HmacSha256.create(&digest, value, salt);
    const hex = std.fmt.bytesToHex(digest[0..8].*, .lower);
    return std.fmt.allocPrint(allocator, "k:{s}", .{hex});
}
const Consent = struct { schema_version: u8, enabled_at: i64, expires_at: i64, scope: []const u8, enabled_by: []const u8 };

pub fn collect(allocator: std.mem.Allocator, dir: std.posix.fd_t, call_id: []const u8, at: i64, version: []const u8, verb: []const u8, subverb: ?[]const u8, resolver: ?*const fn (std.mem.Allocator, []const []const u8) anyerror!?[]const u8) !?[]const u8 {
    const raw = read(allocator, dir, "friction-consent.json", 32 * 1024) catch return null;
    const consent = (std.json.parseFromSlice(Consent, allocator, raw, .{ .ignore_unknown_fields = true }) catch return null).value;
    if (consent.schema_version != 1 or consent.enabled_at < 0 or name(consent.enabled_by) == null or consent.expires_at <= at or consent.enabled_at > at or consent.expires_at - consent.enabled_at > 30 * 86400000 or consent.expires_at <= consent.enabled_at) return null;
    const via_raw = std.posix.getenv("TEEREX_CALLER");
    const via = name(via_raw);
    if (!std.mem.eql(u8, consent.scope, "all")) {
        if (!std.mem.startsWith(u8, consent.scope, "callers:") or via == null) return null;
        var scopes = std.mem.splitScalar(u8, consent.scope[8..], ',');
        var selected = false;
        var seen: std.StringHashMap(void) = .init(allocator);
        while (scopes.next()) |scope| {
            if (name(scope) == null or seen.count() >= 64 or seen.contains(scope)) return null;
            try seen.put(scope, {});
            if (std.mem.eql(u8, via.?, scope)) selected = true;
        }
        if (!selected) return null;
    }
    const salt = read(allocator, dir, "friction-salt", 32) catch return null;
    if (salt.len != 32) return null;
    const args = (try std.process.argsAlloc(allocator))[1..];
    var flags: std.ArrayList([]const u8) = .empty;
    var positionals: usize = 0;
    var other: usize = 0;
    var after = false;
    var options = false;
    var words: usize = 0;
    const server = if (resolver) |resolve| resolve(allocator, args) catch null else null;
    var target_unknown = false;
    for (args) |arg| {
        if (after) {
            positionals += 1;
            other += 1;
            continue;
        }
        if (std.mem.eql(u8, arg, "--")) {
            after = true;
            continue;
        }
        if (std.mem.startsWith(u8, arg, "--")) {
            options = true;
            const end = std.mem.indexOfScalar(u8, arg, '=') orelse arg.len;
            const flag = arg[2..end];
            if (flag_names.allowed(flag)) {
                var duplicate = false;
                for (flags.items) |old| if (std.mem.eql(u8, old, flag)) {
                    duplicate = true;
                    break;
                };
                if (!duplicate) try flags.append(allocator, flag);
                if (end < arg.len) other += 1;
            } else other += 1;
            if (std.mem.eql(u8, flag, "config") or std.mem.eql(u8, flag, "host")) target_unknown = server == null;
        } else if (!options and words < 2) {
            words += 1;
        } else {
            other += 1;
            if (!options) positionals += 1;
        }
    }
    std.mem.sort([]const u8, flags.items, {}, struct {
        fn less(_: void, a: []const u8, b: []const u8) bool {
            return std.mem.order(u8, a, b) == .lt;
        }
    }.less);
    const cwd = try std.fs.cwd().realpathAlloc(allocator, ".");
    var ancestor: ?[]const u8 = cwd;
    var repo: ?[]const u8 = null;
    while (ancestor) |path| {
        const git = try std.fs.path.join(allocator, &.{ path, ".git" });
        if (std.fs.cwd().statFile(git)) |_| {
            repo = path;
            break;
        } else |_| {}
        ancestor = std.fs.path.dirname(path);
    }
    const agent = name(std.posix.getenv("AGENT_NAME"));
    const pane = std.posix.getenv("AGENT_PANE") orelse std.posix.getenv("REX_BLOCK") orelse std.posix.getenv("LC_REX_BLOCK") orelse "";
    const episode = try std.fmt.allocPrint(allocator, "{s}\x00{s}", .{ agent orelse "", pane });
    const stdin_stat = try std.posix.fstat(std.posix.STDIN_FILENO);
    const stdin_kind = stdin_stat.mode & std.posix.S.IFMT;
    var host_buffer: [std.posix.HOST_NAME_MAX]u8 = undefined;
    const host = try std.posix.gethostname(&host_buffer);
    const record = try std.json.Stringify.valueAlloc(allocator, .{
        .schema_version = 1,
        .call_id = call_id,
        .ts = at,
        .shape = .{ .verb = verb, .subverb = subverb, .flags = flags.items, .positionals = positionals, .other_tokens = other, .stdin = stdin_kind == std.posix.S.IFIFO or stdin_kind == std.posix.S.IFREG },
        .context = .{ .host = host, .cwd_key = try key(allocator, salt, cwd), .repo_key = if (repo) |r| try key(allocator, salt, r) else null, .target_unknown = target_unknown, .server_key = if (server) |s| try key(allocator, salt, s) else null, .version = version },
        .caller = .{ .via = via, .via_invalid = via_raw != null and via == null, .agent_name = agent, .episode_key = try key(allocator, salt, episode) },
    }, .{});
    const line = try std.fmt.allocPrint(allocator, "{s}\n", .{record});
    var fd = try std.posix.openat(dir, "friction.jsonl", .{ .ACCMODE = .WRONLY, .APPEND = true, .CREAT = true, .NOFOLLOW = true, .CLOEXEC = true, .NONBLOCK = true }, 0o600);
    defer std.posix.close(fd);
    try private(fd);
    if ((try std.posix.fstat(fd)).size + @as(i64, @intCast(line.len)) > limit) {
        const old = std.posix.openat(dir, "friction.jsonl.1", .{ .ACCMODE = .RDONLY, .NOFOLLOW = true, .CLOEXEC = true, .NONBLOCK = true }, 0) catch |err| switch (err) {
            error.FileNotFound => null,
            else => return err,
        };
        if (old) |f| {
            defer std.posix.close(f);
            try private(f);
        }
        try std.posix.renameat(dir, "friction.jsonl", dir, "friction.jsonl.1");
        const next = try std.posix.openat(dir, "friction.jsonl", .{ .ACCMODE = .WRONLY, .APPEND = true, .CREAT = true, .EXCL = true, .NOFOLLOW = true, .CLOEXEC = true }, 0o600);
        std.posix.close(fd);
        fd = next;
    }
    if (try std.posix.write(fd, line) != line.len) return error.PartialFrictionWrite;
    return "written";
}
