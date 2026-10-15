#!/usr/bin/env python3
"""ORGX server — stdlib only. Serves web/ and the JSON API over data/.

    python3 server.py                     # http://127.0.0.1:48750
    python3 server.py --host 0.0.0.0 --port 48750 --data /srv/orgx

Environment (Docker): ORGX_HOST, ORGX_PORT, ORGX_DATA, ORGX_INBOX_SECONDS (0 = off),
ORGX_UPLOAD (0 disables browser uploads), ORGX_DEMO (1 = load synthetic data when empty).

Inbox: drop a CSV into <data>/inbox/ (e.g. from a scheduled PowerShell export)
and it is ingested automatically, then moved to <data>/sources/.
"""
from __future__ import annotations

import argparse
import gzip
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections import OrderedDict
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from orgx import api

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
MAX_UPLOAD = 2 * 1024**3

# Answers that depend only on the directory, its notes and rules. They are kept until any of
# those change, so going back, reopening a unit or re-running a search is instant.
CACHEABLE = {"/api/search", "/api/facets", "/api/object", "/api/org", "/api/orgtree", "/api/orgs", "/api/locations",
             "/api/location", "/api/ask", "/api/topics", "/api/changes", "/api/quality", "/api/tags"}
# POSTs that only read (or change org.db, whose own timestamp then moves)
READ_POSTS = {"/api/resolve", "/api/ad/test", "/api/live/search", "/api/live/person", "/api/live/unit", "/api/live/site"}
# what the first screens ask for, worked out ahead of the first visit after each load
WARM = [("/api/locations", {}), ("/api/orgs", {"parent": ""}), ("/api/orgtree", {"depth": "1", "cap": "80"}),
        ("/api/orgtree", {"depth": "2", "cap": "30"}), ("/api/facets", {"q": ""}), ("/api/topics", {}),
        ("/api/search", {"q": "", "sort": "smart", "limit": "100"}), ("/api/quality", {})]


class Answers:
    def __init__(self, max_bytes: int = 128 * 1024**2, max_items: int = 600):
        self.items: "OrderedDict[tuple, bytes]" = OrderedDict()
        self.bytes = 0
        self.max_bytes, self.max_items = max_bytes, max_items
        self.version = None
        self.lock = threading.Lock()

    def key(self, path: str, p: dict) -> tuple:
        return (path, tuple(sorted((k, v) for k, v in p.items() if not k.startswith("_"))))

    def get(self, version, key):
        with self.lock:
            if version != self.version:
                self.items.clear()
                self.bytes = 0
                self.version = version
                return None
            body = self.items.get(key)
            if body is not None:
                self.items.move_to_end(key)
            return body

    def put(self, version, key, body: bytes):
        with self.lock:
            if version != self.version or len(body) > self.max_bytes // 8:
                return
            old = self.items.pop(key, None)
            self.bytes += len(body) - (len(old) if old else 0)
            self.items[key] = body
            while self.items and (self.bytes > self.max_bytes or len(self.items) > self.max_items):
                _, b = self.items.popitem(last=False)
                self.bytes -= len(b)


def answer(ctx: api.Ctx, cache: Answers, path: str, p: dict) -> bytes | None:
    """The JSON body for a cacheable GET, from the cache or computed and kept."""
    version = ctx.version()
    k = cache.key(path, p)
    body = cache.get(version, k)
    if body is None:
        ctx.begin()
        try:
            out = api.GET[path](ctx, p, None)
        finally:
            ctx.end()
        body = json.dumps(out, default=str, separators=(",", ":")).encode()
        if not (isinstance(out, dict) and out.get("error")):
            cache.put(version, k, body)
    return body


def warm_loop(ctx: api.Ctx, cache: Answers):
    seen = None
    while True:
        time.sleep(3)
        try:
            v = ctx.version()
            if v == seen or ctx.job["running"] or not v[0]:
                continue
            time.sleep(2)
            if ctx.version() != v:
                continue                    # still being written; wait for it to settle
            for path, p in WARM:
                answer(ctx, cache, path, dict(p))
            seen = v
        except Exception:  # noqa: BLE001 — warming is best effort
            traceback.print_exc()
            time.sleep(30)


