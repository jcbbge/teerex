"""A project's cartridge: the project-specific setup Made Well plugs in, so the engine stays project-agnostic.

The project keeps it at .madewell/cartridge.json in its repo root:
  {"project": "arc",
   "checkpoints": [{"id": "data-loop", "steps": ["ideation", "planning"],
                    "when": "...", "ask": "...", "check": "optional command"}]}
Each checkpoint has a span. Ground (the default) is judgment before the work: the hand answers it in its
evidence with one line, "checkpoint <id>: <what it found, or n/a and why>". Rumen is the mechanical flip
side: a "run" command the engine itself executes in the repo root when the hand checks its step yes; a
non-zero exit refuses the step with the command's output. Every hand is briefed with both.
"""
import json
from pathlib import Path
import re
import subprocess

FILE = ".madewell/cartridge.json"


def repo_root(cwd):
    r = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def load(cwd):
    root = repo_root(cwd)
    if not root or not (root / FILE).exists():
        return {}
    return json.loads((root / FILE).read_text())


def for_step(cartridge, step):
    return [p for p in cartridge.get("checkpoints", []) if step in p.get("steps", [])]


def ground(cartridge, step):
    return [p for p in for_step(cartridge, step) if p.get("span", "ground") == "ground"]


def rumen(cartridge, step):
    return [p for p in for_step(cartridge, step) if p.get("span") == "rumen"]


def brief(cartridge, step):
    asks, runs = ground(cartridge, step), rumen(cartridge, step)
    if not asks and not runs:
        return ""
    lines = [f"PROJECT CHECKPOINTS for {step} ({cartridge.get('project', 'this project')}'s cartridge; "
             "your step is refused a yes without them):"]
    for p in asks:
        lines.append(f"  - Ground {p['id']}: when {p['when']}: {p['ask']}")
        if p.get("check"):
            lines.append(f"    Run: {p['check']}")
    if asks:
        lines.append('  Your evidence carries one line per Ground checkpoint: "checkpoint <id>: <what you found, or n/a and why>".')
    for p in runs:
        lines.append(f"  - Rumen {p['id']}: the engine runs `{p['run']}` when you check yes; a failure refuses the step. {p['ask']}")
    return "\n".join(lines)


def missing(cartridge, step, evidence):
    return [p["id"] for p in ground(cartridge, step)
            if not re.search(rf"(?im)^\s*checkpoint {re.escape(p['id'])}:\s*\S", evidence or "")]


def failures(cartridge, step, cwd):
    root = repo_root(cwd)
    out = []
    for p in rumen(cartridge, step):
        r = subprocess.run(["bash", "-lc", p["run"]], cwd=root, capture_output=True, text=True)
        if r.returncode != 0:
            tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-20:])
            out.append(f"Rumen {p['id']} (`{p['run']}`) exited {r.returncode}:\n{tail}")
    return out
