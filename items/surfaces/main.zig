const std = @import("std");
const supervised = @import("supervised_child");

const usage =
    \\Usage: teerex surfaces resolve --socket ABS --session TEXT [--pane TEXT | --window TEXT]
    \\       teerex surfaces resolve --socket ABS --session any --pane TEXT
    \\       teerex surfaces ensure --socket ABS --session any --label TEXT --create-session TEXT
    \\         [--focus yes|no] [open options; layout defaults tab] -- ARGV...
    \\"any" searches terminal pane labels across all sessions; --create-session is used only when absent.
    \\All pane ensure calls serialize by canonical socket under $XDG_STATE_HOME/teerex-surfaces
    \\(default ~/.local/state/teerex-surfaces). --timeout-ms bounds lock wait plus transport;
    \\ensure_busy refuses before mutation and is retry-safe. Successful receipts name ensure_lock.
    \\       teerex surfaces session ensure --socket ABS --label TEXT [--timeout-ms N]
    \\       teerex surfaces ensure --socket ABS --session TEXT --label TEXT [--focus yes|no]
    \\         [open options; layout defaults tab] -- ARGV...
    \\Resolve accepts canonical IDs, unique ID suffixes, exact labels; refuses ambiguity with candidates.
    \\All surfaces target options accept these selectors; requested preserves input, resolved carries IDs.
    \\Session ensure returns existing/created (fresh label/ID readback); creates an empty session, no focus.
    \\Pane ensure reuses a uniquely labelled pane/tab or opens once, focus defaults no. No automatic retry.
    \\       teerex surfaces open --socket ABS --session session:UUID --layout tiled|float|tab
    \\         --label TEXT [--anchor block:UUID] [--direction right|left|up|down] [--ratio N]
    \\         [--bounds '[x,y,w,h]'] [--cwd ABS] [--timeout-ms N] -- ARGV...
    \\       teerex surfaces inspect|focus|close --socket ABS --session session:UUID --pane block:UUID [--timeout-ms N]
    \\       teerex surfaces rename --socket ABS --session session:UUID (--window window:UUID | --pane block:UUID)
    \\         --label TEXT [--timeout-ms N]
    \\Rename requires the server-advertised label method; fresh label/focus readback, no focus request or retry.
    \\       teerex surfaces move --socket ABS --session session:UUID --pane block:UUID --anchor block:UUID
    \\         [--direction right|left|up|down] [--ratio N] [--focus yes|no] [--timeout-ms N]
    \\Move preserves the same attached terminal; no creation. NEW pane share; focus defaults no and refuses
    \\a focused source because Rex moves its focus too. Explicit yes permits that and verifies focus.
    \\Focus explicitly selects the pane/window. Close explicitly ends that block, including the last pane;
    \\close verifies absence from view/list, not death of all descendant/remote processes.
    \\       teerex surfaces palette agents --file ABS --teerex ABS --rex ABS [--profiles ABS]
    \\       teerex surfaces palette hosts --file ABS --teerex ABS [--config ABS]
    \\Generates native profile/workspace menus, frozen until regenerated; never changes personal config.
    \\Profiles/hosts default to ~/.config/teerex/{profiles,hosts}.json. Install generated menus via plan/apply.
    \\Agent actions take name/brief_file, or open a visible name/brief form; managed launch handles ACK.
    \\Host actions use optional hosts.NAME.workspaces (label -> cwd, argv, session label), default home shell.
    \\       teerex surfaces palette install --init ABS --file ABS --socket ABS --plan ABS [--apply PLAN_SHA256]
    \\Plan previews native config inclusion and one reload; apply requires the unchanged plan's printed hash.
    \\Requires Python3.9+. Checks selected server config path/instance and actual action source after reload.
    \\       teerex surfaces palette --file ABS --name ACTION --title TEXT --layout tiled|float|tab
    \\         --label TEXT [--direction D --ratio N | --bounds '[x,y,w,h]'] [--cwd ABS] -- ARGV...
    \\Open actual terminal programs, not graphical widgets. Tiled/float need an attached terminal anchor;
    \\tab forbids one. Tiled defaults right, NEW pane share 1/3 (not Rex's before ratio). Float requires
    \\explicit fractional bounds inside the window. Tab forbids ratio/direction/bounds. No fallback/retry.
    \\Fresh session.view readback returns actual normalized geometry/label/host, not pixel or paint proof.
    \\Open never requests focus or auto-close; no detached worker/autostart. API10..13; Unix; rex on PATH.
    \\Palette creates a NEW fragment (no overwrite/reload); palette install plans/applies native inclusion
    \\and verifies registration. Then use ACTION via Rex's palette or rex do.
    \\Palette uses the invoking session/pane, never a baked-in personal target; programs stay attached.
    \\Deadline defaults 5000ms (100..60000), plus bounded cleanup. Inspect before any uncertain retry.
    \\Exit: 0 stated postcondition/fragment/plan verified; 1 refusal/mismatch/uncertain;
    \\2 usage; 124 deadline; 130/143 cancellation. Program readiness/painted visibility not assessed.
    \\
;

const SurfaceResult = struct {
    outcome: []const u8,
    source: std.json.Value = .null,
    resolved: std.json.Value = .null,
    candidates: std.json.Value = .null,
    created: std.json.Value = .null,
    actual: std.json.Value = .null,
    previous: std.json.Value = .null,
    previous_anchor: std.json.Value = .null,
    move_receipt: std.json.Value = .null,
    focus_acknowledged: bool = false,
    control_attempted: bool = false,
    control_acknowledged: bool = false,
    block_absence_verified: bool = false,
    creation_attempted: bool = false,
    requested_geometry_verified: bool = false,
    requested_label_verified: bool = false,
    failure_reason: ?[]const u8 = null,
};
fn ensureFocusVerified(r: SurfaceResult) bool {
    if (r.actual != .object or (!r.control_acknowledged and !r.focus_acknowledged)) return false;
    const active = r.actual.object.get("in_active_window") orelse return false;
    const focused = r.actual.object.get("focused_block_id") orelse return false;
    const block = r.actual.object.get("block_id") orelse return false;
    return active == .bool and active.bool and focused == .string and block == .string and std.mem.eql(u8, focused.string, block.string);
}
const Frame = struct { event: []const u8, control: bool = false, result: ?SurfaceResult = null, created: std.json.Value = .null };
const Collector = struct {
    allocator: std.mem.Allocator,
    pending: std.ArrayList(u8) = .empty,
    attempt: bool = false,
    control: bool = false,
    created: std.json.Value = .null,
    result: ?SurfaceResult = null,
    count: u8 = 0,
    pub fn receive(self: *Collector, bytes: []const u8) !void {
        if (bytes.len > 32768 - self.pending.items.len) return error.SurfaceFrameTooLarge;
        try self.pending.appendSlice(self.allocator, bytes);
        while (std.mem.indexOfScalar(u8, self.pending.items, '\n')) |end| {
            if (self.result != null or self.count >= 3) return error.InvalidSurfaceFrame;
            self.count += 1;
            const frame = (try std.json.parseFromSlice(Frame, self.allocator, self.pending.items[0..end], .{ .allocate = .alloc_always, .ignore_unknown_fields = true })).value;
            if (std.mem.eql(u8, frame.event, "attempt") and !self.attempt) {
                self.attempt = true;
                self.control = frame.control;
            } else if (std.mem.eql(u8, frame.event, "created") and self.attempt and self.created == .null and frame.created == .object) {
                self.created = frame.created;
            } else if (std.mem.eql(u8, frame.event, "result")) {
                self.result = frame.result orelse return error.InvalidSurfaceFrame;
                if ((self.result.?.creation_attempted or self.result.?.control_attempted) != self.attempt) return error.InvalidSurfaceFrame;
            } else return error.InvalidSurfaceFrame;
            try self.pending.replaceRange(self.allocator, 0, end + 1, &.{});
        }
    }
};

fn fullId(value: []const u8, prefix: []const u8) bool {
    if (!std.mem.startsWith(u8, value, prefix) or value.len != prefix.len + 36) return false;
    for (value[prefix.len..], 0..) |c, i| {
        if (i == 8 or i == 13 or i == 18 or i == 23) {
            if (c != '-') return false;
        } else if (!std.ascii.isHex(c) or std.ascii.isUpper(c)) return false;
    }
    return true;
}
fn selectorValid(value: []const u8, prefix: []const u8) bool {
    if (std.mem.startsWith(u8, value, prefix)) return fullId(value, prefix);
    return labelValid(value);
}
fn labelValid(s: []const u8) bool {
    if (s.len == 0 or s.len > 128 or !std.unicode.utf8ValidateSlice(s)) return false;
    for (s) |c| if (c < 32 or c == 127) return false;
    return true;
}
const EnsureLock = struct {
    file: std.fs.File,
    path: []const u8,
    waited_ms: u64,
};
fn ensureLock(allocator: std.mem.Allocator, socket: []const u8, budget: u64) !EnsureLock {
    var timer = try std.time.Timer.start();
    // Dir.realpathAlloc opens the final path; Darwin cannot open a Unix socket as a file.
    // POSIX realpath uses libc path resolution on Darwin and preserves socket symlink identity.
    var canonical_buffer: [std.fs.max_path_bytes]u8 = undefined;
    const canonical = try std.posix.realpath(socket, &canonical_buffer);
    var digest: [32]u8 = undefined;
    std.crypto.hash.sha2.Sha256.hash(canonical, &digest, .{});
    const hex = std.fmt.bytesToHex(digest, .lower);
    const state = std.process.getEnvVarOwned(allocator, "XDG_STATE_HOME") catch try std.fs.path.join(allocator, &.{ try std.process.getEnvVarOwned(allocator, "HOME"), ".local", "state" });
    if (!std.fs.path.isAbsolute(state)) return error.EnsureStatePathMustBeAbsolute;
    try std.fs.cwd().makePath(state);
    const root = try std.fs.path.join(allocator, &.{ state, "teerex-surfaces" });
    std.posix.mkdir(root, 0o700) catch |err| if (err != error.PathAlreadyExists) return err;
    var dir = try std.fs.openDirAbsolute(root, .{ .no_follow = true });
    defer dir.close();
    const info = try std.posix.fstat(dir.fd);
    if (info.uid != std.posix.getuid() or (info.mode & 0o7777) != 0o700) return error.EnsureStateDirectoryNotPrivate;
    const name = try std.fmt.allocPrint(allocator, "server-{s}.lock", .{hex});
    // Match the registry's bounded retry for macOS concurrent O_CREAT/ENOENT.
    const fd = while (true) {
        if (supervised.requestedSignal() != 0) return error.EnsureWaitCancelled;
        if (timer.read() / std.time.ns_per_ms >= budget) return error.EnsureBusy;
        break std.posix.openat(dir.fd, name, .{ .ACCMODE = .RDWR, .CREAT = true, .NOFOLLOW = true, .CLOEXEC = true, .NONBLOCK = true }, 0o600) catch |err| {
            if (err != error.FileNotFound) return err;
            std.Thread.sleep(5 * std.time.ns_per_ms);
            continue;
        };
    };
    const file: std.fs.File = .{ .handle = fd };
    errdefer file.close();
    const stat = try std.posix.fstat(fd);
    if (stat.uid != std.posix.getuid() or (stat.mode & 0o7777) != 0o600 or (stat.mode & std.posix.S.IFMT) != std.posix.S.IFREG or stat.nlink != 1) return error.EnsureLockNotPrivateRegular;
    while (true) {
        if (supervised.requestedSignal() != 0) return error.EnsureWaitCancelled;
        if (timer.read() / std.time.ns_per_ms >= budget) return error.EnsureBusy;
        if (try file.tryLock(.exclusive)) break;
        std.Thread.sleep(5 * std.time.ns_per_ms);
    }
    return .{ .file = file, .path = try std.fs.path.join(allocator, &.{ root, name }), .waited_ms = timer.read() / std.time.ns_per_ms };
}
fn usageError(message: []const u8) u8 {
    std.debug.print("teerex surfaces: {s}\n{s}", .{ message, usage });
    return 2;
}
fn writeJson(allocator: std.mem.Allocator, value: anytype) !void {
    const s = try std.json.Stringify.valueAlloc(allocator, value, .{ .whitespace = .indent_2 });
    try std.fs.File.stdout().writeAll(s);
    try std.fs.File.stdout().writeAll("\n");
}
fn encodedDiagnostic(allocator: std.mem.Allocator, bytes: []const u8) ![]const u8 {
    const encoder = std.base64.standard.Encoder;
    const buffer = try allocator.alloc(u8, encoder.calcSize(bytes.len));
    return encoder.encode(buffer, bytes);
}
fn luaString(allocator: std.mem.Allocator, input: []const u8) ![]const u8 {
    var out: std.ArrayList(u8) = .empty;
    try out.append(allocator, '"');
    for (input) |c| {
        if (c == '"' or c == '\\') {
            try out.append(allocator, '\\');
            try out.append(allocator, c);
        } else if (c < 32 or c == 127) {
            try out.appendSlice(allocator, try std.fmt.allocPrint(allocator, "\\{d:0>3}", .{c}));
        } else try out.append(allocator, c);
    }
    try out.append(allocator, '"');
    return out.items;
}

const RawOutput = struct {
    allocator: std.mem.Allocator,
    bytes: std.ArrayList(u8) = .empty,
    pub fn receive(self: *RawOutput, bytes: []const u8) !void {
        if (bytes.len > 32768 - self.bytes.items.len) return error.PaletteOutputTooLarge;
        try self.bytes.appendSlice(self.allocator, bytes);
    }
};
fn paletteController(allocator: std.mem.Allocator, args: []const []const u8, script: []const u8) !u8 {
    if (args.len > 0 and std.mem.eql(u8, args[args.len - 1], "--help")) {
        try std.fs.File.stdout().writeAll(usage);
        return 0;
    }
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.appendSlice(allocator, &.{ "python3", "-I", "-c", try @import("rex_boards").call_log.python(allocator, script) });
    try argv.appendSlice(allocator, args);
    var env = try std.process.getEnvMap(allocator);
    for ([_][]const u8{ "REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT" }) |key| env.remove(key);
    const signals = supervised.Signals.init();
    defer signals.deinit();
    var output: RawOutput = .{ .allocator = allocator };
    var failure: ?[]const u8 = null;
    const result = supervised.collect(allocator, argv.items, &env, 15000, &output) catch |err| blk: {
        failure = @errorName(err);
        break :blk null;
    };
    const sig = supervised.requestedSignal();
    const deadline = result != null and result.?.deadline_exceeded;
    if (sig == 0 and result != null and !result.?.stopped and result.?.term == .Exited) {
        if (result.?.term.Exited == 2) {
            try std.fs.File.stderr().writeAll(result.?.stderr);
            return 2;
        }
        const parsed = std.json.parseFromSlice(std.json.Value, allocator, output.bytes.items, .{}) catch null;
        if (parsed != null and parsed.?.value == .object) {
            try std.fs.File.stdout().writeAll(output.bytes.items);
            return result.?.term.Exited;
        }
    }
    try writeJson(allocator, .{ .schema_version = 1, .kind = "surface_palette_install_result", .outcome = "uncertain", .registered_in_running_server = false, .config_updated = "unknown", .failure_reason = failure orelse "palette_install_transport_incomplete", .backend_stderr_base64 = try encodedDiagnostic(allocator, if (result) |r| r.stderr else ""), .retry_safe = false });
    return if (sig != 0) 128 + sig else if (deadline) 124 else 1;
}

pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    if (args.len == 1 and std.mem.eql(u8, args[0], "--help")) {
        try std.fs.File.stdout().writeAll(usage);
        return 0;
    }
    if (args.len >= 2 and std.mem.eql(u8, args[0], "palette") and std.mem.eql(u8, args[1], "install")) return paletteController(allocator, args[2..], @embedFile("palette.py"));
    if (args.len >= 2 and std.mem.eql(u8, args[0], "palette") and (std.mem.eql(u8, args[1], "agents") or std.mem.eql(u8, args[1], "hosts"))) return paletteController(allocator, args[1..], @embedFile("menu.py"));
    if (args.len == 0) return usageError("resolve, session ensure, ensure, open, inspect, rename, focus, close, move or palette is required");
    if (args.len >= 2 and std.mem.eql(u8, args[0], "session") and std.mem.eql(u8, args[1], "ensure")) {
        var translated: std.ArrayList([]const u8) = .empty;
        try translated.append(allocator, "session-ensure");
        try translated.appendSlice(allocator, args[2..]);
        return run(allocator, translated.items);
    }
    const resolve = std.mem.eql(u8, args[0], "resolve");
    const session_ensure = std.mem.eql(u8, args[0], "session-ensure");
    const ensure = std.mem.eql(u8, args[0], "ensure");
    const inspect = std.mem.eql(u8, args[0], "inspect");
    const focus = std.mem.eql(u8, args[0], "focus");
    const close = std.mem.eql(u8, args[0], "close");
    const move = std.mem.eql(u8, args[0], "move");
    const rename = std.mem.eql(u8, args[0], "rename");
    const pane_control = focus or close or move or rename;
    const palette = std.mem.eql(u8, args[0], "palette");
    if (!resolve and !session_ensure and !ensure and !inspect and !pane_control and !palette and !std.mem.eql(u8, args[0], "open")) return usageError("unknown subcommand");
    if (args.len == 2 and std.mem.eql(u8, args[1], "--help")) {
        try std.fs.File.stdout().writeAll(usage);
        return 0;
    }
    var options: std.StringHashMap([]const u8) = .init(allocator);
    const allowed = [_][]const u8{ "--socket", "--session", "--anchor", "--pane", "--window", "--layout", "--direction", "--ratio", "--bounds", "--label", "--cwd", "--timeout-ms", "--create-session", "--file", "--name", "--title", "--focus" };
    var i: usize = 1;
    while (i < args.len and !std.mem.eql(u8, args[i], "--")) : (i += 2) {
        if (i + 1 >= args.len) return usageError("every option needs a value");
        var known = false;
        for (allowed) |key| if (std.mem.eql(u8, key, args[i])) {
            known = true;
            break;
        };
        if (!known or options.contains(args[i])) return usageError("unknown or repeated option");
        try options.put(args[i], args[i + 1]);
    }
    const socket = options.get("--socket");
    const session = options.get("--session");
    const pane = options.get("--pane");
    const window = options.get("--window");
    const create_session = options.get("--create-session");
    const any_session = session != null and std.mem.eql(u8, session.?, "any") and (resolve or ensure);
    if (create_session != null and (!ensure or !any_session)) return usageError("--create-session requires ensure --session any");
    if (any_session and resolve and (pane == null or window != null)) return usageError("resolve --session any requires --pane TEXT");
    if (any_session and ensure and (create_session == null or !selectorValid(create_session.?, "session:") or std.mem.eql(u8, create_session.?, "any"))) return usageError("ensure --session any requires --create-session TEXT");
    const anchor = options.get("--anchor");
    if (window != null and !rename and !resolve) return usageError("--window is rename-only");
    const layout: ?[]const u8 = if (move) "tiled" else options.get("--layout") orelse (if (ensure) @as(?[]const u8, "tab") else null);
    const label = options.get("--label");
    const cwd = options.get("--cwd");
    var budget: u64 = 5000;
    if (options.get("--timeout-ms")) |v| budget = std.fmt.parseUnsigned(u64, v, 10) catch return usageError("invalid timeout");
    if (budget < 100 or budget > 60000) return usageError("timeout must be 100..60000ms");
    if (palette) {
        for ([_][]const u8{ "--socket", "--session", "--anchor", "--pane", "--timeout-ms" }) |key| if (options.contains(key)) return usageError("palette takes context at invocation, not target options");
    } else {
        if (socket == null or !std.fs.path.isAbsolute(socket.?)) return usageError("--socket ABS is required");
        if (!session_ensure and (session == null or !selectorValid(session.?, "session:"))) return usageError("--session TEXT is required");
        for ([_][]const u8{ "--file", "--name", "--title" }) |key| if (options.contains(key)) return usageError("palette-only option");
    }
    var move_focus = false;
    if (options.get("--focus")) |value| {
        if ((!move and !ensure) or (!std.mem.eql(u8, value, "yes") and !std.mem.eql(u8, value, "no"))) return usageError("--focus yes|no requires move or ensure");
        move_focus = std.mem.eql(u8, value, "yes");
    }
    if (move and (options.contains("--layout") or label != null or cwd != null)) return usageError("move preserves the existing program/label; no layout, label or cwd option");
    var direction: ?[]const u8 = null;
    var ratio: ?f64 = null;
    var bounds: ?[4]f64 = null;
    var command: ?[]const []const u8 = null;
    if (resolve or session_ensure) {
        if (i != args.len or options.count() > 4 or anchor != null or layout != null or cwd != null or options.contains("--focus") or options.contains("--direction") or options.contains("--ratio") or options.contains("--bounds")) return usageError("resolve/session ensure take only target options and timeout");
        if (pane) |v| if (!selectorValid(v, "block:")) return usageError("invalid pane selector");
        if (window) |v| if (!selectorValid(v, "window:")) return usageError("invalid window selector");
        if (resolve and (pane != null and window != null or label != null)) return usageError("resolve takes session and at most one pane/window");
        if (session_ensure and (session != null or pane != null or window != null or label == null or !labelValid(label.?))) return usageError("session ensure requires only --label TEXT");
    } else if (rename) {
        if ((pane == null) == (window == null)) return usageError("rename requires exactly one of --window or --pane");
        if (pane) |v| if (!selectorValid(v, "block:")) return usageError("--pane TEXT is required");
        if (window) |v| if (!selectorValid(v, "window:")) return usageError("--window TEXT is required");
        if (label == null or !labelValid(label.?)) return usageError("1..128 byte non-control UTF-8 label is required");
        if (i != args.len or options.count() > 5 or anchor != null or layout != null or cwd != null or options.contains("--direction") or options.contains("--ratio") or options.contains("--bounds")) return usageError("rename takes only socket, session, window or pane, label and timeout");
    } else if (inspect or focus or close) {
        if (pane == null or !selectorValid(pane.?, "block:")) return usageError("--pane TEXT is required");
        if (i != args.len or options.count() > 4 or anchor != null or layout != null or label != null or cwd != null or options.contains("--direction") or options.contains("--ratio") or options.contains("--bounds")) return usageError("inspect/focus/close take only socket, session, pane and timeout");
    } else {
        if (!move and pane != null) return usageError("--pane is inspect/focus/close/move-only");
        if (move and (pane == null or !selectorValid(pane.?, "block:") or i != args.len)) return usageError("move requires --pane TEXT and no program argv");
        if (layout == null or (!move and (label == null or !labelValid(label.?)))) return usageError("layout and 1..128 byte non-control UTF-8 label are required");
        const tiled = std.mem.eql(u8, layout.?, "tiled");
        const floating = std.mem.eql(u8, layout.?, "float");
        const tab = std.mem.eql(u8, layout.?, "tab");
        if (!tiled and !floating and !tab) return usageError("layout must be tiled, float or tab");
        if (!palette and !tab and (anchor == null or !selectorValid(anchor.?, "block:"))) return usageError("tiled/float need --anchor TEXT");
        if (tab and anchor != null) return usageError("tab does not take an anchor");
        if (tiled) {
            if (options.contains("--bounds")) return usageError("tiled does not take bounds");
            direction = options.get("--direction") orelse "right";
            if (!std.mem.eql(u8, direction.?, "right") and !std.mem.eql(u8, direction.?, "left") and !std.mem.eql(u8, direction.?, "up") and !std.mem.eql(u8, direction.?, "down")) return usageError("invalid direction");
            ratio = if (options.get("--ratio")) |v| std.fmt.parseFloat(f64, v) catch return usageError("invalid ratio") else 1.0 / 3.0;
            if (!std.math.isFinite(ratio.?) or ratio.? <= 0 or ratio.? >= 1) return usageError("new pane ratio must be >0 and <1");
        } else {
            if (options.contains("--direction") or options.contains("--ratio")) return usageError("direction/ratio require tiled");
            if (floating) {
                const raw = options.get("--bounds") orelse return usageError("float requires --bounds '[x,y,w,h]'");
                bounds = (std.json.parseFromSlice([4]f64, allocator, raw, .{}) catch return usageError("invalid bounds array")).value;
                for (bounds.?) |n| if (!std.math.isFinite(n)) return usageError("bounds must be finite");
                const b = bounds.?;
                if (b[0] < 0 or b[1] < 0 or b[2] <= 0 or b[3] <= 0 or b[0] + b[2] > 1 or b[1] + b[3] > 1) return usageError("bounds must fit inside window");
            } else if (options.contains("--bounds")) return usageError("tab does not take bounds");
        }
        if (cwd) |v| if (!std.fs.path.isAbsolute(v) or !std.unicode.utf8ValidateSlice(v)) return usageError("cwd must be absolute UTF-8 on program host");
        if (!move) {
            if (i >= args.len or i + 1 >= args.len or args[i + 1].len == 0) return usageError("-- ARGV... is required");
            command = args[i + 1 ..];
            for (command.?) |v| if (!std.unicode.utf8ValidateSlice(v)) return usageError("argv must be UTF-8");
        }
    }
    const request = .{ .operation = if (resolve) "resolve" else if (session_ensure) "session-ensure" else if (ensure) "ensure" else if (inspect) "inspect" else if (focus) "focus" else if (close) "close" else if (move) "move" else if (rename) "rename" else "open", .focus = focus or move_focus, .session_id = session, .create_session = create_session, .block_id = pane, .window_id = window, .anchor = anchor, .layout = layout, .label = label, .direction = direction, .ratio = ratio, .bounds = bounds, .cwd = cwd, .argv = command };
    const encoded = try std.json.Stringify.valueAlloc(allocator, request, .{ .emit_null_optional_fields = false });
    if (encoded.len > 24000) return usageError("encoded arguments exceed 24000 bytes");
    if (palette) {
        const file = options.get("--file") orelse return usageError("palette requires --file ABS");
        const name = options.get("--name") orelse return usageError("palette requires --name");
        const title = options.get("--title") orelse return usageError("palette requires --title");
        if (!std.fs.path.isAbsolute(file) or !labelValid(title) or name.len == 0 or name.len > 64) return usageError("invalid palette path/title/name");
        for (name) |c| if (!(std.ascii.isLower(c) or std.ascii.isDigit(c) or c == '_')) return usageError("palette name: lowercase letters, digits, underscores only");
        const source = try std.fmt.allocPrint(allocator, "-- teerex-surface-action:{s}\n{s}\nrex.action{{name={s},title={s},category=\"teerex\",run=function(ctx)\nlocal a=rex.json.decode({s})\na.session_id=ctx.session_id\na.anchor=ctx.block_id\nlocal r=surface(a)\nif r.outcome~=\"created_and_verified\" then error(rex.json.encode(r),0) end\nreturn r\nend}}\n", .{ name, @embedFile("surfaces.lua"), try luaString(allocator, name), try luaString(allocator, title), try luaString(allocator, encoded) });
        var f = std.fs.createFileAbsolute(file, .{ .exclusive = true, .mode = 0o600 }) catch |err| {
            try writeJson(allocator, .{ .schema_version = 1, .kind = "surface_palette_result", .outcome = "refused", .failure_reason = @errorName(err), .registered_in_running_server = false });
            return 1;
        };
        defer f.close();
        f.writeAll(source) catch |err| {
            std.fs.deleteFileAbsolute(file) catch {};
            return err;
        };
        try writeJson(allocator, .{ .schema_version = 1, .kind = "surface_palette_result", .outcome = "fragment_written", .file = file, .name = name, .registered_in_running_server = false, .next = "Use surfaces palette install to plan/apply native config inclusion and verify selected-server registration" });
        return 0;
    }
    var env = try std.process.getEnvMap(allocator);
    for ([_][]const u8{ "REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT" }) |key| env.remove(key);
    const endpoint = try std.fmt.allocPrint(allocator, "unix://{s}", .{socket.?});
    const source = @embedFile("surfaces.lua") ++ "\nlocal function emit(v) io.write(rex.json.encode(v),'\\n'); io.flush() end\nemit({event='result',result=surface(rex.args,emit)})\n";
    const argv = [_][]const u8{ "rex", "--autostart=false", "--server", endpoint, "--timeout", "3s", "--color", "never", "do", "-e", source, "--args", encoded };
    const signals = supervised.Signals.init();
    defer signals.deinit();
    const lock: ?EnsureLock = if (ensure) ensureLock(allocator, socket.?, budget) catch |err| {
        const sig = supervised.requestedSignal();
        try writeJson(allocator, .{ .schema_version = 1, .kind = "surface_result", .outcome = "refused", .requested = request, .creation_attempted = false, .control_attempted = false, .failure_reason = if (err == error.EnsureBusy) "ensure_busy" else @errorName(err), .retry_safe = err == error.EnsureBusy, .timeout_ms = budget });
        return if (sig != 0) 128 + sig else 1;
    } else null;
    defer if (lock) |held| held.file.close();
    const transport_budget = if (lock) |held| budget -| held.waited_ms else budget;
    var c: Collector = .{ .allocator = allocator };
    var failure: ?[]const u8 = null;
    const transport = supervised.collect(allocator, &argv, &env, @max(1, transport_budget), &c) catch |err| blk: {
        failure = @errorName(err);
        break :blk null;
    };
    const sig = supervised.requestedSignal();
    const deadline = transport != null and transport.?.deadline_exceeded;
    const ok = transport != null and !transport.?.stopped and transport.?.term == .Exited and transport.?.term.Exited == 0 and c.pending.items.len == 0 and c.result != null;
    const r = c.result orelse SurfaceResult{ .outcome = "uncertain" };
    const success = ok and sig == 0 and ((resolve and std.mem.eql(u8, r.outcome, "resolved") and r.resolved == .object) or ((session_ensure or ensure) and (std.mem.eql(u8, r.outcome, "existing") or std.mem.eql(u8, r.outcome, "created")) and r.actual == .object and r.resolved == .object and (!ensure or !move_focus or ensureFocusVerified(r))) or ((!ensure and r.actual == .object and (std.mem.eql(u8, r.outcome, "created_and_verified") and r.requested_geometry_verified and r.created == .object or std.mem.eql(u8, r.outcome, "renamed_and_verified") and rename and r.control_acknowledged and r.requested_label_verified or std.mem.eql(u8, r.outcome, "inspected") and inspect or std.mem.eql(u8, r.outcome, "focused_and_verified") and focus and r.control_acknowledged or std.mem.eql(u8, r.outcome, "moved_and_verified") and move and r.control_acknowledged and r.requested_geometry_verified and r.move_receipt == .object and (!move_focus or r.focus_acknowledged))) or (close and std.mem.eql(u8, r.outcome, "closed_and_absent") and r.control_acknowledged and r.block_absence_verified)));
    const reported_success = std.mem.eql(u8, r.outcome, "resolved") or std.mem.eql(u8, r.outcome, "existing") or std.mem.eql(u8, r.outcome, "created") or std.mem.eql(u8, r.outcome, "renamed_and_verified") or std.mem.eql(u8, r.outcome, "created_and_verified") or std.mem.eql(u8, r.outcome, "inspected") or std.mem.eql(u8, r.outcome, "focused_and_verified") or std.mem.eql(u8, r.outcome, "closed_and_absent") or std.mem.eql(u8, r.outcome, "moved_and_verified");
    const outcome = if (sig != 0) "cancel_requested" else if (deadline) "deadline_exceeded" else if (ok and (!reported_success or success)) r.outcome else "uncertain";
    try writeJson(allocator, .{ .schema_version = 1, .kind = "surface_result", .target = .{ .server = endpoint, .session_id = session }, .resolved = r.resolved, .candidates = r.candidates, .requested = request, .source = r.source, .created = if (r.created != .null) r.created else c.created, .actual = r.actual, .previous = r.previous, .previous_anchor = r.previous_anchor, .move_receipt = r.move_receipt, .focus_acknowledged = r.focus_acknowledged, .outcome = outcome, .creation_attempted = !c.control and c.attempt, .control_attempted = c.control and c.attempt, .control_acknowledged = r.control_acknowledged, .block_absence_verified = ok and r.block_absence_verified, .close_scope = "rex_block_absence_not_descendant_process_death", .attempt_evidence = "received_local_frame_not_server_dispatch_proof", .requested_geometry_verified = success and r.requested_geometry_verified, .requested_label_verified = success and r.requested_label_verified, .failure_reason = failure orelse r.failure_reason orelse if (!ok or reported_success and !success) @as(?[]const u8, "rex_transport_incomplete") else null, .backend_stderr_base64 = try encodedDiagnostic(allocator, if (transport) |v| v.stderr else ""), .retry_safe = false, .automatic_close = false, .focus_requested = focus or move_focus, .close_requested = close, .geometry_units = "window_fraction", .painted_visibility = "not_assessed", .program_readiness = "not_assessed", .ensure_lock = if (lock) |held| held.path else null, .timeout_ms = budget });
    return if (sig != 0) 128 + sig else if (deadline) 124 else if (success) 0 else 1;
}
