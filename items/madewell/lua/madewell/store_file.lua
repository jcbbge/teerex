local store_file = {}
local Store = {}
Store.__index = Store

local function exec(argv, opts)
  local result, reason = rex.exec(argv, opts)
  assert(result, reason)
  assert(result.ok, argv[1] .. ": " .. result.stderr)
  return result.stdout
end

local function write_file(path, mode, bytes)
  local file = assert(io.open(path, mode))
  local written, reason = file:write(bytes)
  local flushed, flush_reason = file:flush()
  local closed, close_reason = file:close()
  assert(written, reason)
  assert(flushed, flush_reason)
  assert(closed, close_reason)
end

local function path_component(name)
  assert(type(name) == "string" and name ~= "", "run name is required")
  if name == "." or name == ".." then return (name:gsub("%.", "%%2E")) end
  return (name:gsub("[^A-Za-z0-9_.+-]", function(byte)
    return string.format("%%%02X", byte:byte())
  end))
end

function store_file.new(root)
  return setmetatable({
    root = root or (assert(os.getenv("HOME")) .. "/.local/state/madewell/runs"),
    tails = {},
  }, Store)
end

function Store:load(run)
  local dir = self.root .. "/" .. path_component(run)
  exec{ "mkdir", "-m", "700", "-p", "--", dir .. "/blobs" }
  local path = dir .. "/journal.jsonl"
  local file = assert(io.open(path, "ab+"))
  assert(file:seek("set", 0))
  local bytes = assert(file:read("*a"))
  assert(file:close())

  local entries, offset = {}, 0
  for line, next_offset in bytes:gmatch("([^\n]*)\n()") do
    local entry, reason = rex.json.decode(line)
    assert(type(entry) == "table" and type(entry.key) == "string"
      and type(entry.fn) == "string" and type(entry.input_sha) == "string"
      and type(entry.attempt) == "number"
      and (entry.state == "started" or entry.state == "returned" or entry.state == "failed"),
      "invalid journal record in " .. path .. (reason and ": " .. reason or ""))
    entries[#entries + 1] = entry
    offset = next_offset - 1
  end
  -- A writer can die between writing the final record and its newline.
  self.tails[run] = offset < #bytes and offset or nil
  return entries
end

function Store:append(run, entry)
  local dir = self.root .. "/" .. path_component(run)
  local path = dir .. "/journal.jsonl"
  local line = assert(rex.json.encode(entry)) .. "\n"
  local tail = self.tails[run]
  if tail then
    exec{ "truncate", "-s", tostring(tail), "--", path }
    self.tails[run] = nil
  end
  write_file(path, "ab", line)
  exec{ "sync", "--", path, dir }
end

function Store:put_blob(run, bytes)
  local sha = assert(exec({ "sha256sum" }, { stdin = bytes }):match("^([0-9a-f]+)"))
  local dir = self.root .. "/" .. path_component(run) .. "/blobs"
  local path = dir .. "/" .. sha
  local exists = io.open(path, "rb")
  if exists then
    assert(exists:close())
    return sha
  end
  local tmp = (exec{ "mktemp", "--", dir .. "/.blob.XXXXXXXX" }:gsub("\n$", ""))
  local ok, reason = pcall(function()
    write_file(tmp, "wb", bytes)
    exec{ "sync", "--", tmp }
    assert(os.rename(tmp, path))
    exec{ "sync", "--", dir }
  end)
  if not ok then
    os.remove(tmp)
    error(reason, 0)
  end
  return sha
end

function Store:get_blob(run, sha)
  assert(type(sha) == "string" and #sha == 64 and sha:match("^[a-f0-9]+$"), "invalid blob SHA")
  local file = assert(io.open(self.root .. "/" .. path_component(run) .. "/blobs/" .. sha, "rb"))
  local bytes, reason = file:read("*a")
  assert(file:close())
  return assert(bytes, reason)
end

return store_file
