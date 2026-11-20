"""Citation locking and the per-change diff the web app uses."""

from humanizer.citations import find_marks, missing_marks
from humanizer.web.server import hunks, split_chunks

TEXT = ("Prior work (Smith & Lee, 2019; Wong et al., 2021, p. 4) shows this. Furthermore, Twenge (2017) disagreed [3, 5]. "
        "The effect was large, r = .43, p < .001, N = 212, 95% CI [1.2, 3.4]. See 10.1038/s41586-020-2649-2.")


def test_finds_citations_and_figures():
    found = {m.text for m in find_marks(TEXT)}
    assert "(Smith & Lee, 2019; Wong et al., 2021, p. 4)" in found
    assert "Twenge (2017)" in found            # not "Furthermore, Twenge (2017)"
    assert {"[3, 5]", "p < .001", "N = 212", "95% CI [1.2, 3.4]", "10.1038/s41586-020-2649-2"} <= found


def test_missing_marks_ignores_spacing_but_catches_changes():
    assert missing_marks(TEXT, TEXT.replace("[3, 5]", "[3,5]")) == []
    lost = missing_marks(TEXT, TEXT.replace("N = 212", "N = 213"))
    assert [m.text for m in lost] == ["N = 212"]


def test_hunks_rebuild_both_sides():
    a = "It is not just a tool; it is a movement. It costs $5.\n\nLet that sink in. Second paragraph."
    b = "The tool costs $5.\n\nSecond paragraph."
    hs = hunks(a, b)
    assert "".join(h["s"] if h["t"] == "eq" else h["a"] for h in hs) == a
    assert "".join(h["s"] if h["t"] == "eq" else h["b"] for h in hs) == b
    assert sum(h["t"] == "ch" for h in hs) >= 2


def test_split_chunks_keeps_text():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 300 for i in range(5))
    chunks = split_chunks(text, limit=700)
    assert len(chunks) > 1
    assert "".join(c + sep for c, sep in chunks) == text
