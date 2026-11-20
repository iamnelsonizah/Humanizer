# Humanize eval

Measures whether `Humanizer.humanize` removes AI tells without changing what the text says.

## Cases

`cases.jsonl`, one JSON object per line:

| field | meaning |
|---|---|
| `id` | unique, path-safe |
| `kind` | `ai` (should be rewritten) or `human` (a control that should come back nearly unchanged) |
| `mode` | passed to the pipeline (`auto`, `personal`, `technical`, `business`, ...) |
| `tags` | `tags[0]` is the kind of text; later tags show the source (`user-seed`, `synthetic`, `public-example`) |
| `text` | the input |
| `reference` | optional good rewrite, used only by the oracle check |

## Metrics

- **pass**: the headline. AI case: no material fact change, scanner score at most 15, and no strong tells left.
  Control: no material fact change, word similarity at least 0.80, and the scanner score did not go up.
- **facts_kept**: the judge (Claude Sonnet 5.5) found no material dropped, changed, or added fact.
- **tells_cleared**: the share of the scanner score removed (AI cases). For controls, 1 if no tells were added.
- **similarity**: word-level similarity to the input. Shown for information. It only counts toward pass on controls.

## Run

```bash
.venv/bin/python -m evals.run --app oracle --no-judge   # offline: reference rewrites, expect ~100%
.venv/bin/python -m evals.run --app null --no-judge     # offline: input returned as-is, expect only controls to pass
.venv/bin/python -m evals.run --limit 5                 # paid pilot
.venv/bin/python -m evals.run --reps 2                  # full baseline
```

The first paid run stops until you review the harness files and pass `--approve-harness`. Any later edit to the
runner, grader, cases, or pipeline asks for approval again.

Output goes to `.claude/hillclimb/humanize/<variant>/`. Failed attempts go to `errors.jsonl` with a failure class
and are never scored as zero.
