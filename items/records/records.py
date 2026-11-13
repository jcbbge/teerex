"""Private reasoning, evidence and decision applicability. pin add records dependencies; decide sets attributed options; claim-status explicitly accepts/withdraws; revalidate is read-only unless --write. Resume reads; only navigate focuses."""
import argparse
import contextlib
import copy
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time

SCHEMA = "teerex.records/1"
LIMIT = 1048576
KINDS = ("investigation", "experiment", "receipt", "handoff", "decision")
KIND_FIELDS = {"investigation": set(), "experiment": {"change_made", "pair_with", "cost"},
               "receipt": {"shipped_identity", "human_caveat"},
               "handoff": {"direction", "from", "to", "changes", "risks", "undo", "reply_to"},
               "decision": {"decision", "because", "options", "invalidators", "card_id"}}
REQUIRED_KIND_FIELDS = {"handoff": ("direction", "from", "to", "undo"),
                        "receipt": ("shipped_identity.repo", "shipped_identity.commit")}
PACKETS = {"friction_report": "teerex_friction", "run_visible_result": "teerex_run_visible", "run_result": "teerex_run",
           "observation_changes": "teerex_compare", "observation_wait": "teerex_watch"}
FLAGS = ("retry_safe", "task_completion", "painted_visibility", "all_descendants_verified_gone", "atomic_snapshot", "freshness", "interpretation")
DEFAULT_PRIVATE = ["notes", "target", "target_at_park", "subject.repo", "subject.untracked", "history[].previous"]
CONTENT = {"question", "next_action", "hypothesis", "discriminating_experiment", "claims", "checks", "omissions", "uncertainty", "notes", "subject", "cleanup", "kind_fields"}
VAGUE = {"continue", "keep digging", "keep investigating", "continue investigating", "tbd", "todo"}
SLUG = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
BASES = ("observed", "inferred", "supplied", "chosen")


class Refusal(Exception):
    def __init__(self, reason, code=1, **details):
        self.reason, self.code, self.details = reason, code, details


def require(ok, reason, code=1):
    if not ok:
        raise Refusal(reason, code)


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def loads(raw, reason="record_corrupt"):
    def pairs(items):
        d = {}
        for k, v in items:
            require(k not in d, reason)
            d[k] = v
        return d
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(Refusal(reason)))
    except (ValueError, UnicodeError):
        raise Refusal(reason)


def absolute(path):
    require(isinstance(path, str) and os.path.isabs(path) and "\0" not in path, "invalid_field:path")
    return path


def text(value, field, cap=4096, notes=False):
    require(isinstance(value, str) and bool(value), "invalid_field:" + field)
    try:
        raw = value.encode("utf-8")
    except UnicodeError:
        raise Refusal("invalid_utf8:" + field)
    require(len(raw) <= cap, "cap_exceeded:" + field)
    require(all((ord(c) >= 32 and not 127 <= ord(c) <= 159) or c in ("\t\n\r" if notes else "\t\n") for c in value), "control_character:" + field)
    return value


def private(fd, directory=False):
    s = os.fstat(fd)
    require(s.st_uid == os.getuid() and stat.S_IMODE(s.st_mode) == (0o700 if directory else 0o600)
            and (stat.S_ISDIR(s.st_mode) if directory else stat.S_ISREG(s.st_mode) and s.st_nlink == 1), "store_hazard")


def read_file(path, cap=LIMIT, store=False):
    absolute(str(path))
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            s = os.fstat(fd)
            require(s.st_uid == os.getuid() and stat.S_ISREG(s.st_mode) and s.st_nlink == 1, "store_hazard" if store else "evidence_hazard")
            if store:
                private(fd)
            with os.fdopen(fd, "rb", closefd=False) as f:
                raw = f.read(cap + 1)
            require(len(raw) <= cap, "record_oversize" if store else "evidence_oversize")
            return raw
        finally:
            os.close(fd)
    except OSError:
        raise Refusal("store_hazard" if store else "evidence_hazard")


def stdin_bytes(cap, oversize="fields_oversize"):
    end = time.monotonic() + 10
    parts = bytearray()
    with selectors.DefaultSelector() as sel:
        try:
            sel.register(sys.stdin.buffer, selectors.EVENT_READ)
        except PermissionError:  # regular redirected file on epoll
            raw = sys.stdin.buffer.read(cap + 1)
            require(len(raw) <= cap, oversize)
            return raw
        while True:
            wait = end - time.monotonic()
            if wait <= 0:
                raise Refusal("stdin_deadline", 124)
            if not sel.select(wait):
                raise Refusal("stdin_deadline", 124)
            part = os.read(sys.stdin.fileno(), min(8192, cap + 1 - len(parts)))
            if not part:
                return bytes(parts)
            parts.extend(part)
            require(len(parts) <= cap, oversize)


