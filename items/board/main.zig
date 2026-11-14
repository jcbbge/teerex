//! Event-driven board: bounded model, row diffs, ANSI theme slots, optional kitty marks.
const std = @import("std");
const builtin = @import("builtin");
const p = std.posix;
const A = std.mem.Allocator;
const Value = std.json.Value;
const Parsed = std.json.Parsed(Value);
const ESC = "\x1b";
const usage =
    \\Usage: teerex board [--config ABS] [--hosts hive,m5] [--replay FILE]
    \\                    [--tasks ABS_DIR] [--width N --height N] [--no-graphics] [--once] [--json] [--lens 1-5] [--benchmark N]
    \\Live Rex/teerex events and machine vitals. Event-driven; no screen timer.
    \\--json prints finite per-host rows and header counts from live feeds or replay.
    \\Feed: teerex board feed --help
    \\Replay is JSONL v1; EOF holds the final frame, q exits. --once prints it and exits.
    \\Keys: j/k or arrows select; Enter jump; Space scratchpad; m machine;
    \\      1–5 lenses; d decisions; ? keys; q quit. Mouse selects; double-click jumps; wheel scrolls.
    \\Uses ANSI theme slots and cell-aware Unicode rows.
    \\NO_COLOR disables colour. --no-graphics is accepted as a no-op.
    \\--benchmark N measures N changed 60-column frames without terminal output.
    \\
;

fn get(v: Value, key: []const u8) Value {
    return if (v == .object) v.object.get(key) orelse .null else .null;
}
fn str(v: Value) []const u8 {
    return if (v == .string) v.string else "";
}
fn text(v: Value, key: []const u8) []const u8 {
    return str(get(v, key));
}
fn num(v: Value) f64 {
    return switch (v) {
        .integer => @floatFromInt(v.integer),
        .float => if (std.math.isFinite(v.float)) v.float else 0,
        else => 0,
    };
}
fn eq(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}
fn arr(v: Value) []const Value {
    return if (v == .array) v.array.items else &.{};
}
fn fmt(a: A, comptime format: []const u8, args: anytype) ![]const u8 {
    return std.fmt.allocPrint(a, format, args);
}
fn percent(v: Value) f64 {
    const total = num(get(v, "total"));
    return if (total > 0) @min(100, 100 * num(get(v, "used")) / total) else 0;
}
fn integer(n: f64) u64 {
    return @intFromFloat(@max(0, @min(1e15, n)));
}
fn amount(a: A, n: f64) ![]const u8 {
    const names = [_][]const u8{ "B", "K", "M", "G", "T" };
    var val = @max(0, n);
    var unit: usize = 0;
    while (val >= 1024 and unit < 4) : (unit += 1) val /= 1024;
    return fmt(a, "{d:.1}{s}", .{ val, names[unit] });
}

fn memUsed(a: A, mem: Value) ![]const u8 {
    const used = try amount(a, num(get(mem, "used")));
    const total = try amount(a, num(get(mem, "total")));
    return if (used[used.len - 1] == total[total.len - 1]) used[0 .. used.len - 1] else used;
}

const Role = enum { words, secondary, accent, problem, pass, lines, marks, warning };
const Line = struct { value: []const u8, role: Role = .words, selected: bool = false, held_broken: ?bool = null };
const Host = struct {
    name: []const u8,
    vitals: ?Parsed = null,
    reachable: ?bool = null,
    held: ?Parsed = null,
    decisions: ?Parsed = null,
    attention: ?Parsed = null,
    history: [48]f64 = @splat(0),
    count: usize = 0,
};
const Model = struct {
    allocator: A,
    hosts: [2]Host = .{ .{ .name = "hive" }, .{ .name = "m5" } },
    agents: std.ArrayList(Parsed) = .empty,
    tasks: std.ArrayList(Parsed) = .empty,
    stream: std.ArrayList(Parsed) = .empty,
    timestamp: i64 = 0,
    replay: bool = false,
    ended: bool = false,
    invalid: usize = 0,
    fn deinit(self: *Model) void {
        for (&self.hosts) |*h| if (h.vitals) |*v| v.deinit();
        for (&self.hosts) |*h| if (h.held) |*v| v.deinit();
        for (&self.hosts) |*h| if (h.decisions) |*v| v.deinit();
        for (&self.hosts) |*h| if (h.attention) |*v| v.deinit();
        for (self.agents.items) |*v| v.deinit();
        for (self.stream.items) |*v| v.deinit();
        for (self.tasks.items) |*v| v.deinit();
        self.tasks.deinit(self.allocator);
        self.agents.deinit(self.allocator);
        self.stream.deinit(self.allocator);
    }
    fn ingest(self: *Model, bytes: []const u8) !bool {
        const parsed = std.json.parseFromSlice(Value, self.allocator, bytes, .{ .allocate = .alloc_always, .max_value_len = 65536 }) catch {
            self.invalid += 1;
            return false;
        };
        var retained = false;
        defer if (!retained) parsed.deinit();
        const v = parsed.value;
        const name = text(v, "host");
        const host: usize = if (eq(name, "hive")) 0 else if (eq(name, "m5")) 1 else {
            self.invalid += 1;
            return false;
        };
        if (num(get(v, "v")) != 1 or num(get(v, "t")) <= 0) {
            self.invalid += 1;
            return false;
        }
        self.timestamp = @max(self.timestamp, @as(i64, @intFromFloat(@min(1e15, num(get(v, "t"))))));
        const kind = text(v, "kind");
        if (eq(kind, "vitals")) {
            const h = &self.hosts[host];
            if (h.vitals) |*old| old.deinit();
            h.vitals = parsed;
            retained = true;
            std.mem.copyForwards(f64, h.history[0..47], h.history[1..48]);
            h.history[47] = @max(0, @min(100, num(get(v, "cpu_total"))));
            h.count = @min(48, h.count + 1);
        } else if (eq(kind, "host")) {
            const reachable = get(v, "reachable");
            self.hosts[host].reachable = if (reachable == .bool) reachable.bool else null;
        } else if (eq(kind, "held")) {
            if (get(v, "available") != .bool or get(v, "items") != .array or arr(get(v, "items")).len > 256) {
                self.invalid += 1;
                return false;
            }
            for (arr(get(v, "items"))) |item| {
                if (text(item, "id").len == 0 or get(item, "text") != .string or get(item, "since") != .integer or get(item, "broken") != .bool) {
                    self.invalid += 1;
                    return false;
                }
            }
            if (self.hosts[host].held) |*old| old.deinit();
            self.hosts[host].held = parsed;
            retained = true;
        } else if (eq(kind, "decisions")) {
            if (get(v, "available") != .bool or get(v, "decisions") != .array) {
                self.invalid += 1;
                return false;
            }
            if (self.hosts[host].decisions) |*old| old.deinit();
            self.hosts[host].decisions = parsed;
            retained = true;
        } else if (eq(kind, "attention")) {
            if (get(v, "available") != .bool or get(v, "over_share") != .bool or
                (get(v, "available").bool and (get(v, "messages") != .integer or get(v, "messages").integer < 0)))
            {
                self.invalid += 1;
                return false;
            }

            if (self.hosts[host].attention) |*old| old.deinit();
            self.hosts[host].attention = parsed;
            retained = true;
        } else if (eq(kind, "agent")) {
            const id = text(v, "id");
            if (id.len == 0 or id.len > 256) return false;
            const state = text(v, "state");
            for (self.agents.items, 0..) |*old, i| {
                if (eq(text(old.value, "id"), id) and eq(text(old.value, "host"), name)) {
                    old.deinit();
                    if (eq(state, "gone")) {
                        _ = self.agents.orderedRemove(i);
                    } else {
                        old.* = parsed;
                        retained = true;
                    }
                    return true;
                }
            }
            if (!eq(state, "gone")) {
                try self.agents.append(self.allocator, parsed);
                retained = true;
            }
        } else if (eq(kind, "task")) {
            const id = text(v, "id");
            if (id.len == 0 or (!eq(text(v, "state"), "gone") and (get(v, "title") != .string or get(v, "owner") != .string or get(v, "done") != .bool or get(v, "chunks") != .array))) {
                self.invalid += 1;
                return false;
            }
            for (self.tasks.items, 0..) |*old, i| {
                if (eq(text(old.value, "id"), id) and eq(text(old.value, "host"), name)) {
                    old.deinit();
                    if (eq(text(v, "state"), "gone")) {
                        _ = self.tasks.orderedRemove(i);
                    } else {
                        old.* = parsed;
                        retained = true;
                    }
                    return true;
                }
            }
            if (!eq(text(v, "state"), "gone")) {
                try self.tasks.append(self.allocator, parsed);
                retained = true;
            }
        } else if (eq(kind, "stream")) {
            if (self.stream.items.len == 128) {
                var old = self.stream.orderedRemove(0);
                old.deinit();
            }
            try self.stream.append(self.allocator, parsed);
            retained = true;
        } else {
            self.invalid += 1;
            return false;
        }
        return true;
    }
};

