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
    const child = b.createModule(.{
        .root_source_file = b.path("src/child.zig"),
        .target = target,
        .optimize = optimize,
    });
    exe.root_module.addImport("supervised_child", child);
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
    exe.root_module.addImport("rex_send", send);
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
