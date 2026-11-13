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
    \\                    [--no-graphics] [--once] [--benchmark N]
    \\Live Rex/teerex events and machine vitals. Event-driven; no screen timer.
    \\Feed: teerex board feed --help
    \\Replay is JSONL v1; EOF holds the final frame, q exits. --once prints it and exits.
    \\Keys: j/k or arrows select; Enter jump; Space expand; d decisions; m machine;
    \\      ? keys; q quit. Mouse selects; double-click jumps; wheel scrolls.
    \\Uses ANSI theme slots, queries contrast, and uses kitty charts when supported.
    \\NO_COLOR disables colour and graphics. --no-graphics forces Unicode marks.
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

const Role = enum { words, secondary, accent, problem, pass, lines, marks };
const Line = struct { value: []const u8, role: Role = .words, selected: bool = false };
const Host = struct {
    name: []const u8,
    vitals: ?Parsed = null,
    reachable: ?bool = null,
    history: [48]f64 = @splat(0),
    count: usize = 0,
};
const Model = struct {
    allocator: A,
    hosts: [2]Host = .{ .{ .name = "hive" }, .{ .name = "m5" } },
    agents: std.ArrayList(Parsed) = .empty,
    decisions: ?Parsed = null,
    timestamp: i64 = 0,
    replay: bool = false,
    ended: bool = false,
    invalid: usize = 0,
    fn deinit(self: *Model) void {
        for (&self.hosts) |*h| if (h.vitals) |*v| v.deinit();
        for (self.agents.items) |*v| v.deinit();
        if (self.decisions) |*v| v.deinit();
        self.agents.deinit(self.allocator);
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
        } else if (eq(kind, "agent")) {
            const id = text(v, "id");
            if (id.len == 0 or id.len > 256) return false;
            const state = text(v, "state");
            for (self.agents.items, 0..) |*old, i| {
                if (eq(text(old.value, "id"), id) and eq(text(old.value, "host"), name)) {
                    old.deinit();
                    if (eq(state, "gone") or eq(state, "done")) {
                        _ = self.agents.orderedRemove(i);
                    } else {
                        old.* = parsed;
                        retained = true;
                    }
                    return true;
                }
            }
            if (!eq(state, "gone") and !eq(state, "done") and self.agents.items.len < 256) {
                try self.agents.append(self.allocator, parsed);

                retained = true;
            }
        } else if (eq(kind, "decisions")) {
            if (self.decisions) |*old| old.deinit();
            self.decisions = parsed;
            retained = true;
        } else if (eq(kind, "stream")) {
            return false;
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
fn bar(a: A, value: f64, width: usize) ![]const u8 {
    const eighths = [_][]const u8{ "", "▏", "▎", "▍", "▌", "▋", "▊", "▉" };
    const units: usize = @intFromFloat(@round(@max(0, @min(100, value)) * @as(f64, @floatFromInt(width * 8)) / 100));
    const full = units / 8;
    const part = units % 8;
    return fmt(a, "{s}{s}{s}", .{ try repeat(a, "█", full), eighths[part], try repeat(a, "░", width - full - @intFromBool(part > 0)) });
}
fn spark(a: A, host: Host, width: usize) ![]const u8 {
    const ramp = [_][]const u8{ "⣀", "⣠", "⣤", "⣴", "⣶", "⣾", "⣿" };
    const n = @min(width, host.count);
    var out: std.ArrayList(u8) = .empty;
    try out.appendSlice(a, try repeat(a, "·", width - n));
    for (host.history[48 - n ..]) |v| try out.appendSlice(a, ramp[@min(6, @as(usize, @intFromFloat(v * 6 / 100)))]);
    return out.toOwnedSlice(a);
}
fn priority(v: Value) usize {
    const state = text(v, "state");
    return if (eq(state, "waiting")) 0 else if (eq(state, "error")) 1 else if (eq(state, "working")) 2 else 3;
}
fn stalled(model: *Model, row: Value) bool {
    if (get(row, "stalled") == .bool and get(row, "stalled").bool) return true;
    const wait = get(row, "waiting");
    if (wait == .object) {
        for (model.agents.items) |entry| {
            const target = entry.value;
            if (eq(text(target, "name"), text(wait, "on"))) return eq(text(target, "state"), "error") or (eq(text(target, "state"), "idle") and text(target, "now").len == 0 and get(target, "waiting") != .object);
        }
        return true;
    }
    return eq(text(row, "state"), "idle") and text(row, "now").len == 0;
}
fn less(_: void, a: Value, b: Value) bool {
    const pa = priority(a);
    const pb = priority(b);
    return if (pa != pb) pa < pb else std.ascii.lessThanIgnoreCase(text(a, "name"), text(b, "name"));
}
const UI = struct {
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
    decisions_open: bool = false,
    decision_index: usize = 0,
    status: []const u8 = "",
    rows: std.ArrayList(Value) = .empty,
    hit: [256]?usize = @splat(null),
    fn visible(self: *UI, model: *Model) !void {
        self.rows.clearRetainingCapacity();
        for (model.agents.items) |entry| if (eq(text(entry.value, "host"), model.hosts[self.host].name)) {
            try self.rows.append(model.allocator, entry.value);
        };
        std.mem.sort(Value, self.rows.items, {}, less);
        if (self.selected == self.last_selected and self.host == self.selected_host and self.selected_len > 0) {
            for (self.rows.items, 0..) |row, i| if (eq(text(row, "id"), self.selected_id[0..self.selected_len])) {
                self.selected = i;
                break;
            };
        }
        self.selected = @min(self.selected, self.rows.items.len -| 1);
        self.last_selected = self.selected;
        self.selected_host = self.host;
        self.selected_len = 0;
        if (self.rows.items.len > 0) {
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
        var lines: std.ArrayList(Line) = .empty;
        const host = model.hosts[self.host];
        const inner = width -| 7;
        const clock: u64 = @intCast(@mod(@divTrunc(model.timestamp, 1000), 86400));
        const decisions = if (model.decisions) |v| arr(get(v.value, "decisions")) else &.{};
        const decision_count = if (model.decisions == null) "?" else try fmt(a, "{d}", .{decisions.len -| self.decision_index});
        const title = try fmt(a, " {s}  {s}  {d:0>2}:{d:0>2}  ◇ {s} ", .{ host.name, if (model.replay) "REPLAY" else "LIVE", clock / 3600, clock / 60 % 60, decision_count });
        try add(&lines, a, try fmt(a, "╭{s}{s}╮", .{ title, try repeat(a, "─", (width -| 3) -| cells(title)) }), .lines);
        if (host.reachable == false) try add(&lines, a, "! Connection lost · showing last readings", .problem);
        if (host.vitals) |v| {
            try self.vitals(&lines, a, host, v.value, inner);
        } else try add(&lines, a, "Waiting for machine readings…", .secondary);
        if (width >= 100) {
            const other = model.hosts[1 - self.host];
            if (other.vitals) |v| try add(&lines, a, try fmt(a, "{s}  cpu {d}%   memory {d}%   {s}", .{ other.name, integer(num(get(v.value, "cpu_total"))), integer(percent(get(v.value, "mem"))), if (other.reachable == false) "! unavailable" else "" }), .secondary);
        }
        var waiting: usize = 0;
        var errors: usize = 0;
        var working: usize = 0;
        for (self.rows.items) |r| {
            if (priority(r) == 0) waiting += 1 else if (priority(r) == 1) errors += 1 else if (priority(r) == 2) working += 1;
        }
        try add(&lines, a, try fmt(a, "agents  {d} ► working  {d} ● waiting  {d} !", .{ working, waiting, errors }), .secondary);
        try self.section(&lines, a, "working", width);
        const limit = @max(1, height -| (lines.items.len + 3));
        const first = if (self.selected < limit) 0 else self.selected - limit + 1;
        for (self.rows.items, 0..) |r, i| {
            if (i < first or i >= first + limit) continue;
            const broken = stalled(model, r);
            const label = if (broken and text(r, "now").len == 0 and get(r, "waiting") != .object) "stalled · waiting on nothing" else if (broken) "stalled" else text(r, "now");
            try self.agentLine(&lines, a, model, r, i, label, inner, if (broken or eq(text(r, "state"), "error")) .problem else .words);
            if (self.inline_pad and i == self.selected) {
                const pad = if (!model.replay and arr(get(r, "steps")).len > 0) r else if (self.pad != null and self.pad_host == self.host and eq(self.pad_id[0..self.pad_len], text(r, "id"))) self.pad.?.value else r;
                try self.machine(&lines, a, pad, r, inner);
            }
            const wait = get(r, "waiting");
            if (wait == .object) try add(&lines, a, try fmt(a, "  ⧗ {s} · {s} · {d}m{s}", .{ text(wait, "on"), text(wait, "what"), integer((if (num(get(r, "wait_since_ms")) > 0) @max(0, @as(f64, @floatFromInt(model.timestamp)) - num(get(r, "wait_since_ms"))) else num(get(r, "wait_age_ms"))) / 60000), if (broken) " · stalled" else "" }), if (broken) .problem else .secondary);
        }
        if (self.rows.items.len == 0) try add(&lines, a, "No agents working here", .secondary);
        if (self.rows.items.len > limit) try add(&lines, a, try fmt(a, "{d} more · arrows to browse", .{self.rows.items.len - limit}), .secondary);
        if (self.decisions_open) {
            lines.shrinkRetainingCapacity(@min(lines.items.len, 1));
            self.hit = @splat(null);
            try self.section(&lines, a, "decisions", width);
            if (self.decision_index < decisions.len) {
                const d = decisions[self.decision_index];
                try add(&lines, a, text(d, "title"), .accent);
                try add(&lines, a, text(d, "ask"), .words);
                if (text(d, "context").len > 0) try add(&lines, a, text(d, "context"), .secondary);
                for (arr(get(d, "options"))) |o| try add(&lines, a, try fmt(a, "{s}  {s}{s}", .{ text(o, "key"), text(o, "label"), if (eq(text(o, "key"), text(d, "default"))) "  ← default" else "" }), .words);
                try add(&lines, a, "Enter accepts default · Esc returns", .secondary);
            } else try add(&lines, a, "No open decisions · Esc returns", .secondary);
        }
        if (self.help) {
            lines.shrinkRetainingCapacity(@min(lines.items.len, 2));
            self.hit = @splat(null);
            try add(&lines, a, "↑↓ / j k  select · Enter  jump to pane", .accent);
            try add(&lines, a, "Space  expand steps · m  hive / m5", .words);
            try add(&lines, a, "d  decisions · wheel  browse · q  quit", .words);
            try add(&lines, a, "Click selects · double-click jumps", .words);
        }
        if (model.invalid > 0) try add(&lines, a, try fmt(a, "! {d} unreadable events ignored", .{model.invalid}), .problem);
        if (self.status.len > 0) try add(&lines, a, self.status, .accent);
        if (model.ended and !model.replay) try add(&lines, a, "! Live feed stopped · q quits", .problem);
        // Keep keys anchored and never let the terminal's bottom-right cell scroll.
        const footer = if (width < 55) "╰ ⏎ jump  ␣ steps  d ◇  m host  ? ╯" else "╰ ⏎ jump  ␣ steps  d decisions  m host  ? keys ╯";
        if (lines.items.len >= height) lines.shrinkRetainingCapacity(height - 1);
        while (lines.items.len + 1 < height) try add(&lines, a, "", .words);
        try add(&lines, a, footer, .lines);
        return lines.toOwnedSlice(a);
    }
    fn section(_: *UI, lines: *std.ArrayList(Line), a: A, title: []const u8, width: usize) !void {
        try add(lines, a, try fmt(a, "├ {s} {s}┤", .{ title, try repeat(a, "─", (width -| 6) -| cells(title)) }), .lines);
    }
    fn agentLine(self: *UI, lines: *std.ArrayList(Line), a: A, model: *Model, r: Value, index: usize, now: []const u8, width: usize, role: Role) !void {
        const selected = index == self.selected;
        const done = num(get(r, "done"));
        const total = num(get(r, "total"));
        const progress = if (total > 0) try fmt(a, "{s} {d}/{d}", .{ try bar(a, done * 100 / total, if (width < 45) 5 else 8), integer(done), integer(total) }) else "░░░░░ —";
        _ = model;
        const name = try clip(a, text(r, "name"), 18);
        const room = width -| (cells(name) + cells(progress) + 8);
        const header = try fmt(a, "{s} {s} · {s} · {s}", .{ if (selected) "►" else "·", name, try clip(a, now, room), progress });
        if (lines.items.len < 256) self.hit[lines.items.len] = index;
        try lines.append(a, .{ .value = header, .role = role });
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
                try add(lines, a, try fmt(a, "  {s} {s}  {s}{s}{s}{s}{s}{s}", .{ if (eq(state, "done")) "✓" else if (eq(state, "now")) "▶" else " ", label, by, if (eq(state, "now")) " ← now" else "", if (result.len > 0) " ■ " else "", result, if (text(step, "handoff").len > 0) " ⇥ " else "", text(step, "handoff") }), if (eq(state, "now")) .accent else .secondary);
            }
        } else {
            for (arr(get(pad, "done"))) |item| try add(lines, a, try fmt(a, "  ✓ {s}  {s}", .{ str(item), executor }), .secondary);
            if (text(pad, "now").len > 0) try add(lines, a, try fmt(a, "  ▶ {s}  {s} ← now", .{ text(pad, "now"), executor }), .accent);
            for (arr(get(pad, "todo"))) |item| try add(lines, a, try fmt(a, "    {s}  {s}", .{ str(item), executor }), .secondary);
        }
        try add(lines, a, try fmt(a, "  end: {s}", .{if (unfinished) "—" else outcome}), .secondary);
    }
    fn vitals(_: *UI, lines: *std.ArrayList(Line), a: A, host: Host, v: Value, width: usize) !void {
        const mem = get(v, "mem");
        const swap = get(v, "swap");
        const load = arr(get(v, "load"));
        const net = get(v, "net");
        const cpu = num(get(v, "cpu_total"));
        try add(lines, a, try fmt(a, "cpu  {s}  {d}%", .{ try spark(a, host, @min(24, width -| 14)), integer(cpu) }), .marks);
        try add(lines, a, try fmt(a, "mem  {s}  {d}%  {s}/{s}", .{ try bar(a, percent(mem), @min(12, width -| 27)), integer(percent(mem)), try amount(a, num(get(mem, "used"))), try amount(a, num(get(mem, "total"))) }), .marks);
        if (load.len >= 3) try add(lines, a, try fmt(a, "load {d:.1} {d:.1} {d:.1}   swap {s}/{s}", .{ num(load[0]), num(load[1]), num(load[2]), try amount(a, num(get(swap, "used"))), try amount(a, num(get(swap, "total"))) }), .secondary);
        const disks = arr(get(v, "disks"));
        for (disks[0..@min(disks.len, if (width >= 96) @as(usize, 4) else 1)]) |disk| {
            try add(lines, a, try fmt(a, "disk {s}  {d}%  {s}", .{ try bar(a, percent(disk), 8), integer(percent(disk)), text(disk, "mount") }), .marks);
        }
        try add(lines, a, try fmt(a, "net  ↓ {s}/s   ↑ {s}/s", .{ try amount(a, num(get(net, "rx_bps"))), try amount(a, num(get(net, "tx_bps"))) }), .secondary);
        if (width >= 90) {
            var heat: std.ArrayList(u8) = .empty;
            const shades = [_][]const u8{ "░", "▒", "▓", "█" };
            const cpus = arr(get(v, "cpu"));
            for (cpus[0..@min(cpus.len, width -| 9)]) |core| try heat.appendSlice(a, shades[@min(3, integer(@max(0, num(core)) * 3 / 100))]);
            try add(lines, a, try fmt(a, "cores  {s}", .{heat.items}), .marks);
            const top = arr(get(v, "top"));
            for (top[0..@min(3, top.len)]) |proc| try add(lines, a, try fmt(a, "{s}  cpu {d:.1}%  mem {s}  {s}", .{ text(proc, "agent"), num(get(proc, "cpu")), try amount(a, num(get(proc, "rss"))), text(proc, "cmd") }), .secondary);
        }
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
    slots: [7]usize = .{ 16, 7, 6, 1, 2, 8, 6 },
    color: bool = true,
    fn choose(self: *Theme) void {
        const desired = [_]usize{ 16, 7, 6, 1, 2, 8, 6 };
        for (desired, 0..) |slot, role| {
            self.slots[role] = slot;
            const bg = self.colors[17] orelse {
                self.slots[role] = if (role == @intFromEnum(Role.marks)) 6 else 16;
                continue;
            };
            const threshold: f64 = if (role == @intFromEnum(Role.lines)) 1.5 else if (role == @intFromEnum(Role.marks)) 3 else 4.5;
            if (self.colors[slot]) |fg| if (contrast(fg, bg) >= threshold) continue;
            self.slots[role] = 16;
            if (self.colors[16]) |fg| if (contrast(fg, bg) >= threshold) continue;
            var best: f64 = 0;
            for (self.colors[0..16], 0..) |maybe, i| if (maybe) |rgb| {
                const ratio = contrast(rgb, bg);
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
            const is_frame = std.mem.startsWith(u8, line.value, "╭") or std.mem.startsWith(u8, line.value, "├") or std.mem.startsWith(u8, line.value, "╰");
            const value = try clip(a, line.value, if (is_frame) width -| 1 else width -| 7);
            const content = if (is_frame) value else try fmt(a, "│  {s}{s}  │", .{ value, try repeat(a, " ", (width -| 7) -| cells(value)) });
            const styled = try fmt(a, "{s}{s}{s}{s}", .{ try theme.sgr(a, line.role), if (line.selected and theme.color) ESC ++ "[7m" else "", content, ESC ++ "[0m" });
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
    try std.fs.File.stdout().writeAll(ESC ++ "_Gi=31,s=1,v=1,a=q,t=d,f=24;AAAA" ++ ESC ++ "\\" ++ ESC ++ "[c" ++ ESC ++ "]10;?" ++ ESC ++ "\\" ++ ESC ++ "]11;?" ++ ESC ++ "\\");
    for (0..16) |slot| {
        var buf: [32]u8 = undefined;
        try std.fs.File.stdout().writeAll(try std.fmt.bufPrint(&buf, ESC ++ "]4;{d};?" ++ ESC ++ "\\", .{slot}));
    }
}

// Graphics use exactly the queried ANSI role colour; transparent pixels leave
// the live terminal background intact. No independent RGB palette is invented.
fn graphic(a: A, host: Host, rgb: RGB, row: usize, column: usize) ![]const u8 {
    const width: usize = 96;
    const height: usize = 16;
    var pixels: [width * height * 4]u8 = @splat(0);
    for (host.history, 0..) |value, x| {
        const top = height - @min(height, @as(usize, @intFromFloat(@round(value * @as(f64, @floatFromInt(height)) / 100))));
        for (top..height) |y| for (0..2) |dx| {
            const at = (y * width + x * 2 + dx) * 4;
            @memcpy(pixels[at..][0..3], &rgb);
            pixels[at + 3] = 255;
        };
    }
    const codec = std.base64.standard.Encoder;
    const encoded = try a.alloc(u8, codec.calcSize(pixels.len));
    _ = codec.encode(encoded, &pixels);
    // Payloads <=4096 bytes per chunk, suppress all acknowledgements; replace a
    // private image id in one synchronized transaction.
    var out: std.ArrayList(u8) = .empty;
    try out.appendSlice(a, try fmt(a, ESC ++ "[{d};{d}H" ++ ESC ++ "_Ga=T,f=32,s=96,v=16,i=197845,c=24,r=1,C=1,q=2,m=1;{s}" ++ ESC ++ "\\", .{ row, column, encoded[0..4096] }));
    try out.appendSlice(a, try fmt(a, ESC ++ "_Gm=0;{s}" ++ ESC ++ "\\", .{encoded[4096..]}));
    return out.toOwnedSlice(a);
}

fn jump(allocator: A, self: []const u8, config: []const u8, row: Value) !bool {
    const session = text(row, "session");
    const block = text(row, "block");
    if (!std.mem.startsWith(u8, session, "session:") or !std.mem.startsWith(u8, block, "block:")) return false;
    const result = try std.process.Child.run(.{ .allocator = allocator, .argv = &.{ self, "--config", config, "--host", text(row, "host"), "surfaces", "focus", "--session", session, "--pane", block, "--timeout-ms", "5000" }, .max_output_bytes = 65536 });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    return result.term == .Exited and result.term.Exited == 0;
}

fn scratch(allocator: A, self: []const u8, config: []const u8, row: Value) !?Parsed {
    const result = try std.process.Child.run(.{ .allocator = allocator, .argv = &.{ self, "--config", config, "--host", text(row, "host"), "scratch", "show", "--session", text(row, "session"), "--block", text(row, "block"), "--json" }, .max_output_bytes = 262144 });
    defer allocator.free(result.stdout);
    defer allocator.free(result.stderr);
    if (result.term != .Exited or result.term.Exited != 0) return null;
    return std.json.parseFromSlice(Value, allocator, result.stdout, .{ .allocate = .alloc_always }) catch null;
}

fn refreshDecisions(a: A, self: []const u8, opts: Options, model: *Model) !void {
    const result = try std.process.Child.run(.{ .allocator = a, .argv = &.{ self, "decide", "list", "--config", opts.config, "--hosts", opts.hosts, "--json" }, .max_output_bytes = 262144 });
    defer a.free(result.stdout);
    defer a.free(result.stderr);
    if (result.term != .Exited or result.term.Exited != 0) return;
    const parsed = try std.json.parseFromSlice(Value, a, result.stdout, .{ .allocate = .alloc_always });
    if (model.decisions) |*old| old.deinit();
    model.decisions = parsed;
}
fn answerDecision(a: A, self: []const u8, config: []const u8, d: Value, option: []const u8) !bool {
    const result = try std.process.Child.run(.{ .allocator = a, .argv = &.{ self, "decide", "answer", "--config", config, "--host", text(d, "host"), "--id", text(d, "id"), "--option", option }, .max_output_bytes = 262144 });
    defer a.free(result.stdout);
    defer a.free(result.stderr);
    return result.term == .Exited and result.term.Exited == 0;
}
fn restoreRatio(a: A) void {
    const result = std.process.Child.run(.{ .allocator = a, .argv = &.{ "python3", "-I", "-c", @embedFile("ratio.py") }, .max_output_bytes = 65536 }) catch return;
    a.free(result.stdout);
    a.free(result.stderr);
}
const Options = struct { config: []const u8, hosts: []const u8 = "hive,m5", replay: ?[]const u8 = null, once: bool = false, graphics: bool = true, benchmark: usize = 0 };
fn options(a: A, args: []const []const u8) !Options {
    const home = try std.process.getEnvVarOwned(a, "HOME");
    var result: Options = .{ .config = try std.fs.path.join(a, &.{ home, ".config/teerex/hosts.json" }) };
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        const s = args[i];
        if (eq(s, "--once")) result.once = true else if (eq(s, "--no-graphics")) result.graphics = false else if (eq(s, "--config") or eq(s, "--hosts") or eq(s, "--replay") or eq(s, "--benchmark")) {
            i += 1;
            if (i >= args.len) return error.BoardOptionNeedsValue;
            if (eq(s, "--config")) result.config = args[i] else if (eq(s, "--hosts")) result.hosts = args[i] else if (eq(s, "--replay")) result.replay = args[i] else result.benchmark = try std.fmt.parseInt(usize, args[i], 10);
        } else return error.UnknownBoardOption;
    }
    if (result.once and result.replay == null) return error.OnceRequiresReplay;
    return result;
}

pub fn run(allocator: A, args: []const []const u8) !u8 {
    if (args.len > 0 and eq(args[0], "--help")) {
        try std.fs.File.stdout().writeAll(usage);
        return 0;
    }
    const opts = try options(allocator, args);
    if (opts.benchmark > 0) return benchmark(allocator, opts.benchmark);
    var model: Model = .{ .allocator = allocator, .replay = opts.replay != null };
    defer model.deinit();
    var ui: UI = .{};
    defer ui.rows.deinit(allocator);
    defer if (ui.pad) |*pad| pad.deinit();
    var theme: Theme = .{ .color = !std.process.hasEnvVarConstant("NO_COLOR") };
    if (opts.once) {
        const bytes = try std.fs.cwd().readFileAlloc(allocator, opts.replay.?, 16 * 1024 * 1024);
        defer allocator.free(bytes);
        var events = std.mem.splitScalar(u8, bytes, '\n');
        while (events.next()) |line| if (line.len > 0) {
            _ = try model.ingest(line);
        };
        try ui.visible(&model);
        var arena = std.heap.ArenaAllocator.init(allocator);
        defer arena.deinit();
        const lines = try ui.layout(arena.allocator(), &model, 60, 30);
        for (lines) |line| {
            try std.fs.File.stdout().writeAll(try clip(arena.allocator(), line.value, 59));
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
    if (!model.replay) {
        refreshDecisions(allocator, self, opts, &model) catch {};
        restoreRatio(allocator);
    }
    var child: ?std.process.Child = null;
    var replay: ?std.fs.File = null;
    var fd: p.fd_t = undefined;
    if (opts.replay) |path| {
        replay = try std.fs.cwd().openFile(path, .{});
        fd = replay.?.handle;
    } else {
        child = std.process.Child.init(&.{ self, "board", "feed", "--config", opts.config, "--hosts", opts.hosts }, allocator);
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
    var size = dimensions();
    var dirty = true;
    var kitty = false;
    var last_query: i64 = 0;
    var last_click: i64 = 0;
    var last_click_index: usize = 256;
    try query();
    while (!stopping) {
        const now = std.time.milliTimestamp();
        if (resized) {
            resized = false;
            const previous_width = size.col;
            size = dimensions();
            if (size.col != previous_width and !model.replay) restoreRatio(allocator);
            dirty = true;
            try query();
        }
        if (dirty) {
            try ui.visible(&model);
            var arena = std.heap.ArenaAllocator.init(allocator);
            defer arena.deinit();
            const a = arena.allocator();
            const lines = try ui.layout(a, &model, size.col, size.row);
            // Frame + optional graphic share one DEC 2026 transaction.
            try std.fs.File.stdout().writeAll(ESC ++ "[?2026h");
            try std.fs.File.stdout().writeAll(try renderer.frame(a, lines, theme, size.col, false));
            const color = theme.colors[theme.slots[@intFromEnum(Role.marks)]];
            if (kitty and opts.graphics and theme.color and color != null and model.hosts[ui.host].count > 0 and size.col >= 55) {
                try std.fs.File.stdout().writeAll(try graphic(a, model.hosts[ui.host], color.?, if (model.hosts[ui.host].reachable == false) 3 else 2, 8));
            } else if (kitty) try std.fs.File.stdout().writeAll(ESC ++ "_Ga=d,d=I,i=197845,q=2" ++ ESC ++ "\\");
            try std.fs.File.stdout().writeAll(ESC ++ "[?2026l");
            dirty = false;
        }
        var fds = [_]p.pollfd{ .{ .fd = 0, .events = p.POLL.IN, .revents = 0 }, .{ .fd = if (model.ended) -1 else fd, .events = p.POLL.IN, .revents = 0 }, .{ .fd = signal_pipe[0], .events = p.POLL.IN, .revents = 0 } };
        // At rest, poll sleeps indefinitely; decisions never summon attention.
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
                if (input[0] == 27 and ui.decisions_open and input.len == 1) {
                    ui.decisions_open = false;
                    dirty = true;
                    consumed += 1;
                    continue;
                }
                if (input[0] == 27) {
                    if (input.len < 2) break;
                    if (input[1] == ']' or input[1] == '_' or input[1] == 'P') {
                        const bell = std.mem.indexOfScalar(u8, input, 7);
                        const st = std.mem.indexOf(u8, input, ESC ++ "\\");
                        const end = if (bell != null and (st == null or bell.? < st.?)) bell.? else st orelse break;
                        if (input[1] == ']') dirty = theme.parse(input[2..end]) or dirty;
                        if (input[1] == '_' and std.mem.indexOf(u8, input[2..end], "i=31;OK") != null) {
                            kitty = true;
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
                            ui.selected -|= 1;
                            dirty = true;
                        }
                        if (key == 'B') {
                            ui.selected += 1;
                            dirty = true;
                        }
                        if (key == 'I') {
                            try query();
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
                                    if (idx == last_click_index and now - last_click < 400 and idx < ui.rows.items.len) {
                                        ui.status = if (try jump(allocator, self, opts.config, ui.rows.items[idx])) "Jumped to pane" else "Jump unavailable · check host connection";
                                    }
                                    last_click = now;
                                    last_click_index = idx;
                                }
                            } else if (button == 64) {
                                ui.selected -|= 1;
                            } else if (button == 65) {
                                ui.selected += 1;
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
                if (ui.decisions_open and (key == '\r' or key == '\n' or (key >= '1' and key <= '9'))) {
                    const decisions = if (model.decisions) |v| arr(get(v.value, "decisions")) else &.{};
                    if (ui.decision_index < decisions.len) {
                        const d = decisions[ui.decision_index];
                        const option = if (key == '\r' or key == '\n') text(d, "default") else input[0..1];
                        var valid = false;
                        for (arr(get(d, "options"))) |o| {
                            if (eq(text(o, "key"), option)) valid = true;
                        }
                        if (valid) {
                            if (model.replay) {
                                ui.decision_index += 1;
                            } else {
                                ui.status = if (answerDecision(allocator, self, opts.config, d, option) catch false) "Answer delivered" else "Answer unavailable · decision remains open";
                                refreshDecisions(allocator, self, opts, &model) catch {};
                            }
                        }
                    }
                    dirty = true;
                    continue;
                }
                switch (key) {
                    'q', 3, 4 => {
                        stopping = true;
                        break;
                    },
                    'j' => {
                        ui.selected += 1;
                        dirty = true;
                    },
                    'k' => {
                        ui.selected -|= 1;
                        dirty = true;
                    },
                    'm' => {
                        ui.host = 1 - ui.host;
                        ui.selected = 0;
                        dirty = true;
                    },
                    'd' => {
                        ui.decisions_open = true;
                        if (!model.replay) refreshDecisions(allocator, self, opts, &model) catch {};
                        dirty = true;
                    },
                    ' ' => {
                        ui.inline_pad = !ui.inline_pad;
                        if (ui.inline_pad and ui.rows.items.len > 0) {
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
                    '\r', '\n' => if (ui.rows.items.len > 0) {
                        ui.status = if (try jump(allocator, self, opts.config, ui.rows.items[ui.selected])) "Jumped to pane" else "Jump unavailable · check host connection";
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
