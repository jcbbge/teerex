const std = @import("std");
const builtin = @import("builtin");
const supervised = @import("supervised_child");
pub const queue_source = @embedFile("focus_queue.py");
pub const clutch_state = @import("clutch_state.zig");

const usage =
    \\Usage: teerex send --socket ABS --session session:UUID --block block:UUID --from LABEL --message-file ABS|- [--timeout-ms N]
    \\Send FROM <label>: <file bytes> as one paste, then Enter, to an explicit existing terminal.
    \\Requires Linux/macOS, Rex on PATH, existing API10..13 server, and canonical lowercase full IDs.
    \\Select a dedicated agent terminal: this can submit/execute input and does not establish prompt safety.
    \\--draft guard|ignore defaults guard: defer when input is present or unknown; send only on empty input.
    \\Cooperative clutch applies in both draft modes: held panes durably queue, exit 0, type nothing.
    \\--no-queue waits for empty, released input within the draft-wait budget, then refuses.
    \\Unavailable clutch state is reported unknown with a named failure_reason and does not block send.
    \\Deferred sends create private queue records. A later guarded send, release, or drain delivers in ID order.
    \\State: TEEREX_CLUTCH_DIR or ~/.local/state/teerex/clutch; same command/Rex host required.
    \\--draft-wait-ms N defaults 30000 (0..55000); applies to --no-queue.
    \\Ignore preserves paste/Enter behavior after release. No chunking, resend or autostart.
    \\File: regular, or - reads stdin until EOF within the same deadline/cancellation budget, before any dispatch.
    \\Input: 1..65536 UTF-8 bytes; LF/tab allowed, other C0/DEL rejected. Encoded RPC capped at 60000 bytes.
    \\Same-host/TMPDIR agent-send mkdir lock serializes cooperating senders only.
    \\Timeout defaults to draft wait+10000ms (including ignore), range100..115000; includes lock/Rex.
    \\Draft text is never reported. The reads before paste and Enter leave a small input race.
    \\Restore polls100ms up to1500ms; unverified/failed restore warns without failing acknowledged send.
    \\Stale locks are never stolen.
    \\JSON reports attempts/acknowledgements, NOT application consumption, atomic delivery, or an input lease.
    \\Exit: 0 queued (queue_id) or both ACKs; 1 refusal/error/uncertain, 2 usage, 124 deadline, 130 SIGINT, 143 SIGTERM.
    \\
;

