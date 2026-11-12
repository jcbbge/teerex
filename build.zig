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
    b.installArtifact(exe);

    const run = b.addRunArtifact(exe);
    if (b.args) |args| run.addArgs(args);
    b.step("run", "Run teerex").dependOn(&run.step);
}
