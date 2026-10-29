"""Local HTTP server for timeout tests. None responses stall after accept."""
import socket
import threading


def read_http_request(conn):
    conn.settimeout(2)
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(65536)
        if not chunk:
            break
        data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    length = 0
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
    while len(body) < length:
        chunk = conn.recv(65536)
        if not chunk:
            break
        body += chunk
    return head, body


def send_http(conn, body, status=200, reason="OK", content_type="text/xml"):
    if isinstance(body, str):
        body = body.encode()
    reason = reason.encode() if isinstance(reason, str) else reason
    content_type = content_type.encode() if isinstance(content_type, str) else content_type
    payload = (
        f"HTTP/1.1 {status} ".encode()
        + reason
        + b"\r\nContent-Type: "
        + content_type
        + b"\r\n"
        + f"Content-Length: {len(body)}\r\n".encode()
        + b"Connection: close\r\n\r\n"
        + body
    )
    conn.sendall(payload)


class ScriptedServer:
    """Each item is bytes (HTTP 200), a (status, reason, body) tuple, or None to stall."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}/"

    def __enter__(self):
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=1)

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def _next(self):
        with self._lock:
            self.requests += 1
            if self.responses:
                return self.responses.pop(0)
            return None

    def _handle(self, conn):
        item = self._next()
        try:
            read_http_request(conn)
            if item is None:
                self._stop.wait(30)
                return
            if isinstance(item, tuple):
                status, reason, body = item
                send_http(conn, body, status=status, reason=reason)
            else:
                send_http(conn, item)
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass
