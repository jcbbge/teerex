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
import threading
import time
import unittest
from unittest import mock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/acceptance'))
import test_resources as resources

from test_environment import isolated_environment

SOURCE=Path(__file__).with_name('feed.py')
spec=importlib.util.spec_from_file_location('feed',SOURCE)
feed=importlib.util.module_from_spec(spec);spec.loader.exec_module(feed)
REX=os.environ.get('REX_BIN') or shutil.which('rex')

class FeedTests(unittest.TestCase):
    def test_task_parse_reference_format(self):
        with resources.temporary_directory() as tmp:
            path=Path(tmp)/'7-example.md'
            path.write_text('━━ ⑦ A task title ━━━━\nowner: worker        state: BLOCKED        done: NO\n✓ 1.1 Read contract  abc123\n▶ 1.2a Build it  worker\n☐ 2 Test it\nlast: 17:05 UTC waiting on review\n')
            self.assertEqual(feed.parse_task(path),dict(number='7',title='A task title',owner='worker',state='BLOCKED',done=False,chunks=[dict(mark='done',text='Read contract',who='abc123'),dict(mark='now',text='Build it',who='worker'),dict(mark='todo',text='Test it',who='')],last='17:05 waiting on review'))
            path.write_text('20 Finished\nowner: lead state: DONE done: YES\n')
            self.assertTrue(feed.parse_task(path)['done'])
            path.write_text('')
            self.assertEqual(feed.parse_task(path)['number'],path.name)

    def test_task_watch_changed_and_gone(self):
        with resources.temporary_directory() as tmp:
            root=Path(tmp);path=root/'7-example.md'
            path.write_text('━━ ⑦ Example ━━━━\nowner: worker state: WORKING done: NO\n')
            (root/'PROTOCOL.md').write_text('ignored')
            tasks=feed.Tasks('fixture',root);watcher=feed.Watcher([root])
            try:
                with mock.patch.object(feed,'emit') as emit:
                    tasks.scan();tasks.scan()
                    self.assertEqual(emit.call_count,1)
                    self.assertEqual(emit.call_args.args,('fixture','task'))
                    self.assertEqual(emit.call_args.kwargs['id'],path.name)
                    path.write_text('7 Changed\nowner: worker state: DONE done: YES\n')
                    self.assertTrue(watcher.wait(2));tasks.scan()
                    self.assertTrue(emit.call_args.kwargs['done'])
                    self.assertEqual(emit.call_count,2)
                    path.unlink()
                    self.assertTrue(watcher.wait(2));tasks.scan();tasks.scan()
                    self.assertEqual(emit.call_count,3)
                    self.assertEqual(emit.call_args.kwargs['state'],'gone')
            finally:watcher.close()

    def test_task_once_and_absent_option(self):
        with resources.temporary_directory() as tmp:
            root=Path(tmp);(root/'1-task.md').write_text('1 Example\nowner: worker state: WORKING done: NO\n')
            a=SimpleNamespace(host='fixture',tasks=root,once=True,held_command_json=None)
            with mock.patch.object(feed,'State'),mock.patch.object(feed,'emit') as emit:
                feed.local(a)
                self.assertEqual(emit.call_args.args,('fixture','task'))
                emit.reset_mock();a.tasks=None;feed.local(a);emit.assert_not_called()

    def test_task_named_host_forwarding(self):
        a=SimpleNamespace(executable='/teerex',config='/config',hosts='fixture',tasks=Path('/tasks'),once=True)
        source=dict(host=dict(store='/store'))
        child=mock.Mock();child.stdout=[json.dumps(dict(v=1,kind='task',id='1-a.md',host='wrong'))];child.wait.return_value=0
        output=io.StringIO()
        with mock.patch.object(feed.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(source))),mock.patch.object(feed.subprocess,'Popen',return_value=child) as start,contextlib.redirect_stdout(output):
            try:feed.merge(a)
            finally:feed.CHILDREN.remove(child)
        argv=start.call_args.args[0]
        self.assertEqual(argv[argv.index('--tasks')+1],'/tasks');self.assertIn('--once',argv)
        self.assertEqual(json.loads(output.getvalue())['host'],'fixture')

    def test_seat_label_role(self):
        with resources.temporary_directory() as tmp:
            a=SimpleNamespace(host='fixture',rex='/not-found',socket='/fixture.sock',scratch=Path(tmp)/'scratch',calls=Path(tmp)/'calls')
            state=feed.State(a);state.refresh_inventory=lambda:True
            state.live={'b':dict(session='s',label='seat'),'other':dict(session='s',label='worker')}
            for block in state.live:state.update_status(block,dict(records=[dict(id='agent',app='codex',state='working')]))
            with mock.patch.object(feed,'emit'):state.scan()
            self.assertEqual(state.rows['b']['role'],'seat')
            self.assertNotIn('role',state.rows['other'])

    def test_proof_steps_and_observational_sources(self):
        steps=feed.scratch_steps({'Done':['Read — proof: contract','Guess — unproven'],'Now':[],'To-do':[]})
        self.assertEqual([(s['text'],s['proof']) for s in steps],[('Guess',None),('Read','contract')])

    def held_row(self, identifier='item-1', since=1, broken=False):
        return dict(id=identifier,project='fixture',title='Example',waits='ship',text='ship? Example',on='',since=since,broken=broken,broken_why='broken' if broken else '')

    def test_held_changed_unchanged_and_failure(self):
        with resources.temporary_directory() as tmp:
            path=Path(tmp)/'held.json'
            packet=dict(schema=1,generated_at=1,items=[self.held_row('new',2),self.held_row('old',1,True)])
            path.write_text(json.dumps(packet))
            held=feed.Held('fixture',['cat',str(path)])
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                held.poll();held.poll()
                packet['generated_at']=2;path.write_text(json.dumps(packet));held.poll()
                packet['items'][0]['text']='ship? Changed';path.write_text(json.dumps(packet));held.poll()
                path.write_text('bad json');held.poll();held.poll()
                path.write_text(json.dumps(dict(schema=1,generated_at=3,items=[])));held.poll()
            events=[json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(len(events),4)
            self.assertEqual([r['id'] for r in events[0]['items']],['old','new'])
            self.assertTrue(events[0]['items'][0]['broken'])
            self.assertEqual(events[1]['items'][1]['text'],'ship? Changed')
            self.assertFalse(events[2]['available'])
            self.assertTrue(events[3]['available']);self.assertEqual(events[3]['items'],[])

    def test_held_nonzero_missing_and_timeout_are_unavailable(self):
        for command in (['/not-found'],[sys.executable,'-c','raise SystemExit(1)']):
            with self.subTest(command=command), mock.patch.object(feed,'emit') as emit:
                feed.Held('fixture',command).poll()
                emit.assert_called_once_with('fixture','held',available=False,items=[])
        child=mock.Mock();child.wait.side_effect=[subprocess.TimeoutExpired('fixture',5),0];child.poll.return_value=None
        with mock.patch.object(feed.subprocess,'Popen',return_value=child),mock.patch.object(feed,'emit') as emit:
            feed.Held('fixture',['fixture']).poll()
            child.kill.assert_called_once();self.assertEqual(child.wait.call_count,2)
            emit.assert_called_once_with('fixture','held',available=False,items=[])
        self.assertNotIn(child,feed.CHILDREN)

    def test_held_schema_and_ids_and_open_template(self):
        for identifier in ('-option','x; touch /tmp/no','../bad','x\n','',None):
            with self.subTest(identifier=identifier),self.assertRaises(ValueError):feed.held_id(identifier)
        for argv in ([], 'command', ['command','\n'], ['{id}'], ['command'], ['command','{id}','{id}'], ['command','{other}']):
            with self.subTest(argv=argv),self.assertRaises(ValueError):feed.held_argv(argv,template=True)
        self.assertEqual(feed.held_argv(['/bin/show','{id}'],template=True),['/bin/show','{id}'])
        packet=dict(schema=1,generated_at=1,items=[dict(self.held_row(),on=None,broken_why=None)])
        self.assertIsNone(feed.held_items(packet)[0]['on'])
        self.assertIsNone(feed.held_items(packet)[0]['broken_why'])
        for field,value in [('broken','true'),('since',False),('waits','other'),('text',None)]:
            bad=dict(packet,items=[dict(packet['items'][0],**{field:value})])
            with self.subTest(field=field),self.assertRaises(ValueError):feed.held_items(bad)
        with self.assertRaises(ValueError):feed.held_items(dict(packet,items=packet['items']*2))
        a=SimpleNamespace(held_id='safe:123',held_open_json=json.dumps(['/bin/show','--id={id}']))
        with mock.patch.object(feed.os,'dup2'),mock.patch.object(feed.os,'execvp') as execute:
            feed.open_held(a)
            execute.assert_called_once_with('/bin/show',['/bin/show','--id=safe:123'])
        a.held_id='-bad'
        with mock.patch.object(feed.os,'execvp') as execute,self.assertRaises(ValueError):feed.open_held(a)
        execute.assert_not_called()

    def test_held_enter_routes_host_and_opens_tiled_beside_board(self):
        a=SimpleNamespace(held_id='item-1',held_open_json=None,held_pane=False,executable='/teerex',config='/hosts.json',host='remote',rex='/board/rex')
        source=dict(held_open=['/show','{id}'])
        with mock.patch.object(feed,'selected_host',return_value=source),mock.patch.dict(os.environ,dict(isolated_environment(),REX_SESSION='session:test',REX_BLOCK='block:test'),clear=True),mock.patch.object(feed.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            feed.open_held(a)
            argv=run.call_args.args[0]
            self.assertEqual(argv[:6],['/teerex','--rex','/board/rex','surfaces','open','--session'])
            self.assertEqual(argv[argv.index('--anchor')+1],'block:test')
            self.assertEqual(argv[argv.index('--direction')+1],'right')
            self.assertEqual(argv[argv.index('--layout')+1],'tiled')
            self.assertIn('--held-pane',argv)
            self.assertEqual(argv[argv.index('--host-name')+1],'remote')
        a.held_pane=True
        with mock.patch.object(feed,'selected_host',return_value=source),mock.patch('builtins.input'),mock.patch.object(feed.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
            feed.open_held(a)
            argv=run.call_args.args[0]
            self.assertEqual(argv[:8],['/teerex','targets','exec','--config','/hosts.json','--host','remote','--'])
            self.assertEqual(argv[-2:],['--held-id','item-1'])
            self.assertEqual(run.call_args.kwargs['stderr'],subprocess.DEVNULL)
        with mock.patch.object(feed,'selected_host',return_value=source),mock.patch('builtins.input'),mock.patch.object(feed.subprocess,'run',return_value=SimpleNamespace(returncode=1)),contextlib.redirect_stdout(io.StringIO()) as output:
            feed.open_held(a)
        self.assertIn('Held work unavailable',output.getvalue())

    def test_held_enter_resolves_board_host_separately_from_source(self):
        with resources.temporary_directory() as tmp:
            config=Path(tmp)/'hosts.json'
            hosts=dict(board=dict(transport='local',socket='/board socket'),remote=dict(transport='ssh',socket='/remote'))
            config.write_text(json.dumps(dict(hosts=hosts)))
            a=SimpleNamespace(held_id='item-1',held_open_json=None,held_pane=False,executable='/teerex',config=str(config),host='remote',rex='rex',socket='/default')
            env=dict(LC_REX_SESSION='session:board',LC_REX_BLOCK='block:board',REX_SERVER='unix:///board%20socket')
            with mock.patch.object(feed,'selected_host',return_value=dict(held_open=['/show','{id}'])),mock.patch.dict(os.environ,env,clear=True),mock.patch.object(feed.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as run:
                feed.open_held(a)
                argv=run.call_args.args[0]
                self.assertEqual(argv[:7],['/teerex','--config',str(config),'--host','board','surfaces','open'])
                self.assertEqual(argv[argv.index('--session')+1],'session:board')
                self.assertEqual(argv[argv.index('--anchor')+1],'block:board')
                self.assertEqual(argv[argv.index('--host-name')+1],'remote')
                hosts['duplicate']=hosts['board'];config.write_text(json.dumps(dict(hosts=hosts)))
                run.reset_mock()
                with self.assertRaises(ValueError):feed.open_held(a)
                run.assert_not_called()
                hosts.pop('duplicate');hosts.pop('board');config.write_text(json.dumps(dict(hosts=hosts)))
                with self.assertRaises(ValueError):feed.open_held(a)
                run.assert_not_called()

    def test_native_watcher_existing_and_new_directories(self):
        with resources.temporary_directory() as tmp:
            root=Path(tmp);w=feed.Watcher([root/'new'])
            try:
                (root/'new').mkdir();self.assertTrue(w.wait(2))
                (root/'new'/'state.json').write_text('{}');self.assertTrue(w.wait(2))
                self.assertFalse(w.wait(.05))
            finally:w.close()

    @unittest.skipUnless(sys.platform=='linux','Linux proc fixture')
    def test_proc_deltas_and_agent_tree(self):
        with resources.temporary_directory() as tmp:
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

    def test_status_scratch_calls_and_removal(self):
        with resources.temporary_directory() as tmp:
            root=Path(tmp)
            class Args:pass
            a=Args();a.host='fixture';a.rex='/not-found';a.socket=str(root/'none')
            for field in ('scratch','calls'):
                setattr(a,field,root/field);getattr(a,field).mkdir()
            session='session:11111111-1111-1111-1111-111111111111';block='block:22222222-2222-2222-2222-222222222222'
            (a.scratch/session).mkdir();pad=a.scratch/session/(block+'.md')
            pad.write_text('## Now\n- [ ] Build feed\n## To-do\n- [ ] Test\n## Done\n- [x] Read\n')
            state=feed.State(a);out=io.StringIO()
            state.live={block:dict(block_id=block,session=session,label='worker',placement='placed')}
            state.refresh_inventory=lambda:True
            state.update_status(block,dict(records=[dict(id='agent',app='codex',state='working')]))
            with contextlib.redirect_stdout(out):
                state.scan();state.scan()
                state.scan()
                pad.write_text('## Now\n- [ ] Test feed\n');state.scan()
                (a.calls/'calls.jsonl').write_text(json.dumps(dict(phase='start',call_id='one',verb='send',body='SECRET'))+'\n'+json.dumps(dict(phase='end',call_id='one',exit=0))+'\n');state.scan()
                state.live={};state.scan()
            rows=[json.loads(x) for x in out.getvalue().splitlines()]
            agents=[r for r in rows if r['kind']=='agent']
            self.assertEqual(len(agents),3);self.assertEqual(agents[0]['total'],3);self.assertEqual(agents[-1]['state'],'gone')
            self.assertIn('message delivered',out.getvalue());self.assertNotIn('SECRET',out.getvalue());self.assertNotIn('DO NOT PRINT',out.getvalue())

    def test_agent_hook_status_classifies_panes(self):
        with resources.temporary_directory() as tmp:
            root=Path(tmp)
            a=SimpleNamespace(host='fixture',rex='/not-found',socket=str(root/'none'))
            for field in ('scratch','calls'):
                setattr(a,field,root/field);getattr(a,field).mkdir()
            state=feed.State(a);state.refresh_inventory=lambda:True
            block='block:worker'
            state.live={block:dict(session='session:fixture',label='worker')}
            for identifier,app in [('agent','codex'),('agent','claude'),('agent','pi')]:
                with self.subTest(identifier=identifier):
                    state.update_status(block,dict(records=[dict(id=identifier,app=app,state='working'),dict(id='other',app='other',state='error')]))
                    with mock.patch.object(feed,'emit'):state.scan()
                    self.assertEqual(state.rows[block]['state'],'working')
            for status in ('working','idle','done'):
                state.update_status(block,dict(records=[dict(id='agent',app='codex',state=status)]))
                with mock.patch.object(feed,'emit'):state.scan()
                self.assertEqual(state.rows[block]['state'],status)
                self.assertEqual(state.rows[block]['name'],'worker')
            state.live[block]['label']=''
            with mock.patch.object(feed,'emit'):state.scan()
            self.assertNotIn(block,state.rows)
            state.live[block]['label']='worker'
            state.update_status(block,dict(records=[dict(id='other',app='codex',state='working')]))
            with mock.patch.object(feed,'emit'):state.scan()
            self.assertNotIn(block,state.rows)

    def test_scratch_step_projection_preserves_annotations(self):
        steps=feed.scratch_steps({'Done':['Read · computer · ■ checked'],'Now':['Build · model · ⇥ reviewer'],'To-do':['Verify']})
        self.assertEqual([s['state'] for s in steps],['done','now','todo'])
        self.assertEqual(steps[0]['outcome'],'checked')
        self.assertEqual(steps[1]['handoff'],'reviewer')
        self.assertEqual(steps[2]['text'],'Verify')

    def test_status_and_title_projection(self):
        class Args:host='fixture'
        state=feed.State(Args());state.scan=lambda:None
        out=io.StringIO()
        with contextlib.redirect_stdout(out):
            state.rex_event(dict(type='session_event',payload=dict(event=dict(type='block_event',payload=dict(block_id='b',name='program_status_changed',payload=dict(id='agent',record=dict(state='blocked',msg='Which option?')))))))
            state.rex_event(dict(type='session_event',payload=dict(event=dict(type='block_label_changed',payload={}))))
        self.assertEqual(state.status['b'],'blocked');self.assertEqual(state.questions['b'],'Which option?');self.assertIn('title changed',out.getvalue())

    def test_unreachable_host_is_event(self):
        with resources.temporary_directory() as tmp:
            fake=Path(tmp)/'exec';fake.write_text('#!/bin/sh\nexit 1\n');fake.chmod(0o700)
            class Args:pass
            a=Args();a.once=False;a.executable=str(fake);a.config=str(Path(tmp)/'config');a.hosts='absent'
            out=io.StringIO()
            with contextlib.redirect_stdout(out):feed.merge(a)
            event=json.loads(out.getvalue());self.assertFalse(event['reachable']);self.assertEqual(event['host'],'absent')

    @unittest.skipUnless(REX,'explicit Rex executable required')
    def test_disposable_rex_push_and_filesystem_changes(self):
        with resources.temporary_directory(prefix='boardfeed-',dir='/tmp') as tmp:
            root=Path(tmp);socket=root/'rex.sock';endpoint='unix://'+str(socket)
            log=open(root/'rex.log','w')
            server=resources.start_process([REX,'server','run','--listen',endpoint,'--restore=false','--config','/dev/null','--state-dir',str(root/'state')],stdout=log,stderr=log)
            process=None
            try:
                for _ in range(100):
                    if socket.exists():break
                    if server.poll() is not None:raise RuntimeError('fixture Rex exited')
                    time.sleep(.02)
                command=([os.environ['TEEREX_BIN'],'board','feed'] if os.environ.get('TEEREX_BIN') else [sys.executable,str(SOURCE),'/not-used'])+['--local','--host-name','fixture','--socket',str(socket),'--rex',REX]
                for flag in ('scratch','calls'):
                    (root/flag).mkdir();command+=['--'+flag,str(root/flag)]
                process=resources.start_process(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=dict(isolated_environment(),HOME=tmp))
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
                result=subprocess.run([REX,'--autostart=false','-S',endpoint,'new','--json','boardfixture','--',sys.executable,'-c',"import time;time.sleep(.6);print('\\x1b]7501;state=blocked:id=agent:app=codex:msg=Q2hvb3NlPw==\\x1b\\\\',flush=True);time.sleep(20)"],capture_output=True,text=True,timeout=5)
                self.assertEqual(result.returncode,0,result.stderr)
                wait_for(lambda e:e['kind']=='stream' and e['text']=='workspace opened')
                created=json.loads(result.stdout)
                session=created['session_id'];block=created['initial_windows'][0]['block_ids'][0]
                row=wait_for(lambda e:e['kind']=='agent' and e['block']==block and e['state']=='blocked')
                self.assertEqual(row['placement'],'placed')
                self.assertEqual(row['question'],'Choose?')
                (root/'scratch'/session).mkdir()
                (root/'scratch'/session/(block+'.md')).write_text('## Now\n- [ ] Test push\n')
                wait_for(lambda e:e['kind']=='agent' and e['now']=='Test push')
                other=subprocess.run([REX,'--autostart=false','-S',endpoint,'new','--json','lua','--',sys.executable,'-c',"import time;print('\\x1b]7501;state=idle:id=agent:app=pi\\x1b\\\\',flush=True);time.sleep(20)"],capture_output=True,text=True,timeout=5)
                self.assertEqual(other.returncode,0,other.stderr)
                other_created=json.loads(other.stdout);other_sid=other_created['session_id'];other_block=other_created['initial_windows'][0]['block_ids'][0]
                wait_for(lambda e:e['kind']=='agent' and e['block']==other_block and e['state']=='idle')
                (root/'scratch'/other_sid).mkdir()
                (root/'scratch'/other_sid/(other_block+'.md')).write_text('## Now\n- [ ] Lua own work\n')
                # The duplicate's wrong session has a decoy scratchpad.
                wrong=root/'scratch'/'session:99999999-9999-9999-9999-999999999999';wrong.mkdir()
                (wrong/(block+'.md')).write_text('## Now\n- [ ] WRONG PAD\n')
                plain=subprocess.run([REX,'--autostart=false','-S',endpoint,'new','--json','not-an-agent','--','/bin/sh','-c','sleep 20'],capture_output=True,text=True,timeout=5)
                self.assertEqual(plain.returncode,0,plain.stderr)
                plain_created=json.loads(plain.stdout)
                class Args:pass
                args=Args();args.host='fixture';args.rex=REX;args.socket=str(socket)
                for key,folder in [('scratch','scratch'),('calls','calls')]:setattr(args,key,root/folder)
                inventory=feed.State(args)
                with contextlib.redirect_stdout(io.StringIO()):inventory.scan()
                self.assertEqual(set(inventory.rows),{block,other_block})
                self.assertEqual(inventory.rows[block]['session'],session)
                self.assertEqual(inventory.rows[block]['now'],'Test push')
                self.assertEqual(inventory.rows[block]['state'],'blocked')
                self.assertEqual(inventory.rows[other_block]['now'],'Lua own work')
                self.assertEqual(inventory.rows[other_block]['state'],'idle')
                probe_spec=importlib.util.spec_from_file_location('check_one_source',SOURCE.parent.parent/'board/check_one_source.py')
                probe=importlib.util.module_from_spec(probe_spec);probe_spec.loader.exec_module(probe)
                observed=json.loads(subprocess.check_output([sys.executable,'-c',probe.PROBE,REX,str(socket)],timeout=15))
                self.assertEqual({r['block'] for r in observed},{block,other_block})
                (root/'calls'/'calls.jsonl').write_text(json.dumps(dict(phase='start',call_id='x',verb='send'))+'\n'+json.dumps(dict(phase='end',call_id='x',exit=0))+'\n')
                wait_for(lambda e:e['kind']=='stream' and e['text']=='message delivered')
                closed=subprocess.run([REX,'--autostart=false','-S',endpoint,'block','close','--session',session,block],capture_output=True,text=True,timeout=5)
                self.assertEqual(closed.returncode,0,closed.stderr)
                wait_for(lambda e:e['kind']=='agent' and e['state']=='gone')
                if os.environ.get('TEEREX_BIN'):
                    config=root/'hosts.json'
                    config.write_text(json.dumps(dict(schema_version=1,hosts=dict(hive=dict(host_id='hive',platform='linux-x86_64' if sys.platform=='linux' else 'macos-arm64',transport='local',home=tmp,socket=str(socket),rex=REX,teerex=os.environ['TEEREX_BIN'],store=str(root/'store'))))))
                    merged=resources.start_process([os.environ['TEEREX_BIN'],'board','feed','--config',str(config),'--hosts','hive,absent'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=dict(isolated_environment(),HOME=tmp))
                    try:
                        received=queue.Queue()
                        threading.Thread(target=lambda:[received.put(json.loads(line)) for line in merged.stdout],daemon=True).start()
                        found=set();end=time.monotonic()+8
                        while len(found)<2 and time.monotonic()<end:
                            event=received.get(timeout=max(.01,end-time.monotonic()))
                            if event['host']=='hive' and event['kind']=='vitals':found.add('healthy')
                            if event['host']=='absent' and event['kind']=='host' and not event['reachable']:found.add('absent')
                        self.assertEqual(found,{'healthy','absent'})
                    finally:
                        merged.terminate();merged.communicate(timeout=5)

            finally:
                if process:
                    process.terminate();process.communicate(timeout=5)
                server.terminate();server.wait(timeout=5);log.close()

if __name__=='__main__':unittest.main()
