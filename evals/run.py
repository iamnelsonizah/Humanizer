"""Eval runner for the humanize flow.

Runs humanizer.pipeline.Humanizer (the real entry point) on every case, grades each output, and writes
.claude/hillclimb/humanize/<variant>/{results.jsonl, errors.jsonl, traces/}.

    python -m evals.run --variant baseline --reps 2
    python -m evals.run --app oracle --no-judge     # harness check: reference rewrites should pass
    python -m evals.run --app null --no-judge       # harness check: returning the input should fail

Properties: resume at the (case, rep) key, per-case wall-clock ceiling, SDK retries with jittered backoff,
failures in errors.jsonl with a class (never scored as zero), served-model assertion, and a harness sha gate
that a person approves with --approve-harness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_env_file(path: Path) -> None:
    """Read KEY=value lines from a git-ignored .env file. Values already set in the shell win."""
    import os

    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.removeprefix("export ").split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


def check_endpoint(allowed_proxy: str | None) -> str:
    """Return the API host. Anthropic is the default; any other host must be named with --via."""
    import os
    from urllib.parse import urlparse

    host = urlparse(os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").hostname or ""
    if host != "api.anthropic.com" and host != allowed_proxy:
        sys.exit(f"ANTHROPIC_BASE_URL points at {host!r}. To run the eval through it, pass --via {host}. "
                 "Results are then labelled with that endpoint.")
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        sys.exit("No API key. Put ANTHROPIC_API_KEY=... in the project's .env file.")
    if host != "api.anthropic.com":
        eprint(f"note: calls go through {host}, not Anthropic. The served model can't be independently "
               "verified. Costs use each model's listed price; free-tier calls actually bill $0.")
    return host


import anthropic  # noqa: E402

from evals import grader  # noqa: E402
from humanizer.pipeline import MODEL, Humanizer, RefusedError, TruncatedError  # noqa: E402

DEFAULT_FLOW = ROOT / ".claude/hillclimb/humanize"
DEFAULT_CASES = ROOT / "evals/cases.jsonl"
# $ per million tokens, from the Claude API price table. Cache writes are 1.25x input, cache reads 0.1x.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50),
    # Coarena's listed per-model prices (their free tier bills these three at $0).
    "gpt-6-luna": (0.06, 0.30), "gemini-3-8-flash": (0.45, 2.25), "deepseek-v4-1-flash-1017": (0.18, 0.72),
}
VARIANT_RX = re.compile(r"^(baseline|v\d+)$")
_lock = threading.Lock()
REPLAY: dict[str, str] = {}   # case id -> saved output, for --app replay


def eprint(*a):
    print(*a, file=sys.stderr, flush=True)


def load_cases(path: Path) -> list[dict]:
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    ids = [c["id"] for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        sys.exit(f"duplicate case ids: {sorted(dupes)}")
    for c in cases:
        if c.get("kind") not in ("ai", "human") or not c.get("text") or not c.get("tags"):
            sys.exit(f"case {c.get('id')}: needs kind (ai|human), text, and tags")
    return cases


def check_harness(state_path: Path, approve: bool) -> None:
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    paths = [Path(__file__)] + [ROOT / p for p in state.get("harness_paths", [])]
    h = hashlib.sha256()
    for p in sorted(paths, key=str):
        h.update(str(p.relative_to(ROOT)).encode())
        h.update(p.read_bytes() if p.exists() else b"<missing>")
    sha = h.hexdigest()
    if state.get("harness_sha") == sha:
        return
    names = ", ".join(str(p.relative_to(ROOT)) for p in paths)
    if approve:
        state["harness_sha"] = sha
        state_path.write_text(json.dumps(state, indent=2) + "\n")
        eprint(f"harness approved: sha256 {sha[:12]} over {names}")
        return
    eprint(f"harness not approved (sha {sha[:12]} over {names}).")
    eprint("Review those files, then run once with --approve-harness.")
    sys.exit(2)


def sum_usage(calls: list[dict]) -> dict:
    out = dict.fromkeys(grader.USAGE_KEYS, 0)
    for c in calls:
        for k in out:
            out[k] += c["usage"].get(k, 0)
    return out


def cost(model: str | None, usage: dict | None) -> float:
    if not model or not usage:
        return 0.0
    if model not in PRICES:
        eprint(f"warning: no price for {model}; its cost is left out")
        return 0.0
    pin, pout = PRICES[model]
    return (usage["input_tokens"] * pin + usage["output_tokens"] * pout
            + usage["cache_creation_input_tokens"] * pin * 1.25
            + usage["cache_read_input_tokens"] * pin * 0.1) / 1e6


class CaseError(Exception):
    def __init__(self, cls: str, msg: str, calls=None, judge=None):
        super().__init__(msg)
        self.cls, self.calls, self.judge = cls, calls or [], judge or (None, None)


def run_app(app: str, case: dict, client, model: str) -> tuple[str, list[dict]]:
    if app == "oracle":
        if "reference" not in case:
            raise CaseError("harness", "case has no reference rewrite")
        return case["reference"], []
    if app == "null":
        return case["text"], []
    if app == "replay":
        return REPLAY[case["id"]], []
    h = Humanizer(client=client, model=model)
    try:
        result = h.humanize(case["text"], mode=case.get("mode", "auto"))
    except RefusedError as e:
        raise CaseError("refusal", str(e), h.calls)
    except TruncatedError as e:
        raise CaseError("truncated", str(e), h.calls)
    except anthropic.APIError as e:
        raise CaseError("serving", f"{type(e).__name__}: {e}", h.calls)
    bad = [c["model"] for c in h.calls if c["model"] != model]
    if bad:
        raise CaseError("served_model_mismatch", f"asked for {model}, served by {sorted(set(bad))}", h.calls)
    return result.text, h.calls


def write_trace(path: Path, case: dict, calls: list[dict], output: str) -> None:
    turns = []
    for i, c in enumerate(calls):
        turns.append({"role": "system", "content": f"[call {i + 1}: {c['model']}]\n{c['system']}"})
        turns.append({"role": "user", "content": c["user"]})
        turns.append({"role": "assistant", "content": c["output"]})
    if not calls:
        turns = [{"role": "user", "content": case["text"]}, {"role": "assistant", "content": output}]
    path.write_text(json.dumps(turns, indent=2, ensure_ascii=False))


def append(path: Path, row: dict) -> None:
    with _lock, path.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def one(case, rep, args, client, judge_client, vdir):
    t0 = time.monotonic()
    calls = []
    try:
        output, calls = run_app(args.app, case, client, args.model)
        latency = round(time.monotonic() - t0, 2)
        try:
            g = grader.grade(case, output, judge_client, args.judge_model)
        except grader.JudgeError as e:
            raise CaseError("grader", str(e), calls, (e.judge_model, e.judge_usage))
        except (anthropic.APIError, json.JSONDecodeError, KeyError) as e:
            raise CaseError("grader", f"{type(e).__name__}: {e}", calls)
    except CaseError as e:
        return {"error": True, "prompt_id": case["id"], "rep": rep, "class": e.cls, "message": str(e),
                "model": e.calls[-1]["model"] if e.calls else None, "usage": sum_usage(e.calls) if e.calls else None,
                "judge_model": e.judge[0], "judge_usage": e.judge[1]}

    write_trace(vdir / "traces" / f"{case['id']}_rep{rep}.json", case, calls, output)
    usage = sum_usage(calls)
    model = calls[0]["model"] if calls else None   # oracle/null/replay make no model call
    return {
        "prompt_id": case["id"], "rep": rep, "prompt": case["text"], "tags": case["tags"],
        "status": "ok", "stop_reason": calls[-1]["stop_reason"] if calls else "end_turn",
        "grade": g["grade"], "explanation": g["explanation"],
        "model": model, "usage": usage, "judge_model": g["judge_model"], "judge_usage": g["judge_usage"],
        "latency_s": latency,
        "perf": {"cost_usd": round(cost(model, usage) + cost(g["judge_model"], g["judge_usage"]), 4),
                 "in_tokens": usage["input_tokens"], "out_tokens": usage["output_tokens"]},
        "meta": {"output": output, "scan": g["scan"], "model_calls": len(calls), "app": args.app,
                 "endpoint": getattr(args, "endpoint", None)},
    }


def ci95(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return float("nan")
    m = sum(values) / n
    sd = math.sqrt(sum((v - m) ** 2 for v in values) / (n - 1))
    return 1.96 * sd / math.sqrt(n)


def summarize(rows: list[dict], errors: list[dict]) -> None:
    if not rows:
        eprint("no scored rows")
        return
    metrics = list(rows[0]["grade"])
    print(f"\n{len(rows)} scored rows, {len(errors)} failed attempts")
    for m in metrics:
        vals = [r["grade"][m] for r in rows]
        print(f"  {m:<14} {sum(vals) / len(vals):.3f} ± {ci95(vals):.3f}")
    by_tag = defaultdict(list)
    for r in rows:
        by_tag[r["tags"][0]].append(r["grade"]["pass"])
    print("  pass by type: " + ", ".join(f"{t} {sum(v) / len(v):.2f} (n={len(v)})" for t, v in sorted(by_tag.items())))
    spend = sum(r["perf"]["cost_usd"] for r in rows) + sum(cost(e.get("model"), e.get("usage"))
                                                          + cost(e.get("judge_model"), e.get("judge_usage"))
                                                          for e in errors)
    print(f"  spend ${spend:.2f} (${spend / len(rows):.3f} per scored row, failed attempts included in the total)")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--flow", type=Path, default=DEFAULT_FLOW)
    p.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    p.add_argument("--variant", default="baseline")
    p.add_argument("--app", choices=["humanizer", "oracle", "null", "replay"], default="humanizer")
    p.add_argument("--from", dest="replay_from", default="baseline",
                   help="with --app replay: the variant whose saved outputs are graded again")
    p.add_argument("--model", default=MODEL, help="model the humanizer pipeline uses")
    p.add_argument("--judge-model", default=grader.JUDGE_MODEL, help="model the fact judge uses")
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--timeout-s", type=float, default=600)
    p.add_argument("--limit", type=int, help="run only the first N cases (pilot)")
    p.add_argument("--no-judge", action="store_true", help="skip the fact judge (offline harness checks)")
    p.add_argument("--approve-harness", action="store_true")
    p.add_argument("--via", help="host of an Anthropic-compatible proxy to allow, e.g. coarena.ai")
    args = p.parse_args()

    if args.app != "humanizer":
        args.variant = f"_check_{args.app}"     # never lands in a directory the report reads
    elif not VARIANT_RX.match(args.variant):
        sys.exit("--variant must be 'baseline' or v<N>")

    args.flow.mkdir(parents=True, exist_ok=True)
    needs_api = args.app == "humanizer" or not args.no_judge
    if needs_api:  # offline harness checks spend nothing, so they skip the approval gate
        load_env_file(ROOT / ".env")
        args.endpoint = check_endpoint(args.via)
        check_harness(args.flow / "_state.json", args.approve_harness)

    cases = load_cases(args.cases)[: args.limit]
    if args.app == "replay":
        src = args.flow / args.replay_from / "results.jsonl"
        for line in src.read_text().splitlines():
            r = json.loads(line)
            REPLAY.setdefault(r["prompt_id"], r["meta"]["output"])
        cases = [c for c in cases if c["id"] in REPLAY]
    vdir = args.flow / args.variant
    (vdir / "traces").mkdir(parents=True, exist_ok=True)
    results_path, errors_path = vdir / "results.jsonl", vdir / "errors.jsonl"
    done = set()
    if results_path.exists():
        done = {(r["prompt_id"], r["rep"]) for r in map(json.loads, results_path.read_text().splitlines())}

    client = anthropic.Anthropic(max_retries=4) if needs_api else None
    judge_client = None if args.no_judge else client

    todo = [(c, r) for c in cases for r in range(args.reps) if (c["id"], r) not in done]
    eprint(f"{len(todo)} attempts to run ({len(done)} already done) -> {vdir}")
    t0 = time.monotonic()
    started: dict[tuple, float] = {}

    slots = threading.Semaphore(args.concurrency)   # the real cap on cases in flight

    def timed(c, r):
        with slots:
            started[(c["id"], r)] = time.monotonic()
            return one(c, r, args, client, judge_client, vdir)

    # A timed-out call cannot be aborted; its thread keeps running in the background and keeps its slot
    # until it returns. The pool has spare threads so waiting cases are queued, not dropped.
    pool = ThreadPoolExecutor(max_workers=args.concurrency + 4)
    pending = {pool.submit(timed, c, r): (c, r) for c, r in todo}
    n_done = 0
    while pending:
        finished, _ = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
        now = time.monotonic()
        expired = {f for f, (c, r) in pending.items() if f not in finished and args.timeout_s
                   and now - started.get((c["id"], r), now) > args.timeout_s}
        for fut in finished | expired:
            c, r = pending.pop(fut)
            n_done += 1
            if fut in expired:
                row = {"error": True, "prompt_id": c["id"], "rep": r, "class": "timeout",
                       "message": f"no result within {args.timeout_s}s"}
            else:
                try:
                    row = fut.result()
                except Exception as e:  # a bug in the harness, not a model failure
                    row = {"error": True, "prompt_id": c["id"], "rep": r, "class": "harness", "message": repr(e)}
            if row.pop("error", False):
                append(errors_path, row)
                eprint(f"[{n_done}/{len(todo)}] {c['id']} rep{r}: {row['class']}: {row['message']}")
            else:
                append(results_path, row)
                eprint(f"[{n_done}/{len(todo)}] {c['id']} rep{r}: pass={row['grade']['pass']} "
                       f"facts={row['grade']['facts_kept']} tells={row['grade']['tells_cleared']}")
    pool.shutdown(wait=False, cancel_futures=True)

    rows = [json.loads(x) for x in results_path.read_text().splitlines()] if results_path.exists() else []
    errs = [json.loads(x) for x in errors_path.read_text().splitlines()] if errors_path.exists() else []
    summarize(rows, errs)
    eprint(f"wall clock {time.monotonic() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
