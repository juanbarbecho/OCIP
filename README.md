# OCIP
Python notebooks for data tasks from my time at the CUNY Office of Career and Industry Partnerships (OCIP).

## Layout

- `notebooks/` — the analysis notebooks (match outcomes, rematches, application data validation).
- `data/` — raw exports the notebooks read from (InPlace/Airtable CSVs). **Gitignored** — these contain student-identifying data and must never be committed. Populate this folder locally with your own exports before running a notebook.
- `outputs/` — generated reports meant to be shared (e.g. the matching outcomes write-up). Only aggregate, non-identifying content belongs here.

## One-time setup

Notebooks are committed with cell outputs stripped automatically, so results printed while you work locally (which can include per-student rows) never end up in git history. This requires a one-time local git config per clone:

```
tools/setup_git_filters.sh
```

After running it, `git add`/`git commit` will strip notebook outputs from what's stored in git — your local `.ipynb` files on disk are untouched, so you still see your results while working.
