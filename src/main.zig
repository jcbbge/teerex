const std = @import("std");
const version = @import("build_version").version;

const usage =
    \\teerex: an inspectable Rex operating layer
    \\Usage: teerex [--rex ABS] COMMAND ...
    \\       teerex --config ABS --host NAME COMMAND ...
    \\       teerex targets resolve --config ABS --host NAME
    \\       teerex targets exec --config ABS --host NAME [--tty] -- COMMAND ...
    \\       teerex --version
    \\
    \\Operating-layer commands:
    \\  surfaces open|inspect|move|focus|close|palette  Visible terminals and native palette plans
    \\  boards inbox|fleet|probe|state                Live boards, typed store and remap plans
    \\  seat register|inspect|clear              Exact-address operator seat
    \\  inbox append|inspect|clear                    Private retained messages
    \\  ask                                          Complete typed decisions or explicit resolution
    \\  agents launch|profiles|shell|ack|deliver|inspect|stop|present
    \\         exec|exited|channel                   Explicit compute callbacks / local scoped delivery
    \\  spawn --profile NAME --profiles ABS           Managed protocol-ACK-before-brief launch
    \\  recovery snapshot|inspect|restore|update      Private snapshots and reviewed restoration
    \\  snapshot|restore|update                       Recovery aliases; update is manual handoff
    \\  fleet install|rollback                       Explicit named-host installation plan/apply
    \\  targets resolve|exec                         Named-host lookup and explicit transport
    \\  run-visible                                  Visible noninteractive argv, output and actual exit
    \\Existing tools: observe, compare, watch, run, offstage, doctor, send, spawn,
    \\                jobs, adapters, maneuver-check, filter
    \\Use COMMAND --help for exact flags, effects, evidence and limits.
    \\Who: operators and agents. What: inspectable programs, not a Rex fork/plugin daemon.
    \\When: explicit invocation; every managed agent/board remains visible and controllable.
    \\Where: configured command host; paths belong there, never silently uploaded.
    \\Why: report actual activity/results and unknowns, not infer readiness or completion.
    \\How: explicit config/host or socket/full IDs; no retries, fallback or autostart.
    \\Python3.9+ is required for targets, boards, agents, recovery, fleet and palette install.
    \\Legacy direct-socket native tools do not require Python. SSH trust/key are explicit.
    \\Personal install/restart/close/config actions need their own authorization.
    \\Guides: docs/alpha5.md and items/{surfaces,boards,agents,recovery}/README.md.
    \\
;

pub fn main() void {
    var arena = std.heap.ArenaAllocator.init(std.heap.page_allocator);
    defer arena.deinit();
    run(arena.allocator()) catch |err| {
        std.debug.print("teerex: {s}\n", .{@errorName(err)});
        std.process.exit(1);
    };
}

fn python(allocator: std.mem.Allocator, args: []const []const u8) !void {
    var argv: std.ArrayList([]const u8) = .empty;
    try argv.appendSlice(allocator, &.{ "python3", "-c", @embedFile("targets.py") });
    try argv.appendSlice(allocator, args);
    return std.process.execv(allocator, argv.items);
}

fn send(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    var native: std.ArrayList([]const u8) = .empty;
    var route: std.ArrayList([]const u8) = .empty;
    var store: ?[]const u8 = null;
    var host: ?[]const u8 = null;
    var i: usize = 0;
    while (i < args.len) : (i += 1) {
        if (std.mem.eql(u8, args[i], "--store") or std.mem.eql(u8, args[i], "--host")) {
            if (i + 1 >= args.len) return error.SendRouteOptionNeedsValue;
            if (std.mem.eql(u8, args[i], "--store")) {
                if (store != null) return error.RepeatedSendStore;
                store = args[i + 1];
            } else {
                if (host != null) return error.RepeatedSendHost;
                host = args[i + 1];
            }
            i += 1;
        } else {
            try native.append(allocator, args[i]);
        }
    }
    if (store != null or host != null) {
        if (store == null or host == null) return error.SendStoreAndHostRequiredTogether;
        try route.appendSlice(allocator, &.{ "--store", store.?, "--host", host.? });
        try route.appendSlice(allocator, native.items);
        if (try @import("rex_boards").tryRoute(allocator, route.items)) |code| return code;
    }
    return @import("rex_send").run(allocator, native.items);
}

