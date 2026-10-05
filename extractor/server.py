"""Phone capture server. Listens on 127.0.0.1 only; `tailscale serve` exposes it to your tailnet over HTTPS.

Photos are saved to data/captures (owner-only permissions) and processed in a
background thread; rows are appended to the output CSV (default data/results.csv).
"""
from __future__ import annotations

import io
import json
import os
import queue
import re
import threading
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from PIL import Image

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
MAX_UPLOAD = 40 * 1024 * 1024
ALLOWED_USERS = {u.strip() for u in os.environ.get("PRX_ALLOWED_USERS", "").split(",") if u.strip()}
SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                               "script-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; media-src 'self' blob:",
}


class CaptureStore:
    def __init__(self, data_dir: Path, csv_path: Path):
        self.captures = data_dir / "captures"
        self.captures.mkdir(parents=True, exist_ok=True)
        os.chmod(self.captures, 0o700)
        self.csv = csv_path
        self.jobs: queue.Queue[tuple[Path, str]] = queue.Queue()
        self.lock = threading.Lock()

    def next_number(self) -> int:
        nums = [int(m.group(1)) for p in self.captures.iterdir() if (m := re.match(r"(\d+)", p.name))]
        return max(nums, default=0) + 1

    def save(self, number: int, data: bytes) -> Path:
        """Write the photo without ever overwriting an earlier one (0012.jpg, 0012-2.jpg, ...)."""
        with self.lock:
            for suffix in [""] + [f"-{i}" for i in range(2, 1000)]:
                path = self.captures / f"{number:04d}{suffix}.jpg"
                try:
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    continue
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                return path
        raise RuntimeError("too many captures with the same number")

    def worker(self) -> None:
        from .loader import load_pages
        from .output import append_rows
        from .pipeline import failed_row, process_page

        while True:
            path, item = self.jobs.get()
            try:
                for page_no, img in load_pages(path):
                    row = process_page(img, path.name, page_no, item)
                    append_rows(self.csv, [row])
                    print(f"  [{'REVIEW' if row.needs_review == 'YES' else 'ok':6}] #{item}: "
                          f"{row.release_date or '-'} | {row.first_five_words or '-'}", flush=True)
            except Exception as exc:  # never lose track of a capture: record the failure as a row
                traceback.print_exc()
                append_rows(self.csv, [failed_row(path.name, item, f"processing failed: {exc}")])
            finally:
                self.jobs.task_done()


def make_handler(store: CaptureStore):
    class Handler(BaseHTTPRequestHandler):
        server_version = "capture"
        sys_version = ""

        def log_message(self, fmt, *args):  # keep logs free of request details
            pass

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in SECURITY_HEADERS.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, obj) -> None:
            self._send(status, json.dumps(obj).encode(), "application/json")

        def _allowed(self) -> bool:
            if ALLOWED_USERS and self.headers.get("Tailscale-User-Login") not in ALLOWED_USERS:
                self._json(HTTPStatus.FORBIDDEN, {"error": "not allowed"})
                return False
            return True

        def do_GET(self):
            if not self._allowed():
                return
            path = urlparse(self.path).path
            if path == "/":
                self._send(HTTPStatus.OK, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif path == "/api/next":
                self._json(HTTPStatus.OK, {"next": store.next_number(), "pending": store.jobs.qsize()})
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self):
            if not self._allowed():
                return
            url = urlparse(self.path)
            if url.path != "/api/capture":
                return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            # Custom header forces a CORS preflight, which we never approve: blocks cross-site uploads.
            if self.headers.get("X-Capture") != "1":
                return self._json(HTTPStatus.FORBIDDEN, {"error": "missing header"})
            n = parse_qs(url.query).get("n", [""])[0]
            if not re.fullmatch(r"\d{1,9}", n):
                return self._json(HTTPStatus.BAD_REQUEST, {"error": "number must be digits"})
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 < length <= MAX_UPLOAD:
                return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "bad size"})
            data = self.rfile.read(length)
            try:
                with Image.open(io.BytesIO(data)) as img:
                    img.verify()
                    if img.format != "JPEG":
                        raise ValueError
            except Exception:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": "not a JPEG image"})
            number = int(n)
            path = store.save(number, data)
            store.jobs.put((path, str(number)))
            self._json(HTTPStatus.OK, {"saved": path.name, "next": number + 1})

    return Handler


def serve(port: int, data_dir: Path, csv_path: Path) -> None:
    store = CaptureStore(data_dir, csv_path)
    threading.Thread(target=store.worker, daemon=True).start()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(store))
    print(f"Capture server on http://127.0.0.1:{port} (localhost only).")
    print(f"Expose it to your tailnet with:  tailscale serve --bg --https=8443 {port}")
    print(f"Photos -> {store.captures}   Results -> {store.csv}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
