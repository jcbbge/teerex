const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const exe = b.addExecutable(.{
        .name = "teerex",
        .root_module = b.createModule(.{
            .root_source_file = b.path("items/observe/main.zig"),
            .target = target,
            .optimize = optimize,
        }),
    });
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
    rex_run.addImport("supervised_child", child);
    exe.root_module.addImport("supervised_child", child);
    exe.root_module.addImport("rex_run", rex_run);
    const send = b.createModule(.{
        .root_source_file = b.path("items/send/main.zig"),
        .target = target,
        .optimize = optimize,
    });
    send.addImport("supervised_child", child);
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
    b.installArtifact(exe);

    const run = b.addRunArtifact(exe);
    if (b.args) |args| run.addArgs(args);
    b.step("run", "Run teerex").dependOn(&run.step);
}
