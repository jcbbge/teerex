"""Run the reviewed fleet controller with its exact embedded support files."""
import os
from pathlib import Path
import runpy
import signal
import sys
import tempfile


def cancelled(sig, frame):
    raise SystemExit(128 + sig)


signal.signal(signal.SIGTERM, cancelled)
# These are public source bytes, not configuration, endpoints, credentials or captured data.
controller, worker, installer, resolver = sys.argv[1:5]
arguments = sys.argv[5:]
with tempfile.TemporaryDirectory(prefix="teerex-fleet-support-") as temporary:
    root = Path(temporary)
    paths = {"tools/fleet-install/fleet_install.py": controller,
             "tools/fleet-install/worker.py": worker,
             "tools/install/teerex-install": installer,
             "src/targets.py": resolver}
    for relative, source in paths.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        path.chmod(0o700 if relative.endswith("teerex-install") else 0o600)
    entry = root / "tools/fleet-install/fleet_install.py"
    sys.argv = [str(entry), *arguments]
    runpy.run_path(str(entry), run_name="__main__")
