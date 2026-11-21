local hands = {}

function hands.cmd(opts)
  assert(type(opts) == "table", "mw.hand.cmd expects options")
  local argv = opts.argv
  assert(type(argv) == "table" and type(argv[1]) == "string" and argv[1] ~= "",
    "mw.hand.cmd requires a nonempty argv")
  local command = {}
  for i, arg in ipairs(argv) do
    assert(type(arg) == "string", "hand argv entries must be strings")
    command[i] = arg
  end
  return { kind = "hand", argv = command, duty = opts.duty, label = opts.label }
end

local capture_stdout = [[
cd "$HOME" || exit $?
"$@" < "$MW_INPUT" > "$MW_RETURN.tmp" &&
  mv -- "$MW_RETURN.tmp" "$MW_RETURN"
]]

local capture_codex = [[
cd "$HOME" || exit $?
"$@" -C "$HOME" -o "$MW_RETURN.tmp" - < "$MW_INPUT" &&
  mv -- "$MW_RETURN.tmp" "$MW_RETURN"
]]

function hands.agent(opts)
  assert(type(opts) == "table", "mw.hand.agent expects options")
  local script, command
  local model = opts.model
  if opts.harness == "codex" then
    script = capture_codex
    command = { "codex", "--no-daemon", "--dangerously-bypass-hook-trust", "exec",
      "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox", "--ephemeral" }
  elseif opts.harness == "claude" then
    script = capture_stdout
    command = { "claude", "-p", "--dangerously-skip-permissions", "--no-session-persistence" }
    model = model or "claude-opus-5-5"
  elseif opts.harness == "pi" then
    script = capture_stdout
    command = { "pi", "-p", "--no-session" }
  else
    error("unknown agent harness: " .. tostring(opts.harness), 2)
  end

  local argv = { "sh", "-c", script, "mw-agent" }
  for _, arg in ipairs(command) do argv[#argv + 1] = arg end
  if model then
    argv[#argv + 1] = "--model"
    argv[#argv + 1] = model
  end
  return hands.cmd{ argv = argv, duty = opts.duty, label = opts.label }
end

return hands
