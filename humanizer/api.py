"""FastAPI app: the Humanizer API, plus the web UI for local use.

Deployed to FastAPI Cloud (entrypoint set in pyproject.toml). The Vercel frontend calls it across origins, so
ALLOWED_ORIGINS must list the Vercel domain(s).

Environment:
  ANTHROPIC_API_KEY        required for /api/humanize
  ALLOWED_ORIGINS          comma-separated origins allowed by CORS, e.g. https://humanizer.vercel.app
  RATE_LIMIT_PER_HOUR      humanize runs per client IP per hour (default 20, 0 = unlimited)
  ACCESS_CODE              optional; when set, /api/humanize requires header X-Access-Code with this value
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .detector import detect
from .prompts import MODES
from .voice import build_profile
from .web.server import MAX_CHARS, STATIC, load_env, report_json, run_job

load_env(Path.cwd())
load_env(Path(__file__).resolve().parents[1])

app = FastAPI(title="Humanizer API", version="0.2.0", docs_url="/api/docs", openapi_url="/api/openapi.json")

_origins = [o.strip().rstrip("/") for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    # Vercel preview deployments get their own subdomains; allow them when the production domain is on vercel.app.
    allow_origin_regex=os.environ.get("ALLOWED_ORIGIN_REGEX") or None,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Access-Code"],
    max_age=3600,
)


# --- request models -----------------------------------------------------------------------------------------

class TextIn(BaseModel):
    text: str = Field("", max_length=MAX_CHARS)


class ProfileIn(BaseModel):
    sample: str = Field("", max_length=MAX_CHARS)


class HumanizeIn(BaseModel):
    text: str = Field(..., max_length=MAX_CHARS)
    mode: str = "auto"
    intensity: str = "balanced"
    dialect: str = "auto"
    keep_length: bool | None = None
    protect_citations: bool = True
    protected_terms: list[str] = Field(default_factory=list, max_length=50)
    voice_sample: str = Field("", max_length=20_000)


# --- abuse limits -------------------------------------------------------------------------------------------

_hits: dict[str, deque] = defaultdict(deque)
_hits_lock = threading.Lock()


def _client_ip(req: Request) -> str:
    fwd = req.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (req.client.host if req.client else "unknown")


def _check_limits(req: Request) -> None:
    code = os.environ.get("ACCESS_CODE")
    if code and req.headers.get("x-access-code") != code:
        raise HTTPException(401, "This Humanizer needs an access code.")
    limit = int(os.environ.get("RATE_LIMIT_PER_HOUR", "20"))
    if limit <= 0:
        return
    now, ip = time.time(), _client_ip(req)
    with _hits_lock:
        q = _hits[ip]
        while q and now - q[0] > 3600:
            q.popleft()
        if len(q) >= limit:
            raise HTTPException(429, f"Limit reached: {limit} rewrites per hour. Try again later.")
        q.append(now)


@app.exception_handler(HTTPException)
async def _err(_req: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


# --- routes -------------------------------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/meta")
def meta():
    return {"modes": list(MODES), "has_key": bool(os.environ.get("ANTHROPIC_API_KEY")), "max_chars": MAX_CHARS,
            "needs_code": bool(os.environ.get("ACCESS_CODE"))}


@app.post("/api/scan")
def scan(body: TextIn):
    return report_json(body.text, detect(body.text))


@app.post("/api/profile")
def profile(body: ProfileIn):
    p = build_profile(body.sample)
    return {"profile": p.__dict__ | {"excerpt": ""}, "describe": p.describe(), "words": len(body.sample.split())}


@app.post("/api/humanize")
def humanize(body: HumanizeIn, request: Request):
    if not body.text.strip():
        raise HTTPException(400, "Paste some text first.")
    _check_limits(request)
    payload = body.model_dump()
    if payload["keep_length"] is None:
        payload.pop("keep_length")

    events: queue.Queue = queue.Queue()
    done = object()

    def worker():
        try:
            run_job(payload, events.put)
        except Exception as e:  # noqa: BLE001
            events.put({"type": "error", "message": str(e) or "The rewrite failed."})
        finally:
            events.put(done)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        while True:
            try:
                ev = events.get(timeout=15)
            except queue.Empty:
                yield ": keep-alive\n\n"      # stops proxies from closing a quiet connection
                continue
            if ev is done:
                return
            yield f"data: {json.dumps(ev)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# The UI, for local use and as a fallback. In production the Vercel deployment serves it.
app.mount("/", StaticFiles(directory=STATIC, html=True), name="ui")
