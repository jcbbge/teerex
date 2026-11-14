const std = @import("std");
const state = @import("rex_send").clutch_state;
const usage =
    \\Usage: teerex clutch take|release|status|queue --socket ABS --session session:UUID --pane block:UUID [--reason TEXT]
    \\queue [--json] [--show]: inspect ordered pending/inflight ids, sender, age, first line; --show includes bodies.
    \\Held panes queue native sends without input; send --no-queue retains bounded wait/refusal.
    \\release deletes the hold and drains through guarded send. Failed drain stops; uncertain claims never replay.
    \\Private state: TEEREX_CLUTCH_DIR or ~/.local/state/teerex/clutch (0700), per canonical socket/session/pane.
    \\prune [--apply]: plan/remove released records whose socket/session/pane is absent; preserves held/unknown. Python3.9+.
    \\status/queue read only; release also drains any pending queue on repeat. status is saved state, not live evidence.
    \\No expiry, automatic release, background drain or retry loop. Python3.9+ required for queue/drain.
    \\Store errors produce named failure_reason; send treats unreadable state as unknown and continues.
    \\Binds teerex writers only, never raw Rex writers or human keys. Not a server input lease.
    \\Palette: teerex clutch palette --file ABS --socket ABS [--teerex ABS]
    \\Creates a new native two-action fragment; register with surfaces palette install plan/apply.
    \\Palette generation does not reload config or type. Hand back calls release, which may drain queued input.
    \\Exit: 0 recorded/status/queue/drained/generated; 1 unavailable/refused or drain stopped; 2 usage.
    \\
;
fn valid(value: []const u8, prefix: []const u8) bool {
    if (!std.mem.startsWith(u8, value, prefix) or value.len != prefix.len + 36) return false;
    for (value[prefix.len..], 0..) |c, i| {
        if (i == 8 or i == 13 or i == 18 or i == 23) {
            if (c != '-') return false;
        } else if (!std.ascii.isHex(c) or std.ascii.isUpper(c)) return false;
    }
    return true;
}
fn usageError(reason: []const u8) u8 {
    std.debug.print("teerex clutch: {s}\n{s}", .{ reason, usage });
    return 2;
}
fn execute(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    if (args.len == 1 and std.mem.eql(u8, args[0], "--help")) {
        try std.fs.File.stdout().writeAll(usage);
        return 0;
    }
    if (args.len > 0 and std.mem.eql(u8, args[0], "palette")) {
        var argv: std.ArrayList([]const u8) = .empty;
        try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", @embedFile("palette.py"), try std.fs.selfExePathAlloc(allocator) });
        try argv.appendSlice(allocator, args[1..]);
        return std.process.execv(allocator, argv.items);
    }
    if (args.len > 0 and std.mem.eql(u8, args[0], "prune")) {
        var argv: std.ArrayList([]const u8) = .empty;
        try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", @embedFile("prune.py") });
        try argv.appendSlice(allocator, args[1..]);
        return std.process.execv(allocator, argv.items);
    }
    var options = std.StringHashMap([]const u8).init(allocator);
    if (args.len == 0 or (!std.mem.eql(u8, args[0], "take") and !std.mem.eql(u8, args[0], "release") and !std.mem.eql(u8, args[0], "status") and !std.mem.eql(u8, args[0], "queue"))) {
        try std.fs.File.stderr().writeAll(usage);
        return 2;
    }
    const queue = std.mem.eql(u8, args[0], "queue");
    var show = false;
    var json = false;
    var i: usize = 1;
    while (i < args.len) {
        if (queue and std.mem.eql(u8, args[i], "--show") and !show) {
            show = true;
            i += 1;
            continue;
        }
        if (queue and std.mem.eql(u8, args[i], "--json") and !json) {
            json = true;
            i += 1;
            continue;
        }
        if (i + 1 >= args.len or options.contains(args[i])) return usageError("InvalidClutchOptions");
        var known = false;
        for ([_][]const u8{ "--socket", "--session", "--pane", "--reason" }) |key| {
            if (std.mem.eql(u8, key, args[i])) known = true;
        }
        if (!known) return usageError("InvalidClutchOptions");
        try options.put(args[i], args[i + 1]);
        i += 2;
    }
    const socket = options.get("--socket") orelse return usageError("ClutchSocketRequired");
    const session = options.get("--session") orelse return usageError("ClutchSessionRequired");
    const pane = options.get("--pane") orelse return usageError("ClutchPaneRequired");
    const reason = options.get("--reason") orelse "";
    if (std.mem.eql(u8, args[0], "take")) try @import("pane_guard").checkTake(allocator, socket, session, pane);
    if (!std.fs.path.isAbsolute(socket) or !valid(session, "session:") or !valid(pane, "block:") or reason.len > 512 or !std.unicode.utf8ValidateSlice(reason)) return usageError("InvalidClutchTargetOrReason");
    for (reason) |c| if (c < 32 or c == 127) return usageError("InvalidClutchReason");
    const env = try std.process.getEnvMap(allocator);
    const status = queue or std.mem.eql(u8, args[0], "status");
    var store = if (status) try state.Store.openRead(allocator, &env, socket, session, pane) else try state.Store.open(allocator, &env, socket, session, pane);
    defer store.close();
    if (queue) {
        var argv: std.ArrayList([]const u8) = .empty;
        try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", @import("rex_send").queue_source, "inspect", store.path });
        if (show) try argv.append(allocator, "--show");
        return std.process.execv(allocator, argv.items);
    }
    var changed = false;
    var saved: ?state.State = null;
    if (status) {
        saved = try store.read(allocator);
    } else {
        const result = try store.set(allocator, std.mem.eql(u8, args[0], "take"), reason);
        changed = result.changed;
        saved = result.state;
    }
    const raw = try std.json.Stringify.valueAlloc(allocator, .{ .schema_version = 1, .kind = "clutch_result", .operation = args[0], .held = if (saved) |s| s.held else false, .changed = changed, .record = saved, .state_file = store.path, .target = .{ .socket = store.socket, .session = session, .pane = pane }, .cooperative = true, .server_enforced = false, .pane_liveness = "not_assessed" }, .{});
    if (std.mem.eql(u8, args[0], "release")) {
        const argv = [_][]const u8{ "python3", "-I", "-c", @import("rex_send").queue_source, "drain", store.path, try std.fs.selfExePathAlloc(allocator), raw };
        return std.process.execv(allocator, &argv);
    }
    try std.fs.File.stdout().writeAll(raw);
    try std.fs.File.stdout().writeAll("\n");
    return 0;
}

pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    return execute(allocator, args) catch |err| {
        const raw = try std.json.Stringify.valueAlloc(allocator, .{ .schema_version = 1, .kind = "clutch_result", .outcome = "refused", .state = "unknown", .failure_reason = state.failureReason(err), .cooperative = true, .server_enforced = false }, .{});
        try std.fs.File.stdout().writeAll(raw);
        try std.fs.File.stdout().writeAll("\n");
        return 1;
    };
}
