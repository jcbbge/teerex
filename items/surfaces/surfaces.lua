-- Public Rex terminal placement and normalized geometry; no detached block or worker.
local function surface(a, emit)
    local function progress(v) if emit then emit(v) end end
    local result = {outcome="refused", creation_attempted=false, retry_safe=false,
        automatic_close=false, focus_requested=false, painted_visibility="not_assessed",
        geometry_units="window_fraction", program_readiness="not_assessed"}
    local function fail(reason) result.failure_reason=reason; return result end
    local version = rex.call("server.version")
    if type(version) ~= "table" then return fail("version_unavailable") end
    result.source={rex_version=version.rex_version,platform=version.platform,api_revision=version.api_revision}
    if type(version.api_revision) ~= "number" or version.api_revision < 10 or version.api_revision > 13 then
        return fail("unsupported_surface_api_revision")
    end
    local function locate(view, bid)
        if type(view) ~= "table" or view.session_id ~= a.session_id then return end
        local function walk(node, path)
            if type(node) ~= "table" then return end
            if node.block_id == bid then return node.rect, path end
            local s=node.split
            if s then
                for _, side in ipairs({"before","after"}) do
                    local copy={}
                    for i,p in ipairs(path) do copy[i]=p end
                    copy[#copy+1]={split_id=s.split_id,direction=s.direction,ratio=s.ratio,side=side,rect=node.rect}
                    local rect, found=walk(s[side],copy)
                    if rect then return rect,found end
                end
            end
        end
        for _,w in ipairs(view.windows or {}) do
            for _,l in ipairs(w.layers or {}) do
                for _,b in ipairs(l.blocks or {}) do
                    if b.block_id == bid and b.creator_name == "com.superlogical.terminal" then
                        local rect,path=walk(l.layout,{})
                        if not rect then return end
                        return {session_id=view.session_id,revision=view.revision,block_id=bid,window_id=w.window_id,
                            layer_id=l.layer_id,layer_kind=l.kind,layer_state=l.state or "normal",layer_bounds=l.bounds,
                            rect=rect,split_path=path,label=b.label,host_id=b.host_id,
                            active_window_id=view.active_window_id,in_active_window=view.active_window_id==w.window_id,
                            focused_block_id=w.focused_block_id,zoomed_block_id=w.zoomed_block_id,
                            attached=true}, w, l
                    end
                end
            end
        end
    end
    local before=rex.call("session.view",{session_id=a.session_id})
    if type(before) ~= "table" or before.session_id ~= a.session_id then return fail("session_unavailable") end
    if a.operation == "move" then
        local previous=locate(before,a.block_id)
        local anchor=locate(before,a.anchor)
        if not previous or not anchor then return fail("move_requires_attached_terminals") end
        if a.block_id == a.anchor then return fail("move_anchor_is_source") end
        if previous.layer_state ~= "normal" or anchor.layer_state ~= "normal" or anchor.layer_kind ~= "tiled" then
            return fail("move_requires_normal_source_and_tiled_anchor")
        end
        if previous.zoomed_block_id or anchor.zoomed_block_id then return fail("move_refuses_zoomed_window") end
        if not a.focus and previous.focused_block_id == a.block_id then return fail("focused_source_move_requires_focus_yes") end
        result.previous=previous
        result.previous_anchor=anchor
        result.control_attempted=true
        result.outcome="uncertain"
        progress({event="attempt"})
        local before_side=a.direction=="left" or a.direction=="up"
        local axis=(a.direction=="left" or a.direction=="right") and "horizontal" or "vertical"
        local side=before_side and "before" or "after"
        local ratio=before_side and a.ratio or 1-a.ratio
        local receipt=rex.call("session.move_block",{session_id=a.session_id,block_id=a.block_id,
            anchor_block_id=a.anchor,direction=axis,side=side,ratio=ratio})
        if type(receipt) ~= "table" or type(receipt.created_split_id) ~= "string" then return fail("move_receipt_unavailable") end
        result.control_acknowledged=true
        result.move_receipt=receipt
        if a.focus then
            local focused=rex.call("session.focus_block",{session_id=a.session_id,block_id=a.block_id})
            if type(focused) ~= "table" then return fail("move_focus_receipt_unavailable") end
            result.focus_acknowledged=true
        end
        local after=rex.call("session.view",{session_id=a.session_id})
        if type(after) ~= "table" or after.session_id ~= a.session_id then return fail("move_readback_unavailable") end
        result.actual=locate(after,a.block_id)
        local current_anchor=locate(after,a.anchor)
        local actual=result.actual
        local p=actual and actual.split_path[#actual.split_path]
        local q=current_anchor and current_anchor.split_path[#current_anchor.split_path]
        local matches=actual and p and q and p.split_id==receipt.created_split_id and q.split_id==p.split_id and
            p.side==side and q.side~=side and p.direction==axis and math.abs(p.ratio-ratio)<0.000001 and
            actual.window_id==anchor.window_id and actual.layer_id==anchor.layer_id and
            actual.host_id==previous.host_id and actual.label==previous.label
        if actual and p then actual.pane_share=p.side=="before" and p.ratio or 1-p.ratio end
        if a.focus then
            matches=matches and actual.in_active_window and actual.focused_block_id==a.block_id
        else
            matches=matches and before.active_window_id==after.active_window_id
            for _,w in ipairs(after.windows or {}) do
                for _,old in ipairs(before.windows or {}) do
                    if w.window_id==old.window_id and w.focused_block_id~=old.focused_block_id then matches=false end
                end
            end
        end
        result.requested_geometry_verified=not not matches
        result.outcome=matches and "moved_and_verified" or "geometry_mismatch"
        if not matches then result.failure_reason="move_geometry_or_focus_not_verified" end
        return result
    end
    if a.operation == "focus" or a.operation == "close" then
        local previous=locate(before,a.block_id)
        if not previous then return fail("pane_not_attached_terminal") end
        if a.operation == "focus" and previous.layer_state ~= "normal" then return fail("pane_layer_not_normal") end
        result.previous=previous
        result.control_attempted=true
        result.outcome="uncertain"
        progress({event="attempt"})
        local receipt
        if a.operation == "focus" then
            receipt=rex.call("session.focus_block",{session_id=a.session_id,block_id=a.block_id})
        else
            receipt=rex.call("block.close",{session_id=a.session_id,block_id=a.block_id,keep_last=false})
        end
        if type(receipt) ~= "table" or type(receipt.revision) ~= "number" then return fail("control_receipt_unavailable") end
        result.control_acknowledged=true
        local after=rex.call("session.view",{session_id=a.session_id})
        if type(after) ~= "table" or after.session_id ~= a.session_id then return fail("control_readback_unavailable") end
        result.actual=locate(after,a.block_id)
        if a.operation == "focus" then
            if not result.actual or not result.actual.in_active_window or result.actual.focused_block_id ~= a.block_id then
                return fail("focus_not_verified")
            end
            result.outcome="focused_and_verified"
        else
            local blocks=rex.call("session.list_blocks",{session_id=a.session_id})
            if type(blocks) ~= "table" or type(blocks.blocks) ~= "table" then return fail("closed_block_list_unavailable") end
            for _, b in ipairs(blocks.blocks) do if b.block_id == a.block_id then return fail("closed_block_still_listed") end end
            if result.actual then return fail("closed_pane_still_attached") end
            result.block_absence_verified=true
            result.outcome="closed_and_absent"
        end
        return result
    end
    if a.operation == "inspect" then
        result.actual=locate(before,a.block_id)
        if not result.actual then return fail("pane_not_attached_terminal") end
        result.outcome="inspected"
        return result
    end
    local anchor
    if a.layout ~= "tab" then
        anchor=locate(before,a.anchor)
        if not anchor then return fail("anchor_not_attached_terminal") end
        if anchor.layer_state ~= "normal" then return fail("anchor_layer_not_normal") end
        if a.layout == "tiled" and anchor.layer_kind ~= "tiled" then return fail("anchor_not_tiled") end
    end
    local options={command=a.argv,exit={on_completion=false}}
    if a.cwd then options.cwd=a.cwd end
    local layout={block={flavor="com.superlogical.terminal.shell",label=a.label,options=options}}
    local method,params
    if a.layout == "tab" then
        method="session.new_window"
        params={session_id=a.session_id,window_label=a.label,focus=false,layout=layout}
    elseif a.layout == "float" then
        method="session.new_layer"
        params={session_id=a.session_id,window_id=anchor.window_id,bounds=a.bounds,focus=false,layout=layout}
    else
        local before_side=a.direction=="left" or a.direction=="up"
        method="session.new_split"
        params={session_id=a.session_id,anchor_id=a.anchor,focus=false,layout=layout,
            direction=(a.direction=="left" or a.direction=="right") and "horizontal" or "vertical",
            side=before_side and "before" or "after",ratio=before_side and a.ratio or 1-a.ratio}
    end
    if #rex.json.encode({jsonrpc="2.0",id=1,method=method,params=params}) > 60000 then
        return fail("encoded_surface_exceeds_limit")
    end
    result.creation_attempted=true
    progress({event="attempt"})
    local made=rex.call(method,params)
    result.outcome="uncertain"
    if type(made) ~= "table" or type(made.block_ids) ~= "table" or #made.block_ids ~= 1 then
        return fail("creation_receipt_unavailable")
    end
    result.created={block_id=made.block_ids[1],window_id=made.window_id,layer_id=made.layer_id,revision=made.revision}
    progress({event="created",created=result.created})
    local after=rex.call("session.view",{session_id=a.session_id})
    result.actual=locate(after,made.block_ids[1])
    local actual=result.actual
    if not actual then return fail("created_geometry_unavailable") end
    local function near(x,y) return type(x)=="number" and math.abs(x-y)<0.000001 end
    local function rect_equal(x,y)
        if type(x)~="table" or type(y)~="table" then return false end
        for i=1,4 do if not near(x[i],y[i]) then return false end end
        return true
    end
    local matches=actual.label==a.label and actual.layer_state=="normal"
    if a.layout=="tab" then
        matches=matches and actual.window_id==made.window_id and actual.layer_kind=="tiled" and rect_equal(actual.rect,{0,0,1,1})
    elseif a.layout=="float" then
        matches=matches and actual.window_id==anchor.window_id and actual.layer_id==made.layer_id and
            actual.layer_kind=="floating" and rect_equal(actual.layer_bounds,a.bounds) and rect_equal(actual.rect,a.bounds)
    else
        local p=actual.split_path[#actual.split_path]
        local current_anchor=locate(after,a.anchor)
        local q=current_anchor and current_anchor.split_path[#current_anchor.split_path]
        matches=matches and p~=nil and q~=nil and p.split_id==q.split_id and p.side~=q.side and
            p.direction==params.direction and p.side==params.side and near(p.ratio,params.ratio) and
            actual.window_id==anchor.window_id and actual.layer_id==anchor.layer_id
        if p then actual.pane_share=p.side=="before" and p.ratio or 1-p.ratio end
    end
    result.requested_geometry_verified=matches
    result.outcome=matches and "created_and_verified" or "geometry_mismatch"
    if not matches then result.failure_reason="requested_geometry_not_verified" end
    return result
end
