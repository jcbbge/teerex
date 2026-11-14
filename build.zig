const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const exe = b.addExecutable(.{
        .name = "teerex",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
    const build_version = b.addOptions();
    build_version.addOption([]const u8, "version", b.option([]const u8, "version", "Release/build identity without the leading v") orelse localVersion(b));
    exe.root_module.addOptions("build_version", build_version);
    const fleet_sources = b.addOptions();
    for ([_][]const u8{ "controller", "worker", "installer", "resolver" }, [_][]const u8{ "tools/fleet-install/fleet_install.py", "tools/fleet-install/worker.py", "tools/install/teerex-install", "src/targets.py" }) |name, path| {
        const source = b.build_root.handle.readFileAlloc(b.allocator, path, 1024 * 1024) catch @panic("fleet support source unavailable");
        fleet_sources.addOption([]const u8, name, if (std.mem.eql(u8, name, "resolver"))
            std.mem.concat(b.allocator, u8, &.{ @embedFile("src/caller_identity.py"), "\n", source }) catch @panic("resolver identity unavailable")
        else
            source);
    }
    const fleet_module = fleet_sources.createModule();
    exe.root_module.addImport("fleet_sources", fleet_module);
    const observation = b.createModule(.{
        .root_source_file = b.path("items/observe/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    const state_sources = b.addOptions();
    state_sources.addOption([]const u8, "draft", b.build_root.handle.readFileAlloc(b.allocator, "items/send/draft.lua", 32768) catch @panic("send draft source unavailable"));
    observation.addOptions("state_sources", state_sources);
    exe.root_module.addImport("rex_observe", observation);
    const child = b.createModule(.{
        .root_source_file = b.path("src/child.zig"),
        .target = target,
        .optimize = optimize,
    });
    const rex_run = b.createModule(.{
        .root_source_file = b.path("items/run/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    observation.addImport("supervised_child", child);
    const pane_guard = b.createModule(.{ .root_source_file = b.path("src/pane_guard.zig"), .target = target, .optimize = optimize });
    child.addImport("pane_guard", pane_guard);
    exe.root_module.addImport("pane_guard", pane_guard);
    rex_run.addImport("supervised_child", child);
    exe.root_module.addImport("supervised_child", child);
    exe.root_module.addImport("rex_run", rex_run);
    const send = b.createModule(.{
        .root_source_file = b.path("items/send/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    send.addImport("supervised_child", child);
    const clutch = b.createModule(.{ .root_source_file = b.path("items/clutch/main.zig"), .target = target, .optimize = optimize });
    clutch.addImport("rex_send", send);
    exe.root_module.addImport("rex_clutch", clutch);
    clutch.addImport("supervised_child", child);
    clutch.addImport("pane_guard", pane_guard);
    exe.root_module.addImport("rex_send", send);
    const doctor = b.createModule(.{
        .root_source_file = b.path("items/doctor/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    doctor.addImport("supervised_child", child);
    exe.root_module.addImport("rex_doctor", doctor);
    const jobs = b.createModule(.{
        .root_source_file = b.path("items/jobs/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    jobs.addImport("supervised_child", child);
    exe.root_module.addImport("rex_jobs", jobs);
    const surfaces = b.createModule(.{
        .root_source_file = b.path("items/surfaces/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    surfaces.addImport("supervised_child", child);
    exe.root_module.addImport("rex_surfaces", surfaces);
    const recovery = b.createModule(.{
        .root_source_file = b.path("items/recovery/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    recovery.addImport("supervised_child", child);
    recovery.addImport("pane_guard", pane_guard);
    exe.root_module.addImport("rex_recovery", recovery);
    const records = b.createModule(.{ .root_source_file = b.path("items/records/main.zig"), .target = target, .optimize = optimize });
    records.addImport("supervised_child", child);
    exe.root_module.addImport("rex_records", records);
    const board = b.createModule(.{ .root_source_file = b.path("items/board/main.zig"), .target = target, .optimize = optimize });
    board.addImport("fleet_sources", fleet_module);
    exe.root_module.addImport("rex_board", board);
    exe.root_module.addImport("rex_boardfeed", b.createModule(.{ .root_source_file = b.path("items/boardfeed/main.zig"), .target = target, .optimize = optimize }));
    b.installArtifact(exe);

    const run = b.addRunArtifact(exe);
    if (b.args) |args| run.addArgs(args);
    b.step("run", "Run teerex").dependOn(&run.step);
}

fn localVersion(b: *std.Build) []const u8 {
    const base = "0.1.0-alpha.6";
    const result = std.process.Child.run(.{
        .allocator = b.allocator,
        .argv = &.{ "git", "rev-parse", "--short=12", "HEAD" },
        .cwd = b.build_root.path orelse ".",
    }) catch return base;
    if (result.term != .Exited or result.term.Exited != 0) return base;
    const revision = std.mem.trim(u8, result.stdout, "\r\n");
    if (revision.len == 0) return base;
    return b.fmt("{s}.main.{s}", .{ base, revision });
}
