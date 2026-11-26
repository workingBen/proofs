#!/usr/bin/env python3
"""Turn before/after measurements into the findings a machine can be sure of.

The division of labor this whole pipeline rests on: a machine can measure
whether a page scrolls sideways at 390px, and cannot tell you that squeezing
the field to fix it truncated the year to "09/12/20". So this emits only what
it can stand behind, and every finding names the number it came from.

The rule that matters: report a REGRESSION, not a state. Plenty of pages in
an app already overflow slightly at some width; a QA that lists those buries
the one the PR caused. A finding is raised when the after is worse than the
before for the same page at the same size.

A flaw on both sides is not dropped: it goes under "already_on_main" (severity
"note"), which the page lists apart and never counts toward the verdict.

    python3 scripts/pr_qa_findings.py --dir work/pr-7 --out work/pr-7/findings.json

With --out the JSON goes to that file and stdout carries a one-line summary;
without it the JSON is printed, so a pipe still works.

With no layout measurements in before.json and after.json the verdict is
"unknown" ("not measured"), never "clean": absence of measurements is not
evidence that nothing broke.
"""
import argparse
from collections import Counter
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "shared"))
import settings  # shared/settings.py: the Proofs settings table and resolver

# Below this, a difference is noise -- sub-pixel rounding and scrollbar
# arithmetic, not a layout that broke.
OVERFLOW_NOISE_PX = 2

# The keys a shot carries when the capture step actually measured the layout.
# A shot with none of them (just label, size, path, file) proves nothing, and a
# comparison of two such lists would otherwise read as "clean".
MEASURES = ("overflow", "scrollWidth", "clientWidth", "smallTargets", "errors")

NOT_MEASURED_NOTE = ("not measured: before.json and after.json hold no layout "
                     "measurements, so no regression could be checked")


