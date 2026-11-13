const std = @import("std");

pub const State = struct {
    schema_version: u8 = 1,
    socket: []const u8,
    session: []const u8,
    pane: []const u8,
    held: bool,
    at_unix_ms: i64,
    reason: []const u8,
};

pub fn privateStat(fd: std.posix.fd_t, directory: bool) !void {
    const s = try std.posix.fstat(fd);
    if (s.uid != std.posix.getuid() or (s.mode & 0o7777) != (if (directory) @as(u32, 0o700) else @as(u32, 0o600)) or
        (s.mode & std.posix.S.IFMT) != (if (directory) @as(u32, std.posix.S.IFDIR) else @as(u32, std.posix.S.IFREG)) or
        (!directory and s.nlink != 1)) return error.ClutchStateNotPrivateOwned;
}

pub const Store = struct {
    dir: ?std.fs.Dir,
    path: []const u8,
    name: []const u8,
    socket: []const u8,
    session: []const u8,
    pane: []const u8,

    pub fn open(allocator: std.mem.Allocator, env: *const std.process.EnvMap, socket: []const u8, session: []const u8, pane: []const u8) !Store {
        return openMode(allocator, env, socket, session, pane, true);
    }

    pub fn openRead(allocator: std.mem.Allocator, env: *const std.process.EnvMap, socket: []const u8, session: []const u8, pane: []const u8) !Store {
        return openMode(allocator, env, socket, session, pane, false);
    }

    fn openMode(allocator: std.mem.Allocator, env: *const std.process.EnvMap, socket: []const u8, session: []const u8, pane: []const u8, create: bool) !Store {
        const root = env.get("TEEREX_CLUTCH_DIR") orelse try std.fs.path.join(allocator, &.{ env.get("HOME") orelse return error.HomeRequiredForClutch, ".local/state/teerex/clutch" });
        if (!std.fs.path.isAbsolute(root)) return error.AbsoluteClutchDirectoryRequired;
        // Parents are trusted operator filesystem context; the leaf never follows a symlink.
        if (create) {
            if (std.fs.path.dirname(root)) |parent| try std.fs.cwd().makePath(parent);
            std.posix.mkdir(root, 0o700) catch |err| if (err != error.PathAlreadyExists) return err;
        }
        var dir: ?std.fs.Dir = std.fs.openDirAbsolute(root, .{ .no_follow = true, .iterate = true }) catch |err| switch (err) {
            error.FileNotFound => if (!create) null else return err,
            else => return err,
        };
        errdefer if (dir) |*d| d.close();
        if (dir) |d| try privateStat(d.fd, true);
        // Darwin cannot open Unix sockets as regular files. Resolve paths through POSIX realpath.
        var canonical_buffer: [std.fs.max_path_bytes]u8 = undefined;
        const resolved = std.posix.realpath(socket, &canonical_buffer) catch |err| switch (err) {
            error.FileNotFound => socket,
            else => return error.ClutchSocketCanonicalizationFailed,
        };
        const canonical = try allocator.dupe(u8, resolved);
        var hash = std.crypto.hash.sha2.Sha256.init(.{});
        hash.update(canonical);
        hash.update("\x00");
        hash.update(session);
        hash.update("\x00");
        hash.update(pane);
        var digest: [32]u8 = undefined;
        hash.final(&digest);
        const name = try std.fmt.allocPrint(allocator, "{s}.json", .{std.fmt.bytesToHex(digest, .lower)});
        return .{ .dir = dir, .path = try std.fs.path.join(allocator, &.{ root, name }), .name = name, .socket = canonical, .session = session, .pane = pane };
    }

    pub fn close(self: *Store) void {
        if (self.dir) |*dir| dir.close();
    }

    pub fn read(self: *Store, allocator: std.mem.Allocator) !?State {
        const dir = self.dir orelse return null;
        const fd = std.posix.openat(dir.fd, self.name, .{ .ACCMODE = .RDONLY, .NOFOLLOW = true, .NONBLOCK = true, .CLOEXEC = true }, 0) catch |err| switch (err) {
            error.FileNotFound => return null,
            else => return err,
        };
        const file: std.fs.File = .{ .handle = fd };
        defer file.close();
        try privateStat(fd, false);
        const raw = try file.readToEndAlloc(allocator, 8192);
        const state = (try std.json.parseFromSlice(State, allocator, raw, .{ .allocate = .alloc_always })).value;
        if (state.schema_version != 1 or !std.mem.eql(u8, state.socket, self.socket) or
            !std.mem.eql(u8, state.session, self.session) or !std.mem.eql(u8, state.pane, self.pane) or
            state.reason.len > 512 or state.at_unix_ms <= 0) return error.InvalidClutchState;
        return state;
    }

    pub fn set(self: *Store, allocator: std.mem.Allocator, desired: bool, reason: []const u8) !struct { changed: bool, state: ?State } {
        const dir = self.dir orelse return error.ClutchStateUnavailable;
        // Darwin can transiently return ENOENT while cooperating creators open the same lock.
        var attempts: usize = 0;
        const fd = while (true) : (attempts += 1) {
            break std.posix.openat(dir.fd, "clutch.lock", .{ .ACCMODE = .RDWR, .CREAT = true, .NOFOLLOW = true, .NONBLOCK = true, .CLOEXEC = true }, 0o600) catch |err| switch (err) {
                error.FileNotFound => if (attempts < 200) {
                    std.Thread.sleep(5 * std.time.ns_per_ms);
                    continue;
                } else return error.ClutchLockCreationUnavailable,
                else => return err,
            };
        };
        const lock: std.fs.File = .{ .handle = fd };
        defer lock.close();
        try privateStat(fd, false);
        // Mutations only; never wait behind a sender or a draft guard.
        var timer = try std.time.Timer.start();
        while (true) {
            std.posix.flock(fd, std.posix.LOCK.EX | std.posix.LOCK.NB) catch |err| {
                if (err != error.WouldBlock or timer.read() / std.time.ns_per_ms >= 1000) return err;
                std.Thread.sleep(5 * std.time.ns_per_ms);
                continue;
            };
            break;
        }
        const previous = try self.read(allocator);
        if (!desired) {
            if (previous != null) {
                try dir.deleteFile(self.name);
                try std.posix.fsync(dir.fd);
            }
            return .{ .changed = if (previous) |p| p.held else false, .state = null };
        }
        if (previous) |state| if (state.held) return .{ .changed = false, .state = state };
        const held = true;
        const state: State = .{ .socket = self.socket, .session = self.session, .pane = self.pane, .held = held, .reason = reason, .at_unix_ms = std.time.milliTimestamp() };
        const stage = try std.fmt.allocPrint(allocator, "{s}.next", .{self.name});
        const out_fd = try std.posix.openat(dir.fd, stage, .{ .ACCMODE = .WRONLY, .CREAT = true, .EXCL = true, .NOFOLLOW = true, .CLOEXEC = true }, 0o600);
        const out: std.fs.File = .{ .handle = out_fd };
        defer out.close();
        defer dir.deleteFile(stage) catch {};
        try out.writeAll(try std.json.Stringify.valueAlloc(allocator, state, .{}));
        try out.sync();
        try dir.rename(stage, self.name);
        try std.posix.fsync(dir.fd);
        return .{ .changed = previous != null or held, .state = state };
    }
};

pub fn failureReason(err: anyerror) []const u8 {
    return switch (err) {
        error.Unexpected => "clutch_state_system_error",
        else => @errorName(err),
    };
}
