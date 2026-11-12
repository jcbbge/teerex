-- Fixed source; caller values are JSON in rex.args, never interpolated into Lua.
local a = rex.args
local function emit(value)
    io.write(rex.json.encode(value), "\n")
    io.flush()
end
local v = rex.call("server.version")
if v.api_revision ~= 13 then error("unsupported Rex API revision") end
emit({event="source", source={rex_version=v.rex_version, platform=v.platform, api_revision=v.api_revision}})

local remaining = a.max_bytes
local seen = {stdout=0, stderr=0}
local function receive(stream, chunk)
    seen[stream] = seen[stream] + #chunk
    local n = math.min(remaining, #chunk)
    if n > 0 then
        remaining = remaining - n
        -- Hex preserves arbitrary bytes and UTF-8 characters split across callbacks.
        local hex = chunk:sub(1, n):gsub(".", function(c) return string.format("%02x", c:byte()) end)
        emit({event=stream, hex=hex})
    end
end
local h, err = rex.exec.start(a.argv, {
    cwd=a.cwd, stdin="", timeout=a.timeout_ms / 1000,
    stdout=function(s) receive("stdout", s) end,
    stderr=function(s) receive("stderr", s) end,
})
if not h then error(err) end
emit({event="started", pid=h.pid})
local r, wait_error = h:wait()
if not r then error(wait_error) end
emit({event="result", code=r.code, signal=r.signal, timed_out=r.timed_out or false,
      ok=r.ok, stdout_seen=seen.stdout, stderr_seen=seen.stderr})
