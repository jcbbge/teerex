local mw = require "madewell"
local defaults = {}

local discovery_steps = { "declared", "lookFirst", "classify", "lenses", "oneThing", "route", "confirm" }
local delivery_steps = {
  { name = "ideation", span = "ground" },
  { name = "planning", span = "ground" },
  { name = "implementation", span = "rumen" },
  { name = "verification", span = "rumen" }
}

-- Duties follow the composition and effort guidance in Made Well's FOUNDATION.md.
local duties = {
  declared = "State the intended outcome and scope. Retain uncertainty in the raw input.",
  lookFirst = "Inspect the actual relevant material and resources. Report what is available or missing.",
  classify = "Classify the work described by the input and preserve anything still unclear.",
  lenses = "Consider developer experience, user experience, and agentic experience.",
  oneThing = "State the single outcome that should guide the task list.",
  route = "Identify the appropriate owner or delivery path for each candidate.",
  confirm = "Clarify intent and propose candidate tasks. Return a JSON list of task strings.",
  ideation = "Relate the desired outcome and possible approaches to the actual material.",
  planning = "Plan the chosen work against the scope, resources, and acceptance conditions.",
  implementation = "Carry out the settled brief and return the result with its evidence.",
  verification = "Independently check the implementation result against the acceptance conditions and report the evidence."
}

function defaults.ground(fn, material)
  return function(...)
    return mw.span("ground", material, fn, ...)
  end
end

function defaults.rumen(fn, rules)
  return function(...)
    return mw.span("rumen", rules, fn, ...)
  end
end

local function compile(opts, names)
  local steps = {}
  local effort = opts.effort
  if type(effort) == "table" then effort = assert(rex.json.encode(effort)) end
  for i, spec in ipairs(opts.steps or names) do
    if type(spec) == "string" then spec = { name = spec } end
    local name = assert(spec.name, "step requires a name")
    local body = spec.body
    if body == nil then
      local duty = assert(spec.duty or duties[name], "step " .. name .. " requires a body or duty")
      if effort ~= nil then
        duty = duty .. "\nAdjust the depth of your work to this effort setting: " .. tostring(effort)
      end
      body = mw.hand.agent{
        harness = spec.harness or opts.harness or "codex",
        model = spec.model or opts.model,
        duty = duty,
        label = spec.label
      }
    end
    local call = mw.fn(name, body)
    if spec.span == "ground" and opts.ground ~= nil then
      call = defaults.ground(call, opts.ground)
    elseif spec.span == "rumen" and opts.rumen ~= nil then
      call = defaults.rumen(call, opts.rumen)
    end
    steps[i] = { name = name, call = call, receives = spec.receives }
  end
  return steps
end

function defaults.discovery(opts)
  local steps = compile(opts or {}, discovery_steps)
  return function(...)
    local outputs, by_name = {}, {}
    for i, step in ipairs(steps) do
      if step.receives then
        outputs[i] = step.call(step.receives(by_name, outputs[i - 1], ...))
      else
        outputs[i] = step.call(...)
      end
      by_name[step.name] = outputs[i]
    end
    return outputs
  end
end

function defaults.delivery(opts)
  local steps = compile(opts or {}, delivery_steps)
  return function(...)
    local by_name, previous = {}, nil
    for i, step in ipairs(steps) do
      if step.receives then
        previous = step.call(step.receives(by_name, previous, ...))
      elseif i == 1 then
        previous = step.call(...)
      else
        previous = step.call(previous, ...)
      end
      by_name[step.name] = previous
    end
    if #steps == 0 then return (...) end
    return previous
  end
end

return defaults
