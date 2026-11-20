from humanizer.detector import detect
from humanizer.voice import build_profile, voice_distance

AI = (
    "I'm thrilled to announce that shared drafts are finally here! 🚀 For months, our own team was drowning in "
    "files named final_v7.docx — and we knew there had to be a better way. It's not just a feature; it's a whole "
    "new way to collaborate. And the best part? It's available today on every plan. Let that sink in."
)
HUMAN = (
    "Shared drafts are out today. For months our own team passed around files named final_v7.docx, and we got "
    "sick of it. Now two people can edit the same doc at once and see each other's changes as they type. "
    "It's free on every plan."
)


def rules(text, **kw):
    return {h.rule for h in detect(text, **kw).hits}


def test_finds_strong_tells():
    assert {"not_x_but_y", "runup", "closer", "dash", "emoji"} <= rules(AI)


def test_clean_text_scores_low():
    ai, human = detect(AI), detect(HUMAN)
    assert human.score < 10 < ai.score
    assert not human.hits


def test_ignores_code_and_urls():
    assert not detect("Run `delve --showcase` or see https://example.com/pivotal-landscape.").hits


def test_dashes_allowed_by_voice():
    assert "dash" not in rules("The plan — if it works — ships Friday.", allow_dashes=True)


def test_chatbot_residue():
    assert "chatbot" in rules("Great question! The answer is 4. I hope this helps!")


def test_voice_distance_self_is_zero():
    sample = "I write short. Then I write a much longer sentence that wanders a bit, because I can. Done."
    assert voice_distance(build_profile(sample), sample) == 0
