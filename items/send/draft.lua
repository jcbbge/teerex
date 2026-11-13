-- Port of agent-core agent-send GUARD_PY: last 15 nonempty VT lines,
-- prompt borders, and SGR dim/grey filtering. No draft text leaves this Lua chunk.
local csi = "\27%[[0-?]*[ -/]*[@-~]"
local whitespace = {" ", "\t", "\r", "\n", "\v", "\f", "\28", "\29", "\30", "\31", "\194\133", "\194\160", "\225\154\128", "\226\128\128", "\226\128\129", "\226\128\130", "\226\128\131", "\226\128\132", "\226\128\133", "\226\128\134", "\226\128\135", "\226\128\136", "\226\128\137", "\226\128\138", "\226\128\168", "\226\128\169", "\226\128\175", "\226\129\159", "\227\128\128"}
local function trim(s)
    local changed = true
    while changed do
        changed = false
        for _, w in ipairs(whitespace) do
            if s:sub(1, #w) == w then s = s:sub(#w + 1); changed = true end
            if s:sub(-#w) == w then s = s:sub(1, #s - #w); changed = true end
        end
    end
    return s
end
local function prompt(s)
    s = trim(s)
    for _, border in ipairs({"│", "┃", "|"}) do
        if s:sub(1, #border) == border then s = trim(s:sub(#border + 1)); break end
    end
    if s:sub(1, 1) == ">" then s = s:sub(2)
    elseif s:sub(1, #"❯") == "❯" then s = s:sub(#"❯" + 1)
    else return nil end
    s = trim(s)
    for _, border in ipairs({"│", "┃", "|"}) do
        if s:sub(-#border) == border then s = trim(s:sub(1, #s - #border)); break end
    end
    return trim(s)
end
local function draft_from_vt(text)
    local lines = {}
    for line in (text .. "\n"):gmatch("([^\n]*)\n") do
        if trim((line:gsub(csi, ""))) ~= "" then table.insert(lines, line) end
    end
    local draft = ""
    for index = math.max(1, #lines - 14), #lines do
        local line = lines[index]
        if prompt((line:gsub(csi, ""))) ~= nil then
            local dim, grey, out, pos = false, false, {}, 1
            while pos <= #line do
                local first, last = line:find(csi, pos)
                local part = line:sub(pos, first and first - 1 or #line)
                if not dim and not grey then table.insert(out, part) end
                if not first then break end
                local escape = line:sub(first, last)
                if escape:sub(-1) == "m" then
                    local codes = {}
                    local parameters = escape:sub(3, -2) .. ";"
                    for code in parameters:gmatch("(.-);") do
                        local n = tonumber(code == "" and "0" or code)
                        if not n then return "" end
                        table.insert(codes, n)
                    end
                    local i = 1
                    while i <= #codes do
                        local c = codes[i]
                        if c == 0 then dim, grey = false, false
                        elseif c == 2 then dim = true
                        elseif c == 22 then dim = false
                        elseif c == 90 then grey = true
                        elseif c == 39 or (c >= 30 and c <= 37) or (c >= 91 and c <= 97) then grey = false
                        elseif c == 38 and codes[i+1] == 5 and codes[i+2] then
                            -- Rex VT captures normalize SGR90 into indexed colour8.
                            grey = codes[i+2] == 8 or (codes[i+2] >= 240 and codes[i+2] <= 250); i = i + 2
                        elseif c == 38 and codes[i+1] == 2 and codes[i+4] then
                            grey = codes[i+2] == codes[i+3] and codes[i+3] == codes[i+4] and codes[i+2] < 160; i = i + 4
                        end
                        i = i + 1
                    end
                end
                pos = last + 1
            end
            draft = prompt(table.concat(out)) or ""
        end
    end
    return draft
end
