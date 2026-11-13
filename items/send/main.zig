const std = @import("std");
const builtin = @import("builtin");
const supervised = @import("supervised_child");
pub const clutch_state = @import("clutch_state.zig");

const usage =
    \\Usage: teerex send --socket ABS --session session:UUID --block block:UUID --from LABEL --message-file ABS|- [--timeout-ms N]
    \\Send FROM <label>: <file bytes> as one paste, then Enter, to an explicit existing terminal.
    \\Requires Linux/macOS, Rex on PATH, existing API10..13 server, and canonical lowercase full IDs.
    \\Select a dedicated agent terminal: this can submit/execute input and does not establish prompt safety.
    \\--draft guard|ignore defaults guard: wait for quiet/empty draft, clear, send, restore without Enter.
    \\Cooperative clutch always applies, including --draft ignore; held panes wait then refuse pane_held_by_human.
    \\State: TEEREX_CLUTCH_DIR or ~/.local/state/teerex/clutch; same command/Rex host required.
    \\--draft-wait-ms N defaults 30000 (0..55000); quiet window1500ms, restore delay400ms.
    \\Ignore preserves prior paste/Enter behavior. No chunking, retry, inbox forwarding, or autostart.
    \\File: regular, or - reads stdin until EOF within the same deadline/cancellation budget, before any dispatch.
    \\Input: 1..65536 UTF-8 bytes; LF/tab allowed, other C0/DEL rejected. Encoded RPC capped at 60000 bytes.
    \\Local inbox markers refuse input. Same-host/TMPDIR agent-send mkdir lock serializes cooperating senders only.
    \\Timeout defaults to draft wait+10000ms (including ignore), range100..115000; includes lock/Rex.
    \\Draft text is never reported. Keystrokes between final read and Ctrl-U can still race clearing.
    \\Restore polls100ms up to1500ms; unverified/failed restore warns without failing acknowledged send.
    \\Stale locks are never stolen.
    \\JSON reports attempts/acknowledgements, NOT application consumption, atomic delivery, or an input lease.
    \\Exit: 0 both ACKs, 1 refusal/error/uncertain, 2 usage, 124 deadline, 130 SIGINT, 143 SIGTERM.
    \\
;

const Source = struct { rex_version: []const u8, platform: []const u8, api_revision: i64 };
const Draft = struct {
    mode: []const u8,
    detected: bool = false,
    chars: usize = 0,
    waited_ms: u64 = 0,
    bound_reached: bool = false,
    cleared: ?bool = null,
    restored: ?bool = null,
    restore_verified: ?bool = null,
};
const Clutch = struct { held_observed: bool = false, waited_ms: u64 = 0, bound_reached: bool = false };
const Frame = struct {
    clutch: ?Clutch = null,
    event: []const u8,
    source: ?Source = null,
    stage: ?[]const u8 = null,
    draft: ?Draft = null,
    reason: ?[]const u8 = null,
    encoded_rpc_bytes: ?usize = null,
};

