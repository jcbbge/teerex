-- Fixed code, JSON arguments. One attached connection; no focus lookup or retry.
local a = rex.args
local function emit(v)
    io.write(rex.json.encode(v), "\n"); io.flush()
end
local function refuse(reason)
    emit({event="refused", reason=reason})
end
local v, err = rex.call("server.version")
if not v then refuse("version_unavailable"); return end
emit({event="source", source={rex_version=v.rex_version, platform=v.platform, api_revision=v.api_revision}})
if type(v.api_revision) ~= "number" or v.api_revision % 1 ~= 0 or v.api_revision < 10 or v.api_revision > 13 then
    refuse("unsupported_send_api_revision"); return
end
local view = rex.call("session.view", {session_id=a.session_id})
if type(view) ~= "table" or view.session_id ~= a.session_id then refuse("target_unavailable"); return end
local terminal = false
for _, w in ipairs(view.windows or {}) do
    for _, l in ipairs(w.layers or {}) do
        for _, b in ipairs(l.blocks or {}) do
            if b.block_id == a.block_id and b.creator_name == "com.superlogical.terminal" then terminal = true end
        end
    end
end
-- Detached terminals remain explicit tracked destinations. Keep the same draft
-- and clutch paths below; only presence is read from the complete inventory.
if not terminal and v.api_revision==13 then
    local listed=rex.call("session.list_blocks", {session_id=a.session_id})
    for _,b in ipairs(type(listed)=="table" and listed.blocks or {}) do
        if b.block_id==a.block_id and b.creator_name=="com.superlogical.terminal" and b.placement=="detached" then
            terminal=true
        end
    end
end
if not terminal then refuse("target_not_visible_terminal"); return end
local paste = {session_id=a.session_id, block_id=a.block_id, event={type="paste", payload={text=a.text}}}
-- Rex preview.16 caps control messages at 65536 bytes. Use Rex's own encoder,
-- not raw text length: quotes, LF and HTML characters can expand. Leave >5 KiB
-- for the actual protocol envelope/ID; this is not a maximum-throughput claim.
local n = #rex.json.encode({jsonrpc="2.0", id=1, method="block.event", params=paste})
emit({event="preflight", encoded_rpc_bytes=n})
if n > 60000 then refuse("encoded_paste_exceeds_limit"); return end
local draft = {mode=a.draft_mode, state="unknown", deferred=false}
local function report()
    emit({event="draft", draft=draft})
end
local target = {session_id=a.session_id, block_id=a.block_id, args={}}
local function read_input()
    local size = rex.call("com.superlogical.terminal.size", target)
    local process = rex.call("com.superlogical.terminal.process", target)
    local status = rex.call("com.superlogical.terminal.program_status", target)
    local function identify(name)
        if type(name) ~= "string" then return end
        name = name:match("([^/]+)$") or name
        if name == "claude" or name == "claude-code" or name:match("^%d+%.%d+%.%d+$") then return "claude" end
        if name == "codex" or name == "pi" then return name end
    end
    local foreground = type(process) == "table" and process.foreground
    local name = type(foreground) == "table" and foreground.name
    local child = type(process) == "table" and process.child
    local function identify_process(info)
        if type(info) ~= "table" then return end
        local app = identify(info.name) or identify(info.argv0)
        if app then return app end
        if type(info.script) == "string" and
           (info.name == "node" or info.argv0 == "node" or
            (type(info.argv0) == "string" and info.argv0:match("/node$"))) then
            if identify(info.script) == "pi" or info.script:find("/pi/", 1, true) or
               info.script:find("/pi-coding-agent/", 1, true) then return "pi" end
        end
    end
    local app = identify_process(foreground) or identify_process(child)
    if type(status) == "table" and type(status.records) == "table" then
        for _, record in pairs(status.records) do
            if type(record) == "table" then app = app or identify(record.app) end
        end
    end
    local capture = rex.call("com.superlogical.terminal.format", {
        session_id=a.session_id, block_id=a.block_id, args={format="vt", extra_cursor=true},
    })
    if type(capture) ~= "table" or capture.id ~= nil then return "unknown" end
    if type(size) ~= "table" then return "unknown" end
    return input_state(capture.text or capture.content, size.rows, app, name, size.columns)
end
-- Cooperative state is local to the command/Rex host. No server input lease is implied.
local clutch = {state="unknown", held_observed=false, waited_ms=0, bound_reached=false}
local clutch_reason
local function gate(no_wait)
    local function unknown(reason)
        clutch.state, clutch.failure_reason = "unknown", reason
        emit({event="clutch", clutch=clutch})
        return true
    end
    if type(a.clutch_file) ~= "string" then
        return unknown(type(a.clutch_failure) == "string" and a.clutch_failure or "clutch_state_unavailable")
    end
    while true do
        local f, open_error, errno = io.open(a.clutch_file, "r")
        local held = false
        if f then
            local raw = f:read(8193); f:close()
            local ok, state = pcall(rex.json.decode, raw)
            if not ok or type(state) ~= "table" or type(state.held) ~= "boolean" or #raw > 8192 then
                return unknown("clutch_state_invalid")
            end
            held = state.held
        -- Rex's Go-backed Lua reports generic code1 for ENOENT; accept its exact Unix suffix too.
        elseif errno ~= 2 and not (type(open_error) == "string" and open_error:match(": no such file or directory$")) then
            return unknown("clutch_state_unreadable")
        end
        clutch.state, clutch.failure_reason = held and "held" or "released", nil
        if not held then emit({event="clutch", clutch=clutch}); return true end
        clutch.held_observed = true
        if no_wait or a.queue_on_hold or clutch.waited_ms >= a.draft_wait_ms then
            clutch.bound_reached = true
            clutch_reason = "pane_held_by_human"
            emit({event="clutch", clutch=clutch})
            return false
        end
        local delay = math.min(100, a.draft_wait_ms - clutch.waited_ms)
        rex.sleep(delay / 1000)
        clutch.waited_ms = clutch.waited_ms + delay
        emit({event="clutch", clutch=clutch})
    end
