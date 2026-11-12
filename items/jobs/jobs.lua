-- Explicit foreground operations only. No launches, detach, close, own or input calls.
local a = rex.args
local function emit(v) io.write(rex.json.encode(v), "\n"); io.flush() end
local function call(method, args)
    local v, err = rex.call(method, args)
    if not v then error(err) end
    if #rex.json.encode(v) > 131072 then error("response_exceeds_128KiB") end
    return v
end
local function refuse(reason) emit({event="refused", reason=reason}) end
local version = call("server.version")
local status = call("server.status")
if version.api_revision ~= 13 or (version.platform ~= "darwin_arm64" and version.platform ~= "linux_amd64") then
    refuse("jobs_requires_API13_Mac_arm64_or_Linux_amd64"); return
end
if type(status.instance_id) ~= "string" or #status.instance_id == 0 or
    type(status.host_id) ~= "string" or #status.host_id == 0 then error("missing_identity") end
local source = {rex_version=version.rex_version, api_revision=version.api_revision, platform=version.platform,
    instance_id=status.instance_id, host_id=status.host_id}
emit({event="source", source=source})
if a.instance_id and (status.instance_id ~= a.instance_id or status.host_id ~= a.host_id) then
    refuse("stale_server_identity"); return
end
local blocks = call("session.list_blocks", {session_id=a.session_id})
if type(blocks.blocks) ~= "table" then error("invalid_block_list") end
local target, anchor
for k, b in pairs(blocks.blocks) do
    if type(k) ~= "number" or k % 1 ~= 0 or k < 1 or k > #blocks.blocks or
        type(b) ~= "table" or type(b.block_id) ~= "string" then error("invalid_block_list") end
    if b.block_id == a.block_id then target = b end
    if b.block_id == a.anchor then anchor = b end
end
if not target then refuse("target_absent_at_observation"); return end
if target.creator_name ~= "com.superlogical.terminal" or type(target.host_id) ~= "string" or #target.host_id == 0 then
    refuse("target_not_identified_terminal"); return
end
if a.block_host_id and target.host_id ~= a.block_host_id then refuse("stale_block_host"); return end
local function visible(view, id)
    if view.session_id ~= a.session_id or type(view.windows) ~= "table" then error("invalid_view") end
    for _, w in ipairs(view.windows) do
        for _, l in ipairs(w.layers or {}) do
            if l.state ~= "minimized" and (not w.zoomed_block_id or w.zoomed_block_id == id) then
                for _, b in ipairs(l.blocks or {}) do
                    if b.block_id == id then return w, l end
                end
            end
        end
    end
end
local before = call("session.view", {session_id=a.session_id})
local window = visible(before, a.block_id)
local process, process_error = rex.call("com.superlogical.terminal.process", {session_id=a.session_id, block_id=a.block_id, args={}})
local exit_code
if type(process) == "table" and type(process.last_exit) == "table" then exit_code=process.last_exit.exit_code end
emit({event="observed", observation={placement=target.placement, window_id=target.window_id,
    block_host_id=target.host_id, native_owner=target.owner, visible_in_view=window ~= nil,
    last_exit_code_reported=exit_code, process_available=process ~= nil, revision=before.revision}})
if a.kind == "agent" and (target.placement ~= "placed" or not window) then
    refuse("agent_not_visible_in_view"); return
end
if a.operation ~= "present" then
    if a.operation == "adopt" and target.owner then refuse("resource_has_native_owner"); return end
    emit({event="verified"}); return
end
if target.owner then refuse("resource_has_native_owner"); return end
if not anchor or anchor.block_id == target.block_id then refuse("invalid_anchor"); return end
local anchor_window = visible(before, a.anchor)
if not anchor_window then refuse("anchor_not_visible_in_view"); return end
if anchor_window.zoomed_block_id then refuse("anchor_window_zoomed"); return end
if target.placement == "placed" then
    -- Never rearrange an already placed pane. Explicit focus/label can present it in place.
    if not window or window.window_id ~= anchor_window.window_id then
        refuse("placed_target_not_visible_in_destination"); return
    end
elseif target.placement ~= "detached" then refuse("unknown_placement"); return end
-- All refusals precede the mutation marker. Missing markers are still not dispatch proof.
emit({event="attempt"})
if target.placement == "detached" then
    call("session.move_block", {session_id=a.session_id, block_id=a.block_id, anchor_block_id=a.anchor,
        direction="horizontal", side="after", ratio=0.5})
end
if a.label then call("session.set_block_label", {session_id=a.session_id, block_id=a.block_id, label=a.label}) end
if a.focus then call("session.focus_block", {session_id=a.session_id, block_id=a.block_id}) end
local after = call("session.view", {session_id=a.session_id})
local placed = visible(after, a.block_id)
if not placed or placed.window_id ~= anchor_window.window_id then error("presentation_location_not_verified") end
if a.focus then
    if after.active_window_id ~= placed.window_id or placed.focused_block_id ~= a.block_id then
        error("requested_focus_not_verified")
    end
else
    if after.active_window_id ~= before.active_window_id then error("active_window_changed") end
    for _, old in ipairs(before.windows) do
        for _, new in ipairs(after.windows or {}) do
            if old.window_id == new.window_id and old.focused_block_id ~= new.focused_block_id then
                error("focus_changed")
            end
        end
    end
end
if a.label then
    local described = call("session.describe_block", {session_id=a.session_id, block_id=a.block_id})
    if not described.block or described.block.label ~= a.label then error("requested_label_not_verified") end
end
emit({event="verified"})
