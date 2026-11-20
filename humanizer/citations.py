"""Find citations and other marks a rewrite must carry over exactly.

Researchers lose trust in a humanizer the first time it drops "(Nguyen et al., 2021, p. 14)" or turns [12] into
[13]. This module pulls those marks out of the original so the pipeline can check every one survived.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

_NAME = r"[A-Z][A-Za-z'’\-]+(?:\s(?:van|von|de|da|del|der|di|le|la)\s[A-Z][A-Za-z'’\-]+)?"
_AUTHORS = rf"{_NAME}(?:(?:,\s|\s(?:and|&)\s){_NAME})*(?:,?\s(?:et al\.?))?"
_YEAR = r"(?:1[6-9]\d\d|20\d\d)[a-z]?|n\.d\.|in press|forthcoming"
_LOCATOR = r"(?:,\s*(?:pp?\.|ch\.|para\.|sec\.|§)\s*[\dA-Za-z–\-]+)?"

PATTERNS: list[tuple[str, re.Pattern]] = [
    # (Smith, 2020) (Smith & Lee, 2019a; Wong et al., 2021, p. 4) (see Smith, 2020)
    ("author-year", re.compile(
        rf"\((?:(?:see|e\.g\.,?|cf\.|i\.e\.,?)\s)?{_AUTHORS},?\s(?:{_YEAR}){_LOCATOR}"
        rf"(?:;\s(?:{_AUTHORS},?\s)?(?:{_YEAR}){_LOCATOR})*\)")),
    # Smith (2020)  Smith and Lee (2019, p. 3)
    ("narrative", re.compile(rf"\b{_NAME}(?:\s(?:and|&)\s{_NAME})?(?:\set al\.?)?\s\((?:{_YEAR}){_LOCATOR}\)")),
    ("interval", re.compile(r"\b\d{2}(?:\.\d)?%\s?(?:CI|confidence interval)\s?[\[(]\s?-?\d*\.?\d+\s?[,–\-]\s?-?\d*\.?\d+\s?[\])]")),
    # [1]  [2, 5]  [3–7]  [Smi20]
    ("numeric", re.compile(r"\[(?:\d+(?:\s*[–\-,]\s*\d+)*|[A-Z][a-z]{1,3}\d{2}[a-z]?)\]")),
    ("doi", re.compile(r"\b10\.\d{4,9}/[^\s\"<>)\]]+[^\s\"<>)\].,;]")),
    ("arxiv", re.compile(r"\barXiv:\s?\d{4}\.\d{4,5}(?:v\d+)?\b", re.IGNORECASE)),
    # Statistics researchers cannot afford to see reworded: p < .05, r = .43, N = 212, 95% CI [1.2, 3.4]
    ("statistic", re.compile(
        r"\b(?:p|r|t|F|N|n|M|SD|SE|d|β|R²|R2|χ²|OR|HR|CI)\s?(?:\(\d+(?:,\s?\d+)?\))?\s?[=<>≤≥]\s?-?\d*\.?\d+%?")),
]


@dataclass
class Mark:
    kind: str
    text: str
    start: int
    end: int


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s.replace("’", "'").replace("–", "-"))


def find_marks(text: str) -> list[Mark]:
    marks: list[Mark] = []
    taken: list[tuple[int, int]] = []
    for kind, rx in PATTERNS:
        for m in rx.finditer(text):
            if any(m.start() < e and s < m.end() for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            marks.append(Mark(kind, m.group(), m.start(), m.end()))
    marks.sort(key=lambda m: m.start)
    return marks


def missing_marks(original: str, rewrite: str) -> list[Mark]:
    """Marks in the original that do not appear, character for character (bar spacing), in the rewrite."""
    have = Counter(_norm(m.text) for m in find_marks(rewrite))
    # Marks can be legally regrouped, so also accept a mark found verbatim anywhere in the rewrite.
    flat = _norm(rewrite)
    lost: list[Mark] = []
    for m in find_marks(original):
        key = _norm(m.text)
        if have[key] > 0:
            have[key] -= 1
        elif key not in flat:
            lost.append(m)
    return lost


def missing_terms(terms: list[str], rewrite: str) -> list[str]:
    low = rewrite.lower()
    return [t for t in terms if t.strip() and t.strip().lower() not in low]
