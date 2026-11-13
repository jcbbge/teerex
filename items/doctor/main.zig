const std = @import("std");
const builtin = @import("builtin");
const supervised = @import("supervised_child");

const usage =
    \\Usage: teerex doctor --socket /absolute/path [--timeout-ms N] [--baseline FILE]
    \\Read-only, narrow API-10..13 diagnosis for observe/watch/run. Requires macOS/Linux and Rex on PATH (or global --rex ABS / TEEREX_REX).
    \\Uses only the explicit existing socket; never autostarts, upgrades, configures, reads terminal text or executes argv.
    \\Reports rex_executable, client/server mismatch and platform applicability (Linux run: not_applicable).
    \\Checks CLI/server versions, five selected method descriptions and Lua binding shapes, not program behavior.
    \\Discovery is not permission. Advertised requirements do not prove execution, cleanup or input safety.
    \\Optional baseline is a prior doctor JSON receipt (at most 128 KiB); changed identity requires adapter revalidation.
    \\Total monotonic budget defaults to 5000 ms (100..60000), plus bounded owned-child cleanup.
    \\JSON stdout; exit 0 advertised requirements met (NOT behavior certified), 1 incompatible/unknown/error,
    \\2 usage, 124 deadline, 130 SIGINT, 143 SIGTERM. No persistent writes or automatic remediation.
    \\
;

const methods = [_][]const u8{
    "server.version",
    "com.superlogical.terminal.format",
    "com.superlogical.terminal.process",
    "com.superlogical.terminal.pwd",
    "com.superlogical.terminal.program_status",
};

const Identity = struct {
    rex_version: []const u8,
    platform: []const u8,
    api_revision: u32 = 0,
    api_min_revision: u32 = 0,
    commit: ?[]const u8 = null,
    built_at: ?[]const u8 = null,
    dirty: bool,
};

const Check = struct {
    method: []const u8,
    advertised: ?bool = null,
    schema_status: []const u8 = "not_checked",
    descriptor_sha256: ?[]const u8 = null,
    behavior_tested: bool = false,
    error_name: ?[]const u8 = null,
};

const BindingShapes = struct {
    call: []const u8,
    encode: []const u8,
    sleep: []const u8,
    exec_start: []const u8,
};

const Output = struct {
    allocator: std.mem.Allocator,
    bytes: std.ArrayList(u8) = .empty,

    pub fn receive(self: *Output, bytes: []const u8) !void {
        if (bytes.len > 128 * 1024 - self.bytes.items.len) return error.DoctorResponseExceedsLimit;
        try self.bytes.appendSlice(self.allocator, bytes);
    }
};

