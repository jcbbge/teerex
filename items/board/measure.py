#!/usr/bin/env python3
"""Bounded native renderer benchmark and idle/keypress PTY measurements."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time


def cpu(pid):
    if os.uname().sysname == 'Linux':
        fields=Path('/proc/%d/stat'%pid).read_text().rsplit(')',1)[1].split()
        return (int(fields[11])+int(fields[12]))/os.sysconf('SC_CLK_TCK')
    value=subprocess.check_output(['ps','-p',str(pid),'-o','time='],text=True).strip()
    minutes,seconds=value.split(':')
    return int(minutes)*60+float(seconds)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    spec=importlib.util.spec_from_file_location('board_tests',Path(__file__).with_name('test_board.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix='board-measure-',dir='/tmp') as directory:
        root=Path(directory)
        env=dict(os.environ,TEEREX_CALL_LOG_DIR=str(root/'calls'))
        result=json.loads(subprocess.check_output([module.BIN,'board','--benchmark','10000'],env=env,text=True))
        pane=module.Pane(root)
        try:
            pane.until(lambda:b'Which sound' in pane.output)
            warmup=time.monotonic()+.5
            while time.monotonic()<warmup:pane.read(warmup-time.monotonic())
            pane.settle()
            initial=cpu(pane.proc.pid);start=time.monotonic()
            before=len(pane.output)
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:pane.read(deadline-time.monotonic())
            elapsed=time.monotonic()-start
            delta=cpu(pane.proc.pid)-initial
            idle_bytes=len(pane.output)-before
            timings=[]
            for _ in range(100):
                before=len(pane.output);start=time.perf_counter_ns()
                os.write(pane.master,b'm')
                pane.until(lambda:len(pane.output)>before and pane.output.endswith(b'\x1b[?2026l'))
                timings.append((time.perf_counter_ns()-start)/1e6)
            result.update(machine=os.uname().sysname,architecture=os.uname().machine,
                          binary_bytes=Path(module.BIN).stat().st_size,binary_sha256=hashlib.sha256(Path(module.BIN).read_bytes()).hexdigest(),idle_seconds=elapsed,
                          idle_cpu_seconds=delta,idle_cpu_percent=100*delta/elapsed,
                          idle_cpu_resolution_seconds=.01,idle_output_bytes=idle_bytes,
                          event_to_pty_ms_median=statistics.median(timings),
                          event_to_pty_ms_p95=sorted(timings)[94],
                          clear_screen_sequences=pane.output.count(b'\x1b[2J'),
                          sync_begins=pane.output.count(b'\x1b[?2026h'),
                          sync_ends=pane.output.count(b'\x1b[?2026l'))
        finally:pane.close()
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':main()
