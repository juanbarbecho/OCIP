#!/usr/bin/env python3
"""Git clean filter: strip cell outputs/execution counts from a notebook
before it's stored in git, so committed notebooks never carry student-level
data that was printed while running them locally.

Registered via .gitattributes + `git config filter.nbstrip.clean` (see
tools/setup_git_filters.sh). Only affects what gets committed — the
notebook file on disk keeps its outputs so you can still see your results.
"""
import json
import sys


def strip(nb):
    for cell in nb.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
        cell.get("metadata", {}).pop("ExecuteTime", None)
    nb.get("metadata", {}).pop("widgets", None)
    return nb


def main():
    nb = json.load(sys.stdin)
    strip(nb)
    json.dump(nb, sys.stdout, indent=1, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
