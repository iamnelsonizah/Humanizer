"""Pipeline control flow, with a fake client in place of the Claude API."""

import json
from types import SimpleNamespace

from humanizer.pipeline import Humanizer

ORIGINAL = "It's not just a tool; it's a movement. It costs $5. Let that sink in."


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self.replies.pop(0)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


def make(replies):
    msgs = FakeMessages(replies)
    client = SimpleNamespace(beta=SimpleNamespace(messages=msgs))
    return Humanizer(client=client), msgs


def test_clean_first_draft_needs_no_revision():
    h, msgs = make(["The tool costs $5.", json.dumps({"issues": []})])
    r = h.humanize(ORIGINAL)
    assert r.text == "The tool costs $5." and r.revisions == 0
    assert len(msgs.calls) == 2
    assert msgs.calls[1]["output_config"]["format"]["type"] == "json_schema"


def test_dropped_fact_triggers_revision():
    issue = {"kind": "dropped", "original": "$5", "rewrite": "", "explanation": "Price lost."}
    h, msgs = make([
        "The tool is useful.",
        json.dumps({"issues": [issue]}),
        "The tool costs $5.",
        json.dumps({"issues": []}),
    ])
    r = h.humanize(ORIGINAL)
    assert r.text == "The tool costs $5." and r.revisions == 1 and not r.fact_issues
    assert "Price lost." in msgs.calls[2]["messages"][0]["content"]
