//! Declared presentation only: raw evidence is never changed.
const std = @import("std");

pub const builtin_json =
    \\{"schema_version":1,"kind":"rex_presentation_view","id":"progress-v1","rules":[{"id":"braille-spinner","position":"anywhere","pattern":"{one_of:⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏}"},{"id":"star-spinner","position":"line_start","pattern":"{one_of:·✢✳✶✻✽∗} "},{"id":"elapsed-ms","position":"anywhere","pattern":"({digits}m {digits}s"},{"id":"elapsed-s","position":"anywhere","pattern":"({digits}s"},{"id":"tokens","position":"anywhere","pattern":"{number} tokens"}]}
;
const RuleSource = struct { id: []const u8, position: []const u8, pattern: []const u8 };
const Source = struct { schema_version: u32, kind: []const u8, id: []const u8, note: ?[]const u8 = null, protect_also: []const []const u8 = &.{}, rules: []const RuleSource };
const Token = union(enum) { literal: []const u8, digits, number, one_of: []const u8 };
const Rule = struct { id: []const u8, at_start: bool, tokens: []const Token };
pub const Rules = struct { id: []const u8, sha256: []const u8, extra: []const []const u8, rules: []const Rule };
pub const Span = struct { rule: []const u8, line: usize, byte_offset: usize, before: []const u8, after: []const u8 };
pub const Verdict = enum { unchanged, cosmetic_only, changed, unknown };
pub const Result = struct {
    kind: []const u8 = "rex_presentation_view_result",
    interpretation: []const u8 = "none",
    rules_id: []const u8,
    rules_sha256: []const u8,
    captured_text: Verdict,
    full_text: Verdict,
    non_text_evidence_changed: ?bool,
    spans: []const Span,
    spans_truncated: bool,
    protected_lines: usize,
    wake: bool,
};

pub fn refused(reason: []const u8) noreturn {
    std.debug.print("teerex: view refused: {s}\n", .{reason});
    std.process.exit(2);
}

pub const Options = struct {
    name: ?[]const u8 = null,
    file: ?[]const u8 = null,
    pub fn set(self: *Options, flag: []const u8, value: []const u8) bool {
        if (std.mem.eql(u8, flag, "--view")) {
            if (self.name != null or self.file != null) refused("view_flags_exclusive");
            self.name = value;
            return true;
        }
        if (std.mem.eql(u8, flag, "--view-rules")) {
            if (self.name != null or self.file != null) refused("view_flags_exclusive");
            self.file = value;
            return true;
        }
        return false;
    }
    pub fn enabled(self: Options) bool {
        return self.name != null or self.file != null;
    }
    pub fn load(self: Options, allocator: std.mem.Allocator) !?Rules {
        if (self.name) |name| {
            if (!std.mem.eql(u8, name, "progress-v1")) refused("builtin_unknown");
            return try compile(allocator, builtin_json);
        }
        if (self.file) |path| {
            const handle = std.posix.open(path, .{ .ACCMODE = .RDONLY, .NONBLOCK = true, .CLOEXEC = true }, 0) catch refused("rules_unreadable");
            const file: std.fs.File = .{ .handle = handle };
            defer file.close();
            const info = file.stat() catch refused("rules_unreadable");
            if (info.kind != .file) refused("rules_unreadable");
            if (info.size > 16384) refused("rules_too_large");
            const bytes = file.readToEndAlloc(allocator, 16384) catch |err| {
                if (err == error.FileTooBig) refused("rules_too_large");
                refused("rules_unreadable");
            };
            return try compile(allocator, bytes);
        }
        return null;
    }
};

fn validId(id: []const u8) bool {
    if (id.len == 0 or id.len > 64) return false;
    for (id) |c| if (!(c >= 'a' and c <= 'z') and !(c >= '0' and c <= '9') and c != '.' and c != '_' and c != '-') return false;
    return true;
}

