"""Generate candidate eval cases from real model drafts.

Sends ordinary writing requests to several Claude models and saves their unedited drafts to
evals/generated.jsonl. Nothing is added to cases.jsonl automatically: review the drafts, then copy the
ones you want.

    python -m evals.generate                 # all requests on all models
    python -m evals.generate --models claude-haiku-5-5
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import anthropic

OUT = Path(__file__).resolve().parent / "generated.jsonl"
MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]

# (tag, mode, request). Phrased the way people actually ask, with the facts they would supply.
REQUESTS = [
    ("email", "business", "Write an email to my landlord, Mr. Kowalski, saying the kitchen sink has leaked since "
     "Monday, I put a bucket under it, and I'm home after 5pm any weekday this week for a plumber."),
    ("announcement", "business", "Write a LinkedIn post announcing I've joined Tidewater Health as head of data, "
     "after 6 years at Contoso. I'll be building their analytics team."),
    ("blog", "personal", "Write a short blog post about learning to bake sourdough during a cold winter. My first "
     "four loaves failed; the fifth worked after I moved the starter on top of the fridge."),
    ("essay", "personal", "Write a 150-word college essay paragraph about working at my uncle's hardware store "
     "every summer since I was 14."),
    ("technical", "technical", "Explain to a junior developer why our Postgres query got slow after the table grew "
     "to 50 million rows: we filter on created_at, which has no index."),
    ("marketing", "marketing", "Write product copy for a reusable water bottle: 750 ml, keeps drinks cold for 24 "
     "hours, dishwasher safe lid, $32."),
    ("encyclopedic", "technical", "Write a short encyclopedia-style paragraph about the town of Ely, Minnesota: "
     "population about 3,400, gateway to the Boundary Waters, former iron mining town."),
    ("report", "business", "Summarize these survey results for leadership: 212 responses, 64% want a four-day "
     "week, 22% neutral, 14% against, top concern is coverage on Fridays."),
    ("support", "business", "Reply to a customer whose refund hasn't arrived. It was issued on May 2 and takes 5 "
     "to 10 business days to reach their card."),
    ("academic", "academic", "Write the limitations paragraph for a study of 84 undergraduates at one university "
     "that measured sleep with self-reported diaries for two weeks."),
    ("social", "casual", "Write a tweet about finishing my first marathon in 4 hours 12 minutes."),
    ("chat-answer", "technical", "What's the difference between a Roth IRA and a traditional IRA?"),
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--models", nargs="+", default=MODELS)
    args = p.parse_args()

    client = anthropic.Anthropic(max_retries=4)
    have = set()
    if OUT.exists():
        have = {json.loads(line)["id"] for line in OUT.read_text().splitlines() if line.strip()}

    with OUT.open("a") as f:
        for model in args.models:
            for tag, mode, request in REQUESTS:
                cid = f"gen_{tag}_{re.sub(r'[^a-z0-9]+', '', model.split('claude-')[-1])}"
                if cid in have:
                    continue
                resp = client.messages.create(
                    model=model, max_tokens=4000, messages=[{"role": "user", "content": request}],
                )
                if resp.stop_reason != "end_turn":
                    print(f"skip {cid}: stop_reason {resp.stop_reason}")
                    continue
                text = "".join(b.text for b in resp.content if b.type == "text").strip()
                f.write(json.dumps({"id": cid, "kind": "ai", "mode": mode, "tags": [tag, f"generated:{model}"],
                                    "text": text, "meta": {"request": request, "model": resp.model}},
                                   ensure_ascii=False) + "\n")
                f.flush()
                print(f"wrote {cid} ({len(text.split())} words)")
    print(f"Review {OUT}, then copy the cases you want into cases.jsonl.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