// Input is untrusted terminal data. Strip controls/bidi; bound by DISPLAY cells,
// preserving combining marks and reserving two cells for CJK/emoji codepoints.
fn cellWidth(cp: u21) usize {
    if ((cp >= 0x300 and cp <= 0x36f) or (cp >= 0xfe00 and cp <= 0xfe0f) or (cp >= 0x1ab0 and cp <= 0x1aff)) return 0;
    if (@import("width.zig").isWide(cp)) return 2;
    return 1;
}
fn clip(a: A, input: []const u8, width: usize) ![]const u8 {
    var out: std.ArrayList(u8) = .empty;
    var it = (std.unicode.Utf8View.init(input) catch return "?").iterator();
    var used: usize = 0;
    while (it.nextCodepoint()) |cp| {
        if (cp == 0xfe0f or cp < 32 or (cp >= 127 and cp <= 159) or (cp >= 0x202a and cp <= 0x202e) or (cp >= 0x2066 and cp <= 0x2069)) continue;
        const size = cellWidth(cp);
        if (used + size > width) break;
        var buf: [4]u8 = undefined;
        const len = try std.unicode.utf8Encode(cp, &buf);
        try out.appendSlice(a, buf[0..len]);
        used += size;
    }
    return out.toOwnedSlice(a);
}
fn cells(input: []const u8) usize {
    var it = (std.unicode.Utf8View.init(input) catch return input.len).iterator();
    var n: usize = 0;
    while (it.nextCodepoint()) |cp| n += cellWidth(cp);
    return n;
}
fn repeat(a: A, glyph: []const u8, n: usize) ![]const u8 {
    var out: std.ArrayList(u8) = .empty;
    for (0..n) |_| try out.appendSlice(a, glyph);
    return out.toOwnedSlice(a);
}
fn fit(a: A, input: []const u8, width: usize) ![]const u8 {
    const clean = try clip(a, input, std.math.maxInt(usize));
    if (cells(clean) <= width) return clean;
    var normalized: std.ArrayList(u8) = .empty;
    var words = std.mem.tokenizeAny(u8, clean, " \t\r\n");
    while (words.next()) |word| {
        if (normalized.items.len > 0) try normalized.append(a, ' ');
        try normalized.appendSlice(a, word);
    }
    if (cells(normalized.items) <= width) return normalized.items;
    if (width == 0) return "";
    if (width == 1) return "…";
    const cut = try clip(a, normalized.items, width - 1);
    var end = std.mem.trimEnd(u8, cut, " ").len;
    const whole = (cut.len < normalized.items.len and normalized.items[cut.len] == ' ') or std.mem.endsWith(u8, cut, " ");
    if (!whole) if (std.mem.lastIndexOfScalar(u8, cut[0..end], ' ')) |space| {
        if (cells(cut[0..space]) >= cells(cut[0..end]) / 2) end = space;
    };
    return fmt(a, "{s}…", .{trimFitEnd(cut[0..end])});
}
fn trimFitEnd(input: []const u8) []const u8 {
    var result = input;
    while (result.len > 0) {
        if (std.mem.endsWith(u8, result, "·")) {
            result = result[0 .. result.len - "·".len];
            continue;
        }
        if (std.mem.indexOfScalar(u8, " ,;:-", result[result.len - 1]) == null) break;
        result = result[0 .. result.len - 1];
    }
    return result;
}
fn lr(a: A, left: []const u8, right: []const u8, width: usize) ![]const u8 {
    const r = try fit(a, right, width);
    const l = try fit(a, left, width -| (cells(r) + if (r.len > 0) @as(usize, 2) else 0));
    return fmt(a, "{s}{s}{s}", .{ l, try repeat(a, " ", width -| (cells(l) + cells(r))), r });
}
fn age(a: A, now: i64, contact: f64) ![]const u8 {
    const seconds = @divTrunc(@max(0, now - @as(i64, @intFromFloat(@max(0, @min(1e15, contact))))), 1000);
    if (seconds < 60) return "now";
    return fmt(a, "{d}{s}", .{ @divTrunc(seconds, if (seconds < 3600) @as(i64, 60) else if (seconds < 86400) @as(i64, 3600) else 86400), if (seconds < 3600) "m" else if (seconds < 86400) "h" else "d" });
}
const AgentKind = enum { stuck, waiting, working, idle, finished, seat };
fn agentKind(r: Value) AgentKind {
    const state = text(r, "state");
    if (eq(text(r, "role"), "seat") or eq(text(r, "name"), "seat")) return .seat;
    if (eq(state, "error") or (get(r, "stalled") == .bool and get(r, "stalled").bool) or (eq(state, "idle") and text(r, "now").len == 0 and text(r, "waiting").len == 0)) return .stuck;
    if (eq(state, "waiting") or eq(state, "blocked") or text(r, "waiting").len > 0) return .waiting;
    if (eq(state, "working")) return .working;
    if (num(get(r, "total")) > 0 and num(get(r, "done")) == num(get(r, "total"))) return .finished;
    return .idle;
}
fn mark(k: AgentKind) []const u8 {
    return switch (k) {
        .stuck => "!",
        .waiting => "⧗",
        .working => "●",
        .idle => "○",
        .finished => "✓",
        .seat => "◆",
    };
}
fn boardLess(_: void, x: Value, y: Value) bool {
    const kx = @intFromEnum(agentKind(x));
    const ky = @intFromEnum(agentKind(y));
    return if (kx == ky) std.mem.lessThan(u8, text(x, "name"), text(y, "name")) else kx < ky;
}
fn stepLabel(a: A, r: Value) ![]const u8 {
    var total = num(get(r, "step_total"));
    var n = num(get(r, "step_n"));
    if (total == 0) {
        total = num(get(r, "total"));
        n = num(get(r, "done")) + @as(f64, if (text(r, "now").len > 0) 1 else 0);
    }
    return if (total > 0) fmt(a, "{d}/{d}", .{ integer(n), integer(total) }) else "";
}
fn nowLabel(r: Value) []const u8 {
    const value = text(r, "now");
    if (value.len == 0) return "no Now line";
    var i: usize = 0;
    while (i < value.len and std.ascii.isDigit(value[i])) : (i += 1) {}
    if (i > 0) {
        if (i < value.len and std.mem.indexOfScalar(u8, ".):", value[i]) != null) i += 1;
        if (i < value.len and std.ascii.isWhitespace(value[i])) return std.mem.trimStart(u8, value[i..], " \t");
    }
    return value;
}
fn bar(a: A, value: f64, width: usize) ![]const u8 {
    const exact = @max(0, @min(100, value)) * @as(f64, @floatFromInt(width)) / 100;
    var full: usize = @intFromFloat(@round(exact));
    // Python's reference uses ties-to-even rounding.
    if (exact - @floor(exact) == 0.5 and full % 2 == 1) full -= 1;
    return fmt(a, "{s}{s}", .{ try repeat(a, "█", full), try repeat(a, "░", width - full) });
}
fn spark(a: A, host: Host, width: usize) ![]const u8 {
    const ramp = [_][]const u8{ "▁", "▂", "▃", "▄", "▅", "▆", "▇", "█" };
    const n = @min(width, host.count);
    var out: std.ArrayList(u8) = .empty;
    try out.appendSlice(a, try repeat(a, " ", width - n));
    for (host.history[48 - n ..]) |v| try out.appendSlice(a, ramp[@min(7, @as(usize, @intFromFloat(v * 8 / 100)))]);
    return out.toOwnedSlice(a);
}
fn priority(v: Value) usize {
    const state = text(v, "state");
    return if ((eq(state, "waiting") or eq(state, "blocked"))) 0 else if (eq(state, "error")) 1 else if (eq(state, "working")) 2 else 3;
}
fn stalled(model: *Model, row: Value) bool {
    if (get(row, "stalled") == .bool and get(row, "stalled").bool) return true;
    const waiting = text(row, "waiting");
    if (eq(text(row, "state"), "idle") and text(row, "now").len == 0 and waiting.len == 0) return true;
    if (waiting.len > 0) {
        var parts = std.mem.splitSequence(u8, waiting, " · ");
        const target = parts.next() orelse return false;
        for (model.agents.items) |entry| {
            if (!eq(text(row, "host"), text(entry.value, "host")) or !eq(target, text(entry.value, "name"))) continue;
            const state = text(entry.value, "state");
            if (eq(state, "idle") or eq(state, "done") or eq(state, "error")) return true;
        }
    }
    return false;
}
fn less(_: void, a: Value, b: Value) bool {
    const pa = priority(a);
    const pb = priority(b);
    return if (pa != pb) pa < pb else std.ascii.lessThanIgnoreCase(text(a, "name"), text(b, "name"));
}
const Counts = struct {
    total: usize = 0,
    working: usize = 0,
    waiting: usize = 0,
    blocked: usize = 0,
    error_count: usize = 0,
    idle: usize = 0,
    done: usize = 0,
    unknown: usize = 0,
};
fn countRows(rows: []const Value) Counts {
    var counts: Counts = .{ .total = rows.len };
    for (rows) |row| {
        const state = text(row, "state");
        if (eq(state, "working")) counts.working += 1 else if (eq(state, "waiting")) counts.waiting += 1 else if (eq(state, "blocked")) counts.blocked += 1 else if (eq(state, "error")) counts.error_count += 1 else if (eq(state, "idle")) counts.idle += 1 else if (eq(state, "done")) counts.done += 1 else counts.unknown += 1;
    }
    return counts;
}

fn heldLess(_: void, a: Value, b: Value) bool {
    return num(get(a, "since")) < num(get(b, "since"));
}
const lenses = [_][]const u8{ "agent", "project", "waiting", "cost", "machine" };
fn group(row: Value, lens: usize) []const u8 {
    return switch (lens) {
        1 => if (text(row, "project").len > 0) text(row, "project") else "none",
        2 => if (text(row, "waiting").len > 0) "waiting edges" else "ready",
        3 => if (get(row, "cost") == .object) "measured cost" else "unknown cost",
        4 => text(row, "host"),
        else => "working",
    };
}
fn lensLess(lens: usize, a: Value, b: Value) bool {
    if (lens == 3) {
        const x = num(get(get(a, "cost"), "current_turn_seconds"));
        const y = num(get(get(b, "cost"), "current_turn_seconds"));
        if (x != y) return x > y;
    }
    const x = group(a, lens);
    const y = group(b, lens);
    return if (!eq(x, y)) std.ascii.lessThanIgnoreCase(x, y) else less({}, a, b);
}
// Scratchpad Waiting text often starts "waiting on"; the row already says "⧗ on".
fn waitingText(row: Value) []const u8 {
    const value = text(row, "waiting");
    const prefix = "waiting on ";
    return if (value.len > prefix.len and std.ascii.eqlIgnoreCase(value[0..prefix.len], prefix)) value[prefix.len..] else value;
}
fn waitTarget(row: Value) []const u8 {
    var parts = std.mem.splitSequence(u8, text(row, "waiting"), " · ");
    return parts.next() orelse "";
}
fn waitChildren(a: A, rows: []const Value, out: *std.ArrayList(Value), row: Value) anyerror!void {
    for (out.items) |seen| if (eq(text(seen, "id"), text(row, "id"))) return;
    try out.append(a, row);
    for (rows) |child| if (waitTarget(child).len > 0 and eq(waitTarget(child), text(row, "name"))) {
        try waitChildren(a, rows, out, child);
    };
}
fn taskLess(_: void, x: Value, y: Value) bool {
    const bx = eq(text(x, "state"), "BLOCKED");
    const by = eq(text(y, "state"), "BLOCKED");
    if (bx != by) return bx;
    const nx = std.fmt.parseInt(u64, text(x, "number"), 10) catch 0;
    const ny = std.fmt.parseInt(u64, text(y, "number"), 10) catch 0;
    return if (nx != ny) nx < ny else std.mem.lessThan(u8, text(x, "id"), text(y, "id"));
}
fn ownerRow(model: *Model, owner: []const u8) ?Value {
    for (model.agents.items) |entry| if (eq(text(entry.value, "name"), owner)) return entry.value;
    return null;
}
fn normalizeTitle(a: A, input: []const u8) ![]const u8 {
    var out: std.ArrayList(u8) = .empty;
    var it = (std.unicode.Utf8View.init(input) catch return "?").iterator();
    while (it.nextCodepoint()) |cp| {
        if (cp >= 0x2460 and cp <= 0x2473) {
            try out.appendSlice(a, try fmt(a, "{d}", .{cp - 0x2460 + 1}));
        } else if (cp != 0x2501 and cp != 0x2500) {
            var buf: [4]u8 = undefined;
            const len = try std.unicode.utf8Encode(cp, &buf);
            try out.appendSlice(a, buf[0..len]);
        }
    }
    return std.mem.trim(u8, out.items, " ");
}
fn wrapTitle(a: A, input: []const u8, width: usize) ![][]const u8 {
    var out: std.ArrayList([]const u8) = .empty;
    var words = std.mem.tokenizeAny(u8, input, " \t\r\n");
    var current: []const u8 = "";
    while (words.next()) |word| {
        const trial = if (current.len > 0) try fmt(a, "{s} {s}", .{ current, word }) else word;
        if (cells(trial) <= width) {
            current = trial;
            continue;
        }
        if (out.items.len == 1) {
            try out.append(a, try fit(a, try fmt(a, "{s}{s}{s}", .{ trial, if (words.rest().len > 0) " " else "", words.rest() }), width));
            return out.toOwnedSlice(a);
        }
        try out.append(a, if (current.len > 0) current else try fit(a, word, width));
        current = if (current.len > 0) word else "";
    }
    if (current.len > 0 or out.items.len == 0) try out.append(a, current);
    return out.toOwnedSlice(a);
}

