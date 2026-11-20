"""Shared logic for the web app: serialization, diffing, chunking, and the humanize job.

The HTTP layer lives in humanizer/api.py (FastAPI). Run locally with `humanize web`.
"""

from __future__ import annotations

import difflib
import os
import re
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..citations import find_marks
from ..detector import Report, detect
from ..prompts import ACADEMIC_MODES, MODES
from ..voice import build_profile

STATIC = Path(__file__).parent / "static"
MAX_CHARS = 120_000
CHUNK_WORDS = 900          # long documents are split at paragraph breaks and edited in parallel
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}


def load_env(root: Path) -> None:
    env = root / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# --- serialization --------------------------------------------------------------------------------------------

def _utf16_map(text: str):
    """Python indexes code points; the browser indexes UTF-16 units. Map one to the other."""
    out, n = [0], 0
    for ch in text:
        n += 2 if ord(ch) > 0xFFFF else 1
        out.append(n)
    return out


def report_json(text: str, report: Report, with_hits: bool = True) -> dict:
    s = report.stats
    data = {
        "score": report.score,
        "stats": s.__dict__ if s else {},
        "counts": {"strong": sum(h.strength == 3 for h in report.hits),
                   "medium": sum(h.strength == 2 for h in report.hits),
                   "weak": sum(h.strength == 1 for h in report.hits)},
    }
    if with_hits:
        u = _utf16_map(text)
        data["hits"] = [{"rule": h.rule, "name": h.name, "strength": h.strength, "text": h.text,
                         "advice": h.advice, "start": u[h.start], "end": u[h.end]} for h in report.hits]
        data["marks"] = [{"kind": m.kind, "text": m.text, "start": u[m.start], "end": u[m.end]}
                         for m in find_marks(text)]
    return data


TOKEN_RX = re.compile(r"\s+|[\w'’\-]+|[^\w\s]", re.UNICODE)


def hunks(a: str, b: str) -> list[dict]:
    """Diff at word level, then merge nearby edits so each hunk reads as one change a person can judge."""
    ta, tb = TOKEN_RX.findall(a), TOKEN_RX.findall(b)
    ops = difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes()
    out: list[dict] = []
    for tag, i1, i2, j1, j2 in ops:
        sa, sb = "".join(ta[i1:i2]), "".join(tb[j1:j2])
        if tag == "equal":
            out.append({"t": "eq", "s": sa})
        else:
            out.append({"t": "ch", "a": sa, "b": sb})

    merged: list[dict] = []
    i = 0
    while i < len(out):
        cur = out[i]
        # Absorb a short equal run sitting between two changes into one hunk.
        if (cur["t"] == "eq" and merged and merged[-1]["t"] == "ch" and i + 1 < len(out)
                and len(re.findall(r"\w+", cur["s"])) <= 2 and not re.search(r"[.!?:;\n]", cur["s"])):
            merged[-1]["a"] += cur["s"]
            merged[-1]["b"] += cur["s"]
        elif cur["t"] == "ch" and merged and merged[-1]["t"] == "ch":
            merged[-1]["a"] += cur["a"]
            merged[-1]["b"] += cur["b"]
        else:
            merged.append(dict(cur))
        i += 1

    # Move leading/trailing whitespace shared by both sides out of the hunk, so toggling it never glues words.
    final: list[dict] = []
    for h in merged:
        if h["t"] == "ch":
            lead = re.match(r"\s*", h["a"]).group()
            if lead and h["b"].startswith(lead):
                final.append({"t": "eq", "s": lead})
                h["a"], h["b"] = h["a"][len(lead):], h["b"][len(lead):]
            trail = re.search(r"\s*$", h["a"]).group()
            if trail and h["b"].endswith(trail) and len(trail) < len(h["a"]) and len(trail) < len(h["b"]) + 1:
                h["a"], h["b"] = h["a"][: len(h["a"]) - len(trail)], h["b"][: len(h["b"]) - len(trail)]
                final.append(h)
                final.append({"t": "eq", "s": trail})
                continue
        final.append(h)
    return [h for h in final if (h["t"] == "eq" and h["s"]) or (h["t"] == "ch" and (h["a"] or h["b"]))]


