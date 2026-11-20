# Humanizer

Rewrites AI-sounding text so people want to read it, without changing what it says.

The pattern list builds on [blader/humanizer](https://github.com/blader/humanizer) and Wikipedia's
[Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing). The difference is that this
is a program, not one prompt:

1. **Scan.** A rule-based detector (`humanizer/detector.py`) finds tells and measures rhythm: sentence-length
   spread, dashes, triads, fragment rows. It needs no model and no network.
2. **Rewrite.** Claude rewrites the text, given the exact tells found, the kind of text, and your voice profile.
3. **Fact-check.** A separate Claude call compares the original and the rewrite, and lists any fact that was
   dropped, changed, or added.
4. **Rescan and revise.** If facts changed or strong tells survived, Claude revises the draft. It does this up to two times.

## Setup

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

Set `ANTHROPIC_API_KEY` to use the `run` command. The `scan` and `profile` commands work without a key.

## Use

```bash
humanize scan draft.md                      # list tells, no model call
humanize run draft.md                       # print the rewrite
humanize run draft.md --mode business --diff
humanize profile my-posts/*.md -o voice.json
humanize run draft.md --voice voice.json -i # rewrite in your voice, in place
```

Modes: `auto`, `essay`, `academic`, `abstract`, `review`, `proposal`, `personal`, `social`, `technical`, `business`,
`marketing`, `casual`.

## Web app

```bash
humanize web            # then open http://127.0.0.1:8765
```

Paste a draft and the report updates as you type: a machine score, sentence rhythm, every tell highlighted in place
(click one to see why), and the citations and figures that will be locked. Humanize streams each step, then shows
the rewrite as separate changes you can keep or revert one by one, in a clean or tracked-changes view.

Built for research writing:

- **Locked citations and figures.** `(Smith & Lee, 2019)`, `Twenge (2017)`, `[3, 5]`, DOIs, arXiv ids, `p < .001`,
  `N = 212`, `95% CI [1.2, 3.4]` are passed to the model as must-keep marks and checked after each draft. A lost or
  altered mark triggers a revision, and anything still missing is flagged.
- **Protected terms** that must survive unchanged (discipline terms, instrument names).
- **Keep length** within 10%, on by default for academic modes; US or UK spelling; light, balanced, or deep edits.
- **Your voice.** Paste your own earlier writing and the rewrite matches its sentence length, rhythm, and habits.
- **Long documents** are split at paragraph breaks and edited in parallel, up to about 20,000 words.

The API is a FastAPI app (`humanizer/api.py`) that reads `ANTHROPIC_API_KEY` from the environment or a `.env` file. See [DEPLOY.md](DEPLOY.md) to put it online (FastAPI Cloud for the API, Vercel for the site).

## AI detectors

Humanizer edits for human readers. Text with fewer AI tells usually also scores as more human on detectors, but
Humanizer does not target any detector. It does not add typos, random synonyms, invisible characters, or other
tricks meant to fool one.

## Tests

```bash
.venv/bin/pytest
```

## Next steps

- An eval set: a few hundred AI texts across kinds of writing, scored on tells left, facts kept, voice distance,
  and blind reader preference.
- Periodic mining of new tells by comparing current model output with human writing.