const Source = struct { rex_version: []const u8, platform: []const u8, api_revision: i64 };
const Draft = struct {
    mode: []const u8,
    state: []const u8 = "unknown",
    deferred: bool = false,
};
const Clutch = struct { state: []const u8 = "unknown", failure_reason: ?[]const u8 = null, held_observed: bool = false, waited_ms: u64 = 0, bound_reached: bool = false };
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
    draft: Draft,
    clutch: Clutch = .{},
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
                self.draft = f.draft orelse return error.InvalidSendFrame;
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
    if (std.posix.isatty(std.posix.STDIN_FILENO) and std.posix.isatty(std.posix.STDERR_FILENO)) std.debug.print("next: teerex send --help\n", .{});
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
    var no_queue = false;
    var i: usize = 0;
    while (i < args.len) {
        if (std.mem.eql(u8, args[i], "--no-queue") and !no_queue) {
            no_queue = true;
            i += 1;
            continue;
        }
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
        i += 2;
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
    for ([_][]const u8{ "REX_SERVER", "REX_CLIENT" }) |key| env.remove(key);
    var clutch_failure: ?[]const u8 = null;
    var clutch = clutch_state.Store.openRead(allocator, &env, path, sid, bid) catch |err| blk: {
        clutch_failure = clutch_state.failureReason(err);
        break :blk @as(?clutch_state.Store, null);
    };
    defer if (clutch) |*store| store.close();
    var clutch_file: ?[]const u8 = null;
    var clutch_initial: []const u8 = "unknown";
    if (clutch) |*store| prepare: {
        // Send only reads. An absent record is released; Lua rechecks this path before input.
        const previous = store.read(allocator) catch |err| {
            clutch_failure = clutch_state.failureReason(err);
            break :prepare;
        };
        clutch_file = store.path;
        clutch_initial = if (previous != null and previous.?.held) "held" else "released";
    }
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
    var collector: Collector = .{ .allocator = allocator, .draft = .{ .mode = mode }, .clutch = .{ .state = clutch_initial, .failure_reason = clutch_failure } };
    var locked = false;
    var acquired = false;
    var backend_started = false;
    defer if (locked) std.fs.cwd().deleteDir(lock_path) catch {};
    var outcome: []const u8 = "backend_error";
    var failure: ?[]const u8 = null;
    var backend: ?supervised.Result = null;
    var encoded_argument_bytes: ?usize = null;
    var queued_id: ?[]const u8 = null;
    var deferred_reason: ?[]const u8 = null;
    const queue_request = try std.json.Stringify.valueAlloc(allocator, .{
        .socket = if (clutch) |store| store.socket else path,
        .session = sid,
        .pane = bid,
        .sender = sender,
        .body = message,
        .draft = mode,
        .draft_wait_ms = draft_wait_ms,
        .timeout_ms = timeout_ms,
    }, .{});
    const exchange = env.get("TEEREX_QUEUE_DISPATCH");
    const drain_child = no_queue and exchange != null and
        std.mem.eql(u8, env.get("TEEREX_QUEUE_LOCK") orelse "", lock_path);
    var settle_file: ?[]const u8 = if (drain_child) try std.fs.path.join(allocator, &.{ exchange.?, "previous" }) else null;
    defer if (!drain_child) {
        if (settle_file) |file| std.fs.deleteFileAbsolute(file) catch {};
    };
    work: {
        // A diagnostic is for the invoking caller, never a message to another pane.
        const body = std.mem.trimStart(u8, message, " \t\n");
        for ([_][]const u8{ "send refused:", "pane control refused;", "pane_guard_", "registered_seat_", "agent-send: not delivered", "teerex send:" }) |prefix| {
            if (std.mem.startsWith(u8, body, prefix)) {
                std.debug.print("teerex send: refusal_text_is_not_a_message\n", .{});
                failure = "refusal_text_is_not_a_message";
                outcome = "refused";
                break :work;
            }
        }
        if (input_failure) |reason| {
            failure = reason;
            outcome = if (std.mem.eql(u8, reason, "StdinDeadlineExceeded")) "deadline_exceeded" else "cancel_requested";
            break :work;
        }
        while (!drain_child) {
            if (supervised.requestedSignal() != 0) break :work;
            const elapsed = timer.read() / std.time.ns_per_ms;
            if (elapsed >= timeout_ms) {
                outcome = "deadline_exceeded";
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
        const elapsed = timer.read() / std.time.ns_per_ms;
        if (elapsed >= timeout_ms) {
            outcome = "deadline_exceeded";
            break :work;
        }
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
        if (!no_queue and std.mem.eql(u8, clutch_initial, "held")) {
            if (clutch) |*store| {
                queued_id = enqueue(allocator, &env, store, queue_request, true) catch |err| {
                    failure = @errorName(err);
                    outcome = "refused";
                    break :work;
                };
                if (queued_id != null) {
                    collector.clutch.held_observed = true;
                    outcome = "queued";
                    deferred_reason = "pane_held_by_human";
                    break :work;
                }
            }
        }
        if (!drain_child) {
            if (clutch) |*store| {
                const stopped = drainPending(allocator, &env, store, mode, timeout_ms, if (no_queue) draft_wait_ms else 0, &timer, &settle_file) catch |err| {
                    failure = @errorName(err);
                    outcome = "refused";
                    break :work;
                };
                if (stopped) |reason| {
                    collector.reason = reason;
                    collector.draft.state = if (std.mem.eql(u8, reason, "draft_present")) "present" else "unknown";
                    outcome = "refused";
                    break :work;
                }
            }
        }
        const request = try std.json.Stringify.valueAlloc(allocator, .{
            .session_id = sid,
            .block_id = bid,
            .draft_mode = mode,
            .draft_wait_ms = draft_wait_ms,
            .clutch_file = clutch_file,
            .clutch_failure = clutch_failure,
            .queue_on_hold = !no_queue,
            .queue_exchange = if (drain_child) exchange else null,
            .settle_file = settle_file,
            .text = try std.fmt.allocPrint(allocator, "FROM {s}: {s}", .{ sender, message }),
        }, .{});
        encoded_argument_bytes = request.len;
        const argv = [_][]const u8{ "rex", "--autostart=false", "--server", endpoint, "--timeout", "3s", "--color", "never", "do", "--session", sid, "--block", bid, "-e", "-- teerex-guarded-message\n" ++ @embedFile("draft.lua") ++ "\n" ++ @embedFile("send.lua"), "--args", request };
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
    // Queue only before any input attempt; a failed or uncertain dispatch is never replayable.
    if (!no_queue and deferrable(collector.reason) and !collector.paste_attempted and
        supervised.requestedSignal() == 0)
    {
        if (clutch) |*store| {
            queued_id = enqueue(allocator, &env, store, queue_request, false) catch |err| blk: {
                failure = @errorName(err);
                break :blk null;
            };
            if (queued_id != null) {
                outcome = "queued";
                deferred_reason = collector.reason;
                collector.reason = null;
            }
        } else {
            failure = "QueueStoreUnavailable";
        }
    }
    collector.draft.deferred = queued_id != null and
        (std.mem.eql(u8, deferred_reason orelse "", "draft_present") or
            std.mem.eql(u8, deferred_reason orelse "", "input_state_unknown"));
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
        .queue_id = queued_id,
        .deferred_reason = deferred_reason,
        .failure_reason = failure orelse collector.reason orelse if (backend != null and !success and queued_id == null) @as(?[]const u8, "rex_transport_incomplete") else null,
        .cancellation_signal = if (signal == 0) @as(?u8, null) else signal,
        .draft = collector.draft,
        .clutch = .{ .cooperative = true, .state_file = clutch_file, .state = collector.clutch.state, .failure_reason = collector.clutch.failure_reason, .held_observed = collector.clutch.held_observed, .waited_ms = collector.clutch.waited_ms, .bound_reached = collector.clutch.bound_reached },
        .paste = .{ .attempted = collector.paste_attempted, .acknowledged = collector.paste_acknowledged },
        .enter = .{ .attempted = collector.enter_attempted, .acknowledged = collector.enter_acknowledged },
        .attempt_evidence = "received_local_pre_call_frames_not_server_dispatch_proof",
        .backend_invoked = backend_started,
        .cooperative_lock = .{ .path = lock_path, .acquired = acquired, .scope = "same_host_and_temp_directory_cooperating_senders" },
        .server_enforced_atomic_delivery = false,
        .exclusive_input_lease = false,
        .application_consumption = "not_assessed",
        .prompt_safety = "not_assessed",
        .retry_safe = deferrable(collector.reason) and !collector.paste_attempted,
    }, .{ .whitespace = .indent_2 });
    try std.fs.File.stdout().writeAll(output);
    try std.fs.File.stdout().writeAll("\n");
    return if (signal != 0) 128 + signal else if (std.mem.eql(u8, outcome, "deadline_exceeded")) 124 else if (success or queued_id != null) 0 else 1;
}

const QueueCollector = struct {
    allocator: std.mem.Allocator,
    bytes: std.ArrayList(u8) = .empty,
    pub fn receive(self: *QueueCollector, bytes: []const u8) !void {
        try self.bytes.appendSlice(self.allocator, bytes);
    }
};

fn deferrable(reason: ?[]const u8) bool {
    for ([_][]const u8{ "pane_held_by_human", "draft_present", "input_state_unknown", "queued_messages_pending" }) |value| {
        if (std.mem.eql(u8, reason orelse "", value)) return true;
    }
    return false;
}

fn enqueue(allocator: std.mem.Allocator, env: *const std.process.EnvMap, store: *clutch_state.Store, request: []const u8, require_hold: bool) !?[]const u8 {
    // The hold/store may have appeared after this send entered draft guarding.
    var current = try clutch_state.Store.open(allocator, env, store.socket, store.session, store.pane);
    defer current.close();
    const dir = current.dir orelse return error.QueueStoreUnavailable;
    var random: [16]u8 = undefined;
    std.crypto.random.bytes(&random);
    const name = try std.fmt.allocPrint(allocator, "{s}.request", .{std.fmt.bytesToHex(random, .lower)});
    const file = try dir.createFile(name, .{ .exclusive = true, .mode = 0o600 });
    defer file.close();
    defer dir.deleteFile(name) catch {};
    try file.writeAll(request);
    try file.sync();
    const request_path = try std.fs.path.join(allocator, &.{ std.fs.path.dirname(current.path).?, name });
    const argv = [_][]const u8{ "python3", "-I", "-c", queue_source, "enqueue", current.path, request_path, if (require_hold) "pane_held_by_human" else "deferred" };
    var collector = QueueCollector{ .allocator = allocator };
    const result = try supervised.collect(allocator, &argv, env, 2000, &collector);
    if (result.stopped or result.term != .Exited or result.term.Exited != 0) return error.QueueWriteFailed;
    const Reply = struct { outcome: []const u8, id: ?[]const u8 = null };
    const reply = (try std.json.parseFromSlice(Reply, allocator, collector.bytes.items, .{ .allocate = .alloc_always })).value;
    if (std.mem.eql(u8, reply.outcome, "queued")) return reply.id orelse error.QueueIdMissing;
    if (std.mem.eql(u8, reply.outcome, "released")) return null;
    return error.QueueWriteFailed;
}

fn drainPending(allocator: std.mem.Allocator, env: *const std.process.EnvMap, store: *clutch_state.Store, mode: []const u8, timeout: u64, draft_wait_ms: u64, timer: *std.time.Timer, settle_file: *?[]const u8) !?[]const u8 {
    const queue_path = try std.fmt.allocPrint(allocator, "{s}.queue", .{store.path[0 .. store.path.len - ".json".len]});
    var queue = std.fs.openDirAbsolute(queue_path, .{ .iterate = true, .no_follow = true }) catch |err| switch (err) {
        error.FileNotFound => return null,
        else => return err,
    };
    defer queue.close();
    try clutch_state.privateStat(queue.fd, true);
    var entries = queue.iterate();
    while (try entries.next()) |entry| {
        if (std.mem.endsWith(u8, entry.name, ".pending.json") or std.mem.endsWith(u8, entry.name, ".inflight.json")) break;
    } else return null;
    if (std.mem.eql(u8, mode, "ignore")) return "queued_messages_pending";
    const elapsed = timer.read() / std.time.ns_per_ms;
    if (elapsed >= timeout) return "queued_messages_pending";
    // Keep the previous envelope in a private file, outside argv and receipts.
    var random: [16]u8 = undefined;
    std.crypto.random.bytes(&random);
    const name = try std.fmt.allocPrint(allocator, "{s}.settle", .{std.fmt.bytesToHex(random, .lower)});
    const settle_path = try std.fs.path.join(allocator, &.{ std.fs.path.dirname(store.path).?, name });
    const file = try std.fs.createFileAbsolute(settle_path, .{ .exclusive = true, .mode = 0o600 });
    settle_file.* = settle_path;
    file.close();
    const raw = try std.json.Stringify.valueAlloc(allocator, .{
        .target = .{ .socket = store.socket, .session = store.session, .pane = store.pane },
        .draft_wait_ms = draft_wait_ms,
        .settle_file = settle_path,
    }, .{});
    const argv = [_][]const u8{ "python3", "-I", "-c", queue_source, "drain", store.path, try std.fs.selfExePathAlloc(allocator), raw, "--locked" };
    var collector = QueueCollector{ .allocator = allocator };
    const result = try supervised.collect(allocator, &argv, env, timeout - elapsed, &collector);
    if (result.stopped or result.term != .Exited) return "queued_messages_pending";
    const Reply = struct { queue: struct { stopped: ?struct { reason: []const u8 } = null } };
    const reply = (try std.json.parseFromSlice(Reply, allocator, collector.bytes.items, .{ .allocate = .alloc_always, .ignore_unknown_fields = true })).value;
    if (reply.queue.stopped) |stopped| return if (deferrable(stopped.reason)) stopped.reason else "queued_messages_pending";
    return null;
}