class Handler(BaseHTTPRequestHandler):
    ctx: api.Ctx
    cache = Answers()
    allow_upload = True
    server_version = "orgx/1"

    def log_message(self, fmt, *args):  # quieter: only errors
        if args and str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ------------------------------------------------------------ helpers
    def send(self, status: int, body: bytes, ctype: str, extra: dict | None = None):
        gz = len(body) > 1400 and "gzip" in (self.headers.get("Accept-Encoding") or "") and not ctype.startswith(("image/",))
        if gz:
            body = gzip.compress(body, 5)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if gz:
            self.send_header("Content-Encoding", "gzip")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, obj, status=200):
        self.send(status, json.dumps(obj, default=str, separators=(",", ":")).encode(), "application/json; charset=utf-8",
                  {"Cache-Control": "no-store"})

    def params(self):
        u = urlparse(self.path)
        return u.path, {k: v[-1] for k, v in parse_qs(u.query, keep_blank_values=True).items()}

    # ------------------------------------------------------------ verbs
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path, p = self.params()
        if path.startswith("/api/"):
            fn = api.GET.get(path)
            if not fn:
                return self.json({"error": "unknown endpoint"}, 404)
            if path in CACHEABLE:
                try:
                    body = answer(self.ctx, self.cache, path, p)
                except api.NoData:
                    return self.json({"error": "no data yet", "empty": True}, 409)
                except Exception as e:  # noqa: BLE001
                    traceback.print_exc()
                    return self.json({"error": f"{type(e).__name__}: {e}"}, 500)
                return self.send(200, body, "application/json; charset=utf-8", {"Cache-Control": "no-store"})
            return self.dispatch(fn, p, None)
        self.static(path)

    def do_POST(self):
        path, p = self.params()
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_UPLOAD:
            return self.json({"error": "upload too large"}, 413)
        raw = self.rfile.read(n) if n else b""
        if path == "/api/upload":
            if not self.allow_upload:
                return self.json({"error": "uploads are disabled on this server (ORGX_UPLOAD=0)"}, 403)
            return self.json(api.upload(self.ctx, p, None, raw, p.get("name") or "upload.csv"))
        fn = api.POST.get(path)
        if not fn:
            return self.json({"error": "unknown endpoint"}, 404)
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return self.json({"error": "bad json"}, 400)
        self.dispatch(fn, p, body)

    def dispatch(self, fn, p, body):
        p["_client"] = self.client_address[0]
        self.ctx.begin()
        try:
            out = fn(self.ctx, p, body)
        except api.NoData:
            return self.json({"error": "no data yet", "empty": True}, 409)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self.json({"error": f"{type(e).__name__}: {e}"}, 500)
        finally:
            self.ctx.end()
            if self.command == "POST" and urlparse(self.path).path not in READ_POSTS:
                self.ctx.writes += 1
        if isinstance(out, tuple):
            data, ctype, fname = out
            extra = {"Cache-Control": "no-store"}
            if fname:
                extra["Content-Disposition"] = f'attachment; filename="{fname}"'
            return self.send(200, data, ctype, extra)
        self.json(out)

    def static(self, path):
        rel = path.lstrip("/") or "index.html"
        f = (WEB / rel).resolve()
        if not str(f).startswith(str(WEB.resolve())) or not f.is_file():
            f = WEB / "index.html"          # SPA fallback
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if f.suffix == ".js":
            ctype = "text/javascript"
        if ctype.startswith("text/") or ctype in ("application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        cache = "no-cache" if f.name == "index.html" else "max-age=300"
        self.send(200, f.read_bytes(), ctype, {"Cache-Control": cache})


def inbox_loop(ctx: api.Ctx, seconds: int):
    inbox = ctx.data_dir / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    seen: dict[str, tuple] = {}
    while True:
        time.sleep(seconds)
        try:
            for f in sorted(inbox.glob("*.csv"), key=lambda x: x.stat().st_mtime):
                st = f.stat()
                sig = (st.st_size, st.st_mtime)
                if seen.get(f.name) != sig:        # wait one cycle for the writer to finish
                    seen[f.name] = sig
                    continue
                if ctx.job["running"]:
                    break
                dest = ctx.data_dir / "sources" / f"{time.strftime('%Y%m%d-%H%M%S')}_{f.name}"
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(f), dest)
                seen.pop(f.name, None)
                print(f"inbox: ingesting {f.name}")
                api.run_ingest(ctx, dest)
                break
        except OSError as e:
            print(f"inbox: {e}")


def seed_demo(ctx: api.Ctx):
    """First run with ORGX_DEMO=1: generate and ingest two synthetic snapshots so every view has data."""
    from orgx.ingest import ingest
    out = ctx.data_dir / "synthetic"
    if not list(out.glob("*.csv")):
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_synthetic.py"), "--out", str(out)], check=True)
    for f in sorted(out.glob("*.csv")):
        ingest(f, ctx.data_dir)


def main():
    ap = argparse.ArgumentParser(description="ORGX directory explorer")
    ap.add_argument("--host", default=os.environ.get("ORGX_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("ORGX_PORT", "48750")))
    ap.add_argument("--data", default=os.environ.get("ORGX_DATA", str(ROOT / "data")))
    ap.add_argument("--demo", action="store_true", default=os.environ.get("ORGX_DEMO") == "1")
    a = ap.parse_args()
    data = Path(a.data).resolve()
    data.mkdir(parents=True, exist_ok=True)
    for name in ("centroids.json",):                   # mounted data volumes start empty
        if not (data / name).exists() and (ROOT / "data" / name).exists():
            shutil.copy(ROOT / "data" / name, data / name)
    ctx = api.Ctx(data)
    from orgx import ingest as ing
    ing.upgrade(data)
    Handler.ctx = ctx
    threading.Thread(target=warm_loop, args=(ctx, Handler.cache), daemon=True).start()
    Handler.allow_upload = os.environ.get("ORGX_UPLOAD", "1") != "0"
    if a.demo and not (data / "org.db").exists():
        print("demo: seeding synthetic directory …")
        seed_demo(ctx)
    from orgx import adsync
    threading.Thread(target=adsync.scheduler, args=(ctx,), daemon=True).start()
    secs = int(os.environ.get("ORGX_INBOX_SECONDS", "20"))
    if secs > 0:
        threading.Thread(target=inbox_loop, args=(ctx, secs), daemon=True).start()
    httpd = ThreadingHTTPServer((a.host, a.port), Handler)
    httpd.daemon_threads = True
    shown = "localhost" if a.host in ("127.0.0.1", "0.0.0.0") else a.host
    print(f"ORGX → http://{shown}:{a.port}/   data: {data}   inbox: {data / 'inbox'}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
