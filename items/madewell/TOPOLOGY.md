# Topology: Rivet, Rex and Made Well, fused

The reference for where everything sits. Before any change, drop it through the **Plinko** (section 5):
it falls through each layer and lands where that layer serves it best. Josh's words, 21 Nov 2026 (CT),
unless marked. The diagram is on Josh's M5 in tldraw (`Topology.tldraw`, Documents); this file is
the authority, and the diagram is where he plays with the structure. When they differ, he decides and
both change.

## 1. The ethos

Made Well is anti-slop, anti-vibe-code, anti-one-shot. It is an opinionated grammar for building
software with well-intentioned decisions and an end user in mind, and it doesn't let go of it. Nobody
one-shots Arc: eight months in, the work is still being shaped decision by decision.

Two things the industry gets wrong, and this system refuses:
1. **It treats agents as the durable actors.** Here the **work** is durable. Agents are disposable hands.
2. **It keeps the chat, thread and message-board paradigm.** Here there are no threads. There is work,
   and there are sittings at the computer.

## 2. The nouns

| Noun | What it is | What it is not |
|---|---|---|
| **Work** | One Rivet actor per thing to be done: initiative = task = todo. It holds the whole of it: Josh's words, the phase, effort dials, the pinned plan, each step's sticky note, tasks (now), todos (later), the log, child work, links, and done (yes or no, with evidence). It lives across many sessions. | A chat, a thread, a directory, a session |
| **Session** | **A sitting**: from when Josh sits down at the computer to when he logs off. It's time-bound. In one sitting he may touch one piece of work or ten, across clients, projects and chores. Leaving work unfinished is normal; that's how the real world works. | A project, a client, an area, a thread, a chat, a directory, infrastructure |
| **Step** | One Made Well function in the work's plan (for example lookFirst, implementation, verification). It takes input from the actor and returns output to it. | An agent |
| **Sticky note** | On each step: who works it (harness, model, effort), preferred first, the rest taking over on a limit or failure. | A fixed assignment |
| **Hand (agent)** | Claude, Codex, Pi or an agentOS program, hired for one step. Its context is the actor; its output goes back to the actor. It can be swapped at any point. | The work, or the record of it |
| **Area** | Which part of Josh's world a piece of work belongs to (a client, a side project, Rex itself, chores). It's a field on the work. | A session |

## 3. The layers and what each owns

Bottom up. Each layer owns some things and refuses others.

| Layer | Owns | Refuses |
|---|---|---|
| **Machine** (hive does all compute; the M5 is the screen) | Processes, services, disks, network | Knowing what the work is |
| **Rivet** (engine and runner on hive; agentOS) | **Holding and driving the work.** Actor state, durable workflows (steps, retries, replay), schedules (wake), queues, events pushed to listeners. agentOS runs agent-written code in a sandbox (code mode). | How anything looks; Josh's attention |
| **Rex** (server on hive, app on the M5) | **The room.** Where work is seen, navigated, started and talked about; where agents start and speak; where Josh is asked (the decision card). Lua draws views, pickers and actions. | Being the record; holding state that must survive it |
| **teerex / rexconfig** | Utilities and Josh's configuration over Rex: the board, the agent commands, hooks, keys | New concepts |
| **Made Well** (the grammar, lives inside the actor) | The shape of the work: brainstorm, discovery, delivery and land, each with an effort dial. `compositions.json` (which steps each effort prescribes) and `staffing.json` (the default sticky notes) are Josh's opinionated defaults; each actor pins them at creation. | A fixed pipeline; one-shot delivery |
| **Hands** | Doing one step: thinking and checking (Claude Opus 5.5), coding (Codex), tool-heavy steps (agentOS code mode, most likely Pi) | Owning the work; deciding they're done without evidence |

**Rex in practice** (corrected for sessions as sittings):

