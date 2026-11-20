"""Command line: humanize, scan, and build voice profiles."""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

from .detector import detect
from .prompts import MODES
from .voice import VoiceProfile, build_profile


def _read(src: str) -> str:
    return sys.stdin.read() if src == "-" else Path(src).read_text()


def _print_report(report, title: str) -> None:
    s = report.stats
    print(f"{title}: score {report.score}/100, {len(report.hits)} tells, {s.words} words", file=sys.stderr)
    print(f"  sentence length {s.mean_sentence_len} avg, spread {s.sentence_len_cv}; "
          f"dashes {s.dashes_per_1k}/1k; triads {s.triads_per_1k}/1k", file=sys.stderr)


def cmd_scan(args) -> int:
    report = detect(_read(args.input))
    _print_report(report, "Scan")
    for h in report.hits:
        print(f"  {'!' * h.strength:<3} {h.name}: \"{h.text}\"  -> {h.advice}")
    return 1 if report.strong_hits() else 0


def cmd_profile(args) -> int:
    profile = build_profile("\n\n".join(_read(p) for p in args.samples))
    profile.save(args.out)
    print(profile.describe())
    print(f"Saved to {args.out}", file=sys.stderr)
    return 0


def cmd_humanize(args) -> int:
    from .pipeline import Humanizer, RefusedError

    text = _read(args.input)
    voice = None
    if args.voice:
        voice = VoiceProfile.load(args.voice) if args.voice.endswith(".json") else build_profile(_read(args.voice))

    try:
        result = Humanizer().humanize(text, mode=args.mode, voice=voice,
                                      on_step=lambda m: print(m, file=sys.stderr))
    except RefusedError as e:
        print(e, file=sys.stderr)
        return 2

    _print_report(result.before, "Before")
    _print_report(result.after, "After ")
    if result.voice_distance is not None:
        print(f"Voice distance: {result.voice_distance} (0 = matches your sample)", file=sys.stderr)
    if result.fact_issues:
        print("Unresolved meaning changes, check these by hand:", file=sys.stderr)
        for i in result.fact_issues:
            print(f"  - {i['kind']}: {i['explanation']}", file=sys.stderr)

    if args.diff:
        sys.stdout.writelines(difflib.unified_diff(
            text.splitlines(keepends=True), (result.text + "\n").splitlines(keepends=True),
            "original", "humanized"))
    elif args.in_place and args.input != "-":
        Path(args.input).write_text(result.text + "\n")
        print(f"Wrote {args.input}", file=sys.stderr)
    else:
        print(result.text)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="humanize", description="Rewrite AI-sounding text so people want to read it.")
    sub = p.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("run", help="rewrite text (needs Claude API credentials)")
    h.add_argument("input", help="file path, or - for stdin")
    h.add_argument("--mode", choices=sorted(MODES), default="auto")
    h.add_argument("--voice", help="writing sample (.txt/.md) or saved profile (.json)")
    h.add_argument("--diff", action="store_true", help="print a diff instead of the text")
    h.add_argument("-i", "--in-place", action="store_true", help="overwrite the input file")
    h.set_defaults(func=cmd_humanize)

    s = sub.add_parser("scan", help="list tells without calling a model")
    s.add_argument("input", help="file path, or - for stdin")
    s.set_defaults(func=cmd_scan)

    v = sub.add_parser("profile", help="build a voice profile from your own writing")
    v.add_argument("samples", nargs="+")
    v.add_argument("-o", "--out", default="voice.json")
    v.set_defaults(func=cmd_profile)

    w = sub.add_parser("web", help="open the web app")
    w.add_argument("--host", default="127.0.0.1")
    w.add_argument("--port", type=int, default=8765)
    w.set_defaults(func=lambda a: __import__("humanizer.web.server", fromlist=["serve"]).serve(a.host, a.port) or 0)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