const Collector = struct {
    allocator: std.mem.Allocator,
    timer: *std.time.Timer,
    draft: Draft,
    clutch: Clutch = .{},
    draft_wait_started: ?u64 = null,
    draft_warning: ?[]const u8 = null,
    pending: std.ArrayList(u8) = .empty,
    source: ?Source = null,
    paste_attempted: bool = false,
    paste_acknowledged: bool = false,
    enter_attempted: bool = false,
    enter_acknowledged: bool = false,
    finished: bool = false,
    reason: ?[]const u8 = null,
    encoded_rpc_bytes: ?usize = null,

    pub fn receive(self: *Collector, bytes: []const u8) !void {
        // Fixed source emits bounded small records, never message or draft text.
        if (bytes.len > 8192 - self.pending.items.len) return error.InvalidSendFrame;
        try self.pending.appendSlice(self.allocator, bytes);
        while (std.mem.indexOfScalar(u8, self.pending.items, '\n')) |end| {
            // Retained strings must outlive compaction of the transport buffer.
            const parsed = try std.json.parseFromSlice(Frame, self.allocator, self.pending.items[0..end], .{ .allocate = .alloc_always });
            const f = parsed.value;
            if (self.finished) return error.InvalidSendFrame;
            if (std.mem.eql(u8, f.event, "source")) {
                if (self.source != null) return error.InvalidSendFrame;
                self.source = f.source orelse return error.InvalidSendFrame;
            } else if (std.mem.eql(u8, f.event, "clutch")) {
                self.clutch = f.clutch orelse return error.InvalidSendFrame;
            } else if (std.mem.eql(u8, f.event, "draft")) {
                const waited = self.draft.waited_ms;
                self.draft = f.draft orelse return error.InvalidSendFrame;
                self.draft.waited_ms = waited;
                const elapsed = self.timer.read() / std.time.ns_per_ms;
                if (std.mem.eql(u8, f.stage orelse "", "waiting")) self.draft_wait_started = elapsed;
                if (std.mem.eql(u8, f.stage orelse "", "ready")) {
                    if (self.draft_wait_started) |start| self.draft.waited_ms = elapsed - start;
                    self.draft_wait_started = null;
                }
            } else if (std.mem.eql(u8, f.event, "preflight")) {
                self.encoded_rpc_bytes = f.encoded_rpc_bytes orelse return error.InvalidSendFrame;
            } else if (std.mem.eql(u8, f.event, "attempt")) {
                if (std.mem.eql(u8, f.stage orelse "", "paste") and !self.paste_attempted) {
                    self.paste_attempted = true;
                } else if (std.mem.eql(u8, f.stage orelse "", "enter") and self.paste_acknowledged and !self.enter_attempted) {
                    self.enter_attempted = true;
                } else return error.InvalidSendFrame;
            } else if (std.mem.eql(u8, f.event, "ack")) {
                if (std.mem.eql(u8, f.stage orelse "", "paste") and self.paste_attempted and !self.paste_acknowledged) {
                    self.paste_acknowledged = true;
                } else if (std.mem.eql(u8, f.stage orelse "", "enter") and self.enter_attempted and !self.enter_acknowledged) {
                    self.enter_acknowledged = true;
                } else return error.InvalidSendFrame;
            } else if (std.mem.eql(u8, f.event, "warning") and self.enter_acknowledged and self.draft_warning == null) {
                self.draft_warning = f.reason orelse return error.InvalidSendFrame;
            } else if (std.mem.eql(u8, f.event, "refused") or std.mem.eql(u8, f.event, "failed")) {
                self.reason = f.reason orelse return error.InvalidSendFrame;
                self.finished = true;
            } else if (std.mem.eql(u8, f.event, "finished") and self.enter_acknowledged) {
                self.finished = true;
            } else return error.InvalidSendFrame;
            try self.pending.replaceRange(self.allocator, 0, end + 1, &.{});
        }
    }
};

