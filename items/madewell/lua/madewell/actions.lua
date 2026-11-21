-- Server-side action for Made Well questions. Rex shows rex.ui prompts only from an action
-- run by the server (init.lua), not from a `rex do` script, so the library asks through
-- `rex do madewell_ui`. Load it from init.lua: dofile("<item>/lua/madewell/actions.lua").
-- Josh's palette shows one line per field (2026-11-20 20:24 CT: "the text is cut off because the popup
-- is too small"), so a prompt carries only a short question and short option titles; anything longer
-- belongs in the asking pane. Same limits as rexconfig's ask.lua.
local function short(text, n)
  text = tostring(text or ""):gsub("%s+", " "):gsub("^ ", ""):gsub(" $", "")
  if #text <= n then return text end
  return text:sub(1, n - 1):gsub("[\128-\191]+$", ""):gsub("[\192-\255]$", "") .. "…"
end

local function readable(options)
  local o = {}
  for k, v in pairs(options) do o[k] = v end
  o.title = short(o.title, 70)
  o.placeholder, o.confirm = o.placeholder and short(o.placeholder, 40), o.confirm and short(o.confirm, 24)
  if type(o.items) == "table" then
    local items = {}
    for i, item in ipairs(o.items) do
      if type(item) == "table" then
        items[i] = { id = item.id, title = short(item.title or item.id, 60), icon = item.icon, selected = item.selected }
      else
        items[i] = { id = item, title = short(item, 60) }
      end
    end
    o.items = items
  end
  return o
end

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
    local answer, reason, detail = rex.ui[args.method](readable(args.options))
    return { answer = answer, reason = reason, detail = detail }
  end,
}