end
-- Match all visible text, allowing layout to split words or wrap at a space
-- near the right rule. A rendered short row cannot stand in for a missing line break.
local function matches_paste(parts, text, width)
    if not parts then return false end
    local at = 1
    for i, part in ipairs(parts) do
        if text:sub(at, at + #part - 1) ~= part then return false end
        at = at + #part
        local next_part = parts[i + 1]
        if next_part then
            local boundary = text:sub(at, at)
            if boundary == "\n" then
                at = at + 1
            elseif width then
                local next_word = next_part:match("^%S+") or ""
                if boundary == " " and #part + #next_word + 3 >= width then
                    at = at + 1
                elseif #part + 3 < width then
                    return false
                end
            else
                return false
            end
        end
    end
    return at == #text + 1
end

local function finish(reason, attempted)
    if reason then
        if attempted then emit({event="failed", reason=reason}) else refuse(reason) end
    else
        emit({event="finished"})
    end
    rex.stop()
end

local guarded = a.draft_mode == "guard"
local previous
if guarded and type(a.settle_file) == "string" then
    local file = io.open(a.settle_file, "r")
    if file then previous = file:read("*a"); file:close() end
    if previous == "" then previous = nil end
end
if not gate(previous ~= nil) then finish(clutch_reason); return end
local editor
if guarded then
    local waited = 0
    while true do
        local state, parts, tracked, width = read_input()
        draft.state, editor = state, tracked
        if state == "empty" then break end
        local wait_ms = a.queue_on_hold and 0 or a.draft_wait_ms
        if previous then
            -- Wait only for this drain's last submission. A different draft,
            -- an ambiguous placeholder, or unknown input stops immediately.
            wait_ms = state == "present" and matches_paste(parts, previous, width) and 2000 or 0
        end
        if waited >= wait_ms then
            report()
            finish(state == "present" and "draft_present" or "input_state_unknown")
            return
        end
        local delay = math.min(100, wait_ms - waited)
        rex.sleep(delay / 1000)
        waited = waited + delay
        if not gate(previous ~= nil) then finish(clutch_reason); return end
    end
end
report()
if not gate(previous ~= nil) then finish(clutch_reason); return end
if guarded then
    local state, _, tracked = read_input()
    draft.state, editor = state, tracked
    if state ~= "empty" then
        report()
        finish(state == "present" and "draft_present" or "input_state_unknown")
        return
    end
end
if type(a.queue_exchange) == "string" then
    local ready = io.open(a.queue_exchange .. "/ready", "w")
    if not ready then finish("queue_dispatch_unavailable"); return end
    ready:close()
    local permit
    for _ = 1, 100 do
        permit = io.open(a.queue_exchange .. "/claimed", "r")
        if permit then break end
        rex.sleep(.01)
    end
    if not permit then finish("queue_dispatch_unavailable"); return end
    permit:close()
    if not gate(true) then finish(clutch_reason); return end
    local state, _, tracked = read_input()
    editor = editor or tracked
    if state ~= "empty" then
        draft.state = state
        report()
        finish(state == "present" and "draft_present" or "input_state_unknown")
        return
    end
end
emit({event="attempt", stage="paste"})
if not rex.call("block.event", paste) then finish("paste_call_failed", true); return end
emit({event="ack", stage="paste"})
-- Rex acknowledges dispatch before the editor necessarily redraws.
if guarded then
    local newline_count = select(2, a.text:gsub("\n", ""))
    for waited = 75, 1500, 75 do
        rex.sleep(.075)
        if not gate(true) then finish(clutch_reason, true); return end
        local state, parts, tracked, width = read_input()
        if state == "present" then
            local content = parts and table.concat(parts, "\n")
            local lines = content and content:match("^%[Pasted text #%d+ %+(%d+) lines?%]$")
            if matches_paste(parts, a.text, width) or tonumber(lines) == newline_count then break end
            finish("input_changed_before_enter", true)
            return
        end
        -- Preserve the no-echo path for terminals without a recognized editor.
        editor = editor or tracked
        if state == "empty" and not editor then break end
        if waited == 1500 then finish("input_changed_before_enter", true); return end
    end
elseif not gate(false) then
    finish(clutch_reason, true)
    return
end
emit({event="attempt", stage="enter"})
local ok = rex.call("block.event", {session_id=a.session_id, block_id=a.block_id,
    event={type="key", payload={key="enter", mods="", consumed_mods="", text="\r",
        unshifted_codepoint=13, composing=false, action="press"}}})
if not ok then finish("enter_call_failed", true); return end
emit({event="ack", stage="enter"})
finish()