fn run(allocator: std.mem.Allocator) !void {
    const all = try std.process.argsAlloc(allocator);
    const args = all[1..];
    if (args.len == 1 and std.mem.eql(u8, args[0], "--version")) {
        try std.fs.File.stdout().writeAll("teerex " ++ version ++ "\n");
        return;
    }
    if (args.len == 0 or (args.len == 1 and std.mem.eql(u8, args[0], "--help"))) {
        try std.fs.File.stdout().writeAll(usage);
        return;
    }
    if (std.mem.eql(u8, args[0], "targets")) return python(allocator, args[1..]);
    if (std.mem.eql(u8, args[0], "--config") or std.mem.eql(u8, args[0], "--host")) {
        var config: ?[]const u8 = null;
        var host: ?[]const u8 = null;
        var i: usize = 0;
        while (i < args.len and std.mem.startsWith(u8, args[i], "--")) : (i += 2) {
            if (i + 1 >= args.len) return error.GlobalOptionNeedsValue;
            if (std.mem.eql(u8, args[i], "--config") and config == null) {
                config = args[i + 1];
            } else if (std.mem.eql(u8, args[i], "--host") and host == null) {
                host = args[i + 1];
            } else return error.UnknownOrRepeatedGlobalOption;
        }
        var forwarded: std.ArrayList([]const u8) = .empty;
        try forwarded.appendSlice(allocator, &.{ "exec", "--config", config orelse return error.ExplicitConfigRequired, "--host", host orelse return error.ExplicitHostRequired, "--" });
        try forwarded.appendSlice(allocator, args[i..]);
        return python(allocator, forwarded.items);
    }
    if (std.mem.eql(u8, args[0], "--rex")) {
        if (args.len < 3 or !std.fs.path.isAbsolute(args[1])) return error.ExplicitRexExecutableRequired;
        var env = try std.process.getEnvMap(allocator);
        try env.put("TEEREX_INTERNAL_REX", args[1]);
        try env.put("TEEREX_REX", args[1]);
        const self = try std.fs.selfExePathAlloc(allocator);
        var forwarded: std.ArrayList([]const u8) = .empty;
        try forwarded.append(allocator, self);
        try forwarded.appendSlice(allocator, args[2..]);
        std.debug.print("teerex: explicit Rex executable {s}; selected by --rex, not authenticated\n", .{args[1]});
        return std.process.execve(allocator, forwarded.items, &env);
    }
    const command = args[0];
    const rest = args[1..];
    if (std.mem.eql(u8, command, "fleet") and rest.len > 0 and (std.mem.eql(u8, rest[0], "install") or std.mem.eql(u8, rest[0], "rollback"))) {
        const sources = @import("fleet_sources");
        var forwarded: std.ArrayList([]const u8) = .empty;
        try forwarded.appendSlice(allocator, &.{ "python3", "-c", @embedFile("fleet_bridge.py"), sources.controller, sources.worker, sources.installer, sources.resolver });
        try forwarded.appendSlice(allocator, rest);
        return std.process.execv(allocator, forwarded.items);
    }
    if (std.mem.eql(u8, command, "recovery")) std.process.exit(try @import("rex_recovery").run(allocator, rest));
    if (std.mem.eql(u8, command, "snapshot") or std.mem.eql(u8, command, "restore") or std.mem.eql(u8, command, "update")) std.process.exit(try @import("rex_recovery").run(allocator, args));
    if (std.mem.eql(u8, command, "surfaces")) std.process.exit(try @import("rex_surfaces").run(allocator, rest));
    if (std.mem.eql(u8, command, "run")) std.process.exit(try @import("rex_run").run(allocator, rest));
    if (std.mem.eql(u8, command, "run-visible")) std.process.exit(try @import("rex_run").runVisible(allocator, rest));
    if (std.mem.eql(u8, command, "offstage")) std.process.exit(try @import("rex_offstage").run(allocator, rest));
    if (std.mem.eql(u8, command, "doctor")) std.process.exit(try @import("rex_doctor").run(allocator, rest));
    if (std.mem.eql(u8, command, "jobs")) std.process.exit(try @import("rex_jobs").run(allocator, rest));
    if (std.mem.eql(u8, command, "adapters")) std.process.exit(try @import("rex_adapters").run(allocator, rest));
    if (std.mem.eql(u8, command, "send")) std.process.exit(try send(allocator, rest));
    if (std.mem.eql(u8, command, "boards")) std.process.exit(try @import("rex_boards").run(allocator, rest));
    if (std.mem.eql(u8, command, "seat") or std.mem.eql(u8, command, "inbox") or std.mem.eql(u8, command, "ask") or std.mem.eql(u8, command, "fleet")) std.process.exit(try @import("rex_boards").run(allocator, args));
    if (std.mem.eql(u8, command, "agents")) std.process.exit(try @import("rex_agents").run(allocator, rest));
    if (std.mem.eql(u8, command, "spawn")) {
        var managed = false;
        for (rest) |arg| {
            if (std.mem.eql(u8, arg, "--")) break;
            if (std.mem.eql(u8, arg, "--profile")) managed = true;
        }
        if (managed) {
            var forwarded: std.ArrayList([]const u8) = .empty;
            try forwarded.append(allocator, "launch");
            for (rest) |arg| try forwarded.append(allocator, if (std.mem.eql(u8, arg, "--profiles")) "--config" else arg);
            std.process.exit(try @import("rex_agents").run(allocator, forwarded.items));
        }
        std.process.exit(try @import("rex_spawn").run(allocator, rest));
    }
    if (std.mem.eql(u8, command, "maneuver-check")) std.process.exit(try @import("rex_maneuvers").run(allocator, rest, @import("rex_observe")));
    if (std.mem.eql(u8, command, "filter")) std.process.exit(try @import("rex_filter").run(allocator, rest, @import("rex_observe")));
    std.process.exit(try @import("rex_observe").runObservations(allocator, args));
}
