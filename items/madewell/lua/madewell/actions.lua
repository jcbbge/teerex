-- Server-side action for Made Well questions. Rex shows rex.ui prompts only from an action
-- run by the server (init.lua), not from a `rex do` script, so the library asks through
-- `rex do madewell_ui`. Load it from init.lua: dofile("<item>/lua/madewell/actions.lua").
rex.action {
  name = "madewell_ui",
  title = "Made Well question",
  description = "Ask Josh one question for a Made Well call and return the answer.",
  category = "Made Well",
  args = { method = "string", options = "object" },
  run = function(_, args)
    if type(rex.ui) ~= "table" or type(rex.ui[args.method]) ~= "function" then
      return { reason = "unsupported", detail = "rex.ui." .. tostring(args.method) .. " is unavailable" }
    end
    local answer, reason, detail = rex.ui[args.method](args.options)
    return { answer = answer, reason = reason, detail = detail }
  end,
}