const UI = struct {
    lens: usize = 0,
    host: usize = 0,
    selected: usize = 0,
    selected_id: [256]u8 = @splat(0),
    selected_len: usize = 0,
    last_selected: usize = 0,
    selected_host: usize = 0,
    inline_pad: bool = false,
    pad: ?Parsed = null,
    pad_id: [256]u8 = @splat(0),
    pad_len: usize = 0,
    pad_host: usize = 0,
    help: bool = false,
    stream_focus: bool = false,
    stream_offset: usize = 0,
    status: []const u8 = "",
    // A status note shows for 30 s of feed time after it changes, then fades;
    // judged on redraw, so no timer runs. Replay time never advances, so it stays.
    status_shown: []const u8 = "",
    status_at: i64 = 0,
    rows: std.ArrayList(Value) = .empty,
    held_rows: std.ArrayList(Value) = .empty,
    hit: [256]?usize = @splat(null),
    tasks_view: bool = false,
    show_finished: bool = false,
    task_rows: std.ArrayList(Value) = .empty,
    held_open: bool = false,
    decisions_open: bool = false,
    decision_index: usize = 0,
    fn note(self: *UI, model: *Model) ?[]const u8 {
        if (self.status.len == 0) return null;
        if (self.status.ptr != self.status_shown.ptr or self.status.len != self.status_shown.len) {
            self.status_shown = self.status;
            self.status_at = model.timestamp;
        }
        // A note set before the first event is stamped when feed time starts.
        if (self.status_at == 0) self.status_at = model.timestamp;
        return if (model.timestamp - self.status_at < 30000) self.status else null;
    }
    fn visible(self: *UI, model: *Model) !void {
        self.rows.clearRetainingCapacity();
        for (model.agents.items) |entry| if (eq(text(entry.value, "host"), model.hosts[self.host].name)) {
            try self.rows.append(model.allocator, entry.value);
        };
        std.mem.sort(Value, self.rows.items, self.lens, lensLess);
        if (self.lens == 2) {
            var ordered: std.ArrayList(Value) = .empty;
            for (self.rows.items) |row| {
                var parent = false;
                for (self.rows.items) |candidate| if (waitTarget(row).len > 0 and eq(waitTarget(row), text(candidate, "name"))) {
                    parent = true;
                    break;
                };
                if (!parent) try waitChildren(model.allocator, self.rows.items, &ordered, row);
            }
            for (self.rows.items) |row| try waitChildren(model.allocator, self.rows.items, &ordered, row);
            self.rows.deinit(model.allocator);
            self.rows = ordered;
        }
        self.held_rows.clearRetainingCapacity();
        if (model.hosts[self.host].held) |held| {
            if (get(held.value, "available") == .bool and get(held.value, "available").bool and model.hosts[self.host].reachable != false) {
                try self.held_rows.appendSlice(model.allocator, arr(get(held.value, "items")));
                std.mem.sort(Value, self.held_rows.items, {}, heldLess);
            }
        }
        if (self.selected == self.last_selected and self.host == self.selected_host and self.selected_len > 0) {
            for (self.rows.items, 0..) |row, i| if (eq(text(row, "id"), self.selected_id[0..self.selected_len])) {
                self.selected = i;
                break;
            };
        }
        self.selected = @min(self.selected, (self.rows.items.len + self.held_rows.items.len) -| 1);
        self.last_selected = self.selected;
        self.selected_host = self.host;
        self.selected_len = 0;
        if (self.selected < self.rows.items.len) {
            const id = text(self.rows.items[self.selected], "id");
            self.selected_len = @min(id.len, self.selected_id.len);
            @memcpy(self.selected_id[0..self.selected_len], id[0..self.selected_len]);
        }
    }
    fn add(lines: *std.ArrayList(Line), a: A, value: []const u8, role: Role) !void {
        try lines.append(a, .{ .value = value, .role = role });
    }
    fn layout(self: *UI, a: A, model: *Model, width: usize, height: usize) ![]Line {
        self.hit = @splat(null);
        if (self.tasks_view) return self.tasksLayout(a, model, width, height);
        var lines: std.ArrayList(Line) = .empty;
        const host = model.hosts[self.host];
        const inner = width -| 2;
        const clock: u64 = @intCast(@mod(@divTrunc(model.timestamp, 1000), 86400));
        const decisions = if (host.decisions) |d| arr(get(d.value, "decisions")) else &.{};
        const decision_known = host.decisions != null and get(host.decisions.?.value, "available") == .bool and get(host.decisions.?.value, "available").bool;
        const decision_count = if (decision_known) try fmt(a, "{d}", .{decisions.len}) else "?";
        const right = if (host.reachable == false) try fmt(a, "! {s} offline", .{host.name}) else if (!decision_known and host.decisions != null) "asks ?" else if (decisions.len > 0) try fmt(a, "{d} asks", .{decisions.len}) else "";
        try add(&lines, a, try lr(a, try fmt(a, "{s}  {d:0>2}:{d:0>2}", .{ host.name, clock / 3600, clock / 60 % 60 }), right, inner), .words);
        if (host.vitals) |v| try self.vitals(&lines, a, host, v.value, inner) else {
            try add(&lines, a, "cpu  unknown", .secondary);
            try add(&lines, a, "mem  unknown", .secondary);
            try add(&lines, a, "disk unknown", .secondary);
        }
        var live: std.ArrayList(Value) = .empty;
        var finished: std.ArrayList(Value) = .empty;
        var working: usize = 0;
        var waiting: usize = 0;
        var stuck: usize = 0;
        for (self.rows.items) |r| switch (agentKind(r)) {
            .seat => {},
            .finished => try finished.append(a, r),
            else => |k| {
                try live.append(a, r);
                working += @intFromBool(k == .working);
                waiting += @intFromBool(k == .waiting);
                stuck += @intFromBool(k == .stuck);
            },
        };
        if (self.lens == 0) std.mem.sort(Value, live.items, {}, boardLess);
        const counts_title = try fmt(a, "agents · {d} working{s}{s}", .{ working, if (waiting > 0) try fmt(a, " · {d} waiting", .{waiting}) else "", if (stuck > 0) try fmt(a, " · {d} stuck", .{stuck}) else "" });
        try self.section(&lines, a, counts_title, width);
        for (self.rows.items) |r| if (agentKind(r) == .seat) {
            try add(&lines, a, try fmt(a, "◆ seat  {s}", .{if (eq(text(r, "state"), "working")) "working" else "at rest"}), .words);
        };
        const bottom = 1 + @as(usize, @intFromBool(finished.items.len > 0)) + @as(usize, @intFromBool(self.held_rows.items.len > 0));
        const room = height -| (lines.items.len + bottom);
        var first: usize = 0;
        var selected_live: usize = 0;
        for (live.items, 0..) |r, i| if (self.selected < self.rows.items.len and eq(text(r, "id"), text(self.rows.items[self.selected], "id"))) {
            selected_live = i;
        };
        while (first < selected_live) {
            var needed: usize = 0;
            for (live.items[first .. selected_live + 1]) |r| needed += agentHeight(r, inner);
            if (needed <= room -| @as(usize, @intFromBool(selected_live + 1 < live.items.len))) break;
            first += 1;
        }
        var used: usize = 0;
        var shown: usize = 0;
        for (live.items[first..], first..) |r, li| {
            const rh = agentHeight(r, inner);
            if (used + rh > room -| @as(usize, @intFromBool(li + 1 < live.items.len))) break;
            var index: usize = 0;
            for (self.rows.items, 0..) |candidate, i| if (eq(text(candidate, "id"), text(r, "id"))) {
                index = i;
                break;
            };
            if (self.lens != 0 and (li == first or !eq(group(r, self.lens), group(live.items[li - 1], self.lens)))) try add(&lines, a, group(r, self.lens), .accent);
            try self.agentLine(&lines, a, model, r, index, nowLabel(r), inner, .words);
            used += rh;
            shown += 1;
        }
        if (shown < live.items.len) try add(&lines, a, try fmt(a, "+ {d} more  ↓", .{live.items.len - shown}), .secondary);
        if (finished.items.len > 0) {
            var names: std.ArrayList(u8) = .empty;
            for (finished.items, 0..) |r, i| {
                if (i > 0) try names.appendSlice(a, ", ");
                try names.appendSlice(a, text(r, "name"));
            }
            try add(&lines, a, try fmt(a, "✓ {d} finished: {s}", .{ finished.items.len, names.items }), .secondary);
        }
        if (self.held_rows.items.len > 0) {
            const held_selected = self.selected >= self.rows.items.len;
            // Preserve the selected held item when live rows fill the pane.
            if (self.held_open and held_selected and lines.items.len > height -| 4) {
                const retained = @min(lines.items.len, height -| 4);
                lines.shrinkRetainingCapacity(retained);
                for (retained..self.hit.len) |i| self.hit[i] = null;
            }
            try add(&lines, a, try lr(a, try fmt(a, "▸ held {d} · oldest {s}", .{ self.held_rows.items.len, try age(a, model.timestamp, num(get(self.held_rows.items[0], "since"))) }), "h", inner), .secondary);
            lines.items[lines.items.len - 1].selected = held_selected and !self.held_open;
            if (self.held_open) {
                const held_room = height -| (lines.items.len + 1);
                const held_first = if (held_selected) (self.selected - self.rows.items.len + 1) -| held_room else 0;
                for (self.held_rows.items[held_first..], held_first..) |item, i| {
                    if (lines.items.len < self.hit.len) self.hit[lines.items.len] = self.rows.items.len + i;
                    try lines.append(a, .{ .value = try fmt(a, "  {s}  {s:>3}", .{ try fit(a, text(item, "text"), inner -| 7), try age(a, model.timestamp, num(get(item, "since"))) }), .selected = self.selected == self.rows.items.len + i, .held_broken = get(item, "broken").bool });
                }
            }
        } else if (host.held != null and !get(host.held.?.value, "available").bool) try add(&lines, a, "held work · unavailable", .secondary);
        if (self.inline_pad and self.selected < self.rows.items.len) {
            const r = self.rows.items[self.selected];
            try add(&lines, a, try fmt(a, "Scratchpad · {s}", .{text(r, "name")}), .accent);
            const pad = if (self.pad != null and self.pad_host == self.host and eq(self.pad_id[0..self.pad_len], text(r, "id"))) self.pad.?.value else .null;
            try self.machine(&lines, a, if (pad == .object) pad else r, r, inner);
            try add(&lines, a, try fmt(a, "{d}/{d} steps done", .{ integer(num(get(r, "done"))), integer(num(get(r, "total"))) }), .secondary);
        }
        if (self.decisions_open) {
            lines.shrinkRetainingCapacity(@min(lines.items.len, 1));
            self.hit = @splat(null);
            try self.section(&lines, a, "decisions", width);
            if (self.decision_index >= decisions.len) self.decision_index = 0;
            if (decisions.len > 0) {
                const d = decisions[self.decision_index];
                try add(&lines, a, text(d, "title"), .accent);
                try add(&lines, a, text(d, "ask"), .words);
                try add(&lines, a, text(d, "context"), .secondary);
                for (arr(get(d, "options")), 1..) |option, i| {
                    try add(&lines, a, try fmt(a, "{d}. {s}", .{ i, text(option, "label") }), .words);
                    try add(&lines, a, try fmt(a, "+ {s}", .{text(option, "gain")}), .secondary);
                    try add(&lines, a, try fmt(a, "− {s}", .{text(option, "lose")}), .secondary);
                }
                try add(&lines, a, try fmt(a, "Recommendation: {s}", .{text(d, "recommend")}), .secondary);
                try add(&lines, a, "1–8 answer · j/k browse · d returns", .secondary);
            } else try add(&lines, a, if (eq(decision_count, "?")) "Decision source unavailable · d returns" else "No open decisions · d returns", .secondary);
        }
        if (self.help) {
            lines.shrinkRetainingCapacity(@min(lines.items.len, 2));
            self.hit = @splat(null);
            try add(&lines, a, "↑↓ / j k  select · Enter  jump to pane", .accent);
            try add(&lines, a, "1–5 lens · Space proof · m hive / m5", .words);
            try add(&lines, a, "d  decisions · wheel  browse · q  quit", .words);
            try add(&lines, a, "Click selects · double-click jumps", .words);
        }
        if (model.invalid > 0) try add(&lines, a, try fmt(a, "! {d} unreadable events ignored", .{model.invalid}), .problem);
        if (self.note(model)) |status| try add(&lines, a, status, .secondary);
        if (model.ended and !model.replay) try add(&lines, a, "! Live feed stopped · q quits", .problem);
        // Keep keys anchored and never let the terminal's bottom-right cell scroll.
        const footer = try fmt(a, "⏎ jump  ␣ steps  h held  m {s}  ? keys", .{model.hosts[1 - self.host].name});
        if (lines.items.len >= height) lines.shrinkRetainingCapacity(height - 1);
        while (lines.items.len + 1 < height) try add(&lines, a, "", .words);
        try add(&lines, a, footer, .lines);
        for (lines.items) |*line| line.value = try fit(a, line.value, inner);
        return lines.toOwnedSlice(a);
    }
    fn tasksLayout(self: *UI, a: A, model: *Model, width: usize, height: usize) ![]Line {
        const content = width -| 2;
        var lines: std.ArrayList(Line) = .empty;
        self.task_rows.clearRetainingCapacity();
        var finished: std.ArrayList(Value) = .empty;
        var blocked: usize = 0;
        for (model.tasks.items) |entry| {
            if (!eq(text(entry.value, "host"), model.hosts[self.host].name)) continue;
            if (get(entry.value, "done").bool) {
                try finished.append(a, entry.value);
            } else {
                try self.task_rows.append(model.allocator, entry.value);
                blocked += @intFromBool(eq(text(entry.value, "state"), "BLOCKED"));
            }
        }
        std.mem.sort(Value, self.task_rows.items, {}, taskLess);
        const open = self.task_rows.items.len;
        if (self.show_finished) try self.task_rows.appendSlice(model.allocator, finished.items);
        self.selected = @min(self.selected, self.task_rows.items.len -| 1);
        const clock: u64 = @intCast(@mod(@divTrunc(model.timestamp, 1000), 86400));
        try add(&lines, a, try lr(a, try fmt(a, "tasks  {d} open{s}", .{ open, if (blocked > 0) try fmt(a, " · {d} blocked", .{blocked}) else "" }), try fmt(a, "{d:0>2}:{d:0>2}", .{ clock / 3600, clock / 60 % 60 }), content), .words);
        try add(&lines, a, "", .words);
        var body: std.ArrayList(Line) = .empty;
        var starts: std.ArrayList(usize) = .empty;
        for (self.task_rows.items[0..open], 0..) |t, index| {
            try starts.append(a, body.items.len);
            const pre = try fmt(a, "{s}{s}{s} ", .{ if (eq(text(t, "state"), "BLOCKED")) "!" else " ", try repeat(a, " ", 2 -| cells(text(t, "number"))), text(t, "number") });
            const indent = try repeat(a, " ", cells(pre));
            const title = try normalizeTitle(a, text(t, "title"));
            const wrapped = try wrapTitle(a, title, content -| cells(pre));
            for (wrapped, 0..) |part, i| try add(&body, a, try fmt(a, "{s}{s}", .{ if (i == 0) pre else indent, part }), if (eq(text(t, "state"), "BLOCKED")) .problem else .words);
            const owner = text(t, "owner");
            const who = if (ownerRow(model, owner)) |r| try fmt(a, "{s}  {s} {s}{s}", .{ owner, mark(agentKind(r)), try stepLabel(a, r), if (num(get(r, "last_contact_at")) > 0) try fmt(a, " · {s}", .{try age(a, model.timestamp, num(get(r, "last_contact_at")))}) else "" }) else blk: {
                var done: usize = 0;
                for (arr(get(t, "chunks"))) |chunk| done += @intFromBool(eq(text(chunk, "mark"), "done"));
                break :blk try fmt(a, "{s}  ○ not running · {d}/{d}", .{ owner, done, arr(get(t, "chunks")).len });
            };
            try add(&body, a, try fmt(a, "{s}{s}", .{ indent, try fit(a, who, content -| cells(indent)) }), .secondary);
            for (arr(get(t, "chunks"))) |chunk| if (eq(text(chunk, "mark"), "now")) {
                try add(&body, a, try fmt(a, "{s}▶ {s}", .{ indent, try fit(a, text(chunk, "text"), content -| (cells(indent) + 2)) }), .accent);
            };
            if (text(t, "last").len > 0) try add(&body, a, try fmt(a, "{s}{s}", .{ indent, try fit(a, text(t, "last"), content -| cells(indent)) }), .secondary);
            try add(&body, a, "", .words);
            for (starts.items[index]..body.items.len) |i| body.items[i].selected = self.selected == index;
        }
        var offset: usize = 0;
        if (self.selected < open and starts.items[self.selected] >= height -| 3) offset = starts.items[self.selected];
        for (body.items[offset..], offset..) |line, i| {
            if (lines.items.len >= height -| 1) break;
            for (starts.items, 0..) |start, index| if (i >= start and (index + 1 == starts.items.len or i < starts.items[index + 1])) {
                if (lines.items.len < self.hit.len) self.hit[lines.items.len] = index;
                break;
            };
            try lines.append(a, line);
        }
        if (finished.items.len > 0) {
            try add(&lines, a, try fmt(a, "✓ {d} finished{s}", .{ finished.items.len, if (self.show_finished) "" else "  ·  f shows" }), .secondary);
            if (self.show_finished) for (finished.items, open..) |t, index| {
                if (lines.items.len < self.hit.len) self.hit[lines.items.len] = index;
                try lines.append(a, .{ .value = try fmt(a, "  {s}", .{try fit(a, try fmt(a, "{s} {s}", .{ text(t, "number"), try normalizeTitle(a, text(t, "title")) }), content -| 2)}), .selected = self.selected == index });
            };
        }
        if (self.help) {
            lines.shrinkRetainingCapacity(@min(lines.items.len, 2));
            try add(&lines, a, "j/k select · Enter jump to owner", .words);
            try add(&lines, a, "f finished · m host · q quit", .words);
        }
        if (self.note(model)) |status| try add(&lines, a, status, .secondary);
        if (lines.items.len >= height) lines.shrinkRetainingCapacity(height -| 1);
        while (lines.items.len < height -| 1) try add(&lines, a, "", .words);
        try add(&lines, a, "⏎ jump to lead  f finished  ? keys", .lines);
        for (lines.items) |*line| line.value = try fit(a, line.value, content);
        return lines.toOwnedSlice(a);
    }
    fn section(_: *UI, lines: *std.ArrayList(Line), a: A, title: []const u8, width: usize) !void {
        const head = try fit(a, try fmt(a, "─ {s} ", .{title}), width -| 2);
        try add(lines, a, try fmt(a, "{s}{s}", .{ head, try repeat(a, "─", (width -| 2) -| cells(head)) }), .lines);
    }
    fn agentHeight(r: Value, width: usize) usize {
        return (if (width >= 64) @as(usize, 1) else 2) + @as(usize, @intFromBool(agentKind(r) == .stuck or text(r, "waiting").len > 0));
    }
    fn agentLine(self: *UI, lines: *std.ArrayList(Line), a: A, model: *Model, r: Value, index: usize, now: []const u8, width: usize, _: Role) !void {
        const k = agentKind(r);
        const start = lines.items.len;
        const st = try stepLabel(a, r);
        const contact = if (num(get(r, "last_contact_at")) > 0) num(get(r, "last_contact_at")) else num(get(r, "since"));
        const ago = if (contact > 0) try age(a, model.timestamp, contact) else "";
        if (width >= 64) {
            const name = try fit(a, text(r, "name"), 12);
            const head = try fmt(a, "{s} {s}{s} {s:>5}  ", .{ mark(k), name, try repeat(a, " ", 12 -| cells(name)), st });
            const tail = try fmt(a, "  {s:>3}", .{ago});
            const budget = width -| (cells(head) + cells(tail));
            const label = try fit(a, now, budget);
            try add(lines, a, try fmt(a, "{s}{s}{s}{s}", .{ head, label, try repeat(a, " ", budget -| cells(label)), tail }), if (k == .stuck) .problem else .words);
        } else {
            try add(lines, a, try lr(a, try fmt(a, "{s} {s}", .{ mark(k), text(r, "name") }), if (st.len > 0) try fmt(a, "{s}  {s:>3}", .{ st, ago }) else ago, width), if (k == .stuck) .problem else .words);
            try add(lines, a, try fmt(a, "  {s}", .{try fit(a, now, width -| 2)}), if (k == .stuck) .problem else .words);
        }
        if (k == .stuck) {
            try add(lines, a, try fmt(a, "  {s}", .{try fit(a, try fmt(a, "stalled · {s}", .{if (eq(text(r, "state"), "error")) "error" else if (text(r, "now").len == 0) "idle, no Now line" else "no contact"}), width -| 2)}), .problem);
        } else if (text(r, "waiting").len > 0) {
            try add(lines, a, try fmt(a, "  {s}", .{try fit(a, try fmt(a, "⧗ on {s}{s}{s}", .{ waitingText(r), if (text(r, "check").len > 0) " · check " else "", text(r, "check") }), width -| 2)}), .secondary);
        }
        for (start..lines.items.len) |i| {
            if (i < self.hit.len) self.hit[i] = index;
            lines.items[i].selected = index == self.selected;
        }
        if (self.lens == 3) {
            const cost = get(r, "cost");
            try add(lines, a, try fmt(a, "  tokens {s} · {s} · turn {s}", .{ if (get(cost, "tokens_in") == .null or get(cost, "tokens_out") == .null) "unknown" else try fmt(a, "{d}", .{integer(num(get(cost, "tokens_in")) + num(get(cost, "tokens_out")))}), if (get(cost, "dollars") == .null) "unknown" else try fmt(a, "${d:.4}", .{num(get(cost, "dollars"))}), if (get(cost, "current_turn_seconds") == .null) "unknown" else try fmt(a, "{d}m", .{integer(num(get(cost, "current_turn_seconds")) / 60)}) }), .secondary);
        }
    }
    fn machine(_: *UI, lines: *std.ArrayList(Line), a: A, pad: Value, row: Value, width: usize) !void {
        const executor = if (text(row, "executor").len > 0) text(row, "executor") else "agent";
        const steps = arr(get(pad, "steps"));
        var outcome: []const u8 = "—";
        var unfinished = false;
        if (steps.len > 0) {
            for (steps) |step| {
                const state = text(step, "state");
                if (!eq(state, "done")) unfinished = true;
                const by = if (text(step, "by").len > 0) text(step, "by") else executor;
                const result = text(step, "outcome");
                if (eq(state, "done") and result.len > 0) outcome = result;
                const label = try clip(a, text(step, "text"), @max(8, width -| (cells(by) + 15)));
                try add(lines, a, try fmt(a, "  {s} {s}  {s}{s}{s}{s}{s}{s}", .{ if (eq(state, "done")) (if (text(step, "proof").len > 0) "✓" else "unproven") else if (eq(state, "now")) "▶" else " ", label, by, if (eq(state, "now")) " ← now" else "", if (result.len > 0) " ■ " else "", result, if (text(step, "handoff").len > 0) " ⇥ " else "", text(step, "handoff") }), if (eq(state, "now")) .accent else .secondary);
                if (eq(state, "done") and text(step, "proof").len > 0) try add(lines, a, try fmt(a, "    proof: {s}", .{text(step, "proof")}), .secondary);
            }
        } else {
            var completed = arr(get(pad, "done")).len;
            while (completed > 0) {
                completed -= 1;
                try add(lines, a, try fmt(a, "  {s}  {s}", .{ try fmt(a, "{s} {s}", .{ if (std.mem.indexOf(u8, str(arr(get(pad, "done"))[completed]), " — proof: ") != null) "✓" else "unproven", str(arr(get(pad, "done"))[completed]) }), executor }), .secondary);
            }
            if (text(pad, "now").len > 0) try add(lines, a, try fmt(a, "  ▶ {s}  {s} ← now", .{ text(pad, "now"), executor }), .accent);
            for (arr(get(pad, "todo"))) |item| try add(lines, a, try fmt(a, "    {s}  {s}", .{ str(item), executor }), .secondary);
        }
        try add(lines, a, try fmt(a, "  end: {s}", .{if (unfinished) "—" else outcome}), .secondary);
    }
    fn vitals(_: *UI, lines: *std.ArrayList(Line), a: A, host: Host, v: Value, width: usize) !void {
        const mem = get(v, "mem");
        const cpu = num(get(v, "cpu_total"));
        const bw = @max(8, @min(30, width -| (11 + if (width >= 60) @as(usize, 12) else 0)));
        try add(lines, a, try fmt(a, "cpu  {s}  {d}%", .{ try spark(a, host, bw), integer(cpu) }), .marks);
        try add(lines, a, try fmt(a, "mem  {s}  {d}%{s}", .{ try bar(a, percent(mem), bw), integer(percent(mem)), if (width >= 60) try fmt(a, "  {s}/{s}", .{ try memUsed(a, mem), try amount(a, num(get(mem, "total"))) }) else "" }), .marks);
        const disks = arr(get(v, "disks"));
        if (disks.len > 0) {
            const disk = disks[0];
            try add(lines, a, try fmt(a, "disk {s}  {d}%{s}", .{ try bar(a, percent(disk), bw), integer(percent(disk)), if (width >= 60) try fmt(a, "  {s}", .{text(disk, "mount")}) else "" }), .marks);
        } else try add(lines, a, "disk unknown", .secondary);
    }
};

