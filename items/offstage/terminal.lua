-- Fixed source. Only this invocation's newly created terminal is managed.
local a = rex.args
local function call(method, args)
    local value, err = rex.call(method, args)
    if not value then error(err) end
    if #rex.json.encode(value) > 128 * 1024 then error("Rex response exceeds 128 KiB") end
    return value
end
local function emit(value)
    io.write(rex.json.encode(value), "\n"); io.flush()
end
local version = call("server.version")
if version.api_revision ~= 13 or (version.platform ~= "darwin_arm64" and version.platform ~= "linux_amd64") then
    error("offstage requires API-13 macOS arm64 or Linux x86_64 server")
end
local server = call("server.status")
if not server.instance_id or not server.host_id then error("missing server identity") end

if a.operation == "close" then
    if server.instance_id ~= a.instance_id or server.host_id ~= a.host_id then
        emit({event="closed", instance_matched=false}); return
    end
    local closed = rex.call("block.close", {session_id=a.session_id, block_id=a.block_id})
    local blocks = call("session.list_blocks", {session_id=a.session_id})
    if type(blocks.blocks) ~= "table" then error("missing block list; absence unknown") end
    local absent = true
    for index, block in pairs(blocks.blocks) do
        if type(index) ~= "number" or index % 1 ~= 0 or index < 1 or index > #blocks.blocks or
            type(block) ~= "table" or type(block.block_id) ~= "string" then
            error("invalid block list; absence unknown")
        end
        if block.block_id == a.block_id then absent = false end
    end
    emit({event="closed", instance_matched=true, close_acknowledged=closed ~= nil, block_absent=absent})
    return
end

local creators = call("block_creator.list")
local local_terminal = false
for _, creator in ipairs(creators.creators or {}) do
    if creator.name == "com.superlogical.terminal" and creator.host_id == server.host_id then local_terminal = true end
end
if not local_terminal then error("terminal creator host does not match selected server") end
emit({event="source", source={rex_version=version.rex_version, platform=version.platform,
    api_revision=version.api_revision, instance_id=server.instance_id, host_id=server.host_id}})
-- A lost create acknowledgement leaves the outcome unknown: never retry creation.
emit({event="creating"})
-- The fixed shim fails closed on an invalid cwd, rather than accepting Rex's
-- documented fallback to home. Values are argv, not interpolated shell source.
local command = {"/bin/sh", "-c", 'cd -- "$1" || exit 125\nshift\nexec "$@"', "teerex-offstage", a.cwd}
for _, arg in ipairs(a.argv) do command[#command + 1] = arg end
local block = call("session.new_block", {session_id=a.session_id,
    flavor="com.superlogical.terminal.shell", label=a.label,
    options={shell="none", login=false, interactive=false, cwd=a.cwd, command=command,
        exit={on_completion=false}}})
emit({event="created", block_id=block.block_id})
while true do
    local process = call("com.superlogical.terminal.process", {session_id=a.session_id, block_id=block.block_id, args={}})
    if process.last_exit then
        local capture = call("com.superlogical.terminal.format", {session_id=a.session_id, block_id=block.block_id,
            args={format="text", max_bytes=a.max_bytes - 2}})
        emit({event="exited", exit_code=process.last_exit.exit_code, content=capture.content,
            complete=capture.id == nil})
        return
    end
    rex.sleep(0.05)
end
