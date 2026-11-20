"""Voice profiles: measure how a writer writes, then measure how close a rewrite comes."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from .detector import WORD_RX, compute_stats, split_sentences


@dataclass
class VoiceProfile:
    mean_sentence_len: float
    sentence_len_cv: float
    dashes_per_1k: float
    contractions_per_1k: float
    first_person_per_1k: float
    question_share: float
    common_openers: list[str]
    excerpt: str                    # a short passage the model can imitate

    @property
    def uses_dashes(self) -> bool:
        return self.dashes_per_1k >= 2.0

    def describe(self) -> str:
        return (
            f"- Average sentence length: {self.mean_sentence_len} words (spread {self.sentence_len_cv}; "
            "higher means more mixed short and long sentences)\n"
            f"- Contractions per 1,000 words: {self.contractions_per_1k}\n"
            f"- First-person words per 1,000 words: {self.first_person_per_1k}\n"
            f"- Dashes per 1,000 words: {self.dashes_per_1k}\n"
            f"- Share of sentences that are questions: {self.question_share}\n"
            f"- Frequent sentence openers: {', '.join(self.common_openers) or 'none'}"
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "VoiceProfile":
        return cls(**json.loads(Path(path).read_text()))


FIRST_PERSON = {"i", "i'm", "i've", "i'd", "i'll", "me", "my", "mine", "we", "we're", "our", "us"}


def build_profile(sample: str) -> VoiceProfile:
    s = compute_stats(sample)
    words = [w.lower() for w in WORD_RX.findall(sample)]
    n = max(len(words), 1)
    sents = split_sentences(sample)
    openers = Counter(WORD_RX.findall(x)[0].lower() for x in sents if WORD_RX.findall(x))
    return VoiceProfile(
        mean_sentence_len=s.mean_sentence_len,
        sentence_len_cv=s.sentence_len_cv,
        dashes_per_1k=s.dashes_per_1k,
        contractions_per_1k=s.contractions_per_1k,
        first_person_per_1k=round(sum(w in FIRST_PERSON for w in words) * 1000 / n, 1),
        question_share=round(sum(x.rstrip().endswith("?") for x in sents) / max(len(sents), 1), 2),
        common_openers=[w for w, c in openers.most_common(5) if c > 1],
        excerpt=sample.strip()[:1500],
    )


def voice_distance(profile: VoiceProfile, text: str) -> float:
    """0 means the text matches the profile's numbers; around 1 means far off."""
    p = build_profile(text)
    pairs = [
        (profile.mean_sentence_len, p.mean_sentence_len, 10.0),
        (profile.sentence_len_cv, p.sentence_len_cv, 0.4),
        (profile.contractions_per_1k, p.contractions_per_1k, 30.0),
        (profile.first_person_per_1k, p.first_person_per_1k, 40.0),
        (profile.dashes_per_1k, p.dashes_per_1k, 8.0),
    ]
    return round(sum(min(abs(a - b) / scale, 1.0) for a, b, scale in pairs) / len(pairs), 2)