const RGB = [3]u8;
fn luminance(rgb: RGB) f64 {
    var result: f64 = 0;
    for (rgb, [_]f64{ 0.2126, 0.7152, 0.0722 }) |v, factor| {
        const c = @as(f64, @floatFromInt(v)) / 255;
        result += factor * (if (c <= 0.04045) c / 12.92 else std.math.pow(f64, (c + 0.055) / 1.055, 2.4));
    }
    return result;
}
fn contrast(a: RGB, b: RGB) f64 {
    const x = luminance(a);
    const y = luminance(b);
    return (@max(x, y) + 0.05) / (@min(x, y) + 0.05);
}
const Theme = struct {
    colors: [18]?RGB = @splat(null),
    slots: [8]usize = .{ 16, 7, 6, 1, 2, 8, 6, 3 },
    color: bool = true,
    fn choose(self: *Theme) void {
        const desired = [_]usize{ 16, 7, 6, 1, 2, 8, 6, 3 };
        for (desired, 0..) |slot, role| {
            self.slots[role] = slot;
            const bg = self.colors[17] orelse {
                self.slots[role] = if (role == @intFromEnum(Role.marks)) 6 else if (role == @intFromEnum(Role.warning)) 3 else 16;
                continue;
            };
            const threshold: f64 = if (role == @intFromEnum(Role.lines)) 1.5 else if (role == @intFromEnum(Role.marks)) 3 else 4.5;
            if (self.colors[slot]) |fg| if (contrast(fg, bg) >= threshold) continue;
            self.slots[role] = 16;
            if (self.colors[16]) |fg| if (contrast(fg, bg) >= threshold) continue;
            var best: f64 = 0;
            for (self.colors[0..16], 0..) |maybe, i| if (maybe) |rgb| {
                const ratio = contrast(rgb, bg);
                if (role == @intFromEnum(Role.warning) and (i == 1 or i == 9)) continue;
                if (ratio > best) {
                    best = ratio;
                    self.slots[role] = i;
                }
            };
        }
    }
    fn sgr(self: Theme, a: A, role: Role) ![]const u8 {
        if (!self.color) return "";
        const slot = self.slots[@intFromEnum(role)];
        return if (slot == 16) ESC ++ "[39m" else fmt(a, ESC ++ "[{d}m", .{if (slot < 8) 30 + slot else 90 + slot - 8});
    }
    fn parse(self: *Theme, response: []const u8) bool {
        // OSC payload: 4;N;rgb:rrrr/gggg/bbbb or 10/11;rgb:…
        var parts = std.mem.splitScalar(u8, response, ';');
        const command = parts.next() orelse return false;
        const index = if (eq(command, "10")) @as(usize, 16) else if (eq(command, "11")) @as(usize, 17) else if (eq(command, "4")) std.fmt.parseInt(usize, parts.next() orelse return false, 10) catch return false else return false;
        if (index >= 18) return false;
        const rgb_text = parts.next() orelse return false;
        if (!std.mem.startsWith(u8, rgb_text, "rgb:")) return false;
        var channels = std.mem.splitScalar(u8, rgb_text[4..], '/');
        var color: RGB = undefined;
        for (&color) |*channel| {
            const s = channels.next() orelse return false;
            if (s.len == 0 or s.len > 4) return false;
            const raw = std.fmt.parseInt(u32, s, 16) catch return false;
            const max: u32 = (@as(u32, 1) << @as(u5, @intCast(s.len * 4))) - 1;
            channel.* = @intCast(raw * 255 / max);
        }
        if (channels.next() != null) return false;
        const changed = self.colors[index] == null or !std.mem.eql(u8, &self.colors[index].?, &color);
        self.colors[index] = color;
        self.choose();
        return changed;
    }
};

