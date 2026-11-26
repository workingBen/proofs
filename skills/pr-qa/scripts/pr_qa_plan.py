#!/usr/bin/env python3
"""Decide which URLs a PR's screenshots should cover.

The pr-qa skill's first rule is that a screenshot of a page which does not
contain the change is worse than no screenshot: it looks like evidence. So
this maps changed files to URLs through a map you write and commit
(pr_qa_pages.json by default) rather than inferring routes from view paths,
and when nothing matches it says NOTHING MATCHED rather than falling back to a
default page.

The map is JSON. Each entry in "pages" has a "name", a "match" list of glob
patterns against repo-relative changed paths, and "urls": a list of
{"label": ..., "path": "/some/page/{record_id}"}. {placeholders} are filled
from a JSON file you pass with --ids (for example, ids of sample records you
seed so that they exercise the change). An optional top-level
"visual_prefixes" list replaces the default list of directories that can change
how a page looks.

Prints JSON on stdout:

    {"pages": [{"label": "...", "path": "/contacts/14", ...}],
     "matched": ["contact"], "unmatched_changes": ["app/models/x.rb"]}

Usage:
    python3 scripts/pr_qa_plan.py --map pr_qa_pages.json --changed-file changed.txt --ids ids.json
    git diff --name-only origin/main... | python3 scripts/pr_qa_plan.py --ids ids.json
"""
import argparse
import fnmatch
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "shared"))
import settings  # shared/settings.py: the Proofs settings table and resolver

HERE = os.path.dirname(os.path.abspath(__file__))

# Only these directories can change what a page LOOKS like. A PR touching
# nothing but tests or docs has nothing to photograph, and saying so beats
# producing a pair of identical screenshots that imply a change was inspected.
# The directories that can change what a page looks like are the PROOFS_QA_PATHS setting.
# A map can replace them with its own "visual_prefixes".


def default_map():
    return settings.get("PROOFS_QA_MAP")


def read_map(path=None):
    """The whole map file, or an exit with a plain message if it is missing."""
    path = path or default_map()
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        sys.exit("==> no page map at %s: write one (see the pr-qa skill) or pass --map" % path)
    except ValueError as err:
        sys.exit("==> page map %s is not valid JSON: %s" % (path, err))


def load_map(path=None):
    path = path or default_map()
    return read_map(path).get("pages", [])


def is_visual(path, prefixes=None):
    return any(path == p or path.startswith(p) for p in (prefixes or settings.get("PROOFS_QA_PATHS")))


def matches(path, patterns):
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def fill(template, ids):
    """Substitute {placeholders}; a missing one makes the URL unusable, not wrong.

    Returning None rather than a URL with a literal "{contact_id}" in it is the
    point: that URL would 404, and a 404 screenshot published as a before/after
    pair is exactly the "looks like evidence" failure.
    """
    missing = [key for key in re.findall(r"\{(\w+)\}", template) if key not in ids]
    if missing:
        return None
    return re.sub(r"\{(\w+)\}", lambda m: str(ids[m.group(1)]), template)


def plan(changed, ids, pages=None, prefixes=None):
    pages = load_map() if pages is None else pages
    visual = [p for p in changed if is_visual(p, prefixes)]

    chosen, matched, seen = [], [], set()
    for entry in pages:
        hit = [p for p in visual if matches(p, entry.get("match", []))]
        if not hit:
            continue
        matched.append(entry["name"])
        for url in entry.get("urls", []):
            path = fill(url["path"], ids)
            if path is None or path in seen:
                continue
            seen.add(path)
            chosen.append({"label": url["label"], "path": path, "from": entry["name"]})

    claimed = {p for entry in pages if entry["name"] in matched
               for p in visual if matches(p, entry.get("match", []))}
    return {
        "pages": chosen,
        "matched": matched,
        "unmatched_changes": sorted(set(visual) - claimed),
        "non_visual_changes": sorted(set(changed) - set(visual)),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-file", help="file of changed paths, one per line; default stdin")
    parser.add_argument("--ids", help="JSON file of placeholder values to fill into the map's URLs")
    parser.add_argument("--map", default=None, help="page map (default: the PROOFS_QA_MAP setting)")
    args = parser.parse_args(argv)

    if args.changed_file:
        with open(args.changed_file, encoding="utf-8") as handle:
            raw = handle.read()
    else:
        raw = sys.stdin.read()
    changed = [line.strip() for line in raw.splitlines() if line.strip()]

    ids = {}
    if args.ids and os.path.exists(args.ids):
        with open(args.ids, encoding="utf-8") as handle:
            ids = json.load(handle)

    loaded = read_map(args.map)
    result = plan(changed, ids, loaded.get("pages", []), loaded.get("visual_prefixes"))
    print(json.dumps(result, indent=2))
    # Exit 0 even with no pages: "nothing to photograph" is a real answer and
    # must not fail the PR. The caller reads .pages and reports honestly.
    return 0


if __name__ == "__main__":
    sys.exit(main())
