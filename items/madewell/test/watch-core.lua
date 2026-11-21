local args = rex.args
local terminal = "com.superlogical.terminal"
local window, reason = rex.session.new_window{
  focus = false, window_label = "Made Well core test driver",
  layout = rex.layout.block{
    flavor = terminal .. ".shell",
    options = {
      shell = "none", exit = { on_completion = false },
      command = { "env", "TMPDIR=" .. args.tmp, "rex", "-S", args.endpoint, "--autostart=false",
        "do", "-s", args.session, args.script, "--args", args.config },
    },
  },
}
assert(window, reason)
local driver = window.block_ids[1]
local match, wait_reason = rex.wait("terminal.program_status_changed", function(ev)
  local record = ev.record
  return ev.block_id == driver and record and record.title == args.title
    and record.state == args.state and (not args.msg or record.msg == args.msg)
end, 10)
assert(match, "driver did not report " .. args.title .. " " .. args.state .. ": " .. tostring(wait_reason))
if args.state == "done" then
  local exit = assert(rex.wait("terminal.child_exited", function(ev) return ev.block_id == driver end, 10))
  assert(exit.exit_code == 0, "the core driver's assertions failed")
  local result = assert(rex.block.call(terminal, "program_status", { block_id = driver }))
  assert(#result.records == 1 and result.records[1].title == "one" and result.records[1].state == "done",
    "finished children should be folded into the root mark")
  assert(rex.call("block.close", { session_id = args.session, block_id = driver }))
  print("row 1 passed: Rex observed the hand done mark and folded root, and the driver verified the saved return")
else
  print("Observed durable launch of the unfinished hand. Stopping disposable Rex.")
end