const Renderer = struct {
    allocator: A,
    previous: std.ArrayList([]const u8) = .empty,
    width: usize = 0,
    fn deinit(self: *Renderer) void {
        for (self.previous.items) |line| self.allocator.free(line);
        self.previous.deinit(self.allocator);
    }
    fn frame(self: *Renderer, a: A, lines: []const Line, theme: Theme, width: usize, sync: bool) ![]const u8 {
        var output: std.ArrayList(u8) = .empty;
        if (sync) try output.appendSlice(a, ESC ++ "[?2026h");
        const full = self.width != width;
        self.width = width;
        for (lines, 0..) |line, row| {
            const value = try fit(a, line.value, width -| 2);
            const content = try fmt(a, " {s}{s}", .{ value, try repeat(a, " ", (width -| 2) -| cells(value)) });
            // Held colour has one meaning: ANSI red is broken, all other held ink is default.
            const ink = if (line.held_broken) |broken| if (!theme.color) "" else if (broken) ESC ++ "[31m" else ESC ++ "[39m" else try theme.sgr(a, line.role);
            const styled = try fmt(a, "{s}{s}{s}{s}", .{ ink, if (line.selected) ESC ++ "[7m" else "", content, ESC ++ "[0m" });
            if (!full and row < self.previous.items.len and eq(styled, self.previous.items[row])) continue;
            try output.appendSlice(a, try fmt(a, ESC ++ "[{d};1H{s}" ++ ESC ++ "[K", .{ row + 1, styled }));
            if (row < self.previous.items.len) {
                self.allocator.free(self.previous.items[row]);
                self.previous.items[row] = try self.allocator.dupe(u8, styled);
            } else try self.previous.append(self.allocator, try self.allocator.dupe(u8, styled));
        }
        while (self.previous.items.len > lines.len) {
            const row = self.previous.items.len;
            self.allocator.free(self.previous.pop().?);
            try output.appendSlice(a, try fmt(a, ESC ++ "[{d};1H" ++ ESC ++ "[K", .{row}));
        }
        if (sync) try output.appendSlice(a, ESC ++ "[?2026l");
        return output.toOwnedSlice(a);
    }
};

