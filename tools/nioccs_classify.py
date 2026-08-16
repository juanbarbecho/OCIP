#!/usr/bin/env python3
"""Code internship role titles + descriptions to federal NAICS/SOC via NIOCCS.

This is the reusable core of the NAICS (industry) / SOC (occupation) auto-
classification that has powered every sector/occupation deliverable in this
project (the coded datasets behind the QCEW comparison, the education-level
tagging, the stakeholder Excel workbook). It was rebuilt from three versions
that had drifted apart across notebooks/role_classification/RolesWithDescALL.ipynb
and notebooks/cultural_corp_ingestion/culturalcorps.ipynb — this file is now
the one canonical version; those notebooks should call into it rather than
carry their own copies.

Any dataset with a role title, a role description, and a broad industry/hub
label can be coded through the same process — nothing here is specific to
one cohort or hub, so a future placement dataset does not require rebuilding
any of this.

As a library (no file I/O, safe to call from a notebook):

    from tools.nioccs_classify import classify_dataframe
    coded = classify_dataframe(
        df,
        role_name_col="Role Name",
        role_description_col="Role Description",
        industry_col="Program Hub Category",
        id_col="Opportunity Identifier",
    )

As a standalone, resumable, checkpointed batch job over a CSV:

    python tools/nioccs_classify.py \\
        --input data/AllRoles_nioccs_ready.csv \\
        --output data/AllRoles_nioccs_coded.csv \\
        --test   # sanity-check the first few rows before committing to the full file

Output schema (one row per input row) is the same set of columns every
downstream script in this project already expects: NAICS/SOC code, title,
and match probability; insufficient-information and implausible-pairing
flags; whether a duties anchor was found in the description; whether the
description was an unfilled intake-form template (skipped, not coded); and
any API call error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from typing import Callable, Iterable, Optional

import pandas as pd
import requests

NIOCCS_BASE_URL = "https://wwwn.cdc.gov/nioccs/IOCode"
NIOCCS_REQUEST_PARAMS_STATIC = {"c": 2, "v": 18, "u": 1, "n": 1}  # n=1: top match only

# Sentinel codes NIOCCS returns to mean "insufficient information to code" —
# these are not real NAICS/SOC matches and should be flagged, not trusted.
NAICS_INSUFFICIENT_INFO_CODE = "009990"
SOC_INSUFFICIENT_INFO_CODE = "00-9900"

# Occupation text sent to the API is capped here as a safety ceiling; the
# duties-section extraction below does the real trimming. 2000 chars fits
# the 2022-2026 core-hub postings this was tuned against; sources with
# longer-form descriptions (Cultural Corps postings ran ~2,500+ chars) may
# want a higher cap passed explicitly.
DEFAULT_MAX_DESCRIPTION_CHARS = 2000

# Posting templates vary by era and program: 2024+ core-hub postings use a
# clean "DUTIES & RESPONSIBILITIES:" header; 2022-2023 and Cultural Corps
# postings use free-form paragraphs or an intake-form Q&A style instead.
# Tried in order; the first match wins.
DUTIES_ANCHOR_PATTERNS = [
    re.compile(r"duties\s*&?\s*responsibilities\s*:?", re.I),
    re.compile(r"job responsibilities and tasks\s*:?", re.I),
    re.compile(r"please provide a description of this position\s*:?", re.I),
    re.compile(r"projects?\s*&?\s*deliverables?\s*(may include)?\s*:?", re.I),
    re.compile(r"position overview\s*:?", re.I),
    re.compile(r"responsibilities\s*:?", re.I),
]
NEXT_SECTION_HEADER_RE = re.compile(
    r"(intern will learn|what do you predict|qualifications|work schedule|"
    r"location\s*:|^\s*\d+\.\s|compensation)",
    re.I | re.M,
)

# An anchor with almost nothing before the next section marker means the
# intake-form question was left unanswered, not that it has real content.
MIN_CHARS_AFTER_ANCHOR_TO_COUNT_AS_CONTENT = 25

# When no duties anchor is found at all, skip past an org-mission-statement
# opening paragraph so the character budget isn't spent on "About [Agency]..."
# boilerplate instead of the actual role.
ORG_BOILERPLATE_OPENING_RE = re.compile(
    r"^\s*(about\s+[\w\s]+:|who we are\s*:|recently rated|is a multifaith|"
    r"is a nonprofit|is a non-profit)",
    re.I,
)

RESULT_COLUMNS = [
    "NAICS Code", "NAICS Title", "NAICS Match Probability",
    "SOC Code", "SOC Title", "SOC Match Probability",
    "NAICS Flagged As Insufficient Information",
    "SOC Flagged As Insufficient Information",
    "Flagged As Implausible NAICS/SOC Pairing",
    "Duties Anchor Found In Description",
    "Flagged As Blank Intake Form",
    "API Call Error",
]


def extract_duties_text(description: object) -> tuple[str, bool, bool]:
    """Pull the duties/responsibilities section out of a role description.

    Returns (extracted_text, anchor_found, flagged_as_blank_intake_form).
    Falls back to the full description (still capped downstream) if no
    known anchor phrase is found.
    """
    if pd.isna(description):
        return "", False, True
    text = str(description)

    for pattern in DUTIES_ANCHOR_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        after_anchor = text[match.end():]
        next_marker = NEXT_SECTION_HEADER_RE.search(after_anchor)
        extracted = after_anchor[: next_marker.start()] if next_marker else after_anchor
        extracted = extracted.strip()

        if len(extracted) < MIN_CHARS_AFTER_ANCHOR_TO_COUNT_AS_CONTENT:
            # Anchor found, but an unanswered intake-form prompt follows it —
            # there's no real content to code.
            return extracted, True, True

        return extracted, True, False

    boilerplate_match = ORG_BOILERPLATE_OPENING_RE.search(text)
    if boilerplate_match:
        first_break = text.find(".", boilerplate_match.end())
        if first_break != -1 and first_break < len(text) - 1:
            text = text[first_break + 1:].strip()

    return text, False, False


def build_occupation_text(
    role_name: object,
    role_description: object,
    max_description_chars: int = DEFAULT_MAX_DESCRIPTION_CHARS,
) -> tuple[str, bool, bool]:
    """Combine role name + extracted duties into the text sent to NIOCCS as `o`.

    Returns (occupation_text, duties_anchor_found, flagged_as_blank_intake_form).
    """
    role_name = "" if pd.isna(role_name) else str(role_name).strip()
    duties_text, anchor_found, blank_intake_form = extract_duties_text(role_description)
    combined = f"{role_name}. {duties_text}"
    return combined[:max_description_chars], anchor_found, blank_intake_form


def call_nioccs(
    industry_text: str,
    occupation_text: str,
    max_retries: int = 3,
    timeout: int = 20,
) -> dict:
    """Call the NIOCCS API for one (industry, occupation) pair, with retries.

    Returns {"raw_response": dict | None, "http_status": int | None, "error": str | None}.
    """
    params = {**NIOCCS_REQUEST_PARAMS_STATIC, "i": industry_text, "o": occupation_text}

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(NIOCCS_BASE_URL, params=params, timeout=timeout)
            if resp.status_code == 200:
                try:
                    return {"raw_response": resp.json(), "http_status": 200, "error": None}
                except json.JSONDecodeError:
                    last_error = f"Non-JSON response (status 200): {resp.text[:200]}"
            else:
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except requests.exceptions.RequestException as e:
            last_error = f"Request exception: {e}"

        if attempt < max_retries:
            time.sleep(1.5 * attempt)  # simple backoff before retrying

    return {"raw_response": None, "http_status": None, "error": last_error}


def parse_nioccs_response(raw: object) -> dict:
    """Extract NAICS/SOC codes from a NIOCCS response:

        {
          "Industry": [{"NAICSCode": ..., "NAICSTitle": ..., "NAICSProbability": ...}],
          "Occupation": [{"SOCCode": ..., "SOCTitle": ..., "SOCProbability": ...}],
          "UnexpectedCodeCombination": "Y" or "N"
        }

    Takes the top entry in each list (n=1 in the request params asks for
    only the top match anyway).
    """
    empty = {
        "naics_code": None, "naics_title": None, "naics_probability": None,
        "soc_code": None, "soc_title": None, "soc_probability": None,
        "naics_insufficient_info": None, "soc_insufficient_info": None,
        "implausible_pairing_flag": None,
    }
    if not isinstance(raw, dict):
        return empty

    industry_rec = (raw.get("Industry") or [{}])[0] if raw.get("Industry") else {}
    occupation_rec = (raw.get("Occupation") or [{}])[0] if raw.get("Occupation") else {}

    naics_code = industry_rec.get("NAICSCode")
    soc_code = occupation_rec.get("SOCCode")

    return {
        "naics_code": naics_code,
        "naics_title": industry_rec.get("NAICSTitle"),
        "naics_probability": industry_rec.get("NAICSProbability"),
        "soc_code": soc_code,
        "soc_title": occupation_rec.get("SOCTitle"),
        "soc_probability": occupation_rec.get("SOCProbability"),
        "naics_insufficient_info": (naics_code == NAICS_INSUFFICIENT_INFO_CODE) if naics_code else None,
        "soc_insufficient_info": (soc_code == SOC_INSUFFICIENT_INFO_CODE) if soc_code else None,
        "implausible_pairing_flag": raw.get("UnexpectedCodeCombination") == "Y",
    }


def classify_row(
    role_name: object,
    role_description: object,
    industry_text: object,
    max_description_chars: int = DEFAULT_MAX_DESCRIPTION_CHARS,
    max_retries: int = 3,
) -> dict:
    """Classify a single role. Returns a dict matching RESULT_COLUMNS.

    Skips the API call entirely (no cost, no rate-limit hit) when the
    description turns out to be an unfilled intake-form template.
    """
    occupation_text, anchor_found, blank_intake_form = build_occupation_text(
        role_name, role_description, max_description_chars
    )

    if blank_intake_form:
        return {
            "NAICS Code": None, "NAICS Title": None, "NAICS Match Probability": None,
            "SOC Code": None, "SOC Title": None, "SOC Match Probability": None,
            "NAICS Flagged As Insufficient Information": None,
            "SOC Flagged As Insufficient Information": None,
            "Flagged As Implausible NAICS/SOC Pairing": None,
            "Duties Anchor Found In Description": anchor_found,
            "Flagged As Blank Intake Form": True,
            "API Call Error": "Skipped - description is an unfilled intake-form template",
        }

    api_result = call_nioccs(str(industry_text or ""), occupation_text, max_retries=max_retries)
    parsed = parse_nioccs_response(api_result["raw_response"])

    return {
        "NAICS Code": parsed["naics_code"],
        "NAICS Title": parsed["naics_title"],
        "NAICS Match Probability": parsed["naics_probability"],
        "SOC Code": parsed["soc_code"],
        "SOC Title": parsed["soc_title"],
        "SOC Match Probability": parsed["soc_probability"],
        "NAICS Flagged As Insufficient Information": parsed["naics_insufficient_info"],
        "SOC Flagged As Insufficient Information": parsed["soc_insufficient_info"],
        "Flagged As Implausible NAICS/SOC Pairing": parsed["implausible_pairing_flag"],
        "Duties Anchor Found In Description": anchor_found,
        "Flagged As Blank Intake Form": False,
        "API Call Error": api_result["error"],
    }


def classify_dataframe(
    df: pd.DataFrame,
    role_name_col: str,
    role_description_col: str,
    industry_col: str,
    id_col: Optional[str] = None,
    max_description_chars: int = DEFAULT_MAX_DESCRIPTION_CHARS,
    max_retries: int = 3,
    seconds_between_requests: float = 0.5,
    progress_every: int = 25,
    on_row_done: Optional[Callable[[int, int, dict], None]] = None,
) -> pd.DataFrame:
    """Classify every row of `df` against NIOCCS. No file I/O — safe to call
    directly from a notebook on any dataset with a title, description, and
    broad industry/hub label.

    `industry_col` is the broad industry/hub text NIOCCS uses as context for
    the occupation match (e.g. "Healthcare", "Arts, Entertainment, and
    Recreation") — required by the API alongside the occupation text, not
    optional metadata.

    `on_row_done(row_index, total_rows, result_row)` is called after each
    row if given — use it to checkpoint to disk on a long batch (see
    `classify_csv` below for the reference implementation).
    """
    total = len(df)
    results = []
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        result = classify_row(
            row[role_name_col],
            row[role_description_col],
            row[industry_col],
            max_description_chars=max_description_chars,
            max_retries=max_retries,
        )
        if id_col:
            result = {id_col: row[id_col], **result}
        results.append(result)

        if on_row_done:
            on_row_done(i, total, result)
        if progress_every and i % progress_every == 0:
            print(f"...{i}/{total} rows classified")

        if not result["Flagged As Blank Intake Form"]:
            time.sleep(seconds_between_requests)  # be a polite guest on a free public API

    return pd.DataFrame(results)


def _is_row_complete(row: pd.Series) -> bool:
    """A previously-checkpointed row only counts as done if it's a genuine
    success or a genuine skip — a row that errored out on API Call Error
    must be retried on resume, not silently accepted."""
    return bool(pd.isna(row.get("API Call Error")) or row.get("Flagged As Blank Intake Form") is True)


def classify_csv(
    input_path: str,
    output_path: str,
    role_name_col: str = "Role Name",
    role_description_col: str = "Role Description",
    industry_col: str = "Program Hub Category",
    id_col: str = "Opportunity Identifier",
    max_description_chars: int = DEFAULT_MAX_DESCRIPTION_CHARS,
    max_retries: int = 3,
    seconds_between_requests: float = 0.5,
    checkpoint_every: int = 100,
    resume: bool = True,
    test_mode: bool = False,
    test_sample_size: int = 10,
) -> pd.DataFrame:
    """Resumable, checkpointed file-to-file classification — the batch-job
    shape every notebook in this project has hand-rolled independently.
    Writes `output_path` incrementally so a crash mid-run only costs the
    rows since the last checkpoint.
    """
    df = pd.read_csv(input_path, encoding="utf-8-sig")

    if test_mode:
        df = df.head(test_sample_size)
        print(f"TEST MODE: running on {len(df)} rows only.\n")

    done_df = pd.DataFrame()
    if resume and not test_mode and os.path.exists(output_path):
        existing = pd.read_csv(output_path, encoding="utf-8-sig")
        done_df = existing[existing.apply(_is_row_complete, axis=1)]
        done_ids = set(done_df[id_col])
        if done_ids:
            print(f"Resuming: {len(done_ids)} rows already classified, skipping those.")
            df = df[~df[id_col].isin(done_ids)]

    results_buffer: list[dict] = []

    def checkpoint(i: int, total: int, result_row: dict) -> None:
        results_buffer.append(result_row)
        if test_mode:
            print(f"--- Row {i}/{total} ---")
            print({k: v for k, v in result_row.items() if k != id_col})
        if not test_mode and (i % checkpoint_every == 0 or i == total):
            combined = pd.concat([done_df, pd.DataFrame(results_buffer)], ignore_index=True)
            combined.to_csv(output_path, index=False)
            print(f"Checkpoint saved: {len(combined)} rows classified so far.")

    results_df = classify_dataframe(
        df,
        role_name_col=role_name_col,
        role_description_col=role_description_col,
        industry_col=industry_col,
        id_col=id_col,
        max_description_chars=max_description_chars,
        max_retries=max_retries,
        seconds_between_requests=seconds_between_requests,
        on_row_done=checkpoint,
    )

    combined = pd.concat([done_df, results_df], ignore_index=True)
    if not test_mode:
        combined.to_csv(output_path, index=False)
        n_errors = combined["API Call Error"].notna().sum() - combined["Flagged As Blank Intake Form"].sum()
        print(f"\nDone. {len(combined)} total rows written to {output_path}")
        if n_errors > 0:
            print(f"{n_errors} rows had a call error and should be re-run (they're in the "
                  f"output file with the error message — a re-run with resume=True will retry them).")
    else:
        print(f"\nTest run complete on {len(results_df)} rows. Nothing written to disk — "
              f"review the output above, then re-run without --test for the full batch.")

    return combined


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Code role titles + descriptions to NAICS/SOC via the CDC NIOCCS API.",
    )
    parser.add_argument("--input", required=True, help="CSV with role title/description/industry columns")
    parser.add_argument("--output", required=True, help="Where to write the coded CSV (also read back to resume)")
    parser.add_argument("--role-name-col", default="Role Name")
    parser.add_argument("--role-description-col", default="Role Description")
    parser.add_argument("--industry-col", default="Program Hub Category")
    parser.add_argument("--id-col", default="Opportunity Identifier")
    parser.add_argument("--max-description-chars", type=int, default=DEFAULT_MAX_DESCRIPTION_CHARS)
    parser.add_argument("--seconds-between-requests", type=float, default=0.5)
    parser.add_argument("--checkpoint-every", type=int, default=100)
    parser.add_argument("--no-resume", action="store_true", help="Ignore any existing --output and start over")
    parser.add_argument("--test", action="store_true", help="Run on a small sample and print raw results, write nothing")
    parser.add_argument("--test-sample-size", type=int, default=10)
    args = parser.parse_args()

    classify_csv(
        input_path=args.input,
        output_path=args.output,
        role_name_col=args.role_name_col,
        role_description_col=args.role_description_col,
        industry_col=args.industry_col,
        id_col=args.id_col,
        max_description_chars=args.max_description_chars,
        seconds_between_requests=args.seconds_between_requests,
        checkpoint_every=args.checkpoint_every,
        resume=not args.no_resume,
        test_mode=args.test,
        test_sample_size=args.test_sample_size,
    )


if __name__ == "__main__":
    main()
