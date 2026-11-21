-- Saved returns on the work engine: one `journal` actor per run in the madewell-journal namespace,
-- served by items/madewell/journal/node.mjs. Same interface as store_file. The library's scoped token
-- is read by curl from its header file; it never enters argv, the environment or a log.
local store_engine = {}
local Store = {}
Store.__index = Store

local function curl(self, method, run, path, body)
  local key = run:gsub("\\", "\\\\"):gsub(",", "\\,")
  local query = "rvt-namespace=" .. self.namespace .. "&rvt-method=getOrCreate&rvt-runner=" .. self.pool
    .. "&rvt-key=" .. key:gsub("[^A-Za-z0-9_.~-]", function(byte)
      return string.format("%%%02X", byte:byte())
    end) .. "&rvt-crash-policy=sleep"
  local argv = { "curl", "-sS", "--fail-with-body", "-m", tostring(self.timeout),
    "-H", "@" .. self.header, "-X", method }
  if body then
    argv[#argv + 1] = "--data-binary"
    argv[#argv + 1] = "@-"
  end
  argv[#argv + 1] = self.endpoint .. "/gateway/journal/request" .. path .. "?" .. query
  local result, reason = rex.exec(argv, body and { stdin = body } or nil)
  assert(result, reason)
  assert(result.ok, "engine journal " .. method .. " " .. path .. " for run " .. run .. ": "
    .. result.stderr .. result.stdout)
  return result.stdout
end

local function sha256(bytes)
  local result, reason = rex.exec({ "sha256sum" }, { stdin = bytes })
  assert(result, reason)
  assert(result.ok, "sha256sum: " .. result.stderr)
  return assert(result.stdout:match("^([0-9a-f]+)"))
end

function store_engine.new(options)
  options = options or {}
  local credentials = options.credentials
    or (assert(os.getenv("HOME")) .. "/.local/share/agent-credentials/madewell-journal")
  local header = credentials .. "/library.header"
  local probe = io.open(header, "rb")
  assert(probe, "no engine journal credential at " .. header)
  assert(probe:close())
  return setmetatable({
    endpoint = options.endpoint or "http://127.0.0.1:7420",
    namespace = options.namespace or "madewell-journal",
    pool = options.pool or "journal",
    timeout = options.timeout or 60,
    header = header,
  }, Store)
end

function Store:load(run)
  assert(type(run) == "string" and run ~= "", "run name is required")
  local entries = {}
  for line in curl(self, "GET", run, "/records"):gmatch("([^\n]*)\n") do
    local entry, reason = rex.json.decode(line)
    assert(type(entry) == "table" and type(entry.key) == "string"
      and type(entry.fn) == "string" and type(entry.input_sha) == "string"
      and type(entry.attempt) == "number"
      and (entry.state == "started" or entry.state == "returned" or entry.state == "failed"),
      "invalid engine journal record for run " .. run .. (reason and ": " .. reason or ""))
    entries[#entries + 1] = entry
  end
  return entries
end

function Store:append(run, entry)
  curl(self, "POST", run, "/records", assert(rex.json.encode(entry)))
end

function Store:put_blob(run, bytes)
  local sha = sha256(bytes)
  curl(self, "PUT", run, "/blobs/" .. sha, bytes)
  return sha
end

function Store:get_blob(run, sha)
  assert(type(sha) == "string" and #sha == 64 and sha:match("^[a-f0-9]+$"), "invalid blob SHA")
  local bytes = curl(self, "GET", run, "/blobs/" .. sha)
  assert(sha256(bytes) == sha, "engine journal blob " .. sha .. " for run " .. run .. " does not match its hash")
  return bytes
end

return store_engine
