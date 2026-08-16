# OCIP
Python notebooks for data tasks from my time at the CUNY Office of Career and Industry Partnerships (OCIP).

## Layout

`notebooks/` is organized into three projects, grouped by what they actually read/write, not
by when they were added:

- **`notebooks/matching/`** — live seasonal match/placement analysis for the current Career
  Launch (CL26) and Spring Forward (SF26) cycles: match outcomes, rematches, application data
  validation.
- **`notebooks/PreP/`** — pre-program survey stats, self-contained (own data file, own charts).
- **`notebooks/shoutoutdeckfigures/`** — payroll/stipend figures for stakeholder decks,
  self-contained.
- **`notebooks/industry_growth_analysis/`** — the historical (2022-2026, all hubs) pipeline
  that classifies internship postings by federal NAICS/SOC code and compares our placement mix
  against citywide BLS QCEW employment trends: `role_classification/` (NIOCCS coding),
  `cultural_corp_ingestion/` (brings Cultural Corps into the same pipeline),
  `public_data_fetch/` (QCEW pull), `placement_join/` (the current ground-truth comparison +
  a validation gate), `to_excel/` (stakeholder workbook), plus `employernums.ipynb` and
  `tag_education_requirements.ipynb`. See `data/README.md` for how the intermediate CSVs in
  this chain relate to each other.

Other top-level folders:

- `data/` — raw exports and pipeline-derived CSVs the notebooks read from and write to
  (InPlace/Airtable/BLS). **Gitignored** — these contain student-identifying data and must
  never be committed. Populate this folder locally with your own exports before running a
  notebook. See `data/README.md` for the file lineage.
- `outputs/` — generated reports meant to be shared (e.g. the matching outcomes write-up, the
  sector-detail workbook), organized into the same per-project subfolders as `notebooks/`. Only
  aggregate, non-identifying content belongs here.
- `tools/` — shared code imported by notebooks, not run as its own analysis:
  - `paths.py` — every notebook starts with a small bootstrap cell that locates the repo root
    and adds it to `sys.path`, then imports `data_path()` / `outputs_path()` from here instead
    of hardcoding a `../` hop-count. This is what keeps notebook paths working regardless of
    how deeply a notebook is nested — write any new notebook the same way.
  - `nioccs_classify.py` — the reusable NAICS/SOC classification engine (role title +
    description + industry label -> federal industry/occupation codes via the CDC NIOCCS API).
    Any new placement dataset can run through `classify_dataframe()`/`classify_csv()` here
    without rebuilding the coding logic.

## One-time setup

Notebooks are committed with cell outputs stripped automatically, so results printed while you work locally (which can include per-student rows) never end up in git history. This requires a one-time local git config per clone:

```
tools/setup_git_filters.sh
```

After running it, `git add`/`git commit` will strip notebook outputs from what's stored in git — your local `.ipynb` files on disk are untouched, so you still see your results while working.
