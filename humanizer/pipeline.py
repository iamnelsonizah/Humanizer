"""The humanize pipeline: scan, rewrite, fact-check, rescan, revise."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import anthropic

from . import prompts
from .citations import find_marks, missing_marks, missing_terms
from .detector import STRONG, Report, detect
from .voice import VoiceProfile, voice_distance

MODEL = "claude-opus-5-5"
MAX_REVISIONS = 2


class RefusedError(RuntimeError):
    pass


class TruncatedError(RuntimeError):
    pass


def is_direct_anthropic(client) -> bool:
    """True when the client talks to Anthropic's own API rather than a proxy."""
    base = getattr(client, "base_url", None)
    return base is None or "api.anthropic.com" in str(base)


def anthropic_only_kwargs(client) -> dict:
    """Server-side refusal fallback is an Anthropic beta; proxies may reject it, so send it only to Anthropic."""
    if is_direct_anthropic(client):
        return {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    return {}


@dataclass
class Options:
    intensity: str = "balanced"         # light | balanced | deep
    dialect: str = "auto"               # auto | us | uk
    keep_length: bool = False
    protect_citations: bool = True
    protected_terms: list[str] = field(default_factory=list)


@dataclass
class Result:
    original: str
    text: str
    before: Report
    after: Report
    fact_issues: list[dict] = field(default_factory=list)
    revisions: int = 0
    voice_distance: float | None = None
    lost_marks: list[str] = field(default_factory=list)       # citations or figures the final text lacks
    lost_terms: list[str] = field(default_factory=list)       # protected terms the final text lacks


def _format_tells(report: Report, limit: int = 40) -> str:
    lines = []
    for h in report.hits[:limit]:
        lines.append(f'- [{h.name}] "{h.text}" -> {h.advice}')
    s = report.stats
    if s and s.sentences >= 6 and s.sentence_len_cv < 0.25:
        lines.append("- [Flat rhythm] Sentences are all about the same length. Mix short and long ones.")
    if s and s.fragment_rows:
        lines.append("- [Fragment rows] Runs of very short dramatic fragments. Merge them into sentences.")
    if s and s.one_line_paragraph_share >= 0.4:
        lines.append("- [One-line paragraphs] Too many single-sentence paragraphs. Merge related ones.")
    return "\n".join(lines)


class Humanizer:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str = MODEL):
        self.client = client or anthropic.Anthropic()
        self.model = model
        self.calls: list[dict] = []     # one entry per model call, for evals and cost tracking

    def _call(self, system: str, user: str, *, effort: str, schema: dict | None = None) -> str:
        kwargs: dict = {
            "model": self.model,
            "max_tokens": 16000,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {"effort": effort},
            **anthropic_only_kwargs(self.client),
        }
        if schema:
            kwargs["output_config"]["format"] = {"type": "json_schema", "schema": schema}
        t0 = time.monotonic()
        resp = self.client.beta.messages.create(**kwargs)
        out = "".join(b.text for b in resp.content if b.type == "text").strip()
        usage = getattr(resp, "usage", None)
        self.calls.append({
            "system": system, "user": user, "output": out,
            "model": getattr(resp, "model", self.model), "stop_reason": resp.stop_reason,
            "latency_s": round(time.monotonic() - t0, 2),
            "usage": {k: getattr(usage, k, 0) or 0 for k in
                      ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")},
        })
        if resp.stop_reason == "refusal":
            raise RefusedError("The model declined this text.")
        if resp.stop_reason == "max_tokens":
            raise TruncatedError("The output hit the token limit. Split the text into smaller parts.")
        return out

    def rewrite(self, text: str, report: Report, mode: str, voice: VoiceProfile | None,
                options: str | None = None) -> str:
        voice_txt = f"{voice.describe()}\n\nSample:\n{voice.excerpt}" if voice else None
        return self._call(prompts.REWRITE_SYSTEM,
                          prompts.rewrite_user(text, _format_tells(report), mode, voice_txt, options),
                          effort="high")

    def factcheck(self, original: str, rewrite: str) -> list[dict]:
        raw = self._call(prompts.FACTCHECK_SYSTEM, prompts.factcheck_user(original, rewrite),
                         effort="medium", schema=prompts.FACTCHECK_SCHEMA)
        return json.loads(raw)["issues"]

    def revise(self, original: str, draft: str, problems: str, voice: VoiceProfile | None,
               options: str | None = None) -> str:
        system = prompts.REWRITE_SYSTEM
        if options:
            system += f"\n{options}\n"
        if voice:
            system += f"\nMatch this writer's voice:\n{voice.describe()}\n\nSample:\n{voice.excerpt}\n"
        return self._call(system, prompts.revise_user(original, draft, problems), effort="high")

    def humanize(self, text: str, mode: str = "auto", voice: VoiceProfile | None = None,
                 on_step=lambda msg: None, options: Options | None = None) -> Result:
        opts = options or Options()
        allow_dashes = bool(voice and voice.uses_dashes)
        before = detect(text, allow_dashes=allow_dashes)
        marks = [m.text for m in find_marks(text)] if opts.protect_citations else []
        terms = [t for t in opts.protected_terms if t.strip() and t.strip().lower() in text.lower()]
        opt_txt = prompts.options_text(opts.intensity, opts.dialect, opts.keep_length, terms, marks)

        on_step(f"Scan found {len(before.hits)} tells (score {before.score}). Rewriting...")
        draft = self.rewrite(text, before, mode, voice, opt_txt)

        issues: list[dict] = []
        revisions = 0
        for _ in range(MAX_REVISIONS + 1):
            on_step("Checking facts...")
            issues = self.factcheck(text, draft)
            after = detect(draft, allow_dashes=allow_dashes)
            leftover = [h for h in after.hits if h.strength == STRONG or h.rule == "dash"]

            problems = []
            for i in issues:
                problems.append(f"- Meaning {i['kind']}: original \"{i['original']}\" / rewrite \"{i['rewrite']}\". "
                                f"{i['explanation']}")
            lost = missing_marks(text, draft) if marks else []
            lost_t = missing_terms(terms, draft)
            for m in lost:
                problems.append(f"- Citation or figure lost or altered: \"{m.text}\". Restore it exactly.")
            for t in lost_t:
                problems.append(f"- Protected term missing: \"{t}\". Use it exactly as written.")
            if leftover:
                problems.append("Tells that survived:\n" + _format_tells(Report(hits=leftover, stats=after.stats)))
            if not problems or revisions == MAX_REVISIONS:
                break
            revisions += 1
            on_step(f"Revision {revisions}: fixing {len(issues)} meaning issues, {len(lost) + len(lost_t)} "
                    f"lost citations or terms, and {len(leftover)} tells...")
            draft = self.revise(text, draft, "\n".join(problems), voice, opt_txt)

        return Result(
            original=text,
            text=draft,
            before=before,
            after=after,
            fact_issues=issues,
            revisions=revisions,
            voice_distance=voice_distance(voice, draft) if voice else None,
            lost_marks=[m.text for m in lost],
            lost_terms=lost_t,
        )
