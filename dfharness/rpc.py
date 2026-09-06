"""The small, stable RunCommand subset of DFHack's protobuf/TCP protocol.

Protocol: https://docs.dfhack.org/en/stable/docs/dev/Remote.html
Schema: DFHack/dfhack, library/proto/CoreProtocol.proto
No Wine subprocess, protobuf compiler, or third-party package is required.
"""

import socket
import struct
import time
from contextlib import suppress

HEADER = struct.Struct("<h2xi")  # The two padding bytes are part of the protocol.
HANDSHAKE = struct.Struct("<8si")
MAX_MESSAGE = 64 * 1024 * 1024


class DFHackError(RuntimeError):
    pass


class DispatchError(DFHackError):
    """A failed call with the dispatch identity needed to inspect/recover it."""

    def __init__(self, dispatch_id, cause):
        self.dispatch_id = dispatch_id
        self.resume_action = {"type": "resume", "dispatch_id": dispatch_id}
        super().__init__(
            f"{cause}\nDispatch ID: {dispatch_id}. No input was retried. "
            "Observe/status before continuing; resume this ID if its checkpoint exists, "
            "or interrupt it before choosing a different action."
        )


class CommandError(DFHackError):
    def __init__(self, code, output):
        self.code, self.output = code, output
        super().__init__(f"DFHack command failed ({code}): {output.strip()}")


def varint(value):
    if value < 0:
        raise ValueError("Expected a nonnegative varint")
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def read_varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise DFHackError("Truncated protobuf varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise DFHackError("Invalid protobuf varint")


def string_field(number, value):
    raw = value.encode("utf-8")
    return varint((number << 3) | 2) + varint(len(raw)) + raw


def fields(data):
    """Decode fields, including unknown fields, with strict length checks."""
    offset = 0
    while offset < len(data):
        tag, offset = read_varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if not number:
            raise DFHackError("Invalid protobuf field zero")
        if wire == 0:
            value, offset = read_varint(data, offset)
        else:
            if wire == 2:
                size, offset = read_varint(data, offset)
            elif wire in (1, 5):
                size = 8 if wire == 1 else 4
            else:
                raise DFHackError(f"Unsupported protobuf wire type {wire}")
            end = offset + size
            if end > len(data):
                raise DFHackError("Truncated protobuf field")
            value, offset = data[offset:end], end
        yield number, wire, value


def notification_text(payload):
    return "".join(
        text.decode("utf-8", errors="replace")
        for number, wire, fragment in fields(payload)
        if (number, wire) == (1, 2)
        for field, kind, text in fields(fragment)
        if (field, kind) == (1, 2)
    )


class Connection:
    def __init__(self, port=5000, timeout=10.0):
        if not 1 <= port <= 65535 or timeout <= 0:
            raise ValueError("Invalid port or timeout")
        self.port, self.timeout = port, timeout
        self.sock = None

    def _recv(self, size, deadline):
        sock = self.sock
        if sock is None:
            raise DFHackError("Connection is not open")
        chunks = bytearray()
        while len(chunks) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("DFHack response deadline exceeded")
            sock.settimeout(remaining)
            chunk = sock.recv(size - len(chunks))
            if not chunk:
                raise DFHackError("DFHack closed the connection mid-response")
            chunks.extend(chunk)
        return bytes(chunks)

    def __enter__(self):
        try:
            deadline = time.monotonic() + self.timeout
            self.sock = socket.create_connection(("127.0.0.1", self.port), self.timeout)
            self.sock.sendall(HANDSHAKE.pack(b"DFHack?\n", 1))
            reply = self._recv(HANDSHAKE.size, deadline)
            if reply != HANDSHAKE.pack(b"DFHack!\n", 1):
                raise DFHackError(f"Port {self.port} is not a compatible DFHack server")
            return self
        except (OSError, DFHackError) as exc:
            self.close()
            raise DFHackError(
                f"Cannot connect to DFHack on 127.0.0.1:{self.port}: {exc}. "
                "Run ./dfctl doctor. On macOS, AirPlay/Control Center often uses port 5000."
            ) from exc

    def close(self):
        if self.sock is not None:
            with suppress(OSError):
                self.sock.sendall(HEADER.pack(-4, 0))
            self.sock.close()
            self.sock = None

    def __exit__(self, *_):
        self.close()

    def run(self, command, *arguments):
        sock = self.sock
        if sock is None:
            raise DFHackError("Connection is not open")
        payload = string_field(1, command) + b"".join(string_field(2, a) for a in arguments)
        if len(payload) > MAX_MESSAGE:
            raise ValueError("Command exceeds DFHack's message limit")
        deadline = time.monotonic() + self.timeout
        output, total = [], 0
        try:
            sock.settimeout(self.timeout)
            sock.sendall(HEADER.pack(1, len(payload)) + payload)
            while True:
                kind, size = HEADER.unpack(self._recv(HEADER.size, deadline))
                if kind == -2:
                    # Failure puts the command_result in size; there is NO body.
                    raise CommandError(size, "".join(output))
                if kind not in (-1, -3) or not 0 <= size <= MAX_MESSAGE:
                    raise DFHackError(f"Invalid RPC response header: {kind}, {size}")
                total += size
                if total > MAX_MESSAGE:
                    raise DFHackError("DFHack output exceeds 64 MiB")
                body = self._recv(size, deadline)
                if kind == -1:
                    return "".join(output)
                output.append(notification_text(body))
        except OSError as exc:
            self.close()
            raise DFHackError(
                f"DFHack connection interrupted: {exc}. The command may have executed; "
                "observe before retrying an action."
            ) from exc


def run_command(command, *arguments, port=5000, timeout=10.0):
    with Connection(port, timeout) as conn:
        return conn.run(command, *arguments)
