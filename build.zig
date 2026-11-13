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
    build_version.addOption([]const u8, "version", "0.1.0-alpha.5");
    exe.root_module.addOptions("build_version", build_version);
    const cartridge_sources = b.addOptions();
    const manager = b.build_root.handle.readFileAlloc(b.allocator, "tools/cartridges/cartridges.py", 1024 * 1024) catch @panic("cartridge manager source unavailable");
    cartridge_sources.addOption([]const u8, "manager", manager);
    exe.root_module.addOptions("cartridge_sources", cartridge_sources);
    const fleet_sources = b.addOptions();
    for ([_][]const u8{ "controller", "worker", "installer", "resolver" }, [_][]const u8{ "tools/fleet-install/fleet_install.py", "tools/fleet-install/worker.py", "tools/install/teerex-install", "src/targets.py" }) |name, path| {
        const source = b.build_root.handle.readFileAlloc(b.allocator, path, 1024 * 1024) catch @panic("fleet support source unavailable");
        fleet_sources.addOption([]const u8, name, source);
    }
    exe.root_module.addOptions("fleet_sources", fleet_sources);
    const observation = b.createModule(.{
        .root_source_file = b.path("items/observe/main.zig"),
        .target = target,
        .optimize = optimize,
    });
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
    exe.root_module.addImport("rex_send", send);
    const spawn = b.createModule(.{
        .root_source_file = b.path("items/spawn/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    spawn.addImport("supervised_child", child);
    exe.root_module.addImport("rex_spawn", spawn);
    const offstage = b.createModule(.{
        .root_source_file = b.path("items/offstage/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    offstage.addImport("supervised_child", child);
    exe.root_module.addImport("rex_offstage", offstage);
    const doctor = b.createModule(.{
        .root_source_file = b.path("items/doctor/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    doctor.addImport("supervised_child", child);
    exe.root_module.addImport("rex_doctor", doctor);
    exe.root_module.addImport("rex_maneuvers", b.createModule(.{
        .root_source_file = b.path("items/maneuvers/main.zig"),
        .target = target,
        .optimize = optimize,
    }));
    exe.root_module.addImport("rex_filter", b.createModule(.{
        .root_source_file = b.path("items/filter/main.zig"),
        .target = target,
        .optimize = optimize,
    }));
    const jobs = b.createModule(.{
        .root_source_file = b.path("items/jobs/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    jobs.addImport("supervised_child", child);
    exe.root_module.addImport("rex_jobs", jobs);
    const adapters = b.createModule(.{
        .root_source_file = b.path("items/adapters/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    adapters.addImport("supervised_child", child);
    exe.root_module.addImport("rex_adapters", adapters);
    const surfaces = b.createModule(.{
        .root_source_file = b.path("items/surfaces/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    surfaces.addImport("supervised_child", child);
    exe.root_module.addImport("rex_surfaces", surfaces);
    const boards = b.createModule(.{
        .root_source_file = b.path("items/boards/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    exe.root_module.addImport("rex_boards", boards);
    surfaces.addImport("rex_boards", boards);
    rex_run.addImport("rex_boards", boards);
    const recovery = b.createModule(.{
        .root_source_file = b.path("items/recovery/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    recovery.addImport("supervised_child", child);
    exe.root_module.addImport("rex_recovery", recovery);
    recovery.addImport("rex_boards", boards);
    const agents = b.createModule(.{
        .root_source_file = b.path("items/agents/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    exe.root_module.addImport("rex_agents", agents);
    const channel = b.createModule(.{ .root_source_file = b.path("src/scoped_channel.zig"), .target = target, .optimize = optimize });
    agents.addImport("scoped_channel", channel);
    rex_run.addImport("scoped_channel", channel);
    agents.addImport("rex_boards", boards);
    exe.root_module.addImport("rex_replay", b.createModule(.{
        .root_source_file = b.path("items/replay/main.zig"),
        .target = target,
        .optimize = optimize,
    }));
    exe.root_module.addImport("rex_mcp", b.createModule(.{
        .root_source_file = b.path("items/mcp/main.zig"),
        .target = target,
        .optimize = optimize,
    }));
    b.installArtifact(exe);

    const run = b.addRunArtifact(exe);
    if (b.args) |args| run.addArgs(args);
    b.step("run", "Run teerex").dependOn(&run.step);
}
