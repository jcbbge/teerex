local item = assert(rex.args.item)
package.path = item .. "/lua/?.lua;" .. package.path
local hands = io.open(item .. "/lua/madewell/hands.lua", "r")
if hands then
  assert(hands:close())
else
  package.preload["madewell.hands"] = function() return {} end
end

local mw = require "madewell"
local store = require("madewell.store_file").new(assert(rex.args.root))

local function hand(script, ...)
  return { kind = "hand", argv = { "sh", "-eu", "-c", script, "core-test", ... }, duty = "Test duty" }
end

local function literal(bytes)
  return hand('printf "%s" "$1" > "$MW_RETURN.tmp"; mv "$MW_RETURN.tmp" "$MW_RETURN"', bytes)
end

local function run(name, main, place)
  return mw.run{ name = name, main = main, place = place, store = store }
end

local function row_one()
  local one = mw.fn("one", literal("hello"))
  local result = run("one", function() return one() end)
  local entries = store:load("one")
  assert(result == "hello" and #entries == 2)
  assert(entries[1].state == "started" and entries[1].block_id)
  assert(entries[2].state == "returned" and entries[2].key == "one.1")
  assert(store:get_blob("one", entries[2].return_sha) == "hello")
  for _, block in ipairs(rex.session.list_blocks{}.blocks) do
    assert(block.block_id ~= entries[1].block_id, "returned block should be closed")
  end
  print("row 1 passed: one block opened, saved its return and closed")
end

local function rows_two_three()
  local fifo = assert(rex.args.fifo)
  local created = assert(rex.exec{ "mkfifo", fifo })
  assert(created.ok, created.stderr)
  local first = mw.fn("first", hand([[
    printf '%s\n' first > "$1"
    printf '%s' left > "$MW_RETURN.tmp"; mv "$MW_RETURN.tmp" "$MW_RETURN"
  ]], fifo))
  local second = mw.fn("second", hand([[
    read -r first < "$1"
    test "$first" = first
    printf '%s' right > "$MW_RETURN.tmp"; mv "$MW_RETURN.tmp" "$MW_RETURN"
  ]], fifo))
  local results = run("parallel", function()
    local left, right = first(), second()
    return mw.await_all{ left, right }
  end, "split")
  assert(#results == 2 and results[1] == "left" and results[2] == "right")
  local entries = store:load("parallel")
  assert(entries[1].state == "started" and entries[2].state == "started")
  assert(entries[1].block_id ~= entries[2].block_id)
  print("row 2 passed: split hands overlapped and yielded an ordered list")

  local payload = "north" .. string.char(0, 255) .. "\n\n--- text\r"
  local source = mw.fn("source", hand([[
    printf 'north\000\377\n\n--- text\r' > "$MW_RETURN.tmp"; mv "$MW_RETURN.tmp" "$MW_RETURN"
  ]]))
  local wired = mw.fn("wired", hand([[cp "$MW_INPUT" "$MW_RETURN.tmp"; mv "$MW_RETURN.tmp" "$MW_RETURN"]]))
  local packet = run("wiring", function()
    return wired({ item = source() })
  end, "detached")
  entries = store:load("wiring")
  assert(entries[2].key == "source.1" and entries[2].state == "returned")
  assert(entries[3].key == "wired.1" and entries[3].state == "started")
  local header = string.format("Test duty\n--- Received: source.1 sha256=%s bytes=%d ---\n",
    entries[2].return_sha, #payload)
  assert(packet == header .. payload, "wired packet changed the source bytes or provenance")
  print("row 3 passed: a detached hand waited for a nested future and received exact binary bytes")
end

local function lua_and_questions()
  local leaf = mw.fn("leaf", literal("leaf"))
  local branch = mw.fn("branch", function()
    local first = leaf()
    local nothing = mw.fn("nothing", function() return nil end)()
    assert(mw.await(nothing) == nil)
    return { first, leaf() }
  end)
  local values = run("nested", function()
    return mw.extend({ "before" }, branch())
  end)
  assert(#values == 3 and values[2] == "leaf" and values[3] == "leaf")
  local entries = store:load("nested")
  local seen = {}
  for _, entry in ipairs(entries) do
    if entry.state == "returned" then seen[entry.key] = true end
  end
  assert(seen["branch.1/leaf.1"] and seen["branch.1/leaf.2"] and seen["branch.1/nothing.1"])

  local bad = mw.fn("bad", hand("exit 17"))
  local good = mw.fn("good", literal("success"))
  local ok, reason = pcall(run, "failure", function()
    local broken, independent = bad(), good()
    return { broken, independent }
  end)
  assert(not ok and reason:find("bad.1: hand exited 17", 1, true), tostring(reason))
  local kept, saved
  for _, entry in ipairs(store:load("failure")) do
    if entry.state == "failed" then kept = entry.block_id end
    if entry.state == "returned" then saved = entry.return_sha end
  end
  assert(kept and saved and store:get_blob("failure", saved) == "success")
  local block_exists = false
  for _, block in ipairs(rex.session.list_blocks{}.blocks) do
    if block.block_id == kept then block_exists = true end
  end
  assert(block_exists, "failed block should remain open")
  print("Lua coroutines nested, a hand error named its key, and the independent hand finished")

  local native_input, native_pick = rex.ui.input, rex.ui.pick
  rex.ui.input = function(options)
    assert(options.title == "Say it" and options.value == "edit me" and options.placeholder == "hint")
    return " exactly "
  end
  rex.ui.pick = function(options)
    if options.title == "Select" then
      assert(options.multiple and options.items[1] == "left")
      return { "left" }
    end
    assert(options.title == "Promote tasks" and options.multiple)
    assert(options.items[1].selected and options.items[2].selected and options.items[2].title == "B")
    return { "2" }
  end
  local function ask()
    local auto = { "unchanged" }
    assert(mw.promote(auto, { auto = true }) == auto)
    return {
      mw.ask{ title = "Say it", value = "edit me", placeholder = "hint" },
      mw.pick{ title = "Select", items = { "left", "right" }, multiple = true }[1],
      mw.promote({ { title = "A" }, { name = "B" } }, { title = "Promote tasks" })[1].name,
    }
  end
  values = run("questions", ask)
  assert(values[1] == " exactly " and values[2] == "left" and values[3] == "B")
  rex.ui.input = function() error("replay asked again") end
  rex.ui.pick = rex.ui.input
  values = run("questions", ask)
  assert(values[1] == " exactly " and values[2] == "left" and values[3] == "B")
  assert(#store:load("questions") == 8, "replay should add no journal entries")
  rex.ui.input, rex.ui.pick = native_input, native_pick
  ok, reason = pcall(run, "headless", function()
    return mw.ask{ title = "No Rex app on this server" }
  end)
  assert(not ok and (reason == "ask.1: unsupported" or reason == "ask.1: no_client"), tostring(reason))
  local headless = store:load("headless")
  assert(headless[2].state == "failed" and reason:find(headless[2].reason, 1, true))
  print("Question stubs verified answers, preselection and replay. Native Rex returned its headless reason")
end

local function span_seam()
  local packet = mw.fn("packet", hand([[cp "$MW_INPUT" "$MW_RETURN.tmp"; mv "$MW_RETURN.tmp" "$MW_RETURN"]]))
  local material = mw.fn("material", literal("outer material\n"))
  local branch = mw.fn("branch", function(arg)
    return mw.span("rumen", { "inner material" }, function()
      return packet(arg)
    end)
  end)
  local function main(use_saved_material)
    local outer = use_saved_material and material() or "changed material"
    local spanned, nothing, trailing = mw.span("ground", outer, function(value)
      return branch(value), nil, false
    end, "argument")
    assert(nothing == nil and trailing == false)
    return { mw.await(spanned), mw.await(packet("outside")) }
  end
  local values = run("span", function() return main(true) end)
  local function header(label, value)
    return string.format("\n--- Received: %s sha256=%s bytes=%d ---\n", label,
      store:put_blob("span", value), #value) .. value
  end
  assert(values[1] == "Test duty" .. header("span:ground", "outer material\n")
    .. header("span:rumen", '["inner material"]') .. header("arg:1", "argument"))
  assert(values[2] == "Test duty" .. header("arg:1", "outside"), "span leaked outside its scope")
  local entries = store:load("span")
  assert(#entries == 8 and entries[3].key == "branch.1" and entries[4].key == "branch.1/packet.1")
  values = run("span", function() return main(true) end)
  assert(#values == 2 and #store:load("span") == #entries)

  local ok, reason = pcall(run, "span", function() return main(false) end)
  assert(not ok and reason:find("journal mismatch at branch.1", 1, true), tostring(reason))
  print("Span seam passed: coroutine inheritance, outermost-first bytes, unchanged keys and replay mismatch")
end

local function resume_after_failure()
  local stable = mw.fn("stable", literal("saved"))
  local retry = mw.fn("retry", hand([[
    if [ ! -f "$1" ]; then touch "$1"; exit 12; fi
    printf '%s' recovered > "$MW_RETURN.tmp"; mv "$MW_RETURN.tmp" "$MW_RETURN"
  ]], rex.args.retry_flag))
  local function main(arg)
    local saved = mw.await(stable(arg))
    return { saved, mw.await(retry(saved)) }
  end
  local ok, reason = pcall(run, "resume", function() return main("same input") end)
  assert(not ok and reason == "retry.1: hand exited 12", tostring(reason))
  local before = store:load("resume")
  assert(#before == 4 and before[2].state == "returned" and before[4].state == "failed")

  local journal = assert(io.open(rex.args.root .. "/resume/journal.jsonl", "ab"))
  assert(journal:write('{"key":'))
  assert(journal:close())
  local native_window = rex.session.new_window
  local opened = {}
  rex.session.new_window = function(options)
    opened[#opened + 1] = options.window_label
    return native_window(options)
  end
  local result = run("resume", function() return main("same input") end)
  assert(result[1] == "saved" and result[2] == "recovered")
  assert(#opened == 1 and opened[1] == "retry.1")
  local after = store:load("resume")
  assert(#after == 6 and after[5].key == "retry.1" and after[5].attempt == 2)
  assert(after[6].state == "returned" and after[6].attempt == 2)
  result = run("resume", function() return main("same input") end)
  assert(result[2] == "recovered" and #opened == 1 and #store:load("resume") == 6)
  ok, reason = pcall(run, "resume", function() return main("different input") end)
  assert(not ok and reason:find("journal mismatch at stable.1", 1, true) and #opened == 1, tostring(reason))
  rex.session.new_window = native_window
  print("row 6 passed: replay opened no saved block, repaired a torn tail, retried attempt 2 and rejected changed input")
end

local function restart_mid_hand()
  local stable = mw.fn("stable", literal("saved before restart"))
  local unfinished = mw.fn("unfinished", hand([[
    if [ ! -f "$1" ]; then read -r unused < "$2"; fi
    printf '%s' recovered > "$MW_RETURN.tmp"; mv "$MW_RETURN.tmp" "$MW_RETURN"
  ]], rex.args.restart_flag, rex.args.fifo))
  local function main()
    local before = mw.await(stable())
    return { before, mw.await(unfinished(before)) }
  end
  if not rex.args.restarted then
    run("restart", main)
    error("the server was supposed to stop mid-hand")
  end
  local prior = store:load("restart")
  assert(#prior == 3 and prior[2].state == "returned" and prior[3].state == "started")
  local native_window = rex.session.new_window
  local opened = {}
  rex.session.new_window = function(options)
    opened[#opened + 1] = options.window_label
    return native_window(options)
  end
  local values = run("restart", main)
  assert(values[1] == "saved before restart" and values[2] == "recovered")
  local entries = store:load("restart")
  assert(#opened == 1 and opened[1] == "unfinished.1" and #entries == 5)
  assert(entries[4].attempt == 2 and entries[4].block_id ~= entries[3].block_id)
  assert(entries[5].state == "returned")
  print("row 7 passed: a fresh Rex server replayed the saved value and opened only the interrupted hand")
end

local function rex_limit()
  local blocked = mw.fn("blocked", literal("should not start"))
  local ok, reason = pcall(run, "native-limit", function() return blocked() end)
  assert(not ok and reason:find("maximum of 1 blocks", 1, true)
    and not reason:find("status=409", 1, true), tostring(reason))
  local entries = store:load("native-limit")
  assert(entries[2].state == "failed" and not entries[2].block_id)
  print("Rex limit passed: a native 409 named the block limit in plain words")
end

local tests = {
  one = row_one, wiring = rows_two_three, lua = lua_and_questions, span = span_seam, resume = resume_after_failure,
  restart = restart_mid_hand, limit = rex_limit,
}
assert(tests[rex.args.test], "unknown core test")()
