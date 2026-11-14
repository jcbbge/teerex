#!/usr/bin/env python3
"""Feed 2,000 fixture call events through a real local feed and board PTY.

Uses only a disposable Rex server. RSS samples are KiB, per process, every 100
acknowledged feed events. The PTY is continuously drained (no capture backlog).
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import pty
import queue
import select
import shutil
import struct
import subprocess
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]


def rss(pid):
    return int(subprocess.check_output(['ps', '-p', str(pid), '-o', 'rss='], text=True).strip())


def cpu(pid):
    if os.uname().sysname=='Linux':
        fields=Path('/proc/%d/stat'%pid).read_text().rsplit(')',1)[1].split()
        return (int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK')
    value=subprocess.check_output(['ps','-p',str(pid),'-o','time='],text=True).strip()
    minutes,seconds=value.split(':')
    return int(minutes)*60+float(seconds)


def measure():
    binary = os.environ.get('TEEREX_BIN', str(ROOT/'zig-out/bin/teerex'))
    rex = os.environ.get('REX_BIN') or shutil.which('rex')
    with tempfile.TemporaryDirectory(prefix='board-memory-', dir='/tmp') as tmp:
        root = Path(tmp)
        socket = root/'rex.sock'
        fifo = root/'events'
        os.mkfifo(fifo)
        calls = root/'calls'
        calls.mkdir()
        env = dict(os.environ, HOME=tmp, TEEREX_CALL_LOG_DIR=str(root/'own-calls'))
        master, slave = pty.openpty()
        fcntl.ioctl(slave, __import__('termios').TIOCSWINSZ, struct.pack('HHHH',30,60,0,0))
        children = []
        drained = threading.Event()
        def drain():
            while not drained.is_set():
                try:
                    if select.select([master], [], [], .05)[0]: os.read(master, 65536)
                except OSError: return
        threading.Thread(target=drain, daemon=True).start()
        try:
            server = subprocess.Popen([rex,'server','run','--listen','unix://'+str(socket),'--restore=false','--config','/dev/null','--state-dir',str(root/'rex-state')], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            children.append(server)
            deadline = time.monotonic()+10
            while not socket.exists():
                if time.monotonic()>deadline: raise RuntimeError('disposable server did not start')
                time.sleep(.01)
            feed = subprocess.Popen([binary,'board','feed','--local','--host-name','hive','--socket',str(socket),'--rex',rex,'--calls',str(calls)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
            children.append(feed)
            events = queue.Queue()
            def relay():
                with open(fifo, 'wb', buffering=0) as out:
                    out.write((ROOT/'items/board/fixture.jsonl').read_bytes())
                    for line in feed.stdout:
                        try: out.write(line)
                        except BrokenPipeError: return
                        if json.loads(line).get('kind')=='stream':
                            # Pace the renderer independently of filesystem notifications.
                            time.sleep(.002)
                            events.put(1)
            threading.Thread(target=relay, daemon=True).start()
            board = subprocess.Popen([binary,'board','--replay',str(fifo),'--no-graphics'], stdin=slave, stdout=slave, stderr=slave, env=env)
            children.append(board)
            samples = []
            with open(calls/'fixture.jsonl', 'w', buffering=1) as source:
                for i in range(100,2001,100):
                    source.write(''.join(json.dumps(dict(command='send',fixture=j))+'\n' for j in range(i-99,i+1)))
                    for _ in range(100): events.get(timeout=10)
                    if i%100==0:
                        table = subprocess.check_output(['ps','-axo','pid=,ppid=,rss=,comm='],text=True)
                        known = {board.pid:'board', feed.pid:'python_feed', server.pid:'rex_server'}
                        rows = [line.split(None,3) for line in table.splitlines()]
                        pending = [feed.pid]
                        descendants = []
                        while pending:
                            parent = pending.pop()
                            for row in rows:
                                if int(row[1])==parent:
                                    pending.append(int(row[0])); descendants.append(dict(pid=int(row[0]),rss_kib=int(row[2]),command=row[3]))
                        samples.append(dict(events=i, board_cpu_seconds=cpu(board.pid), **{name:rss(pid) for pid,name in known.items()}, children=descendants))
            board_cpu_seconds=cpu(board.pid)
            os.write(master,b'q'); board.wait(timeout=5)
            return dict(machine=os.uname().sysname, board_cpu_seconds=board_cpu_seconds, samples=samples)
        finally:
            for child in reversed(children):
                if child.poll() is None: child.terminate()
                try: child.wait(timeout=5)
                except subprocess.TimeoutExpired: child.kill();child.wait()
            drained.set()
            os.close(master);os.close(slave)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    result=measure()
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
