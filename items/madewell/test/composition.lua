local args = rex.args
local calls, spans = {}, {}
local bad_reply
local mw = { hand = require "madewell.hands" }
package.preload.madewell = function() return mw end

local function write(path, bytes)
  local file = assert(io.open(path, "wb"))
  assert(file:write(bytes))
  assert(file:close())
end

local function read(path)
  local file = assert(io.open(path, "rb"))
  local bytes = file:read("*a")
  assert(file:close())
  return bytes
end

local function packet(name, bytes)
  return ("\n--- Received: %s sha256=%s bytes=%d ---\n%s"):format(name, string.rep("0", 64), #bytes, bytes)
end

function mw.fn(name, body)
  return function(...)
    calls[#calls + 1] = { name = name, body = body, args = {...}, span = spans[#spans] }
    if type(body) == "function" then return body(...) end
    if not rex.args.demo then return name end
    local text = body.duty or ""
    for _, span in ipairs(spans) do text = text .. packet("span:" .. span.name, span.material) end
    for i, value in ipairs({...}) do text = text .. packet("arg." .. i, value) end
    local input, output = args.dir .. "/packet", args.dir .. "/answer"
    write(input, text)
    os.remove(output)
    if name == "implementation" and bad_reply then body.argv[5] = bad_reply end
    local argv = { args.item .. "/hand" }
    for _, arg in ipairs(body.argv) do argv[#argv + 1] = arg end
    local result = assert(rex.exec(argv, { env = {
      MW_CALL = name, MW_INPUT = input, MW_RETURN = output, PATH = args.dir .. ":" .. os.getenv("PATH")
    } }))
    assert(result.ok, name .. " failed: " .. result.stderr)
    return read(output)
  end
end

function mw.span(name, material, fn, ...)
  spans[#spans + 1] = { name = name, material = material }
  local value = fn(...)
  spans[#spans] = nil
  return value
end

local defaults = require "madewell.defaults"
local discovered = defaults.discovery{ harness = "pi", model = "test-model", effort = 7 }("raw")
assert(table.concat(discovered, " ") == "declared lookFirst classify lenses oneThing route confirm")
for _, call in ipairs(calls) do
  assert(#call.args == 1 and call.args[1] == "raw")
  assert(call.body.argv[5] == "pi" and call.body.argv[#call.body.argv] == "test-model")
  assert(call.body.duty:find("effort setting: 7", 1, true))
end

calls = {}
local delivered = defaults.delivery{ ground = "actual material", rumen = "rules" }("task", "project")
assert(delivered == "verification" and #calls == 4)
assert(calls[1].args[1] == "task" and calls[1].args[2] == "project")
assert(calls[2].args[1] == "ideation" and calls[3].args[1] == "planning")
assert(calls[4].args[1] == "implementation" and calls[4].args[2] == "task")
assert(calls[1].span.material == "actual material" and calls[2].span.name == "ground")
assert(calls[3].span.material == "rules" and calls[4].span.name == "rumen")
assert(calls[3].body ~= calls[4].body)

local wired = defaults.discovery{ steps = {
  "declared",
  { name = "confirm", receives = function(out) return out.declared end }
} }
wired("input")
assert(calls[#calls].args[1] == "declared")
assert(#defaults.discovery{ steps = {} }("none") == 0)
assert(defaults.delivery{ steps = {} }("none") == "none")
local steps = {}
local step = { name = "custom", body = function() return "value" end }
for i = 1, 1000 do steps[i] = step end
assert(#defaults.discovery{ steps = steps }("raw") == 1000)
assert(defaults.delivery{ steps = steps }("raw") == "value")

function mw.run(opts) return opts.main() end
function mw.await_all(list) return list end
function mw.extend(list, values)
  for _, value in ipairs(values) do list[#list + 1] = value end
end
function mw.promote(todos) return todos end
function mw.ask(opts)
  assert(opts.title == "What do the tab and the Activity sidebar show for this run?")
  assert(calls[#calls].name == "verification")
  return "observed"
end

local function demo(overrides, expected)
  calls = {}
  rex.args = overrides
  rex.args.demo = true
  local result = dofile(args.item .. "/demo/pingpong.lua")
  assert(result.observation == "observed" and #result.shipped == expected)
  for _, shipped in ipairs(result.shipped) do assert(shipped.result == "pong") end
  return result.shipped
end
local single = demo({}, 1)
assert(single[1].task == "answer ping with pong" and single[1].project == "demo")
local multi = demo({ inputs = {"ping", "héllo"}, projects = {"one", "two"} }, 4)
assert(multi[2].task == "answer ping with pong" and multi[2].project == "two")
assert(multi[3].task == "answer héllo with pong" and multi[3].project == "one")
for _, bad in ipairs({ "pang", "pong\n" }) do
  bad_reply = bad
  local ok, err = pcall(demo, {}, 1)
  assert(not ok and err:find("verification failed", 1, true))
  spans = {}
end
return "PASS defaults and demo against the core API contract"
