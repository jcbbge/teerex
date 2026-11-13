-- Fixed source: target and budget arrive as JSON, never interpolated Lua.
local a = rex.args
local function read(method, args)
    local value, err = rex.call(method, args)
    if not value then error(err) end
    local encoded = rex.json.encode(value)
    local limit = method == "com.superlogical.terminal.blob_read" and 512*1024 or 128*1024
    if #encoded > limit then error("Rex response exceeds retained limit") end
    return value, encoded
end

local function collect()
    local version, v = read("server.version")
    local revision = version.api_revision
    if type(revision) ~= "number" or revision % 1 ~= 0 or revision < 10 or revision > 13 then
        error("unsupported Rex API revision " .. tostring(revision) .. " (accepted: 10..13)")
    end
    local target = {session_id=a.session_id, block_id=a.block_id, args={}}
    local captured, capture = read("com.superlogical.terminal.format", {
        session_id=a.session_id, block_id=a.block_id,
        args={format="text", max_bytes=a.max_bytes - 2},
    })
    if a.tail then
        if revision ~= 13 then error("tail capture requires observed API13") end
        local text = captured.content
        if type(text) ~= "string" then error("invalid capture text") end
        local offset = 0
        if captured.id ~= nil then
            if type(captured.id) ~= "number" or captured.id % 1 ~= 0 or captured.id < 0 or
                type(captured.total) ~= "number" or captured.total % 1 ~= 0 or captured.total < #text then
                error("tail capture requires blob id and total")
            end
            -- The overlap keeps any replacement bytes from an unaligned blob
            -- start outside the retained UTF-8 suffix. One bounded blob read
            -- reaches EOF; continuation never recaptures a changing terminal.
            offset = math.max(0, captured.total - (a.max_bytes - 2) - 4)
            local blob = read("com.superlogical.terminal.blob_read", {
                session_id=a.session_id, block_id=a.block_id,
                args={id=captured.id, offset=offset, max_bytes=6*(a.max_bytes+4)}})
            if blob.id ~= captured.id or blob.total ~= captured.total or blob.eof ~= true or type(blob.data) ~= "string" then
                error("incomplete or mismatched tail continuation")
            end
            if #blob.data < captured.total-offset or #blob.data > captured.total-offset+8 then
                error("tail continuation byte count mismatch")
            end
            text = blob.data
        end
        -- Find the longest suffix whose JSON string fits the public byte budget.
        -- JSON-encoded size is monotone as whole UTF-8 characters are removed.
        local low, high = 1, #text + 1
        while low < high do
            local middle = math.floor((low+high)/2)
            local boundary = middle
            while boundary <= #text and text:byte(boundary) >= 128 and text:byte(boundary) < 192 do
                boundary = boundary + 1
            end
            if #rex.json.encode(text:sub(boundary)) <= a.max_bytes then high = middle
            else low = middle + 1 end
        end
        while low <= #text and text:byte(low) >= 128 and text:byte(low) < 192 do low=low+1 end
        local complete = offset == 0 and low == 1
        local tail = {content=text:sub(low), portion="tail", eof=complete}
        if not complete then tail.id=captured.id or 0 end
        capture = rex.json.encode(tail)
    end
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
