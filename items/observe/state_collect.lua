-- Read-only, one connection. The shared send draft parser precedes this source.
local a = rex.args
local function read(method, args)
    local v, e = rex.call(method, args)
    if not v then error(e) end
    if #rex.json.encode(v) > 131072 then error("state_response_exceeds_limit") end
    return v
end
local version = read("server.version")
if type(version.api_revision) ~= "number" or version.api_revision < 10 or version.api_revision > 13 then
    error("unsupported_agent_state_api")
end
local target = {session_id=a.session_id, block_id=a.block_id, args={}}
local capture = read("com.superlogical.terminal.format", {session_id=a.session_id, block_id=a.block_id,
    args={format="vt", max_bytes=a.max_bytes - 2}})
local process = read("com.superlogical.terminal.process", target)
local status = read("com.superlogical.terminal.program_status", target)
local complete = capture.id == nil
local parsed, editor = nil, nil
if complete then
    local ok, draft = pcall(draft_from_vt, capture.content)
    if ok and type(draft) == "string" then parsed = draft ~= "" end
    -- Pi's default editor has horizontal borders and no prompt chevron. Feed
    -- its bounded editor lines through the SAME style/suggestion parser.
    local lines, borders = {}, {}
    for line in (capture.content .. "\n"):gmatch("([^\n]*)\n") do
        table.insert(lines, line)
        local plain = trim(line:gsub(csi, ""))
        if plain:sub(1, #"──") == "──" then table.insert(borders, #lines) end
    end
    if #borders >= 2 then
        local first, last = borders[#borders-1], borders[#borders]
        if last > first and last - first <= 8 then
            editor = false
            for i=first+1,last-1 do
                local ok, draft = pcall(draft_from_vt, "> " .. lines[i])
                if not ok or type(draft) ~= "string" then editor=nil; break end
                if draft ~= "" then editor = true end
            end
        end
    end
end
local p = '{"child":' .. rex.json.encode(process.child) .. ',"foreground":' .. rex.json.encode(process.foreground) ..
    ',"last_exit":' .. rex.json.encode(process.last_exit) .. '}'
local s = rex.json.encode(status)
if type(status.records) ~= "table" then error("invalid_status_records") end
if next(status.records) == nil then s = '{"records":[]}' end
io.write('{"version":', rex.json.encode(version), ',"capture":', rex.json.encode(capture), ',"process":', p,
    ',"status":', s, ',"draft_present":', parsed == nil and 'null' or tostring(parsed),
    ',"editor_draft_present":', editor == nil and 'null' or tostring(editor), '}\n')
