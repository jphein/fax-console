"""faxconsole.server — fixed-size worker pool + http.server adapter.

The HTTP handler is a thin wrapper around the pure ``handle()`` function
from faxconsole.routes.  A fixed-size ``ThreadPoolExecutor`` replaces the
per-request thread model of ``ThreadingHTTPServer`` (fixes analysis §9 F).

Design:
  - One ``ThreadPoolExecutor(max_workers=POOL_SIZE)`` is created once and
    shared for the lifetime of the server.
  - A ``threading.BoundedSemaphore`` limits waiting requests to
    ``POOL_SIZE + BACKLOG``.  A request that cannot acquire the semaphore
    immediately receives 503 with a JSON body and a ``Retry-After`` header.
  - Tests call ``handle()`` directly and never open a TCP port.  The adapter
    is exercised over ``socket.socketpair(AF_UNIX)`` (see test_faxconsole_adapter).
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import http.server
import json
import socket
import threading
from typing import Any

from faxconsole.routes import Config, Response, _mask_error, _write_authorized, handle

POOL_SIZE = 8   # fixed worker count
BACKLOG = 4     # extra waiting slots beyond the pool
_CAPACITY = POOL_SIZE + BACKLOG  # total inflight + queued requests allowed

_503_BODY = json.dumps({
    "ok": False,
    "detail": "server overloaded; retry shortly",
}).encode()


def _send_503(sock: Any) -> None:
    """Write a minimal HTTP/1.0 503 response directly to *sock*, then drain its input.

    Called in the accept thread, before a handler is constructed, so it writes raw
    bytes and must never block: the socket goes non-blocking first.

    The request bytes that have already arrived are read and dropped before the
    caller closes the socket. Closing with unread input makes the kernel reset the
    connection (a TCP RST; ECONNRESET on AF_UNIX), and the client then sees a reset
    instead of this 503. A body still in flight, such as a large upload, can still be
    reset: the 503 is best-effort, and the drain never waits for more input.
    """
    body = _503_BODY
    response = (
        b"HTTP/1.0 503 Service Unavailable\r\n"
        b"Content-Type: application/json\r\n"
        b"Retry-After: 5\r\n"
        b"Cache-Control: no-cache, no-store, must-revalidate\r\n"
        + b"Content-Length: " + str(len(body)).encode() + b"\r\n"
        b"\r\n"
        + body
    )
    with contextlib.suppress(OSError):   # BlockingIOError ends the drain: nothing more buffered
        sock.setblocking(False)
        sock.sendall(response)            # ~200 bytes into an empty send buffer
        sock.shutdown(socket.SHUT_WR)
        for _ in range(16):               # at most 1 MiB: a fast upload cannot hold this thread
            if not sock.recv(65536):
                break


class _Handler(http.server.BaseHTTPRequestHandler):
    """Adapter between http.server and the pure handle() function.

    The ``config`` attribute is set by FaxServer before the handler is used.
    """

    server_version = "faxconsole"
    config: Config  # set by FaxServer

    # Suppress the default request log; errors still go to stderr.
    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def _dispatch(self, method: str, body: bytes) -> None:
        headers = {k.lower(): v for k, v in self.headers.items()}
        try:
            resp = handle(method, self.path, headers, body, self.config)
        except Exception as exc:
            detail = _mask_error(self.config, str(exc))
            resp = Response(
                status=500,
                body=json.dumps({"ok": False, "detail": detail}).encode(),
            )
        self._send(resp)

    def _send(self, resp: Response) -> None:
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(resp.body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        if resp.extra_headers:
            for k, v in resp.extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(resp.body)

    def do_GET(self) -> None:
        self._dispatch("GET", b"")

    def _linger(self) -> None:
        """After an early 401 or 413, read and drop what the client already sent, then let it close.

        Closing with unread input makes the kernel reset the connection (a TCP RST; ECONNRESET on
        AF_UNIX), and a client that sent its body before reading, as a browser upload does, would see
        a reset instead of the answer. This is the review of run 13, the same class as run 7's 503.
        It is bounded: at most 1 MiB, at most 1 s, and it never holds a buffer beyond 64 KiB.
        """
        import time  # noqa: PLC0415
        sock = self.connection
        with contextlib.suppress(OSError):
            self.wfile.flush()
            sock.shutdown(socket.SHUT_WR)
            sock.settimeout(0.25)
            deadline, got = time.monotonic() + 1.0, 0
            while got < (1 << 20) and time.monotonic() < deadline:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                got += len(chunk)

    def do_POST(self) -> None:
        # FIRST, before any route matching or body read: check the write token
        # (legacy e:2953–2957: "FIRST, before any route matching or body read").
        # An unauthenticated client that declares a huge Content-Length must be
        # rejected before rfile.read(n) reserves n bytes.
        headers = {k.lower(): v for k, v in self.headers.items()}
        auth_err = _write_authorized(headers, self.config)
        if auth_err is not None:
            self.close_connection = True   # unread body desyncs a reused connection
            self._send(auth_err)
            self._linger()
            return

        # Size cap: reject before reading (legacy e:2960–2961).
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
        except (ValueError, TypeError):
            n = 0
        cap = self.config.max_bytes + 65536  # PDF cap + multipart allowance
        if n > cap:
            self.close_connection = True
            self._send(Response(
                status=413,
                body=json.dumps({"ok": False, "detail": "upload too large (15 MB max)"}).encode(),
                extra_headers={"X-Content-Type-Options": "nosniff"},
            ))
            self._linger()
            return

        # Read the body in bounded chunks: never more than the cap.
        to_read = min(n, cap) if n > 0 else 0
        body = self.rfile.read(to_read) if to_read > 0 else b""
        self._dispatch("POST", body)


class FaxServer:
    """Fixed-pool HTTP server wrapping a ``socketserver.TCPServer``.

    Usage::

        server = FaxServer(config, host="127.0.0.1", port=8093)
        server.serve_forever()
    """

    def __init__(
        self,
        config: Config,
        host: str = "127.0.0.1",
        port: int = 8093,
        pool_size: int = POOL_SIZE,
        backlog: int = BACKLOG,
        bind: bool = True,
    ) -> None:
        """``bind=False`` builds the server without binding its socket: tests drive
        ``process_request`` over AF_UNIX socketpairs, since no test may open a TCP port."""
        self.config = config
        capacity = pool_size + backlog
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=pool_size)
        # BoundedSemaphore(capacity): at most *capacity* requests are inflight
        # or queued at any moment.  A non-blocking acquire attempt on a full
        # semaphore returns False; that request gets an immediate 503.
        self._sem: threading.BoundedSemaphore = threading.BoundedSemaphore(capacity)

        # Build a custom HTTPServer subclass that injects config into the handler
        server_config = config

        class _ConfiguredHandler(_Handler):
            pass

        _ConfiguredHandler.config = server_config  # type: ignore[attr-defined]

        sem = self._sem

        class _PooledHTTPServer(http.server.HTTPServer):
            """Overrides process_request to use the shared pool + semaphore."""

            def process_request(self, request: Any, client_address: Any) -> None:
                if not sem.acquire(blocking=False):
                    # Capacity full: send 503 and close without queuing.
                    _send_503(request)
                    self.shutdown_request(request)
                    return
                try:
                    outer_pool.submit(self._run, request, client_address)
                except RuntimeError:
                    # Pool was shut down between the acquire and the submit.
                    sem.release()
                    self.shutdown_request(request)

            _HANDLER_TIMEOUT = 30  # seconds; a client that sends nothing gives up here

            def _run(self, request: Any, client_address: Any) -> None:
                try:
                    request.settimeout(self._HANDLER_TIMEOUT)
                    self.finish_request(request, client_address)
                except Exception:
                    self.handle_error(request, client_address)
                finally:
                    self.shutdown_request(request)
                    sem.release()

        outer_pool = self._pool
        self._httpd = _PooledHTTPServer((host, port), _ConfiguredHandler,
                                        bind_and_activate=bind)

    def serve_forever(self) -> None:
        try:
            self._httpd.serve_forever()
        finally:
            self._pool.shutdown(wait=False)

    def shutdown(self) -> None:
        self._httpd.shutdown()
        self._pool.shutdown(wait=False)

    def close(self) -> None:
        """Release the pool and the socket without a serve loop; shutdown() waits for one."""
        self._pool.shutdown(wait=True)
        self._httpd.server_close()

    @property
    def server_address(self) -> tuple[str, int]:
        return self._httpd.server_address  # type: ignore[return-value]
