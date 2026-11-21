local mw = { hand = require "madewell.hands" }
local source = debug.getinfo(1, "S").source:gsub("^@", "")
local wrapper = assert(source:match("^(.*)/lua/madewell%.lua$"), "cannot locate Made Well hand: " .. source) .. "/hand"
local terminal = "com.superlogical.terminal.shell"
local contexts = setmetatable({}, { __mode = "k" })
local Future = {}

local function pack(...)
  return { n = select("#", ...), ... }
end

local function identity(value)
  local kind = type(value)
  if kind == "nil" then return "nil" end
  if kind == "string" then return "s" .. #value .. ":" .. value end
  if kind == "boolean" then return tostring(value) end
  if kind == "number" then return "n" .. string.format("%.17g", value) .. ";" end
  assert(kind == "table", "cannot journal a " .. kind .. " input")
  local entries = {}
  for key, item in pairs(value) do
    assert(type(key) ~= "table", "cannot journal a table key")
    entries[#entries + 1] = identity(key) .. identity(item)
  end
  table.sort(entries)
  return "{" .. table.concat(entries) .. "}"
end

local function is_future(value)
  return getmetatable(value) == Future
end

local function context()
  return assert(contexts[coroutine.running()], "Made Well calls require mw.run")
end

local function force(future)
  if not future.done then
    assert(context().job.run == future.run, "future belongs to another run")
    coroutine.yield("await", future)
  end
  if future.reason then error(future.key .. ": " .. future.reason, 0) end
  return future.value
end

local function map_tree(value, visiting, resolve_futures)
  while is_future(value) do
    if not resolve_futures then return value end
    value = force(value)
  end
  if type(value) ~= "table" then return value end
  assert(not visiting[value], "cannot await a cyclic table")
  visiting[value] = true
  local result = {}
  for key, item in pairs(value) do result[key] = map_tree(item, visiting, resolve_futures) end
  visiting[value] = nil
  return result
end

function mw.await(value)
  return map_tree(value, {}, true)
end

function mw.await_all(list)
  return mw.await(list)
end

function mw.extend(list, items)
  for _, item in ipairs(mw.await(items)) do list[#list + 1] = item end
  return list
end

local function base64(value)
  local alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
  local parts = {}
  local function char(index) return alphabet:sub(index + 1, index + 1) end
  for i = 1, #value, 3 do
    local a, b, c = value:byte(i, i + 2)
    local bb, cc = b or 0, c or 0
    parts[#parts + 1] = char(math.floor(a / 4))
      .. char((a % 4) * 16 + math.floor(bb / 16))
      .. (b and char((bb % 16) * 4 + math.floor(cc / 64)) or "=")
      .. (c and char(cc % 64) or "=")
  end
  return table.concat(parts)
end

local function status(fields)
  io.write("\27]7501;", table.concat(fields, ":"), "\27\\")
  io.flush()
end

local function mark(job, state, message)
  local fields = { "state=" .. state, "title=" .. job.title }
  fields[#fields + 1] = job.id and "id=" .. job.id or "app=madewell"
  if state == "blocked" then fields[#fields + 1] = "kind=question" end
  if message then fields[#fields + 1] = "msg=" .. base64((message:gsub("%c", " "))) end
  status(fields)
end

local function mark_id(parent, serial)
  local path = parent.id or ""
  local segment = tostring(serial)
  local levels = parent.levels
  while levels >= 8 or #path + #segment + 1 > 128 do
    path = path:match("^(.*)/[^/]+$") or ""
    levels = levels - 1
  end
  return path ~= "" and path .. "/" .. segment or segment, levels + 1
end

local function store_call(run, method, ...)
  return run.store[method](run.store, run.name, ...)
end

local function append(job, state, sha, reason)
  store_call(job.run, "append", {
    key = job.key, fn = job.name, input_sha = job.input_sha, state = state,
    return_sha = sha, block_id = job.block_id, attempt = job.attempt, at = os.time(), reason = reason,
  })
end

local function update_mark(job)
  local message = job.message
  if job.folded > 0 then
    local counts = string.format("%d finished, %d failed", job.folded, job.failed_children)
    message = message and message .. " · " .. counts or counts
  end
  mark(job, job.state, message)
end

local function fold(job)
  update_mark(job)
  while job.future.done and job.open_children == 0 and job.parent do
    status{ "state=clear", "id=" .. job.id }
    local parent = job.parent
    parent.open_children = parent.open_children - 1
    parent.folded = parent.folded + job.folded + 1
    parent.failed_children = parent.failed_children + job.failed_children + (job.future.reason and 1 or 0)
    job = parent
    update_mark(job)
  end
end

local function settle(job, value, reason, bytes, sha)
  local future = job.future
  future.done, future.value, future.reason = true, value, reason
  future.bytes, future.sha = bytes, sha
  contexts[job.thread] = nil
  job.state, job.message = reason and "error" or "done", reason
  fold(job)
  for _, waiter in ipairs(future.waiters) do
    job.run.ready[#job.run.ready + 1] = waiter
  end
  future.waiters = nil
end

local function fail(job, reason)
  reason = tostring(reason)
  if job.attempt then append(job, "failed", nil, reason) end
  if job.parent then job.run.failed = job.run.failed + 1 end
  settle(job, nil, reason)
end

local function returned(job, bytes, value)
  local sha = store_call(job.run, "put_blob", bytes)
  append(job, "returned", sha)
  job.run.returned = job.run.returned + 1
  settle(job, value, nil, bytes, sha)
end

local function exec(argv)
  local result, reason = rex.exec(argv)
  assert(result, reason)
  assert(result.ok, argv[1] .. ": " .. result.stderr)
  return result.stdout
end

local function write_file(path, bytes)
  local file = assert(io.open(path, "wb"))
  local written, reason = file:write(bytes)
  local closed, close_reason = file:close()
  assert(written, reason)
  assert(closed, close_reason)
end

local function read_file(path)
  local file, reason = io.open(path, "rb")
  if not file then return nil, reason end
  local bytes, read_reason = file:read("*a")
  assert(file:close())
  return bytes, read_reason
end

local function hand_start(job, packet)
  local run, body = job.run, job.body
  if not run.temp then
    run.temp = (exec{ "mktemp", "-d", "-t", "madewell.XXXXXXXX" }:gsub("\n$", ""))
  end
  local prefix = run.temp .. "/" .. job.serial
  local input = prefix .. ".input"
  job.return_file = prefix .. ".return"
  write_file(input, packet)
  local command = {
    "env", "MW_CALL=" .. job.key, "MW_INPUT=" .. input, "MW_RETURN=" .. job.return_file,
  }
  -- A block starts with the Rex server's environment; a hand finds programs on its caller's PATH.
  if os.getenv("PATH") then command[#command + 1] = "PATH=" .. os.getenv("PATH") end
  command[#command + 1] = wrapper
  for _, arg in ipairs(body.argv) do command[#command + 1] = arg end
  local options = {
    shell = "none", command = command, cwd = os.getenv("HOME"), exit = { on_completion = false },
  }
  local label = body.label or job.key
  local result, reason
  if run.place == "detached" then
    result, reason = rex.session.new_block{ flavor = terminal, label = label, options = options }
  else
    local layout = rex.layout.block{ flavor = terminal, label = label, options = options }
    if run.place == "split" then
      result, reason = rex.session.new_split{ focus = false, direction = "horizontal", side = "after", layout = layout }
    else
      result, reason = rex.session.new_window{ focus = false, window_label = job.key, layout = layout }
    end
  end
  if not result then
    reason = tostring(reason)
    if reason:find("status=409", 1, true) then
      reason = reason:match('failed: (.-) %(status=409') or reason
    end
    return nil, reason
  end
  return result.block_id or result.block_ids[1]
end

local function hand_exit(job, code)
  if code ~= 0 then return fail(job, "hand exited " .. tostring(code)) end
  local bytes = read_file(job.return_file)
  if bytes == nil then return fail(job, "hand exited without a return file") end
  returned(job, bytes, bytes)
  local closed, reason = rex.call("block.close", { session_id = job.run.session_id, block_id = job.block_id })
  if not closed then rex.log("warn", "could not close " .. job.key .. ": " .. tostring(reason)) end
end

local function new_job(run, parent, key, name, body, args, spans)
  run.serial = run.serial + 1
  local job = {
    run = run, parent = parent, key = key, name = name, body = body, serial = run.serial, spans = spans,
    title = base64(key), state = "working", levels = 0, calls = {},
    open_children = 0, folded = 0, failed_children = 0,
    future = setmetatable({ key = key, run = run, waiters = {} }, Future),
  }
  if parent then
    job.id, job.levels = mark_id(parent, job.serial)
    parent.open_children = parent.open_children + 1
  end
  job.thread = coroutine.create(function()
    if not parent then return mw.await(body()) end
    local inputs = mw.await(args)
    coroutine.yield("prepare", { raw = args, resolved = inputs })
    return mw.await(body(unpack(inputs, 1, inputs.n)))
  end)
  contexts[job.thread] = { job = job, spans = spans }
  return job
end

local function define(name, body)
  return function(...)
    local scope = context()
    local parent = scope.job
    local ordinal = (parent.calls[name] or 0) + 1
    parent.calls[name] = ordinal
    local segment = name .. "." .. ordinal
    local key = parent.parent and parent.key .. "/" .. segment or segment
    local future = coroutine.yield("start", {
      key = key, name = name, body = body, args = map_tree(pack(...), {}, false), spans = scope.spans,
    })
    return future
  end
end

function mw.span(name, material, fn, ...)
  assert(type(name) == "string" and name ~= "" and not name:find("%c"), "invalid span name")
  assert(type(fn) == "function", "span body must be a Lua function")
  local scope = context()
  local value = mw.await(material)
  local bytes = type(value) == "string" and value or assert(rex.json.encode(value))
  local result = pack(coroutine.yield("span", {
    fn = fn, args = pack(...), spans = { name = name, bytes = bytes, parent = scope.spans },
  }))
  if not result[1] then error(result[2], 0) end
  return unpack(result, 2, result.n)
end

function mw.fn(name, body)
  assert(type(name) == "string" and name ~= "" and not name:find("[/%c]"), "invalid call name")
  assert(type(body) == "function" or (type(body) == "table" and body.kind == "hand" and type(body.argv) == "table"),
    "call body must be a Lua function or a hand")
  return define(name, body)
end

local ask = define("ask", { kind = "question", method = "input" })
local pick = define("pick", { kind = "question", method = "pick" })
local promote = define("promote", { kind = "question", method = "promote" })

function mw.ask(options)
  return mw.await(ask(options))
end

function mw.pick(options)
  return mw.await(pick(options))
end

function mw.promote(list, options)
  options = options or {}
  local chosen = mw.await(promote(list, options))
  if options.auto then return list end
  return chosen
end

local function return_json(job, value)
  local bytes, reason = rex.json.encode(value)
  if not bytes then return fail(job, reason) end
  returned(job, bytes, value)
end

local function question(job, args)
  local method = job.body.method
  local options, list
  if method == "promote" then
    list, options = args[1], args[2]
    if type(list) ~= "table" or type(options) ~= "table" then
      return fail(job, "promote requires a list and options")
    end
    if options.auto then return return_json(job, true) end
    options.title = options.title or "Promote"
    options.auto, options.multiple, options.items = nil, true, {}
    for i, item in ipairs(list) do
      local title = type(item) == "table" and (item.title or item.name) or nil
      options.items[i] = { id = tostring(i), title = tostring(title or (type(item) == "table" and rex.json.encode(item) or item)),
        selected = true }
    end
    method = "pick"
  else
    options = args[1]
  end
  if type(options) ~= "table" or type(options.title) ~= "string" or options.title == "" then
    return fail(job, "question title is required")
  end
  job.state, job.message = "blocked", options.title
  mark(job, job.state, job.message)
  -- Rex shows prompts only from an action the server loaded from init.lua (lua/madewell/actions.lua),
  -- not from a `rex do` script, so the question runs as `rex do madewell_ui`, which waits for the answer.
  local argv = { "rex" }
  if os.getenv("MW_REX_SERVER") then argv[#argv + 1], argv[#argv + 2] = "-S", os.getenv("MW_REX_SERVER") end
  for _, a in ipairs({ "do", "madewell_ui", "--args", rex.json.encode({ method = method, options = options }) }) do
    argv[#argv + 1] = a
  end
  local result, exec_err = rex.exec(argv)
  if not result then return fail(job, "cannot run rex do madewell_ui: " .. tostring(exec_err)) end
  if not result.ok then
    local why = (result.stderr or ""):gsub("%s+$", "")
    if why:find("no action named", 1, true) or why:find("not found", 1, true) then
      why = "the server has no madewell_ui action; load lua/madewell/actions.lua from init.lua (" .. why .. ")"
    end
    return fail(job, why ~= "" and why or ("rex do madewell_ui exited " .. tostring(result.code)))
  end
  local reply = rex.json.decode(result.stdout) or {}
  local answer, reason = reply.answer, reply.reason
  if answer == nil then return fail(job, reason or "failed") end
  if list then
    local selected = {}
    for _, id in ipairs(answer) do selected[#selected + 1] = list[tonumber(id)] end
    answer = selected
  end
  return_json(job, answer)
end

local function contains_future(value)
  if is_future(value) then return true end
  if type(value) ~= "table" then return false end
  for _, item in pairs(value) do
    if contains_future(item) then return true end
  end
  return false
end

local function ordered_spans(span)
  local spans = {}
  while span do
    spans[#spans + 1] = span
    span = span.parent
  end
  return spans
end

local function packet_for(job, args, spans)
  local parts = { job.body.duty or "" }
  local function section(path, bytes, sha)
    sha = sha or store_call(job.run, "put_blob", bytes)
    parts[#parts + 1] = string.format("\n--- Received: %s sha256=%s bytes=%d ---\n", path, sha, #bytes)
    parts[#parts + 1] = bytes
  end
  for i = #spans, 1, -1 do section("span:" .. spans[i].name, spans[i].bytes) end
  local function received(path, value)
    if type(value) == "table" and not is_future(value) and contains_future(value) then
      local keys = {}
      for key in pairs(value) do keys[#keys + 1] = key end
      table.sort(keys, function(a, b) return identity(a) < identity(b) end)
      for _, key in ipairs(keys) do
        local part = tostring(key):gsub("%c", function(c) return string.format("%%%02X", c:byte()) end)
        received(path .. "[" .. part .. "]", value[key])
      end
      return
    end
    if is_future(value) then
      section(value.key, value.bytes, value.sha)
    else
      section(path, type(value) == "string" and value or assert(rex.json.encode(value)))
    end
  end
  for i = 1, args.n do
    received("arg:" .. i, args[i])
  end
  return table.concat(parts)
end

local function prepare(job, inputs)
  local run = job.run
  local kind = type(job.body) == "table" and job.body.kind or "lua"
  local is_hand = kind == "hand"
  local spans = ordered_spans(job.spans)
  local input
  if is_hand then
    input = packet_for(job, inputs.raw, spans)
  else
    local materials = {}
    for i = #spans, 1, -1 do materials[#materials + 1] = { spans[i].name, spans[i].bytes } end
    input = kind .. identity{ inputs.resolved, materials }
  end
  job.input_sha = store_call(run, "put_blob", input)
  local previous = run.saved[job.key]
  if previous then
    if previous.fn ~= job.name or previous.input_sha ~= job.input_sha then
      run.mismatch = "journal mismatch at " .. job.key .. " (function or input changed)"
      return fail(job, run.mismatch)
    end
    if previous.state == "returned" then
      local bytes = store_call(run, "get_blob", previous.return_sha)
      local value = bytes
      if not is_hand then
        local reason
        value, reason = rex.json.decode(bytes)
        assert(not reason, reason)
      end
      run.replayed = run.replayed + 1
      return settle(job, value, nil, bytes, previous.return_sha)
    end
  end
  job.attempt = previous and previous.attempt + 1 or 1
  local reason
  if is_hand then job.block_id, reason = hand_start(job, input) end
  append(job, "started")
  if reason then return fail(job, reason) end
  if is_hand then
    run.in_flight[job.block_id] = job
    job.message = "Hand started"
    update_mark(job)
  elseif kind == "question" then
    return true
  else
    run.ready[#run.ready + 1] = job
  end
end

local function step(run, job)
  local args = job.resume or { n = 0 }
  job.resume = nil
  local result = pack(coroutine.resume(job.thread, unpack(args, 1, args.n)))
  local ok, operation, data = unpack(result, 1, 3)
  local finished = coroutine.status(job.thread) == "dead"
  if job.frame and (not ok or finished) then
    contexts[job.thread] = nil
    job.thread, job.frame = job.frame.thread, job.frame.parent
    job.resume = result
    run.ready[#run.ready + 1] = job
    return
  end
  if not ok then return fail(job, operation) end
  if finished then
    if not job.parent then return settle(job, operation) end
    return return_json(job, operation)
  elseif operation == "start" then
    -- Rex's Lua threads inherit their creator's cancellation context. Create
    -- new work on the driver so an independent call can outlive its caller.
    local child = new_job(run, job, data.key, data.name, data.body, data.args, data.spans)
    mark(child, "working")
    job.resume = pack(child.future)
    run.ready[#run.ready + 1] = job
    run.ready[#run.ready + 1] = child
  elseif operation == "await" then
    data.waiters[#data.waiters + 1] = job
  elseif operation == "span" then
    -- A span frame shares the job and its call counters, and owns its span stack.
    job.frame = { thread = job.thread, parent = job.frame }
    job.thread = coroutine.create(data.fn)
    contexts[job.thread] = { job = job, spans = data.spans }
    job.resume = data.args
    run.ready[#run.ready + 1] = job
  elseif operation == "prepare" then
    local prepared, prompt_or_reason = pcall(prepare, job, data)
    if not prepared then
      fail(job, prompt_or_reason)
    elseif prompt_or_reason then
      question(job, data.resolved)
    end
  else
    fail(job, "unexpected coroutine yield")
  end
end

function mw.run(config)
  assert(type(config.name) == "string" and config.name ~= "", "run name is required")
  assert(type(config.main) == "function", "main must be a Lua function")
  local place = config.place or "tab"
  assert(place == "tab" or place == "split" or place == "detached", "unknown hand placement " .. tostring(place))
  -- The file journal is the default; `store=engine` in the run's arguments keeps saved returns on the work
  -- engine (`engine={endpoint=..., credentials=...}` overrides where).
  local store = config.store
  if not store then
    local args = rex.args or {}
    local chosen = args.store or "file"
    assert(chosen == "file" or chosen == "engine", "unknown store " .. tostring(chosen) .. " (file or engine)")
    store = chosen == "engine" and require("madewell.store_engine").new(args.engine)
      or require("madewell.store_file").new()
  end
  local run = {
    name = config.name, place = place, store = store,
    saved = {}, ready = {}, in_flight = {}, serial = 0, returned = 0, replayed = 0, failed = 0,
  }
  local view, reason = rex.session.view{}
  assert(view, reason)
  run.session_id = assert(view.session_id, "Rex session id is unavailable")
  for _, entry in ipairs(store_call(run, "load")) do run.saved[entry.key] = entry end
  local root = new_job(run, nil, config.name, nil, config.main)
  mark(root, "working")
  run.ready[1] = root
  while (not run.mismatch and #run.ready > 0) or next(run.in_flight) do
    if not run.mismatch and #run.ready > 0 then
      local job = table.remove(run.ready)
      step(run, job)
    else
      local event, wait_reason = rex.wait("terminal.child_exited", function(ev) return run.in_flight[ev.block_id] end)
      assert(event, wait_reason)
      local job = run.in_flight[event.block_id]
      run.in_flight[event.block_id] = nil
      hand_exit(job, event.exit_code)
    end
  end
  local failure = run.mismatch or root.future.reason
  if not root.future.done and not failure then failure = "unresolved Made Well calls" end
  for thread, scope in pairs(contexts) do
    if scope.job.run == run then contexts[thread] = nil end
  end
  local summary = string.format("%s · %d returned, %d replayed, %d failed",
    (config.name:gsub("%c", " ")), run.returned, run.replayed, run.failed)
  mark(root, failure and "error" or "done", failure or summary)
  print(summary)
  if run.temp then
    local ok, cleanup_reason = pcall(exec, { "rm", "-r", "--", run.temp })
    if not ok then rex.log("warn", "could not remove hand files: " .. tostring(cleanup_reason)) end
  end
  if failure then error(failure, 0) end
  return root.future.value
end

return mw
