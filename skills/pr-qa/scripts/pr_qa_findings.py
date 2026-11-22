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

    python3 scripts/pr_qa_findings.py --dir work/pr-7 --out work/pr-7/findings.json

With --out the JSON goes to that file and stdout carries a one-line summary;
without it the JSON is printed, so a pipe still works.

With no layout measurements in before.json and after.json the verdict is
"unknown" ("not measured"), never "clean": absence of measurements is not
evidence that nothing broke.
"""
import argparse
import json
import os
import sys

# Below this, a difference is noise -- sub-pixel rounding and scrollbar
# arithmetic, not a layout that broke.
OVERFLOW_NOISE_PX = 2
MIN_TAP_TARGET = 44

# The keys a shot carries when the capture step actually measured the layout.
# A shot with none of them (just label, size, path, file) proves nothing, and a
# comparison of two such lists would otherwise read as "clean".
MEASURES = ("overflow", "scrollWidth", "clientWidth", "smallTargets", "errors")

NOT_MEASURED_NOTE = ("not measured: before.json and after.json hold no layout "
                     "measurements, so no regression could be checked")


def load(directory, label):
    path = os.path.join(directory, f"{label}.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as handle:
        return json.load(handle).get("shots", [])


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

        old_small = {(t.get("text"), t.get("tag")) for t in (old or {}).get("smallTargets") or []}
        fresh = [t for t in shot.get("smallTargets") or []
                 if (t.get("text"), t.get("tag")) not in old_small]
        if fresh and shot.get("size") == "phone":
            worst = min(fresh, key=lambda t: min(t.get("width", 0), t.get("height", 0)))
            findings.append(finding(
                "warning", f"{where}: a new control is small for a finger",
                f'"{worst.get("text") or worst.get("tag")}" is '
                f'{worst.get("width")}x{worst.get("height")}px, under the {MIN_TAP_TARGET}px '
                "that reads as reliably tappable.",
                {"targets": fresh[:4]}))

        fresh_errors = [e for e in shot.get("errors") or []
                        if e not in ((old or {}).get("errors") or [])]
        if fresh_errors:
            findings.append(finding(
                "blocker", f"{where}: a new JavaScript error",
                fresh_errors[0], {"errors": fresh_errors[:3]}))

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


def summarize(findings, plan=None, measured=True, unmeasured=None):
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
    result = summarize(compare(before, after), plan, measured=measured(before, after),
                       unmeasured=unmeasured_routes(before, after))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2)
        counts = result.get("counts") or {}
        print(f"verdict: {result.get('verdict')}; {sum(counts.values()) if counts else len(result.get('findings', []))} finding(s) -> {args.out}")
    else:
        print(json.dumps(result, indent=2))
    # Never fail the build. A blocker is a thing for a person to decide about,
    # and a red X on the PR would say "the agent's change is broken" when what
    # is true is "the layout needs a look".
    return 0


if __name__ == "__main__":
    sys.exit(main())