const Diagnosis = struct {
    allocator: std.mem.Allocator,
    endpoint: []const u8,
    env: std.process.EnvMap,
    timer: std.time.Timer,
    timeout_ms: u64,
    executable: ?[]const u8 = null,
    cli: ?Identity = null,
    server: ?Identity = null,
    checks: [methods.len]Check = undefined,
    lua_bindings: []const u8 = "not_checked",
    binding_shapes: ?BindingShapes = null,
    diagnostics: std.ArrayList(struct { stage: []const u8, error_name: []const u8 }) = .empty,

    fn query(self: *Diagnosis, suffix: []const []const u8) ![]const u8 {
        if (supervised.requestedSignal() != 0) return error.DoctorCancelled;
        const elapsed = self.timer.read() / std.time.ns_per_ms;
        if (elapsed >= self.timeout_ms) return error.DoctorDeadlineExceeded;
        const base = [_][]const u8{ self.executable orelse return error.FileNotFound, "--autostart=false", "--server", self.endpoint, "--timeout", "2s", "--color", "never" };
        const argv = try std.mem.concat(self.allocator, []const u8, &.{ &base, suffix });
        var output: Output = .{ .allocator = self.allocator };
        const result = try supervised.collect(self.allocator, argv, &self.env, self.timeout_ms - elapsed, &output);
        if (result.stop_signal != 0) return error.DoctorCancelled;
        if (result.deadline_exceeded) return error.DoctorDeadlineExceeded;
        if (result.term != .Exited or result.term.Exited != 0) return error.RexQueryFailed;
        return output.bytes.items;
    }

    fn failure(self: *Diagnosis, stage: []const u8, err: anyerror) !void {
        try self.diagnostics.append(self.allocator, .{ .stage = stage, .error_name = @errorName(err) });
    }

    fn identity(self: *Diagnosis, args: []const []const u8) !Identity {
        const bytes = try self.query(args);
        const parsed = try std.json.parseFromSlice(Identity, self.allocator, bytes, .{ .ignore_unknown_fields = true });
        if (parsed.value.rex_version.len == 0 or parsed.value.platform.len == 0) return error.InvalidVersionIdentity;
        return parsed.value;
    }

    fn describe(self: *Diagnosis, method: []const u8) !Check {
        const bytes = try self.query(&.{ "api", "describe", method, "--json" });
        const value = (try std.json.parseFromSlice(std.json.Value, self.allocator, bytes, .{})).value;
        const invoke = at(value, "invoke.method") orelse return error.InvalidMethodDescription;
        if (invoke != .string or !std.mem.eql(u8, invoke.string, method)) return error.InvalidMethodDescription;
        return .{
            .method = method,
            .advertised = true,
            .schema_status = if (matches(method, value)) "selected_shape_matches" else "selected_shape_mismatch",
            .descriptor_sha256 = try fingerprint(self.allocator, bytes),
            .behavior_tested = std.mem.eql(u8, method, "server.version") and self.server != null,
        };
    }

    fn bindings(self: *Diagnosis) !void {
        // This runs fixed introspection, NOT rex.exec.start, a terminal read or supplied code.
        const script =
            \\io.write(rex.json.encode({call=type(rex.call),encode=type(rex.json.encode),sleep=type(rex.sleep),exec_start=type(rex.exec) == "table" and type(rex.exec.start) or "nil"}))
        ;
        const bytes = try self.query(&.{ "do", "-e", script });
        const value = (try std.json.parseFromSlice(BindingShapes, self.allocator, bytes, .{})).value;
        self.binding_shapes = value;
        self.lua_bindings = if (std.mem.eql(u8, value.call, "function") and std.mem.eql(u8, value.encode, "function") and
            std.mem.eql(u8, value.sleep, "function") and std.mem.eql(u8, value.exec_start, "function")) "shape_matches_not_executed" else "shape_mismatch";
    }
};

// Fixed paths for fields consumed by shipped collectors, not a schema evaluator.
fn at(value: std.json.Value, path: []const u8) ?std.json.Value {
    var node = value;
    var parts = std.mem.splitScalar(u8, path, '.');
    while (parts.next()) |part| {
        if (node != .object) return null;
        node = node.object.get(part) orelse return null;
    }
    return node;
}

fn hasType(value: std.json.Value, path: []const u8, expected: []const u8) bool {
    const node = at(value, path) orelse return false;
    if (node == .string) return std.mem.eql(u8, node.string, expected);
    if (node == .array) for (node.array.items) |item| {
        if (item == .string and std.mem.eql(u8, item.string, expected)) return true;
    };
    return false;
}

fn acceptsCollectorArgs(value: std.json.Value, path: []const u8, format: bool) bool {
    const required = at(value, path) orelse return true;
    if (required != .array) return false;
    for (required.array.items) |field| {
        if (field != .string or !format or
            (!std.mem.eql(u8, field.string, "format") and !std.mem.eql(u8, field.string, "max_bytes"))) return false;
    }
    return true;
}

