"""H02 local, consent-gated shape analysis. No execution, network or payload fields."""
import collections
import contextlib
import datetime
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import statistics
import sys
import time

LIMIT = 4 * 1024 * 1024
NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
KEY = re.compile(r"^k:[0-9a-f]{16}$")
CALL_ID = re.compile(r"^[0-9a-f]{32}$")
FLAGS = set()  # injected from the same compiled flagnames.zig allowlist


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def private(fd, directory=False):
    s = os.fstat(fd)
    require(s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == (0o700 if directory else 0o600)
            and (stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode) and s.st_nlink == 1), "private_owned_files_required")


@contextlib.contextmanager
def locked(path):
    require(os.path.isabs(path), "absolute_log_dir_required")
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK)
    lock = None
    try:
        private(directory, True)
        lock = os.open("lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=directory)
        private(lock)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("log_busy")
        yield directory
    finally:
        if lock is not None:
            os.close(lock)
        os.close(directory)


def read(directory, name, cap=LIMIT):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        private(fd)
        with os.fdopen(os.dup(fd), "rb") as stream:
            value = stream.read(cap + 1)
        require(len(value) <= cap, "file_limit_exceeded")
        return value
    finally:
        os.close(fd)


def optional(directory, name, cap=LIMIT):
    try:
        return read(directory, name, cap)
    except FileNotFoundError:
        return None


def atomic(directory, name, value):
    # Validate an existing target before replacing it, including link count.
    optional(directory, name)
    temporary = ".friction-next-" + secrets.token_hex(8)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        with os.fdopen(os.dup(fd), "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.rename(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        os.close(fd)
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def timestamp(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    require(isinstance(value, str), "invalid_timestamp")
    try:
        if value.isdigit():
            return int(value)
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.tzinfo is not None, "timestamp_timezone_required")
        return int(parsed.timestamp() * 1000)
    except (ValueError, OverflowError):
        raise ValueError("invalid_timestamp")


def consent(directory):
    raw = optional(directory, "friction-consent.json", 32768)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
        require(value["schema_version"] == 1, "invalid_consent")
        enabled, expires = timestamp(value["enabled_at"]), timestamp(value["expires_at"])
        require(0 < expires-enabled <= 30*86400000, "invalid_consent")
        scope(value["scope"])
        require(NAME.fullmatch(value["enabled_by"]) is not None, "invalid_consent")
        labels = value.get("labels", {})
        require(isinstance(labels, dict) and len(labels) <= 128 and all(KEY.fullmatch(k) and isinstance(v,str) and NAME.fullmatch(v) for k,v in labels.items()), "invalid_consent")
        return dict(value, enabled_at=enabled, expires_at=expires)
    except (ValueError, TypeError, KeyError):
        return None  # malformed consent never enables collection


def scope(value):
    require(isinstance(value, str), "invalid_scope")
    if value == "all":
        return value
    require(value.startswith("callers:") and 0 < len(value) <= 4096, "invalid_scope")
    names = value[8:].split(",")
    require(len(names) <= 64 and all(NAME.fullmatch(n) for n in names) and len(names) == len(set(names)), "invalid_scope")
    return value


def segments(directory):
    # Fixed names only; no globs following user links or unrelated call-log files.
    return [(name, raw) for name in ("friction.jsonl.1", "friction.jsonl")
            if (raw := optional(directory, name)) is not None]


def shapes(directory):
    records = []
    malformed = 0
    for _, raw in segments(directory):
        for line in raw.splitlines():
            try:
                value = json.loads(line)
                require(value["schema_version"] == 1 and CALL_ID.fullmatch(value["call_id"]), "invalid_shape")
                timestamp(value["ts"])
                s, c, caller = value["shape"], value["context"], value["caller"]
                require((NAME.fullmatch(s["verb"]) or s["verb"] in ("--version","--help")) and (s.get("subverb") is None or NAME.fullmatch(s["subverb"])), "invalid_shape")
                require(isinstance(s["flags"], list) and len(s["flags"]) <= len(FLAGS) and all(f in FLAGS for f in s["flags"]), "invalid_shape")
                require(all(isinstance(s.get(k), int) and 0 <= s[k] <= 1000000 for k in ("positionals", "other_tokens")) and isinstance(s.get("stdin"),bool), "invalid_shape")
                require(isinstance(c["host"],str) and 0 < len(c["host"]) <= 255 and all(ch.isalnum() or ch in ".-_" for ch in c["host"]), "invalid_context")
                require(isinstance(c["version"],str) and 0 < len(c["version"]) <= 128 and re.fullmatch(r"[a-zA-Z0-9.+_-]+",c["version"]), "invalid_context")
                require(KEY.fullmatch(c["cwd_key"]) and all(c.get(k) is None or KEY.fullmatch(c[k]) for k in ("repo_key","server_key")), "invalid_context")
                require(KEY.fullmatch(caller["episode_key"]) and all(caller.get(k) is None or NAME.fullmatch(caller[k]) for k in ("via","agent_name")), "invalid_caller")
                records.append(value)
            except (ValueError, KeyError, TypeError):
                malformed += 1
    return records, malformed


def status(directory):
    c = consent(directory)
    now = int(time.time()*1000)
    salt = optional(directory, "friction-salt",32)
    records, malformed = shapes(directory)
    times = [timestamp(r["ts"]) for r in records]
    parts = segments(directory)
    return dict(enabled=bool(c and c["enabled_at"] <= now < c["expires_at"] and salt is not None and len(salt)==32),
                expired=bool(c and c["expires_at"] <= now), expires_at=c["expires_at"] if c else None,
                scope=c["scope"] if c else None, lines=sum(len(raw.splitlines()) for _,raw in parts),
                bytes=sum(len(raw) for _,raw in parts), oldest_ts=min(times,default=None),newest_ts=max(times,default=None),
                salt_present=salt is not None and len(salt)==32, labels=(c or {}).get("labels",{}),malformed=malformed)


def join(directory, records):
    ids = {r["call_id"] for r in records}
    starts, ends = {}, {}
    names = sorted(n for n in os.listdir(directory) if re.fullmatch(r"calls-[0-9]{20}-[0-9]+\.jsonl", n)) + ["calls.jsonl"]
    require(len(names) <= 100000, "call_segment_limit")
    for name in names:
        raw = optional(directory,name,1048576)
        if raw is None:
            continue
        for line in raw.splitlines():
            try:
                value=json.loads(line)
                if value.get("call_id") not in ids: continue
                if value.get("phase")=="start": starts[value["call_id"]]=value
                elif value.get("phase")=="end": ends[value["call_id"]]=value
            except (ValueError,TypeError,AttributeError):
                continue
    joined, unmatched = [], 0
    seen=set()
    for record in records:
        ident=record["call_id"]
        if ident in seen: continue
        seen.add(ident)
        if ident not in starts:
            unmatched+=1;continue
        end=ends.get(ident,{})
        # Landed #13 has exact exit/elapsed, not backend refusal reasons. Never
        # turn unexplained nonzero exits or missing ends into invented defects.
        code=end.get("exit")
        reason=end.get("failure_reason") or starts[ident].get("failure_reason")
        outcome=end.get("outcome") or starts[ident].get("outcome")
        if code==0: klass="ok"
        elif code==2: klass="usage"
        elif reason and outcome in ("refused","refused_or_unknown","backend_error") and re.fullmatch(r"[a-zA-Z0-9_.:-]{1,128}",reason): klass="refused:"+reason
        else: klass="uncertain"
        joined.append(dict(record, klass=klass, elapsed_ms=end.get("elapsed_ms") if isinstance(end.get("elapsed_ms"), (int,float)) and end["elapsed_ms"]>=0 else None))
    return joined, unmatched


MUTATING={"send","spawn","agents.launch","agents.deliver","surfaces.open","surfaces.close","ask","boards.ask","inbox.append","recovery.restore","fleet.install"}
AUTHORITY={"recovery.restore","fleet.install","fleet.rollback","surfaces.close","agents.stop"}
ISSUES=((('boards.probe','boards.probe','targets.resolve'),'teerex-target','#2,#23'),
        (('boards.probe','targets.resolve','agents.launch'),'agent-spawn','#14'),
        (('boards.probe','targets.resolve','send'),'agent-send','#2'))


def verb(record):
    return record["shape"]["verb"]+("."+record["shape"]["subverb"] if record["shape"].get("subverb") else "")


def step(record):
    return verb(record)+"("+",".join(sorted(set(record["shape"]["flags"])))+")="+record["klass"]


def classify(occurrences):
    for rows in occurrences:
        for index,r in enumerate(rows):
            if r["klass"]=="uncertain" and verb(r) in MUTATING and any(verb(later)==verb(r) for later in rows[index+1:]):
                return "refuse_automation:retry_of_uncertain"
    if any(verb(r) in AUTHORITY or verb(r) in ("ask","boards.ask") and "resolve" in r["shape"]["flags"] for rows in occurrences for r in rows):
        return "refuse_automation:operator_authority"
    endings={rows[-1]["klass"] for rows in occurrences}
    if len(endings)==1 and next(iter(endings)).startswith("refused:"):
        return "defect"
    names=tuple(verb(r) for r in occurrences[0])
    callers={r["caller"].get("via") for rows in occurrences for r in rows}
    for run,caller,issue in ISSUES:
        if names==run and callers=={caller}: return "existing_issue:"+issue
    return "verb_candidate"


def maximal_runs(keys, support):
    # At most six steps: index each longer run's substrings instead of comparing
    # every candidate with every other candidate.
    result=set(keys)
    for context,tokens in keys:
        for length in range(1,len(tokens)):
            for offset in range(len(tokens)-length+1):
                shorter=(context,tokens[offset:offset+length])
                if shorter in keys and support(shorter)==support((context,tokens)):
                    result.discard(shorter)
    return result


def report(directory, args):
    records, malformed=shapes(directory)
    records=[r for r in records if args.since is None or timestamp(r["ts"])>=timestamp(args.since)]
    rows, unmatched=join(directory,records)
    unresolved=sum(bool(r["context"].get("target_unknown")) for r in rows)
    episodes=collections.defaultdict(list)
    for row in rows: episodes[row["caller"]["episode_key"]].append(row)
    occurrences=collections.defaultdict(list)
    episode_ids=collections.defaultdict(set)
    context_values={}
    count=0
    for episode_key,events in episodes.items():
        events.sort(key=lambda r:(timestamp(r["ts"]),r["call_id"]))
        chunks=[]
        for row in events:
            if not chunks or timestamp(row["ts"])-timestamp(chunks[-1][-1]["ts"])>args.gap_s*1000: chunks.append([])
            chunks[-1].append(row)
        for number,episode in enumerate(chunks):
            count+=1
            for start in range(len(episode)):
                for length in range(1,min(6,len(episode)-start)+1):
                    group=episode[start:start+length]
                    if any(r["context"].get("target_unknown") for r in group): break
                    if length==1 and not group[0]["klass"].startswith("refused:"): continue
                    contexts=[]
                    for r in group:
                        c=r["context"]
                        contexts.append((c["host"],c.get("repo_key") or c["cwd_key"],c.get("server_key"),c["version"]))
                    if len(set(contexts))!=1: break
                    context=contexts[0]
                    tokens=tuple(step(r) for r in group)
                    key=(context,tokens)
                    occurrences[key].append(group)
                    episode_ids[key].add((episode_key,number))
                    context_values[context]=group[0]["context"]
    kept={key for key,ids in episode_ids.items() if len(ids)>=args.min_episodes}
    maximal=maximal_runs(kept,lambda key: len(episode_ids[key]))
    labels=(consent(directory) or {}).get("labels",{})
    candidates=[]
    for context,tokens in sorted(maximal,key=lambda k:(str(k[0]),k[1])):
        groups=occurrences[(context,tokens)]
        kind=classify(groups)
        elapsed=[sum(r["elapsed_ms"] for r in group) for group in groups if all(r["elapsed_ms"] is not None for r in group)]
        gaps=[sum(max(0,timestamp(b["ts"])-timestamp(a["ts"])) for a,b in zip(group,group[1:]))/1000 for group in groups]
        c=context_values[context]
        row=dict(run=list(tokens),support=len(episode_ids[(context,tokens)]),context=dict(c,repo_label=labels.get(c.get("repo_key") or c["cwd_key"])),
                 callers=sorted({r["caller"]["via"] for group in groups for r in group if r["caller"].get("via")}),
                 median_elapsed_ms=statistics.median(elapsed) if elapsed else None,plausible_saving_s=statistics.median(gaps),
                 estimate_basis="inferred: inter-step gaps only; occurrence counts are not measured benefit",
                 refusal_count=sum(r["klass"].startswith("refused:") for group in groups for r in group))
        row["class"]=kind
        if kind=="defect": row["failure_reason"]=groups[0][-1]["klass"][8:]
        if not kind.startswith("refuse_automation:"): row["suggestion_text"]="Review repeated call shapes: "+" → ".join(tokens)
        candidates.append(row)
    pooled=collections.defaultdict(set)
    contexts=collections.defaultdict(set)
    for (context,tokens),ids in episode_ids.items():
        pooled[tokens].update(ids);contexts[tokens].add(context)
    similar=[]
    eligible={(None,tokens) for tokens,ids in pooled.items() if len(ids)>=args.min_episodes and not any((c,tokens) in kept for c in contexts[tokens])}
    for _,tokens in sorted(maximal_runs(eligible,lambda key:len(pooled[key[1]])),key=lambda key:key[1]):
        ids=pooled[tokens]
        differing=[field for index,field in enumerate(("host","cwd_key" if all(context_values[c].get("repo_key") is None for c in contexts[tokens]) else "repo_key","server_key","version")) if len({c[index] for c in contexts[tokens]})>1]
        similar.append(dict(run=list(tokens),support=len(ids),differing_fields=differing))
    consent_status=status(directory)
    times=[timestamp(r["ts"]) for r in rows]
    return dict(schema_version=1,kind="friction_report",host=sorted({r["context"]["host"] for r in rows}),
                window={"from":min(times,default=None),"to":max(times,default=None)},consent={k:consent_status[k] for k in ("enabled","expires_at")},
                calls=len(rows),unresolved_context=unresolved,unmatched=unmatched,malformed=malformed,episodes=count,
                candidates=[r for r in candidates if r["class"]=="verb_candidate" or r["class"].startswith("existing_issue:")],
                defects=[r for r in candidates if r["class"]=="defect"],
                refused=[r for r in candidates if r["class"].startswith("refuse_automation:")],similar_not_same=similar)


def execute(args):
    with locked(args.log_dir) as directory:
        op=args.operation
        if op=="enable":
            require(1<=args.for_days<=30,"invalid_days")
            scope(args.scope)
            require(NAME.fullmatch(args.by),"invalid_name")
            current=consent(directory)
            now=int(time.time()*1000)
            require(not current or current["expires_at"]<=now,"consent_exists")
            salt=optional(directory,"friction-salt",32)
            if salt is None: atomic(directory,"friction-salt",secrets.token_bytes(32))
            else: require(len(salt)==32,"invalid_salt")
            value=dict(schema_version=1,enabled_at=now,expires_at=now+args.for_days*86400000,scope=args.scope,enabled_by=args.by,labels=(current or {}).get("labels",{}))
            atomic(directory,"friction-consent.json",encode(value))
            return dict(kind="friction_consent",**status(directory))
        if op=="disable":
            current=consent(directory)
            now=int(time.time()*1000)
            active=bool(current and current["enabled_at"] <= now < current["expires_at"])
            raw=optional(directory,"friction-consent.json",32768)
            if raw is not None: os.unlink("friction-consent.json",dir_fd=directory);os.fsync(directory)
            return dict(kind="friction_consent",enabled=False,was_enabled=active)
        if op=="status": return dict(kind="friction_status",**status(directory))
        if op=="label":
            current=consent(directory)
            require(current is not None and status(directory)["enabled"],"active_consent_required")
            require(os.path.isabs(args.path) and os.path.exists(args.path),"existing_absolute_path_required")
            require(NAME.fullmatch(args.name),"invalid_name")
            salt=read(directory,"friction-salt",32)
            key="k:"+hmac.new(salt,os.path.realpath(args.path).encode(),hashlib.sha256).hexdigest()[:16]
            current.setdefault("labels",{})[key]=args.name
            require(len(current["labels"])<=128,"label_limit")
            atomic(directory,"friction-consent.json",encode(current))
            return dict(kind="friction_label",key=key,name=args.name)
        if op=="forget":
            if args.caller is not None: require(NAME.fullmatch(args.caller),"invalid_name")
            before=timestamp(args.before) if args.before is not None else None
            remove=0;rewrites=[]
            for name,raw in segments(directory):
                retained=[]
                for line in raw.splitlines(keepends=True):
                    try:
                        r=json.loads(line)
                        selected=args.all or before is not None and timestamp(r["ts"])<before or args.caller is not None and r["caller"].get("via")==args.caller
                    except (ValueError,KeyError,TypeError): selected=args.all
                    if selected:remove+=1
                    else:retained.append(line)
                rewrites.append((name,b"".join(retained)))
            if args.yes:
                for name,raw in rewrites:
                    if args.all: os.unlink(name,dir_fd=directory)
                    else: atomic(directory,name,raw)
                if args.all:
                    if optional(directory,"friction-salt",32) is not None:os.unlink("friction-salt",dir_fd=directory)
                    c=consent(directory)
                    if c is not None:
                        c["labels"]={};atomic(directory,"friction-consent.json",encode(c))
                os.fsync(directory)
            return dict(kind="friction_forget",would_remove=remove,applied=args.yes,call_log_changed=False)
        return report(directory,args)


def main(args):
    try:
        result=execute(args)
    except (OSError,ValueError,TypeError,KeyError):
        # Fixed reasons only: OS exception strings can contain supplied paths.
        error=sys.exc_info()[1]
        reason=str(error) if isinstance(error,ValueError) and re.fullmatch(r"[a-z_]+",str(error)) else "friction_io_refused"
        print(json.dumps(dict(ok=False,failure_reason=reason)),file=sys.stderr)
        return 1
    if args.operation=="report" and not args.json:
        for group in ("candidates","defects","refused","similar_not_same"):
            for row in sorted(result[group],key=lambda r:r.get("class","")!="verb_candidate"):print(group, row.get("class","similar_not_same"),row["support"]," → ".join(row["run"]))
        if not any(result[g] for g in ("candidates","defects","refused","similar_not_same")):print("No repeated call shapes meet the episode threshold.")
    else: print(json.dumps({"schema_version":1,**result}))
    return 0
