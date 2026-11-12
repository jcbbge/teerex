-- Fixed source: target and budget arrive as JSON, never interpolated Lua.
local a = rex.args
local function read(method, args)
    local value, err = rex.call(method, args)
    if not value then error(err) end
    local encoded = rex.json.encode(value)
    if #encoded > 128 * 1024 then error("Rex response exceeds 128 KiB") end
    return value, encoded
end

local function collect()
    local version, v = read("server.version")
    local revision = version.api_revision
    if type(revision) ~= "number" or revision % 1 ~= 0 or revision < 10 or revision > 13 then
        error("unsupported Rex API revision " .. tostring(revision) .. " (accepted: 10..13)")
    end
    local target = {session_id=a.session_id, block_id=a.block_id, args={}}
    local _, capture = read("com.superlogical.terminal.format", {
        session_id=a.session_id, block_id=a.block_id,
        args={format="text", max_bytes=a.max_bytes - 2},
    })
    local process = read("com.superlogical.terminal.process", target)
    local _, directory = read("com.superlogical.terminal.pwd", target)
    local status, s = read("com.superlogical.terminal.program_status", target)

    -- Lua drops null object members and encodes an empty array as {}. Restore
    -- only the consumed shapes, not arbitrary nulls/arrays or inferred facts.
    local p = '{"child":' .. rex.json.encode(process.child) ..
        ',"foreground":' .. rex.json.encode(process.foreground) ..
        ',"last_exit":' .. rex.json.encode(process.last_exit) .. '}'
    if type(status.records) ~= "table" then error("invalid status records") end
    if next(status.records) == nil then s = '{"records":[]}' end
    -- The five reads remain serial and NON-ATOMIC; no partial sample is emitted.
    return '{"version":' .. v .. ',"capture":' .. capture .. ',"process":' .. p ..
        ',"directory":' .. directory .. ',"status":' .. s .. '}'
end

if a.interval_ms then
    while true do
        io.write('{"event":"sample","data":', collect(), '}\n'); io.flush()
        rex.sleep(a.interval_ms / 1000)
        io.write('{"event":"collecting"}\n'); io.flush()
    end
else
    io.write(collect())
end
