"""Write evals/cases.md: every case in full, for review."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from humanizer.detector import detect  # noqa: E402


def fence(text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def main() -> None:
    cases = [json.loads(line) for line in (HERE / "cases.jsonl").read_text().splitlines() if line.strip()]
    types = Counter(c["tags"][0] for c in cases)
    kinds = Counter(c["kind"] for c in cases)
    out = [
        "# Humanize eval cases",
        "",
        f"{len(cases)} cases: {kinds['ai']} AI-written to rewrite, {kinds['human']} human-style controls to leave alone.",
        "",
        "By type: " + ", ".join(f"{t} {n}" for t, n in sorted(types.items())),
        "",
        "| id | kind | mode | tags | words | scan before |",
        "|---|---|---|---|---|---|",
    ]
    for c in cases:
        r = detect(c["text"])
        out.append(f"| {c['id']} | {c['kind']} | {c.get('mode', 'auto')} | {', '.join(c['tags'])} "
                   f"| {r.stats.words} | {r.score} |")
    for c in cases:
        f = fence(c["text"])
        out += ["", f"## {c['id']}", "", f"{c['kind']} · {c.get('mode', 'auto')} · {', '.join(c['tags'])}", "",
                f + "text", c["text"], f]
    (HERE / "cases.md").write_text("\n".join(out) + "\n")
    print(f"wrote {HERE / 'cases.md'}")


if __name__ == "__main__":
    main()