def split_chunks(text: str, limit: int = CHUNK_WORDS) -> list[tuple[str, str]]:
    """Split at paragraph breaks into (chunk, separator-after) pairs of about `limit` words."""
    parts = re.split(r"(\n\s*\n)", text)
    chunks, cur, words = [], "", 0
    for i in range(0, len(parts), 2):
        para = parts[i]
        sep = parts[i + 1] if i + 1 < len(parts) else ""
        n = len(para.split())
        if cur and words + n > limit:
            chunks.append(cur)
            cur, words = "", 0
        cur += para + sep
        words += n
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks:
        body = c.rstrip()
        out.append((body, c[len(body):]))
    return out


# --- humanize job -------------------------------------------------------------------------------------------

def run_job(payload: dict, emit) -> None:
    from ..pipeline import Humanizer, Options, RefusedError, TruncatedError

    text = payload.get("text", "")
    mode = payload.get("mode", "auto")
    if mode not in MODES:
        mode = "auto"
    opts = Options(
        intensity=payload.get("intensity", "balanced"),
        dialect=payload.get("dialect", "auto"),
        keep_length=bool(payload.get("keep_length", mode in ACADEMIC_MODES)),
        protect_citations=bool(payload.get("protect_citations", True)),
        protected_terms=[t.strip() for t in payload.get("protected_terms", []) if t.strip()][:50],
    )
    sample = (payload.get("voice_sample") or "").strip()
    voice = build_profile(sample) if len(sample.split()) >= 60 else None

    chunks = split_chunks(text)
    emit({"type": "plan", "chunks": len(chunks)})

    try:
        import anthropic
        client = anthropic.Anthropic()
    except Exception as e:  # noqa: BLE001
        emit({"type": "error", "message": f"Could not start the Claude client: {e}"})
        return

    lock = threading.Lock()
    usage = {"input_tokens": 0, "output_tokens": 0}

    def work(idx: int):
        body, _sep = chunks[idx]
        if not body.strip():
            return idx, None
        h = Humanizer(client=client)

        def step(msg: str):
            stage = ("scan" if msg.startswith("Scan") else "check" if msg.startswith("Checking")
                     else "revise" if msg.startswith("Revision") else "rewrite")
            emit({"type": "step", "chunk": idx, "stage": stage, "message": msg})

        emit({"type": "step", "chunk": idx, "stage": "rewrite", "message": "Rewriting"})
        r = h.humanize(body, mode=mode, voice=voice, on_step=step, options=opts)
        with lock:
            for c in h.calls:
                for k in usage:
                    usage[k] += c["usage"].get(k, 0)
        emit({"type": "chunk_done", "chunk": idx})
        return idx, r

    results: dict[int, object] = {}
    try:
        with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
            for idx, r in pool.map(work, range(len(chunks))):
                results[idx] = r
    except RefusedError:
        emit({"type": "error", "message": "The model declined to edit this text."})
        return
    except TruncatedError as e:
        emit({"type": "error", "message": str(e)})
        return
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        msg = str(e)
        if "api_key" in msg.lower() or "authentication" in msg.lower():
            msg = "No working ANTHROPIC_API_KEY. Add it to .env in the project folder and restart."
        emit({"type": "error", "message": msg})
        return

    out_text = "".join((results[i].text if results[i] else chunks[i][0]) + chunks[i][1] for i in range(len(chunks)))
    out_text = out_text.rstrip() + ("\n" if text.endswith("\n") else "")
    rs = [r for r in results.values() if r]
    allow = bool(voice and voice.uses_dashes)
    emit({
        "type": "result",
        "text": out_text,
        "hunks": hunks(text, out_text),
        "before": report_json(text, detect(text, allow_dashes=allow), with_hits=False),
        "after": report_json(out_text, detect(out_text, allow_dashes=allow)),
        "fact_issues": [i for r in rs for i in r.fact_issues],
        "lost_marks": [m for r in rs for m in r.lost_marks],
        "lost_terms": sorted({t for r in rs for t in r.lost_terms}),
        "marks_total": len(find_marks(text)) if opts.protect_citations else 0,
        "revisions": sum(r.revisions for r in rs),
        "voice_distance": rs[0].voice_distance if voice and len(rs) == 1 else None,
        "voice_used": voice is not None,
        "usage": usage,
    })


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn
    print(f"Humanizer is running at http://{host}:{port}  (Ctrl+C to stop)")
    uvicorn.run("humanizer.api:app", host=host, port=port, log_level="warning")