class Store:
    def __init__(self, path, write=False, init=False):
        self.path, self.fds = Path(absolute(path)), []
        try:
            if init:
                self.path.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.root = self.directory(self.path)
            flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | (os.O_CREAT if init else 0)
            fd = os.open("lock", flags, 0o600, dir_fd=self.root)
            self.fds.append(fd)
            private(fd)
            try:
                fcntl.flock(fd, (fcntl.LOCK_EX if write else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refusal("store_busy")
            if init:
                try:
                    os.mkdir("records", 0o700, dir_fd=self.root)
                except FileExistsError:
                    pass
            self.records = self.directory(self.path / "records")
            names = os.listdir(self.records)
            require(len(names) <= 4096, "store_full")
            require(all(SLUG.fullmatch(n) for n in names), "store_hazard")
        except BaseException:
            self.close()
            raise

    def directory(self, path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK)
        self.fds.append(fd)
        private(fd, True)
        return fd

    def close(self):
        for fd in reversed(self.fds):
            os.close(fd)
        self.fds.clear()

    def folder(self, rid):
        require(isinstance(rid, str) and SLUG.fullmatch(rid), "invalid_field:id")
        p = self.path / "records" / rid
        require(p.exists() or p.is_symlink(), "record_not_found")
        fd = self.directory(p)
        require(not any(n.startswith("record.json.tmp-") for n in os.listdir(fd)), "staging_present")
        evidence_fd = self.directory(p / "evidence")
        for opened in (evidence_fd, fd):
            self.fds.remove(opened)
            os.close(opened)
        return p

    def read(self, rid):
        p = self.folder(rid)
        r = loads(read_file(p / "record.json", store=True))
        require(isinstance(r, dict) and r.get("schema") == SCHEMA and r.get("id") == rid and type(r.get("generation")) is int, "record_corrupt")
        try:
            validate(r)
        except (Refusal, KeyError, TypeError, ValueError, AttributeError):
            raise Refusal("record_corrupt")
        return r

    def save(self, r, packets, new=False):
        try:
            return self._save(r, packets, new)
        except OSError as error:
            raise Refusal("internal_error", outcome="uncertain", exception_class=type(error).__name__)

    def _save(self, r, packets, new=False):
        # Never persist recognized credentials, including private notes/history or packet copies.
        # Refuse structural values rather than silently changing evidence identities.
        redact_record(r)
        for data in packets.values():
            require(not CREDENTIAL.search(data.decode("utf-8", "replace")), "secret_in_evidence")
        raw = encoded(r)
        require(len(raw) <= LIMIT, "record_oversize")
        p = self.path / "records" / r["id"]
        if new:
            require(len(os.listdir(self.records)) < 4096, "store_full")
            require(not p.exists() and not p.is_symlink(), "record_exists")
            p.mkdir(mode=0o700)
            (p / "evidence").mkdir(mode=0o700)
        else:
            self.folder(r["id"])
        for name, data in packets.items():
            fd = os.open(p / "evidence" / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        tmp = p / ("record.json.tmp-" + secrets.token_hex(8))
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p / "record.json")
        with contextlib.ExitStack() as stack:
            for d in (p / "evidence", p, p.parent):
                handle = os.open(d, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                stack.callback(os.close, handle)
                os.fsync(handle)
        check = read_file(p / "record.json", store=True)
        if sha(check) != sha(raw) or loads(check) != r:
            raise Refusal("readback_mismatch", outcome="uncertain")
        return sha(raw)


def packet_info(p):
    require(isinstance(p, dict) and type(p.get("schema_version")) is int and p["schema_version"] == 1, "unsupported_packet")
    kind = p.get("kind")
    typ = PACKETS.get(kind)
    if typ is None and "observation_id" in p and isinstance(p.get("capture"), dict):
        typ = "teerex_observation"
    require(typ is not None, "unsupported_packet")
    if typ == "teerex_observation":
        require("observation_id" in p and isinstance(p.get("capture"), dict), "unsupported_packet")
    elif typ == "teerex_friction":
        require(all(isinstance(p.get(k), list) for k in ("candidates", "defects", "refused")), "unsupported_packet")
    elif typ == "teerex_compare":
        require(isinstance(p.get("capture"), dict) and all(k in p for k in ("before_observation_id", "after_observation_id")), "unsupported_packet")
    else:
        require("outcome" in p, "unsupported_packet")
    require(p.get("target") is None or isinstance(p["target"], dict), "unsupported_packet")
    require(p.get("success") is None or type(p["success"]) is bool, "unsupported_packet")
    for field in ("exit_report", "exit", "stdout", "stderr"):
        require(p.get(field) is None or isinstance(p[field], dict), "unsupported_packet")
    ex = p.get("exit_report") if "exit_report" in p else p.get("exit")
    ex = ex if isinstance(ex, dict) else {}
    code = ex.get("exit_code") if "exit_code" in ex else ex.get("code")
    sig = ex.get("signal")
    require(code is None or type(code) is int, "unsupported_packet")
    require(sig is None or type(sig) is int and sig >= 0, "unsupported_packet")
    streams = {}
    for stream in ("stdout", "stderr"):
        value = p.get(stream)
        streams[stream] = (value.get("full_complete") if "full_complete" in value else value.get("complete")) if isinstance(value, dict) else None
    if isinstance(p.get("capture"), dict):
        streams = {k: copy.deepcopy(p["capture"].get(k)) for k in (("before_complete", "after_complete") if typ == "teerex_compare" else ("complete",))}
        if typ != "teerex_compare":
            streams = {"capture": streams["complete"]}
    if "output_complete" in p:
        streams = copy.deepcopy(p["output_complete"])
    return typ, dict(packet_kind=kind, schema_version=p.get("schema_version"), target=copy.deepcopy(p.get("target")),
                     source_version=copy.deepcopy(p.get("source_version", p.get("source"))), observation_id=p.get("observation_id"),
                     outcome=p.get("outcome"), exit=dict(code=code, signal=sig), reported_success=p.get("success"),
                     output_complete=streams, storage_dir=p.get("storage_dir", p.get("output_dir")),
                     storage_dir_retained=p.get("storage_dir_retained", p.get("storage_retained")), carried_flags={k: copy.deepcopy(p.get(k)) for k in FLAGS})


def file_hash(path):
    absolute(str(path))
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        s = os.fstat(fd)
        require(stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid() and s.st_nlink == 1, "evidence_hazard")
        require(s.st_size <= 64 * LIMIT, "evidence_oversize")
        h, n = hashlib.sha256(), 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                return "sha256:" + h.hexdigest(), n
            n += len(chunk)
            require(n <= 64 * LIMIT, "evidence_oversize")
            h.update(chunk)
    finally:
        os.close(fd)


def evidence_file(path):
    fd = os.open(absolute(path), os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        st = os.fstat(fd)
        require(st.st_uid == os.getuid() and stat.S_ISREG(st.st_mode) and st.st_nlink == 1, "evidence_hazard")
        require(st.st_size <= 64 * LIMIT, "evidence_oversize")
        with os.fdopen(fd, "rb", closefd=False) as f:
            head = f.read(LIMIT + 1)
            h, size = hashlib.sha256(head), len(head)
            while True:
                part = f.read(65536)
                if not part:
                    return head, "sha256:" + h.hexdigest(), size
                size += len(part)
                require(size <= 64 * LIMIT, "evidence_oversize")
                h.update(part)
    finally:
        os.close(fd)


def board_card(e):
    path = Path(e["locator"])
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        private(fd, True)
        lock = os.open("lock", os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=fd)
        try:
            private(lock)
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            state = loads(read_file(path / "state.json", store=True))
        finally:
            os.close(lock)
    finally:
        os.close(fd)
    seat = next((s for s in state.get("seats", []) if s.get("target") == e["seat"]), None)
    require(seat is not None, "evidence_hazard")
    found, resolved = None, False
    for r in seat.get("records", []):
        if r.get("kind") not in ("decision", "resolution"):
            continue
        b = r.get("body", {})
        require(isinstance(b, dict), "evidence_hazard")
        if b.get("id") == e["card_id"]:
            if r.get("kind") == "decision":
                found = {"card_id": b["id"], "title": b["title"], "state": "open", "answer_present": False}
            elif r.get("kind") == "resolution":
                require("answer" in b, "evidence_hazard")
                resolved = True
    require(found is not None, "evidence_hazard")
    if resolved:
        found.update(state="resolved", answer_present=True)
    return found


def directory_info(path):
    fd = os.open(absolute(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        require(os.fstat(fd).st_uid == os.getuid(), "evidence_hazard")
        names = sorted(os.listdir(fd))
        require(len(names) <= 256, "evidence_oversize")
        return {name: {"digest": file_hash(Path(path) / name)[0]} if name in ("stdout.full", "stderr.full") else {"private_contents_not_read": True} for name in names}
    finally:
        os.close(fd)


def attach_inputs(r, o, packets):
    assigned = []
    specs = o.inputs or []
    require(len(o.labels or []) <= len(specs) and len(o.exportable or []) <= len(specs), "invalid_field:evidence_labels", 2)
    for i, (flag, values) in enumerate(specs):
        require(len(r["evidence"]) < 256, "evidence_limit")
        eid = "e" + str(max([int(e["id"][1:]) for e in r["evidence"]] or [0]) + 1)
        e = dict(id=eid, type=None, label=(o.labels or [])[i] if i < len(o.labels or []) else eid,
                 locator=values[0], digest=None, bytes=None, recorded_at=now(), attached_by=o.by or o.writer,
                 availability_at_attach="present", moved_from=[], copy=None, supplied_by=o.supplied_by,
                 private=i not in (o.exportable or []), teerex=None)
        text(e["label"], "label", 128)
        require(not any(ord(c) < 32 for c in e["label"]), "control_character:label")
        try:
            if flag == "--evidence":
                if values[0] == "-":
                    raw = stdin_bytes(LIMIT, "evidence_oversize")
                    dg, size = sha(raw), len(raw)
                else:
                    raw, dg, size = evidence_file(values[0])
                if raw.lstrip().startswith(b"{") or values[0] == "-":
                    require(len(raw) <= LIMIT, "evidence_oversize")
                    p = loads(raw, "unsupported_packet")
                    looking = isinstance(p, dict) and ("schema_version" in p or "observation_id" in p or p.get("kind") in PACKETS)
                    if looking:
                        e["type"], e["teerex"] = packet_info(p)
                        require(sum(x["copy"] is not None for x in r["evidence"]) < 64, "evidence_limit")
                        e["copy"] = "evidence/" + eid + ".json"
                        packets[eid + ".json"] = raw
                if e["type"] is None:
                    e["type"] = "file"
                e["digest"], e["bytes"] = dg, size
            elif flag == "--evidence-dir":
                e.update(type="teerex_output_dir", files=directory_info(values[0]))
                e["digest"] = sha(encoded(e["files"]))
            elif flag == "--card":
                require(all(getattr(o, k) for k in ("card_id", "seat_host", "seat_socket", "seat_session", "seat_block")), "invalid_field:card", 2)
                e.update(type="board_card", card_id=o.card_id, seat=dict(host=o.seat_host, server="unix://" + absolute(o.seat_socket), session_id=o.seat_session, block_id=o.seat_block))
                e["card"] = board_card(e)
                e["digest"] = sha(encoded(e["card"]))
            elif flag == "--commit":
                absolute(values[0])
                require(re.fullmatch(r"[0-9a-f]{40}", values[1]), "invalid_field:commit", 2)
                e.update(type="commit", commit=values[1], basis="supplied", digest=sha(encoded(values)))
            elif flag == "--ref":
                require(values[0] in ("url", "human_report", "screenshot"), "invalid_field:ref", 2)
                e.update(type=values[0], locator=values[1], availability_at_attach="not_checked")
                require(e["type"] != "human_report" or o.supplied_by, "supplied_without_source")
            else:
                raise Refusal("invalid_field:evidence", 2)
        except (OSError, Refusal) as exc:
            reason = exc.reason if isinstance(exc, Refusal) else "evidence_hazard"
            if reason in ("evidence_hazard", "evidence_oversize", "store_hazard"):
                raise Refusal(("evidence_hazard" if reason == "store_hazard" else reason) + ":" + str(i))
            raise
        if e["digest"]:
            previous = next((x for x in r["evidence"] if x["type"] == e["type"] and x["digest"] == e["digest"]), None)
            require(previous is None, "duplicate_evidence:" + (previous["id"] if previous else ""))
        r["evidence"].append(e)
        assigned.append(eid)
        if o.check_command:
            require(e["teerex"] is not None, "invalid_field:check_packet", 2)
            ex = e["teerex"]["exit"]
            value = dict(command=o.check_command, ran="yes" if ex["code"] is not None or ex["signal"] is not None else "unknown",
                         process_exit=str(ex["code"]) if ex["code"] is not None else "signal:" + str(ex["signal"]) if ex["signal"] is not None else "unknown",
                         assertion=o.assertion, establishes=o.establishes, does_not_establish=o.does_not_establish, evidence=[eid])
            assigned.extend(append_elements(r, "checks", [value]))
    return assigned


def availability(e, folder, check=True):
    out = copy.deepcopy(e)
    out["availability_now"], out["copy_availability_now"] = "not_checked", "none"
    if check:
        try:
            if e["type"] == "board_card":
                out["card"] = board_card(e)
                status = "present"
            elif e["type"] == "teerex_output_dir":
                status = "present" if sha(encoded(directory_info(e["locator"]))) == e["digest"] else "digest_differs"
            elif e["type"] in ("commit", "url", "human_report", "screenshot") or e["locator"] == "-":
                status = "not_checked"
            else:
                status = "present" if file_hash(e["locator"])[0] == e["digest"] else "digest_differs"
        except FileNotFoundError:
            status = "missing"
        except (OSError, Refusal):
            status = "missing" if not os.path.lexists(e["locator"]) else "hazard_refused"
        out["availability_now"] = status
    if e["copy"] and not check:
        out["copy_availability_now"] = "not_checked"
    if e["copy"] and check:
        try:
            raw = read_file(folder / e["copy"], store=True)
            out["copy_availability_now"] = "present" if sha(raw) == e["digest"] else "digest_differs"
        except (OSError, Refusal):
            out["copy_availability_now"] = "missing" if not os.path.lexists(folder / e["copy"]) else "hazard_refused"
    return out


def append_elements(r, field, values):
    require(isinstance(values, list), "invalid_field:" + field)
    prefix, cap = {"claims": ("k", 128), "checks": ("c", 128), "omissions": ("o", 128), "items": ("u", 64)}[field]
    target = r["cleanup"]["items"] if field == "items" else r[field]
    require(len(target) + len(values) <= cap, "cap_exceeded:" + field)
    assigned = []
    for value in values:
        require(isinstance(value, dict) and "id" not in value, "invalid_field:" + field)
        value = copy.deepcopy(value)
        if field == "claims":
            require(not set(value) & {"status", "status_history", "original"}, "claim_status_requires_command")
        past = list(target)
        if field == "items":
            for entry in r["history"]:
                if entry["field"] == "cleanup" and isinstance(entry["previous"], dict):
                    past.extend(entry["previous"].get("items", []))
        value["id"] = prefix + str(max([int(v["id"][1:]) for v in past] or [0]) + 1)
        target.append(value)
        assigned.append(value["id"])
    return assigned


def validate(r):
    fields = {"schema", "kind", "id", "generation", "state", "written_at", "updated_at", "writer", "supersedes", "question", "hypothesis", "discriminating_experiment", "next_action", "claims", "checks", "omissions", "uncertainty", "notes", "subject", "target", "target_at_park", "evidence", "cleanup", "kind_fields", "history", "private"}
    require(fields <= set(r) <= fields | {"pins", "revalidation"} and r["schema"] == SCHEMA, "record_corrupt")
    require(r["kind"] in KINDS, "invalid_field:kind")
    require(SLUG.fullmatch(r["id"]) and isinstance(r["writer"], str), "invalid_field:identity")
    if r["target"] is not None:
        t = r["target"]
        require(isinstance(t, dict) and set(t) == {"host", "server", "session_id", "block_id"}, "invalid_field:target")
        require(isinstance(t["host"], str) and isinstance(t["server"], str) and t["server"].startswith("unix:///"), "invalid_field:target")
        for prefix in ("session", "block"):
            require(isinstance(t[prefix + "_id"], str) and re.fullmatch(prefix + r":[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", t[prefix + "_id"]), "invalid_field:target")
    for field in ("question", "discriminating_experiment", "notes"):
        require(r[field] is None or isinstance(r[field], str), "invalid_field:" + field)
    require(type(r["generation"]) is int and r["generation"] >= 0 and (r["state"] in ("open", "parked", "concluded", "abandoned") or r["state"].startswith("superseded_by:")), "invalid_field:state_or_generation")
    require(isinstance(r["evidence"], list) and len(r["evidence"]) <= 256 and sum(bool(e.get("copy")) for e in r["evidence"]) <= 64, "evidence_limit")
    if r["subject"] is not None:
        subject = r["subject"]
        allowed = {"repo", "commit", "dirty", "untracked", "untracked_truncated", "artifact", "digest", "basis"}
        require(isinstance(subject, dict) and set(subject) <= allowed, "invalid_field:subject")
        for key in ("repo", "commit", "artifact", "digest"):
            subject.setdefault(key, None)
            require(subject[key] is None or isinstance(subject[key], str), "invalid_field:subject." + key)
        subject.setdefault("dirty", "unknown")
        subject.setdefault("untracked", [])
        subject.setdefault("untracked_truncated", False)
        subject.setdefault("basis", "supplied")
        require(subject["dirty"] in ("true", "false", "unknown") and subject["basis"] in ("observed", "supplied") and isinstance(subject["untracked"], list) and len(subject["untracked"]) <= 256, "invalid_field:subject")
    if r["next_action"] is not None:
        require(isinstance(r["next_action"], dict) and set(r["next_action"]) == {"actor", "step", "stop_when"}, "invalid_field:next_action")
    if r["next_action"] is not None:
        require(all(v is None or isinstance(v, str) for v in r["next_action"].values()), "invalid_field:next_action")
    if r["hypothesis"] is not None:
        require(isinstance(r["hypothesis"], dict) and set(r["hypothesis"]) == {"text", "basis"} and r["hypothesis"]["basis"] in ("inferred", "chosen"), "invalid_field:hypothesis")
    if r["hypothesis"] is not None:
        require(isinstance(r["hypothesis"]["text"], str), "invalid_field:hypothesis")
    if r["uncertainty"] is not None:
        require(isinstance(r["uncertainty"], dict) and set(r["uncertainty"]) == {"text", "confidence"} and r["uncertainty"]["confidence"] in ("low", "medium", "high"), "invalid_field:uncertainty")
    if r["uncertainty"] is not None:
        require(isinstance(r["uncertainty"]["text"], str), "invalid_field:uncertainty")
    require(isinstance(r["cleanup"], dict) and set(r["cleanup"]) == {"status", "items"} and r["cleanup"]["status"] in ("none_needed", "done", "partial", "not_started", "unknown"), "invalid_field:cleanup")
    require(len(r["cleanup"]["items"]) <= 64 and len(r["history"]) <= 64, "cap_exceeded:history_or_cleanup")
    for evidence in r["evidence"]:
        require(isinstance(evidence, dict) and type(evidence.get("private")) is bool and isinstance(evidence.get("label"), str), "invalid_field:evidence")
        require(re.fullmatch(r"e[1-9][0-9]*", evidence.get("id", "")), "invalid_field:evidence.id")
    require(isinstance(r["kind_fields"], dict), "invalid_field:kind_fields")
    allowed_kind = KIND_FIELDS[r["kind"]]
    require(set(r["kind_fields"]) <= allowed_kind, "invalid_field:kind_fields")
    kind = r["kind_fields"]
    for field in ("change_made", "pair_with", "direction", "from", "to", "undo", "reply_to"):
        if field in kind:
            require(kind[field] is None or isinstance(kind[field], str), "invalid_field:kind_fields." + field)
    if kind.get("direction") is not None:
        require(kind["direction"] in ("inbound", "outbound"), "invalid_field:kind_fields.direction")
    for field in ("changes", "risks"):
        if kind.get(field) is not None:
            require(isinstance(kind[field], list) and all(isinstance(v, str) for v in kind[field]), "invalid_field:kind_fields." + field)
    if kind.get("changes") is not None:
        require(all(e in {v["id"] for v in r["evidence"]} for e in kind["changes"]), "invalid_field:kind_fields.changes")
    identity = kind.get("shipped_identity")
    if identity is not None:
        require(isinstance(identity, dict) and set(identity) <= {"repo", "commit", "tag", "artifact_digest"}, "invalid_field:kind_fields.shipped_identity")
        require(all(v is None or isinstance(v, str) for v in identity.values()), "invalid_field:kind_fields.shipped_identity")
        if identity.get("commit") is not None:
            require(re.fullmatch(r"[0-9a-f]{40}", identity["commit"]), "invalid_field:kind_fields.shipped_identity.commit")
    caveat = kind.get("human_caveat")
    if caveat is not None:
        require(isinstance(caveat, dict) and set(caveat) == {"text", "basis", "supplied_by"} and caveat["basis"] == "supplied"
                and isinstance(caveat["text"], str) and isinstance(caveat["supplied_by"], str), "invalid_field:kind_fields.human_caveat")
    for field, allowed, needed, cap in (
        ("claims", {"id", "text", "basis", "evidence", "supplied_by", "scope", "status", "depends_on", "contradicts", "supersedes", "status_history", "original"}, {"text", "basis"}, 128),
        ("checks", {"id", "command", "ran", "process_exit", "assertion", "establishes", "does_not_establish", "evidence"}, {"command", "ran", "process_exit", "assertion", "establishes", "does_not_establish"}, 128),
        ("omissions", {"id", "what", "reason"}, {"what", "reason"}, 128)):
        require(isinstance(r[field], list) and len(r[field]) <= cap, "cap_exceeded:" + field)
        for v in r[field]:
            require(isinstance(v, dict) and set(v) <= allowed and needed <= set(v), "invalid_field:" + field)
            for key in needed - {"basis", "ran", "assertion"}:
                require(isinstance(v[key], str), "invalid_field:" + field + "." + key)
            if field in ("claims", "checks"):
                v.setdefault("evidence", [])
                require(isinstance(v["evidence"], list) and all(e in {x["id"] for x in r["evidence"]} for e in v["evidence"]), "invalid_field:evidence_ids")
            if field == "claims":
                v.setdefault("supplied_by", None)
                v.setdefault("scope", None)
                require(v["supplied_by"] is None or isinstance(v["supplied_by"], str), "invalid_field:supplied_by")
                require(v["scope"] is None or isinstance(v["scope"], str), "invalid_field:scope")
                require(v["basis"] in BASES, "invalid_field:basis")
                require(v["basis"] != "observed" or v["evidence"], "observed_claim_without_evidence")
                require(v["basis"] != "supplied" or v["supplied_by"], "supplied_without_source")
            if field == "checks":
                require(v["ran"] in ("yes", "no", "unknown") and v["assertion"] in ("passed", "failed", "not_evaluated", "unknown"), "invalid_field:check")
                require(isinstance(v["process_exit"], str) and re.fullmatch(r"(?:-?[0-9]+|signal:[0-9]+|unknown)", v["process_exit"]), "invalid_field:process_exit")
    for item in r["cleanup"]["items"]:
        require(isinstance(item, dict) and all(isinstance(item.get(k), str) for k in ("id", "what", "where", "owner")), "invalid_field:cleanup.items")
        require(set(item) == {"id", "what", "where", "owner"}, "invalid_field:cleanup.items")
    require(isinstance(r["private"], list) and all(isinstance(p, str) for p in r["private"]), "invalid_field:private")
    permitted_private = set(DEFAULT_PRIVATE + ["subject", "evidence[].locator", "evidence[].copy", "evidence[].digest", "evidence[].moved_from", "evidence[].supplied_by", "evidence[].teerex.target", "evidence[].teerex.storage_dir", "kind_fields.shipped_identity.repo", "pins", "pins[].target", "pins[].recorded_value", "pins[].last_value"])
    require(set(r["private"]) <= permitted_private, "invalid_field:private")
    def walk(v, path):
        if isinstance(v, str):
            if v == "" and path.startswith("next_action."):
                return
            text(v, path, 16384 if path == "notes" else 4096, path == "notes")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, path + "." + str(i))
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x, path + "." + k if path else k)
        else:
            require(v is None or type(v) in (int, bool, float), "invalid_field:" + path)
    decision_validate(r)
    walk(r, "")


def replace(r, field, value, by):
    if field in ("question", "next_action", "hypothesis", "uncertainty") or field == "cleanup" and r["cleanup"]["items"]:
        require(len(r["history"]) < 64, "cap_exceeded:history")
        r["history"].append(dict(generation=r["generation"], field=field, previous=copy.deepcopy(r[field]), replaced_at=now(), by=by))
    r[field] = copy.deepcopy(value)


def content(o, allowed=CONTENT):
    values = {}
    if o.fields_file:
        try:
            raw = stdin_bytes(65536) if o.fields_file == "-" else read_file(o.fields_file, 65536)
        except Refusal as e:
            if e.reason == "evidence_oversize":
                raise Refusal("fields_oversize")
            raise
        values = loads(raw, "invalid_field:fields_file")
        require(isinstance(values, dict), "invalid_field:fields_file")
    for key in values:
        require(key in allowed, "unknown_field:" + key)
    flags = {}
    for field in ("question", "discriminating_experiment"):
        if getattr(o, field, None) is not None:
            flags[field] = getattr(o, field)
    if any(getattr(o, "next_" + k, None) is not None for k in ("actor", "step", "stop_when")):
        flags["next_action"] = {k: getattr(o, "next_" + k, None) for k in ("actor", "step", "stop_when")}
    if o.hypothesis is not None:
        flags["hypothesis"] = dict(text=o.hypothesis, basis=o.hypothesis_basis)
    if o.uncertainty is not None:
        flags["uncertainty"] = dict(text=o.uncertainty, confidence=o.confidence)
    require(not set(values).intersection(flags), "field_flag_file_conflict", 2)
    values.update(flags)
    for key in flags:
        require(key in allowed, "unknown_field:" + key)
    return values


def apply_content(r, values, by, creating=False):
    assigned = []
    for field, value in values.items():
        if field in ("claims", "checks", "omissions"):
            assigned.extend(append_elements(r, field, value))
        elif field == "cleanup":
            require(isinstance(value, dict) and set(value) <= {"status", "items"}, "invalid_field:cleanup")
            items = copy.deepcopy(value.get("items", []))
            replace(r, "cleanup", dict(status=value.get("status", "unknown"), items=[]), by)
            assigned.extend(append_elements(r, "items", items))
        elif creating:
            r[field] = copy.deepcopy(value)
        else:
            replace(r, field, value, by)
    return assigned


def process(argv, timeout=5, cap=LIMIT):
    env = dict(os.environ)
    for k in ("REX_SERVER", "REX_SESSION", "REX_BLOCK", "REX_CLIENT"):
        env.pop(k, None)
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, env=env, start_new_session=True)
    raw, diagnostics = bytearray(), 0
    end = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as sel:
            sel.register(p.stdout, selectors.EVENT_READ, True)
            sel.register(p.stderr, selectors.EVENT_READ, False)
            while sel.get_map():
                remaining = end - time.monotonic()
                require(remaining > 0, "transport_deadline")
                for key, _ in sel.select(min(remaining, .1)):
                    part = os.read(key.fd, 8192)
                    if not part:
                        sel.unregister(key.fileobj)
                    elif key.data:
                        raw.extend(part)
                        require(len(raw) <= cap, "transport_oversize")
                    else:
                        diagnostics += len(part)
                        require(diagnostics <= 4096, "transport_diagnostics_oversize")
        try:
            p.wait(timeout=max(.001, end - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise Refusal("transport_deadline")
        return p.returncode, bytes(raw)
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(p.pid, signal.SIGKILL)
        p.wait()
        p.stdout.close()
        p.stderr.close()


def invoke(args, timeout):
    binary = os.environ["TEEREX_RECORDS_EXECUTABLE"]
    pin = os.environ.get("TEEREX_INTERNAL_REX") or os.environ.get("TEEREX_REX")
    code, raw = process([binary, *(["--rex", pin] if pin else []), *args], timeout)
    return code, loads(raw, "transport_invalid")


def target_status(target, baseline, host, timeout, enabled=True):
    result = dict(checked=enabled, status="not_checked", server_identity=None, pane=None, checked_at=now())
    if not target:
        result["status"] = "no_target_recorded"
        return result
    if host is not None and host != target["host"]:
        result["status"] = "different_server"
        return result
    if not enabled:
        return result
    socket = target["server"][7:]
    pin = os.environ.get("TEEREX_INTERNAL_REX") or os.environ.get("TEEREX_REX") or shutil.which("rex")
    try:
        require(pin is not None, "rex_unavailable")
        base = [pin, "--autostart=false", "--server", target["server"], "--timeout", "3s", "api", "call"]
        _, raw = process(base + ["server.version", "{}"], timeout)
        version = loads(raw, "transport_invalid")
        _, raw = process(base + ["server.status", "{}"], timeout)
        status = loads(raw, "transport_invalid")
        require(isinstance(status.get("host_id"), str) and isinstance(status.get("instance_id"), str), "identity_unavailable")
    except (OSError, Refusal):
        result["status"] = "server_unreachable"
        return result
    identity = dict(instance_id=status["instance_id"], host_id=status["host_id"], version=version.get("rex_version"), api=version.get("api_revision"))
    result["server_identity"] = identity
    old = (baseline or {}).get("server_identity") or {}
    if old.get("host_id") and old["host_id"] != identity["host_id"]:
        result["status"] = "different_server"
        return result
    if old.get("instance_id") and old["instance_id"] != identity["instance_id"]:
        result.update(status="server_instance_changed", hint="recovery remap receipts may map this pane; records does not follow them")
        return result
    try:
        code, inspect = invoke(["surfaces", "inspect", "--socket", socket, "--session", target["session_id"], "--pane", target["block_id"], "--timeout-ms", str(int(timeout * 1000))], timeout + 1)
        actual = inspect.get("actual")
        if code == 0 and inspect.get("outcome") == "inspected" and isinstance(actual, dict) and actual.get("attached"):
            if actual.get("session_id") != target["session_id"] or actual.get("block_id") != target["block_id"]:
                result["status"] = "unknown"
                return result
            pane = {k: actual.get(k) for k in ("label", "window_label", "host_id")}
            result["pane"] = pane
            if ((baseline or {}).get("pane") or {}).get("host_id") and baseline["pane"]["host_id"] != pane["host_id"]:
                result["status"] = "block_host_changed"
            else:
                result["status"] = "available_unverified_instance" if baseline is not None and not old.get("instance_id") else "available"
        elif inspect.get("outcome") == "refused" and inspect.get("failure_reason") in ("pane_not_attached_terminal", "target_not_found", "session_unavailable"):
            result["status"] = "absent"
        else:
            result["status"] = "unknown"
    except (OSError, Refusal, AttributeError):
        result["status"] = "unknown"
    return result


def missing_kind_fields(r):
    missing = []
    for path in REQUIRED_KIND_FIELDS.get(r["kind"], ()):
        value = r["kind_fields"]
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if not value:
            missing.append("kind_fields." + path)
    return missing


def lint(r, folder, packets=None):
    violations = []
    def bad(rule, path, message):
        violations.append(dict(rule=rule, path=path, message=message))
    nxt = r["next_action"]
    if r["state"] in ("open", "parked") and (not isinstance(nxt, dict) or any(not isinstance(nxt.get(k), str) or not nxt[k].strip() for k in ("actor", "step", "stop_when")) or nxt["step"].strip().lower() in VAGUE):
        bad("L1-next-action", "next_action", "complete specific next action required")
    evidence = {e["id"]: availability(e, folder) for e in r["evidence"]}
    for claim in r["claims"]:
        refs = [evidence[e] for e in claim["evidence"]]
        if claim["basis"] == "observed" and all(e["availability_now"] in ("missing", "deleted", "digest_differs", "hazard_refused") for e in refs):
            bad("L2-observed-evidence", "claims." + claim["id"], "observed evidence unavailable")
        if claim["basis"] == "observed":
            for word in re.findall(r"\b(production|prod|deployed|live|released|customer)\b", claim["text"], re.I):
                if not any(word.lower() in c["establishes"].lower() and set(c["evidence"]) & set(claim["evidence"]) for c in r["checks"]):
                    bad("L4-scope-words", "claims." + claim["id"], "scope word lacks linked check")
    for c in r["checks"]:
        if c["assertion"] in ("passed", "failed") and c["ran"] != "yes" or c["ran"] == "no" and not any(c["id"] in o["what"] or c["id"] in o["reason"] for o in r["omissions"]):
            bad("L3-check-consistency", "checks." + c["id"], "execution/assertion/omission inconsistent")
    for e in evidence.values():
        if e["copy"]:
            try:
                raw = packets.get(Path(e["copy"]).name) if packets and Path(e["copy"]).name in packets else read_file(folder / e["copy"], store=True)
                if sha(raw) != e["digest"] or packet_info(loads(raw, "unsupported_packet"))[1] != e["teerex"]:
                    bad("L5-packet-integrity", "evidence." + e["id"], "copied packet or derived fields changed")
            except (OSError, Refusal):
                bad("L5-packet-integrity", "evidence." + e["id"], "copied packet unavailable")
        t = e.get("teerex") or {}
        if r["cleanup"]["status"] == "done" and t.get("storage_dir_retained") is True and t.get("storage_dir") and os.path.exists(t["storage_dir"]):
            bad("L7-cleanup-retained", "cleanup.status", "retained storage still exists")
    k = r["kind_fields"]
    if (missing_kind_fields(r) or r["kind"] in ("experiment", "receipt") and not r["checks"]
        or r["state"] == "parked" and (not r["target"] or not r["target_at_park"])):
        bad("L6-kind-required", "kind_fields", "kind requirements incomplete")
    if r["kind"] == "handoff" and k.get("direction") == "inbound" and any(c["basis"] == "supplied" and not c["evidence"] for c in r["claims"]) and nxt is None:
        bad("L8-handoff-authority", "next_action", "inbound supplied claim grants no authority")
    violations.extend(decision_lint(r))
    return violations


def render(r, folder, evidence_check=True):
    reasoning = {k: copy.deepcopy(r[k]) for k in ("question", "next_action", "hypothesis", "discriminating_experiment", "claims", "checks", "omissions", "cleanup", "uncertainty", "notes", "subject", "kind_fields")}
    if r["kind"] == "decision":
        reasoning.update(decision_view(r))
    reasoning["claims"] = sorted(reasoning["claims"], key=lambda c: BASES.index(c["basis"]))
    reasoning["missing"] = [k for k in ("question", "next_action", "hypothesis", "discriminating_experiment", "uncertainty", "notes", "subject") if r[k] is None]
    if r["cleanup"]["status"] == "unknown" and not r["cleanup"]["items"]:
        reasoning["missing"].append("cleanup")
    return dict(schema_version=1, kind="records_show", record={k: r[k] for k in ("id", "kind", "state", "generation", "written_at", "updated_at", "writer")},
                reasoning=reasoning, evidence=[availability(e, folder, evidence_check) for e in r["evidence"]], history=copy.deepcopy(r["history"]))


def escape_bidi(s):
    return ''.join("\\u{%04x}" % ord(c) if 0x202a <= ord(c) <= 0x202e or 0x2066 <= ord(c) <= 0x2069 else c for c in s)


def as_text(value):
    if isinstance(value, list):
        return escape_bidi("\n".join(json.dumps(v, ensure_ascii=False) for v in value)) + "\n"
    lines = ["REASONING"]
    decision = value.get("reasoning", {}).get("decision")
    if decision:
        rr = value["reasoning"]
        lines += ["Decision: " + decision["text"], "Authority: " + decision["authority"] + " · " + decision["decided_by"],
                  "State: " + value.get("record", {}).get("state", value.get("state", "unknown")),
                  "needs_review: " + ("yes" if rr["needs_review"] else "no") + " · " + "; ".join(rr["review_reasons"])]
        if rr["claim_caveat"]:
            lines.append(rr["claim_caveat"])
        pins = {p["id"]: p for p in rr["pins"]}
        for cid in value["reasoning"]["kind_fields"].get("because", []):
            c = next(c for c in rr["claims"] if c["id"] == cid)
            lines.append("Claim " + cid + ": " + json.dumps(c, ensure_ascii=False))
            for dep in c["depends_on"]:
                if dep in pins:
                    lines.append("Pin " + dep + ": " + json.dumps(pins[dep], ensure_ascii=False))
        lines.extend(rr["open_contradictions"])
        for option in rr["options"]:
            lines.append("Option: " + json.dumps(option, ensure_ascii=False) + " · " + ("revisit_due" if option["id"] in rr["revisit_due"] else "revisit: pinned condition" if option.get("revisit_when") else "revisit: manual"))
        lines += ["Invalidators: " + json.dumps(rr["kind_fields"].get("invalidators", []), ensure_ascii=False),
                  "EVIDENCE (historical, re-checked now)", json.dumps(value.get("evidence", []), ensure_ascii=False)]
        return escape_bidi("\n".join(lines)) + "\n"
    reasoning = value.get("reasoning", value)
    lines.append("Question: " + str(reasoning.get("question")))
    nxt = reasoning.get("next_action")
    lines.append("Next action: " + (" · ".join(str(nxt.get(k)) for k in ("actor", "step", "stop_when")) if isinstance(nxt, dict) else "missing"))
    for k, v in reasoning.items():
        if k not in ("question", "next_action"):
            lines.append(k + ": " + json.dumps(v, ensure_ascii=False))
    lines += ["EVIDENCE (historical, re-checked now)", json.dumps(value.get("evidence", []), ensure_ascii=False)]
    if "target" in value:
        lines += ["TARGET (now)", json.dumps(value["target"], ensure_ascii=False)]
    return escape_bidi("\n".join(lines)) + "\n"


SECRET = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|(?i:\b(api[_-]?key|secret|token|passwd|password|bearer)\b\s*[:=]\s*\S{8,})|\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}|\bsk-[A-Za-z0-9_-]{20,}|\bxox[abpr]-[A-Za-z0-9-]{10,}|\bAKIA[0-9A-Z]{16}\b|eyJ[A-Za-z0-9_-]{10,}\.|[A-Za-z0-9+/=_-]{40,}")


# Deliberately excludes generic long strings: hashes and identity pins must remain exact.
CREDENTIAL = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)|(?i:\b(?:api[_-]?key|secret|token|passwd|password)\b\s*[:=]\s*[^\s\"',}]{8,}|\bbearer\s+[A-Za-z0-9._~-]{8,})|\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}|\bsk-[A-Za-z0-9_-]{20,}|\bxox[abprs]-[A-Za-z0-9-]{10,}|\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


def redact_record(value):
    """Redact prose before storage; identifiers/locators refuse instead of losing identity."""
    prose = {"question", "notes", "text", "step", "stop_when", "hypothesis", "discriminating_experiment", "reason", "why", "what", "establishes", "does_not_establish", "command", "revisit_text"}
    def walk(v, field=None):
        if isinstance(v, dict):
            for k in v:
                require(not CREDENTIAL.search(k), "secret_in_field_name")
                v[k] = walk(v[k], k)
        elif isinstance(v, list):
            for i in range(len(v)):
                v[i] = walk(v[i], field)
        elif isinstance(v, str) and CREDENTIAL.search(v):
            require(field in prose, "secret_in_structural_field")
            return CREDENTIAL.sub("[REDACTED]", v)
        return v
    walk(value)


def erase_file(path):
    """Best effort logical overwrite; no physical-media erasure claim on SSD/COW/backups."""
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        private(fd)
        remaining = os.fstat(fd).st_size
        require(remaining <= LIMIT, "record_oversize")
        while remaining:
            count = os.write(fd, b"\0" * min(remaining, 65536))
            require(count > 0, "erase_short_write")
            remaining -= count
        os.fsync(fd)
        os.ftruncate(fd, 0)
        os.fsync(fd)
    finally:
        os.close(fd)
    path.unlink()


def export_record(r):
    out = copy.deepcopy(r)
    omitted = list(r["private"])
    # Private evidence never loses packet caveats, only private locators/identity.
    for e in out["evidence"]:
        if e["private"]:
            for key in ("locator", "digest", "copy", "moved_from", "supplied_by", "seat"):
                e.pop(key, None)
            if e["teerex"]:
                e["teerex"].pop("target", None)
                e["teerex"].pop("storage_dir", None)
        e.pop("seat", None)
    for item in out["cleanup"]["items"]:
        item.pop("where", None)
        item.pop("owner", None)
    def drop(v, parts):
        if not parts or not isinstance(v, dict):
            return
        part = parts[0]
        if part.endswith("[]"):
            for item in v.get(part[:-2], []):
                drop(item, parts[1:])
        elif len(parts) == 1:
            v.pop(part, None)
        elif part in v:
            drop(v[part], parts[1:])
    for path in r["private"]:
        drop(out, path.split("."))
    if r.get("target_at_park"):
        out["target_at_park"] = {"status": r["target_at_park"]["status"]}
    if isinstance(out.get("kind_fields", {}).get("shipped_identity"), dict):
        out["kind_fields"]["shipped_identity"].pop("repo", None)
    out["private_fields_omitted"] = omitted
    out["secret_scan"] = "heuristic_floor_only"
    def scan(v, path=""):
        if isinstance(v, str):
            exempt = path.rsplit(".", 1)[-1] in ("digest", "commit", "artifact_digest") and re.fullmatch(r"(?:sha256:)?[0-9a-f]{40,64}", v)
            pin_path = re.fullmatch(r"pins\.([0-9]+)\.(recorded_value|last_value)", path)
            if pin_path and out["pins"][int(pin_path[1])]["type"] in ("git_ref", "file_sha256"):
                exempt = bool(re.fullmatch(r"(?:sha256:)?[0-9a-f]{40,64}", v))
            require(exempt or not SECRET.search(v), "secret_pattern:" + path)
        elif isinstance(v, dict):
            for k, x in v.items():
                require(not SECRET.search(k), "secret_pattern:" + (path + ".key" if path else "key"))
                scan(x, path + "." + k if path else k)
        elif isinstance(v, list):
            for i, x in enumerate(v):
                scan(x, path + "." + str(i))
    scan(out)
    return out


def set_field(r, path, value, by):
    decision_set_guard(r, path, value, by)
    if path.startswith("kind_fields.options.") or path.startswith("options."):
        oid = path.split(".")[-2]
        option = next((x for x in r["kind_fields"].get("options", []) if x["id"] == oid), None)
        require(option is not None and path.endswith(".status"), "invalid_field:option")
        option["status"] = value
        return
    parts = path.split(".")
    if len(parts) == 1 and path in {"question", "next_action", "hypothesis", "discriminating_experiment", "uncertainty", "private", "notes", "kind_fields"}:
        require(path != "notes", "notes_require_fields_file", 2)
        replace(r, path, value, by)
    elif path == "cleanup.status":
        r["cleanup"]["status"] = value
    elif parts[0] == "kind_fields" and len(parts) == 2:
        r["kind_fields"][parts[1]] = value
    elif parts[0] in ("claims", "checks", "omissions", "evidence") and len(parts) == 3:
        target = next((x for x in r[parts[0]] if x["id"] == parts[1]), None)
        require(target is not None and parts[2] != "id", "invalid_field:" + path)
        if parts[0] == "evidence":
            require(parts[2] in ("locator", "label", "private", "supplied_by"), "invalid_field:" + path)
            if parts[2] == "locator":
                absolute(value)
                target["moved_from"].append(target["locator"])
        else:
            require(parts[2] in target, "invalid_field:" + path)
        target[parts[2]] = value
    else:
        raise Refusal("unknown_field:" + path)


def git_subject(path):
    absolute(path)
    outputs = []
    for args in (["rev-parse", "HEAD"], ["status", "--porcelain=v1", "-z"], ["ls-files", "--others", "--exclude-standard", "-z"]):
        try:
            code, raw = process(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", path, *args], cap=4 * LIMIT)
            require(code == 0, "git_failed")
            outputs.append(raw)
        except (OSError, Refusal):
            raise Refusal("git_failed")
    untracked = outputs[2].decode("utf-8").split("\0")[:-1]
    return dict(repo=path, commit=outputs[0].decode().strip(), dirty="true" if outputs[1] else "false", untracked=untracked[:256],
                untracked_truncated=len(untracked) > 256, artifact=None, digest=None, basis="observed")


# H06 adds applicability to records; probes report facts, never grant authority.
PIN_TYPES = ("git_ref", "file_sha256", "program_version", "gh_issue_state", "supplied")


def decision_validate(r):
    pins = r.get("pins", [])
    require(isinstance(pins, list) and len(pins) <= 64, "cap_exceeded:pins")
    ids = set()
    for p in pins:
        require(isinstance(p, dict) and set(p) == {"id", "type", "target", "recorded_value", "recorded_at", "basis", "last_value", "last_checked", "last_result"}, "invalid_field:pin")
        require(re.fullmatch(r"p[1-9][0-9]*", p["id"]) and p["id"] not in ids and p["type"] in PIN_TYPES, "invalid_field:pin")
        ids.add(p["id"])
        require(p["basis"] in ("observed", "supplied") and p["last_result"] in ("unchecked", "unchanged", "changed", "unavailable", "not_rechecked"), "invalid_field:pin")
        require(all(isinstance(p[k], str) for k in ("target", "recorded_value", "recorded_at")), "invalid_field:pin")
    claims = {c["id"]: c for c in r["claims"]}
    for c in r["claims"]:
        c.setdefault("status", "provisional")
        c.setdefault("depends_on", [])
        c.setdefault("contradicts", [])
        c.setdefault("supersedes", None)
        c.setdefault("status_history", [dict(status="provisional", at=r["written_at"], by=r["writer"], reason="claim recorded")])
        require("original" not in c or isinstance(c["original"], dict) and set(c["original"]) == {"text", "basis"} and all(isinstance(v, str) for v in c["original"].values()), "invalid_field:claim.original")
        require(c["status"] in ("provisional", "accepted", "stale", "withdrawn"), "invalid_field:claim.status")
        require(all(isinstance(c[k], list) and all(isinstance(x, str) for x in c[k]) for k in ("depends_on", "contradicts")), "invalid_field:claim.links")
        require(all(x in claims and x != c["id"] for x in c["contradicts"]) and (c["supersedes"] is None or c["supersedes"] in claims and c["supersedes"] != c["id"]), "invalid_field:claim.links")
        require(isinstance(c["status_history"], list) and len(c["status_history"]) <= 128, "cap_exceeded:claim_history")
        for h in c["status_history"]:
            require(isinstance(h, dict) and set(h) == {"status", "at", "by", "reason"} and h["status"] in ("provisional", "accepted", "stale", "withdrawn") and all(isinstance(x, str) for x in h.values()), "invalid_field:claim_history")
    if r["kind"] != "decision":
        return
    k = r["kind_fields"]
    if not k:
        return
    require(set(k) == {"decision", "because", "options", "invalidators", "card_id"}, "invalid_field:decision")
    d = k["decision"]
    require(isinstance(d, dict) and set(d) == {"text", "decided_by", "authority", "authority_ref", "decided_at"} and all(isinstance(x, str) for x in d.values()), "invalid_field:decision")
    require(d["authority"] in ("operator_standing", "operator", "agent_rubric"), "invalid_field:authority")
    require(d["authority_ref"] in {e["id"] for e in r["evidence"]}, "invalid_field:authority_ref")
    require(isinstance(k["because"], list) and all(x in claims for x in k["because"]), "invalid_field:because")
    require(k["card_id"] is None or isinstance(k["card_id"], str), "invalid_field:card_id")
    for field, prefix, allowed, needed in (("options", "o", {"id", "label", "status", "why", "revisit_when", "revisit_text", "history"}, {"id", "label", "status", "why"}), ("invalidators", "v", {"id", "text", "pin", "condition"}, {"id", "text"})):
        require(isinstance(k[field], list) and len(k[field]) <= 64, "invalid_field:" + field)
        seen = set()
        for x in k[field]:
            require(isinstance(x, dict) and needed <= set(x) <= allowed and re.fullmatch(prefix + r"[1-9][0-9]*", x["id"]) and x["id"] not in seen, "invalid_field:" + field)
            seen.add(x["id"])
            require(all(isinstance(x[a], str) for a in needed), "invalid_field:" + field)
            if field == "options":
                require(x["status"] in ("chosen", "rejected"), "invalid_field:option.status")
                require(isinstance(x.get("revisit_when", []), list), "invalid_field:revisit_when")
                for cond in x.get("revisit_when", []):
                    require(isinstance(cond, dict) and set(cond) in ({"pin", "becomes"}, {"pin", "changes"}) and isinstance(cond.get("becomes", ""), str) and ("changes" not in cond or cond["changes"] is True), "invalid_field:revisit_when")
                    require(isinstance(cond["pin"], str), "invalid_field:revisit_when.pin")
            elif "pin" in x:
                require(isinstance(x["pin"], str), "invalid_field:invalidator.pin")
                require(x.get("condition") == "changes" or isinstance(x.get("condition"), dict) and set(x["condition"]) == {"becomes"} and isinstance(x["condition"]["becomes"], str), "invalid_field:invalidator.condition")


def decision_link(r, by):
    for c in r["claims"]:
        c.setdefault("status_history", [dict(status="provisional", at=now(), by=by, reason="claim recorded")])
    decision_validate(r)
    claims = {c["id"]: c for c in r["claims"]}
    for c in list(claims.values()):
        for other in c["contradicts"]:
            if c["id"] not in claims[other]["contradicts"]:
                claims[other]["contradicts"].append(c["id"])
    protected = set(r["kind_fields"].get("because", [])) if r["kind"] == "decision" else set()
    for c in claims.values():
        if c["contradicts"] or c["supersedes"]:
            protected.add(c["id"])
            protected.update(c["contradicts"])
            if c["supersedes"]:
                protected.add(c["supersedes"])
    for cid in protected:
        c = claims[cid]
        c.setdefault("original", {key: c[key] for key in ("text", "basis")})


def decision_lint(r):
    out = []
    def bad(rule, path):
        out.append(dict(rule=rule, path=path, message="decision applicability requirement"))
    known = {p["id"] for p in r.get("pins", [])} | {e["id"] for e in r["evidence"]}
    for c in r["claims"]:
        if any(x not in known for x in c.get("depends_on", [])):
            bad("L12-dangling-dependency", "claims." + c["id"])
        if "original" in c and any(c[key] != c["original"].get(key) for key in ("text", "basis")):
            bad("L11-claim-immutable", "claims." + c["id"])
    if r["kind"] != "decision":
        return out
    k = r["kind_fields"]
    if not all(k.get("decision", {}).get(x) for x in ("text", "decided_by", "authority", "authority_ref")) or not k.get("because") or not any(x.get("status") == "rejected" for x in k.get("options", [])) or any(not x.get("why") for x in k.get("options", []) if x.get("status") == "rejected") or not k.get("invalidators"):
        bad("L9-decision-shape", "kind_fields")
    for option in k.get("options", []):
        if any(cond["pin"] not in known for cond in option.get("revisit_when", [])):
            bad("L12-dangling-dependency", "kind_fields.options." + option["id"])
    for inv in k.get("invalidators", []):
        if "pin" in inv and inv["pin"] not in known:
            bad("L12-dangling-dependency", "kind_fields.invalidators." + inv["id"])
    claims = {c["id"]: c for c in r["claims"]}
    uncertainty = (r["uncertainty"] or {}).get("text", "")
    for cid in k.get("because", []):
        c = claims[cid]
        for other in c.get("contradicts", []):
            if r["state"] == "concluded" and c["status"] != "withdrawn" and claims[other]["status"] != "withdrawn" and not all(re.search(r"\b" + re.escape(x) + r"\b", uncertainty) for x in (cid, other)):
                bad("L10-open-contradiction", "claims." + cid)
    return out


def pin_probe(p, gh=None):
    typ, target = p["type"], p["target"]
    try:
        if typ == "file_sha256":
            return file_hash(absolute(target))[0]
        if typ == "git_ref":
            repo, ref = target.rsplit("@", 1)
            absolute(repo)
            require(ref and not ref.startswith("-"), "pin_probe_failed")
            code, raw = process(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", repo, "rev-parse", "--verify", "--end-of-options", ref], cap=4096)
        elif typ == "program_version":
            code, raw = process([absolute(target), "--version"], cap=65536)
            require(code == 0 and raw.splitlines(), "pin_probe_failed")
            line = raw.splitlines()[0]
            require(len(line) <= 256, "pin_probe_failed")
            return line.decode("utf-8")
        elif typ == "gh_issue_state":
            require(gh and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*", target), "pin_probe_failed")
            repo, num = target.split("#")
            code, raw = process([absolute(gh), "issue", "view", num, "--repo", repo, "--json", "state,stateReason"], cap=4096)
            require(code == 0, "pin_probe_failed")
            v = loads(raw)
            require(v.get("state") in ("OPEN", "CLOSED"), "pin_probe_failed")
            require(v["state"] == "OPEN" or v.get("stateReason") in ("COMPLETED", "NOT_PLANNED", "REOPENED"), "pin_probe_failed")
            return "OPEN" if v["state"] == "OPEN" else "CLOSED:" + v["stateReason"]
        else:
            raise Refusal("pin_probe_failed")
        require(code == 0 and re.fullmatch(rb"[0-9a-f]{40,64}\n?", raw), "pin_probe_failed")
        return raw.decode().strip()
    except (OSError, ValueError, UnicodeError, Refusal):
        raise Refusal("pin_probe_failed")


def decision_mutate(r, o):
    require(o.by is not None, "by_required", 2)
    if o.operation == "pin":
        require(o.entries == ["add"] and o.type in PIN_TYPES and o.target, "pin_fields_required", 2)
        pins = r.setdefault("pins", [])
        require(len(pins) < 64, "cap_exceeded:pins")
        p = dict(id="p" + str(len(pins) + 1), type=o.type, target=o.target, recorded_at=now(), basis="supplied" if o.value is not None else "observed", last_value=None, last_checked=None, last_result="unchecked")
        require(o.type != "supplied" or o.value is not None, "pin_probe_failed")
        p["recorded_value"] = o.value if o.value is not None else pin_probe(p, o.gh)
        pins.append(p)
        return [p["id"]]
    require(o.expect_generation is not None, "expect_generation_required", 2)
    if o.operation == "decide":
        require(r["kind"] == "decision" and o.fields_file, "decision_fields_required", 2)
        k = loads(stdin_bytes(65536) if o.fields_file == "-" else read_file(o.fields_file, 65536), "invalid_field:decision")
        require(isinstance(k, dict) and set(k) == {"decision", "because", "options", "invalidators", "card_id"}, "invalid_field:decision")
        proposed = copy.deepcopy(r)
        proposed["kind_fields"] = k
        decision_validate(proposed)
        if r["state"] == "concluded":
            require(k["decision"]["text"] == r["kind_fields"]["decision"]["text"] and k["because"] == r["kind_fields"]["because"], "claim_text_immutable")
        for option in k.get("options", []):
            require("history" not in option, "invalid_field:option.history")
            old = next((x for x in r["kind_fields"].get("options", []) if x["id"] == option.get("id")), None)
            if old:
                if option.get("status") == "chosen" and old["status"] != "chosen":
                    decision_option_guard(r, "options." + old["id"] + ".status", o, o.by)
                if "history" in old:
                    option["history"] = copy.deepcopy(old["history"])
        r["kind_fields"] = k
        decision_validate(r)
        known = {p["id"] for p in r.get("pins", [])}
        require(all(c["pin"] in known for option in k["options"] for c in option.get("revisit_when", [])) and all(inv["pin"] in known for inv in k["invalidators"] if "pin" in inv), "unknown_pin")
    else:
        require(o.status in ("accepted", "withdrawn") and o.reason, "claim_status_fields_required", 2)
        c = next((c for c in r["claims"] if c["id"] == o.claim), None)
        require(c is not None, "invalid_field:claim")
        c["status"] = o.status
        c["status_history"].append(dict(status=o.status, at=now(), by=o.by, reason=o.reason))
    return []


def decision_set_guard(r, path, value, by):
    parts = path.split(".")
    if parts[0] == "claims" and len(parts) == 3:
        c = next((c for c in r["claims"] if c["id"] == parts[1]), {})
        require(parts[2] not in ("status", "status_history", "original", "contradicts", "supersedes"), "claim_text_immutable")
        require(parts[2] not in ("text", "basis") or "original" not in c, "claim_text_immutable")
    if r["kind"] == "decision" and (path == "kind_fields" or path.startswith("kind_fields.")):
        require(path not in ("kind_fields", "kind_fields.options"), "revisit_not_due")
        if r["state"] == "concluded":
            if path == "kind_fields":
                require(value.get("decision", {}).get("text") == r["kind_fields"]["decision"]["text"] and value.get("because") == r["kind_fields"]["because"], "claim_text_immutable")
            elif path == "kind_fields.because":
                require(value == r["kind_fields"]["because"], "claim_text_immutable")
            elif path == "kind_fields.decision":
                require(isinstance(value, dict) and value.get("text") == r["kind_fields"]["decision"]["text"], "claim_text_immutable")
        require(path not in ("kind_fields", "kind_fields.options"), "revisit_not_due")


def decision_option_guard(r, path, o, actor):
    oid = path.split(".")[-2]
    option = next((x for x in r["kind_fields"].get("options", []) if x["id"] == oid), None)
    require(option is not None, "invalid_field:option")
    if option["status"] == "chosen":
        return
    due = oid in r.get("revalidation", {}).get("revisit_due", [])
    require(due or o.override_reason is not None, "revisit_not_due")
    require(o.by is not None, "by_required", 2)
    option.setdefault("history", []).append(dict(status="chosen", at=now(), by=actor, reason=o.override_reason or "revisit condition holds"))


def revalidation(r, folder, o):
    pins = copy.deepcopy(r.get("pins", []))
    for p in pins:
        p.update(last_checked=now(), last_value=None)
        if p["basis"] == "supplied" or p["type"] == "supplied" or p["type"] == "gh_issue_state" and not o.network:
            p["last_result"] = "not_rechecked"
        else:
            try:
                p["last_value"] = pin_probe(p, o.gh)
                p["last_result"] = "unchanged" if p["last_value"] == p["recorded_value"] else "changed"
            except Refusal:
                p["last_result"] = "unavailable"
    results = {p["id"]: p["last_result"] for p in pins}
    evidence = [availability(e, folder) for e in r["evidence"]]
    for e in evidence:
        a = e["availability_now"]
        results[e["id"]] = "changed" if a in ("missing", "deleted", "digest_differs", "digest_mismatch") else "unavailable" if a in ("unavailable", "hazard_refused", "unreachable") else "unchanged"
    claims = {}
    not_rechecked = []
    for c in r["claims"]:
        deps = [results.get(x, "unavailable") for x in c.get("depends_on", [])]
        claims[c["id"]] = "stale" if "changed" in deps else "unverifiable" if "unavailable" in deps else c["status"]
        if "not_rechecked" in deps:
            not_rechecked.append(c["id"])
    byid = {p["id"]: p for p in pins}
    def holds(cond):
        p = byid.get(cond.get("pin"), {})
        return p.get("last_result") in ("changed", "unchanged") and (p.get("last_value") == cond["becomes"] if "becomes" in cond else p.get("last_result") == "changed")
    k = r["kind_fields"] if r["kind"] == "decision" else {}
    reasons = [cid + " " + claims[cid] for cid in k.get("because", []) if claims[cid] in ("stale", "unverifiable", "withdrawn")]
    manual = []
    for inv in k.get("invalidators", []):
        if "pin" not in inv:
            manual.append(inv["id"])
        else:
            condition = inv["condition"]
            if holds(dict(pin=inv["pin"], **({"changes": True} if condition == "changes" else condition))):
                reasons.append(inv["id"] + " invalidated")
    due = [x["id"] for x in k.get("options", []) if x["status"] == "rejected" and x.get("revisit_when") and all(holds(c) for c in x["revisit_when"])]
    return dict(checked_at=now(), pins=pins, evidence=evidence, claims=claims, not_rechecked=not_rechecked, needs_review=bool(reasons), reasons=reasons, revisit_due=due, manual_invalidators=manual)


def revalidate_records(store, o):
    require(bool(o.id) != bool(o.all) and (not o.all or o.kind == "decision"), "id_or_all_kind_required", 2)
    require(not o.network or o.gh is not None, "gh_required", 2)
    ids = [o.id] if o.id else sorted(os.listdir(store.records))
    values = []
    for rid in ids:
        r = store.read(rid)
        if o.all and r["kind"] != "decision":
            continue
        result = revalidation(r, store.path / "records" / rid, o)
        if o.write:
            r["pins"] = result["pins"]
            r["revalidation"] = {k: v for k, v in result.items() if k not in ("pins", "evidence")}
            for c in r["claims"]:
                if result["claims"][c["id"]] == "stale" and c["status"] != "stale":
                    c["status"] = "stale"
                    c["status_history"].append(dict(status="stale", at=now(), by="revalidate", reason="dependency changed"))
            r["generation"] += 1
            r["updated_at"] = now()
            validate(r)
            store.save(r, {})
        values.append(dict(id=rid, generation=r["generation"], **result))
    return 0, dict(schema_version=1, kind="records_revalidate", writes_performed=len(values) if o.write else 0, results=values)


def decision_view(r):
    k = r["kind_fields"]
    v = r.get("revalidation", {})
    pairs = sorted({tuple(sorted((c["id"], x))) for c in r["claims"] for x in c.get("contradicts", [])})
    return dict(decision=k.get("decision"), needs_review=v.get("needs_review", False), review_reasons=v.get("reasons", []), pins=r.get("pins", []),
                open_contradictions=[a + " ⟷ " + b for a, b in pairs if all(c["status"] != "withdrawn" for c in r["claims"] if c["id"] in (a, b))],
                claim_caveat="decided on provisional claims" if r["state"] == "concluded" and k.get("because") and all(c["status"] == "provisional" for c in r["claims"] if c["id"] in k["because"]) else None,
                revisit_due=v.get("revisit_due", []), options=sorted(k.get("options", []), key=lambda x: x["status"] != "chosen"))


def execute(o):
    op = o.operation
    if op == "forget-scratchpad":
        require(o.archived_scratchpad and o.expect_sha256 and o.reason, "archive_digest_reason_required", 2)
        path = Path(absolute(o.archived_scratchpad))
        require(path.parent.parent.name == "archive" and re.fullmatch(r"session:[0-9a-f-]{36}", path.parent.name) and
                re.fullmatch(r"block:[0-9a-f-]{36}(?:-[0-9]+)?\.md", path.name), "archived_scratchpad_required")
        handles = []
        try:
            for parent in (path.parent.parent, path.parent):
                fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                handles.append(fd)
                private(fd, True)
            raw = read_file(path, store=True)
            require(hashlib.sha256(raw).hexdigest() == o.expect_sha256.removeprefix("sha256:"), "scratchpad_digest_mismatch")
            erase_file(path)
            os.fsync(handles[-1])
        finally:
            for fd in handles:
                os.close(fd)
        return 0, dict(schema_version=1, kind="records_result", operation=op, outcome="forgotten", erasure="logical_overwrite_fsync_unlink", physical_erasure="not_guaranteed")
    require(op not in ("add", "attach", "close") or o.by is not None, "by_required", 2)
    writes = op in ("pin", "decide", "claim-status") or op == "revalidate" and o.write or op in ("init", "new", "park", "add", "attach", "set", "close", "forget")
    if o.check_command:
        require(o.assertion is not None and o.establishes is not None and o.does_not_establish is not None, "check_assertion_and_scope_required", 2)
    if o.fields_file == "-" and any(flag == "--evidence" and vals[0] == "-" for flag, vals in (o.inputs or [])):
        raise Refusal("stdin_consumed_twice", 2)
    with contextlib.closing(Store(o.store, writes, op == "init")) as store:
        if op == "init":
            return 0, dict(schema_version=1, kind="records_result", operation=op, outcome="initialized", generation=0)
        if op == "revalidate":
            return revalidate_records(store, o)
        if op in ("list", "lint") and (op == "list" or o.all):
            rs = [store.read(rid) for rid in sorted(os.listdir(store.records))]
            if op == "lint":
                violations = [dict(id=r["id"], **v) for r in rs for v in lint(r, store.path / "records" / r["id"])]
                return (3 if violations else 0), dict(schema_version=1, kind="records_lint", violations=violations)
            rs = [r for r in rs if (o.state == "all" or r["state"] == o.state) and (o.kind is None or r["kind"] == o.kind)]
            if o.needs_review:
                rs = [r for r in rs if r.get("revalidation", {}).get("needs_review", False)]
            rs.sort(key=lambda r: (r["state"] in ("open", "parked"), r["updated_at"], r["id"]), reverse=True)
            values = [dict(id=r["id"], kind=r["kind"], state=r["state"], written_at=r["written_at"], updated_at=r["updated_at"], writer=r["writer"],
                           question=r["question"], next_action={"step": (r["next_action"] or {}).get("step")}, target=r["target"], evidence_count=len(r["evidence"]), generation=r["generation"]) for r in rs]
            return 0, values
        creating = op in ("new", "park")
        assigned, packets = [], {}
        if creating:
            require(o.writer is not None and (op == "park" or o.kind is not None), "writer_and_kind_required", 2)
            rid = o.id or ("park" if op == "park" else o.kind) + "-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dt%H%M%Sz").lower() + "-" + secrets.token_hex(4)
            require(SLUG.fullmatch(rid), "invalid_field:id", 2)
            require(not (store.path / "records" / rid).exists(), "record_exists")
            r = dict(schema=SCHEMA, kind="investigation" if op == "park" else o.kind, id=rid, generation=0,
                     state="parked" if op == "park" else "open", written_at=now(), updated_at=now(), writer=o.writer, supersedes=o.supersedes,
                     question=None, hypothesis=None, discriminating_experiment=None, next_action=None, claims=[], checks=[], omissions=[], uncertainty=None, notes=None,
                     subject=None, target=None, target_at_park=None, evidence=[], cleanup=dict(status="unknown", items=[]), kind_fields={}, history=[], private=list(DEFAULT_PRIVATE))
            values = content(o)
            if o.git_repo:
                require("subject" not in values, "field_flag_file_conflict", 2)
                r["subject"] = git_subject(o.git_repo)
            if o.subject_artifact:
                r["subject"] = r["subject"] or dict(repo=None, commit=None, dirty="unknown", untracked=[], untracked_truncated=False, artifact=None, digest=None, basis="observed")
                r["subject"].update(artifact=absolute(o.subject_artifact), digest=file_hash(o.subject_artifact)[0])
        else:
            require(o.id is not None, "id_required", 2)
            r = store.read(o.id)
            values = {}
        folder = store.path / "records" / r["id"]
        if o.expect_generation is not None:
            require(r["generation"] == o.expect_generation, "generation_mismatch")
        if op in ("show", "resume", "navigate"):
            value = render(r, folder, o.evidence_check == "yes")
            if op == "show":
                return 0, value
            status = target_status(r["target"], r["target_at_park"], o.host, o.timeout_ms / 1000, o.target_check == "yes")
            value["kind"] = "records_resume"
            value.update(target=dict(recorded=r["target"], at_park=r["target_at_park"], now=status),
                         navigate=dict(possible=status["status"] == "available", argv=[os.environ.get("TEEREX_RECORDS_EXECUTABLE", "teerex"), "records", "navigate", "--store", o.store, "--id", r["id"], "--host", (r["target"] or {}).get("host", ""), "--focus", "yes"] if status["status"] == "available" else None),
                         is_fresh_snapshot=False, authority_granted="none", draft_restored=False, harness_resumed=False, writes_performed=0)
            if op == "resume":
                return 0, value
            require(o.focus == "yes", "navigate_requires_focus_yes", 2)
            if status["status"] != "available":
                return 3, dict(schema_version=1, kind="records_navigate", outcome="refused_target", target=status, writes_performed=0)
            t = r["target"]
            code, focus = invoke(["surfaces", "focus", "--socket", t["server"][7:], "--session", t["session_id"], "--pane", t["block_id"], "--timeout-ms", str(o.timeout_ms)], o.timeout_ms / 1000 + 1)
            return code, dict(schema_version=1, kind="records_navigate", outcome=focus.get("outcome"), focus=focus, writes_performed=0)
        if op in ("lint", "export"):
            violations = lint(r, folder)
            if violations:
                return 3, dict(schema_version=1, kind="records_lint", violations=violations)
            if op == "lint":
                return 0, dict(schema_version=1, kind="records_lint", violations=[])
            for field in o.include or []:
                if any(e["private"] for e in r["evidence"]):
                    require(not (field == "evidence" or field.startswith("evidence") and any(part in field for part in ("locator", "digest", "copy", "moved_from", "supplied_by", "target", "storage_dir", "seat"))), "private_field_export_refused:" + field)
                require(not any(field == p or field.startswith(p + ".") or p.startswith(field + ".") for p in r["private"]), "private_field_export_refused:" + field)
            value = export_record(r)
            if o.out:
                absolute(o.out)
                raw = ("Exported " + now() + " from " + SCHEMA + "; private fields omitted: " + ", ".join(r["private"]) + "\n" + as_text(value)).encode() if o.format == "md" else encoded(value)
                try:
                    fd = os.open(o.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                except FileExistsError:
                    raise Refusal("output_exists")
                with os.fdopen(fd, "wb") as f:
                    f.write(raw)
                    f.flush()
                    os.fsync(f.fileno())
                return 0, dict(schema_version=1, kind="records_result", operation=op, outcome="exported", bytes=len(raw), digest=sha(raw))
            return 0, value
        require(creating or r["state"] in ("open", "parked") or op in ("forget", "pin", "decide", "claim-status") or r["kind"] == "decision" and op in ("add", "attach", "set"), "record_closed")
        if op == "forget":
            require(o.expect_generation is not None and o.reason, "generation_and_reason_required", 2)
            text(o.reason, "reason")
            names = os.listdir(folder)
            require(set(names) == {"record.json", "evidence"}, "store_hazard")
            for p in (folder / "evidence").iterdir():
                require(re.fullmatch(r"e[0-9]+\.json", p.name), "store_hazard")
                read_file(p, store=True)
            for p in (folder / "evidence").iterdir():
                erase_file(p)
            (folder / "evidence").rmdir()
            erase_file(folder / "record.json")
            folder.rmdir()
            os.fsync(store.records)
            return 0, dict(schema_version=1, kind="records_result", operation=op, outcome="forgotten", id=r["id"], generation=r["generation"], erasure="logical_overwrite_fsync_unlink", physical_erasure="not_guaranteed")
        actor = o.by or o.writer or "operator"
        if op in ("pin", "decide", "claim-status"):
            assigned.extend(decision_mutate(r, o))
        elif op in ("new", "park"):
            assigned.extend(attach_inputs(r, o, packets))
            assigned.extend(apply_content(r, values, actor, True))
            if op == "park":
                require(o.host and o.socket and o.session and o.block, "explicit_target_required", 2)
                for prefix, v in (("session", o.session), ("block", o.block)):
                    require(re.fullmatch(prefix + r":[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", v), "invalid_field:target", 2)
                r["target"] = dict(host=o.host, server="unix://" + absolute(o.socket), session_id=o.session, block_id=o.block)
                r["target_at_park"] = target_status(r["target"], None, o.host, o.timeout_ms / 1000, o.target_check == "yes")
                require(r["target_at_park"]["status"] == "available" or o.allow_unavailable_target == "yes", "target_not_available:" + r["target_at_park"]["status"])
                if o.observe == "yes":
                    code, packet = invoke(["observe", "--socket", o.socket, "--session", o.session, "--block", o.block, "--max-bytes", str(o.observe_max_bytes)], o.timeout_ms / 1000 + 1)
                    require(code == 0, "target_observation_unavailable")
                    typ, info = packet_info(packet)
                    eid = "e" + str(len(r["evidence"]) + 1)
                    raw = encoded(packet)
                    e = dict(id=eid, type=typ, label="park observation", locator="-", digest=sha(raw), bytes=len(raw), recorded_at=now(), attached_by=actor,
                             availability_at_attach="present", moved_from=[], copy="evidence/" + eid + ".json", supplied_by=None, private=True, teerex=info)
                    require(len(r["evidence"]) < 256 and sum(x["copy"] is not None for x in r["evidence"]) < 64 and len(raw) <= LIMIT, "evidence_limit")
                    r["evidence"].append(e)
                    packets[eid + ".json"] = raw
                    assigned.append(eid)
        elif op == "attach":
            require(o.inputs or o.fields_file, "attachment_required", 2)
            assigned.extend(attach_inputs(r, o, packets))
            assigned.extend(apply_content(r, content(o, {"claims", "omissions", "uncertainty", "cleanup", "next_action"}), actor))
        elif op == "add":
            require(len(o.entries) == 1 and o.entries[0] in ("claim", "check", "omission", "cleanup"), "add_element_required", 2)
            field = {"claim": "claims", "check": "checks", "omission": "omissions", "cleanup": "items"}[o.entries[0]]
            if o.fields_file:
                values = content(o, {"claims", "checks", "omissions", "cleanup"})
                for f, vals in values.items():
                    assigned.extend(append_elements(r, "items" if f == "cleanup" else f, vals["items"] if f == "cleanup" else vals))
            else:
                keys = {"claims": ("text", "basis", "supplied_by", "scope"), "checks": ("command", "ran", "process_exit", "assertion", "establishes", "does_not_establish"),
                        "omissions": ("what", "reason"), "items": ("what", "where", "owner")}[field]
                required = {"claims": ("text", "basis"), "checks": keys, "omissions": keys, "items": keys}[field]
                require(all(getattr(o, k) is not None for k in required), "add_fields_required", 2)
                value = {k: getattr(o, k) for k in keys if getattr(o, k) is not None}
                if field in ("claims", "checks"):
                    value["evidence"] = (o.evidence_ids or "").split(",") if o.evidence_ids else []
                if field == "claims":
                    value.update(depends_on=o.depends_on.split(",") if o.depends_on else [], contradicts=o.contradicts.split(",") if o.contradicts else [], supersedes=o.supersedes)
                assigned.extend(append_elements(r, field, [value]))
        elif op == "set":
            require(o.expect_generation is not None, "expect_generation_required", 2)
            require(o.entries or o.fields_file, "set_fields_required", 2)
            values = content(o, {"question", "next_action", "hypothesis", "discriminating_experiment", "uncertainty", "cleanup.status", "kind_fields", "private", "notes"})
            assignments = {}
            for item in o.entries:
                require("=" in item, "set_requires_FIELD_JSON", 2)
                path, raw = item.split("=", 1)
                require(path not in assignments and path not in values, "field_flag_file_conflict", 2)
                assignments[path] = loads(raw, "invalid_field:" + path)
            for path, value in assignments.items():
                if path.startswith(("kind_fields.options.", "options.")) and value == "chosen":
                    decision_option_guard(r, path, o, actor)
                set_field(r, path, value, actor)
            for path, value in values.items():
                if path == "notes":
                    r[path] = value
                elif path == "cleanup.status":
                    r["cleanup"]["status"] = value
                else:
                    decision_set_guard(r, path, value, actor)
                    replace(r, path, value, actor)
        elif op == "close":
            require(o.state in ("concluded", "abandoned"), "close_state_required", 2)
            values = content(o, {"claims", "uncertainty", "cleanup", "next_action", "kind_fields"})
            if "kind_fields" in values:
                require(o.expect_generation is not None, "expect_generation_required", 2)
                decision_set_guard(r, "kind_fields", values["kind_fields"], actor)
            assigned.extend(apply_content(r, values, actor))
            r["state"] = o.state
        decision_link(r, actor)
        validate(r)
        if op == "new":
            missing = missing_kind_fields(r)
            if missing:
                raise Refusal("kind_fields_required", missing_fields=missing)
        if op in ("park", "close"):
            violations = lint(r, folder, packets)
            if op == "park" and r["question"] is None:
                violations.append(dict(rule="L1-next-action", path="question", message="park question required"))
            if violations:
                return 3, dict(schema_version=1, kind="records_lint", violations=violations)
        old = None
        if creating and o.supersedes:
            old = store.read(o.supersedes)
            require(old["state"] in ("open", "parked") or old["kind"] == "decision", "record_closed")
            old["state"] = "superseded_by:" + r["id"]
            old["generation"] += 1
            old["updated_at"] = now()
            require(len(encoded(old)) <= LIMIT, "record_oversize")
        r["generation"] += 1
        r["updated_at"] = now()
        dg = store.save(r, packets, creating)
        if old:
            store.save(old, {})
        receipt = dict(schema_version=1, kind="records_result", operation=op, outcome="written", id=r["id"], generation=r["generation"], assigned=assigned,
                       bytes=len(encoded(r)), record_digest=dg, warnings=[])
        if op == "park":
            receipt.update(target_status=r["target_at_park"]["status"], evidence_ids=[e["id"] for e in r["evidence"]])
        return 0, receipt


class EvidenceAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        inputs = list(getattr(namespace, "inputs", None) or [])
        if option_string == "--evidence" and namespace.operation == "add":
            namespace.evidence_ids = values if isinstance(values, str) else values[0]
            return
        inputs.append((option_string, values if isinstance(values, list) else [values]))
        namespace.inputs = inputs


class ExportableAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        inputs = getattr(namespace, "inputs", None) or []
        require(inputs, "exportable_requires_preceding_evidence", 2)
        namespace.exportable = list(getattr(namespace, "exportable", None) or []) + [len(inputs) - 1]


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse messages can embed rejected private argument values.
        self.exit(2, "records: invalid_arguments\n")


def parser():
    p = SafeParser(prog='teerex records', description=__doc__, epilog="new requires handoff direction/from/to/undo or receipt shipped_identity repo/commit. Writes redact recognized credentials in prose and refuse credential-bearing identities or evidence. Forget overwrites/fsyncs/unlinks; physical erasure is not guaranteed. Repair older records with set kind_fields=JSON or close --fields-file and --expect-generation; decisions use decide.")
    sub = p.add_subparsers(dest="operation", required=True)
    for op in ("init", "new", "park", "add", "attach", "set", "close", "show", "resume", "navigate", "list", "lint", "export", "forget", "forget-scratchpad", "pin", "decide", "claim-status", "revalidate"):
        q = sub.add_parser(op, help={"resume": "read reasoning, historical evidence and live target; zero writes", "navigate": "one explicit verified focus; never relaunch", "park": "write private reasoning for an explicit Rex target"}.get(op, op + " private records"))
        q.add_argument("--archived-scratchpad", help="forget-scratchpad only: exact private archived scratchpad path")
        q.add_argument("--expect-sha256", help="forget-scratchpad only: SHA256 of reviewed file")
        q.add_argument("--store", default=str(Path.home() / ".local/state/teerex-records"))
        for key in ("id", "writer", "by", "supersedes", "fields-file", "question", "next-actor", "next-step", "next-stop-when", "hypothesis", "discriminating-experiment", "uncertainty", "git-repo", "subject-artifact",
                    "host", "socket", "session", "block", "card-id", "seat-host", "seat-socket", "seat-session", "seat-block", "supplied-by", "check-command", "command", "text", "scope", "what", "reason", "where", "owner", "out", "type", "target", "value", "gh", "depends-on", "contradicts", "claim", "status", "override-reason"):
            q.add_argument("--" + key)
        q.add_argument("--kind", choices=KINDS)
        q.add_argument("--state", choices=("open", "parked", "all", "concluded", "abandoned"), default="all" if op == "list" else None)
        q.add_argument("--basis", choices=BASES)
        q.add_argument("--hypothesis-basis", choices=("inferred", "chosen"))
        q.add_argument("--confidence", choices=("low", "medium", "high"))
        q.add_argument("--ran", choices=("yes", "no", "unknown"))
        q.add_argument("--assertion", choices=("passed", "failed", "not_evaluated", "unknown"))
        q.add_argument("--process-exit")
        q.add_argument("--establishes")
        q.add_argument("--does-not-establish")
        q.add_argument("--expect-generation", type=int)
        q.add_argument("--format", choices=("json", "text", "md"), default="json")
        q.add_argument("--target-check", choices=("yes", "no"), default="yes")
        q.add_argument("--evidence-check", choices=("yes", "no"), default="yes")
        q.add_argument("--observe", choices=("yes", "no"), default="no")
        q.add_argument("--allow-unavailable-target", choices=("yes", "no"), default="no")
        q.add_argument("--focus", choices=("yes",), required=op == "navigate")
        q.add_argument("--observe-max-bytes", type=int, default=4096)
        q.add_argument("--timeout-ms", type=int, default=5000)
        for flag, nargs in (("--evidence", None), ("--evidence-dir", None), ("--card", None), ("--commit", 2), ("--ref", 2)):
            q.add_argument(flag, nargs=nargs, action=EvidenceAction)
        q.add_argument("--label", dest="labels", action="append")
        q.add_argument("--exportable", action=ExportableAction, nargs=0)
        q.add_argument("--include", action="append")
        for flag in ("all", "network", "write", "needs-review"):
            q.add_argument("--" + flag, action="store_true")
        q.add_argument("entries", nargs="*")
        q.set_defaults(operation=op, inputs=None, evidence_ids=None, exportable=None)
    return p


class Cancelled(Exception):
    def __init__(self, number):
        self.number = number


def cancelled(number, frame):
    raise Cancelled(number)


def main():
    os.umask(0o077)
    signal.signal(signal.SIGINT, cancelled)
    signal.signal(signal.SIGTERM, cancelled)
    p = parser()
    try:
        o = p.parse_args()
        require(100 <= o.timeout_ms <= 60000 and 256 <= o.observe_max_bytes <= 65536, "invalid_bounds", 2)
        if o.operation not in ("set", "add", "pin"):
            require(not o.entries, "unexpected_arguments", 2)
        code, value = execute(o)
        if o.format in ("text", "md") and isinstance(value, (list, dict)) and o.operation in ("show", "resume", "list", "export") and code == 0 and not o.out:
            prefix = "Exported " + now() + " from " + SCHEMA + "; private fields omitted: " + ", ".join(value.get("private_fields_omitted", [])) + "\n" if o.format == "md" else ""
            sys.stdout.write(prefix + as_text(value))
        else:
            sys.stdout.buffer.write(encoded(value))
        return code
    except Cancelled as e:
        return 128 + e.number
    except Refusal as e:
        if not re.fullmatch(r"[a-z0-9_.:\[\]-]{1,256}", e.reason):
            e.reason = e.reason.split(":", 1)[0] + ":invalid_field_name"
        if e.code in (2, 124):
            print("records: " + e.reason, file=sys.stderr)
        else:
            value = dict(schema_version=1, kind="records_result", outcome=e.details.get("outcome", "refused"), failure_reason=e.reason, **{k: v for k, v in e.details.items() if k != "outcome"})
            sys.stdout.buffer.write(encoded(value))
            print("records: " + e.reason, file=sys.stderr)
        return e.code
    except OSError:
        sys.stdout.buffer.write(encoded(dict(schema_version=1, kind="records_result", outcome="refused", failure_reason="store_hazard")))
        return 1
    except Exception as e:
        sys.stdout.buffer.write(encoded(dict(schema_version=1, kind="records_result", outcome="failed", failure_reason="internal_error", exception_class=type(e).__name__)))
        print("records: internal_error:" + type(e).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
