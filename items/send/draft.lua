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
    elseif s:sub(1, #"›") == "›" then s = s:sub(#"›" + 1)
    else return nil end
    s = trim(s)
    for _, border in ipairs({"│", "┃", "|"}) do
        if s:sub(-#border) == border then s = trim(s:sub(1, #s - #border)); break end
    end
    return trim(s)
end
local function visible_text(line)
    -- The renderer erases and skips unused background cells at the right edge.
    line = line:gsub("\27%[(%d+)X\27%[%1C", "")
    local dim, grey, out, pos, rendered = false, false, {}, 1, 0
    while pos <= #line do
        local first, last = line:find(csi, pos)
        local part = line:sub(pos, first and first - 1 or #line)
        if not dim and not grey then
            if #part > 1048576 - rendered then return nil end
            table.insert(out, part); rendered = rendered + #part
        end
        if not first then break end
        local escape = line:sub(first, last)
        local forward = escape:match("^\27%[(%d*)C$")
        if forward ~= nil then
            local count = math.max(1, tonumber(forward) or 1)
            if count > 1048576 then return nil end
            if not dim and not grey then
                if count > 1048576 - rendered then return nil end
                table.insert(out, string.rep(" ", count)); rendered = rendered + count
            end
        elseif escape:sub(-1) == "m" then
            local codes = {}
            local parameters = escape:sub(3, -2) .. ";"
            for code in parameters:gmatch("(.-);") do
                local n = tonumber(code == "" and "0" or code)
                if not n then return nil end
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
                elseif (c == 48 or c == 58) and codes[i+1] == 2 and codes[i+4] then
                    -- Background/underline RGB channels are not SGR attributes (notably 2=dim).
                    i = i + 4
                elseif (c == 48 or c == 58) and codes[i+1] == 5 and codes[i+2] then
                    i = i + 2
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
    return table.concat(out)
end

local function active_screen(text, rows)
    if type(text) ~= "string" or type(rows) ~= "number" or rows < 1 then return end
    local row, col = text:match("\27%[(%d+);(%d+)H$")
    row, col = tonumber(row), tonumber(col)
    if not row or row < 1 or row > rows or col < 1 then return end
    local lines = {}
    text = text:gsub("\27%[%d+;%d+H$", "")
    for line in (text .. "\n"):gmatch("([^\n]*)\n") do table.insert(lines, (line:gsub("\r$", ""))) end
    if #lines < rows then return end
    local screen = {}
    for i = #lines - rows + 1, #lines do table.insert(screen, lines[i]) end
    return screen, row, col
end

local function marker_row(line)
    if not line then return nil end
    local plain = line:gsub(csi, "")
    for _, border in ipairs({"│", "┃", "|"}) do
        if plain:sub(1, #border) == border then return prompt(plain) end
    end
    if plain:sub(1, 1) == ">" or
       plain:sub(1, #"❯") == "❯" or plain:sub(1, #"›") == "›" then
        return prompt(plain)
    end
end

local function prompt_body(line, exact)
    -- Find the marker in the unfiltered line first. A grey marker can be absent from visible output.
    local end_marker
    for _, marker in ipairs({">", "❯", "›"}) do
        local index = line:find(marker, 1, true)
        if index and (not end_marker or index < end_marker) then end_marker = index + #marker end
    end
    if not end_marker then return nil end
    local prefix = line:sub(1, end_marker - 1)
    -- Preserve SGR context across the marker, including a grey suggestion that shares its style.
    local styles = {}
    for escape in prefix:gmatch(csi) do
        if escape:sub(-1) == "m" then table.insert(styles, escape) end
    end
    local suffix = line:sub(end_marker)
    local body = visible_text(table.concat(styles) .. suffix)
    if body == nil then return nil end
    local plain_prefix = trim((prefix:gsub(csi, "")))
    for _, border in ipairs({"│", "┃", "|"}) do
        if plain_prefix:sub(1, #border) == border and body:sub(-#border) == border then
            body = body:sub(1, -#border-1)
            break
        end
    end
    if exact then
        if body:sub(1, 1) == " " then body = body:sub(2)
        elseif body:sub(1, 2) == "\194\160" then body = body:sub(3) end
        local _, characters = plain_prefix:gsub("[^\128-\191]", "")
        local suggestion = trim(body) == "" and trim((suffix:gsub(csi, ""))) ~= ""
        return body, characters + 2, suggestion
    end
    return trim(body)
end

local function shell_draft_from_vt(text, rows)
    local lines, row = active_screen(text, rows)
    if not lines then return nil end
    local path, body = lines[row]:match("^\27%[0m\27%[1m\27%[38;5;4m([^\27]+)\27%[0m (.*)$")
    if body == nil or not (path:match("^~") or path:match("^/")) then return nil end
    local visible = visible_text(body)
    return visible and trim(visible), #path + 2
end

local function rule(line)
    local plain = trim((line:gsub(csi, "")))
    return plain:sub(1, #"──") == "──" and
        (plain:gsub("─", ""):match("^%s*$") ~= nil or plain:find("↑", 1, true) ~= nil)
end

-- Return a state, visible editor rows for local verification, and whether a tracked editor was found.
local function input_state(text, rows, app, process, columns)
    local lines, row, col = active_screen(text, rows)
    if not lines then return "unknown" end
    local above, below
    for i = row - 1, 1, -1 do if rule(lines[i]) then above = i; break end end
    for i = row + 1, #lines do if rule(lines[i]) then below = i; break end end
    if above and below then
        local first = above + 1
        if lines[above]:find("↑", 1, true) then return "present", nil, true end
        if marker_row(lines[first]) ~= nil then
            local body, start = prompt_body(lines[first], true)
            if not body then return "unknown" end
            local parts = {body}
            for i = first + 1, below - 1 do
                local visible = visible_text(lines[i])
                if visible == nil then return "unknown" end
                table.insert(parts, (visible:gsub("^  ", "", 1)))
            end
            local _, width = lines[below]:gsub("─", "")
            return (#parts > 1 or trim(body) ~= "" or col > start) and "present" or "empty", parts, true, width
        elseif app == "pi" then
            local parts = {}
            for i = first, below - 1 do
                local visible = visible_text(lines[i])
                if visible == nil then return "unknown" end
                table.insert(parts, visible)
            end
            return (#parts > 1 or trim(parts[1]) ~= "" or col > 1) and "present" or "empty", parts, true, columns
        end
    end
    if app == "claude" or app == "pi" then return "unknown" end
    for i = row, 1, -1 do
        if marker_row(lines[i]) ~= nil then
            local body, start, suggestion = prompt_body(lines[i], true)
            if not body then return "unknown" end
            local parts = {body}
            for j = i + 1, row do
                local visible = visible_text(lines[j])
                if visible == nil then return "unknown" end
                table.insert(parts, (visible:gsub("^  ", "", 1)))
            end
            return (#parts > 1 or trim(body) ~= "" or (not suggestion and col > start))
                and "present" or "empty", parts, true, columns
        end
        -- A blank cursor row in a plain terminal cannot authenticate earlier output as a prompt.
        if i == row and app == nil and trim((lines[i]:gsub(csi, ""))) == "" then break end
    end
    if app then return "unknown" end
    if process == "zsh" then
        local body, start = shell_draft_from_vt(text, rows)
        if body then return (trim(body) ~= "" or col > start) and "present" or "empty", {trim(body)}, true end
    end
    return "empty", nil, false
end

-- Legacy read-only observation has no cursor or screen dimensions. Sends never use it.
local function draft_from_vt(text)
    local recent, count = {}, 0
    for line in (text .. "\n"):gmatch("([^\n]*)\n") do
        if trim((line:gsub(csi, ""))) ~= "" then count = count + 1; recent[count % 15] = line end
    end
    for i = count, math.max(1, count - 14), -1 do
        local line = recent[i % 15]
        if prompt((line:gsub(csi, ""))) ~= nil then return prompt_body(line) end
    end
    return ""
end