fn matches(method: []const u8, value: std.json.Value) bool {
    if (!hasType(value, "output_schema.type", "object")) return false;
    if (std.mem.eql(u8, method, methods[0])) return hasType(value, "input_schema.type", "object") and
        acceptsCollectorArgs(value, "input_schema.required", false) and
        hasType(value, "output_schema.properties.rex_version.type", "string") and
        hasType(value, "output_schema.properties.platform.type", "string") and
        hasType(value, "output_schema.properties.api_revision.type", "integer");
    if (!hasType(value, "args_schema.type", "object") or
        !acceptsCollectorArgs(value, "args_schema.required", std.mem.eql(u8, method, methods[1]))) return false;
    if (std.mem.eql(u8, method, methods[1])) return hasType(value, "args_schema.properties.format.type", "string") and
        hasType(value, "args_schema.properties.max_bytes.type", "integer") and
        hasType(value, "output_schema.properties.content.type", "string") and
        hasType(value, "output_schema.properties.id.type", "integer") and
        hasType(value, "output_schema.properties.eof.type", "boolean");
    if (std.mem.eql(u8, method, methods[2])) {
        inline for (.{ "child", "foreground" }) |field| {
            if (!hasType(value, "output_schema.properties." ++ field ++ ".type", "null") or
                !hasType(value, "output_schema.properties." ++ field ++ ".type", "object") or
                !hasType(value, "output_schema.properties." ++ field ++ ".properties.pid.type", "integer") or
                !hasType(value, "output_schema.properties." ++ field ++ ".properties.name.type", "string") or
                !hasType(value, "output_schema.properties." ++ field ++ ".properties.cwd.type", "string")) return false;
        }
        return hasType(value, "output_schema.properties.last_exit.type", "null") and
            hasType(value, "output_schema.properties.last_exit.type", "object") and
            hasType(value, "output_schema.properties.last_exit.properties.exit_code.type", "integer");
    }
    if (std.mem.eql(u8, method, methods[3])) return hasType(value, "output_schema.properties.pwd.type", "string") and
        hasType(value, "output_schema.properties.owner.type", "null") and
        hasType(value, "output_schema.properties.owner.type", "object") and
        hasType(value, "output_schema.properties.owner.properties.pid.type", "integer") and
        hasType(value, "output_schema.properties.owner.properties.name.type", "string");
    if (!hasType(value, "output_schema.properties.records.type", "array") or
        !hasType(value, "output_schema.properties.records.items.type", "object")) return false;
    inline for (.{ "state", "updated_at", "id", "app", "effective_app", "kind", "title", "msg" }) |field| {
        if (!hasType(value, "output_schema.properties.records.items.properties." ++ field ++ ".type", "string")) return false;
    }
    return hasType(value, "output_schema.properties.records.items.properties.progress.type", "null") and
        hasType(value, "output_schema.properties.records.items.properties.progress.type", "integer") and
        hasType(value, "output_schema.properties.records.items.properties.owner.type", "null") and
        hasType(value, "output_schema.properties.records.items.properties.owner.type", "object") and
        hasType(value, "output_schema.properties.records.items.properties.owner.properties.pid.type", "integer") and
        hasType(value, "output_schema.properties.records.items.properties.owner.properties.name.type", "string");
}

fn fingerprint(allocator: std.mem.Allocator, bytes: []const u8) ![]const u8 {
    var digest: [32]u8 = undefined;
    std.crypto.hash.sha2.Sha256.hash(bytes, &digest, .{});
    return allocator.dupe(u8, &std.fmt.bytesToHex(digest, .lower));
}

fn usageError(message: []const u8) u8 {
    std.debug.print("teerex doctor: {s}\n{s}", .{ message, usage });
    return 2;
}

