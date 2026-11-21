local mw = require "madewell"
local defaults = require "madewell.defaults"
local args = rex.args

local function string_list(value, fallback, name)
  if value == nil then return fallback end
  if type(value) == "string" then value = assert(rex.json.decode(value)) end
  assert(type(value) == "table", name .. " must be a JSON list of strings")
  local count = 0
  for key, item in pairs(value) do
    assert(type(key) == "number" and key >= 1 and key % 1 == 0 and type(item) == "string",
      name .. " must be a JSON list of strings")
    count = count + 1
  end
  for i = 1, count do
    assert(value[i] ~= nil, name .. " must be a JSON list of strings")
  end
  return value
end

local inputs = string_list(args.inputs, { "ping" }, "inputs")
local projects = string_list(args.projects, { "demo" }, "projects")

local return_text = [[
sleep 2
printf '%s' "$1" > "$MW_RETURN.tmp" && mv "$MW_RETURN.tmp" "$MW_RETURN"
]]

local function step(name, value, span)
  return {
    name = name,
    span = span,
    body = mw.hand.cmd{ argv = { "sh", "-c", return_text, "pingpong", value } }
  }
end

local discovery = mw.fn("discovery", function(raw)
  local steps = {
    step("declared", "Answer the supplied input."),
    step("lookFirst", "The input is present in the call packet."),
    step("classify", "A reply task."),
    step("lenses", "Keep the reply simple and easy to verify."),
    step("oneThing", "Return pong."),
    step("route", "Send the reply task to delivery."),
    step("confirm", assert(rex.json.encode({ "answer " .. raw .. " with pong" })))
  }
  local outputs = mw.await_all(defaults.discovery{ steps = steps }(raw))
  return assert(rex.json.decode(outputs[#steps]))
end)

local implementation = step("implementation", "pong", "rumen")
if args.live then
  implementation.body = mw.hand.agent{
    harness = "codex",
    duty = "Reply with exactly the word pong in your final answer. Use no tools."
  }
end

local verify_pong = [[
sleep 2
# Ground/Rumen records precede arguments. Verification receives only the implementation return.
offset=$(LC_ALL=C awk '
  /^--- Received: / && $3 !~ /^span:/ {
    if ($5 == "bytes=4") {
      print offset + length($0) + 1
      found = 1
    }
    exit
  }
  { offset += length($0) + 1 }
  END { if (!found) exit 1 }
' "$MW_INPUT") || exit 1
actual=$(dd if="$MW_INPUT" bs=1 skip="$offset" count=4 2>/dev/null)
if [ "$actual" != pong ]; then
  printf '%s\n' 'Expected the implementation to return exactly pong.' >&2
  exit 1
fi
printf '%s' "$actual" > "$MW_RETURN.tmp" && mv "$MW_RETURN.tmp" "$MW_RETURN"
]]

local delivery = mw.fn("delivery", defaults.delivery{
  ground = "Use the promoted task and its project as your material.",
  rumen = "The implementation passes only if its whole return is exactly the four bytes pong.",
  steps = {
    step("ideation", "Use a one-word reply.", "ground"),
    step("planning", "Write pong and independently check the exact bytes.", "ground"),
    implementation,
    {
      name = "verification",
      span = "rumen",
      receives = function(_, previous) return previous end,
      body = mw.hand.cmd{ argv = { "sh", "-c", verify_pong } }
    }
  }
})

return mw.run{
  name = args.run or "pingpong",
  place = args.place,
  main = function()
    local discoveries = {}
    for _, raw in ipairs(inputs) do discoveries[#discoveries + 1] = discovery(raw) end
    local todos = {}
    for _, candidates in ipairs(mw.await_all(discoveries)) do mw.extend(todos, candidates) end

    local shipped = {}
    for _, task in ipairs(mw.promote(todos)) do
      for _, project in ipairs(projects) do
        shipped[#shipped + 1] = { project = project, task = task, result = delivery(task, project) }
      end
    end
    shipped = mw.await_all(shipped)
    local observation = mw.ask{ title = "What do the tab and the Activity sidebar show for this run?" }
    return { shipped = shipped, observation = observation }
  end
}