def _load_json(directory, label):
    path = os.path.join(directory, f"{label}.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def load(directory, label):
    return _load_json(directory, label).get("shots", [])


def capture_failures(directory):
    """Shots the capture could not take because the page answered with an error.

    capture.cjs lists them under "failures" (HTTP 400 or above, or a page that
    reads as an error page) and exits 6. A shot that still carries such a
    status (an older capture, or one written by hand) counts too. Either way
    the run photographed something that is not the page, so it can never be
    "clean" (SvelteKit run 1: two 404 pages scored "verdict: clean").
    """
    found = []
    for label in ("before", "after"):
        data = _load_json(directory, label)
        for item in data.get("failures") or []:
            found.append(dict(item, side=label))
        for shot in data.get("shots") or []:
            status = shot.get("status")
            if isinstance(status, int) and status >= 400:
                found.append({"side": label, "page": shot.get("pageLabel") or shot.get("path"),
                              "viewport": shot.get("label") or shot.get("size"), "path": shot.get("path"),
                              "status": status,
                              "error": f'{shot.get("path")} answered HTTP {status}; this is not the page'})
    return found


def failure_note(failures):
    parts = []
    for f in failures[:4]:
        status = f.get("status")
        what = f"HTTP {status}" if status else "an error page"
        parts.append(f'{f.get("page")} at {f.get("viewport")} ({f.get("side")}: {what})')
    more = f" and {len(failures) - 4} more" if len(failures) > 4 else ""
    return ("capture failed: " + "; ".join(parts) + more +
            ". Those shots are not the page, so nothing there was checked; fix the "
            "pages file's base and path (or the server) and capture again")


def key(shot):
    return (shot.get("slug"), shot.get("size"))


def finding(severity, title, detail, evidence):
    return {"severity": severity, "title": title, "detail": detail, "evidence": evidence}


def compare(before, after):
    """Findings, worst first, from two runs of the same page set."""
    olds = {key(s): s for s in before}
    findings = []

    for shot in after:
        old = olds.get(key(shot))
        where = where_of(shot)

        # A shot of the wrong page is not evidence, and saying so beats
        # publishing it silently.
        if shot.get("redirected"):
            findings.append(finding(
                "blocker", f"{where}: the screenshot is not of that page",
                f'Asked for {shot.get("path")} and landed on {shot.get("landedOn")}. '
                "Treat this pair as no evidence at all.",
                {"path": shot.get("path"), "landedOn": shot.get("landedOn")}))
            continue

        # No measurements on either side: nothing to compare, and defaulting
        # the missing fields to 0 would invent a baseline. unmeasured_routes()
        # reports these.
        if not is_measured(shot) or (old is not None and not is_measured(old)):
            continue

        new_overflow = shot.get("overflow", 0)
        old_overflow = (old or {}).get("overflow", 0)
        if new_overflow - old_overflow > OVERFLOW_NOISE_PX:
            worst = max(shot.get("overflowing") or [],
                        key=lambda e: e.get("past", 0), default=None)
            culprit = ""
            if worst:
                label = worst.get("text") or worst.get("tag")
                culprit = (f' The furthest thing out is "{label}", '
                           f'{worst.get("past")}px past the edge.')
            findings.append(finding(
                "blocker" if shot.get("size") == "phone" else "warning",
                f"{where}: the page now scrolls sideways",
                f"{shot.get('clientWidth')}px viewport, {shot.get('scrollWidth')}px of content "
                f"— {new_overflow}px over, against {old_overflow}px before this PR.{culprit} "
                "No test asserts on a layout, so nothing else will catch this.",
                {"before": old_overflow, "after": new_overflow,
                 "size": shot.get("size"), "worst": worst}))
        elif old_overflow - new_overflow > OVERFLOW_NOISE_PX:
            findings.append(finding(
                "good", f"{where}: sideways scrolling is fixed",
                f"{old_overflow}px of overflow before, {new_overflow}px after.",
                {"before": old_overflow, "after": new_overflow}))

        fresh = fresh_targets(old, shot)
        targets_rose = item_count(shot, "smallTargets", "smallTargetCount") > \
            item_count(old, "smallTargets", "smallTargetCount")
        if fresh:
            findings.append(finding(
                "warning", f"{where}: new small tap targets",
                f"Under the {settings.get('PROOFS_MIN_TAP')}px that reads as reliably tappable: "
                f"{name_items([target_label(t) for t in fresh])}.",
                dict({"targets": fresh[:4]}, **({"rise": True} if targets_rose else {}))))

        fresh_text = fresh_small_text(old, shot)
        text_rose = item_count(shot, "smallText", "smallTextCount") > \
            item_count(old, "smallText", "smallTextCount")
        if fresh_text:
            findings.append(finding(
                "warning", f"{where}: new text below the size floor",
                "Text smaller than the floor the page is held to: "
                f"{name_items([text_label(t) for t in fresh_text])}.",
                dict({"text": fresh_text[:4]}, **({"rise": True} if text_rose else {}))))

        fresh_off = fresh_off_center(old, shot)
        if fresh_off:
            findings.append(finding(
                "warning", f"{where}: a row is now off-center",
                "Inside a centered column, content now sits to one side (gaps left and "
                f"right of it): {name_items([off_center_label(o) for o in fresh_off])}. "
                "Usually a flex or grid row, which text-align: center does not center.",
                {"rows": fresh_off[:4]}))

        fresh_cols = fresh_off_columns(old, shot)
        if fresh_cols:
            findings.append(finding(
                "warning", f"{where}: a section column is now out of line",
                "A page-wide column now sits off-center or starts at a different left edge from the "
                f"columns around it: {name_items([off_column_label(o) for o in fresh_cols])}.",
                {"columns": fresh_cols[:4]}))

        fresh_mid = fresh_by_key(old, shot, "midWord", lambda w: w)
        if fresh_mid:
            findings.append(finding(
                "warning", f"{where}: a word now breaks mid-word",
                f"Split across two lines with no hyphen: {name_items(fresh_mid)}.",
                {"words": fresh_mid[:4]}))

        fresh_untitled = fresh_by_key(old, shot, "untitled", untitled_key)
        if fresh_untitled:
            findings.append(finding(
                "warning", f"{where}: a new section without a heading",
                "A page-wide section with content and no h1-h6 inside, so a reader scanning by headings "
                f"skips it: {name_items([untitled_label(u) for u in fresh_untitled])}.",
                {"sections": fresh_untitled[:4]}))

        fresh_errors = [e for e in shot.get("errors") or []
                        if e not in ((old or {}).get("errors") or [])]
        if fresh_errors:
            findings.append(finding(
                "blocker", f"{where}: a new JavaScript error",
                fresh_errors[0], {"errors": fresh_errors[:3]}))

    # A shot that does not show the page below its first screen is not evidence there, on either
    # side, whatever the other numbers say (Astro run 1: sections that fade in on scroll left every
    # shot blank below the hero, and the findings said "clean").
    for label, shots in (("before", before), ("after", after)):
        for shot in shots:
            blank = shot.get("blank") or {}
            if not blank.get("flagged"):
                continue
            why = []
            if blank.get("image"):
                why.append(f'{round((blank.get("colorShare") or 0) * 100)}% one flat color below the first screen')
            if blank.get("hidden"):
                why.append(f'{blank.get("hiddenBlocks")} blocks still at opacity 0')
            findings.append(finding(
                "warning", f"{where_of(shot)}: the {label} shot is mostly blank",
                f'{"; ".join(why) or "blank below the first screen"}, so nothing there was checked. The page may '
                "reveal sections as you scroll, or load them late. Open the PNG and say what was not seen; "
                "do not call this page clean.", {"side": label, "blank": blank}))

    missing = [s for s in before if key(s) not in {key(a) for a in after}]
    for shot in missing:
        findings.append(finding(
            "warning",
            f'{shot.get("pageLabel") or shot.get("path")} at {shot.get("size")}: '
            "no after shot",
            "The page was photographed before the change but not after, so this pair "
            "proves nothing.", {"path": shot.get("path")}))

    order = {"blocker": 0, "warning": 1, "good": 2}
    return sorted(findings, key=lambda f: order.get(f["severity"], 9))


def name_items(items, limit=4):
    """Up to `limit` items joined by "; ", then "and N more"."""
    out = "; ".join(items[:limit])
    if len(items) > limit:
        out += f"; and {len(items) - limit} more"
    return out


def target_label(t):
    name = t.get("text") or t.get("tag")
    return f'"{name}" {t.get("width")}x{t.get("height")}px'


def text_label(t):
    return f'"{t.get("text")}" {t.get("px")}px'


def fresh_by_count(old_items, new_items, keyfn):
    """Items in new_items beyond what old_items already had, per key.

    A multiset comparison: one "Edit" link becoming four is three new items,
    even though the label was already seen.
    """
    budget = Counter(keyfn(t) for t in old_items)
    fresh = []
    for item in new_items:
        k = keyfn(item)
        if budget[k] > 0:
            budget[k] -= 1
        else:
            fresh.append(item)
    return fresh


def item_count(shot, list_key, count_key):
    """How many such items a shot holds: its count field when present (the
    list may be capped), else the list length. A missing shot is zero."""
    if not shot:
        return 0
    count = shot.get(count_key)
    if isinstance(count, int):
        return count
    return len(shot.get(list_key) or [])


def fresh_targets(old, shot):
    return fresh_by_count((old or {}).get("smallTargets") or [],
                          shot.get("smallTargets") or [],
                          lambda t: (t.get("text"), t.get("tag")))


def fresh_small_text(old, shot):
    # A before shot from an older capture has no smallText at all; that is "not
    # measured", not "zero", so it cannot be compared.
    if old is not None and "smallText" not in old:
        return []
    return fresh_by_count((old or {}).get("smallText") or [],
                          shot.get("smallText") or [],
                          lambda t: t.get("text"))


def off_center_label(o):
    return f'"{o.get("text") or o.get("tag")}" ({o.get("left")}px left, {o.get("right")}px right)'


def fresh_off_center(old, shot):
    # An older capture has no offCenter: "not measured", not "zero".
    if old is not None and "offCenter" not in old:
        return []
    return fresh_by_count((old or {}).get("offCenter") or [], shot.get("offCenter") or [],
                          lambda o: (o.get("text"), o.get("tag")))


def off_column_label(o):
    name = o.get("text") or o.get("tag")
    if o.get("kind") == "edge":
        return f'"{name}" (edge at {o.get("edge")}px, the columns around it at {o.get("neighbors")}px)'
    return f'"{name}" (not centered: {o.get("left")}px left, {o.get("right")}px right)'


def fresh_off_columns(old, shot):
    # An older capture has no offColumns: "not measured", not "zero".
    if old is not None and "offColumns" not in old:
        return []
    return fresh_by_count((old or {}).get("offColumns") or [], shot.get("offColumns") or [],
                          lambda o: (o.get("kind"), o.get("text"), o.get("tag")))


def fresh_by_key(old, shot, field, keyfn):
    """Items of `field` the after shot has beyond the before's. An older capture without
    the field is "not measured", not "zero", so nothing is fresh against it."""
    if old is not None and field not in old:
        return []
    return fresh_by_count((old or {}).get(field) or [], shot.get(field) or [], keyfn)


def untitled_key(u):
    return (u.get("tag"), u.get("id"), u.get("text"))


def untitled_label(u):
    ident = f' (#{u.get("id")})' if u.get("id") else ""
    return f'"{u.get("text") or u.get("tag")}"{ident}'


def shared_by_count(old_items, new_items, keyfn):
    """Items of new_items that old_items had too (a multiset intersection)."""
    budget = Counter(keyfn(t) for t in old_items)
    shared = []
    for item in new_items:
        k = keyfn(item)
        if budget[k] > 0:
            budget[k] -= 1
            shared.append(item)
    return shared


# What already_on_main() looks at: (field, title, label for one item, key for one item).
ON_MAIN = (
    ("midWord", "a word breaks mid-word", lambda w: f'"{w}"', lambda w: w),
    ("offCenter", "a row is off-center", off_center_label, lambda o: (o.get("text"), o.get("tag"))),
    ("offColumns", "a section column is off-center or out of line", off_column_label,
     lambda o: (o.get("kind"), o.get("text"), o.get("tag"))),
    ("untitled", "a section without a heading", untitled_label, untitled_key),
    ("smallTargets", "small tap targets", target_label, lambda t: (t.get("text"), t.get("tag"))),
    ("smallText", "text below the size floor", text_label, lambda t: t.get("text")),
)


def already_on_main(before, after):
    """Flaws the capture found on both sides: already on the base branch, so not this PR's.

    Astro run 2: the off-center steps column and the "tem|plate" break were caught, and the
    page left them out because they were on main too, so a reader of the page never saw them.
    They go in their own list, severity "note", and never count toward the verdict.
    """
    olds = {key(s): s for s in before}
    notes = []
    for shot in after:
        old = olds.get(key(shot))
        if old is None or shot.get("redirected") or not is_measured(shot) or not is_measured(old):
            continue
        where = where_of(shot)
        both = min(shot.get("overflow", 0), old.get("overflow", 0))
        if both > OVERFLOW_NOISE_PX:
            notes.append(finding(
                "note", f"{where}: the page scrolls sideways",
                f'{old.get("overflow")}px over before this PR and {shot.get("overflow")}px after, '
                f'on a {shot.get("clientWidth")}px viewport.', {"before": old.get("overflow"),
                                                               "after": shot.get("overflow")}))
        for field, title, labelfn, keyfn in ON_MAIN:
            if field not in old or field not in shot:
                continue
            shared = shared_by_count(old.get(field) or [], shot.get(field) or [], keyfn)
            if shared:
                notes.append(finding("note", f"{where}: {title}", name_items([labelfn(x) for x in shared]) + ".",
                                     {field: shared[:4]}))
    return notes


def is_measured(shot):
    return any(name in shot for name in MEASURES)


def where_of(shot):
    return f'{shot.get("pageLabel") or shot.get("path")} at {shot.get("size")}'


def unmeasured_routes(before, after):
    """Routes (page at size) whose before or after shot holds no measurements.

    Decided per route and per side: a bare shot on either side means that route
    could not be compared, and must never read as clean or as a 0 baseline.
    A redirected shot is skipped; it is already a blocker.
    """
    olds = {key(s): s for s in before}
    names = []
    for shot in after:
        if shot.get("redirected"):
            continue
        old = olds.get(key(shot))
        if not is_measured(shot) or (old is not None and not is_measured(old)):
            names.append(where_of(shot))
    return names


def measured(before, after):
    """True only when at least one after shot is measured and no compared
    route is missing measurements on either side."""
    return (any(is_measured(s) for s in after)
            and not unmeasured_routes(before, after))


def summarize(findings, plan=None, measured=True, unmeasured=None, failures=None, already=None):
    counts = {"blocker": 0, "warning": 0, "good": 0}
    for item in findings:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1
    if counts["blocker"]:
        verdict = "hold"
    elif counts["warning"]:
        verdict = "look"
    elif not measured:
        # Something was not measured, so "clean" would be a claim with no evidence.
        verdict = "unknown"
    else:
        verdict = "clean"
    out = {"findings": findings, "counts": counts, "verdict": verdict,
           "measured": bool(measured)}
    if not measured:
        out["note"] = NOT_MEASURED_NOTE
        if unmeasured:
            out["unmeasured"] = list(unmeasured)
            out["note"] = ("not measured: " + ", ".join(unmeasured) +
                           " hold no layout measurements in before.json or "
                           "after.json, so no regression could be checked there")
    if failures:
        # A failed capture is never clean, whatever else the run measured.
        if verdict == "clean":
            verdict = "unknown"
        out["verdict"] = verdict
        out["measured"] = False
        out["capture_failures"] = list(failures)
        out["note"] = failure_note(failures) + (("; " + out["note"]) if out.get("note") else "")
    if already:
        # Listed apart, after the verdict is set: these never change it.
        out["already_on_main"] = list(already)
    if plan:
        # An unmapped view means the QA covered less than it appears to. Saying
        # so is the difference between a gap and a silent gap.
        out["unmapped_changes"] = plan.get("unmatched_changes", [])
        out["pages_covered"] = [p["path"] for p in plan.get("pages", [])]
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True)
    parser.add_argument("--plan")
    parser.add_argument("--out", help="write the findings JSON here and print only a one-line summary")
    args = parser.parse_args(argv)

    plan = None
    if args.plan and os.path.exists(args.plan):
        with open(args.plan, encoding="utf-8") as handle:
            plan = json.load(handle)

    before = load(args.dir, "before")
    after = load(args.dir, "after")
    failures = capture_failures(args.dir)
    result = summarize(compare(before, after), plan, measured=measured(before, after),
                       unmeasured=unmeasured_routes(before, after), failures=failures,
                       already=already_on_main(before, after))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
        counts = result.get("counts") or {}
        on_main = len(result.get("already_on_main") or [])
        extra = f"; {on_main} already on main (not counted)" if on_main else ""
        print(f"verdict: {result.get('verdict')}; {sum(counts.values()) if counts else len(result.get('findings', []))} finding(s){extra} -> {args.out}")
        if failures:
            print(result["note"])
    else:
        print(json.dumps(result, indent=2))
    # Never fail the build. A blocker is a thing for a person to decide about,
    # and a red X on the PR would say "the agent's change is broken" when what
    # is true is "the layout needs a look".
    return 0


if __name__ == "__main__":
    sys.exit(main())