pub fn run(allocator: std.mem.Allocator, args: []const []const u8) !u8 {
    if (args.len == 1 and std.mem.eql(u8, args[0], "--help")) {
        try std.fs.File.stdout().writeAll(usage);
        return 0;
    }
    var socket: ?[]const u8 = null;
    var timeout: ?u64 = null;
    var baseline_path: ?[]const u8 = null;
    var i: usize = 0;
    while (i < args.len) : (i += 2) {
        if (i + 1 >= args.len) return usageError("every option needs a value");
        if (std.mem.eql(u8, args[i], "--socket") and socket == null) {
            socket = args[i + 1];
        } else if (std.mem.eql(u8, args[i], "--timeout-ms") and timeout == null) {
            timeout = std.fmt.parseUnsigned(u64, args[i + 1], 10) catch return usageError("invalid timeout");
        } else if (std.mem.eql(u8, args[i], "--baseline") and baseline_path == null) {
            baseline_path = args[i + 1];
        } else return usageError("unknown or repeated option");
    }
    const path = socket orelse return usageError("--socket is required");
    if (!std.fs.path.isAbsolute(path)) return usageError("socket must be absolute");
    const budget = timeout orelse 5000;
    if (budget < 100 or budget > 60000) return usageError("timeout out of range");
    // Validate a baseline before contacting Rex, including on unsupported platforms.
    const baseline: ?struct { schema_version: u32, kind: []const u8, adapter_identity: ?[]const u8 } = if (baseline_path) |file| blk: {
        const bytes = std.fs.cwd().readFileAlloc(allocator, file, 128 * 1024) catch return usageError("cannot read bounded baseline");
        const parsed = std.json.parseFromSlice(struct { schema_version: u32, kind: []const u8, adapter_identity: ?[]const u8 }, allocator, bytes, .{ .ignore_unknown_fields = true }) catch return usageError("invalid baseline JSON");
        if (parsed.value.schema_version != 1 or !std.mem.eql(u8, parsed.value.kind, "rex_compatibility_doctor") or
            parsed.value.adapter_identity == null or parsed.value.adapter_identity.?.len != 64) return usageError("baseline needs a complete doctor identity");
        for (parsed.value.adapter_identity.?) |c| if (!std.ascii.isHex(c)) return usageError("invalid baseline identity");
        break :blk .{ .schema_version = parsed.value.schema_version, .kind = parsed.value.kind, .adapter_identity = parsed.value.adapter_identity };
    } else null;
    if (builtin.os.tag != .macos and builtin.os.tag != .linux) return error.DoctorRequiresUnix;
    const endpoint = try std.fmt.allocPrint(allocator, "unix://{s}", .{path});
    var d: Diagnosis = .{ .allocator = allocator, .endpoint = endpoint, .env = try std.process.getEnvMap(allocator), .timer = try std.time.Timer.start(), .timeout_ms = budget };
    for ([_][]const u8{ "REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT" }) |key| d.env.remove(key);
    d.executable = rexExecutable(allocator, &d.env) catch |err| blk: {
        try d.failure("rex_executable", err);
        break :blk null;
    };
    const signals = supervised.Signals.init();
    defer signals.deinit();
    d.cli = d.identity(&.{ "version", "--json" }) catch |err| blk: {
        try d.failure("cli_version", err);
        break :blk null;
    };
    d.server = d.identity(&.{ "api", "call", "server.version" }) catch |err| blk: {
        try d.failure("server_version", err);
        break :blk null;
    };
    const api_range = d.cli != null and d.server != null and
        d.cli.?.api_revision >= 10 and d.cli.?.api_revision <= 13 and
        d.server.?.api_revision >= 10 and d.server.?.api_revision <= 13 and
        d.cli.?.api_min_revision <= d.server.?.api_revision and d.server.?.api_min_revision <= d.cli.?.api_revision;
    const revision_refusal = if (d.cli != null and d.server != null and !api_range) try std.fmt.allocPrint(allocator, "Rex CLI API revision {d} (minimum {d}), server API revision {d} (minimum {d}); accepted revisions 10..13 with overlapping API support", .{
        d.cli.?.api_revision, d.cli.?.api_min_revision, d.server.?.api_revision, d.server.?.api_min_revision,
    }) else null;
    for (methods, 0..) |method, index| {
        d.checks[index] = .{ .method = method };
        if (api_range) d.checks[index] = d.describe(method) catch |err| blk: {
            try d.failure(method, err);
            break :blk .{ .method = method, .schema_status = "unknown", .error_name = @errorName(err) };
        };
    }
    // A successful version query remains observed evidence even when the range
    // or a later descriptor check refuses this server.
    d.checks[0].behavior_tested = d.server != null;
    if (api_range) d.bindings() catch |err| {
        d.lua_bindings = "unknown";
        try d.failure("lua_bindings", err);
    };
    var selected_shapes = api_range;
    for (d.checks) |check| selected_shapes = selected_shapes and std.mem.eql(u8, check.schema_status, "selected_shape_matches");
    const call_encode = d.binding_shapes != null and std.mem.eql(u8, d.binding_shapes.?.call, "function") and
        std.mem.eql(u8, d.binding_shapes.?.encode, "function");
    const observe_requirements = selected_shapes and call_encode;
    const watch_requirements = observe_requirements and std.mem.eql(u8, d.binding_shapes.?.sleep, "function");
    const run_requirements = api_range and std.mem.eql(u8, d.checks[0].schema_status, "selected_shape_matches") and
        call_encode and std.mem.eql(u8, d.binding_shapes.?.exec_start, "function");
    const complete = observe_requirements and watch_requirements and run_requirements;
    // The identity is deliberately conservative: even changed descriptor prose/order
    // invalidates a previous receipt. No cached adapter is silently reused.
    var descriptors: [methods.len]?[]const u8 = undefined;
    for (d.checks, 0..) |check, index| descriptors[index] = check.descriptor_sha256;
    const identity = if (complete) try fingerprint(allocator, try std.json.Stringify.valueAlloc(allocator, .{
        .contract = "observe_watch_run_api10_13",
        .server = endpoint,
        .cli = d.cli,
        .source = d.server,
        .descriptors = descriptors,
        .lua_bindings = d.lua_bindings,
    }, .{})) else null;
    const identity_changed = if (baseline) |prior| identity == null or !std.mem.eql(u8, identity.?, prior.adapter_identity.?) else false;
    const cancelled = supervised.requestedSignal();
    var deadline = false;
    for (d.diagnostics.items) |diagnostic| {
        if (std.mem.eql(u8, diagnostic.error_name, "DoctorDeadlineExceeded")) deadline = true;
    }
    const ok = complete and !identity_changed and cancelled == 0 and !deadline;
    const same_build: ?bool = if (d.cli != null and d.server != null) d.cli.?.api_revision == d.server.?.api_revision and
        d.cli.?.api_min_revision == d.server.?.api_min_revision and std.mem.eql(u8, d.cli.?.platform, d.server.?.platform) and
        std.mem.eql(u8, d.cli.?.rex_version, d.server.?.rex_version) and optionalEqual(d.cli.?.commit, d.server.?.commit) and
        optionalEqual(d.cli.?.built_at, d.server.?.built_at) and d.cli.?.dirty == d.server.?.dirty else @as(?bool, null);
    const output = try std.json.Stringify.valueAlloc(allocator, .{
        .schema_version = 1,
        .kind = "rex_compatibility_doctor",
        .server = endpoint,
        .client_platform = @tagName(builtin.os.tag) ++ "/" ++ @tagName(builtin.cpu.arch),
        .cli = d.cli,
        .source = d.server,
        .rex_executable = d.executable,
        .cli_server_same_build = same_build,
        .cli_server_mismatch = if (same_build) |same| !same else @as(?bool, null),
        .client_server_check = if (same_build) |same| (if (same) "same_build" else "mismatch_review_selected_client_and_server") else "unknown",
        .operation_platform_support = .{
            .observe = "applicable",
            .watch = "applicable",
            .run = if (builtin.os.tag == .macos) "applicable" else "not_applicable",
            .run_reason = if (builtin.os.tag == .macos) @as(?[]const u8, null) else "teerex run requires macOS; binding discovery does not establish Linux execution support",
        },
        .accepted_api_revisions = .{ .min = 10, .max = 13 },
        .api_revision_matches = if (d.cli != null and d.server != null) api_range else @as(?bool, null),
        .api_revision_refusal = revision_refusal,
        .methods = d.checks,
        .lua_bindings = d.lua_bindings,
        .lua_binding_shapes = d.binding_shapes,
        .operation_advertised_requirements_met = .{ .observe = observe_requirements, .watch = watch_requirements, .run = run_requirements },
        .advertised_requirements_met = complete,
        .behavior_certified = false,
        .recorded_build_behavior = "see_exact_build_matrix_in_items/doctor/README.md_not_inferred_from_revision",
        .observe_watch_behavior = "not_tested_no_terminal_reads",
        .run_behavior = "not_tested_no_program_started",
        .offstage = "not_assessed_contract_not_included",
        .permission = "not_assessed_discovery_is_not_authorization",
        .adapter_identity = identity,
        .baseline_identity = if (baseline) |prior| prior.adapter_identity else null,
        .identity_status = if (baseline == null) "not_compared" else if (identity_changed) "changed_or_unknown" else "unchanged",
        .adapter_revalidation_required = !complete or identity_changed,
        .diagnostics = d.diagnostics.items,
        .outcome = if (cancelled != 0) "cancel_requested" else if (deadline) "deadline_exceeded" else if (ok) "advertised_requirements_met" else "incompatible_or_unknown",
        .elapsed_ms = d.timer.read() / std.time.ns_per_ms,
        .timeout_ms = budget,
    }, .{ .whitespace = .indent_2 });
    try std.fs.File.stdout().writeAll(output);
    try std.fs.File.stdout().writeAll("\n");
    return if (cancelled != 0) 128 + cancelled else if (deadline) 124 else if (ok) 0 else 1;
}

fn optionalEqual(a: ?[]const u8, b: ?[]const u8) bool {
    if (a == null or b == null) return a == null and b == null;
    return std.mem.eql(u8, a.?, b.?);
}

// Freeze PATH selection before invoking Rex; receipts name the executable used.
fn rexExecutable(allocator: std.mem.Allocator, env: *std.process.EnvMap) ![]const u8 {
    if (env.get("TEEREX_INTERNAL_REX")) |path| {
        if (!std.fs.path.isAbsolute(path)) return error.RexExecutableMustBeAbsolute;
        return path;
    }
    if (env.get("TEEREX_REX")) |path| {
        if (!std.fs.path.isAbsolute(path)) return error.RexExecutableMustBeAbsolute;
        return path;
    }
    var denied = false;
    var paths = std.mem.splitScalar(u8, env.get("PATH") orelse "", std.fs.path.delimiter);
    while (paths.next()) |directory| {
        const path = try std.fs.path.resolve(allocator, &.{ directory, "rex" });
        std.posix.access(path, std.posix.X_OK) catch |err| {
            if (err == error.AccessDenied) denied = true;
            continue;
        };
        return path;
    }
    return if (denied) error.AccessDenied else error.FileNotFound;
}