var resized = false;
var stopping = false;
var signal_fd: p.fd_t = -1;
fn signal(sig: i32) callconv(.c) void {
    if (sig == p.SIG.WINCH) resized = true else stopping = true;
    if (signal_fd >= 0) _ = p.write(signal_fd, "s") catch 0;
}
fn dimensions() p.winsize {
    var size: p.winsize = .{ .row = 30, .col = 60, .xpixel = 0, .ypixel = 0 };
    if (builtin.os.tag == .linux) {
        _ = std.os.linux.syscall3(.ioctl, 1, std.os.linux.T.IOCGWINSZ, @intFromPtr(&size));
    } else {
        _ = std.c.ioctl(1, @bitCast(@as(u32, 0x40087468)), &size);
    }
    size.row = @max(4, @min(256, size.row));
    size.col = @max(12, @min(512, size.col));
    return size;
}
fn query() !void {
    try std.fs.File.stdout().writeAll(ESC ++ "[c" ++ ESC ++ "]10;?" ++ ESC ++ "\\" ++ ESC ++ "]11;?" ++ ESC ++ "\\");
    for (0..16) |slot| {
        var buf: [32]u8 = undefined;
        try std.fs.File.stdout().writeAll(try std.fmt.bufPrint(&buf, ESC ++ "]4;{d};?" ++ ESC ++ "\\", .{slot}));
    }
}

// Graphics use exactly the queried ANSI role colour; transparent pixels leave
// the live terminal background intact. No independent RGB palette is invented.
fn jump(allocator: A, self: []const u8, config: []const u8, row: Value) !bool {
    const session = text(row, "session");
    const block = text(row, "block");
    if (!std.mem.startsWith(u8, session, "session:") or !std.mem.startsWith(u8, block, "block:")) return false;
    const result = try std.process.Child.run(.{ .allocator = allocator, .argv = &.{ self, "--config", config, "--host", text(row, "host"), "surfaces", "focus", "--session", session, "--pane", block, "--timeout-ms", "5000" }, .max_output_bytes = 65536 });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    return result.term == .Exited and result.term.Exited == 0;
}

fn activate(allocator: A, self: []const u8, config: []const u8, model: *Model, ui: *UI) ![]const u8 {
    if (ui.tasks_view) {
        if (ui.selected >= ui.task_rows.items.len) return "Task owner unavailable";
        const owner = text(ui.task_rows.items[ui.selected], "owner");
        const row = ownerRow(model, owner) orelse return "Task owner not running";
        return if (try jump(allocator, self, config, row)) "Jumped to pane" else "Jump unavailable · check host connection";
    }
    if (ui.selected < ui.rows.items.len) return if (try jump(allocator, self, config, ui.rows.items[ui.selected])) "Jumped to pane" else "Jump unavailable · check host connection";
    const index = ui.selected - ui.rows.items.len;
    if (index >= ui.held_rows.items.len) return "Held work unavailable";
    const result = try std.process.Child.run(.{ .allocator = allocator, .argv = &.{ self, "board", "feed", "--open-held", "--config", config, "--host-name", model.hosts[ui.host].name, "--held-id", text(ui.held_rows.items[index], "id") }, .max_output_bytes = 65536 });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    return if (result.term == .Exited and result.term.Exited == 0) "Opened held work" else "Held work unavailable";
}

fn scratch(allocator: A, self: []const u8, config: []const u8, row: Value) !?Parsed {
    const result = try std.process.Child.run(.{ .allocator = allocator, .argv = &.{ self, "--config", config, "--host", text(row, "host"), "scratch", "show", "--session", text(row, "session"), "--block", text(row, "block"), "--json" }, .max_output_bytes = 262144 });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (result.term != .Exited or result.term.Exited != 0) return null;
    return std.json.parseFromSlice(Value, allocator, result.stdout, .{ .allocate = .alloc_always }) catch null;
}

const Health = enum {
    calm,
    amber,
    broken,
    fn glyph(self: Health) []const u8 {
        return switch (self) {
            .calm => "○",
            .amber => "🟠",
            .broken => "🔴",
        };
    }
};
fn health(model: *Model) Health {
    if (model.invalid > 0 or (model.ended and !model.replay)) return .broken;
    for (model.hosts) |host| if (host.reachable == false) return .broken;
    var result: Health = .calm;
    for (model.agents.items) |entry| {
        const row = entry.value;
        const state = text(row, "state");
        if (eq(state, "error")) return .broken;
        if (stalled(model, row)) result = .amber;
    }
    return result;
}
const TabLabel = struct {
    allocator: A,
    self: []const u8,
    session: []const u8,
    window: []const u8,
    base: []const u8,
    previous: ?Health = null,
    fn init(a: A, self: []const u8) !?TabLabel {
        var env = try std.process.getEnvMap(a);
        defer env.deinit();
        const session = env.get("LC_REX_SESSION") orelse env.get("REX_SESSION") orelse return null;
        const block = env.get("LC_REX_BLOCK") orelse env.get("REX_BLOCK") orelse return null;
        const result = try std.process.Child.run(.{ .allocator = a, .argv = &.{ self, "surfaces", "inspect", "--session", session, "--pane", block } });
        defer a.free(result.stdout);
        defer a.free(result.stderr);
        if (result.term != .Exited or result.term.Exited != 0) return error.BoardTabInspectFailed;
        const parsed = try std.json.parseFromSlice(Value, a, result.stdout, .{});
        defer parsed.deinit();
        const actual = get(parsed.value, "actual");
        const window = text(actual, "window_id");
        if (window.len == 0 or get(actual, "window_label") != .string) return error.BoardTabMissing;
        var base = text(actual, "window_label");
        for ([_][]const u8{ "○ ", "🟠 ", "🔴 " }) |prefix| {
            if (std.mem.startsWith(u8, base, prefix)) {
                base = base[prefix.len..];
                break;
            }
        }
        return .{ .allocator = a, .self = self, .session = try a.dupe(u8, session), .window = try a.dupe(u8, window), .base = try a.dupe(u8, base) };
    }
    fn rename(self: *TabLabel, label: []const u8) !void {
        const a = self.allocator;
        const result = try std.process.Child.run(.{ .allocator = a, .argv = &.{ self.self, "surfaces", "rename", "--session", self.session, "--window", self.window, "--label", label } });
        defer a.free(result.stdout);
        defer a.free(result.stderr);
        if (result.term != .Exited or result.term.Exited != 0) return error.BoardTabRenameFailed;
    }
    fn update(self: *TabLabel, state: Health) !void {
        if (self.previous == state) return;
        // A failed mutation is not retried on another event with the same state.
        self.previous = state;
        const label = try fmt(self.allocator, "{s} {s}", .{ state.glyph(), self.base });
        defer self.allocator.free(label);
        try self.rename(label);
    }
    fn deinit(self: *TabLabel) void {
        self.rename(self.base) catch |err| std.debug.print("board: restore tab: {s}\n", .{@errorName(err)});
        self.allocator.free(self.session);
        self.allocator.free(self.window);
        self.allocator.free(self.base);
    }
};

const Options = struct { config: []const u8, hosts: []const u8 = "hive,m5", replay: ?[]const u8 = null, once: bool = false, json: bool = false, tasks: ?[]const u8 = null, width: usize = 60, height: usize = 30, lens: usize = 0, benchmark: usize = 0 };
fn options(a: A, args: []const []const u8) !Options {
    const home = try std.process.getEnvVarOwned(a, "HOME");
    var result: Options = .{ .config = try std.fs.path.join(a, &.{ home, ".config/teerex/hosts.json" }) };
    const profiles = try std.fs.path.join(a, &.{ home, ".config/teerex/profiles.json" });
    defer a.free(profiles);
    if (std.fs.cwd().readFileAlloc(a, profiles, std.math.maxInt(usize))) |bytes| {
        defer a.free(bytes);
        if (std.json.parseFromSlice(Value, a, bytes, .{})) |parsed| {
            defer parsed.deinit();
            const preferred = get(get(parsed.value, "defaults"), "board_lens");
            if (preferred == .integer and preferred.integer >= 1 and preferred.integer <= 5) result.lens = @intCast(preferred.integer - 1);
        } else |_| {}
    } else |_| {}
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const s = args[i];
        if (eq(s, "--json")) result.json = true else if (eq(s, "--once")) result.once = true else if (eq(s, "--no-graphics")) {} else if (eq(s, "--config") or eq(s, "--hosts") or eq(s, "--replay") or eq(s, "--benchmark") or eq(s, "--lens") or eq(s, "--width") or eq(s, "--height") or eq(s, "--tasks")) {
            i += 1;
            if (i >= args.len) return error.BoardOptionNeedsValue;
            if (eq(s, "--tasks")) {
                if (!std.fs.path.isAbsolute(args[i])) return error.TasksRequiresAbsoluteDirectory;
                result.tasks = args[i];
            } else if (eq(s, "--config")) result.config = args[i] else if (eq(s, "--hosts")) result.hosts = args[i] else if (eq(s, "--replay")) result.replay = args[i] else if (eq(s, "--lens")) {
                const value = try std.fmt.parseInt(usize, args[i], 10);
                if (value < 1 or value > 5) return error.InvalidLens;
                result.lens = value - 1;
            } else if (eq(s, "--width")) result.width = @max(2, try std.fmt.parseInt(usize, args[i], 10)) else if (eq(s, "--height")) result.height = @max(1, try std.fmt.parseInt(usize, args[i], 10)) else result.benchmark = try std.fmt.parseInt(usize, args[i], 10);
        } else return error.UnknownBoardOption;
    }
    if (result.once and !result.json and result.replay == null) return error.OnceRequiresReplay;
    return result;
}

