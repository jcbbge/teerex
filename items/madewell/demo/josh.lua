-- Josh's pseudo-code, as written (REX-BRAINSTORM.md, "Corrections to the fold", 13:43 CT):
--   "var declare = declared(); var lookFirst = looked(); return [declare, lookFirst]"
--   "while raw input > todo list. while todo list > each task > shipped."
-- Run: mw demo/josh.lua run=<name> [inputs='["ping"]' (else asked)] [projects='["demo"]'] [live=true] [auto=true]
local mw = require "madewell"
local args = rex.args

local function list(value, fallback)
  if value == nil then return fallback end
  if type(value) == "string" then value = assert(rex.json.decode(value)) end
  return value
end

-- A hand that answers from its packet: the last received input is the raw text.
local function hand(script)
  return mw.hand.cmd{ argv = { "sh", "-c", "sleep 2\n" .. script ..
    '\n} > "$MW_RETURN.tmp" && mv "$MW_RETURN.tmp" "$MW_RETURN"' } }
end
local last = [[raw=$(awk '/^--- Received: /{body=""; next} {body = body (body=="" ? "" : "\n") $0} END{printf "%s", body}' "$MW_INPUT")
{ ]]

local declared = mw.fn("declared", hand(last .. [[printf 'answer %s with pong' "$raw"]]))
local looked   = mw.fn("looked",   hand(last .. [[printf 'looked first: the input is "%s"' "$raw"]]))

local implementation = mw.fn("implementation", args.live
  and mw.hand.agent{ harness = "codex",
    duty = "Reply with exactly the word pong and nothing else in your final answer. Use no tools." }
  or hand(last .. "printf pong"))
local verification = mw.fn("verification", hand(last .. [[
  [ "$(printf '%s' "$raw" | tr -d '[:space:]')" = pong ] || { echo "not pong: $raw" >&2; exit 1; }
  printf 'shipped: verified pong']]))

-- discovery(): independent calls, returned together.
local discovery = mw.fn("discovery", function(input)
  local declare = declared(input)
  local lookFirst = looked(input)
  return { declare, lookFirst }
end)

-- delivery(): one task to shipped. The maker never verifies its own work.
local delivery = mw.fn("delivery", function(task, project)
  local made = implementation(task, project)
  return verification(made)
end)

return mw.run{ name = args.run or "josh", place = args.place, main = function()
  local raw, projects = list(args.inputs, nil), list(args.projects, { "demo" })
  if raw == nil then                                 -- capture: Josh types the raw input
    raw = { mw.ask{ title = "Raw input?", value = "ping", confirm = "Start", timeout = 3600 } }
  end

  local found = {}                                   -- while raw input > todo list
  while #raw > 0 do found[#found + 1] = discovery(table.remove(raw, 1)) end
  local todos = {}
  for _, d in ipairs(mw.await_all(found)) do todos[#todos + 1] = d[1] end

  todos = mw.promote(todos, { title = "Promote to tasks?", auto = args.auto, timeout = 3600 })
  local shipped = {}                                 -- while todo list > each task > shipped
  while #todos > 0 do
    local task = table.remove(todos, 1)
    for _, project in ipairs(projects) do
      shipped[#shipped + 1] = { project = project, task = task, result = delivery(task, project) }
    end
  end
  shipped = mw.await_all(shipped)
  local seen = nil
  if not args.auto then
    print("\nShipped. Look at this tab's marks and the Activity sidebar, then answer the prompt in a few words.")
    seen = mw.ask{ title = "What do the marks show?", timeout = 3600 }
  end
  return { shipped = shipped, seen = seen }
end }
