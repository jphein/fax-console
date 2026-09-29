"""faxconsole.server — fixed-size worker pool + http.server adapter.

The HTTP handler is a thin wrapper around the pure ``handle()`` function
from faxconsole.routes.  A fixed-size ``ThreadPoolExecutor`` replaces the
per-request thread model of ``ThreadingHTTPServer`` (fixes analysis §9 F).

Design:
  - One ``ThreadPoolExecutor(max_workers=POOL_SIZE)`` is created once and
    shared for the lifetime of the server.
  - Each request is submitted as a task; if all workers are busy the task
    queues (the ``Future`` is not waited on in the server loop — the handler
    method blocks the reader thread just long enough to submit the work, then
    returns; responses are sent from the worker thread, which has its own
    wfile reference).
  - Tests call ``handle()`` directly and never open a TCP port.  The adapter
    is exercised over ``socket.socketpair(AF_UNIX)`` (see test_faxconsole_adapter).
"""
from __future__ import annotations

import concurrent.futures
import http.server
import json
from typing import Any

from faxconsole.routes import Config, Response, handle

POOL_SIZE = 8  # fixed worker count; queue is unbounded but each task is bounded


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
            resp = Response(
                status=500,
                body=json.dumps({"ok": False, "detail": str(exc)}).encode(),
            )
        self._send(resp)

    def _send(self, resp: Response) -> None:
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(resp.body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(resp.body)

    def do_GET(self) -> None:
        self._dispatch("GET", b"")

    def do_POST(self) -> None:
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
        except (ValueError, TypeError):
            n = 0
        body = self.rfile.read(n) if n > 0 else b""
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
    ) -> None:
        self.config = config
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=pool_size)

        # Build a custom HTTPServer subclass that injects config into the handler
        server_config = config

        class _ConfiguredHandler(_Handler):
            pass

        _ConfiguredHandler.config = server_config  # type: ignore[attr-defined]

        class _PooledHTTPServer(http.server.HTTPServer):
            """Overrides process_request to use the shared pool."""

            def process_request(self, request: Any, client_address: Any) -> None:
                pool = outer_pool
                pool.submit(self.process_request_thread, request, client_address)

            def process_request_thread(self, request: Any, client_address: Any) -> None:
                try:
                    self.finish_request(request, client_address)
                except Exception:
                    self.handle_error(request, client_address)
                finally:
                    self.shutdown_request(request)

        outer_pool = self._pool
        self._httpd = _PooledHTTPServer((host, port), _ConfiguredHandler)

    def serve_forever(self) -> None:
        try:
            self._httpd.serve_forever()
        finally:
            self._pool.shutdown(wait=False)

    def shutdown(self) -> None:
        self._httpd.shutdown()
        self._pool.shutdown(wait=False)

    @property
    def server_address(self) -> tuple[str, int]:
        return self._httpd.server_address  # type: ignore[return-value]
