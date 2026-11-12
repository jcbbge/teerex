-- Fixed code, JSON arguments. One attached connection, no focus lookup or input clearing.
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
emit({event="attempt", stage="paste"})
local ok = rex.call("block.event", paste)
if not ok then emit({event="failed", reason="paste_call_failed"}); return end
emit({event="ack", stage="paste"})
emit({event="attempt", stage="enter"})
ok = rex.call("block.event", {
    session_id=a.session_id, block_id=a.block_id,
    event={type="key", payload={key="enter", mods="", consumed_mods="", text="\r",
        unshifted_codepoint=13, composing=false, action="press"}},
})
if not ok then emit({event="failed", reason="enter_call_failed"}); return end
emit({event="ack", stage="enter"})
emit({event="finished"})
