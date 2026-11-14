"""A foreground walkthrough, using the public commands and only its own panes."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile


PAGES = (
    ("Open a pane", "A pane is a terminal with an address. Open a practice pane in a new tab.\nIt only echoes messages; nothing you send here runs as a command."),
    ("Observe it", "Observe reads a pane without touching its input. You get its address,\nterminal text, and evidence about what is running. Read the capture below."),
    ("Send a line", "Send delivers one message and presses Enter. Real terminals may execute\nwhat you send, so choose the address carefully. This practice pane is safe."),
    ("Keep your place", "A scratchpad shows Now, To-do, and Done beside a worker. Write a small\ntask, open its scratchpad, then move the task to Done."),
    ("Open the board", "The board brings work on this machine together. Its rows link back to\nreal panes. This practice board uses a temporary store and opens in a new tab."),
    ("Leave it tidy", "Close the panes you opened when you finish. The tour now closes its\npractice pane, scratchpad, and board, and checks that each pane is gone."),
)


class Tour:
    def __init__(self, executable, socket, session, temp):
        self.executable, self.socket, self.session = executable, socket, session
        self.temp = Path(temp)
        self.panes = []
        self.scratch = None

    def call(self, *args, message=None):
        result = subprocess.run([self.executable, *args], input=message,
                                text=True, capture_output=True)
        try:
            receipt = (dict(path=result.stdout.strip()) if args[:2] in (("scratch", "path"), ("scratch", "init"))
                       else json.loads(result.stdout) if result.stdout else {})
        except ValueError:
            raise RuntimeError(result.stderr or result.stdout)
        # Even a failed creation may identify a pane that needs closing.
        if args[:2] == ("surfaces", "open"):
            block = (receipt.get("created") or {}).get("block_id")
            block = block or (receipt.get("actual") or {}).get("block_id")
            if block:
                self.panes.append(block)
        if result.returncode:
            raise RuntimeError(result.stderr or json.dumps(receipt))
        return receipt

    def open(self, label, *command):
        self.call("surfaces", "open", "--socket", self.socket,
                  "--session", self.session, "--layout", "tab",
                  "--label", "tour: " + label, "--", *command)
        print("Opened " + self.panes[-1], flush=True)
        return self.panes[-1]

    def target(self):
        return ("--session", self.session, "--block", self.panes[0])

    def action(self, step):
        if step == 1:
            self.open("practice", sys.executable, "-u", "-c",
                      "import sys; print('Welcome to teerex. This pane echoes your messages.', flush=True); "
                      "[print('Received: ' + line.rstrip(), flush=True) for line in sys.stdin]")
        elif step == 2:
            receipt = self.call("observe", "--socket", self.socket, *self.target(), "--tail")
            print(receipt["capture"]["content"], flush=True)
        elif step == 3:
            self.call("send", "--socket", self.socket, *self.target(), "--from", "tour",
                      "--message-file", "-", message="Hello from the tour!")
            print("Sent: Hello from the tour!", flush=True)
        elif step == 4:
            self.scratch = Path(self.call("scratch", "path", *self.target())["path"])
            self.call("scratch", "init", "--name", "Tour practice", "--purpose", "Learn teerex",
                      "--intent", "Finish the walkthrough", *self.target())
            self.call("scratch", "now", "Try the teerex tour", *self.target())
            self.open("scratchpad", self.executable, "scratch", "watch", *self.target())
            self.call("scratch", "done", *self.target(), "--proof", "Tour practice completed")
            print("Scratchpad task moved from Now to Done.", flush=True)
        elif step == 5:
            store = self.temp / "board"
            store.mkdir(mode=0o700)
            targets = self.temp / "targets.json"
            targets.write_text(json.dumps([dict(host="tour", server="unix://" + self.socket)]))
            self.open("board", self.executable, "boards", "fleet", "--store", str(store),
                      "--targets-file", str(targets))

    def cleanup(self):
        failures = []
        for block in reversed(self.panes):
            try:
                self.call("surfaces", "close", "--socket", self.socket,
                          "--session", self.session, "--pane", block)
                print("Closed and verified absent: " + block, flush=True)
            except (RuntimeError, OSError) as error:
                failures.append(str(error))
        if self.scratch:
            self.scratch.unlink(missing_ok=True)
            Path(str(self.scratch) + ".lock").unlink(missing_ok=True)
            try:
                self.scratch.parent.rmdir()
            except OSError:
                pass  # A session may contain other workers' scratchpads.
        if failures:
            raise RuntimeError("Cleanup needs attention: " + "; ".join(failures))


def main():
    executable = sys.argv.pop(1)
    parser = argparse.ArgumentParser(prog="teerex tour", description=
        "Six short pages with live practice. Enter continues; q quits and cleans up. "
        "Run on the machine whose Rex panes you want to use.")
    parser.add_argument("--socket", help="local Rex socket; defaults to REX_SERVER or the personal server")
    parser.add_argument("--session", default=os.environ.get("REX_SESSION") or os.environ.get("LC_REX_SESSION"),
                        help="session to use; defaults to the invoking Rex session")
    options = parser.parse_args()
    if not options.session:
        parser.error("run inside a Rex session, or pass --session session:UUID")
    socket = options.socket or os.environ.get("REX_SERVER")
    if not socket:
        socket = (str(Path.home() / "Library/Application Support/rex/server.sock") if sys.platform == "darwin"
                  else f"/run/user/{os.getuid()}/rex/server.sock")
    socket = socket.removeprefix("unix://")
    # Preserve normal interrupt handling during cleanup, including a second Ctrl-C.
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    previous = signal.signal(signal.SIGTERM, interrupted)
    code = 0
    try:
        with tempfile.TemporaryDirectory(prefix="teerex-tour-") as temp:
            tour = Tour(executable, socket, options.session, temp)
            try:
                for step, (title, words) in enumerate(PAGES, 1):
                    print(f"\n{step}/6 — {title}\n\n{words}\n", flush=True)
                    while True:
                        print("Enter to continue · q to quit: ", end="", flush=True)
                        answer = sys.stdin.readline()
                        if not answer or answer.strip().lower() == "q":
                            print("\nTour stopped. Cleaning up.", flush=True)
                            return 0
                        if not answer.strip():
                            break
                    tour.action(step)
                print("\nTour complete. Use teerex COMMAND --help to explore.", flush=True)
            finally:
                signal.signal(signal.SIGINT, signal.SIG_IGN)
                signal.signal(signal.SIGTERM, signal.SIG_IGN)
                tour.cleanup()
    except KeyboardInterrupt:
        print("\nTour interrupted; practice panes cleaned up.", flush=True)
        code = 130
    except (RuntimeError, OSError) as error:
        print("Tour: " + str(error), file=sys.stderr)
        code = 1
    finally:
        signal.signal(signal.SIGTERM, previous)
    return code


if __name__ == "__main__":
    sys.exit(main())
