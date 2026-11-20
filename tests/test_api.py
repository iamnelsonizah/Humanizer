"""The FastAPI layer: routes, CORS, limits, and the streamed humanize job (with a fake Claude client)."""

import json
from types import SimpleNamespace

import anthropic
import pytest
from fastapi.testclient import TestClient

from humanizer import api


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_HOUR", "0")
    monkeypatch.delenv("ACCESS_CODE", raising=False)
    api._hits.clear()
    return TestClient(api.app)


def test_scan_and_meta(client):
    r = client.post("/api/scan", json={"text": "Let's delve into the tapestry (Smith, 2020)."})
    assert r.status_code == 200 and r.json()["hits"] and r.json()["marks"][0]["text"] == "(Smith, 2020)"
    assert "academic" in client.get("/api/meta").json()["modes"]
    assert client.get("/").status_code == 200   # UI is served locally


def test_humanize_streams_result(client, monkeypatch):
    replies = ["The tool costs $5 (Smith, 2020).", json.dumps({"issues": []})]

    class Msgs:
        def create(self, **k):
            return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=replies.pop(0))])

    monkeypatch.setattr(anthropic, "Anthropic", lambda: SimpleNamespace(beta=SimpleNamespace(messages=Msgs())))
    r = client.post("/api/humanize", json={"text": "It's not just a tool; it's a movement. It costs $5 (Smith, 2020).",
                                           "mode": "academic"})
    events = [json.loads(line[6:]) for line in r.text.split("\n\n") if line.startswith("data: ")]
    result = events[-1]
    assert result["type"] == "result" and result["text"].startswith("The tool costs $5")
    assert result["marks_total"] == 1 and result["lost_marks"] == []


def test_rate_limit_and_access_code(client, monkeypatch):
    monkeypatch.setenv("ACCESS_CODE", "s3cret")
    assert client.post("/api/humanize", json={"text": "hi"}).status_code == 401
    monkeypatch.delenv("ACCESS_CODE")
    monkeypatch.setenv("RATE_LIMIT_PER_HOUR", "1")
    monkeypatch.setattr(api, "run_job", lambda payload, emit: emit({"type": "result"}))
    assert client.post("/api/humanize", json={"text": "hi"}).status_code == 200
    r = client.post("/api/humanize", json={"text": "hi"})
    assert r.status_code == 429 and "Limit" in r.json()["error"]
