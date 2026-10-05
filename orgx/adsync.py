"""Who am I + direct AD sync, both using the logged-in Windows user's credentials.

Identity: when the server runs on the user's own (domain-joined) workstation, the
server process *is* that user, so `whoami /fqdn` (their DN) and `whoami /upn` identify
them without any login screen. Only answered for requests from this machine
(loopback) unless ORGX_WHOAMI=any, so a shared server never claims to be everyone.

Sync: runs tools/Export-ADDirectory.ps1 (ADSI DirectorySearcher → Kerberos as the
logged-in user, or RSAT if present), streams its progress into the job log, then
ingests the CSV like any other source.
"""
from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "Export-ADDirectory.ps1"
DEFAULT_AD = {"server": "", "bases": [], "method": "Auto", "members": True, "hours": 0, "mode": "export", "liveHours": 12}

_identity: dict | None = None


def _run(cmd: list[str], timeout: int = 15) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def detect_identity() -> dict:
    global _identity
    if _identity is not None:
        return _identity
    ident = {"method": "", "dn": "", "upn": "", "user": "", "domain": ""}
    forced = os.environ.get("ORGX_USER", "").strip()
    if forced:
        ident.update(method="ORGX_USER", **({"dn": forced} if "=" in forced else {"upn": forced}))
    elif os.name == "nt":
        ident["method"] = "whoami"
        ident["dn"] = _run(["whoami", "/fqdn"])
        ident["upn"] = _run(["whoami", "/upn"])
        ident["user"] = os.environ.get("USERNAME", "")
        ident["domain"] = os.environ.get("USERDNSDOMAIN", "")
    else:
        ident["method"] = "process user"
        try:
            ident["user"] = getpass.getuser()
        except Exception:  # noqa: BLE001
            pass
    _identity = ident
    return ident


def whoami(ctx, p, b):
    client = p.get("_client", "")
    allowed = os.environ.get("ORGX_WHOAMI", "local") == "any" or client in ("127.0.0.1", "::1", "localhost")
    if not allowed:
        return {"available": False, "reason": "identity is only read for requests from the server's own machine"}
    ident = detect_identity()
    out = {"available": True, "detected": ident, "match": None}
    conn = ctx.conn()
    if conn is None:
        return out
    row = None
    if ident.get("dn"):
        row = conn.execute("SELECT key FROM objects WHERE lower(dn) = lower(?)", (ident["dn"],)).fetchone()
    if not row and ident.get("upn"):
        row = conn.execute("SELECT key FROM objects WHERE lower(upn) = lower(?) OR lower(email) = lower(?)",
                           (ident["upn"], ident["upn"])).fetchone()
    if not row and ident.get("user") and ident.get("domain"):
        row = conn.execute("SELECT key FROM objects WHERE lower(sam) = lower(?) AND lower(domain) = lower(?)",
                           (ident["user"], ident["domain"])).fetchone()
    if row:
        r = conn.execute("SELECT o.key, o.name, o.rank, o.title, o.org_id, o.loc_id, o.email, l.name AS loc_name, l.tz "
                         "FROM objects o LEFT JOIN locations l ON l.id = o.loc_id WHERE o.key = ?", (row[0],)).fetchone()
        out["match"] = {k: r[k] for k in r.keys()}
    return out


# ---------------------------------------------------------------- AD connector
def shell() -> str:
    return shutil.which("powershell") or shutil.which("powershell.exe") or shutil.which("pwsh") or ""


def config(ctx) -> dict:
    return {**DEFAULT_AD, **(ctx.rules().get("ad") or {})}


def _state_path(ctx) -> Path:
    return ctx.data_dir / "ad_state.json"


def state(ctx) -> dict:
    try:
        return json.loads(_state_path(ctx).read_text())
    except (OSError, ValueError):
        return {}


def _save_state(ctx, **kw):
    s = state(ctx)
    s.update(kw)
    _state_path(ctx).write_text(json.dumps(s, indent=1))


def _args(cfg: dict) -> list[str]:
    a = [shell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT),
         "-Method", cfg.get("method", "Auto")]
    if cfg.get("server"):
        a += ["-Server", cfg["server"]]
    bases = [b for b in (cfg.get("bases") or []) if b.strip()]
    if bases:
        a += ["-SearchBase", ";".join(bases)]
    if not cfg.get("members", True):
        a += ["-SkipMembers"]
    return a


def status(ctx, p, b):
    sh = shell()
    return {"available": bool(sh), "shell": sh, "os": os.name, "script": str(SCRIPT), "config": config(ctx),
            "state": state(ctx),
            "hint": "" if sh else "PowerShell isn't available where the server runs (e.g. the Docker image). Run "
                                  "tools/Export-ADDirectory.ps1 on a domain-joined workstation with -Inbox pointing at this server's inbox."}


def test(ctx, p, b):
    if not shell():
        return {"ok": False, "error": status(ctx, p, b)["hint"]}
    cfg = config(ctx)
    try:
        out = subprocess.run(_args(cfg) + ["-Test"], capture_output=True, text=True, timeout=120,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timed out after 120 s — is the domain controller reachable?"}
    res = _result(out.stdout)
    if not res:
        res = {"ok": False, "error": (out.stderr or out.stdout or "no output").strip()[-800:]}
    _save_state(ctx, last_test=datetime.now(timezone.utc).isoformat(timespec="seconds"), test=res)
    return res


def _result(text: str) -> dict | None:
    for line in reversed(text.splitlines()):
        if line.startswith("RESULT "):
            try:
                return json.loads(line[7:])
            except ValueError:
                return None
    return None


def sync(ctx, p, b):
    from .api import run_ingest_job
    if not shell():
        return {"ok": False, "error": status(ctx, p, b)["hint"]}
    cfg = config(ctx)
    src = ctx.data_dir / "sources"
    src.mkdir(parents=True, exist_ok=True)
    out = src / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_ad_{(cfg['server'] or 'domain').split('.')[0]}.csv"

    def work(log):
        proc = subprocess.Popen(_args(cfg) + ["-OutFile", str(out)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        result = None
        for line in proc.stdout:
            line = line.rstrip()
            if line.startswith("RESULT "):
                result = _result(line)
            elif line:
                log(line)
        proc.wait()
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(f"AD export failed (exit {proc.returncode})")
        _save_state(ctx, last_sync=datetime.now(timezone.utc).isoformat(timespec="seconds"), sync=result or {})
        return out

    ok = run_ingest_job(ctx, f"AD sync · {cfg['server'] or 'your domain'}", work)
    return {"ok": ok, "error": None if ok else "a job is already running"}


def scheduler(ctx):
    """Background loop: re-sync every `ad.hours` hours (0 = manual only)."""
    while True:
        time.sleep(300)
        try:
            cfg = config(ctx)
            hours = float(cfg.get("hours") or 0)
            if hours <= 0 or not shell() or ctx.job["running"]:
                continue
            last = state(ctx).get("last_sync")
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() / 3600 if last else 1e9
            if age >= hours:
                sync(ctx, {}, None)
        except Exception as e:  # noqa: BLE001 — never kill the loop
            print(f"ad scheduler: {e}")
