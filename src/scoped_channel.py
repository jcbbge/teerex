"""Shared scoped-channel protocol and foreground service; embedded before each controller.

The caller owns directory lifecycle and dispatch. Peers supply no filesystem paths
or Rex targets; authentication and exact operation fields are checked before work.
"""
import contextlib
import json
import socket
import time
import subprocess
import secrets
import re


def channel_require(condition, reason):
    if not condition:
        raise ValueError(reason)


def frame_read(connection, budget=.5):
    raw = bytearray()
    end = time.monotonic() + budget
    # One bounded JSON line per connection. Newlines inside strings are JSON escaped.
    while b"\n" not in raw:
        remaining = end - time.monotonic()
        channel_require(remaining > 0, "channel_frame_deadline")
        connection.settimeout(remaining)
        part = connection.recv(min(4096, 49153 - len(raw)))
        channel_require(part, "incomplete_channel_frame")
        raw.extend(part)
        channel_require(len(raw) <= 49152, "channel_frame_too_large")
    channel_require(raw.endswith(b"\n") and raw.count(b"\n") == 1, "one_channel_frame_required")
    def unique(pairs):
        value = {}
        for key, item in pairs:
            channel_require(key not in value, "duplicate_channel_field")
            value[key] = item
        return value
    value = json.loads(raw, object_pairs_hook=unique)
    channel_require(isinstance(value, dict), "invalid_channel_frame")
    return value


def channel_failure(reason, outcome="refused_or_uncertain"):
    return dict(schema_version=1, kind="agent_channel_result", outcome=outcome,
                failure_reason=str(reason), retry_safe=False)


def channel_request(request, launch_id, token, grants):
    channel_require(set(request) <= {"launch_id", "token", "request_id", "operation", "to", "body", "session", "block", "event"}, "unknown_channel_field")
    channel_require(request.get("launch_id") == launch_id, "channel_launch_mismatch")
    supplied = request.get("token")
    channel_require(isinstance(supplied, str) and supplied.isascii() and secrets.compare_digest(supplied, token), "channel_token_mismatch")
    event_id, operation = request.get("request_id"), request.get("operation")
    channel_require(isinstance(event_id, str) and re.fullmatch(r"[0-9a-f]{32}", event_id), "invalid_launch_id")
    channel_require(isinstance(operation, str) and operation in grants, "channel_operation_not_granted")
    required = {"launch_id", "token", "request_id", "operation"}
    required |= {"send": {"to", "body"}, "ack": {"session", "block"}, "stop": {"event"}}[operation]
    channel_require(set(request) == required, "invalid_channel_operation_fields")
    if operation == "send":
        channel_require(request["to"] in ("starter", "report-to"), "fixed_channel_destination_required")
        body = request["body"]
        channel_require(isinstance(body, str) and 0 < len(body.encode()) <= 32768 and
                        all(ord(c) >= 32 and ord(c) != 127 or c in "\n\t" for c in body), "invalid_or_oversized_message")
    return event_id, operation


class ChannelService:
    reserve_refusal = False
    errors = (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError, subprocess.SubprocessError)

    def record_request(self, request, code, result):
        pass

    def service(self):
        if self.closed:
            time.sleep(.05)
            return
        if time.monotonic() >= self.deadline:
            self.close()
            self.revoked()
            return
        remaining = self.next_accept - time.monotonic()
        if remaining > 0:
            time.sleep(min(.05, remaining))
            return
        try:
            connection, unused = self.listener.accept()
        except socket.timeout:
            return
        except OSError:
            if self.closed:  # INT/TERM can revoke while accept is waiting.
                return
            raise
        self.count += 1
        self.next_accept = time.monotonic() + .05
        with connection:
            connection.settimeout(.5)
            request = {}
            try:
                request = frame_read(connection)
                # Recheck after the bounded read, not just at accept.
                channel_require(time.monotonic() < self.deadline, "channel_expired")
                code, result = self.dispatch(request)
            except self.errors as exc:
                code, result = 1, channel_failure(exc)
            self.record_request(request, code, result)
            response = json.dumps(dict(code=code, result=result), ensure_ascii=False).encode() + b"\n"
            if len(response) > 49152:
                response = json.dumps(dict(code=1, result=channel_failure("receipt_too_large_inspect_registry", "delivery_uncertain_no_retry"))).encode() + b"\n"
            with contextlib.suppress(OSError):
                connection.sendall(response)

