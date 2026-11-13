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
if not terminal then refuse("target_not_visible_terminal"); return end
local paste = {session_id=a.session_id, block_id=a.block_id, event={type="paste", payload={text=a.text}}}
-- Rex preview.16 caps control messages at 65536 bytes. Use Rex's own encoder,
-- not raw text length: quotes, LF and HTML characters can expand. Leave >5 KiB
-- for the actual protocol envelope/ID; this is not a maximum-throughput claim.
local n = #rex.json.encode({jsonrpc="2.0", id=1, method="block.event", params=paste})
emit({event="preflight", encoded_rpc_bytes=n})
if n > 60000 then refuse("encoded_paste_exceeds_limit"); return end
local draft = {mode=a.draft_mode, detected=false, chars=0, waited_ms=0, bound_reached=false}
local saved = ""
local function report(stage)
    emit({event="draft", stage=stage, draft=draft})
end
local function read_draft()
    local capture = rex.call("com.superlogical.terminal.format", {
        session_id=a.session_id, block_id=a.block_id, args={format="vt"},
    })
    if type(capture) ~= "table" then return nil end
    local text = capture.text or capture.content
    if type(text) ~= "string" or #text > 1048576 then return nil end
    return draft_from_vt(text)
end
-- Cooperative state is local to the command/Rex host. No server input lease is implied.
local clutch = {state="unknown", held_observed=false, waited_ms=0, bound_reached=false}
local clutch_reason
local function gate()
    local function unknown(reason)
        clutch.state, clutch.failure_reason = "unknown", reason
        emit({event="clutch", clutch=clutch})
        return true
    end
    if type(a.clutch_file) ~= "string" then
        return unknown(type(a.clutch_failure) == "string" and a.clutch_failure or "clutch_state_unavailable")
    end
    while true do
        local f = io.open(a.clutch_file, "r")
        local held = false
        if f then
            local raw = f:read(8193); f:close()
            local ok, state = pcall(rex.json.decode, raw)
            if not ok or type(state) ~= "table" or type(state.held) ~= "boolean" or #raw > 8192 then
                return unknown("clutch_state_invalid")
            end
            held = state.held
        else
            return unknown("clutch_state_unreadable")
        end
        clutch.state, clutch.failure_reason = held and "held" or "released", nil
        if not held then emit({event="clutch", clutch=clutch}); return true end
        clutch.held_observed = true
        if clutch.waited_ms >= a.draft_wait_ms then
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
local function input_failure(reason)
    refuse(clutch_reason or reason)
    rex.stop()
end
local function key(name, mods, text, codepoint)
    if not gate() then return false end
    return rex.call("block.event", {session_id=a.session_id, block_id=a.block_id,
        event={type="key", payload={key=name, mods=mods, consumed_mods="", text=text,
            unshifted_codepoint=codepoint, composing=false, action="press"}}})
end
local function paste_text(text)
    if not gate() then return false end
    return rex.call("block.event", {session_id=a.session_id, block_id=a.block_id,
        event={type="paste", payload={text=text}}})
end
local function deliver()
    if not gate() then input_failure("clutch_state_unavailable"); return end
    emit({event="attempt", stage="paste"})
    local ok = rex.call("block.event", paste)
    if not ok then emit({event="failed", reason="paste_call_failed"}); rex.stop(); return end
    emit({event="ack", stage="paste"})
    emit({event="attempt", stage="enter"})
    ok = key("enter", "", "\r", 13)
    if not ok then
        if clutch_reason then input_failure(clutch_reason) else emit({event="failed", reason="enter_call_failed"}); rex.stop() end
        return
    end
    emit({event="ack", stage="enter"})
    if saved ~= "" then
        rex.sleep(.4)
        local acknowledged = not not paste_text(saved)
        draft.restored, draft.restore_verified = false, false
        local verify_timer, restore_bound, complete
        local function finish_restore(warning)
            if complete then return end
            complete = true
            report("restored")
            if warning then emit({event="warning", reason=warning}) end
            -- Restoration cannot undo the already acknowledged message/Enter.
            emit({event="finished"})
            -- Cancelling the last active timer can end rex do immediately.
            -- Publish every final frame before relinquishing those timers.
            if verify_timer then verify_timer:cancel() end
            if restore_bound then restore_bound:cancel() end
            rex.stop()
        end
        if not acknowledged then finish_restore(clutch_reason or "draft_restore_failed"); return end
        local function verify(final)
            if read_draft() == saved then
                draft.restored, draft.restore_verified = true, true
                finish_restore(nil)
            elseif final then
                finish_restore("draft_restore_unverified")
            end
        end
        verify_timer = rex.every(.1, function() verify(false) end)
        restore_bound = rex.after(1.5, function() verify(true) end)
        return
    end
    emit({event="finished"})
    rex.stop()
end
if not gate() then input_failure("clutch_state_unavailable"); return end
if a.draft_mode == "ignore" then report("ready"); deliver(); return end
local poll_timer, quiet_timer, bound_timer
local proceeding = false
local function proceed(bound)
    if proceeding then return end
    proceeding = true
    -- Keep the polling timer alive until final publication; rex.stop owns teardown.
    if not gate() then input_failure("clutch_state_unavailable"); return end
    local current = read_draft()
    if current == nil then refuse("draft_capture_unavailable"); rex.stop(); return end
    saved = current
    draft.detected = draft.detected or saved ~= ""
    draft.chars = select(2, saved:gsub("[^\128-\191]", ""))
    draft.bound_reached = bound or false
    report("ready")
    if saved ~= "" then
        local restore = {session_id=a.session_id, block_id=a.block_id, event={type="paste", payload={text=saved}}}
        if #rex.json.encode({jsonrpc="2.0", id=1, method="block.event", params=restore}) > 60000 then
            refuse("encoded_draft_restore_exceeds_limit"); rex.stop(); return
        end
        draft.cleared = false
        for _ = 1, 2 do
            if not key("u", "ctrl", "u", 117) then report("cleared"); refuse(clutch_reason or "draft_clear_call_failed"); rex.stop(); return end
            rex.sleep(.05)
            local remaining = read_draft()
            if remaining == "" then draft.cleared = true; break end
        end
        report("cleared")
        if not draft.cleared then refuse("draft_not_cleared"); rex.stop(); return end
    end
    deliver()
end
saved = read_draft()
if saved == nil then refuse("draft_capture_unavailable"); return end
if saved == "" then report("ready"); deliver(); return end
draft.detected = true
report("waiting")
if a.draft_wait_ms == 0 then proceed(true); return end
bound_timer = rex.after(a.draft_wait_ms / 1000, function() proceed(true) end)
quiet_timer = rex.after(1.5, function() proceed(false) end)
poll_timer = rex.every(.25, function()
    if proceeding then return end
    local current = read_draft()
    if current == nil then refuse("draft_capture_unavailable"); rex.stop(); return end
    if current == "" then proceed(false); return end
    if current ~= saved then
        saved = current
        quiet_timer:cancel()
        quiet_timer = rex.after(1.5, function() proceed(false) end)
    end
end)
