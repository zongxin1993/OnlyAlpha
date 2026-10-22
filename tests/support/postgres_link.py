"""Controlled TCP COMMIT-ACK fault link to the canonical test DB."""

from __future__ import annotations

import socket
import struct
import subprocess
from threading import Event, Thread
from typing import Self

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo


class CommitAckCut:
    """One test-only TCP link to the canonical DB, cut after actual COMMIT.

    Pass authentication and all statements unchanged. Suppress the backend's
    COMMIT CommandComplete and ReadyForQuery, then close. This is fault injection
    into the real driver, not a second database or a Product API substitute.
    """

    def __init__(self, dsn: str) -> None:
        self.done = Event()
        self.errors: list[Exception] = []
        self.sockets: list[socket.socket] = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(1)
        self.listener.settimeout(20)
        parameters = conninfo_to_dict(dsn)
        host, port = parameters.get("host"), parameters.get("port", "5432")
        if not isinstance(host, str) or not isinstance(port, (str, int)):
            raise ValueError("canonical TCP test DB endpoint required")
        self.upstream = (host, int(port))
        self.dsn = make_conninfo(dsn, host="127.0.0.1", port=self.listener.getsockname()[1])

    @staticmethod
    def exact(stream: socket.socket, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            part = stream.recv(size - len(data))
            if not part:
                raise EOFError("test PG link closed")
            data.extend(part)
        return bytes(data)

    def backend(self, source: socket.socket, destination: socket.socket) -> None:
        suppress = False
        try:
            while True:
                tag = self.exact(source, 1)
                length = self.exact(source, 4)
                size = struct.unpack("!I", length)[0]
                if not 4 <= size <= 16 * 1024 * 1024:
                    raise ValueError("test PG frame outside bound")
                payload = self.exact(source, size - 4)
                if tag == b"C" and payload == b"COMMIT\x00":
                    suppress = True
                if not suppress:
                    destination.sendall(tag + length + payload)
                elif tag == b"Z":
                    if payload != b"I":
                        raise ValueError("server not idle after actual commit")
                    self.done.set()
                    return
        except Exception as error:
            self.errors.append(error)
        finally:
            destination.shutdown(socket.SHUT_RDWR)

    def serve(self) -> None:
        try:
            downstream, _address = self.listener.accept()
            upstream = socket.create_connection(self.upstream, timeout=20)
            self.sockets.extend([downstream, upstream])
            downstream.settimeout(20)
            upstream.settimeout(20)
            pump = Thread(target=self.backend, args=(upstream, downstream))
            pump.start()
            try:
                while chunk := downstream.recv(65536):
                    upstream.sendall(chunk)
            finally:
                upstream.shutdown(socket.SHUT_RDWR)
                pump.join(timeout=20)
                if pump.is_alive():
                    raise TimeoutError("test PG backend pump did not stop")
        except Exception as error:
            self.errors.append(error)

    def __enter__(self) -> Self:
        self.thread = Thread(target=self.serve)
        self.thread.start()
        return self

    def __exit__(self, *_exception: object) -> None:
        self.thread.join(timeout=20)
        for stream in self.sockets:
            stream.close()
        self.listener.close()
        assert not self.thread.is_alive(), "fault-injection link did not stop"
        assert self.errors == []


def wait_for_database_lock_barrier(
    dsn: str, child: subprocess.Popen[str], pid: int, blocker: int, lock_kind: str
) -> None:
    """Wait on an observed PG lock predicate, never infer arrival from elapsed time.

    The deadline is only a watchdog. Repeated read-only observation of the barrier
    neither retries the operation nor changes its result/ordering.
    """
    import time

    deadline = time.monotonic() + 20
    with psycopg.connect(dsn, autocommit=True) as observer:
        while True:
            row = observer.execute(
                "SELECT %s=ANY(pg_blocking_pids(%s)) AND EXISTS(SELECT 1 FROM pg_locks WHERE pid=%s AND locktype=%s AND NOT granted)",
                (blocker, pid, pid, lock_kind),
            ).fetchone()
            if row == (True,):
                return
            assert child.poll() is None, "target operation ended before reaching the held lock"
            assert time.monotonic() < deadline, "target never reached the database lock barrier"


def wait_no_advisory_locks(dsn: str, pid: int) -> None:
    # Observe the actual cleanup predicate. The deadline is only a watchdog;
    # no operation is retried and elapsed time never proves correctness.
    import time

    deadline = time.monotonic() + 20
    with psycopg.connect(dsn, autocommit=True) as observer:
        while True:
            result = observer.execute(
                "SELECT NOT EXISTS (SELECT 1 FROM pg_catalog.pg_locks WHERE pid=%s AND locktype='advisory')", (pid,)
            ).fetchone()
            if result == (True,):
                return
            assert time.monotonic() < deadline, "owned session left an advisory lock"
