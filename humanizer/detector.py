"""Rule-based detector for AI writing tells.

It needs no model and no network, so it is fast, free, and gives the same
answer every time. The pipeline runs it before and after each rewrite.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

# Strength: 3 = act on one sighting, 2 = usual tell, 1 = weak alone.
STRONG, MEDIUM, WEAK = 3, 2, 1


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    strength: int
    pattern: re.Pattern
    advice: str


def _rx(*phrases: str) -> re.Pattern:
    return re.compile("|".join(phrases), re.IGNORECASE | re.MULTILINE)


def _words(*words: str) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)


RULES: list[Rule] = [
    Rule("not_x_but_y", "Not X but Y", STRONG, _rx(
        r"\bnot\s+(?:just|only|merely|simply)\b[^.!?\n]{1,90}?\bbut\b",
        r"\b(?:it'?s|it is|this is|that'?s|that is)\s+not\s+(?:just\s+|only\s+|merely\s+|about\s+)?[^.!?;\n]{1,60}?[;,—–]\s*(?:it'?s|it is|this is|but)\b",
        r"\bdo(?:es)?(?:n'?t| not) mean\b[^.!?\n]{1,100}[.!]\s+It means\b",
        r"\bisn'?t (?:just )?(?:a|an|about)\b[^.!?\n]{1,60}?[;,—–]\s*it'?s\b",
        r"\b(?:isn'?t|is not|wasn'?t|was not) (?:just|only|merely|simply) [^.!?\n]{1,80}[.!]\s+(?:It|This|That)(?:'s| is| was)\b",
        r"\b(?:it'?s|it is|this is|that'?s|is|was) (?:much |so |far )?more than (?:just )?(?:a |an )?[^.!?;\n]{1,50}?[;,—–]\s*(?:it'?s|it is|this is)\b",
    ), "State the point directly. Keep a contrast only if the negative half corrects a real belief."),
    Rule("closer", "One-line closer", STRONG, _rx(
        r"\blet that sink in\b", r"\bread that again\b", r"\bthat(?:'s| is) the real win\b",
        r"\bthat distinction matters\b", r"\bmake no mistake\b", r"\band that changes everything\b",
        r"\bthe message was clear\b", r"\bthis shows the importance of\b", r"\bthe lesson\?",
        r"\b(?:every|each)\.\s+single\.\s+\w+\.",
    ), "Cut the closer, or replace it with a new fact or consequence."),
    Rule("deep_saying", "Saying that sounds deep", STRONG, _rx(
        r"\bat its core\b", r"\bthe real question is\b", r"\bwhat (?:really|truly) matters\b",
        r"\bthe heart of the matter\b", r"\bthe deeper issue\b", r"\bfundamentally,",
        r"\bis the (?:language|currency|architecture) of\b",
    ), "Replace the saying with the specific claim."),
    Rule("runup", "Staged run-up", STRONG, _rx(
        r"\blet(?:'?s| us) (?:dive|delve) (?:in|into)\b", r"\blet(?:'?s| us) (?:explore|break (?:this|it) down|unpack)\b",
        r"\bhere'?s (?:the thing|what you need to know|the kicker|the catch)\b", r"\bthe thing is[,:]",
        r"(?:^|[.!?]\s+)honestly\?", r"\breal talk\b", r"\blet'?s be honest\b", r"\bwithout further ado\b",
        r"\bthe (?:hard|tricky|interesting|best|new|real) part(?: is|\?)",
        r"(?:^|[.!?]\s+)(?:the result|the answer|the catch|the twist)\?",
    ), "Remove the run-up and make the point."),
    Rule("strawman", "Arguing with no one", STRONG, _rx(
        r"\bthis (?:isn'?t|is not) (?:mainly |just |really )?about\b", r"\bi'?m not saying\b",
        r"\bdon'?t get me wrong\b", r"\bthis is not to say\b", r"\ba tempting approach would be\b",
        r"\bone might be tempted\b", r"\byou might think\b[^.!?\n]{0,80}\bbut\b",
    ), "Remove the defense against an objection nobody raised."),
    Rule("ai_words", "Overused AI word", MEDIUM, _words(
        "delve", "delves", "delving", "tapestry", "testament", "underscores?", "underscoring",
        "showcas(?:e|es|ing)", "pivotal", "intricate", "intricacies", "meticulous(?:ly)?",
        "bolstered", "garner(?:ed|s)?", "interplay", "vibrant", "seamless(?:ly)?",
        "leveraging", "leverages? (?:the|our|your|its|their|this)", "realm", "navigat(?:e|ing) the", "ever-evolving", "game-changer",
        "elevate", "unlock(?:s|ing)? the", "harness(?:es|ing)? the power", "embark(?:s|ing)?",
        "landscape", "multifaceted", "nuanced", "paramount", "foster(?:s|ing)?",
    ), "Use a plain word."),
    Rule("inflated", "Inflated significance", MEDIUM, _rx(
        r"\bstands as a (?:testament|symbol|reminder)\b", r"\ba (?:pivotal|crucial|defining) moment\b",
        r"\bplays? an? (?:key|crucial|vital|pivotal|important) role\b", r"\bevolving landscape\b",
        r"\bindelible mark\b", r"\bthe future looks bright\b", r"\bexciting times (?:lie )?ahead\b",
        r"\bsetting the stage for\b", r"\b(?:enduring|lasting) legacy\b", r"\breflects a broader\b",
        r"\bmarking a (?:new|significant|pivotal)\b", r"\bdespite (?:these|its|the) challenges\b",
    ), "Keep the fact, drop the claim of importance."),
    Rule("sales", "Sales language", MEDIUM, _words(
        "nestled", "breathtaking", "must-visit", "must-see", "stunning", "renowned",
        "in the heart of", "diverse array", "rich (?:cultural )?heritage", "hidden gem",
        "world-class", "cutting-edge", "state-of-the-art", "unparalleled",
        "unforgettable", "stole my heart", "truly special", "simply divine", "iconic", "panoramic",
        "national treasure", "capture the magic", "timeless charm", "perfect harmony", "labor of love",
    ), "Say what the thing is."),
    Rule("borrowed_authority", "Borrowed authority", MEDIUM, _rx(
        r"\bexperts (?:believe|argue|say|agree|suggest)\b", r"\bstudies (?:show|suggest|have shown)\b",
        r"\bindustry reports\b", r"\bobservers have (?:noted|cited)\b", r"\bresearch (?:shows|suggests)\b",
    ), "Name the source and what it said, or cut the claim."),
    Rule("copula_avoidance", "Avoiding is/has", MEDIUM, _words(
        "serves as", "stands as", "functions as", "boasts", "boasting",
    ), "Use is, are, or has."),
    Rule("chatbot", "Chatbot residue", STRONG, _rx(
        r"\bgreat question\b", r"\bi hope this helps\b", r"(?:^|\n)\s*(?:certainly|of course|absolutely)!",
        r"\blet me know if you(?:'d| would) like\b", r"\bwould you like me to\b", r"\bfeel free to\b",
        r"\byou'?re absolutely right\b", r"(?:^|\n)\s*here(?:'s| is) (?:a|an|the) (?:\w+ )?(?:overview|summary|breakdown)\b",
    ), "Remove the chat wrapper, keep the content."),
    Rule("stock_phrase", "Stock filler phrase", MEDIUM, _rx(
        r"\bi hope this (?:email|message|note) finds you well\b", r"\b(?:please )?don'?t hesitate to (?:reach out|contact)\b",
        r"\bit(?:'s| is) (?:important|worth) (?:to note|noting)\b", r"\bplease note that\b",
        r"\b(?:i am|i'?m|we are|we'?re) (?:so |incredibly |really )?(?:thrilled|excited|delighted) to\b", r"\bi(?:'m| am) confident that\b",
        r"\b(?:we|i) (?:truly|sincerely|really) (?:value|appreciate)\b", r"\bdynamic team\b",
        r"\bspearhead(?:ed|ing)?\b", r"\bchampion(?:ed|ing) best practices\b", r"\bcommitment to (?:innovation|excellence)\b",
        r"\byour satisfaction is our top priority\b", r"\bwe understand how frustrating\b",
        r"\bi completely understand\b", r"\bi(?:'ve| have) gone ahead and\b", r"\bas a token of our appreciation\b",
        r"\bthis report provides a comprehensive\b", r"\btaken together\b", r"\bholds the potential to\b",
        r"\bmake a meaningful impact\b", r"\b(?:seeks|aims) to address a critical gap\b", r"\bworth every penny\b",
        r"\bthank you for your (?:time and consideration|continued support)\b", r"\bkey takeaways\b",
    ), "Cut the stock phrase or say the specific thing."),
    Rule("knowledge_limit", "Knowledge-limit disclaimer", STRONG, _rx(
        r"\bas of my (?:last|latest) (?:training|knowledge|update)\b", r"\bbased on (?:the )?available information\b",
        r"\bnot (?:widely|extensively|publicly) (?:documented|available|disclosed)\b",
        r"\bwhile specific details (?:are|remain) (?:limited|scarce)\b",
    ), "Say what the source does not show, or cut the sentence."),
    Rule("hedge_stack", "Stacked qualifiers", WEAK, _rx(
        r"\bcould potentially\b", r"\bmight arguably\b", r"\bmay possibly\b", r"\bit(?:'s| is) (?:also )?possible that\b[^.]{0,40}\bmight\b",
    ), "Keep only the qualifiers the source supports."),
    Rule("bold_label", "Bold label list", MEDIUM, _rx(
        r"^\s*(?:[-*•]|\d+\.)\s+\*\*[^*\n]{1,40}:?\*\*:?",
    ), "Drop the bold labels; turn the list into prose if the labels add nothing."),
    Rule("emoji", "Decorative emoji or arrow", MEDIUM, re.compile(
        r"[\U0001F300-\U0001FAFF✨✅❌⭐→➡]",
    ), "Remove decorative emoji and arrows."),
    Rule("curly_quotes", "Curly quotes", WEAK, re.compile("[“”‘’]"),
         "Use straight quotes unless the target format curls them."),
]

AI_WORD_RULES = {"ai_words"}
DASH_RX = re.compile(r"[—–]|\s--\s")
TRIAD_RX = re.compile(r"\b[\w'-]+(?: [\w'-]+)?, [\w'-]+(?: [\w'-]+)?,? and [\w'-]+\b", re.IGNORECASE)
SENT_SPLIT = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9])")
CODE_RX = re.compile(r"```.*?```|`[^`\n]+`|https?://\S+", re.DOTALL)
WORD_RX = re.compile(r"[A-Za-z][A-Za-z'-]*")


@dataclass
class Hit:
    rule: str
    name: str
    strength: int
    text: str
    start: int
    end: int
    advice: str


@dataclass
class Stats:
    words: int
    sentences: int
    mean_sentence_len: float
    sentence_len_cv: float          # spread of sentence lengths; flat rhythm reads as machine-made
    dashes_per_1k: float
    triads_per_1k: float
    contractions_per_1k: float
    fragment_rows: int              # runs of 3+ very short sentences
    one_line_paragraph_share: float


@dataclass
class Report:
    hits: list[Hit] = field(default_factory=list)
    stats: Stats | None = None
    score: float = 0.0              # 0 = no tells found, 100 = saturated

    def by_rule(self) -> dict[str, list[Hit]]:
        out: dict[str, list[Hit]] = {}
        for h in self.hits:
            out.setdefault(h.rule, []).append(h)
        return out

    def strong_hits(self) -> list[Hit]:
        return [h for h in self.hits if h.strength == STRONG]


def _mask_code(text: str) -> str:
    """Blank out code and URLs so rules do not fire inside them. Offsets stay the same."""
    return CODE_RX.sub(lambda m: " " * len(m.group()), text)


def split_sentences(text: str) -> list[str]:
    out = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if para:
            out.extend(s.strip() for s in SENT_SPLIT.split(para) if s.strip())
    return out


def compute_stats(text: str) -> Stats:
    clean = _mask_code(text)
    words = WORD_RX.findall(clean)
    n = max(len(words), 1)
    sents = split_sentences(clean)
    lens = [len(WORD_RX.findall(s)) for s in sents] or [0]
    mean = statistics.fmean(lens)
    cv = (statistics.pstdev(lens) / mean) if mean and len(lens) > 1 else 0.0

    rows, run = 0, 0
    for ln in lens:
        run = run + 1 if 0 < ln <= 4 else 0
        if run == 3:
            rows += 1

    # Skip headings, lists, tables, and short lines such as greetings and sign-offs ("Thanks,\nSam").
    paras = [p for p in re.split(r"\n\s*\n", clean) if len(WORD_RX.findall(p)) >= 6
             and not p.lstrip().startswith(("#", "-", "*", "|"))]
    one_line = sum(1 for p in paras if len(split_sentences(p)) == 1)

    per_k = 1000 / n
    return Stats(
        words=len(words),
        sentences=len(sents),
        mean_sentence_len=round(mean, 1),
        sentence_len_cv=round(cv, 2),
        dashes_per_1k=round(len(DASH_RX.findall(clean)) * per_k, 1),
        triads_per_1k=round(len(TRIAD_RX.findall(clean)) * per_k, 1),
        contractions_per_1k=round(sum(1 for w in words if "'" in w) * per_k, 1),
        fragment_rows=rows,
        one_line_paragraph_share=round(one_line / len(paras), 2) if len(paras) >= 3 else 0.0,
    )


def detect(text: str, *, allow_dashes: bool = False) -> Report:
    """Find tells in `text`. Set allow_dashes when the writer's own sample uses dashes."""
    clean = _mask_code(text)
    hits: list[Hit] = []
    for rule in RULES:
        for m in rule.pattern.finditer(clean):
            hits.append(Hit(rule.id, rule.name, rule.strength, text[m.start():m.end()].strip(),
                            m.start(), m.end(), rule.advice))

    stats = compute_stats(text)
    if not allow_dashes:
        for m in DASH_RX.finditer(clean):
            strength = MEDIUM if stats.dashes_per_1k >= 5 else WEAK
            hits.append(Hit("dash", "Dash as connector", strength, text[max(0, m.start() - 20):m.end() + 20].strip(),
                            m.start(), m.end(), "Use a period, comma, colon, or parentheses."))
    if stats.triads_per_1k >= 8:
        for m in TRIAD_RX.finditer(clean):
            hits.append(Hit("triad", "Forced triad", WEAK, m.group(), m.start(), m.end(),
                            "Use the number of items the meaning needs."))

    hits.sort(key=lambda h: (-h.strength, h.start))
    return Report(hits=hits, stats=stats, score=_score(hits, stats))


def _score(hits: list[Hit], stats: Stats) -> float:
    """A rough 0-100 measure of how many tells the text carries, per 100 words."""
    weight = sum({STRONG: 4.0, MEDIUM: 2.0, WEAK: 0.5}[h.strength] for h in hits)
    weight += 3.0 * stats.fragment_rows
    # Flat rhythm is a soft signal: careful human prose can be even too, so it weighs little.
    if stats.sentences >= 6 and stats.sentence_len_cv < 0.25:
        weight += 2.0
    if stats.one_line_paragraph_share >= 0.4:
        weight += 3.0
    per_100 = weight * 100 / max(stats.words, 50)
    return round(min(100.0, per_100 * 5), 1)
