-- One connection, explicit target, fixed source. No detached intermediate block.
local a = rex.args
local function emit(v) io.write(rex.json.encode(v), "\n"); io.flush() end
local function refuse(reason) emit({event="refused", reason=reason}) end
local v = rex.call("server.version")
if type(v) ~= "table" then refuse("version_unavailable"); return end
emit({event="source", source={rex_version=v.rex_version, platform=v.platform, api_revision=v.api_revision}})
if type(v.api_revision) ~= "number" or v.api_revision % 1 ~= 0 or v.api_revision < 10 or v.api_revision > 13 then
    refuse("unsupported_spawn_api_revision"); return
end
local view = rex.call("session.view", {session_id=a.session_id})
if type(view) ~= "table" or view.session_id ~= a.session_id then refuse("target_unavailable"); return end
local parent = view
if a.report_session ~= a.session_id then
    -- The Lua control stream joins only its creation session by default.
    -- Join the explicitly supplied report session before reading its attached view.
    local attached = rex.call("session.attach", {session_id=a.report_session})
    if type(attached) ~= "table" then refuse("report_session_attach_failed"); return end
    parent = attached.view
end
local report_found = false
if type(parent) == "table" and parent.session_id == a.report_session then
    for _, w in ipairs(parent.windows or {}) do
        for _, l in ipairs(w.layers or {}) do
            for _, b in ipairs(l.blocks or {}) do
                if b.block_id == a.report_block and b.creator_name == "com.superlogical.terminal" then report_found = true end
            end
        end
    end
end
if not report_found then refuse("report_target_not_attached_terminal"); return end
-- Positional parameters preserve argv, quotes, empty arguments and Unicode.
-- The cwd is on the terminal host; never validate it on the CLI host instead.
local shim = [[
cd -- "$1" || exit 125
export AGENT_SESSION="$REX_SESSION" AGENT_PANE="$REX_BLOCK"
export LC_REX_SESSION="$REX_SESSION" LC_REX_BLOCK="$REX_BLOCK"
export AGENT_NAME="$2" LC_AGENT_NAME="$2"
export AGENT_REPORT_TO="$3" LC_AGENT_REPORT_TO="$3"
shift 3
exec "$@"
]]
local command = {"sh", "-c", shim, "teerex-spawn", a.cwd, a.name, a.report_session .. " " .. a.report_block}
for _, arg in ipairs(a.argv) do command[#command+1] = arg end
local params = {session_id=a.session_id, window_label=a.name, focus=false,
    layout={block={flavor="com.superlogical.terminal.shell", label=a.name,
        options={command=command, cwd=a.cwd, exit={on_completion=false}}}}}
-- Reserve protocol space and account for Rex's actual encoder expansion.
if #rex.json.encode({jsonrpc="2.0",id=1,method="session.new_window",params=params}) > 60000 then
    refuse("encoded_spawn_exceeds_limit"); return
end
emit({event="attempt"})
local made = rex.call("session.new_window", params)
if type(made) ~= "table" or type(made.window_id) ~= "string" or type(made.block_ids) ~= "table" or
    #made.block_ids ~= 1 or type(made.block_ids[1]) ~= "string" or type(made.revision) ~= "number" then
    emit({event="failed", reason="creation_receipt_unavailable"}); return
end
emit({event="created", created={window_id=made.window_id,block_id=made.block_ids[1],revision=made.revision}})
local after = rex.call("session.view", {session_id=a.session_id})
if type(after) == "table" and after.session_id == a.session_id then
    for _, w in ipairs(after.windows or {}) do
        if w.window_id == made.window_id then
            for _, l in ipairs(w.layers or {}) do
                for _, b in ipairs(l.blocks or {}) do
                    if b.block_id == made.block_ids[1] and b.creator_name == "com.superlogical.terminal" then
                        emit({event="verified"}); return
                    end
                end
            end
        end
    end
end
emit({event="failed", reason="created_location_not_verified"})
