"""Public board PTY contracts. No personal server, state, credentials or registry."""
import contextlib
import importlib.util
import io
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
from unittest import mock
from types import SimpleNamespace

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
    def __init__(self, root, width=60, fixture=FIXTURE, config=None, extra_env=None):
        self.master, self.slave = pty.openpty()
        self.saved = termios.tcgetattr(self.slave)
        self.width = width
        self.resize(width)
        env = dict(os.environ, HOME=str(root), XDG_STATE_HOME=str(root / 'state'),
                   TEEREX_CALL_LOG_DIR=str(root / 'calls'), REX_SERVER='unix:///tmp/poison-board.sock')
        env.pop('NO_COLOR', None)
        env.update(extra_env or {})
        argv = [BIN, 'board'] + (['--replay', str(fixture)] if fixture else [])
        if config: argv += ['--config', str(config)]
        self.proc = subprocess.Popen(argv, stdin=self.slave, stdout=self.slave, stderr=self.slave, env=env)
        self.output = b''
        self.until(lambda: b'jump' in self.output)
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
        p.until(lambda: b'Which sound' in p.output)
        p.settle()
        return p
    def test_held_section_order_count_broken_colour_and_no_attention(self):
        now=200000000
        rows=[dict(id='new',text='ship? newer',since=now-3600000,broken=False),dict(id='old',text='ship? older',since=now-51*3600000,broken=True)]
        path=self.root/'held.jsonl'
        path.write_text(json.dumps(dict(v=1,t=now,host='hive',kind='held',available=True,items=rows))+'\n')
        p=Pane(self.root,fixture=path);self.addCleanup(p.close)
        p.until(lambda:b'ship? newer' in p.output);p.settle()
        view=p.view()
        self.assertIn('held work · 2',view)
        self.assertLess(view.index('ship? older'),view.index('ship? newer'))
        self.assertIn('51h',view)
        self.assertNotIn(b'7501;state=blocked',p.output)
        # Supply theme evidence so problem red is selected instead of unknown ink.
        p.key(b'\x1b]10;rgb:ffff/ffff/ffff\x1b\\\x1b]11;rgb:0000/0000/0000\x1b\\\x1b]4;1;rgb:ffff/aaaa/aaaa\x1b\\')
        self.assertRegex(p.output,rb'\x1b\[31m[^\x1b]*ship\? older')
        self.assertNotRegex(p.output,rb'\x1b\[31m[^\x1b]*ship\? newer')
        result=subprocess.run([BIN,'board','--replay',str(path),'--hosts','hive','--json'],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        snapshot=json.loads(result.stdout)['hosts'][0]
        self.assertEqual(snapshot['counts']['total'],0)
        self.assertEqual(snapshot['held']['count'],len(snapshot['held']['rows']))
        self.assertEqual([r['id'] for r in snapshot['held']['rows']],['old','new'])
        # Down selects the second held row even with zero agent panes.
        p.key(b'j');self.assertIn('► ship? newer',p.view())
        p.key(b' ');self.assertNotIn('Scratchpad',p.view())

    def test_held_unavailable_is_plain_and_json_failure(self):
        path=self.root/'unavailable.jsonl'
        path.write_text(json.dumps(dict(v=1,t=1,host='hive',kind='held',available=False,items=[]))+'\n')
        p=Pane(self.root,fixture=path);self.addCleanup(p.close)
        p.until(lambda:b'held work' in p.output);p.settle()
        self.assertIn('held work · unavailable',p.view())
        self.assertNotIn(b'7501;state=blocked',p.output)
        result=subprocess.run([BIN,'board','--replay',str(path),'--hosts','hive','--json'],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,1)
        self.assertEqual(json.loads(result.stdout)['hosts'][0]['held'],dict(available=False,rows=[],count=0))

    def test_held_independent_check_detects_order_text_broken_count_and_unavailable(self):
        spec=importlib.util.spec_from_file_location('check_held',Path(__file__).with_name('check_held_source.py'))
        check=importlib.util.module_from_spec(spec);spec.loader.exec_module(check)
        rows=[dict(id='old',text='ship? old',broken=False),dict(id='new',text='ship? new',broken=True)]
        self.assertEqual(check.differences(rows,dict(available=True,rows=rows,count=2)),[])
        changed=[dict(rows[1],text='bad',broken=False),rows[0]]
        errors=check.differences(rows,dict(available=True,rows=changed,count=3))
        for word in ('ids/order','text','broken','count'):self.assertTrue(any(word in e for e in errors),errors)
        self.assertEqual(check.differences(rows,dict(available=False,rows=[],count=0)),['held work unavailable'])

    def test_layout_40(self): self.layout(40)
    def test_layout_60(self): self.layout(60)
    def test_layout_120(self): self.layout(120)
    def layout(self,width):
        p = self.pane(width=width)
        view, scrolls = screen(p.output,width)
        self.assertEqual(scrolls,0,view)
        for word in ['hive','REPLAY','cpu','mem','disk','net','needs you','working','Which sound','4/6','2/6','jump']:
            self.assertIn(word,view)
        self.assertLess(view.index('Which sound'),view.index('codex-render'))
        # The event stream was noise (Josh, 2026-11-13): no stream section and no stream key.
        self.assertNotIn('Listening for the next event',view)
        self.assertNotIn(' stream',view)
        self.assertIn(b'\x1b[?2026h',p.output)
        self.assertIn(b'7501;state=blocked:id=teerex/board',p.output)
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
        self.assertIn('Scratchpad',p.view())
        self.assertIn('three widths',p.view())
        p.key(b's'); self.assertNotIn('stream',p.view())
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
        self.assertIn('Which sound',p.view())
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
        self.assertIn('Scratchpad · codex-render',p.view())
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
        held_rows=[dict(id='held-old',project='fixture',title='Archive',waits='ship',text='ship? Archive',on='',since=1,broken=True,broken_why='fixture')]
        held_source=self.root/'held-source.json';held_source.write_text(json.dumps(dict(schema=1,generated_at=1,items=held_rows)))
        hosts['hive']['held_command']=['/bin/cat',str(held_source)]
        hosts['hive']['held_open']=['/bin/echo','opened','{id}']
        config=self.root/'hosts.json';config.write_text(json.dumps(dict(schema_version=1,hosts=hosts)))
        events.append(dict(v=1,t=200000000,host='hive',kind='held',available=True,items=held_rows))
        path=self.root/'jump.jsonl';path.write_text('\n'.join(map(json.dumps,events)))
        _,board_sid,board_anchor,_=targets['hive']
        p=self.pane(fixture=path,config=config,extra_env=dict(REX_SESSION=board_sid,REX_BLOCK=board_anchor,REX_SERVER='unix://'+hosts['hive']['socket'],TEEREX_INTERNAL_REX='rex',REX_BIN='rex'))
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
        # Held Enter creates a readable adjacent pane on the board's server;
        # its command is routed to the configured source host.
        p.key(b'm');p.key(b'j');p.key(b'j');p.key(b'\r')
        p.until(lambda:b'Opened held work' in p.output)
        rpc,board_sid,_,_=targets['hive']
        def held_panes():
            listed=json.loads(subprocess.check_output([rex,'--autostart=false','--server','unix://'+hosts['hive']['socket'],'block','ls','--session',board_sid,'--json'],timeout=5))
            return [pane for pane in listed['blocks'] if pane.get('label')=='Held work']
        panes=held_panes()
        self.assertEqual(len(panes),1)
        held_block=panes[0]['block_id']
        try:
            end=time.monotonic()+5
            while True:
                observed=subprocess.run([BIN,'--rex',rex,'observe','--socket',hosts['hive']['socket'],'--session',board_sid,'--block',held_block,'--tail'],capture_output=True,text=True,timeout=5)
                content=json.loads(observed.stdout)['capture']['content']
                if 'Press Enter to close' in content:break
                if time.monotonic()>end:self.fail(content)
                time.sleep(.05)
            self.assertIn('opened held-old',content)
        finally:
            subprocess.run([BIN,'--rex',rex,'surfaces','close','--socket',hosts['hive']['socket'],'--session',board_sid,'--pane',held_block],capture_output=True,timeout=5,check=True)
        # Finite live JSON and the independent kept check use these disposable
        # servers and a private launch registry, never the operator's state.
        registry=self.root/'.local/state/teerex-agents';registry.mkdir(parents=True)
        for name, (_, sid, target, _) in targets.items():
            (registry/(name+'.json')).write_text(json.dumps(dict(name=name,launch_id=name,target=dict(session_id=sid,block_id=target))))
        private_env=dict(os.environ,HOME=str(self.root),TEEREX_CALL_LOG_DIR=str(self.root/'calls'))
        snapshot=subprocess.run([BIN,'board','--config',str(config),'--json'],env=private_env,capture_output=True,text=True,timeout=20)
        self.assertEqual(snapshot.returncode,0,snapshot.stderr)
        data=json.loads(snapshot.stdout)
        for host in data['hosts']:
            self.assertEqual(len(host['rows']),1)
            self.assertEqual(host['rows'][0]['block'],targets[host['host']][2])
            self.assertEqual(host['counts']['total'],1)
            self.assertEqual(host['counts']['unknown'],1)
        held_check=Path(__file__).with_name('check_held_source.py')
        result=subprocess.run(['python3',str(held_check),'--config',str(config),'--teerex',BIN],env=private_env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('0 differences',result.stdout)
        self.assertEqual(data['hosts'][0]['held']['rows'],held_rows)
        self.assertIsNone(data['hosts'][1]['held'])
        check=Path(__file__).with_name('check_one_source.py')
        result=subprocess.run(['python3',str(check),'--config',str(config),'--teerex',BIN],env=private_env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('0 differences',result.stdout)
        wrapper=self.root/'inject-count'
        wrapper.write_text('#!/usr/bin/env python3\nimport json,subprocess,sys\nr=subprocess.run('+repr([BIN])+"+sys.argv[1:],capture_output=True,text=True)\nd=json.loads(r.stdout)\nd['hosts'][0]['counts']['total']+=1\nprint(json.dumps(d))\n")
        wrapper.chmod(0o700)
        result=subprocess.run(['python3',str(check),'--config',str(config),'--teerex',str(wrapper)],env=private_env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertIn('header total: rows=1 header=2',result.stdout)
        self.assertIn('1 differences',result.stdout)
        # Profile-only rows and the independent checker agree without a launch record.
        runner=self.root/'profile-runner';shutil.copy2(shutil.which('sleep'),runner)
        profile_dir=self.root/'.config/teerex';profile_dir.mkdir(parents=True)
        profiles=profile_dir/'profiles.json'
        profiles.write_text(json.dumps(dict(profiles=dict(example=dict(argv=[str(runner)])))))
        manual=subprocess.run([rex,'--autostart=false','--server','unix://'+hosts['hive']['socket'],'new','--json','manual','--',str(runner),'60'],capture_output=True,text=True,timeout=5)
        self.assertEqual(manual.returncode,0,manual.stderr)
        manual_created=json.loads(manual.stdout)
        manual_block=manual_created['initial_windows'][0]['block_ids'][0]
        snapshot=subprocess.run([BIN,'board','--config',str(config),'--json'],env=private_env,capture_output=True,text=True,timeout=20)
        self.assertEqual(snapshot.returncode,0,snapshot.stderr)
        host=next(h for h in json.loads(snapshot.stdout)['hosts'] if h['host']=='hive')
        self.assertEqual({r['block'] for r in host['rows']},{targets['hive'][2],manual_block})
        self.assertEqual(host['counts']['total'],2)
        result=subprocess.run(['python3',str(check),'--config',str(config),'--teerex',BIN],env=private_env,capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('0 differences',result.stdout)
        profiles.unlink()
        snapshot=subprocess.run([BIN,'board','--config',str(config),'--json'],env=private_env,capture_output=True,text=True,timeout=20)
        self.assertEqual(snapshot.returncode,0,snapshot.stderr)
        host=next(h for h in json.loads(snapshot.stdout)['hosts'] if h['host']=='hive')
        self.assertEqual({r['block'] for r in host['rows']},{targets['hive'][2]})
        self.assertEqual(host['counts']['total'],1)
        subprocess.run([BIN,'surfaces','close','--socket',hosts['hive']['socket'],'--session',manual_created['session_id'],'--pane',manual_block],capture_output=True,timeout=5,check=True)
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

    def test_header_counts_idle_done_and_unknown_from_rows(self):
        events=[json.loads(line) for line in FIXTURE.read_text().splitlines()]
        template=next(e for e in events if e['kind']=='agent' and e['host']=='hive')
        for state in ('idle','done','unknown'):
            events.append(dict(template,id='hive-'+state,name='agent-'+state,state=state,now=state))
        path=self.root/'counts.jsonl';path.write_text('\n'.join(map(json.dumps,events)))
        p=Pane(self.root,width=120,fixture=path);self.addCleanup(p.close)
        p.until(lambda:b'agent-unknown' in p.output);p.settle()
        view=p.view()
        self.assertIn('agents  5 total  1 ► working',view)
        self.assertIn('idle 1  wait 1  error 0  done 1',view)
        self.assertIn('unknown 1',view)
        for state in ('idle','done','unknown'):self.assertIn('agent-'+state,view)

    def test_json_counts_match_filtered_rows(self):
        events=[json.loads(line) for line in FIXTURE.read_text().splitlines()]
        template=next(e for e in events if e['kind']=='agent' and e['host']=='hive')
        for state in ('idle','done','unknown','blocked','error'):
            events.append(dict(template,id='hive-'+state,name='agent-'+state,state=state))
        path=self.root/'json-counts.jsonl';path.write_text('\n'.join(map(json.dumps,events)))
        result=subprocess.run([BIN,'board','--replay',str(path),'--hosts','hive','--json'],env=dict(os.environ,TEEREX_CALL_LOG_DIR=str(self.root/'calls')),capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        hosts=json.loads(result.stdout)['hosts']
        self.assertEqual(len(hosts),1)
        snapshot=hosts[0]
        self.assertTrue(all(row['host']=='hive' for row in snapshot['rows']))
        self.assertEqual(snapshot['counts'],dict(total=7,working=1,waiting=1,blocked=1,error_count=1,idle=1,done=1,unknown=1))
        self.assertEqual(snapshot['counts']['total'],len(snapshot['rows']))

    def test_check_retries_in_flux_panes_and_reports_only_last_run(self):
        spec=importlib.util.spec_from_file_location('check_one_source',Path(__file__).with_name('check_one_source.py'))
        check=importlib.util.module_from_spec(spec);spec.loader.exec_module(check)
        row=dict(block='changing',session='session',state='working')
        def packet(rows):
            counts=dict(total=len(rows),working=len(rows),waiting=0,blocked=0,error_count=0,idle=0,done=0,unknown=0)
            return SimpleNamespace(returncode=0,stdout=json.dumps(dict(hosts=[dict(host='hive',rows=rows,counts=counts,reachable=True)])))
        for before in ([], [dict(row,state='idle')]):
            with self.subTest(before=before), mock.patch.object(check.targets,'load_config',return_value=dict(hosts=dict(hive={}))), mock.patch.object(check,'rex_rows',side_effect=[before,[row],[row],[row]]) as rex, mock.patch.object(check.subprocess,'run',side_effect=[packet(before),packet([row])]) as board:
                out=io.StringIO()
                with contextlib.redirect_stdout(out): code=check.main(['--config','/unused'])
                self.assertEqual(code,0,out.getvalue())
                self.assertEqual(rex.call_count,4)
                self.assertEqual(board.call_count,2)
                self.assertIn('1 reruns',out.getvalue())
                self.assertIn('0 differences',out.getvalue())
                self.assertNotIn('DIFF',out.getvalue())

    def test_check_settled_mismatch_fails_without_retry(self):
        spec=importlib.util.spec_from_file_location('check_one_source',Path(__file__).with_name('check_one_source.py'))
        check=importlib.util.module_from_spec(spec);spec.loader.exec_module(check)
        row=dict(block='settled',session='session',state='working')
        snapshot=dict(host='hive',rows=[],counts=dict(total=0,working=0,waiting=0,blocked=0,error_count=0,idle=0,done=0,unknown=0),reachable=True)
        with mock.patch.object(check.targets,'load_config',return_value=dict(hosts=dict(hive={}))), mock.patch.object(check,'rex_rows',side_effect=[[row],[row]]), mock.patch.object(check.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(dict(hosts=[snapshot])))) as board:
            out=io.StringIO()
            with contextlib.redirect_stdout(out): code=check.main(['--config','/unused'])
        self.assertEqual(code,1)
        self.assertEqual(board.call_count,1)
        self.assertIn('0 reruns',out.getvalue())
        self.assertIn('DIFF hive: missing board row settled',out.getvalue())
        self.assertIn('1 differences',out.getvalue())

    def test_check_flux_is_bounded_and_keeps_settled_differences(self):
        spec=importlib.util.spec_from_file_location('check_one_source',Path(__file__).with_name('check_one_source.py'))
        check=importlib.util.module_from_spec(spec);spec.loader.exec_module(check)
        settled=dict(block='settled',session='session',state='working')
        changing=dict(block='changing',session='session',state='idle')
        snapshot=dict(host='hive',rows=[],counts=dict(total=0,working=0,waiting=0,blocked=0,error_count=0,idle=0,done=0,unknown=0),reachable=True)
        with mock.patch.object(check.targets,'load_config',return_value=dict(hosts=dict(hive={}))), mock.patch.object(check,'rex_rows',side_effect=[[settled],[settled,changing]]*3) as rex, mock.patch.object(check.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(dict(hosts=[snapshot])))) as board:
            out=io.StringIO()
            with contextlib.redirect_stdout(out): code=check.main(['--config','/unused'])
        self.assertEqual(code,1)
        self.assertEqual(rex.call_count,6)
        self.assertEqual(board.call_count,3)
        self.assertIn('2 reruns',out.getvalue())
        self.assertEqual(out.getvalue().count('missing board row settled'),1)
        self.assertIn('missing board row changing',out.getvalue())
        self.assertIn('2 differences',out.getvalue())

    def test_gone_removes_rows(self):
        events=[json.loads(line) for line in FIXTURE.read_text().splitlines()]
        for e in list(events):
            if e['kind']=='agent': events.append(dict(e,state='gone'))
        path=self.root/'gone.jsonl';path.write_text('\n'.join(map(json.dumps,events)))
        result=subprocess.run([BIN,'board','--replay',str(path),'--once'],env=dict(os.environ,TEEREX_CALL_LOG_DIR=str(self.root/'calls')),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('No agents working',result.stdout)
        self.assertNotIn('Which sound',result.stdout)


if __name__=='__main__': unittest.main()
