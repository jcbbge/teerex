"""Ground checkpoints: a project's own questions that ideation and planning must answer before they pass.

A project keeps them in .madewell/ground.json at its repo root:
  {"checkpoints": [{"id": "data-loop", "when": "...", "ask": "...", "check": "optional command"}]}
A hand on a Ground step is briefed with every checkpoint, and its step is refused a yes until the
evidence carries one line per checkpoint: "ground <id>: <what it found, or n/a and why>".
"""
import json
from pathlib import Path
import re
import subprocess

GROUND_STEPS = ("ideation", "planning")


def repo_root(cwd):
    r = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 else None


def checkpoints(cwd):
    root = repo_root(cwd)
    if not root or not (root / ".madewell/ground.json").exists():
        return []
    return json.loads((root / ".madewell/ground.json").read_text()).get("checkpoints", [])


def brief(points):
    if not points:
        return ""
    lines = ["GROUND CHECKPOINTS (this project's own; your step is refused a yes without them):"]
    for p in points:
        lines.append(f"  - {p['id']}: when {p['when']}: {p['ask']}")
        if p.get("check"):
            lines.append(f"    Run: {p['check']}")
    lines.append('  Your evidence carries one line per checkpoint: "ground <id>: <what you found, or n/a and why>".')
    return "\n".join(lines)


def missing(points, evidence):
    return [p["id"] for p in points
            if not re.search(rf"(?im)^\s*ground {re.escape(p['id'])}:\s*\S", evidence or "")]