pub fn run(_: A, args: []const []const u8) !u8 {
    // The command allocator is a lifetime arena. Frames and replaced events
    // must return their storage immediately instead of growing that arena.
    const allocator = std.heap.page_allocator;
    if (args.len > 0 and eq(args[0], "--help")) {
        try std.fs.File.stdout().writeAll(usage);
        return 0;
    }
    const opts = try options(allocator, args);
    if (opts.benchmark > 0) return benchmark(allocator, opts.benchmark);
    var model: Model = .{ .allocator = allocator, .replay = opts.replay != null };
    defer model.deinit();
    var ui: UI = .{ .lens = opts.lens, .tasks_view = opts.tasks != null };
    defer ui.task_rows.deinit(allocator);
    defer ui.rows.deinit(allocator);
    defer ui.held_rows.deinit(allocator);
    defer if (ui.pad) |*pad| pad.deinit();
    var theme: Theme = .{ .color = !std.process.hasEnvVarConstant("NO_COLOR") };
    if (opts.once or opts.json) {
        var feed_failed = false;
        const bytes = if (opts.replay) |path| try std.fs.cwd().readFileAlloc(allocator, path, 16 * 1024 * 1024) else blk: {
            const self = try std.fs.selfExePathAlloc(allocator);
            defer allocator.free(self);
            const result = try std.process.Child.run(.{ .allocator = allocator, .argv = if (opts.tasks) |dir| &.{ self, "board", "feed", "--config", opts.config, "--hosts", opts.hosts, "--once", "--tasks", dir } else &.{ self, "board", "feed", "--config", opts.config, "--hosts", opts.hosts, "--once" }, .max_output_bytes = 16 * 1024 * 1024 });
            defer allocator.free(result.stderr);
            feed_failed = result.term != .Exited or result.term.Exited != 0;
            break :blk result.stdout;
        };
        defer allocator.free(bytes);
        var events = std.mem.splitScalar(u8, bytes, '\n');
        while (events.next()) |line| if (line.len > 0) {
            _ = try model.ingest(line);
        };
        if (opts.json) {
            const HeldSnapshot = struct { available: bool, rows: []const Value, count: usize };
            const Snapshot = struct { host: []const u8, rows: []const Value, counts: Counts, reachable: ?bool, held: ?HeldSnapshot, lens: []const u8, attention: Value };
            var snapshots: std.ArrayList(Snapshot) = .empty;
            defer {
                for (snapshots.items) |snapshot| {
                    allocator.free(snapshot.rows);
                    if (snapshot.held) |held| allocator.free(held.rows);
                }
                snapshots.deinit(allocator);
            }
            var selected = std.mem.splitScalar(u8, opts.hosts, ',');
            while (selected.next()) |name| {
                ui.host = if (eq(name, "hive")) 0 else if (eq(name, "m5")) 1 else return error.UnknownBoardHost;
                try ui.visible(&model);
                const reachable = model.hosts[ui.host].reachable;
                if (reachable != true and opts.replay == null) feed_failed = true;
                try snapshots.append(allocator, .{ .host = name, .lens = lenses[ui.lens], .attention = if (model.hosts[ui.host].attention) |v| v.value else .null, .rows = try allocator.dupe(Value, ui.rows.items), .counts = countRows(ui.rows.items), .reachable = reachable, .held = if (model.hosts[ui.host].held) |held| .{ .available = get(held.value, "available").bool and reachable != false, .rows = try allocator.dupe(Value, ui.held_rows.items), .count = ui.held_rows.items.len } else null });
                if (model.hosts[ui.host].held) |held| {
                    if (!get(held.value, "available").bool) feed_failed = true;
                }
            }
            const output = try std.json.Stringify.valueAlloc(allocator, .{ .lens = lenses[ui.lens], .hosts = snapshots.items, .invalid = model.invalid }, .{});
            defer allocator.free(output);
            try std.fs.File.stdout().writeAll(output);
            try std.fs.File.stdout().writeAll("\n");
            return if (model.invalid == 0 and !feed_failed) 0 else 1;
        }
        try ui.visible(&model);
        var arena = std.heap.ArenaAllocator.init(allocator);
        defer arena.deinit();
        const lines = try ui.layout(arena.allocator(), &model, opts.width, opts.height);
        for (lines) |line| {
            try std.fs.File.stdout().writeAll(try fmt(arena.allocator(), " {s}{s} ", .{ try clip(arena.allocator(), line.value, opts.width -| 2), try repeat(arena.allocator(), " ", (opts.width -| 2) -| cells(try clip(arena.allocator(), line.value, opts.width -| 2))) }));
            try std.fs.File.stdout().writeAll("\n");
        }
        return if (model.invalid == 0) 0 else 1;
    }
    if (!p.isatty(0) or !p.isatty(1)) return error.BoardRequiresTerminal;
    const saved = try p.tcgetattr(0);
    var raw = saved;
    raw.lflag.ECHO = false;
    raw.lflag.ICANON = false;
    raw.lflag.ISIG = false;
    raw.iflag.IXON = false;
    raw.iflag.ICRNL = false;
    raw.cc[@intFromEnum(p.V.MIN)] = 1;
    raw.cc[@intFromEnum(p.V.TIME)] = 0;
    try p.tcsetattr(0, .NOW, raw);
    defer p.tcsetattr(0, .NOW, saved) catch {};
    const signal_pipe = try p.pipe2(.{ .NONBLOCK = true, .CLOEXEC = true });
    defer {
        p.close(signal_pipe[0]);
        p.close(signal_pipe[1]);
        signal_fd = -1;
    }
    signal_fd = signal_pipe[1];
    const handler: p.Sigaction = .{ .handler = .{ .handler = signal }, .mask = p.sigemptyset(), .flags = 0 };
    var old_winch: p.Sigaction = undefined;
    var old_term: p.Sigaction = undefined;
    var old_int: p.Sigaction = undefined;
    p.sigaction(p.SIG.WINCH, &handler, &old_winch);
    p.sigaction(p.SIG.TERM, &handler, &old_term);
    p.sigaction(p.SIG.INT, &handler, &old_int);
    defer {
        p.sigaction(p.SIG.WINCH, &old_winch, null);
        p.sigaction(p.SIG.TERM, &old_term, null);
        p.sigaction(p.SIG.INT, &old_int, null);
    }
    resized = false;
    stopping = false;
    try std.fs.File.stdout().writeAll(ESC ++ "[?1049h" ++ ESC ++ "[?25l" ++ ESC ++ "[?1000h" ++ ESC ++ "[?1006h" ++ ESC ++ "[?1004h");
    defer std.fs.File.stdout().writeAll(ESC ++ "[?2026l" ++ ESC ++ "_Ga=d,d=I,i=197845,q=2" ++ ESC ++ "\\" ++ ESC ++ "[0m" ++ ESC ++ "[?1000l" ++ ESC ++ "[?1006l" ++ ESC ++ "[?1004l" ++ ESC ++ "[?25h" ++ ESC ++ "[?1049l" ++ ESC ++ "]7501;state=clear:id=teerex/board:app=teerex-board" ++ ESC ++ "\\") catch {};
    const self = try std.fs.selfExePathAlloc(allocator);
    defer allocator.free(self);
    // The tasks view shares a tab with the board; only the board owns the tab's health label.
    // Tab-label failures go to the status line: stderr would land in the alternate
    // screen behind the row-diff renderer and never be repainted away.
    var tab_note: [96]u8 = undefined;
    var tab = if (opts.tasks != null) null else TabLabel.init(allocator, self) catch |err| blk: {
        ui.status = std.fmt.bufPrint(&tab_note, "Tab label unavailable: {s}", .{@errorName(err)}) catch "Tab label unavailable";
        break :blk null;
    };
    defer if (tab) |*label| label.deinit();
    var child: ?std.process.Child = null;
    var replay: ?std.fs.File = null;
    var fd: p.fd_t = undefined;
    if (opts.replay) |path| {
        replay = try std.fs.cwd().openFile(path, .{});
        fd = replay.?.handle;
    } else {
        child = std.process.Child.init(if (opts.tasks) |dir| &.{ self, "board", "feed", "--config", opts.config, "--hosts", opts.hosts, "--tasks", dir } else &.{ self, "board", "feed", "--config", opts.config, "--hosts", opts.hosts }, allocator);
        child.?.stdin_behavior = .Ignore;
        child.?.stdout_behavior = .Pipe;
        child.?.stderr_behavior = .Ignore;
        try child.?.spawn();
        fd = child.?.stdout.?.handle;
    }
    defer if (replay) |file| file.close();
    defer if (child) |*c| {
        _ = c.kill() catch {};
    };
    var renderer: Renderer = .{ .allocator = allocator };
    defer renderer.deinit();
    var pending: std.ArrayList(u8) = .empty;
    defer pending.deinit(allocator);
    var keys: std.ArrayList(u8) = .empty;
    defer keys.deinit(allocator);
    var frame_arena = std.heap.ArenaAllocator.init(allocator);
    defer frame_arena.deinit();
    var size = dimensions();
    var dirty = true;
    var last_query: i64 = 0;
    var last_click: i64 = 0;
    var last_click_index: usize = 256;
    try query();
    while (!stopping) {
        const now = std.time.milliTimestamp();
        if (resized) {
            resized = false;
            size = dimensions();
            renderer.width = 0; // any size change repaints every row, height included
            dirty = true;
            try query();
        }
        if (dirty) {
            if (tab) |*label| label.update(health(&model)) catch |err| {
                // Said once; the board keeps running and stops renaming this tab.
                ui.status = std.fmt.bufPrint(&tab_note, "Tab label not changed: {s}", .{@errorName(err)}) catch "Tab label not changed";
                label.deinit();
                tab = null;
            };
            if (!ui.tasks_view) try ui.visible(&model);
            // Reuse only the last frame's scratch storage; no event history.
            _ = frame_arena.reset(.retain_capacity);
            const a = frame_arena.allocator();
            const lines = try ui.layout(a, &model, size.col, size.row);
            // Frame + optional graphic share one DEC 2026 transaction.
            try std.fs.File.stdout().writeAll(ESC ++ "[?2026h");
            try std.fs.File.stdout().writeAll(try renderer.frame(a, lines, theme, size.col, false));
            try std.fs.File.stdout().writeAll(ESC ++ "[?2026l");
            dirty = false;
        }
        var fds = [_]p.pollfd{ .{ .fd = 0, .events = p.POLL.IN, .revents = 0 }, .{ .fd = if (model.ended) -1 else fd, .events = p.POLL.IN, .revents = 0 }, .{ .fd = signal_pipe[0], .events = p.POLL.IN, .revents = 0 } };
        // At rest, poll sleeps indefinitely.
        _ = try p.poll(&fds, -1);
        if (fds[2].revents & p.POLL.IN != 0) {
            var signals: [64]u8 = undefined;
            _ = p.read(signal_pipe[0], &signals) catch 0;
        }
        if (fds[1].revents & (p.POLL.IN | p.POLL.HUP) != 0) {
            var buffer: [65536]u8 = undefined;
            const n = try p.read(fd, &buffer);
            if (n == 0) {
                if (pending.items.len > 0) {
                    _ = try model.ingest(pending.items);
                    pending.clearRetainingCapacity();
                }
                model.ended = true;
                dirty = true;
            } else {
                try pending.appendSlice(allocator, buffer[0..n]);
                while (std.mem.indexOfScalar(u8, pending.items, '\n')) |end| {
                    if (end > 0) {
                        _ = try model.ingest(pending.items[0..end]);
                        dirty = true;
                    }
                    std.mem.copyForwards(u8, pending.items[0..], pending.items[end + 1 ..]);
                    pending.items.len -= end + 1;
                }
                if (pending.items.len > 262144) return error.BoardEventTooLarge;
            }
            if (!model.replay and now - last_query >= 5000) {
                try query();
                last_query = now;
            }
        }
        if (fds[0].revents & (p.POLL.IN | p.POLL.HUP) != 0) {
            var buffer: [8192]u8 = undefined;
            const n = try p.read(0, &buffer);
            if (n == 0) break;
            try keys.appendSlice(allocator, buffer[0..n]);
            var consumed: usize = 0;
            while (consumed < keys.items.len) {
                const input = keys.items[consumed..];
                if (input[0] == 27) {
                    if (input.len < 2) break;
                    if (input[1] == ']' or input[1] == '_' or input[1] == 'P') {
                        const bell = std.mem.indexOfScalar(u8, input, 7);
                        const st = std.mem.indexOf(u8, input, ESC ++ "\\");
                        const end = if (bell != null and (st == null or bell.? < st.?)) bell.? else st orelse break;
                        if (input[1] == ']') dirty = theme.parse(input[2..end]) or dirty;
                        if (input[1] == '_' and std.mem.indexOf(u8, input[2..end], "i=31;OK") != null) {
                            dirty = true;
                        }
                        consumed += end + (if (input[end] == 7) @as(usize, 1) else 2);
                        continue;
                    }
                    if (input[1] == '[' or input[1] == 'O') {
                        var end: usize = 2;
                        while (end < input.len and !(input[end] >= 0x40 and input[end] <= 0x7e)) : (end += 1) {}
                        if (end == input.len) break;
                        const key = input[end];
                        if (key == 'A') {
                            if (ui.stream_focus) ui.stream_offset += 1 else ui.selected -|= 1;
                            dirty = true;
                        }
                        if (key == 'B') {
                            if (ui.stream_focus) ui.stream_offset -|= 1 else ui.selected += 1;
                            dirty = true;
                        }
                        if (key == 'I') {
                            try query();
                            renderer.width = 0; // focus-in repaints every row
                            dirty = true;
                        }
                        if (input.len > 3 and input[2] == '<' and (key == 'M' or key == 'm')) {
                            var fields = std.mem.splitScalar(u8, input[3..end], ';');
                            const button = std.fmt.parseInt(usize, fields.next() orelse "", 10) catch 99;
                            _ = fields.next();
                            const row = std.fmt.parseInt(usize, fields.next() orelse "", 10) catch 0;
                            if (key == 'M' and button == 0 and row > 0 and row <= ui.hit.len) {
                                if (ui.hit[row - 1]) |idx| {
                                    ui.selected = idx;
                                    if (idx == last_click_index and now - last_click < 400 and idx < (if (ui.tasks_view) ui.task_rows.items.len else ui.rows.items.len + ui.held_rows.items.len)) {
                                        ui.status = try activate(allocator, self, opts.config, &model, &ui);
                                    }
                                    last_click = now;
                                    last_click_index = idx;
                                }
                            } else if (button == 64) {
                                if (ui.stream_focus) ui.stream_offset += 1 else ui.selected -|= 1;
                            } else if (button == 65) {
                                if (ui.stream_focus) ui.stream_offset -|= 1 else ui.selected += 1;
                            }
                            dirty = true;
                        }
                        consumed += end + 1;
                        continue;
                    }
                    consumed += 2;
                    continue;
                }
                const key = input[0];
                consumed += 1;
                if (ui.decisions_open and key >= '1' and key <= '8') {
                    if (model.hosts[ui.host].decisions) |*packet| {
                        const list = packet.value.object.getPtr("decisions").?;
                        if (ui.decision_index < list.array.items.len) {
                            const d = list.array.items[ui.decision_index];
                            const choices = arr(get(d, "options"));
                            const choice: usize = key - '1';
                            if (choice < choices.len) {
                                if (model.replay) {
                                    ui.status = "Replay · answer not sent";
                                } else {
                                    const target = get(d, "target");
                                    const result = try std.process.Child.run(.{ .allocator = allocator, .argv = &.{ self, "--config", opts.config, "--host", model.hosts[ui.host].name, "ask", "--store", text(d, "store"), "--session", text(target, "session_id"), "--block", text(target, "block_id"), "--from", "operator", "--resolve", text(d, "id"), "--answer", text(choices[choice], "label") }, .max_output_bytes = 262144 });
                                    defer allocator.free(result.stdout);
                                    defer allocator.free(result.stderr);
                                    if (result.term == .Exited and result.term.Exited == 0) {
                                        _ = list.array.orderedRemove(ui.decision_index);
                                        ui.status = "Answer recorded";
                                    } else ui.status = "Answer not confirmed · inspect decision history";
                                }
                            }
                        }
                    }
                    dirty = true;
                    continue;
                }
                if (ui.decisions_open and (key == 'j' or key == 'k')) {
                    if (key == 'j') ui.decision_index += 1 else ui.decision_index -|= 1;
                    dirty = true;
                    continue;
                }
                switch (key) {
                    '1'...'5' => {
                        ui.lens = key - '1';
                        dirty = true;
                    },
                    'q', 3, 4 => {
                        stopping = true;
                        break;
                    },
                    'j' => {
                        if (ui.stream_focus) ui.stream_offset -|= 1 else ui.selected += 1;
                        dirty = true;
                    },
                    'k' => {
                        if (ui.stream_focus) ui.stream_offset += 1 else ui.selected -|= 1;
                        dirty = true;
                    },
                    'f' => {
                        ui.show_finished = !ui.show_finished;
                        dirty = true;
                    },
                    'h' => {
                        ui.held_open = !ui.held_open;
                        dirty = true;
                    },
                    'd' => {
                        ui.decisions_open = !ui.decisions_open;
                        ui.status = "";
                        dirty = true;
                    },
                    'm' => {
                        ui.host = 1 - ui.host;
                        ui.selected = 0;
                        ui.stream_offset = 0;
                        dirty = true;
                    },
                    ' ' => {
                        ui.inline_pad = !ui.inline_pad;
                        if (ui.inline_pad and ui.selected < ui.rows.items.len) {
                            if (ui.pad) |*old| old.deinit();
                            ui.pad = scratch(allocator, self, opts.config, ui.rows.items[ui.selected]) catch null;
                            const id = text(ui.rows.items[ui.selected], "id");
                            ui.pad_len = @min(id.len, ui.pad_id.len);
                            @memcpy(ui.pad_id[0..ui.pad_len], id[0..ui.pad_len]);
                            ui.pad_host = ui.host;
                        }
                        dirty = true;
                    },
                    '?' => {
                        ui.help = !ui.help;
                        dirty = true;
                    },
                    '\r', '\n' => if ((if (ui.tasks_view) ui.task_rows.items.len else ui.rows.items.len + ui.held_rows.items.len) > 0) {
                        ui.status = try activate(allocator, self, opts.config, &model, &ui);
                        dirty = true;
                    },
                    else => {},
                }
            }
            std.mem.copyForwards(u8, keys.items[0..], keys.items[consumed..]);
            keys.items.len -= consumed;
            if (keys.items.len > 65536) keys.clearRetainingCapacity();
        }
    }
    return 0;
}

fn benchmark(allocator: A, n: usize) !u8 {
    var renderer: Renderer = .{ .allocator = allocator };
    defer renderer.deinit();
    var timer = try std.time.Timer.start();
    var bytes: usize = 0;
    for (0..n) |i| {
        var arena = std.heap.ArenaAllocator.init(allocator);
        defer arena.deinit();
        const a = arena.allocator();
        var lines: [30]Line = @splat(.{ .value = "│  glyph kit · event-driven board  ▓▓▓▒░░" });
        lines[2].value = try fmt(a, "cpu  {d}%  █████▎░░░░░", .{i % 100});
        bytes += (try renderer.frame(a, &lines, .{}, 60, true)).len;
    }
    const ns = timer.read();
    var buf: [256]u8 = undefined;
    try std.fs.File.stdout().writeAll(try std.fmt.bufPrint(&buf, "{{\"frames\":{d},\"width\":60,\"height\":30,\"ns_per_frame\":{d},\"bytes\":{d}}}\n", .{ n, ns / n, bytes }));
    return 0;
}
