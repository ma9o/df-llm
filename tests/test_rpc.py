import socket
import threading
import unittest
from contextlib import contextmanager

from dfharness.rpc import HEADER, CommandError, Connection, DFHackError, fields, run_command


def receive(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise EOFError("Client disconnected")
        data.extend(chunk)
    return bytes(data)


@contextmanager
def server(handler):
    errors = []
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(3)
    port = listener.getsockname()[1]

    def worker():
        try:
            with listener.accept()[0] as conn:
                conn.settimeout(3)
                handler(conn)
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        thread.join(4)
        listener.close()
        if thread.is_alive():
            raise AssertionError("Fake DFHack server did not finish")
        if errors:
            raise errors[0]


def handshake(conn):
    assert receive(conn, 12) == b"DFHack?\n\x01\x00\x00\x00"
    conn.sendall(b"DFHack!\n\x01\x00\x00\x00")


def request(conn):
    kind, size = HEADER.unpack(receive(conn, 8))
    assert kind == 1
    return receive(conn, size)


class RpcTests(unittest.TestCase):
    def test_golden_request_fragmented_replies_unicode_and_quit(self):
        def handler(conn):
            self.assertEqual(receive(conn, 12), b"DFHack?\n\x01\x00\x00\x00")
            for byte in b"DFHack!\n\x01\x00\x00\x00":
                conn.sendall(bytes([byte]))
            self.assertEqual(request(conn), b"\x0a\x03lua\x12\x09print(42)")
            # CoreTextNotification { fragments: [{text: "é", color: 2}] }
            notification = b"\x0a\x06\x0a\x02\xc3\xa9\x10\x02"
            for byte in HEADER.pack(-3, len(notification)) + notification + HEADER.pack(-1, 0):
                conn.sendall(bytes([byte]))
            self.assertEqual(receive(conn, 8), b"\xfc\xff\x00\x00\x00\x00\x00\x00")

        with server(handler) as port:
            self.assertEqual(run_command("lua", "print(42)", port=port, timeout=2), "é")

    def test_failure_code_is_in_header_without_payload(self):
        def handler(conn):
            handshake(conn)
            request(conn)
            conn.sendall(HEADER.pack(-2, 3))
            receive(conn, 8)

        with server(handler) as port:
            with self.assertRaises(CommandError) as caught:
                run_command("missing-command", port=port, timeout=1)
            self.assertEqual(caught.exception.code, 3)

    def test_wrong_service_is_rejected_before_any_command(self):
        def handler(conn):
            receive(conn, 12)
            conn.sendall(b"HTTP/1.1 400")
            receive(conn, 8)

        with (
            server(handler) as port,
            self.assertRaisesRegex(DFHackError, "not a compatible"),
            Connection(port, timeout=1),
        ):
            self.fail("Handshake should fail")

    def test_oversized_reply_is_rejected_before_allocating_body(self):
        def handler(conn):
            handshake(conn)
            request(conn)
            conn.sendall(HEADER.pack(-3, 64 * 1024 * 1024 + 1))
            receive(conn, 8)

        with (
            server(handler) as port,
            self.assertRaisesRegex(DFHackError, "Invalid RPC response header"),
        ):
            run_command("help", port=port, timeout=1)

    def test_disconnect_in_middle_of_frame(self):
        def handler(conn):
            handshake(conn)
            request(conn)
            conn.sendall(HEADER.pack(-3, 10) + b"\x0a")

        with server(handler) as port, self.assertRaisesRegex(DFHackError, "mid-response"):
            run_command("help", port=port, timeout=1)

    def test_bad_protobuf_lengths_and_unknown_fields(self):
        with self.assertRaisesRegex(DFHackError, "Truncated protobuf field"):
            list(fields(b"\x0a\x05ab"))
        with self.assertRaisesRegex(DFHackError, "Truncated protobuf varint"):
            list(fields(b"\x80"))
        self.assertEqual(
            list(fields(b"\x10\x07\x1d\x01\x02\x03\x04")), [(2, 0, 7), (3, 5, b"\x01\x02\x03\x04")]
        )


if __name__ == "__main__":
    unittest.main()
