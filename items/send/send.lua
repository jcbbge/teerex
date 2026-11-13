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
local function key(name, mods, text, codepoint)
    return rex.call("block.event", {session_id=a.session_id, block_id=a.block_id,
        event={type="key", payload={key=name, mods=mods, consumed_mods="", text=text,
            unshifted_codepoint=codepoint, composing=false, action="press"}}})
end
local function paste_text(text)
    return rex.call("block.event", {session_id=a.session_id, block_id=a.block_id,
        event={type="paste", payload={text=text}}})
end
local function deliver()
    emit({event="attempt", stage="paste"})
    local ok = rex.call("block.event", paste)
    if not ok then emit({event="failed", reason="paste_call_failed"}); rex.stop(); return end
    emit({event="ack", stage="paste"})
    emit({event="attempt", stage="enter"})
    ok = key("enter", "", "\r", 13)
    if not ok then emit({event="failed", reason="enter_call_failed"}); rex.stop(); return end
    emit({event="ack", stage="enter"})
    if saved ~= "" then
        rex.sleep(.4)
        draft.restored = not not paste_text(saved)
        rex.sleep(.05)
        draft.restore_verified = draft.restored and read_draft() == saved
        report("restored")
        if not draft.restore_verified then emit({event="failed", reason="draft_restore_unverified"}); rex.stop(); return end
    end
    emit({event="finished"})
    rex.stop()
end
if a.draft_mode == "ignore" then report("ready"); deliver(); return end
local poll_timer, quiet_timer, bound_timer
local function proceed(bound)
    for _, timer in pairs({poll_timer, quiet_timer, bound_timer}) do timer:cancel() end
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
            if not key("u", "ctrl", "u", 117) then report("cleared"); refuse("draft_clear_call_failed"); rex.stop(); return end
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
    local current = read_draft()
    if current == nil then refuse("draft_capture_unavailable"); rex.stop(); return end
    if current == "" then proceed(false); return end
    if current ~= saved then
        saved = current
        quiet_timer:cancel()
        quiet_timer = rex.after(1.5, function() proceed(false) end)
    end
end)
