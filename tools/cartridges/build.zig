const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const selected = b.option([]const u8, "cartridge", "Build just this cartridge ID");
    const names = [_][]const u8{ "observe", "run", "spawn", "send", "offstage", "doctor", "maneuvers", "filter", "jobs", "adapters" };
    if (selected) |id| {
        var found = false;
        for (names) |name| {
            if (std.mem.eql(u8, id, name)) found = true;
        }
        if (!found) @panic("unknown cartridge ID");
    }
    for (names) |name| {
        if (selected) |id| if (!std.mem.eql(u8, id, name)) continue;
        const child = b.createModule(.{
            .root_source_file = b.path("../../src/child.zig"),
            .target = target,
            .optimize = optimize,
        });
        const observation = b.createModule(.{
            .root_source_file = b.path("../../items/observe/main.zig"),
            .target = target,
            .optimize = optimize,
        });
        observation.addImport("supervised_child", child);
        const state_sources = b.addOptions();
        state_sources.addOption([]const u8, "draft", b.build_root.handle.readFileAlloc(b.allocator, "../../items/send/draft.lua", 32768) catch @panic("send draft source unavailable"));
        observation.addOptions("state_sources", state_sources);
        const leaf = if (std.mem.eql(u8, name, "observe")) observation else b.createModule(.{
            .root_source_file = b.path(b.fmt("../../items/{s}/main.zig", .{name})),
            .target = target,
            .optimize = optimize,
        });
        leaf.addImport("supervised_child", child);
        const options = b.addOptions();
        options.addOption(bool, "uses_observations", std.mem.eql(u8, name, "filter") or std.mem.eql(u8, name, "maneuvers"));
        options.addOption(bool, "observation_entry", std.mem.eql(u8, name, "observe"));
        const exe = b.addExecutable(.{
            .name = b.fmt("teerex-{s}", .{name}),
            .root_module = b.createModule(.{
                .root_source_file = b.path("entry.zig"),
                .target = target,
                .optimize = optimize,
            }),
        });
        exe.root_module.addOptions("options", options);
        exe.root_module.addImport("cartridge", leaf);
        exe.root_module.addImport("observations", observation);
        b.installArtifact(exe);
    }
}
