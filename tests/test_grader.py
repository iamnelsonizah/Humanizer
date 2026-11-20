"""Grader logic with a fake judge client."""

import json
from types import SimpleNamespace

from evals import grader

CASE = {"id": "t", "kind": "ai", "text": "It's not just a tool; it's a movement. It costs $5. Let that sink in."}


class FakeJudge:
    def __init__(self, facts, style):
        self.replies = [facts, style]
        self.beta = SimpleNamespace(messages=self)

    def create(self, **kw):
        usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                                cache_creation_input_tokens=0)
        return SimpleNamespace(model=kw["model"], stop_reason="end_turn", usage=usage,
                               content=[SimpleNamespace(type="text", text=json.dumps(self.replies.pop(0)))])


def test_clear_tell_from_judge_fails_case():
    style = {"remaining": [{"category": "hype", "severity": "clear", "quote": "game changer"}], "voice_lost": []}
    g = grader.grade(CASE, "The tool is a game changer and costs $5.", FakeJudge({"issues": []}, style))
    assert g["grade"]["style_clean"] == 0 and g["grade"]["pass"] == 0
    assert g["judge_usage"]["input_tokens"] == 20


def test_hallucinated_quote_is_dropped():
    style = {"remaining": [{"category": "hype", "severity": "clear", "quote": "breathtaking views"}], "voice_lost": []}
    g = grader.grade(CASE, "The tool costs $5.", FakeJudge({"issues": []}, style))
    assert g["grade"]["style_clean"] == 1 and g["grade"]["pass"] == 1
    assert "dropped" in g["explanation"]["style_clean"]


def test_borderline_items_do_not_fail():
    style = {"remaining": [{"category": "filler", "severity": "borderline", "quote": "costs"}], "voice_lost": []}
    assert grader.grade(CASE, "The tool costs $5.", FakeJudge({"issues": []}, style))["grade"]["pass"] == 1