fn pattern(allocator: std.mem.Allocator, input: []const u8) ![]const Token {
    if (input.len == 0 or input.len > 256 or !std.unicode.utf8ValidateSlice(input) or std.mem.indexOfAny(u8, input, "\r\n") != null) refused("rule_pattern_invalid");
    var tokens: std.ArrayList(Token) = .empty;
    var literal: std.ArrayList(u8) = .empty;
    var i: usize = 0;
    var non_space: usize = 0;
    var variables: usize = 0;
    var non_ascii_set = false;
    while (i < input.len) {
        if (i + 1 < input.len and ((input[i] == '{' and input[i + 1] == '{') or (input[i] == '}' and input[i + 1] == '}'))) {
            try literal.append(allocator, input[i]);
            non_space += 1;
            i += 2;
        } else if (input[i] == '{') {
            if (literal.items.len != 0) {
                try tokens.append(allocator, .{ .literal = try literal.toOwnedSlice(allocator) });
            } else if (tokens.items.len != 0) refused("rule_pattern_invalid");
            const end = std.mem.indexOfScalarPos(u8, input, i + 1, '}') orelse refused("rule_pattern_invalid");
            const value = input[i + 1 .. end];
            if (std.mem.eql(u8, value, "digits")) {
                try tokens.append(allocator, .digits);
            } else if (std.mem.eql(u8, value, "number")) {
                try tokens.append(allocator, .number);
            } else if (std.mem.startsWith(u8, value, "one_of:")) {
                const chars = value[7..];
                var iter = (try std.unicode.Utf8View.init(chars)).iterator();
                var count: usize = 0;
                var all_non_ascii = true;
                while (iter.nextCodepointSlice()) |c| {
                    count += 1;
                    if (c.len == 1) all_non_ascii = false;
                    if (std.mem.indexOf(u8, chars[0 .. iter.i - c.len], c) != null) refused("rule_pattern_invalid");
                }
                if (count == 0 or count > 32) refused("rule_pattern_invalid");
                non_ascii_set = all_non_ascii;
                try tokens.append(allocator, .{ .one_of = chars });
            } else refused("rule_pattern_invalid");
            variables += 1;
            i = end + 1;
        } else {
            if (input[i] == '}') refused("rule_pattern_invalid");
            const n = try std.unicode.utf8ByteSequenceLength(input[i]);
            try literal.appendSlice(allocator, input[i .. i + n]);
            if (n != 1 or !std.ascii.isWhitespace(input[i])) non_space += 1;
            i += n;
        }
    }
    if (literal.items.len != 0) try tokens.append(allocator, .{ .literal = try literal.toOwnedSlice(allocator) });
    if (tokens.items.len > 8) refused("rule_token_limit");
    if (non_space < 2 and !(variables == 1 and non_ascii_set and non_space == 0)) refused("rule_unanchored");
    return tokens.toOwnedSlice(allocator);
}

pub fn compile(allocator: std.mem.Allocator, bytes: []const u8) !Rules {
    // The typed parser rejects unknown and duplicate fields recursively.
    const parsed = std.json.parseFromSlice(Source, allocator, bytes, .{ .allocate = .alloc_always }) catch refused("rules_schema");
    const source = parsed.value;
    if (source.schema_version != 1 or !std.mem.eql(u8, source.kind, "rex_presentation_view") or !validId(source.id) or source.rules.len == 0 or source.rules.len > 32 or source.protect_also.len > 32) refused("rules_schema");
    if (source.note) |note| if (note.len > 512) refused("rules_schema");
    for (source.protect_also) |entry| if (entry.len == 0 or entry.len > 64) refused("rules_schema");
    var rules: std.ArrayList(Rule) = .empty;
    for (source.rules) |rule| {
        if (!validId(rule.id) or (!std.mem.eql(u8, rule.position, "anywhere") and !std.mem.eql(u8, rule.position, "line_start"))) refused("rules_schema");
        for (rules.items) |old| if (std.mem.eql(u8, old.id, rule.id)) refused("rule_id_duplicate");
        try rules.append(allocator, .{ .id = rule.id, .at_start = std.mem.eql(u8, rule.position, "line_start"), .tokens = try pattern(allocator, rule.pattern) });
    }
    // Typed fixed-order compact JSON defines canonical bytes, independent of input layout.
    // Omitted optional fields have their canonical defaults, including for built-ins.
    const canonical = try std.json.Stringify.valueAlloc(allocator, source, .{});
    var hash: [32]u8 = undefined;
    std.crypto.hash.sha2.Sha256.hash(canonical, &hash, .{});
    const hex = std.fmt.bytesToHex(hash, .lower);
    return .{ .id = source.id, .sha256 = try allocator.dupe(u8, &hex), .extra = source.protect_also, .rules = try rules.toOwnedSlice(allocator) };
}

fn protected(line: []const u8, extra: []const []const u8) bool {
    const words = [_][]const u8{ "error", "fail", "fatal", "panic", "exception", "traceback", "abort", "killed", "denied", "refused", "exit", "warning", "permission", "password", "passphrase", "token:", "allow", "approve", "confirm", "[y/n]", "(y/n)", "(yes/no)", "press enter" };
    for (words) |word| if (std.ascii.indexOfIgnoreCase(line, word) != null) return true;
    for (extra) |word| if (std.ascii.indexOfIgnoreCase(line, word) != null) return true;
    const trimmed = std.mem.trimEnd(u8, line, " \t\r\n\x0b\x0c");
    return trimmed.len != 0 and std.mem.indexOfScalar(u8, "?:>", trimmed[trimmed.len - 1]) != null;
}

fn digits(line: []const u8, start: usize, max: usize) usize {
    var end = start;
    while (end < line.len and end - start < max and std.ascii.isDigit(line[end])) : (end += 1) {}
    return end;
}

fn match(rule: Rule, line: []const u8, offset: usize) ?usize {
    if (rule.at_start and std.mem.trim(u8, line[0..offset], " \t").len != 0) return null;
    var pos = offset;
    for (rule.tokens) |token| switch (token) {
        .literal => |literal| {
            if (!std.mem.startsWith(u8, line[pos..], literal)) return null;
            pos += literal.len;
        },
        .digits, .number => {
            const end = digits(line, pos, 12);
            if (end == pos) return null;
            pos = end;
            if (token == .number) {
                if (pos < line.len and line[pos] == '.') {
                    const fraction = digits(line, pos + 1, 6);
                    if (fraction > pos + 1) pos = fraction;
                }
                if (pos < line.len and std.mem.indexOfScalar(u8, "kKmM", line[pos]) != null) pos += 1;
            }
        },
        .one_of => |chars| {
            if (pos == line.len) return null;
            const n = std.unicode.utf8ByteSequenceLength(line[pos]) catch return null;
            if (std.mem.indexOf(u8, chars, line[pos .. pos + n]) == null) return null;
            pos += n;
        },
    };
    return pos;
}

const Occurrence = struct { rule: usize, line: usize, offset: usize, text: []const u8 };
const Masked = struct { text: []const u8, matches: []const Occurrence, protected_lines: []const usize };
fn mask(allocator: std.mem.Allocator, rules: Rules, text: []const u8) !Masked {
    var output: std.ArrayList(u8) = .empty;
    var matches: std.ArrayList(Occurrence) = .empty;
    var protected_lines: std.ArrayList(usize) = .empty;
    var lines = std.mem.splitScalar(u8, text, '\n');
    var line_index: usize = 0;
    while (lines.next()) |line| : (line_index += 1) {
        if (line_index != 0) try output.append(allocator, '\n');
        const protect = protected(line, rules.extra);
        if (protect) try protected_lines.append(allocator, line_index);
        var pos: usize = 0;
        while (pos < line.len) {
            var found = false;
            if (!protect) for (rules.rules, 0..) |rule, index| {
                if (match(rule, line, pos)) |end| {
                    try matches.append(allocator, .{ .rule = index, .line = line_index, .offset = pos, .text = line[pos..end] });
                    const placeholder = try std.fmt.allocPrint(allocator, "\xef\xbf\xbc{d};", .{index});
                    try output.appendSlice(allocator, placeholder);
                    pos = end;
                    found = true;
                    break;
                }
            };
            if (!found) {
                const n = try std.unicode.utf8ByteSequenceLength(line[pos]);
                // Escape literal placeholders so raw text cannot collide with a rule marker.
                if (std.mem.startsWith(u8, line[pos..], "\xef\xbf\xbc")) try output.appendSlice(allocator, "\xef\xbf\xbc");
                try output.appendSlice(allocator, line[pos .. pos + n]);
                pos += n;
            }
        }
    }
    return .{ .text = try output.toOwnedSlice(allocator), .matches = try matches.toOwnedSlice(allocator), .protected_lines = try protected_lines.toOwnedSlice(allocator) };
}

fn verdict(raw: ?bool, same: bool, truncated: bool) Verdict {
    if (raw == null) return .unknown;
    if (!raw.?) return .unchanged;
    return if (same and !truncated) .cosmetic_only else .changed;
}

pub fn computeView(allocator: std.mem.Allocator, rules: Rules, before: anytype, after: @TypeOf(before), raw: anytype) !Result {
    const a = try mask(allocator, rules, before.capture.content);
    const b = try mask(allocator, rules, after.capture.content);
    const same = std.mem.eql(u8, a.text, b.text);
    var spans: std.ArrayList(Span) = .empty;
    var truncated = false;
    for (a.matches[0..@min(a.matches.len, b.matches.len)], b.matches[0..@min(a.matches.len, b.matches.len)]) |old, new| {
        if (old.line != new.line or old.rule != new.rule or std.mem.eql(u8, old.text, new.text)) continue;
        if (spans.items.len == 64) {
            truncated = true;
            break;
        }
        try spans.append(allocator, .{ .rule = rules.rules[old.rule].id, .line = old.line, .byte_offset = old.offset, .before = try allocator.dupe(u8, old.text), .after = try allocator.dupe(u8, new.text) });
    }
    var non_text: ?bool = if (before.process == null or after.process == null or before.reported_directory == null or after.reported_directory == null or before.program_status == null or after.program_status == null) null else false;
    inline for (.{ raw.process.foreground, raw.process.child, raw.process.last_exit, raw.reported_directory, raw.program_status }) |delta| {
        // Both-absent optional values are no new evidence. Missing whole methods
        // remain unknown; availability transitions always wake.
        if (delta.availability_changed or delta.changed == true) non_text = true;
    }
    const captured = verdict(raw.capture.captured_text_changed, same, truncated);
    const full = verdict(raw.capture.full_text_changed, same, truncated);
    var count = a.protected_lines.len;
    for (b.protected_lines) |line| if (std.mem.indexOfScalar(usize, a.protected_lines, line) == null) {
        count += 1;
    };
    return .{ .rules_id = rules.id, .rules_sha256 = rules.sha256, .captured_text = captured, .full_text = full, .non_text_evidence_changed = non_text, .spans = try spans.toOwnedSlice(allocator), .spans_truncated = truncated, .protected_lines = count, .wake = non_text != false or captured == .changed or captured == .unknown or full == .changed };
}
