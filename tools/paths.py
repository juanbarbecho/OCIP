#!/usr/bin/env python3
"""Locate this repo's data/, outputs/, and tools/ folders from any notebook,
regardless of how deeply that notebook is nested under notebooks/.

Every notebook in this repo lives at a different depth (notebooks/matching/*.ipynb
is two levels down; notebooks/industry_growth_analysis/to_excel/*.ipynb is three),
and that depth has already changed once during a reorg and will change again.
Hardcoding a `../../data/...` hop-count breaks every time a notebook moves.
This walks upward looking for the repo root itself — a directory containing
both data/ and tools/ as siblings — instead of assuming a fixed number of hops,
so a notebook's paths keep working no matter where it's nested.

Usage, as the first code cell of a notebook:

    import os, sys
    _root = os.getcwd()
    for _ in range(6):
        if os.path.isdir(os.path.join(_root, "tools")) and os.path.isdir(os.path.join(_root, "data")):
            break
        _root = os.path.dirname(_root)
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from tools.paths import data_path, outputs_path

Then: READY_PATH = data_path("AllRoles_nioccs_ready.csv")
      OUT_PATH = outputs_path("industry_growth_analysis", "Sector_Detail_Workbook.xlsx")
"""

from __future__ import annotations

import os

DEFAULT_MAX_LEVELS_UP = 6

# The repo root is identified by having both of these as direct children —
# arbitrary but stable: both exist today and neither is likely to move.
ROOT_MARKERS = ("data", "tools")


def find_repo_root(start: str | None = None, max_levels_up: int = DEFAULT_MAX_LEVELS_UP) -> str:
    """Walk upward from `start` (default: current working directory) until a
    directory containing all of ROOT_MARKERS is found. Raises RuntimeError if
    no such directory is found within `max_levels_up` levels.
    """
    current = os.path.abspath(start or os.getcwd())
    for _ in range(max_levels_up + 1):
        if all(os.path.isdir(os.path.join(current, marker)) for marker in ROOT_MARKERS):
            return current
        parent = os.path.dirname(current)
        if parent == current:  # hit the filesystem root
            break
        current = parent

    raise RuntimeError(
        f"Couldn't find the repo root (a directory containing both "
        f"{'/ '.join(ROOT_MARKERS)}/) within {max_levels_up} levels above "
        f"{start or os.getcwd()}."
    )


def data_path(*parts: str) -> str:
    """Absolute path into data/, e.g. data_path('cultural_corps', 'cc_step2_ready_for_nioccs.csv')."""
    return os.path.join(find_repo_root(), "data", *parts)


def outputs_path(*parts: str) -> str:
    """Absolute path into outputs/, e.g. outputs_path('matching', 'preference_histograms.png')."""
    return os.path.join(find_repo_root(), "outputs", *parts)


def tools_path(*parts: str) -> str:
    """Absolute path into tools/, e.g. tools_path('nioccs_classify.py')."""
    return os.path.join(find_repo_root(), "tools", *parts)
