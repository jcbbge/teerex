"""Public board PTY contracts. No personal server, state, credentials or registry."""
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import shutil
import select
import signal
import struct
import subprocess
import tempfile
import termios
import time
import unicodedata
import unittest

ROOT = Path(__file__).resolve().parents[2]
BIN = str(Path(os.environ.get('TEEREX_BIN', ROOT / 'zig-out/bin/teerex')).resolve())
FIXTURE = Path(__file__).with_name('fixture.jsonl')


def screen(data, width, height=30):
    """Interpret cursor/erase operations, rather than asserting on scrollback text."""
    grid = [[' '] * width for _ in range(height)]
    row = col = 0
    scrolls = 0
    decoded = data.decode('utf-8', 'replace')
    i = 0
    while i < len(decoded):
        c = decoded[i]
        if c == '\x1b':
            if i + 1 >= len(decoded): break
            if decoded[i + 1] in ']_P':
                match = re.search('\x07|\x1b\\\\', decoded[i + 2:])
                if not match: break
                i += 2 + match.end()
                continue
            match = re.match(r'\x1b\[([0-9;?<]*)([@-~])', decoded[i:])
            if match:
                params, final = match.groups()
                values = [int(v or 0) for v in params.split(';')] if not any(x in params for x in '?<') else []
                if final in 'Hf':
                    row = max(0, (values[0] or 1) - 1) if values else 0
                    col = max(0, (values[1] or 1) - 1) if len(values) > 1 else 0
                elif final == 'K' and row < height:
                    grid[row][min(col,width):] = [' '] * max(0, width - col)
                elif final == 'J' and values == [2]:
                    grid = [[' '] * width for _ in range(height)]
                i += match.end()
                continue
            i += 2
            continue
        if c == '\r': col = 0
        elif c == '\n': row += 1
        elif ord(c) >= 32 and not unicodedata.combining(c):
            cw = 2 if unicodedata.east_asian_width(c) in 'WF' else 1
            if col + cw > width:
                col = 0
                row += 1
            if row >= height:
                scrolls += 1
                row = height - 1
                grid.pop(0)
                grid.append([' '] * width)
            if col < width:
                grid[row][col] = c
                if cw == 2 and col+1 < width: grid[row][col+1] = ''
            col += cw
        i += 1
    return '\n'.join(''.join(line).rstrip() for line in grid), scrolls


class Pane:
    def __init__(self, root, width=60, fixture=FIXTURE, config=None, env_overrides=None):
        self.master, self.slave = pty.openpty()
        self.saved = termios.tcgetattr(self.slave)
        self.width = width
        self.resize(width)
        env = dict(os.environ, HOME=str(root), XDG_STATE_HOME=str(root / 'state'),
                   TEEREX_CALL_LOG_DIR=str(root / 'calls'), REX_SERVER='unix:///tmp/poison-board.sock')
        env.update(env_overrides or {})
        env.pop('NO_COLOR', None)
        argv = [BIN, 'board'] + (['--replay', str(fixture)] if fixture else [])
        if config: argv += ['--config', str(config)]
        self.proc = subprocess.Popen(argv, stdin=self.slave, stdout=self.slave, stderr=self.slave, env=env)
        self.output = b''
        self.until(lambda: b'working' in self.output)
    def resize(self, width, height=30):
        self.width = width
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack('HHHH', height, width, 0, 0))
        if hasattr(self, 'proc'): self.proc.send_signal(signal.SIGWINCH)
    def read(self, timeout=.1):
        if select.select([self.master], [], [], timeout)[0]:
            try: self.output += os.read(self.master, 65536)
            except OSError: pass
    def until(self, predicate, seconds=5):
        end = time.monotonic() + seconds
        while not predicate():
            if time.monotonic() >= end:
                raise AssertionError('PTY deadline: ' + repr(self.output[-2000:]))
            self.read(min(.1, max(0, end-time.monotonic())))
    def settle(self):
        while select.select([self.master], [], [], .08)[0]: self.read(0)
    def key(self, key):
        os.write(self.master, key)
        self.read(.5)
        self.settle()
    def view(self): return screen(self.output, self.width)[0]
    def close(self):
        if self.proc.poll() is None:
            os.write(self.master,b'q')
            try: self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill(); self.proc.wait(); raise
        self.read(0)
        restored = termios.tcgetattr(self.slave)
        # Darwin sets PENDIN when canonical input is restored; Python's tty
        # does the same. Compare settings, excluding that kernel pending bit.
        saved = list(self.saved)
        if os.uname().sysname == 'Darwin':
            restored[3] &= ~termios.PENDIN
            saved[3] &= ~termios.PENDIN
        os.close(self.master); os.close(self.slave)
        if restored != saved: raise AssertionError('terminal mode not restored')
        if self.proc.returncode != 0: raise AssertionError(self.output[-2000:])


class BoardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tboard-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
    def pane(self, **kw):
        p = Pane(self.root, **kw)
        self.addCleanup(p.close)
        p.until(lambda: b'codex-render' in p.output)
        p.settle()
        return p
    def test_layout_40(self): self.layout(40)
    def test_layout_60(self): self.layout(60)
    def test_layout_120(self): self.layout(120)
    def layout(self,width):
        p = self.pane(width=width)
        view, scrolls = screen(p.output,width)
        self.assertEqual(scrolls,0,view)
        for word in ['hive','REPLAY','cpu','mem','disk','net','working','◇ 1','Choose','4/6','2/6','jump']:
            self.assertIn(word,view)
        self.assertNotIn('needs you',view)
        self.assertNotIn('stream',view)
        self.assertIn(b'\x1b[?2026h',p.output)
        self.assertNotIn(b'7501;state=blocked',p.output)
        self.assertNotIn(b'\x1b[2J',p.output)
        self.assertNotRegex(p.output,rb'\x1b\[(?:38|48);(?:2|5);')
        if width==120:
            self.assertIn('cores',view)
            self.assertIn('cpu 14.3%',view)
            self.assertIn('m5',view)
    def test_keys_host_help_scratchpad_and_resize(self):
        p=self.pane()
        p.key(b'm'); self.assertIn('m5  REPLAY',p.view())
        p.key(b'?'); self.assertIn('double-click jumps',p.view())
        p.key(b'?'); p.key(b'j'); p.key(b' ')
        self.assertIn('end:',p.view())
        self.assertIn('← now',p.view())
        self.assertIn('end: —',p.view())
        self.assertIn('■ 14 closed',p.view())
        self.assertIn('⇥ teerex',p.view())
        p.key(b' '); self.assertNotIn('end:',p.view())
        p.key(b'd'); self.assertIn('Which sound',p.view())
        self.assertIn('← default',p.view())
        p.key(b'\r'); self.assertIn('No open decisions',p.view())
        p.key(b'\x1b'); self.assertNotIn('No open decisions',p.view())
        p.resize(40)
        p.until(lambda: len(p.output)>0 and b'\x1b[30;1H' in p.output)
        p.settle()
        self.assertIn('jump',p.view())
    def test_idle_blocks_and_does_not_redraw(self):
        p=self.pane()
        # Let the single 180 ms attention flash expire before idle measurement.
        p.read(.3); p.settle()
        before=len(p.output)
        self.assertFalse(select.select([p.master],[],[],.3)[0])
        self.assertEqual(len(p.output),before)
        self.assertIsNone(p.proc.poll())
    def test_fragmented_palette_and_graphics_responses(self):
        p=self.pane()
        # A deliberately low contrast red slot must fall back to default ink.
        palette=b'\x1b]10;rgb:ffff/ffff/ffff\x1b\\\x1b]11;rgb:0000/0000/0000\x1b\\\x1b]4;1;rgb:0101/0101/0101\x1b\\\x1b]4;6;rgb:aaaa/ffff/ffff\x1b\\'
        p.key(palette[:7]); p.key(palette[7:])
        start=len(p.output)
        p.key(b'\x1b_Gi=31;OK\x1b\\')
        self.assertIn(b'a=T,f=32',p.output[start:])
        self.assertIn(b'\x1b[39m',p.output)
        self.assertIn('Choose',p.view())
    def test_mouse_selects_and_controls_cannot_escape(self):
        events=[json.loads(line) for line in FIXTURE.read_text().splitlines()]
        for e in events:
            if e.get('name')=='codex-render': e['now']='safe\x1b]52;c;STEAL\x07\nend 安全'
        path=self.root/'bad.jsonl';path.write_text('\n'.join(map(json.dumps,events)))
        p=self.pane(fixture=path)
        self.assertNotIn(b'\x1b]52;c;STEAL',p.output)
        # Click the working row, then expand its scratchpad.
        row=next(i+1 for i,line in enumerate(p.view().splitlines()) if 'codex-render' in line)
        p.key(('\x1b[<0;5;%dM'%row).encode());p.key(b' ')
        self.assertIn('end:',p.view())
    def test_eof_and_signal_restore_terminal(self):
        p=self.pane()
        self.assertIsNone(p.proc.poll())
        p.proc.send_signal(signal.SIGTERM)
        p.proc.wait(timeout=3)
        self.assertEqual(p.proc.returncode,0)
    def test_invalid_events_visible_and_once_nonzero(self):
        path=self.root/'invalid.jsonl'
        path.write_text('{bad}\n'+json.dumps(dict(v=2,t=123,host='hive',kind='agent'))+'\n')
        result=subprocess.run([BIN,'board','--replay',str(path),'--once'],env=dict(os.environ,TEEREX_CALL_LOG_DIR=str(self.root/'calls')),capture_output=True)
        self.assertEqual(result.returncode,1)
        self.assertIn(b'2 unreadable events',result.stdout)
    def test_jump_uses_selected_named_server_and_reads_scratchpad(self):
        rex=str(Path(os.environ.get('REX_BIN') or shutil.which('rex') or 'MISSING_REX').resolve())
        hosts={}
        events=[json.loads(line) for line in FIXTURE.read_text().splitlines()]
        targets={}
        for name in ['hive','m5']:
            root=self.root/name;root.mkdir()
            socket=root/'rex.sock'
            log=(root/'server.log').open('w');self.addCleanup(log.close)
            proc=subprocess.Popen([rex,'server','run','--listen','unix://'+str(socket),'--restore=false','--config','/dev/null','--state-dir',str(root/'server')],stdout=log,stderr=log)
            def stop(proc=proc):
                proc.terminate()
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
            self.addCleanup(stop)
            end=time.monotonic()+5
            while not socket.exists():
                if proc.poll() is not None or time.monotonic()>end:raise AssertionError((root/'server.log').read_text())
                time.sleep(.02)
            base=[rex,'--autostart=false','--server','unix://'+str(socket),'api','call']
            def rpc(method,args,base=base):
                return json.loads(subprocess.check_output(base+[method,json.dumps(args)],timeout=5))
            sid=rpc('session.create',dict(label='board disposable '+name))['session_id']
            env=dict(os.environ,TEEREX_CALL_LOG_DIR=str(root/'calls'),XDG_STATE_HOME=str(root/'state'))
            def open_pane(label):
                return json.loads(subprocess.check_output([BIN,'--rex',rex,'surfaces','open','--socket',str(socket),'--session',sid,'--layout','tab','--label',label,'--','/bin/sh','-c','sleep 60'],env=env,stderr=subprocess.DEVNULL,timeout=10))['actual']['block_id']
            target=open_pane('target')
            other=open_pane('other')
            targets[name]=(rpc,sid,target,other)
            hosts[name]=dict(host_id=name,transport='local',home=str(self.root),platform='macos-arm64' if os.uname().sysname=='Darwin' else 'linux-x86_64',socket=str(socket),rex=rex,teerex=BIN,store=str(root/'store'))
            for e in events:
                if e['host']==name and e['kind']=='agent':e.update(session=sid,block=target)
            pad=self.root/'.local/state/teerex/scratch'/sid/(target+'.md')
            pad.parent.mkdir(parents=True)
            pad.write_text('# target\nPurpose: board test\nIntent: inline scratchpad\nUpdated: 2026-11-13T19:00:00Z\n\n## Now\n- [ ] Complete board test\n\n## To-do\n- [ ] Check complete scratchpad\n\n## Done\n- [x] Started private Rex\n')
        config=self.root/'hosts.json';config.write_text(json.dumps(dict(schema_version=1,hosts=hosts)))
        path=self.root/'jump.jsonl';path.write_text('\n'.join(map(json.dumps,events)))
        p=self.pane(fixture=path,config=config)
        # Switch away first so Enter must change the server's active window.
        p.key(b'm')
        p.key(b'\r')
        p.until(lambda:b'Jumped to pane' in p.output)
        rpc,sid,target,_=targets['m5']
        view=rpc('session.view',dict(session_id=sid))
        active=next(w for w in view['windows'] if w['window_id']==view['active_window_id'])
        self.assertEqual(active['focused_block_id'],target)
        p.key(b' ')
        self.assertIn('Check complete scratchpad',p.view())
        self.assertIn('Started private Rex',p.view())
        # The normal entrypoint must start the integrated feed, receive vitals,
        # and reap its foreground feed children when the board exits.
        live=Pane(self.root,fixture=None,config=config)
        self.addCleanup(live.close)
        live.until(lambda:b'net  ' in live.output,seconds=8)
        self.assertIn('LIVE',live.view())
        live.key(b'm');live.until(lambda:'m5  LIVE' in live.view(),seconds=5)
        processes={int(pid):int(ppid) for pid,ppid in (line.split() for line in subprocess.check_output(['ps','-axo','pid=,ppid='],text=True).splitlines())}
        descendants={live.proc.pid}
        for _ in range(10):
            expanded=descendants|{pid for pid,ppid in processes.items() if ppid in descendants}
            if expanded==descendants:break
            descendants=expanded
        descendants.discard(live.proc.pid)
        self.assertTrue(descendants,'integrated feed process was not observed')
        live.key(b'q');live.proc.wait(timeout=5)
        for pid in descendants:
            try:os.kill(pid,0)
            except ProcessLookupError:continue
            self.fail('board left feed descendant alive: %d'%pid)

    def test_wait_edges_and_stalled_idle(self):
        events=[json.loads(line) for line in FIXTURE.read_text().splitlines()]
        for event in events:
            if event.get('name')=='teerex':
                event.update(waiting=dict(on='codex-render',what='render proof',since='2026-11-13T18:58:00Z'),wait_age_ms=120000)
            elif event.get('name')=='codex-render':
                event.update(state='idle',now=None,waiting=None)
        path=self.root/'wait.jsonl';path.write_text('\n'.join(map(json.dumps,events)))
        p=self.pane(fixture=path,width=120)
        self.assertIn('⧗ codex-render · render proof · 2m · stalled',p.view())
        self.assertIn('stalled · waiting on nothing',p.view())
        self.assertIn(b'\x1b[31m',p.output)
        # A working target makes the wait calm; an unknown target is broken.
        for event in events:
            if event.get('name')=='codex-render':event.update(state='working',now='Render')
        path.write_text('\n'.join(map(json.dumps,events)))
        calm=self.pane(fixture=path,width=120)
        self.assertIn('⧗ codex-render · render proof · 2m',calm.view())
        self.assertNotIn('stalled',calm.view())
        self.assertNotIn(b'\x1b[31m',calm.output)

    def test_decision_digit_and_default(self):
        p=self.pane()
        p.key(b'd');self.assertIn('Which sound',p.view())
        p.key(b'9');self.assertIn('Which sound',p.view())
        p.key(b'1');self.assertIn('No open decisions',p.view())
        p.key(b'\x1b');self.assertIn('◇ 0',p.view())

    def test_ratio_restore_after_pane_insert(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('board_ratio',Path(__file__).with_name('ratio.py'))
        ratio=importlib.util.module_from_spec(spec);spec.loader.exec_module(ratio)
        rex=os.environ.get('REX_BIN') or shutil.which('rex')
        self.assertTrue(rex,'explicit disposable-capable Rex required')
        socket=self.root/'ratio.sock';endpoint='unix://'+str(socket)
        log=(self.root/'ratio.log').open('w');self.addCleanup(log.close)
        server=subprocess.Popen([rex,'server','run','--listen',endpoint,'--restore=false','--config','/dev/null','--state-dir',str(self.root/'rex-state')],stdout=log,stderr=log)
        self.addCleanup(lambda:(server.terminate(),server.wait(timeout=5)))
        end=time.monotonic()+5
        while not socket.exists():
            if server.poll() is not None or time.monotonic()>end:self.fail('disposable Rex did not start')
            time.sleep(.02)
        base=[rex,'--autostart=false','--server',endpoint]
        def run(*args):return json.loads(subprocess.check_output(base+list(args),timeout=5))
        created=run('new','board-ratio','--json','--','/bin/sh','-c','sleep 60')
        sid=created['session_id'];anchor=created['initial_windows'][0]['block_ids'][0]
        board=run('split','--session',sid,'--block',anchor,'--ratio','33','--json','--','/bin/sh','-c','sleep 60')['block_ids'][0]
        def width():
            view=run('api','call','session.view',json.dumps(dict(session_id=sid)))
            def find(node):
                if node.get('block_id')==board:return node['rect'][2]
                if node.get('split'):
                    return find(node['split']['before']) or find(node['split']['after'])
            return next(w for window in view['windows'] for layer in window['layers'] if (w:=find(layer['layout'])) is not None)
        run('split','--session',sid,'--block',anchor,'--json','--','/bin/sh','-c','sleep 60')
        # Rex can change the outer split to 50%; emulate that documented failure
        # after the real insertion, then use the exact helper embedded by board.
        run('api','call','session.resize_pane',json.dumps(dict(session_id=sid,direction='horizontal',before_block_id=anchor,after_block_id=board,ratio=.5)))
        self.assertAlmostEqual(width(),.5,places=3)
        config=self.root/'ratio-hosts.json'
        config.write_text(json.dumps(dict(schema_version=1,hosts=dict(hive=dict(host_id='hive',transport='local',home=str(self.root),platform='macos-arm64' if os.uname().sysname=='Darwin' else 'linux-x86_64',socket=str(socket),rex=rex,teerex=BIN,store=str(self.root/'store'))))))
        live=Pane(self.root,fixture=None,config=config,env_overrides=dict(REX_SESSION=sid,REX_BLOCK=board,REX_SERVER=endpoint,REX_BIN=rex))
        self.addCleanup(live.close)
        self.assertAlmostEqual(width(),1/3,places=3)
        run('api','call','session.resize_pane',json.dumps(dict(session_id=sid,direction='horizontal',before_block_id=anchor,after_block_id=board,ratio=.5)))
        live.resize(70)
        live.until(lambda:abs(width()-1/3)<.001)
        self.assertAlmostEqual(width(),1/3,places=3)
        ratio.restore(base,sid,board)
        self.assertAlmostEqual(width(),1/3,places=3)

    def test_gone_and_done_remove_rows(self):
        events=[json.loads(line) for line in FIXTURE.read_text().splitlines()]
        for e in list(events):
            if e['kind']=='agent': events.append(dict(e,state='gone' if e['state']=='working' else 'done'))
        path=self.root/'gone.jsonl';path.write_text('\n'.join(map(json.dumps,events)))
        result=subprocess.run([BIN,'board','--replay',str(path),'--once'],env=dict(os.environ,TEEREX_CALL_LOG_DIR=str(self.root/'calls')),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('No agents working',result.stdout)
        self.assertNotIn('Choose',result.stdout)


if __name__=='__main__': unittest.main()