| Rex piece | Carries |
|---|---|
| Session (sidebar section) | **Today's sitting.** It starts when Josh sits down and ends when he logs off. |
| Tab in that session | One piece of work **touched in this sitting**. Its status dot is the work's state (working, blocked or done), painted from the actor. |
| Panes in a tab | The conversation with whoever Josh is working with, beside a Lua view of the work's actor (phase, steps, who's on each, done yes or no). |
| Floating layer, cmd+alt+] | **The phoropter**: all work across all areas and all time. It opens at the top level, and you dial in from area to work to steps to log. |
| Picker, "Open work…" | Pick any piece of work and it opens as a tab in the current sitting. This is how a new sitting resumes old work. |

Todos, parked work and finished work live only in Rivet and show in the phoropter. When a sitting ends
its tabs go away; the work stays.

## 4. Where the layers meet

1. **One set of verbs on the work**: read, log, add a task, check a step, start child work, ask Josh.
   It's one grammar, reached three ways: from a shell (`mw-work`, built), from Rex (actions and Lua,
   not built), and from an agentOS program in code mode, as host functions (not built).
2. **The driver** walks the plan and hires each step's hand. It is built as `mw-drive` in a Rex
   terminal. It belongs inside the actor as a Rivet workflow, with Rex starting hands when asked.
3. **The mark**: the actor's state is painted onto Rex (tab dots, the phoropter). It's built on the
   board, not yet on the tab.
4. **Delegation**: a hand may hand off work. The piece becomes a child work actor (`mw-work new --parent`)
   with its own driver. Hands spawn and talk only through Rex and the actor, never through a harness's
   own sub-agents. Nothing enforces it; every hand's briefing tells it the way.

## 5. The Plinko: where does a change go?

Drop the change in at the top. At each layer, ask that layer's question. If the answer is yes, that
part of the change lands there; the rest keeps falling. If a part lands in a layer whose "Refuses"
column names it, it's in the wrong place. (This order is a draft; Josh is shaping it in tldraw.)

1. **Rivet:** does it change what the work holds, how it survives, or how it moves step to step (state,
   durability, waking, retrying, pushing events, sandboxing agent code)? It goes in the actor or its
   workflow.
2. **Rex:** does it change how the work is seen, navigated, started or talked about, or how Josh is
   asked? It goes in Rex: Lua, a view, an action, a key, a status mark.
3. **teerex / rexconfig:** is it a utility or one of Josh's settings over Rex? It goes in teerex or
   rexconfig.
4. **Made Well:** does it change the shape of work (phases, steps, effort, which hand works what)? It
   goes in `compositions.json`, `staffing.json` or FOUNDATION, never in engine code.
5. **Hands:** is it about how one agent does one step? It goes in the briefing or the sticky note.

Three checks every change must pass:
- **Does it keep the work durable and the agents disposable?**
- **Does it add a chat, a thread or a message board?** If so, reshape it.
- **Does it push toward one-shotting?** If so, reshape it into steps.

## 6. Built today (21 Nov, CT)

- The work actor runs on hive's live Rivet engine (teerex `items/madewell/journal/node.mjs`), connecting
  with the engine's own token. Nothing mints tokens.
- `mw-work`: the verbs, plus the session hook. Every Claude or Codex turn streams into its pane's work.
  A pane's first prompt opens its work.
- `compositions.json` and `staffing.json`: effort sets which steps are prescribed, and each step carries
  its sticky note.
- `mw-drive`: walks the plan, hires headless hands with a Rex briefing, hands over on failure, and
  delegates child work through Rex. Proven twice, including the brainstorm review
  (`~/desk/REX-FIT.md`).
- The board lists work actors above runs (rexconfig, the board-phoropter run).

## 7. Open, in order

1. Move the driver into the actor as a Rivet workflow, so Rivet wakes, retries and survives restarts.
2. Paint each tab's status dot from the actor.
3. Add the area field, the phoropter layer and the "Open work…" picker. Sessions are sittings.
4. Code mode: the work's verbs as agentOS host functions; a code-mode hand on the sticky note.
5. The checker is never the same model as the maker (staffing guarantees it).
6. Reconcile the two drivers (last night's Lua library and `mw-drive`): the actor holds the plan, and
   Lua composes calls inside a step.
7. Brainstorm and land step names in `compositions.json` are placeholders until Josh names them.
