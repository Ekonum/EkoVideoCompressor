"""Serveur du banc : sert la source en Range (Mediabunny lit en streaming)
et accepte les sorties en PUT, pour que le banc tourne sans intervention."""
import os, re, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SRC = sys.argv[1]
PAGE = sys.argv[2]
OUT = sys.argv[3]
SIZE = os.path.getsize(SRC)


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,PUT,HEAD,OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.send_header("Content-Length", "0"); self.end_headers()

    def do_HEAD(self):
        self.send_response(200); self._cors()
        self.send_header("Content-Length", str(SIZE))
        self.send_header("Content-Type", "video/quicktime")
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/bench"):
            body = open(PAGE, "rb").read()
            self.send_response(200); self._cors()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body); return

        start, end = 0, SIZE - 1
        rng = self.headers.get("Range")
        if rng and (m := re.match(r"bytes=(\d*)-(\d*)", rng)):
            if m.group(1):
                start = int(m.group(1))
                if m.group(2):
                    end = int(m.group(2))
            elif m.group(2):
                start = SIZE - int(m.group(2))
        end = min(end, SIZE - 1)
        length = end - start + 1

        self.send_response(206 if rng else 200); self._cors()
        self.send_header("Content-Type", "video/quicktime")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{SIZE}")
        self.end_headers()
        with open(SRC, "rb") as f:
            f.seek(start)
            while length > 0:
                chunk = f.read(min(1 << 20, length))
                if not chunk:
                    break
                self.wfile.write(chunk)
                length -= len(chunk)

    def do_PUT(self):
        name = os.path.basename(self.path)
        n = int(self.headers.get("Content-Length", 0))
        with open(os.path.join(OUT, name), "wb") as f:
            remaining = n
            while remaining > 0:
                chunk = self.rfile.read(min(1 << 20, remaining))
                if not chunk:
                    break
                f.write(chunk); remaining -= len(chunk)
        self.send_response(204); self._cors(); self.send_header("Content-Length", "0"); self.end_headers()

    def log_message(self, *a):
        pass


ThreadingHTTPServer(("127.0.0.1", 8748), H).serve_forever()
