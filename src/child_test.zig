const std = @import("std");
const supervised = @import("child.zig");

const Receiver = struct {
    bytes: std.ArrayList(u8) = .empty,
    allocator: std.mem.Allocator,

    pub fn receive(self: *Receiver, bytes: []const u8) !void {
        try self.bytes.appendSlice(self.allocator, bytes);
    }
};

test "collect drains both streams past pipe capacity and preserves final bytes and nonzero exit" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const allocator = arena.allocator();
    var env = try std.process.getEnvMap(allocator);
    const signals = supervised.Signals.init();
    defer signals.deinit();
    var receiver: Receiver = .{ .allocator = allocator };
    const result = try supervised.collect(allocator, &.{ "/bin/sh", "-c", "head -c 131073 /dev/zero >&2; head -c 65539 /dev/zero; printf '\\377end'; exit 7" }, &env, 5000, &receiver);
    try std.testing.expectEqual(std.process.Child.Term{ .Exited = 7 }, result.term);
    try std.testing.expect(!result.stopped);
    try std.testing.expectEqual(@as(usize, 65543), receiver.bytes.items.len);
    try std.testing.expectEqualSlices(u8, "\xffend", receiver.bytes.items[65539..]);
    for (receiver.bytes.items[0..65539]) |byte| try std.testing.expectEqual(@as(u8, 0), byte);
    try std.testing.expectEqual(@as(?u64, 131073), result.stderr_seen);
    try std.testing.expectEqual(@as(usize, 4096), result.stderr.len);
    for (result.stderr) |byte| try std.testing.expectEqual(@as(u8, 0), byte);
    try std.testing.expect(result.group_kill != null);
}

test "closed output pipes do not masquerade as process exit or bypass deadline" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const allocator = arena.allocator();
    var env = try std.process.getEnvMap(allocator);
    const signals = supervised.Signals.init();
    defer signals.deinit();
    var receiver: Receiver = .{ .allocator = allocator };
    const result = try supervised.collect(allocator, &.{ "/bin/sh", "-c", "exec 1>&- 2>&-; trap '' TERM; exec sleep 30" }, &env, 150, &receiver);
    try std.testing.expect(result.deadline_exceeded);
    try std.testing.expect(result.stopped);
    try std.testing.expectEqual(@as(u8, 0), result.stop_signal);
    try std.testing.expect(result.elapsed_ms >= 150 and result.elapsed_ms < 2000);
    try std.testing.expectEqual(std.process.Child.Term{ .Signal = std.posix.SIG.KILL }, result.term);
    try std.testing.expectEqual(@as(?u64, 0), result.stderr_seen);
}

test "leader exit cleans same-group descendants retaining pipes without waiting for deadline" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const allocator = arena.allocator();
    var env = try std.process.getEnvMap(allocator);
    const signals = supervised.Signals.init();
    defer signals.deinit();
    var receiver: Receiver = .{ .allocator = allocator };
    const result = try supervised.collect(allocator, &.{ "/bin/sh", "-c", "trap '' TERM; sleep 30 & printf retained; exit 7" }, &env, 5000, &receiver);
    try std.testing.expectEqual(std.process.Child.Term{ .Exited = 7 }, result.term);
    try std.testing.expect(!result.stopped);
    try std.testing.expect(result.elapsed_ms < 2000);
    try std.testing.expectEqualSlices(u8, "retained", receiver.bytes.items);
    try std.testing.expectEqual(@as(?u64, 0), result.stderr_seen);
    try std.testing.expect(result.group_kill != null);
}

test "signals preserve cancellation outcome and can be consumed for bounded cleanup" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const allocator = arena.allocator();
    var env = try std.process.getEnvMap(allocator);
    const signals = supervised.Signals.init();
    defer signals.deinit();
    var receiver: Receiver = .{ .allocator = allocator };
    const result = try supervised.collect(allocator, &.{ "/bin/sh", "-c", "trap '' TERM; kill -INT $PPID; exec sleep 30" }, &env, 5000, &receiver);
    try std.testing.expect(result.stopped);
    try std.testing.expect(!result.deadline_exceeded);
    try std.testing.expectEqual(@as(u8, std.posix.SIG.INT), result.stop_signal);
    try std.testing.expect(result.elapsed_ms < 2000);
    try std.testing.expectEqual(std.process.Child.Term{ .Signal = std.posix.SIG.KILL }, result.term);
    try std.testing.expectEqual(@as(u8, std.posix.SIG.INT), supervised.takeRequestedSignal());
    try std.testing.expectEqual(@as(u8, 0), supervised.requestedSignal());
}

test "socket receipt helper leaves explicit serialization byte-identical" {
    var arena = std.heap.ArenaAllocator.init(std.testing.allocator);
    defer arena.deinit();
    const a = arena.allocator();
    const value = .{ .text = "quote \" α", .nothing = @as(?u8, null), .nested = .{ .number = 3 } };
    supervised.socket_source = null;
    const ordinary = try std.json.Stringify.valueAlloc(a, value, .{ .whitespace = .indent_2 });
    const explicit = try supervised.receiptJson(a, value, .{ .whitespace = .indent_2 });
    try std.testing.expectEqualStrings(ordinary, explicit);
    supervised.socket_source = "REX_SERVER";
    defer supervised.socket_source = null;
    const defaulted = try supervised.receiptJson(a, value, .{});
    const parsed = try std.json.parseFromSlice(std.json.Value, a, defaulted, .{});
    try std.testing.expectEqualStrings("REX_SERVER", parsed.value.object.get("socket_source").?.string);
    try std.testing.expect(parsed.value.object.get("nothing").? == .null);
}
