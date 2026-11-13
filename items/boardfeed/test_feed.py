"""Read-only sources and disposable API13 servers; never personal state."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

SOURCE=Path(__file__).with_name('feed.py')
spec=importlib.util.spec_from_file_location('feed',SOURCE)
feed=importlib.util.module_from_spec(spec);spec.loader.exec_module(feed)
REX=os.environ.get('REX_BIN') or shutil.which('rex')

class FeedTests(unittest.TestCase):
    def test_native_watcher_existing_and_new_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);w=feed.Watcher([root/'new'])
            try:
                (root/'new').mkdir();self.assertTrue(w.wait(2))
                (root/'new'/'state.json').write_text('{}');self.assertTrue(w.wait(2))
                self.assertFalse(w.wait(.05))
            finally:w.close()

    @unittest.skipUnless(sys.platform=='linux','Linux proc fixture')
    def test_proc_deltas_and_agent_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'net').mkdir();(p/'self').mkdir()
            (p/'stat').write_text('cpu 10 0 10 80 0 0 0 0\ncpu0 10 0 10 80 0 0 0 0\n')
            (p/'meminfo').write_text('MemTotal: 1000 kB\nMemAvailable: 400 kB\nSwapTotal: 100 kB\nSwapFree: 25 kB\n')
            (p/'loadavg').write_text('1.0 2.0 3.0 1/2 3')
            (p/'self/mounts').write_text('/dev/root / ext4 rw 0 0\nproc /proc proc rw 0 0\n')
            (p/'net/dev').write_text('header\nheader\neth0: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0\n')
            for pid,ppid in [(11,1),(12,11)]:
                (p/str(pid)).mkdir();fields=['S',str(ppid)]+['0']*20;fields[11]='10';fields[19]='100';fields[21]='2'
                (p/str(pid)/'stat').write_text(str(pid)+' (agent child) '+' '.join(fields))
            v=feed.LinuxVitals(p);first=v.sample({11:'worker'})
            (p/'stat').write_text('cpu 30 0 30 140 0 0 0 0\ncpu0 30 0 30 140 0 0 0 0\n')
            second=v.sample({11:'worker'})
            self.assertEqual(second['cpu'],[40]);self.assertEqual(second['mem']['used'],600*1024)
            self.assertEqual(second['swap']['used'],75*1024);self.assertEqual(len(second['disks']),1)
            self.assertEqual(first['top'][0]['agent'],'worker');self.assertEqual(first['top'][0]['rss'],4*os.sysconf('SC_PAGE_SIZE'))

    def test_native_metrics(self):
        v=feed.LinuxVitals() if sys.platform=='linux' else feed.MacVitals()
        a=v.sample({});b=v.sample({})
        self.assertGreater(a['mem']['total'],0);self.assertTrue(b['cpu']);self.assertTrue(b['disks'])
        self.assertTrue(all(0<=x<=100 for x in b['cpu']))

    def test_registry_scratch_calls_and_removal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            class Args:pass
            a=Args();a.host='fixture';a.rex='/not-found';a.socket=str(root/'none')
            for field in ('agents_registry','jobs_registry','scratch','calls'):
                setattr(a,field,root/field);getattr(a,field).mkdir()
            session='session:11111111-1111-1111-1111-111111111111';block='block:22222222-2222-2222-2222-222222222222'
            (a.scratch/session).mkdir();pad=a.scratch/session/(block+'.md')
            pad.write_text('## Now\n- [ ] Build feed\n## To-do\n- [ ] Test\n## Done\n- [x] Read\n')
            path=a.agents_registry/'agents-fixture.json'
            path.write_text(json.dumps(dict(launch_id='fixture',name='worker',phase='brief_submitted',target=dict(session_id=session,block_id=block),token='DO NOT PRINT')))
            state=feed.State(a);out=io.StringIO()
            with contextlib.redirect_stdout(out):
                state.scan();state.scan()
                (a.jobs_registry/'state.json').write_text(json.dumps(dict(entries=[dict(owner='worker',session_id=session,block_id=block)])))
                state.scan()
                pad.write_text('## Now\n- [ ] Test feed\n');state.scan()
                (a.calls/'calls.jsonl').write_text(json.dumps(dict(phase='start',call_id='one',verb='send',body='SECRET'))+'\n'+json.dumps(dict(phase='end',call_id='one',exit=0))+'\n');state.scan()
                (a.jobs_registry/'state.json').unlink();path.unlink();state.scan()
            rows=[json.loads(x) for x in out.getvalue().splitlines()]
            agents=[r for r in rows if r['kind']=='agent']
            self.assertEqual(len(agents),3);self.assertEqual(agents[0]['total'],3);self.assertEqual(agents[-1]['state'],'gone')
            self.assertIn('message delivered',out.getvalue());self.assertNotIn('SECRET',out.getvalue());self.assertNotIn('DO NOT PRINT',out.getvalue())

    def test_status_and_title_projection(self):
        class Args:host='fixture'
        state=feed.State(Args());state.scan=lambda:None
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            state.rex_event(dict(type='session_event',payload=dict(event=dict(type='block_event',payload=dict(block_id='b',name='program_status_changed',payload=dict(id='',record=dict(state='blocked',msg='Which option?')))))))
            state.rex_event(dict(type='session_event',payload=dict(event=dict(type='block_label_changed',payload={}))))
        self.assertEqual(state.status['b'],'waiting');self.assertEqual(state.questions['b'],'Which option?');self.assertIn('title changed',out.getvalue())

    def test_unreachable_host_is_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake=Path(tmp)/'exec';fake.write_text('#!/bin/sh\nexit 1\n');fake.chmod(0o700)
            class Args:pass
            a=Args();a.executable=str(fake);a.config=str(Path(tmp)/'config');a.hosts='absent'
            out=io.StringIO()
            with contextlib.redirect_stdout(out):feed.merge(a)
            event=json.loads(out.getvalue());self.assertFalse(event['reachable']);self.assertEqual(event['host'],'absent')

    @unittest.skipUnless(REX,'explicit Rex executable required')
    def test_disposable_rex_push_and_filesystem_changes(self):
        with tempfile.TemporaryDirectory(prefix='boardfeed-',dir='/tmp') as tmp:
            root=Path(tmp);socket=root/'rex.sock';endpoint='unix://'+str(socket)
            log=open(root/'rex.log','w')
            server=subprocess.Popen([REX,'server','run','--listen',endpoint,'--restore=false','--config','/dev/null','--state-dir',str(root/'state')],stdout=log,stderr=log)
            process=None
            try:
                for _ in range(100):
                    if socket.exists():break
                    if server.poll() is not None:raise RuntimeError('fixture Rex exited')
                    time.sleep(.02)
                command=([os.environ['TEEREX_BIN'],'board','feed'] if os.environ.get('TEEREX_BIN') else [sys.executable,str(SOURCE),'/not-used'])+['--local','--host-name','fixture','--socket',str(socket),'--rex',REX]
                for flag in ('agents-registry','jobs-registry','scratch','calls'):
                    (root/flag).mkdir();command+=['--'+flag,str(root/flag)]
                process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=dict(os.environ,HOME=tmp))
                events=queue.Queue()
                threading.Thread(target=lambda:[events.put(json.loads(line)) for line in process.stdout],daemon=True).start()
                def wait_for(predicate):
                    end=time.monotonic()+8
                    while time.monotonic()<end:
                        event=events.get(timeout=max(.01,end-time.monotonic()))
                        if predicate(event):return event
                    self.fail('event missing')
                wait_for(lambda e:e['kind']=='vitals')
                # A successful event-driven subscription must observe creation after startup.
                result=subprocess.run([REX,'--autostart=false','-S',endpoint,'new','--json','boardfixture','--',sys.executable,'-c',"import time;time.sleep(.6);print('\\x1b]7501;state=blocked:app=fixture:msg=Q2hvb3NlPw==\\x1b\\\\',flush=True);time.sleep(20)"],capture_output=True,text=True,timeout=5)
                self.assertEqual(result.returncode,0,result.stderr)
                wait_for(lambda e:e['kind']=='stream' and e['text']=='workspace opened')
                created=json.loads(result.stdout)
                session=created['session_id'];block=created['initial_windows'][0]['block_ids'][0]
                record=root/'agents-registry'/'agents-fixture.json'
                record.write_text(json.dumps(dict(launch_id='fixture',name='worker',phase='brief_submitted',target=dict(session_id=session,block_id=block))))
                wait_for(lambda e:e['kind']=='agent' and e['name']=='worker')
                wait_for(lambda e:e['kind']=='agent' and e['state']=='waiting' and e['question']=='Choose?')
                (root/'scratch'/session).mkdir()
                (root/'scratch'/session/(block+'.md')).write_text('## Now\n- [ ] Test push\n')
                wait_for(lambda e:e['kind']=='agent' and e['now']=='Test push')
                (root/'calls'/'calls.jsonl').write_text(json.dumps(dict(phase='start',call_id='x',verb='send'))+'\n'+json.dumps(dict(phase='end',call_id='x',exit=0))+'\n')
                wait_for(lambda e:e['kind']=='stream' and e['text']=='message delivered')
            finally:
                if process:
                    process.terminate();process.communicate(timeout=5)
                server.terminate();server.wait(timeout=5);log.close()

if __name__=='__main__':unittest.main()
