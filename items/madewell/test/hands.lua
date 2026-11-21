local hands = require "madewell.hands"
local args = rex.args
local input, output = args.dir .. "/input", args.dir .. "/return"
local body = rex.args.live and hands.agent{
  harness = "codex",
  duty = "Reply with exactly the word pong in your final answer. Use no tools."
} or hands.cmd{
  argv = { "sh", "-c", 'cat "$MW_INPUT" > "$MW_RETURN.tmp" && mv "$MW_RETURN.tmp" "$MW_RETURN"' },
  duty = "pong"
}

local file = assert(io.open(input, "wb"))
assert(file:write(body.duty))
assert(file:close())

local argv = { "env", "MW_CALL=probe.1", "MW_INPUT=" .. input, "MW_RETURN=" .. output,
  "REX_SERVER=" .. assert(os.getenv("REX_SERVER")), args.item .. "/hand" }
for _, arg in ipairs(body.argv) do argv[#argv + 1] = arg end
local window = assert(rex.session.new_window{
  focus = false,
  window_label = "probe",
  layout = rex.layout.block{
    flavor = "com.superlogical.terminal.shell",
    options = {
      command = argv,
      shell = "none",
      exit = { on_completion = false }
    }
  }
})
local block = window.block_ids[1]

local event = assert(rex.wait("terminal.child_exited", function(ev)
  return ev.block_id == block
end, 90))
assert(event.exit_code == 0, "hand exited with code " .. tostring(event.exit_code))
local status = assert(rex.block.call("com.superlogical.terminal", "program_status", { block_id = block }))
local record = assert(status.records[1], "missing OSC 7501 record")
assert(record.app == "madewell" and record.title == "probe.1" and record.state == "done",
  rex.json.encode(status))
file = assert(io.open(output, "rb"))
local value = file:read("*a")
assert(file:close())
assert(value == "pong", "expected a byte-exact pong, got " .. rex.json.encode(value))
return { harness = args.live and "codex" or "cmd", state = record.state, value = value }