fn usageError(message: []const u8) noreturn {
    std.debug.print("teerex send: {s}\n{s}", .{ message, usage });
    std.process.exit(2);
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

fn textValid(value: []const u8, multiline: bool) bool {
    if (!std.unicode.utf8ValidateSlice(value)) return false;
    for (value) |c| if ((c < 32 and !(multiline and (c == '\n' or c == '\t'))) or c == 127) return false;
    return true;
}

fn inboxMarked(allocator: std.mem.Allocator, env: *const std.process.EnvMap, suffix: []const u8) !bool {
    const configured = env.get("AGENT_INBOX_DIR") orelse "";
    const root = if (configured.len != 0) configured else try std.fs.path.join(allocator, &.{ env.get("HOME") orelse return error.HomeRequiredForInboxCheck, ".local/state/agent-inbox" });
    const path = try std.fmt.allocPrint(allocator, "{s}/{s}.inbox", .{ root, suffix });
    std.fs.cwd().access(path, .{}) catch |err| {
        if (err == error.FileNotFound) return false;
        return err;
    };
    return true;
}

fn readMessage(allocator: std.mem.Allocator, path: []const u8, timer: *std.time.Timer, timeout_ms: u64) ![]const u8 {
    if (!std.mem.eql(u8, path, "-")) {
        // O_NONBLOCK prevents hanging on a FIFO before checking its kind.
        const fd = try std.posix.open(path, .{ .ACCMODE = .RDONLY, .NONBLOCK = true, .CLOEXEC = true }, 0);
        const file: std.fs.File = .{ .handle = fd };
        defer file.close();
        if ((try file.stat()).kind != .file) usageError("message file must be regular");
        return file.readToEndAlloc(allocator, 65536);
    }
    var bytes: std.ArrayList(u8) = .empty;
    while (true) {
        if (supervised.requestedSignal() != 0) return error.StdinCancelled;
        const elapsed = timer.read() / std.time.ns_per_ms;
        if (elapsed >= timeout_ms) return error.StdinDeadlineExceeded;
        var descriptors = [_]std.posix.pollfd{.{ .fd = std.posix.STDIN_FILENO, .events = std.posix.POLL.IN, .revents = 0 }};
        _ = try std.posix.poll(&descriptors, @intCast(@min(20, timeout_ms - elapsed)));
        if (descriptors[0].revents == 0) continue;
        var buffer: [4096]u8 = undefined;
        const count = try std.posix.read(std.posix.STDIN_FILENO, &buffer);
        if (count == 0) return bytes.items;
        if (count > 65536 - bytes.items.len) return error.FileTooBig;
        try bytes.appendSlice(allocator, buffer[0..count]);
    }
}

pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    if (args.len == 1 and std.mem.eql(u8, args[0], "--help")) {
        try std.fs.File.stdout().writeAll(usage);
        return 0;
    }
    var socket: ?[]const u8 = null;
    var session: ?[]const u8 = null;
    var block: ?[]const u8 = null;
    var from: ?[]const u8 = null;
    var message_file: ?[]const u8 = null;
    var timeout: ?u64 = null;
    var draft_mode: ?[]const u8 = null;
    var draft_wait: ?u64 = null;
    var i: usize = 0;
    while (i < args.len) : (i += 2) {
        if (i + 1 == args.len) usageError("every option needs a value");
        const name = args[i];
        const value = args[i + 1];
        if (std.mem.eql(u8, name, "--socket") and socket == null) {
            socket = value;
        } else if (std.mem.eql(u8, name, "--session") and session == null) {
            session = value;
        } else if (std.mem.eql(u8, name, "--block") and block == null) {
            block = value;
        } else if (std.mem.eql(u8, name, "--from") and from == null) {
            from = value;
        } else if (std.mem.eql(u8, name, "--message-file") and message_file == null) {
            message_file = value;
        } else if (std.mem.eql(u8, name, "--timeout-ms") and timeout == null) {
            timeout = std.fmt.parseUnsigned(u64, value, 10) catch usageError("invalid timeout");
        } else if (std.mem.eql(u8, name, "--draft") and draft_mode == null) {
            draft_mode = value;
        } else if (std.mem.eql(u8, name, "--draft-wait-ms") and draft_wait == null) {
            draft_wait = std.fmt.parseUnsigned(u64, value, 10) catch usageError("invalid draft wait");
        } else usageError("unknown or repeated option");
    }
    const path = socket orelse usageError("--socket is required");
    const sid = session orelse usageError("--session is required");
    const bid = block orelse usageError("--block is required");
    const sender = from orelse usageError("--from is required");
    const file_path = message_file orelse usageError("--message-file is required");
    const mode = draft_mode orelse "guard";
    const draft_wait_ms = draft_wait orelse 30000;
    if ((!std.mem.eql(u8, mode, "guard") and !std.mem.eql(u8, mode, "ignore")) or draft_wait_ms > 55000) usageError("draft must be guard|ignore; draft wait must be 0..55000 ms");
    const timeout_ms = timeout orelse (draft_wait_ms + 10000);
    if (!std.fs.path.isAbsolute(path) or (!std.mem.eql(u8, file_path, "-") and !std.fs.path.isAbsolute(file_path))) usageError("socket must be absolute; message file must be absolute or - for stdin");
    if (!fullId(sid, "session:") or !fullId(bid, "block:")) usageError("canonical lowercase full session:UUID and block:UUID are required");
    if (sender.len < 1 or sender.len > 128 or !textValid(sender, false)) usageError("from must be 1..128 UTF-8 bytes without controls");
    if (timeout_ms < 100 or timeout_ms > 115000) usageError("timeout must be 100..115000 ms");
    if (builtin.os.tag != .macos and builtin.os.tag != .linux) return error.SendRequiresUnix;

    const signals = supervised.Signals.init();
    defer signals.deinit();
    var timer = try std.time.Timer.start();
    const started_at = std.time.milliTimestamp();
    var env = try std.process.getEnvMap(allocator);
    for ([_][]const u8{ "REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT" }) |key| env.remove(key);
    var clutch = try clutch_state.Store.open(allocator, &env, path, sid, bid);
    defer clutch.close();
    // Validate existing state before invoking Lua; corrupt or unsafe state fails closed.
    _ = try clutch.set(allocator, null, "");
    var input_failure: ?[]const u8 = null;
    const message = readMessage(allocator, file_path, &timer, timeout_ms) catch |err| blk: {
        if (err == error.FileTooBig) usageError("message exceeds 65536 bytes");
        if (err != error.StdinCancelled and err != error.StdinDeadlineExceeded) return err;
        input_failure = @errorName(err);
        break :blk "";
    };
    if (input_failure == null and (message.len == 0 or !textValid(message, true))) usageError("message must be nonempty UTF-8, with no controls except LF/tab");
    const suffix = bid["block:".len..];
    const configured_tmp = env.get("TMPDIR") orelse "";
    const lock_path = try std.fmt.allocPrint(allocator, "{s}/agent-send.{s}.lock", .{ if (configured_tmp.len != 0) configured_tmp else "/tmp", suffix });
    if (!std.fs.path.isAbsolute(lock_path)) usageError("TMPDIR must be absolute");
    const endpoint = try std.fmt.allocPrint(allocator, "unix://{s}", .{path});
    var collector: Collector = .{ .allocator = allocator, .timer = &timer, .draft = .{ .mode = mode } };
    var locked = false;
    var acquired = false;
    var backend_started = false;
    defer if (locked) std.fs.cwd().deleteDir(lock_path) catch {};
    var outcome: []const u8 = "backend_error";
    var failure: ?[]const u8 = null;
    var backend: ?supervised.Result = null;
    var encoded_argument_bytes: ?usize = null;
    work: {
        if (input_failure) |reason| {
            failure = reason;
            outcome = if (std.mem.eql(u8, reason, "StdinDeadlineExceeded")) "deadline_exceeded" else "cancel_requested";
            break :work;
        }
        while (true) {
            if (supervised.requestedSignal() != 0) break :work;
            const elapsed = timer.read() / std.time.ns_per_ms;
            if (elapsed >= timeout_ms) {
                outcome = "deadline_exceeded";
                break :work;
            }
            if (try inboxMarked(allocator, &env, suffix)) {
                outcome = "inbox_refused";
                break :work;
            }
            std.fs.cwd().makeDir(lock_path) catch |err| {
                if (err != error.PathAlreadyExists) return err;
                std.Thread.sleep(@as(u64, @min(20, timeout_ms - elapsed)) * std.time.ns_per_ms);
                continue;
            };
            locked = true;
            acquired = true;
            break;
        }
        if (try inboxMarked(allocator, &env, suffix)) {
            outcome = "inbox_refused";
            break :work;
        }
        const elapsed = timer.read() / std.time.ns_per_ms;
        if (elapsed >= timeout_ms) {
            outcome = "deadline_exceeded";
            break :work;
        }
        const request = try std.json.Stringify.valueAlloc(allocator, .{
            .session_id = sid,
            .block_id = bid,
            .draft_mode = mode,
            .draft_wait_ms = draft_wait_ms,
            .clutch_file = clutch.path,
            .text = try std.fmt.allocPrint(allocator, "FROM {s}: {s}", .{ sender, message }),
        }, .{});
        encoded_argument_bytes = request.len;
        // Only paste text is a lower bound on RPC size; clutch metadata belongs
        // to the local controller and must not shrink the existing paste budget.
        const paste_lower_bound = try std.json.Stringify.valueAlloc(allocator, .{
            .text = try std.fmt.allocPrint(allocator, "FROM {s}: {s}", .{ sender, message }),
        }, .{});
        // Reject before exec too: LF-heavy 64 KiB inputs exceed Linux's per-argument cap.
        if (paste_lower_bound.len > 60000) {
            outcome = "refused";
            failure = "encoded_paste_exceeds_limit";
            break :work;
        }
        const argv = [_][]const u8{ "rex", "--autostart=false", "--server", endpoint, "--timeout", "3s", "--color", "never", "do", "--session", sid, "--block", bid, "-e", @embedFile("draft.lua") ++ "\n" ++ @embedFile("send.lua"), "--args", request };
        const before_spawn = timer.read() / std.time.ns_per_ms;
        if (before_spawn >= timeout_ms or supervised.requestedSignal() != 0) {
            outcome = "deadline_exceeded";
            break :work;
        }
        backend_started = true;
        backend = supervised.collect(allocator, &argv, &env, timeout_ms - before_spawn, &collector) catch |err| {
            failure = @errorName(err);
            outcome = "uncertain";
            break :work;
        };
        const r = backend.?;
        const transport_ok = !r.stopped and r.term == .Exited and r.term.Exited == 0 and collector.pending.items.len == 0;
        outcome = if (r.deadline_exceeded) "deadline_exceeded" else if (transport_ok and collector.enter_acknowledged and collector.finished and collector.reason == null) "events_acknowledged" else if (collector.paste_attempted) "uncertain" else if (collector.reason != null) "refused" else "backend_error";
        if (!transport_ok and r.stderr.len != 0 and std.mem.eql(u8, mode, "ignore")) std.debug.print("teerex send: Rex backend: {s}\n", .{r.stderr});
    }
    if (collector.draft_wait_started) |start| collector.draft.waited_ms = timer.read() / std.time.ns_per_ms - start;
    const signal = supervised.requestedSignal();
    if (signal != 0) outcome = "cancel_requested";
    // Keep the lock through subprocess cleanup. Never remove another sender's lock.
    if (locked) {
        std.fs.cwd().deleteDir(lock_path) catch |err| {
            failure = @errorName(err);
        };
        locked = false;
    }
    const success = std.mem.eql(u8, outcome, "events_acknowledged") and failure == null;
    const output = try std.json.Stringify.valueAlloc(allocator, .{
        .schema_version = 1,
        .kind = "send_result",
        .target = .{ .server = endpoint, .session_id = sid, .block_id = bid },
        .source = collector.source,
        .started_at_unix_ms = started_at,
        .elapsed_ms = timer.read() / std.time.ns_per_ms,
        .timeout_ms = timeout_ms,
        .message_bytes = message.len,
        .paste_text_bytes = "FROM ".len + sender.len + 2 + message.len,
        .encoded_argument_bytes = encoded_argument_bytes,
        .encoded_rpc_bytes = collector.encoded_rpc_bytes,
        .max_encoded_rpc_bytes = 60000,
        .outcome = outcome,
        .failure_reason = failure orelse collector.reason orelse if (backend != null and !success) @as(?[]const u8, "rex_transport_incomplete") else null,
        .cancellation_signal = if (signal == 0) @as(?u8, null) else signal,
        .draft = collector.draft,
        .clutch = .{ .cooperative = true, .state_file = clutch.path, .held_observed = collector.clutch.held_observed, .waited_ms = collector.clutch.waited_ms, .bound_reached = collector.clutch.bound_reached },
        .draft_warning = collector.draft_warning,
        .paste = .{ .attempted = collector.paste_attempted, .acknowledged = collector.paste_acknowledged },
        .enter = .{ .attempted = collector.enter_attempted, .acknowledged = collector.enter_acknowledged },
        .attempt_evidence = "received_local_pre_call_frames_not_server_dispatch_proof",
        .backend_invoked = backend_started,
        .cooperative_lock = .{ .path = lock_path, .acquired = acquired, .scope = "same_host_and_temp_directory_cooperating_senders" },
        .server_enforced_atomic_delivery = false,
        .exclusive_input_lease = false,
        .application_consumption = "not_assessed",
        .prompt_safety = "not_assessed",
        .retry_safe = std.mem.eql(u8, collector.reason orelse "", "pane_held_by_human") and !collector.paste_attempted and collector.draft.cleared == null,
    }, .{ .whitespace = .indent_2 });
    try std.fs.File.stdout().writeAll(output);
    try std.fs.File.stdout().writeAll("\n");
    return if (signal != 0) 128 + signal else if (std.mem.eql(u8, outcome, "deadline_exceeded")) 124 else if (success) 0 else 1;
}
