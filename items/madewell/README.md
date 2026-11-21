# Made Well on Rex

Made Well lets you write work as Lua functions. A function can launch a command or an agent in a Rex pane, or compose other functions. Rex shows the work in progress, and the journal supplies saved returns when a run resumes.

## Run the ping-pong demo

From a teerex checkout, run this in a Rex pane with the Rex app connected.

```sh
items/madewell/bin/mw items/madewell/demo/pingpong.lua run=first-pong
```

Select the proposed task in the Rex picker. A command hand returns `pong` and a separate hand checks its four bytes. Rex then asks what the tab and Activity sidebar show. The demo reports the verified result for each selected task and project.

Use JSON to pass several inputs and projects. Set `"live":true` to use the authenticated Codex CLI for each implementation call.

```sh
items/madewell/bin/mw items/madewell/demo/pingpong.lua --args \
  '{"run":"two-projects","inputs":["ping","hello"],"projects":["demo","sandbox"]}'
```

## Write your own functions

Save a Lua script and run it with `items/madewell/bin/mw /path/to/work.lua`. The launcher sets the Lua module path and forwards arguments to `rex do`.

```lua
local mw = require "madewell"

local send = mw.fn("send", mw.hand.cmd{
  duty = "Return pong.",
  argv = { "sh", "-c", 'printf %s pong > "$MW_RETURN.tmp" && mv "$MW_RETURN.tmp" "$MW_RETURN"' }
})

local read = mw.fn("read", mw.hand.agent{
  harness = "codex",
  duty = "Explain the received reply in one sentence."
})

local work = mw.fn("work", function(input)
  local first = send(input)
  local second = send(input)
  return { read(first), read(second) }
end)

return mw.run{
  name = rex.args.run or "my-work",
  main = function() return work("ping") end
}
```

Calling a function starts its work and returns a future. The two `send` calls can run concurrently. Each `read` receives the corresponding return when it is ready. Use `mw.await(value)` or `mw.await_all(list)` when Lua needs the resolved values. Use `place = "tab"`, `"split"`, or `"detached"` in `mw.run` to choose where hands appear.

## Compose discovery and delivery

`require "madewell.defaults"` supplies Lua bodies to pass to `mw.fn`. Discovery starts its seven default steps independently and returns their results in step order. Delivery wires each step to the previous return and finishes with the verification return. Each hand starts its own Rex block, including implementation and verification.

```lua
local defaults = require "madewell.defaults"

local discover = mw.fn("discovery", defaults.discovery{
  harness = "claude",
  effort = "Read the source closely and keep each return short.",
  steps = {
    "declared",
    "lookFirst",
    {
      name = "confirm",
      receives = function(results, _, input)
        return input, results.declared, results.lookFirst
      end
    }
  }
})

local deliver = mw.fn("delivery", defaults.delivery{
  ground = "Use the project brief and the supplied material.",
  rumen = "Check the acceptance conditions against the actual result."
})
```

Omitting `steps` uses Josh's defaults. Supply an ordered list, including an empty one, to change the composition. A step can be a built-in name or a table with a `name` and an optional `body`, `duty`, `harness`, `model`, `label`, `span`, or `receives`. A `body` can be a hand or a Lua function. `receives(by_name, previous, ...)` supplies that call's arguments. Generated agent duties carry the chosen effort setting. With empty delivery, the body returns its first argument.

`defaults.ground(fn, material)` and `defaults.rumen(fn, rules)` wrap any Lua callable. The material is included in each hand packet started inside the wrapped function, including its nested calls. The default delivery applies Ground to ideation and planning and Rumen to implementation and verification. Set a custom step's `span` to `"ground"` or `"rumen"` to use the corresponding material. The composition and effort guidance comes from the [Made Well Foundation](https://github.com/jcbbge/madewell/blob/main/FOUNDATION.md#bedrock-composition-spanning-processes-and-effort-dials).

## Hand contract

- `MW_CALL` identifies the call. `MW_INPUT` points to the packet containing the duty and each received value. A `--- Received: <key> sha256=<hex> bytes=<n> ---` header precedes its exact bytes. Inherited span material precedes the call arguments.
- Write the complete return to `"$MW_RETURN.tmp"`, rename it to `"$MW_RETURN"`, and exit zero. Standard output and standard error are for the terminal. A nonzero body exit is preserved. A zero exit with a missing return exits with code 70.
- The wrapper uses OSC 7501 to report working, done, and error. Rex keeps a failed block open for inspection.
- `mw.hand.agent` uses the selected headless CLI from the login user's home. Supported harnesses are `codex`, `claude`, and `pi`. Set `model` to override the default. The Codex and Claude commands use rexconfig's standing approval and sandbox flags. The agent runs with the login user's access and sends the packet to the configured provider.

## Journal and resume

By default, each run writes its journal and content blobs under `~/.local/state/madewell/runs/<run>/`. The journal records call keys, input and return hashes, attempts, outcomes, and answers. `mw.run{store = ...}` can select another journal backend. Pass `store=engine` in a run's arguments to keep its journal on the work engine instead; see `journal/README.md`.

Reissue the same command with the same run name and inputs to resume. Completed calls and answered questions replay from the journal. The first unfinished call starts a new attempt. A conflicting function or input at a saved call key stops the run and identifies the key. Use a fresh run name for a new experiment. A hand interrupted by a server restart runs again on resume, so make retryable hands safe to repeat.

## Requirements and checks

This experimental teerex item runs on Linux with Rex Preview 22, a POSIX shell, and the system command-line utilities. The chosen agent CLI and its existing authentication are required only when launching that harness. Run it from the checkout. The launcher uses the available Rex server and does not install services, packages, or Rex configuration.

`items/madewell/test/run-hands.sh` creates and removes an isolated Rex server and checks the wrappers. Add `--live` to make one real Codex call. `items/madewell/test/run-engine.sh` checks the engine journal against a running journal node. Removing the checkout removes the launcher and source. The run directories are separate so saved results can be retained.
