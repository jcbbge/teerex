"""Foreground, event-driven board feed. Python 3.9+, no service or dependencies."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import platform
import re
import select
import signal
import stat
import subprocess
import sys
import threading
import tempfile
import time
from urllib.parse import unquote

LOCK = threading.Lock()
STOP = threading.Event()
CHILDREN = []


def tracked_output(command, timeout=None, text=False):
    """check_output, but registered in CHILDREN so a stopping feed terminates and reaps it."""
    if STOP.is_set():raise subprocess.SubprocessError('feed stopping')
    p=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=text);CHILDREN.append(p)
    try:
        try:out,_=p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:p.kill();p.communicate();raise
    finally:
        try:CHILDREN.remove(p)
        except ValueError:pass
    if p.returncode:raise subprocess.CalledProcessError(p.returncode,command,out)
    return out


def emit(host, kind, **fields):
    with LOCK:
        print(json.dumps(dict(v=1, t=time.time_ns() // 1000000, host=host, kind=kind, **fields), separators=(',', ':')), flush=True)


def read(path, limit=262144):
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('not a regular file')
        data = os.read(fd, limit + 1)
        if len(data) > limit:
            raise ValueError('file too large')
        return data.decode('utf8')
    finally:
        os.close(fd)


class Watcher:
    """Native filesystem notifications. Missing paths watch their nearest ancestor."""
    def __init__(self, roots):
        self.roots = roots
        self.paths = {}
        self.kq = None
        if sys.platform == 'linux':
            self.lib = ctypes.CDLL(None, use_errno=True)
            self.fd = self.lib.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
            if self.fd < 0:
                raise OSError(ctypes.get_errno(), 'inotify_init1')
        else:
            self.kq = select.kqueue()
            self.fd = self.kq.fileno()
        self.refresh()

    def refresh(self):
        desired = set()
        for root in self.roots:
            parent = root
            while not parent.exists():
                parent = parent.parent
            desired.add(str(parent))
            if root.is_dir():
                for directory, dirs, files in os.walk(root, followlinks=False):
                    dirs[:] = [n for n in dirs if not Path(directory, n).is_symlink() and n != 'archive']
                    desired.add(directory)
                    if self.kq:
                        desired.update(str(Path(directory, f)) for f in files if not Path(directory, f).is_symlink())
        for path in desired - self.paths.keys():
            try:
                if self.kq:
                    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
                    flags = select.KQ_NOTE_WRITE | select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME | select.KQ_NOTE_EXTEND
                    self.kq.control([select.kevent(fd, filter=select.KQ_FILTER_VNODE, flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR, fflags=flags)], 0)
                    self.paths[path] = fd
                else:
                    wd = self.lib.inotify_add_watch(self.fd, os.fsencode(path), 0x00000fce)
                    if wd >= 0:
                        self.paths[path] = wd
            except OSError:
                pass
        for path in list(self.paths):
            if path not in desired or not os.path.exists(path):
                fd = self.paths.pop(path)
                if self.kq:
                    os.close(fd)
                else:
                    self.lib.inotify_rm_watch(self.fd, fd)

    def wait(self, timeout):
        if self.kq:
            changed = bool(self.kq.control([], 256, timeout))
        else:
            changed = bool(select.select([self.fd], [], [], timeout)[0])
            if changed:
                os.read(self.fd, 65536)
        if changed:
            self.refresh()
        return changed

    def close(self):
        if self.kq:
            for fd in self.paths.values():
                os.close(fd)
            self.kq.close()
        else:
            os.close(self.fd)


class LinuxVitals:
    def __init__(self, proc='/proc'):
        self.proc = Path(proc)
        self.previous = {}
        self.net = None
        self.at = time.monotonic()
        self.processes = {}

    def sample(self, roots):
        now = time.monotonic()
        elapsed = max(now - self.at, .001)
        cpus = []
        for line in read(self.proc / 'stat').splitlines():
            fields = line.split()
            if not re.fullmatch(r'cpu[0-9]*', fields[0]):
                continue
            values = list(map(int, fields[1:9]))
            total, idle = sum(values), values[3] + values[4]
            old = self.previous.get(fields[0], (total, idle))
            cpus.append(100 * max(0, total - old[0] - idle + old[1]) / max(1, total - old[0]))
            self.previous[fields[0]] = (total, idle)
        mem = {}
        for line in read(self.proc / 'meminfo').splitlines():
            k, value = line.split(':', 1)
            mem[k] = int(value.split()[0]) * 1024
        rx = tx = 0
        for line in read(self.proc / 'net/dev').splitlines()[2:]:
            name, value = line.split(':')
            if name.strip() != 'lo':
                fields = value.split(); rx += int(fields[0]); tx += int(fields[8])
        old = self.net or (rx, tx)
        net = dict(rx_bps=max(0, rx-old[0])/elapsed, tx_bps=max(0, tx-old[1])/elapsed)
        self.net = (rx, tx)
        disks = []
        for line in read(self.proc / 'self/mounts').splitlines():
            fields = line.split()
            if fields[2] in ('proc', 'sysfs', 'tmpfs', 'devtmpfs', 'devpts', 'cgroup', 'cgroup2', 'squashfs', 'mqueue', 'securityfs', 'debugfs', 'tracefs', 'pstore', 'fusectl', 'configfs', 'hugetlbfs', 'autofs', 'binfmt_misc'):
                continue
            mount = re.sub(r'\\([0-7]{3})', lambda m: chr(int(m[1], 8)), fields[1])
            try:
                v = os.statvfs(mount)
                if v.f_blocks:
                    disks.append(dict(mount=mount, total=v.f_blocks*v.f_frsize, used=(v.f_blocks-v.f_bfree)*v.f_frsize))
            except OSError:
                pass
        processes = {}
        ticks = os.sysconf('SC_CLK_TCK')
        page_size = os.sysconf('SC_PAGE_SIZE')
        proc_path = str(self.proc)
        for pid_text in os.listdir(proc_path):
            if not pid_text.isdigit():
                continue
            try:
                fd = os.open(proc_path+'/'+pid_text+'/stat', os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
                try: raw = os.read(fd, 8192).decode()
                finally: os.close(fd)
                end = raw.rindex(')'); fields = raw[end+2:].split()
                pid = int(pid_text); total = int(fields[11])+int(fields[12]); start = fields[19]
                key = (pid, start); before = self.processes.get(key, total)
                processes[pid] = dict(pid=pid, ppid=int(fields[1]), cpu=max(0,total-before)/ticks/elapsed*100, rss=int(fields[21])*page_size, cmd=raw[raw.index('(')+1:end], ticks=total, key=key)
            except (OSError, ValueError, IndexError):
                continue
        self.processes = {p['key']:p['ticks'] for p in processes.values()}
        self.at = now
        return dict(cpu=cpus[1:], cpu_total=cpus[0] if cpus else 0, load=list(map(float, read(self.proc/'loadavg').split()[:3])), mem=dict(total=mem['MemTotal'], used=mem['MemTotal']-mem.get('MemAvailable',mem.get('MemFree',0))), swap=dict(total=mem.get('SwapTotal',0), used=mem.get('SwapTotal',0)-mem.get('SwapFree',0)), disks=disks, net=net, top=group_processes(processes, roots))


def group_processes(processes, roots):
    groups = {}
    for pid, p in processes.items():
        parent = pid; seen = set(); agent = None
        while parent in processes and parent not in seen:
            seen.add(parent)
            if parent in roots:
                agent = roots[parent]; break
            parent = processes[parent]['ppid']
        key = ('agent', agent) if agent else ('pid', pid)
        if key not in groups:
            groups[key] = dict(agent=agent, pid=parent if agent else pid, cpu=0, rss=0, cmd=agent or p['cmd'])
        groups[key]['cpu'] += p['cpu']; groups[key]['rss'] += p['rss']
    return sorted(groups.values(), key=lambda p:(p['cpu'],p['rss']), reverse=True)[:16]

class MacVitals:
    def __init__(self):
        self.previous = None
        self.net = None
        self.at = time.monotonic()
        self.lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib')

    def sample(self, roots):
        # host_processor_info returns per-core cumulative user/system/idle/nice ticks.
        count = ctypes.c_uint(); info = ctypes.POINTER(ctypes.c_int)(); size = ctypes.c_uint()
        port = self.lib.mach_host_self()
        if self.lib.host_processor_info(port, 2, ctypes.byref(count), ctypes.byref(info), ctypes.byref(size)):
            raise OSError('host_processor_info failed')
        values = [tuple(info[i*4+j] & 0xffffffff for j in range(4)) for i in range(count.value)]
        self.lib.vm_deallocate(self.lib.mach_task_self(), ctypes.cast(info, ctypes.c_void_p), size.value*4)
        old = self.previous or values
        cpu = [100*(sum(v)-sum(p)-v[2]+p[2])/max(1,sum(v)-sum(p)) for v,p in zip(values,old)]
        self.previous = values
        total = int(tracked_output(['sysctl','-n','hw.memsize'],text=True))
        vm = tracked_output(['vm_stat'],text=True)
        page = int(re.search(r'page size of (\d+)',vm)[1])
        stats = {k:int(v) for k,v in re.findall(r'([^\n:]+):\s+(\d+)\.',vm)}
        available = page*sum(stats.get(k,0) for k in ('Pages free','Pages inactive','Pages speculative'))
        swap = tracked_output(['sysctl','-n','vm.swapusage'],text=True)
        def byte_value(key):
            m = re.search(key+r' = ([0-9.]+)([KMG])',swap)
            return int(float(m[1])*{'K':1024,'M':1024**2,'G':1024**3}[m[2]]) if m else 0
        disks = []
        for line in tracked_output(['mount'],text=True).splitlines():
            if not line.startswith('/dev/'):
                continue
            mount = line.split(' on ',1)[1].rsplit(' (',1)[0]
            v = os.statvfs(mount)
            disks.append(dict(mount=mount,total=v.f_blocks*v.f_frsize,used=(v.f_blocks-v.f_bfree)*v.f_frsize))
        rx=tx=0
        output = tracked_output(['netstat','-ibn'],text=True).splitlines()
        seen=set()
        if output:
            header=output[0].split(); ri=header.index('Ibytes'); ti=header.index('Obytes')
            for line in output[1:]:
                f=line.split()
                if len(f)>max(ri,ti) and f[0] not in seen and not f[0].startswith('lo') and '<Link#' in line:
                    seen.add(f[0]); rx+=int(f[ri]); tx+=int(f[ti])
        now=time.monotonic(); elapsed=max(.001,now-self.at); old=self.net or (rx,tx)
        net=dict(rx_bps=max(0,rx-old[0])/elapsed,tx_bps=max(0,tx-old[1])/elapsed)
        self.at=now;self.net=(rx,tx)
        processes={}
        for line in tracked_output(['ps','-axo','pid=,ppid=,%cpu=,rss=,comm='],text=True).splitlines():
            f=line.split(None,4)
            if len(f)==5:
                pid=int(f[0]);processes[pid]=dict(pid=pid,ppid=int(f[1]),cpu=float(f[2]),rss=int(f[3])*1024,cmd=os.path.basename(f[4]))
        return dict(cpu=cpu,cpu_total=sum(cpu)/max(1,len(cpu)),load=list(os.getloadavg()),mem=dict(total=total,used=max(0,total-available)),swap=dict(total=byte_value('total'),used=byte_value('used')),disks=disks,net=net,top=group_processes(processes,roots))


def executable_path(value):
    if not isinstance(value,str) or not value:return None
    try:return str(Path(value).resolve()) if Path(value).exists() else value
    except (OSError,RuntimeError):return value


def profile_executables(path):
    try:
        profiles=json.loads(read(path.resolve())).get('profiles',{})
        return {executable_path(p['argv'][0]) for p in profiles.values()
                if isinstance(p,dict) and isinstance(p.get('argv'),list) and p['argv']
                and isinstance(p['argv'][0],str) and p['argv'][0]}
    except (OSError,ValueError,UnicodeError,TypeError,AttributeError,RuntimeError):return set()


class State:
    def __init__(self, a):
        self.a=a; self.rows={};self.calls={};self.call_starts={};self.roots={};self.pids={};self.status={};self.questions={};self.reports={};self.seeded=set();self.live={};self.reachable=None
        self.lock=threading.RLock()
        self.processes={}

    def rex_json(self, *args):
        command=[self.a.rex,'--autostart=false','--server','unix://'+self.a.socket,'--timeout','2s',*args]
        return json.loads(tracked_output(command,timeout=3))

    def refresh_inventory(self):
        live={}
        try:
            sessions=self.rex_json('api','call','session.list','{}').get('sessions') or []
            for session in sessions:
                sid=session['session_id']
                result=self.rex_json('block','ls','--session',sid,'--json')
                blocks=result.get('blocks',[]) if isinstance(result,dict) else result
                for pane in blocks:
                    block=pane['block_id']
                    live[block]=dict(pane,session=sid)
            self.live=live
            reachable=True
        except (OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError):
            self.live={};reachable=False
        if reachable!=self.reachable:
            emit(self.a.host,'host',reachable=reachable,error=None if reachable else 'Cannot read live panes')
            self.reachable=reachable
        return reachable

    def scan(self):
        with self.lock:
            self.refresh_inventory()
            # Registries provide names/launch metadata, never the pane inventory.
            records={}
            for registry in (self.a.agents_registry,self.a.jobs_registry):
                if not registry.exists():continue
                for path in sorted(registry.glob('*.json')):
                    try:
                        data=json.loads(read(path))
                        if not isinstance(data,dict):continue
                        for record in data.get('entries',[data]):
                            if not isinstance(record,dict):continue
                            target=record.get('target') or {}
                            block=target.get('block_id') or record.get('block_id')
                            if not block:continue
                            # Prefer named managed launches; duplicates can never add rows.
                            if block not in records:records[block]=dict(record,_managed=registry==self.a.agents_registry)
                    except (OSError,ValueError,UnicodeError,TypeError):continue
            executables=profile_executables(self.a.profiles) if getattr(self.a,'profiles',None) else set()
            rows={}
            for block,pane in self.live.items():
                session=pane['session']
                if block not in self.rows or block not in self.processes:
                    self.refresh_process(block,session)
                if block not in self.seeded:
                    self.seeded.add(block)
                    try:
                        status=self.rex_json('block','call','--session',session,'--block',block,'program_status','{}')
                        self.update_status(block,status)
                    except (OSError,ValueError,subprocess.SubprocessError):pass
                record=records.get(block)
                agent_reports=[r for r in self.reports.get(block,{}).values() if r.get('app') in ('teerex-agent',)]
                matched=next((value for role in ('child','foreground')
                              for field in ('argv0','path')
                              for value in [(self.processes.get(block,{}).get(role) or {}).get(field)]
                              if executable_path(value) in executables),None)
                if not (record or {}).get('_managed') and not agent_reports and not matched:continue
                record=record or {}
                # The pane address owns its scratchpad, regardless of record name/session.
                pad=self.a.scratch/session/(block+'.md')
                sections={'Now':[],'To-do':[],'Done':[]};section=None
                try:
                    for line in read(pad,65536).splitlines():
                        if line.startswith(('## ','# ')):section=line.lstrip('# ').strip()
                        elif section in sections and line.startswith(('- [ ] ','- [x] ','- ')):
                            sections[section].append(line[6:] if line.startswith(('- [ ] ','- [x] ')) else line[2:])
                except (OSError,ValueError,UnicodeError):pass
                hook=record.get('last_hook') or {}
                contract=record.get('contract') or {}
                starter=contract.get('starter',record.get('starter')) or {}
                starter_block=starter.get('block_id','')
                starter_session=starter.get('session_id')
                starter_record=records.get(starter_block,{})
                starter_pane=self.live.get(starter_block,{})
                if (starter_record.get('target') or {}).get('session_id')!=starter_session:starter_record={}
                if starter_pane.get('session')!=starter_session:starter_pane={}
                starter_name=starter_record.get('name') or starter_pane.get('label') or starter_block.split(':')[-1][:8]
                if not record.get('_managed') and not agent_reports:
                    name=pane.get('label') or os.path.basename(matched)
                else:
                    name=record.get('name') or pane.get('label') or (agent_reports[0].get('app') if agent_reports else None) or 'agent'
                row=dict(id=block,name=name,session=session,block=block,state=self.status.get(block,'unknown'),placement=pane.get('placement','placed'),now=next(iter(sections['Now']),None),done=len(sections['Done']),total=sum(map(len,sections.values())),question=self.questions.get(block),since=hook.get('at') or record.get('created_at') or record.get('registered_at_unix_ms') or 0,cpu=None,rss=None)
                row.update(starter=starter_name,step_n=contract.get('step_n',len(sections['Done'])+bool(sections['Now'])),step_total=contract.get('steps_total',row['total']),last_contact_at=contract.get('last_contact_at',hook.get('at') or 0),stalled=contract.get('stalled',False))
                rows[block]=row
            for block,row in rows.items():
                if self.rows.get(block)!=row:emit(self.a.host,'agent',**row)
            for block,row in self.rows.items():
                if block not in rows:emit(self.a.host,'agent',**dict(row,state='gone'))
            self.rows=rows
            self.seeded.intersection_update(self.live)
            self.processes={b:p for b,p in self.processes.items() if b in self.live}
            self.roots={self.pids[row['block']]:row['name'] for row in rows.values() if row['block'] in self.pids}
            self.tail_calls()

    def refresh_process(self,block,session):
        self.processes.pop(block,None)
        self.pids.pop(block,None)
        try:
            process=self.rex_json('block','call','--session',session,'--block',block,'process','{}')
            self.processes[block]=process
            root=process.get('child') or process.get('foreground') or {}
            if type(root.get('pid')) is int:self.pids[block]=root['pid']
        except (OSError,ValueError,subprocess.SubprocessError):pass

    def tail_calls(self):
        for path in self.a.calls.glob('*.jsonl') if self.a.calls.exists() else []:
            try:
                fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
                with os.fdopen(fd,'r') as f:
                    st=os.fstat(f.fileno())
                    if not stat.S_ISREG(st.st_mode):continue
                    key=(str(path),st.st_ino); offset=self.calls.get(key,0)
                    if offset>st.st_size:offset=0
                    f.seek(offset)
                    while True:
                        at=f.tell();line=f.readline(65537)
                        if not line or not line.endswith('\n'):f.seek(at);break
                        try:
                            r=json.loads(line)
                            # Never project command arguments, message bodies, tokens or paths.
                            if r.get('phase')=='start':
                                if len(self.call_starts)>=4096:self.call_starts.pop(next(iter(self.call_starts)))
                                self.call_starts[r.get('call_id')]=r
                                continue
                            if r.get('phase')=='end':
                                start=self.call_starts.pop(r.get('call_id'),{})
                                if r.get('exit')!=0:continue
                                r=dict(start,**r)
                            command=r.get('command',r.get('verb',''))
                            if isinstance(command,list):command=command[0] if command else ''
                            if command in ('send','ask','agents','run','run-visible','spawn'):
                                text={'send':'message delivered','ask':'question updated','agents':'agent activity','spawn':'pane opened','run':'command updated','run-visible':'command updated'}[command]
                                emit(self.a.host,'stream',agent=None,text=text,role='words')
                        except (ValueError,TypeError):pass
                    self.calls[key]=f.tell()
            except (OSError,UnicodeError):pass

    def update_status(self,block,payload):
        reports=self.reports.setdefault(block,{})
        if 'records' in payload:
            reports.clear()
            for record in payload['records']:
                if isinstance(record,dict):reports[record.get('id','')]=record
        elif isinstance(payload.get('record'),dict):
            reports[payload.get('id','')]=payload['record']
        elif 'ids' in payload:
            for identifier in payload['ids']:reports.pop(identifier,None)
        elif 'state' in payload:reports[payload.get('id','')]=payload
        priority={'error':5,'blocked':4,'waiting':4,'working':3,'done':2,'idle':1}
        agent_reports=[r for r in reports.values() if r.get('app') in ('teerex-agent',)]
        managed=[r for r in agent_reports if r.get('app')=='teerex-agent']
        record=managed[-1] if managed else agent_reports[-1] if agent_reports else max(reports.values(),key=lambda r:priority.get(r.get('state'),0),default={})
        state=record.get('state')
        if state in ('working','waiting','blocked','error','idle','done'):self.status[block]=state
        else:self.status.pop(block,None)
        if state=='blocked':self.questions[block]=record.get('msg') or record.get('title')
        else:self.questions.pop(block,None)

    def rex_event(self,event):
        kind=event.get('type');p=event.get('payload') or {}
        session=p.get('session_id')
        if kind=='session_event':event=p.get('event') or {};kind=event.get('type');p=event.get('payload') or {}
        block=p.get('block_id');name=p.get('name') if kind=='block_event' else kind
        payload=p.get('payload') or {}
        with self.lock:
            if name in ('session_view_changed','block_removed','block_closed','session_created','session_removed','window_created','window_closed'):
                self.scan()
            if name=='process_changed':
                if block in self.live:self.refresh_process(block,self.live[block]['session'])
                self.scan()
            elif name and 'status' in name:
                self.update_status(block,payload)
                self.scan()
            text={'block_created':'pane opened','block_removed':'pane closed','block_closed':'pane closed','title_changed':'title changed','label_changed':'title changed','focus_changed':'focus moved','window_focused':'focus moved','focused_block_changed':'focus moved','active_window_changed':'focus moved','block_label_changed':'title changed','window_label_changed':'title changed','session_created':'workspace opened','session_removed':'workspace closed'}.get(name)
            if text:emit(self.a.host,'stream',agent=None,text=text,role='words')


def rex_events(a,state):
    command=[a.rex,'--autostart=false','--server','unix://'+a.socket,'--timeout','3s','events','--all','--json']
    try:
        p=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True);CHILDREN.append(p)
        for line in p.stdout:
            if STOP.is_set():break
            try:state.rex_event(json.loads(line))
            except (ValueError,TypeError):pass
        if not STOP.is_set():emit(a.host,'host',reachable=False,error='Rex event connection closed')
    except OSError:emit(a.host,'host',reachable=False,error='Cannot start Rex event subscription')


# IDs are passed as literal argv, never as options or shell fragments.
def held_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}', value):
        raise ValueError('invalid held item id')
    return value


def held_argv(value, template=False):
    if not isinstance(value, list) or not value or len(value)>128 or any(not isinstance(v,str) or not v or len(v)>4096 or any(ord(c)<32 or ord(c)==127 for c in v) for v in value):
        raise ValueError('held command must be a nonempty argv list without controls')
    if template and (value[0].find('{')>=0 or sum(v.count('{id}') for v in value)!=1 or any('{' in v.replace('{id}','') or '}' in v.replace('{id}','') for v in value)):
        raise ValueError('held_open requires exactly one {id} argument placeholder')
    return value


def held_items(data):
    if not isinstance(data,dict) or type(data.get('schema')) is not int or data['schema']!=1 or type(data.get('generated_at')) is not int or not isinstance(data.get('items'),list) or len(data['items'])>256:
        raise ValueError('invalid held snapshot')
    seen=set();rows=[]
    for item in data['items']:
        if not isinstance(item,dict) or any(k not in item for k in ('id','project','title','waits','text','on','since','broken','broken_why')):raise ValueError('invalid held row')
        held_id(item.get('id'))
        if item['id'] in seen:raise ValueError('duplicate held id')
        seen.add(item['id'])
        if any(not isinstance(item.get(k),str) or len(item[k])>8192 for k in ('project','title','waits','text')) or any(item.get(k) is not None and (not isinstance(item[k],str) or len(item[k])>8192) for k in ('on','broken_why')) or item['waits'] not in ('promote','ship','item','block','hold') or type(item.get('since')) is not int or item['since']<0 or type(item.get('broken')) is not bool:
            raise ValueError('invalid held row fields')
        rows.append({k:item[k] for k in ('id','project','title','waits','text','on','since','broken','broken_why')})
    return sorted(rows,key=lambda r:r['since'])


class Held:
    def __init__(self, host, command):
        self.host=host;self.command=held_argv(command);self.previous=None

    def poll(self):
        try:
            with tempfile.TemporaryFile() as output:
                child=subprocess.Popen(self.command,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.DEVNULL)
                CHILDREN.append(child)
                try:
                    code=child.wait(timeout=5)
                    output.seek(0);raw=output.read(262145)
                    if code or len(raw)>262144:raise ValueError('held command failed')
                    snapshot=dict(available=True,items=held_items(json.loads(raw)))
                finally:
                    if child.poll() is None:child.kill();child.wait()
                    CHILDREN.remove(child)
        except (OSError,ValueError,TypeError,UnicodeError,subprocess.SubprocessError):
            snapshot=dict(available=False,items=[])
        # generated_at is deliberately excluded: a new sample is not a change.
        if snapshot!=self.previous:
            emit(self.host,'held',**snapshot)
            self.previous=snapshot


def selected_host(a):
    result=subprocess.run([a.executable,'targets','resolve','--config',a.config,'--host',a.host],capture_output=True,timeout=15)
    if result.returncode:raise ValueError('held host unavailable')
    return json.loads(result.stdout)['host']


def open_held(a):
    identifier=held_id(a.held_id)
    if a.held_open_json is not None:
        argv=held_argv(json.loads(a.held_open_json),template=True)
        # The transport's stderr is suppressed; restore command errors to pane output.
        os.dup2(sys.stdout.fileno(),sys.stderr.fileno())
        return os.execvp(argv[0],[v.replace('{id}',identifier) for v in argv])
    host=selected_host(a)
    template=held_argv(host.get('held_open'),template=True)
    if a.held_pane:
        result=subprocess.run([a.executable,'targets','exec','--config',a.config,'--host',a.host,'--',
                        'board','feed','--held-open-json',json.dumps(template),'--held-id',identifier],stderr=subprocess.DEVNULL,check=False)
        if result.returncode:print('Held work unavailable')
        # Keep even short output on screen; no shell or environment pager command.
        input('\nPress Enter to close')
    else:
        session=os.environ.get('REX_SESSION') or os.environ.get('LC_REX_SESSION')
        block=os.environ.get('REX_BLOCK') or os.environ.get('LC_REX_BLOCK')
        if not session or not block:raise ValueError('board pane address unavailable')
        # The source host may be remote; the adjacent pane belongs to the board.
        # Keep an explicit local Rex selection, otherwise resolve its socket's
        # local host entry instead of depending on rex being on PATH.
        command=[a.executable]
        if a.rex != 'rex':
            command+=['--rex',a.rex]
        else:
            server=os.environ.get('REX_SERVER')
            if server is not None and not server.startswith('unix://'):raise ValueError('board server must be Unix')
            socket=unquote(server[7:]) if server is not None else a.socket
            hosts=json.loads(read(a.config,1024*1024))['hosts']
            names=[name for name,entry in hosts.items() if isinstance(entry,dict) and entry.get('transport')=='local' and entry.get('socket')==socket]
            if len(names)!=1:raise ValueError('board local host unavailable or ambiguous')
            command+=['--config',a.config,'--host',names[0]]
        result=subprocess.run([*command,'surfaces','open','--session',session,'--layout','tiled','--anchor',block,'--direction','right','--label','Held work','--',
                               a.executable,'board','feed','--held-pane','--config',a.config,'--host-name',a.host,'--held-id',identifier],stdout=subprocess.DEVNULL,timeout=15)
        if result.returncode:raise ValueError('held pane unavailable')


def local(a):
    state=State(a)
    held=Held(a.host,json.loads(a.held_command_json)) if a.held_command_json else None
    if a.once:
        if held:held.poll()
        state.scan()
        return
    watcher=Watcher([a.agents_registry,a.jobs_registry,a.scratch,a.calls,a.profiles])
    sample=LinuxVitals() if sys.platform=='linux' else MacVitals()
    thread=threading.Thread(target=rex_events,args=(a,state),daemon=True);thread.start()
    state.scan();deadline=time.monotonic();held_deadline=0
    try:
        while not STOP.is_set():
            now=time.monotonic()
            if held and now>=held_deadline:
                held.poll();held_deadline=time.monotonic()+30
            if now>=deadline:
                try:
                    with state.lock: roots=dict(state.roots)
                    emit(a.host,'vitals',**sample.sample(roots))
                except (OSError,ValueError,KeyError,IndexError,subprocess.SubprocessError):
                    emit(a.host,'stream',agent=None,text='Machine measurements unavailable',role='problem')
                deadline=now+1
            if watcher.wait(max(0,deadline-time.monotonic())):state.scan()
    finally:watcher.close()


def merge(a):
    threads=[]
    def host_feed(host):
        configured=False;last_held=None
        command=[a.executable,'targets','exec','--config',a.config,'--host',host,'--','board','feed','--local','--host-name',host]+(['--once'] if a.once else [])
        try:
            selected=subprocess.run([a.executable,'targets','resolve','--config',a.config,'--host',host],capture_output=True,timeout=15)
            if selected.returncode:raise ValueError('host unavailable')
            source=json.loads(selected.stdout)['host']
            configured='held_command' in source
            if configured:
                try:
                    held_argv(source['held_command'])
                    command+=['--held-command-json',json.dumps(source['held_command'])]
                except ValueError:
                    emit(host,'held',available=False,items=[]);last_held=False
            p=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True);CHILDREN.append(p)
            for line in p.stdout:
                if STOP.is_set():break
                try:
                    event=json.loads(line)
                    if event.get('v')!=1 or event.get('kind') not in ('host','agent','stream','vitals','held'):continue
                    event['host']=host
                    if event['kind']=='held':last_held=event.get('available')
                    with LOCK: print(json.dumps(event,separators=(',',':')),flush=True)
                except (ValueError,TypeError):continue
            code=p.wait()
            if not STOP.is_set() and configured and (last_held is None or (not a.once or code) and last_held is not False):
                emit(host,'held',available=False,items=[])
            if not STOP.is_set() and (not a.once or code):emit(host,'host',reachable=False,error='Host feed disconnected')
        except (OSError,ValueError,KeyError,subprocess.SubprocessError):
            if configured and last_held is not False:emit(host,'held',available=False,items=[])
            emit(host,'host',reachable=False,error='Host feed unavailable')
    for host in a.hosts.split(','):
        t=threading.Thread(target=host_feed,args=(host,),daemon=True);t.start();threads.append(t)
    while any(t.is_alive() for t in threads) and not STOP.wait(.2):pass


def main(argv=None):
    parser=argparse.ArgumentParser(prog='teerex board feed',description=__doc__)
    parser.add_argument('--config',default=os.path.expanduser('~/.config/teerex/hosts.json'),help='absolute named-host configuration')
    parser.add_argument('--hosts',default='hive,m5',help='comma-separated configured hosts; both by default')
    parser.add_argument('--held-command-json',help=argparse.SUPPRESS)
    parser.add_argument('--held-open-json',help=argparse.SUPPRESS)
    parser.add_argument('--held-id',help=argparse.SUPPRESS)
    parser.add_argument('--open-held',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--held-pane',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--once',action='store_true',help='finite pane snapshot, then exit (no vitals or event subscription)')
    parser.add_argument('--local',action='store_true',help='read this host only (transport worker)')
    parser.add_argument('--host-name',dest='host',default=platform.node().split('.')[0])
    parser.add_argument('--socket',default=os.environ.get('TEEREX_BOARD_SOCKET', '/run/user/%d/rex/server.sock'%os.getuid() if sys.platform=='linux' else os.path.expanduser('~/Library/Application Support/rex/server.sock')))
    parser.add_argument('--rex',default=os.environ.get('TEEREX_INTERNAL_REX',os.environ.get('REX_BIN','rex')))
    parser.add_argument('--profiles',type=Path,default=Path.home()/'.config/teerex/profiles.json',help='absolute read-only profiles file on this host')
    home=Path.home()/'.local/state'
    for flag,default in [('agents-registry',home/'teerex-agents'),('jobs-registry',home/'teerex-jobs'),('scratch',home/'teerex/scratch'),('calls',Path(os.environ.get('TEEREX_CALL_LOG_DIR',home/'teerex/calls')))]:
        parser.add_argument('--'+flag,type=Path,default=default,help='absolute read-only source directory on this host')
    args=parser.parse_args(argv)
    args.executable=EXECUTABLE
    if not os.path.isabs(args.config) or any(not re.fullmatch(r'[A-Za-z0-9_-]+',h) for h in args.hosts.split(',')):
        parser.error('absolute --config and valid host names required')
    for path in (args.agents_registry,args.jobs_registry,args.scratch,args.calls,args.profiles):
        if not path.is_absolute():parser.error('source paths must be absolute')
    if args.open_held or args.held_pane or args.held_open_json is not None:
        try:open_held(args)
        except (OSError,ValueError,KeyError,EOFError,subprocess.SubprocessError):
            print('Held work unavailable',file=sys.stderr)
            raise SystemExit(1)
        return
    def stop(signum,frame):
        STOP.set()
        for p in list(CHILDREN):
            if p.poll() is None:p.terminate()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        local(args) if args.local else merge(args)
    except BrokenPipeError:STOP.set()
    finally:
        stop(0,None)
        for p in list(CHILDREN):
            try:p.wait(timeout=3)
            except subprocess.TimeoutExpired:p.kill();p.wait()


if __name__=='__main__':
    EXECUTABLE=sys.argv.pop(1)
    main()
