"""Rex API13 Unix-socket wire probe transport (Python standard library only).

Contract: the selected server's /llms.txt, control and data connections.
No default socket, reconnect, or retry is implicit.
"""
import base64
import hashlib
import json
import os
import socket
import struct


class WebSocket:
    def __init__(self, path, endpoint, protocol, timeout=5):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        try:
            self.sock.connect(str(path))
            key = base64.b64encode(os.urandom(16)).decode()
            self.sock.sendall((f"GET {endpoint} HTTP/1.1\r\nHost: localhost\r\n"
                               "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                               f"Sec-WebSocket-Protocol: {protocol}\r\n\r\n").encode())
            header = bytearray()
            while not header.endswith(b"\r\n\r\n"):
                header.extend(self.exact(1))
                if len(header) > 16384:
                    raise ValueError("oversized_websocket_header")
            lines = header.decode("ascii").split("\r\n")
            fields = dict(line.lower().split(": ", 1) for line in lines[1:] if ": " in line)
            accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode().lower()
            if " 101 " not in lines[0] or fields.get("sec-websocket-accept") != accept or fields.get("sec-websocket-protocol") != protocol:
                raise ValueError("websocket_upgrade_refused")
        except BaseException:
            self.sock.close()
            raise

    def exact(self, count):
        result = bytearray()
        while len(result) < count:
            part = self.sock.recv(count - len(result))
            if not part:
                raise EOFError("websocket_eof")
            result.extend(part)
        return bytes(result)

    def send(self, data, opcode=2):
        mask = os.urandom(4)
        size = len(data)
        header = bytes([0x80 | opcode])
        header += bytes([0x80 | size]) if size < 126 else (b"\xfe" + struct.pack("!H", size) if size < 65536 else b"\xff" + struct.pack("!Q", size))
        self.sock.sendall(header + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))

    def receive(self):
        opcode_expected = None
        result = bytearray()
        while True:
            first, second = self.exact(2)
            opcode = first & 15
            if first & 0x70 or second & 0x80:
                raise ValueError("unsupported_websocket_frame")
            length = second & 127
            if length == 126:
                length = struct.unpack("!H", self.exact(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self.exact(8))[0]
            if length > 1048576 or len(result) + length > 1048576:
                raise ValueError("oversized_websocket_message")
            data = self.exact(length)
            if opcode == 8:
                raise EOFError("websocket_closed:" + str(struct.unpack("!H", data[:2])[0] if len(data) >= 2 else None))
            if opcode == 9:
                self.send(data, 10)
                continue
            if opcode == 10:
                continue
            if opcode in (1, 2) and opcode_expected is None:
                opcode_expected = opcode
            elif opcode != 0 or opcode_expected is None:
                raise ValueError("invalid_websocket_fragment")
            result.extend(data)
            if first & 128:
                return bytes(result)

    def close(self):
        self.sock.close()


class Control:
    def __init__(self, path):
        self.ws = WebSocket(path, "/api/control", "rex.control.v1")
        self.serial = 0
        self.ws.send(json.dumps(dict(type="hello", api_revision=13, api_min_revision=13,
                                     client=dict(kind="cli", name="teerex-replay"))).encode(), 1)
        welcome = json.loads(self.ws.receive())
        if welcome.get("type") != "welcome" or welcome.get("protocol") != "rex.control.v1":
            self.ws.close()
            raise ValueError("control_welcome_invalid")

    def call(self, method, payload):
        self.serial += 1
        request_id = str(self.serial)
        self.ws.send(json.dumps(dict(type="request", id=request_id, method=method, payload=payload)).encode(), 1)
        while True:
            value = json.loads(self.ws.receive())
            if value.get("type") == "response" and value.get("id") == request_id:
                if value.get("error"):
                    raise ValueError("rex_error:" + value["error"]["code"])
                return value["payload"]

    def close(self):
        self.ws.close()


def data_connect(control, path, session, block):
    ticket = control.call("data.connect", dict(session_id=session, block_id=block,
                          data_ref_id="terminal", subprotocol="rex.data.terminal.v1"))["ticket"]
    ws = WebSocket(path, "/api/data", "rex.data.terminal.v1")
    try:
        ws.send(b"\x01" + base64.urlsafe_b64decode(ticket + "=="))
        welcome = ws.receive()
        if len(welcome) != 32 or welcome[0] != 0x81:
            raise ValueError("data_welcome_invalid:" + welcome.hex())
        nonce = struct.unpack("<Q", welcome[24:32])[0]
        if not nonce:
            raise ValueError("zero_channel_nonce")
        return ws, nonce
    except BaseException:
        ws.close()
        raise
