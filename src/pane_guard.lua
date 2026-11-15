-- Ownership is a written rule. Only the pane labelled seat, and its tab, are guarded.
do
 local call=rex.call
 rex.call=function(method,p)
  p=p or {}
  if method=='block.close' or method=='session.move_block' or method=='session.detach_block'
   or method=='session.close_window' or method=='session.close_layer' or method=='session.destroy' then
   local attached,attach_err=call('session.attach',{session_id=p.session_id})
   if attach_err then error(attach_err,0) end
   local view,err=call('session.view',{session_id=p.session_id})
   if err then error(err,0) end
   for _,w in ipairs(view.windows or {}) do
    local seat=false
    for _,l in ipairs(w.layers or {}) do for _,b in ipairs(l.blocks or {}) do
     if b.label=='seat' then seat=true end
    end end
    if seat then
     for _,l in ipairs(w.layers or {}) do for _,b in ipairs(l.blocks or {}) do
      local label=b.label
      if label=='seat' and
       (method=='session.destroy' or p.block_id==b.block_id or
        p.window_id==w.window_id or p.layer_id==l.layer_id) then
       error('seat_tab_label_protected: '..label,0)
      end
     end end
    end
   end
  end
  return call(method,p)
 end
end
