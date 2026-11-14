"""H02 acceptance: private temporary logs only; no personal server or live consent."""
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest

BIN = Path(os.environ.get('TEEREX_BIN','zig-out/bin/teerex')).resolve()
ROOT = Path(__file__).resolve().parents[2]
KEY = lambda n: 'k:'+f'{n:016x}'


class FrictionTest(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='friction-',dir='/tmp')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.log=self.root/'logs'; self.log.mkdir(mode=0o700)
        self.admin=self.root/'admin'; self.admin.mkdir(mode=0o700)
        self.env=dict(os.environ,TEEREX_CALL_LOG_DIR=str(self.log),TEEREX_CALLER='agent-read',AGENT_NAME='test-agent',AGENT_PANE='test-pane')
        self.control_env=dict(self.env,TEEREX_CALL_LOG_DIR=str(self.admin))
        self.counter=0

    def test_large_history_remains_readable(self):
        import runpy
        api = runpy.run_path(str(ROOT / 'items/boards/friction.py'))
        path = self.log / 'friction.jsonl'
        path.write_bytes(b'{}\n' * (4 * 1024 * 1024 // 3 + 1))
        path.chmod(0o600)
        with api['locked'](str(self.log)) as directory:
            self.assertGreater(len(api['read'](directory, 'friction.jsonl')), 4 * 1024 * 1024)

    def cli(self, operation, *options, code=0):
        p=subprocess.run([str(BIN),'boards','friction',operation,'--log-dir',str(self.log),*map(str,options)],env=self.control_env,capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,code,p.stderr+p.stdout)
        if code==2:return {'usage':p.stderr}
        return json.loads(p.stdout) if p.stdout else json.loads(p.stderr)

    def enable(self, scope='all'):
        return self.cli('enable','--for-days',1,'--scope',scope)

    def invoke(self,*args,env=None,input=None,cwd=None):
        return subprocess.run([str(BIN),*args],env=env or self.env,input=input,capture_output=True,text=True,cwd=cwd,timeout=10)

    def records(self,name='friction.jsonl'):
        path=self.log/name
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def fixture(self, runs, *, context=None, via='agent-send', episode=1, start=None):
        now=int(time.time()*1000) if start is None else start
        for number, item in enumerate(runs):
            self.counter+=1
            ident=f'{self.counter:032x}'
            if isinstance(item,str): item=(item,'ok',[])
            verb,klass,flags=item
            parts=verb.split('.',1)
            record=dict(schema_version=1,call_id=ident,ts=now+number*1000,
                        shape=dict(verb=parts[0],subverb=parts[1] if len(parts)>1 else None,flags=flags,positionals=0,other_tokens=0,stdin=False),
                        context=dict(host='hive',cwd_key=KEY(10),repo_key=KEY(11),server_key=KEY(12),version='0.1.0-alpha.5'),
                        caller=dict(via=via,agent_name='test-agent',episode_key=KEY(episode)))
            record['context'].update(context or {})
            self.append('friction.jsonl',record)
            self.append('calls.jsonl',dict(schema_version=1,call_id=ident,phase='start',at=now+number*1000,pid=100,start_at=self.counter))
            if klass!='uncertain':
                end=dict(schema_version=1,call_id=ident,phase='end',at=now+number*1000,pid=100,start_at=self.counter,exit=0 if klass=='ok' else 2 if klass=='usage' else 1,elapsed_ms=20)
                if klass.startswith('refused:'):end.update(outcome='refused',failure_reason=klass[8:])
                self.append('calls.jsonl',end)

    def append(self,name,record):
        path=self.log/name
        with path.open('ab') as f:f.write((json.dumps(record)+'\n').encode())
        path.chmod(0o600)

    def report(self,*options):return self.cli('report','--json',*options)

    def test_F1_no_consent_keeps_call_log_without_sidecar(self):
        for _ in range(3):self.assertEqual(self.invoke('--version').returncode,0)
        records=self.records('calls.jsonl')
        self.assertEqual(len(records),6)
        self.assertFalse((self.log/'friction.jsonl').exists())
        starts=[r for r in records if r['phase']=='start'];ends=[r for r in records if r['phase']=='end']
        self.assertEqual({r['call_id'] for r in starts},{r['call_id'] for r in ends})
        self.assertEqual(len({r['call_id'] for r in starts}),3)

    def test_F2_consent_validation_and_private_files(self):
        for days in (0,31):self.cli('enable','--for-days',days,'--scope','all',code=2)
        for scope in ('callers:','callers:a,,b','callers:Bad','other'):
            self.assertEqual(self.cli('enable','--for-days',1,'--scope',scope,code=1)['failure_reason'],'invalid_scope')
        self.assertFalse((self.log/'friction-consent.json').exists())
        result=self.enable();self.assertTrue(result['enabled'])
        self.assertEqual((self.log/'friction-salt').stat().st_mode&0o777,0o600)
        self.assertEqual(len((self.log/'friction-salt').read_bytes()),32)
        self.assertEqual(self.cli('enable','--for-days',1,'--scope','all',code=1)['failure_reason'],'consent_exists')
        self.log.chmod(0o755)
        self.assertEqual(self.cli('status',code=1)['failure_reason'],'private_owned_files_required')

    def test_F3_values_stdin_unknown_flags_and_inline_values_never_stored(self):
        self.enable()
        secret='SYNTHETICTOKEN0000000000'
        result=self.invoke('send','--socket','/tmp/no-server.sock','--session','session:00000000-0000-0000-0000-000000000000','--block','block:00000000-0000-0000-0000-000000000000',
                           '--message-file','-','--from','agent-x','--hunter2-not-a-flag',input='token='+secret)
        self.assertNotEqual(result.returncode,0)
        self.invoke('unknown','--from='+secret)
        raw=b''.join(p.read_bytes() for p in self.log.iterdir() if p.is_file())
        for excluded in (secret,'agent-x','hunter2',str(self.root)):
            self.assertNotIn(excluded.encode(),raw)
        rows=self.records()
        self.assertTrue(rows[0]['shape']['stdin'])
        self.assertGreaterEqual(rows[0]['shape']['other_tokens'],1)
        self.assertIn('message-file',rows[0]['shape']['flags'])
        self.assertEqual(rows[0]['shape']['flags'],sorted(set(rows[0]['shape']['flags'])))

    def test_F4_caller_validation_and_scope(self):
        self.enable()
        result=self.invoke('--version',env=dict(self.env,TEEREX_CALLER='agent-send; rm -rf /'))
        self.assertEqual(result.stdout,'teerex 0.1.0-alpha.6\n')
        row=self.records()[0]
        self.assertIsNone(row['caller']['via']);self.assertTrue(row['caller']['via_invalid'])
        start=[r for r in self.records('calls.jsonl') if r['phase']=='start'][0]
        self.assertTrue(start['caller']['via_invalid'])
        self.cli('disable');self.enable('callers:agent-send')
        size=(self.log/'friction.jsonl').stat().st_size
        self.invoke('--version')
        self.assertEqual((self.log/'friction.jsonl').stat().st_size,size)
        self.invoke('--version',env=dict(self.env,TEEREX_CALLER='agent-send'))
        self.assertGreater((self.log/'friction.jsonl').stat().st_size,size)

    def test_F5_meaningful_repeat_maps_existing_issue(self):
        for episode in (1,2,3):self.fixture(['boards.probe','targets.resolve','send'],episode=episode)
        result=self.report()
        self.assertEqual(len(result['candidates']),1)
        row=result['candidates'][0]
        self.assertEqual(row['support'],3);self.assertEqual(row['class'],'existing_issue:#2')
        self.assertEqual(row['plausible_saving_s'],2)
        self.assertEqual(row['median_elapsed_ms'],60)

    def test_F6_similar_contexts_are_not_pooled(self):
        for episode in (1,2,3):self.fixture(['boards.probe','targets.resolve','send'],episode=episode,context=dict(repo_key=KEY(100+episode)))
        result=self.report()
        self.assertEqual(result['candidates'],[])
        self.assertEqual(len(result['similar_not_same']),1)
        self.assertIn('repo_key',result['similar_not_same'][0]['differing_fields'])

    def test_F7_loop_in_one_episode_is_not_support(self):
        self.fixture(['observe']*80,episode=1)
        result=self.report()
        self.assertEqual(result['episodes'],1)
        self.assertEqual(result['candidates'],[])

    def test_F8_uncertain_mutation_retry_refuses_automation(self):
        for episode in range(4):self.fixture([('send','uncertain',[]),'observe','send'],episode=episode)
        result=self.report()
        self.assertEqual(len(result['refused']),1)
        row=result['refused'][0]
        self.assertEqual(row['class'],'refuse_automation:retry_of_uncertain')
        self.assertNotIn('suggestion_text',row)

    def test_F9_operator_authority_precedes_issue_or_candidate(self):
        for episode in range(3):self.fixture([('boards.ask','ok',['resolve']),'send'],episode=episode)
        row=self.report()['refused'][0]
        self.assertEqual(row['class'],'refuse_automation:operator_authority')
        self.assertNotIn('suggestion_text',row)

    def test_F10_known_refusal_is_a_defect_and_unknown_exit_is_not(self):
        for episode in range(3):self.fixture([('inbox.append','refused:capacity',[])],episode=episode)
        result=self.report()
        self.assertEqual(len(result['defects']),1)
        self.assertEqual(result['defects'][0]['class'],'defect')
        self.assertEqual(result['candidates'],[])
        for episode in range(10,13):self.fixture([('observe','error',[])],episode=episode)
        self.assertEqual(len(self.report()['defects']),1)

    def test_F11_maximal_run_and_estimate_not_measured_benefit(self):
        for episode in range(3):self.fixture([('observe','ok',['block','max-bytes','session']),'watch','observe'],episode=episode,via='agent-read')
        result=self.report()
        self.assertEqual(len(result['candidates']),1)
        self.assertEqual(len(result['candidates'][0]['run']),3)
        self.assertTrue(result['candidates'][0]['estimate_basis'].startswith('inferred:'))
        self.assertEqual(result['candidates'][0]['support'],3)

    def test_F12_expiry_and_bad_consent_fail_closed(self):
        self.enable()
        path=self.log/'friction-consent.json'
        consent=json.loads(path.read_text());consent.update(enabled_at=1,expires_at=2)
        path.write_text(json.dumps(consent))
        self.invoke('--version')
        self.assertFalse((self.log/'friction.jsonl').exists())
        self.assertTrue(self.cli('status')['expired'])
        path.write_text('{')
        self.invoke('--version')
        self.assertFalse((self.log/'friction.jsonl').exists())

    def test_F13_disable_preview_forget_and_salt_reset_preserve_call_history(self):
        self.enable();self.invoke('--version')
        self.assertTrue(self.cli('disable')['was_enabled'])
        self.invoke('--version')
        before={p.name:p.read_bytes() for p in self.log.iterdir()}
        self.assertEqual(self.cli('forget','--all')['would_remove'],1)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.log.iterdir()})
        self.cli('forget','--all','--yes')
        self.assertFalse((self.log/'friction-salt').exists())
        self.assertFalse((self.log/'friction.jsonl').exists())
        self.assertEqual((self.log/'calls.jsonl').read_bytes(),before['calls.jsonl'])
        self.assertFalse(self.cli('disable')['was_enabled'])

    def test_F14_hook_failure_and_lock_busy_never_change_command(self):
        self.enable()
        sidecar=self.log/'friction.jsonl';sidecar.touch(mode=0o600);sidecar.chmod(0o400)
        result=self.invoke('--version')
        self.assertEqual(result.returncode,0);self.assertEqual(result.stderr,'')
        start=[r for r in self.records('calls.jsonl') if r['phase']=='start'][-1]
        self.assertEqual(start['friction_write'],'failed')
        sidecar.chmod(0o600)
        with (self.log/'lock').open('r+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            result=self.invoke('--version')
            self.assertEqual(result.returncode,0);self.assertEqual(result.stderr,'')

    def test_F15_flag_allowlist_matches_all_declared_source_and_help_flags(self):
        allowed=set(re.search(r'pub const names = "([^"]+)"',(ROOT/'items/boards/flagnames.zig').read_text()).group(1).split())
        declared=set()
        for directory in ('src','items'):
            for path in (ROOT/directory).rglob('*'):
                if path.suffix in ('.py','.zig','.lua') and not path.name.startswith('test'):
                    declared.update(re.findall(r'--([a-z][a-z0-9-]*)',path.read_text()))
        self.assertEqual(declared-allowed,set())
        for verb in ('observe','send','spawn','doctor','jobs','adapters','surfaces','run','run-visible','offstage','agents','recovery','boards','clutch','replay','filter','maneuver-check'):
            p=self.invoke(verb,'--help')
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertFalse(set(re.findall(r'--([a-z](?:[a-z0-9-]*[a-z0-9])?)(?![a-z0-9-]|\*)',p.stdout))-allowed)

    def test_hashes_labels_repo_detection_rotation_and_safe_links(self):
        self.enable()
        repo=self.root/'repo';repo.mkdir();(repo/'.git').mkdir();(repo/'child').mkdir()
        self.invoke('--version',cwd=repo/'child')
        record=self.records()[0];salt=(self.log/'friction-salt').read_bytes()
        self.assertEqual(record['context']['repo_key'],'k:'+hmac.new(salt,str(repo.resolve()).encode(),hashlib.sha256).hexdigest()[:16])
        self.cli('label','--path',repo,'--name','test-repo')
        self.assertIn(record['context']['repo_key'],self.cli('status')['labels'])
        sidecar=self.log/'friction.jsonl';sidecar.write_bytes(b'x'*(4*1024*1024));sidecar.chmod(0o600)
        self.invoke('--version')
        self.assertEqual((self.log/'friction.jsonl.1').stat().st_size,4*1024*1024)
        self.assertLess(sidecar.stat().st_size,10000)
        victim=self.root/'victim';victim.write_text('preserve');victim.chmod(0o600)
        sidecar.unlink();sidecar.symlink_to(victim)
        self.assertEqual(self.invoke('--version').returncode,0)
        self.assertEqual(victim.read_text(),'preserve')
        self.cli('forget','--all','--yes',code=1)
        self.assertEqual(victim.read_text(),'preserve')
        self.assertTrue(self.cli('disable')['was_enabled'])
        self.assertFalse((self.log/'friction-consent.json').exists())

    def test_episode_gap_unmatched_and_refused_reason_class(self):
        for start in (1,400000,800000):self.fixture(['observe','watch'],episode=1,start=start)
        row=self.report()['candidates'][0]
        self.assertEqual(row['support'],3)
        self.assertEqual(self.report('--since','900000')['candidates'],[])
        extra=self.records()[0];extra['call_id']='f'*32;self.append('friction.jsonl',extra)
        self.assertEqual(self.report()['unmatched'],1)

    def test_resolved_default_server_and_unresolved_context_are_separate(self):
        self.enable()
        endpoint=str(self.root/'absent.sock')
        env=dict(self.env,REX_SERVER='unix://'+endpoint.replace('/','%2F'))
        self.invoke('observe','--session','x','--block','y',env=env)
        record=self.records()[-1]
        salt=(self.log/'friction-salt').read_bytes()
        expected='k:'+hmac.new(salt,('unix://'+endpoint).encode(),hashlib.sha256).hexdigest()[:16]
        self.assertEqual(record['context']['server_key'],expected)
        self.invoke('observe','--socket',endpoint,'--session','x','--block','y')
        self.assertEqual(self.records()[-1]['context']['server_key'],expected)
        for episode in (1,2,3):
            self.fixture(['observe','send'],episode=episode,context=dict(target_unknown=True,server_key=None))
        result=self.report()
        self.assertEqual(result['unresolved_context'],6)
        self.assertEqual(result['candidates'],[])

    def test_explicit_rex_exec_keeps_one_shape_and_call_id(self):
        self.enable()
        result=self.invoke('--rex','/absent/rex','--version')
        self.assertEqual(result.returncode,0)
        self.assertEqual(len(self.records()),1)
        calls=self.records('calls.jsonl')
        self.assertEqual(len(calls),2)
        self.assertEqual({r['call_id'] for r in calls},{self.records()[0]['call_id']})

    def test_named_host_hook_completes_one_shape_without_values(self):
        self.enable()
        executable=self.root/'target'
        executable.write_text('#!/bin/sh\nexit 7\n');executable.chmod(0o700)
        host=dict(host_id='fixture',transport='local',home=str(self.root),platform='linux-x86_64',socket=str(self.root/'server.sock'),rex='/absent',teerex=str(executable),store=str(self.root/'store'))
        config=self.root/'hosts.json'
        config.write_text(json.dumps(dict(schema_version=1,hosts=dict(fixture=host))))
        args=('--config',str(config),'--host','fixture','observe')
        self.assertEqual(self.invoke(*args).returncode,7)
        rows=self.records();self.assertEqual(len(rows),1)
        self.assertFalse(rows[0]['context']['target_unknown'])
        salt=(self.log/'friction-salt').read_bytes()
        endpoint='unix://'+host['socket']
        self.assertEqual(rows[0]['context']['server_key'],'k:'+hmac.new(salt,endpoint.encode(),hashlib.sha256).hexdigest()[:16])
        self.assertNotIn(str(config),(self.log/'friction.jsonl').read_text())
        host.update(transport='ssh',address='fixture@127.0.0.1',port=2222,known_hosts='/absent',identity_file='/absent')
        config.write_text(json.dumps(dict(schema_version=1,hosts=dict(fixture=host))))
        self.assertEqual(self.invoke('targets','resolve','--config',str(config),'--host','fixture').returncode,0)
        endpoint='ssh://fixture@127.0.0.1:2222'+host['socket']
        self.assertEqual(self.records()[-1]['context']['server_key'],'k:'+hmac.new(salt,endpoint.encode(),hashlib.sha256).hexdigest()[:16])

    def test_partial_forget_and_report_read_only_and_hardlinks(self):
        self.enable()
        self.fixture(['observe','watch'],via='agent-read',start=1000)
        self.fixture(['observe','watch'],via='agent-send',start=5000)
        before={p.name:p.read_bytes() for p in self.log.iterdir()}
        self.report()
        self.cli('forget','--before','4000')
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.log.iterdir()})
        self.assertEqual(self.cli('forget','--before','4000','--yes')['would_remove'],2)
        self.assertEqual(len(self.records()),2)
        self.assertEqual(self.cli('forget','--caller','agent-send','--yes')['would_remove'],2)
        self.assertEqual(self.records(),[])
        victim=self.root/'hardlink';victim.write_text('preserve');victim.chmod(0o600)
        (self.log/'friction.jsonl').unlink()
        os.link(victim,self.log/'friction.jsonl')
        self.assertEqual(self.invoke('--version').returncode,0)
        self.assertEqual(victim.read_text(),'preserve')

    def test_exec_pid_and_output_stay_with_payload_when_consent_active(self):
        self.enable()
        runtime=self.root/'python3';output=self.root/'exec.json'
        runtime.write_text(f'#!{sys.executable}\nimport json,os;from pathlib import Path\nPath({str(output)!r}).write_text(json.dumps(dict(pid=os.getpid())))\nprint("exact payload");raise SystemExit(23)\n')
        runtime.chmod(0o700)
        proc=subprocess.Popen([str(BIN),'boards','friction','status','--log-dir',str(self.log)],env=dict(self.env,PATH=str(self.root)),stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        out,err=proc.communicate(timeout=10)
        self.assertEqual((proc.returncode,out,err),(23,'exact payload\n',''))
        self.assertEqual(json.loads(output.read_text())['pid'],proc.pid)
        self.assertEqual(len(self.records()),1)


if __name__=='__main__':unittest.main()
