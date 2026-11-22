"""A project's cartridge: the project-specific setup Made Well plugs in, so the engine stays project-agnostic.

The project keeps it at .madewell/cartridge.json in its repo root:
  {"project": "arc",
   "checkpoints": [{"id": "data-loop", "steps": ["ideation", "planning"],
                    "when": "...", "ask": "...", "check": "optional command"}]}
Every hand is briefed with the checkpoints its step names, and its step is refused a yes until the
evidence carries one line per checkpoint: "checkpoint <id>: <what it found, or n/a and why>".
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


def brief(cartridge, step):
    points = for_step(cartridge, step)
    if not points:
        return ""
    lines = [f"PROJECT CHECKPOINTS for {step} ({cartridge.get('project', 'this project')}'s cartridge; "
             "your step is refused a yes without them):"]
    for p in points:
        lines.append(f"  - {p['id']}: when {p['when']}: {p['ask']}")
        if p.get("check"):
            lines.append(f"    Run: {p['check']}")
    lines.append('  Your evidence carries one line per checkpoint: "checkpoint <id>: <what you found, or n/a and why>".')
    return "\n".join(lines)


def missing(cartridge, step, evidence):
    return [p["id"] for p in for_step(cartridge, step)
            if not re.search(rf"(?im)^\s*checkpoint {re.escape(p['id'])}:\s*\S", evidence or "")]
