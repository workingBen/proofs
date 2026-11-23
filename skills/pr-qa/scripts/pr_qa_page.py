#!/usr/bin/env python3
"""Turn a run's QA evidence into the review page the user opens.

Pure input -> output: no network, no GitHub, no Claude. Everything it emits it
can stand behind, and everything it CANNOT stand behind it labels as such --
a PR nobody has read renders as "not yet read by a reviewer", never as "clean".
That distinction is the whole reason this file is separate from the session
that publishes it: findings.json can measure that a page scrolls 23px sideways
at 390px, and could never have seen a duplicate migration or a private note's
date reaching a visible field. Both can pass a full test suite.

    python3 scripts/pr_qa_page.py --meta meta.json --out pr-qa.html
"""
import argparse
import base64
import html as html_escape
import json
import os
import re
import shutil
import subprocess
import sys

SEVERITY_RANK = {"blocker": 0, "warning": 1, "good": 2}

# `unknown` sits ABOVE `look` and `clean` deliberately: a PR nobody has read is
# more dangerous than one that was read and found merely untidy. Sorting it last
# is how an unreviewed PR goes quiet, which is how an unreviewed PR sits for days.
VERDICT_RANK = {"hold": 0, "unknown": 1, "look": 2, "clean": 3}

ABSENT = {"present": False, "verdict": "unknown", "findings": [],
          "before": [], "after": [], "counts": {}, "unmapped_changes": [],
          "pages_covered": [], "plan": {}}


def _read(directory, name, default):
    path = os.path.join(directory, name)
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (ValueError, OSError):
        return default


def load_evidence(directory):
    """One PR's evidence directory (findings.json, before.json, after.json,
    plan.json and the screenshots), or ABSENT if there is none."""
    if not directory or not os.path.isdir(directory):
        return dict(ABSENT)
    findings = _read(directory, "findings.json", None)
    if findings is None:
        return dict(ABSENT)
    return {
        "present": True,
        "dir": directory,
        "verdict": findings.get("verdict", "unknown"),
        # Older findings files predate this field; they were measured.
        "measured": findings.get("measured", True),
        "note": findings.get("note", ""),
        "findings": findings.get("findings", []),
        "counts": findings.get("counts", {}),
        "unmapped_changes": findings.get("unmapped_changes", []),
        "pages_covered": findings.get("pages_covered", []),
        "before": _read(directory, "before.json", {}).get("shots", []),
        "after": _read(directory, "after.json", {}).get("shots", []),
        "plan": _read(directory, "plan.json", {}),
    }


def effective_verdict(evidence, human_findings):
    """The worse of what the machine measured and what a reviewer saw.

    Human findings are evaluated FIRST, before evidence presence is checked.
    A reviewer's `blocker` means `hold` whether or not there are screenshots to
    back it up -- a human who wrote "do not merge" must never be overridden by
    an absent artifact into the page silently claiming nobody looked.
    """
    worst = min((SEVERITY_RANK.get(f.get("severity"), 9) for f in human_findings),
                default=9)
    if worst == 0:
        return "hold"
    if not evidence.get("present"):
        return "unknown"
    verdict = evidence.get("verdict", "unknown")
    if (verdict == "unknown" and evidence.get("measured", True) is False
            and worst <= 1):
        # Nothing was measured, but a reviewer looked and wrote something down.
        return "look"
    if worst == 1 and VERDICT_RANK.get(verdict, 9) > VERDICT_RANK["look"]:
        return "look"
    return verdict


def merge_findings(evidence, human_findings):
    """One numbered list, worst first, every item saying where it came from."""
    merged = [dict(f, source="human") for f in human_findings]
    merged += [dict(f, source="machine") for f in evidence.get("findings", [])]
    return sorted(merged, key=lambda f: (SEVERITY_RANK.get(f.get("severity"), 9),
                                         0 if f["source"] == "human" else 1))


def order_prs(prs):
    """Worst first. The one that must not be merged goes at the top."""
    return sorted(prs, key=lambda p: (VERDICT_RANK.get(p.get("verdict"), 9),
                                      p.get("number", 0)))


# 15MB, against a 16MB hard limit. The margin is the HTML, the CSS and the
# script around the images -- all of it small, none of it zero.
MAX_PAGE_BYTES = 15 * 1024 * 1024

SIZES = ("phone", "desktop")


HERE = os.path.dirname(os.path.abspath(__file__))


def _review_page():
    """The shared page builder, for its image encoders and Playwright finder."""
    sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "shared", "review_page"))
    try:
        import review_page
    finally:
        sys.path.pop(0)
    return review_page


def compress_shot(path):
    """(bytes, mime): one screenshot as a lossy WebP, else a JPEG, else the PNG as it is,
    whichever is smallest.

    Vue run 1: six full-page PNGs (three widths, before and after, of a page up to
    27188 px tall at 2x) made a 14.1 MB page; as WebP they come to 2.6 MB. Reuses
    review_page's encoders and its fit to WebP's 16383 px limit (a taller shot is scaled
    down until it fits). Lossy only: lossless never won on a real page and took most
    of a minute for six shots. With no ImageMagick or cwebp installed the PNG goes in."""
    from pathlib import Path
    rp = _review_page()
    path = Path(path)
    best = (path.read_bytes(), "image/png")
    tool = rp.image_tool()
    if tool is None:
        return best
    settings = rp.image_settings({})
    try:
        for w in rp.webp_widths(*rp.image_size(path), settings["max_width"]):
            data = rp.encode_webp(path, settings["quality"], w, False, tool)
            if data is not None and len(data) < len(best[0]):
                best = (data, "image/webp")
        if best[1] == "image/png":
            jpeg = rp.to_fallback(path, settings)
            if len(jpeg[0]) < len(best[0]):
                best = jpeg
    except (IndexError, ValueError, OSError):
        pass  # not an image the encoders can read: embed it as it is
    return best


def data_uri(path):
    data, mime = compress_shot(path)
    return "data:%s;base64,%s" % (mime, base64.b64encode(data).decode("ascii"))


def pair_shots(evidence):
    """One entry per page per size, holding the before file and the after file.

    A PAIR IS ATOMIC. Embedding the after and dropping the before leaves a
    Before/After control that swaps to a broken image -- which reads as a bug in
    the change rather than a gap in the evidence.
    """
    befores = {(s.get("slug"), s.get("size")): s for s in evidence.get("before", [])}
    after_keys = {(s.get("slug"), s.get("size")) for s in evidence.get("after", [])}
    pairs = []
    for shot in evidence.get("after", []):
        key = (shot.get("slug"), shot.get("size"))
        before_shot = befores.get(key)
        pairs.append({
            "slug": shot.get("slug"), "size": shot.get("size"),
            "pageLabel": shot.get("pageLabel") or shot.get("path"),
            "path": shot.get("path"),
            "interesting": bool(shot.get("overflow") or shot.get("errors")
                                or shot.get("redirected")),
            "before": None,
            "after": None,
            "beforeFile": (before_shot or {}).get("file"),
            "afterFile": shot.get("file"),
        })
    # A page photographed before the change but not after is an evidence gap,
    # not a page the pipeline never touched. pr_qa_findings.py already flags
    # this ("no after shot"); dropping it here silently turned a flagged gap
    # back into coverage that never happened. `embed()`'s existing "missing"
    # handling (afterFile is None here, so a real path can never exist) does
    # the rest: the viewer says the shot is missing and the pair proves nothing.
    for shot in evidence.get("before", []):
        key = (shot.get("slug"), shot.get("size"))
        if key in after_keys:
            continue
        pairs.append({
            "slug": shot.get("slug"), "size": shot.get("size"),
            "pageLabel": shot.get("pageLabel") or shot.get("path"),
            "path": shot.get("path"),
            "interesting": True,
            "before": None,
            "after": None,
            "beforeFile": shot.get("file"),
            "afterFile": None,
        })
    # Interesting pages first, then phone before desktop: if the budget bites,
    # what survives is what shows the problem, on the screen the user checks first.
    return sorted(pairs, key=lambda p: (not p["interesting"],
                                        SIZES.index(p["size"]) if p["size"] in SIZES else 9,
                                        p["slug"] or ""))


def embed(prs, budget_bytes=MAX_PAGE_BYTES):
    """Fill in data URIs, worst-PR-first, until the budget runs out."""
    spent = 0
    dropped = []
    for pr in order_prs(prs):
        pr["pairs"] = []
        for pair in pair_shots(pr.get("evidence") or {}):
            directory = (pr.get("evidence") or {}).get("dir")
            paths = [os.path.join(directory, name) if directory and name else None
                     for name in (pair["beforeFile"], pair["afterFile"])]
            if not all(p and os.path.exists(p) for p in paths):
                pair["missing"] = True
                pr["pairs"].append(pair)
                continue
            uris = [data_uri(p) for p in paths]
            cost = sum(len(u) for u in uris)
            if spent + cost > budget_bytes:
                dropped.append(f'PR #{pr.get("number")}: '
                               f'{pair["pageLabel"]} at {pair["size"]}')
                # The pair WAS captured -- only the budget dropped it. It must
                # still appear in pr["pairs"] (before/after stay None, as
                # pair_shots initialised them) so the viewer can say "dropped
                # to stay under the size limit" instead of misreporting it as
                # never photographed.
                pair["dropped"] = True
                pr["pairs"].append(pair)
                continue
            spent += cost
            pair["before"], pair["after"] = uris
            pr["pairs"].append(pair)
    return prs, dropped


CHIP = {"hold": ("Do not merge", "#b91c1c"), "unknown": ("Not reviewed", "#b45309"),
        "look": ("Look first", "#a16207"), "clean": ("Looks safe", "#15803d")}

DECISIONS = [
    ("merge-and-push", "Merge the PR and push. I will say if a migration or deploy is needed."),
    ("merge-hold-push", "Merge locally. Nothing leaves this machine."),
    ("send-back", "The findings become the brief for another attempt."),
    ("wait", "Nothing happens. You will QA it yourself."),
]


def skipped_line(skipped):
    """One line naming the open PRs this page did not cover; "" when none."""
    parts = []
    for item in skipped or []:
        reason = (item.get("reason") or "").strip() if isinstance(item, dict) else ""
        number = item.get("number") if isinstance(item, dict) else item
        if number is None or number == "":
            continue
        parts.append(f"#{number} ({reason})" if reason else f"#{number}")
    return "Other open PRs: " + "; ".join(parts) if parts else ""


def render(prs, dropped, project, repo, session=None, skipped=None):
    """The whole page, as one self-contained string."""
    payload = {
        "project": project, "repo": repo, "session": session, "dropped": dropped,
        "skippedLine": skipped_line(skipped),
        "decisions": [{"value": v, "consequence": c} for v, c in DECISIONS],
        "prs": [{
            "number": pr.get("number"), "title": pr.get("title", ""),
            # `skeleton()` always writes these keys as "" rather than omitting
            # them, so `.get(key, default)` never fires -- an unfilled field
            # rendered as a blank cell instead of falling back. `or` treats an
            # empty string the same as a missing key.
            "branch": pr.get("branch", ""), "cost": pr.get("cost") or "—",
            "tests": pr.get("tests") or "—",
            "verdict": pr.get("verdict", "unknown"),
            "chip": CHIP.get(pr.get("verdict", "unknown"), CHIP["unknown"])[0],
            "color": CHIP.get(pr.get("verdict", "unknown"), CHIP["unknown"])[1],
            "recommendation": pr.get("recommendation") or "wait",
            "narrative": pr.get("narrative", ""),
            "riseExplained": pr.get("rise_explained") or "",
            "reviewed": bool(pr.get("human_findings")),
            "absent": not (pr.get("evidence") or {}).get("present"),
            "absentReason": pr.get("absent_reason", ""),
            "unmapped": (pr.get("evidence") or {}).get("unmapped_changes", []),
            "machineNote": ((pr.get("evidence") or {}).get("note") or "")
                           if (pr.get("evidence") or {}).get("measured", True) is False
                           else "",
            "findings": merge_findings(pr.get("evidence") or {},
                                       pr.get("human_findings") or []),
            "pairs": pr.get("pairs", []),
        } for pr in order_prs(prs)],
    }
    # json.dumps does not escape "<", so an unescaped payload containing
    # "</script>" (e.g. inside a PR title) closes the element early, blanking
    # the page and letting whatever follows land in the live DOM. "<" inside a
    # JS string literal decodes back to "<", so escaping it here changes
    # nothing about the data -- it only removes the character sequence that
    # can close a tag.
    safe_payload = json.dumps(payload).replace("<", "\\u003c")
    return PAGE_TEMPLATE.replace("__TITLE__", html_escape.escape(f"{project} — PR QA")) \
                        .replace("__PAYLOAD__", safe_payload)


VALID_SEVERITIES = tuple(SEVERITY_RANK)
VALID_RECOMMENDATIONS = tuple(value for value, _ in DECISIONS)


def validate_meta(meta):
    """`meta.json` is hand-written by a session; nothing else checks its shape.
    A mistyped severity or recommendation must crash the build, not quietly
    downgrade a blocker to a gray "clean" dot sorted to the bottom of the page.
    """
    for entry in meta:
        number = entry.get("number")
        for finding in entry.get("human_findings") or []:
            severity = finding.get("severity")
            if severity not in VALID_SEVERITIES:
                raise ValueError(
                    f"PR #{number}: human_findings severity {severity!r} is not "
                    f"valid -- valid values are {', '.join(VALID_SEVERITIES)}")
        recommendation = entry.get("recommendation")
        if recommendation and recommendation not in VALID_RECOMMENDATIONS:
            raise ValueError(
                f"PR #{number}: recommendation {recommendation!r} is not valid "
                f"-- valid values are {', '.join(VALID_RECOMMENDATIONS)}")


MERGE_RECOMMENDATIONS = ("merge-and-push", "merge-hold-push")


def has_rise(finding):
    for name in ("evidence", "data"):
        value = finding.get(name)
        if isinstance(value, dict) and value.get("rise"):
            return True
    return False


def check_rise(entry, evidence):
    """Refuse a merge recommendation over a finding that rose, unless the
    session named why it is acceptable. The page must not say "merge" while its
    own capture got worse."""
    if entry.get("recommendation") not in MERGE_RECOMMENDATIONS:
        return
    found = list(evidence.get("findings") or []) + list(entry.get("human_findings") or [])
    risen = [f for f in found if has_rise(f)]
    if risen and not (entry.get("rise_explained") or "").strip():
        titles = "; ".join(f.get("title", "") for f in risen[:3])
        raise SystemExit(
            f"PR #{entry.get('number')}: recommendation {entry.get('recommendation')!r} "
            f"over a finding that rose ({titles}). Name the elements and add "
            '"rise_explained": "<one sentence on why it is acceptable>" to this PR\'s '
            "meta entry, or recommend send-back or wait.")


def load_meta(meta_path):
    """(entries, skipped). meta.json is a list of PR entries, or an object
    {"prs": [...], "skipped": [{"number": 2, "reason": "not requested"}]}."""
    with open(meta_path, encoding="utf-8") as handle:
        meta = json.load(handle)
    if isinstance(meta, dict):
        unknown = sorted(set(meta) - {"prs", "skipped"})
        if unknown:
            raise SystemExit(f"{meta_path}: unknown top-level key(s) {', '.join(unknown)}; "
                             'only "prs" and "skipped" are allowed.')
        if not isinstance(meta.get("prs"), list):
            raise SystemExit(f'{meta_path}: an object meta needs a "prs" list '
                             '(or give a bare list of PR entries).')
        return meta["prs"], meta.get("skipped") or []
    return meta, []


def build(meta_path, out_path, project, repo, session=None):
    meta, skipped = load_meta(meta_path)
    validate_meta(meta)
    prs = []
    for entry in meta:
        evidence = load_evidence(entry.get("dir"))
        human = entry.get("human_findings") or []
        check_rise(entry, evidence)
        prs.append(dict(entry, evidence=evidence,
                        verdict=effective_verdict(evidence, human)))
    embedded, dropped = embed(prs)
    page = render(embedded, dropped, project, repo, session, skipped)
    # The first run in a project has no .proofs/pages yet.
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(page)
    return page


SMOKE_CJS = os.path.join(HERE, "pr_qa_smoke.cjs")


def smoke(page_path, playwright=None):
    """Click through the built page in a real browser. Returns (ok, result);
    ok is None when Playwright is missing. Reuses review_page's finder and
    install hint rather than copying them."""
    review_page = _review_page()
    pw = review_page.find_playwright(playwright)
    if not pw:
        return None, {"error": "Playwright not found. " + review_page.HOW_TO_PY}
    node = shutil.which("node")
    if not node:
        return None, {"error": "node not found on PATH"}
    try:
        r = subprocess.run([node, SMOKE_CJS, pw, os.path.abspath(page_path)],
                           capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return False, {"ok": False, "problems": ["smoke timed out"]}
    try:
        result = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return False, {"ok": False, "problems": [(r.stdout + r.stderr).strip()[-2000:] or "smoke printed nothing"]}
    if result.get("launchFailed"):
        return None, {"error": (result.get("problems") or ["browser could not start"])[0]}
    return not result.get("problems"), result


def repo_slug():
    """owner/name from origin's URL, or None."""
    try:
        out = subprocess.run(["git", "config", "--get", "remote.origin.url"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?\s*$", (out.stdout or "").strip())
    return m.group(1) if out.returncode == 0 and m else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--meta")
    parser.add_argument("--out")
    parser.add_argument("--smoke", metavar="PAGE", help="click through a built page in headless "
                        "Chromium; prints one JSON line, exits 0 only when ok (2: Playwright missing)")
    parser.add_argument("--playwright", help="folder of an installed playwright package")
    parser.add_argument("--project", help="name for the page's top bar; default: the repo name")
    parser.add_argument("--repo", help="owner/name; default: read from the origin remote")
    parser.add_argument("--session", help="this session's name, shown in the top bar so the page can be "
                                          "matched to its session")
    args = parser.parse_args(argv)
    if args.smoke:
        ok, result = smoke(args.smoke, args.playwright)
        if ok is None:
            print(json.dumps({"ok": False, "problems": [result["error"]]}))
            return 2
        print(json.dumps({"ok": bool(ok), "problems": result.get("problems", [])}))
        return 0 if ok else 1
    if not args.meta or not args.out:
        parser.error("give --meta and --out, or --smoke PAGE")
    repo = args.repo or repo_slug() or ""
    project = args.project or (repo.split("/")[-1] if repo else "Project")
    if not args.session:
        print("warning: no --session: the reader can't tell which session this page belongs to", file=sys.stderr)
    page = build(args.meta, args.out, project, repo, args.session)
    print(f"==> {args.out}: {len(page)} bytes")
    return 0


# ---------------------------------------------------------------------------
# PAGE_TEMPLATE -- a utilitarian tool page, not an editorial one. The audience
# skews older: type stays large and readable throughout, nothing drops below
# ~15px, and there is no hero -- the verdict table is the thesis. Semantic
# color (the verdict chips, supplied per-PR from CHIP above) is kept separate
# from the page's own accent (a considered teal), per the "an inspection tool,
# not a brand moment" read of the brief.
#
# The DOM is built entirely from DATA at runtime (see the <script> below) --
# no PR title, branch or finding text is ever written into HTML by hand.
# ---------------------------------------------------------------------------
PAGE_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --bg: #f4f6f8;
    --surface: #ffffff;
    --surface-alt: #eaeef2;
    --ink: #171b21;
    --muted: #566173;
    --border: #d8dee5;
    --accent: #0d7377;
    --accent-ink: #ffffff;
    --focus: #0d7377;
    --brand: #c2410c; --session: #6d28d9;
    --radius: 12px;
    --shadow: 0 1px 2px rgba(23,27,33,.06), 0 10px 28px rgba(23,27,33,.07);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #10151a; --surface: #1a2029; --surface-alt: #212a34;
      --ink: #edf1f5; --muted: #9aa6b4; --border: #2c3542;
      --accent: #3ad8cb; --accent-ink: #08211f; --focus: #3ad8cb;
      --brand: #f08a54; --session: #c4a7ff;
      --shadow: 0 1px 2px rgba(0,0,0,.35), 0 10px 28px rgba(0,0,0,.4);
    }
  }
  :root[data-theme="dark"] {
    --bg: #10151a; --surface: #1a2029; --surface-alt: #212a34;
    --ink: #edf1f5; --muted: #9aa6b4; --border: #2c3542;
    --accent: #3ad8cb; --accent-ink: #08211f; --focus: #3ad8cb;
      --brand: #f08a54; --session: #c4a7ff;
    --shadow: 0 1px 2px rgba(0,0,0,.35), 0 10px 28px rgba(0,0,0,.4);
  }
  :root[data-theme="light"] {
    --bg: #f4f6f8; --surface: #ffffff; --surface-alt: #eaeef2;
    --ink: #171b21; --muted: #566173; --border: #d8dee5;
    --accent: #0d7377; --accent-ink: #ffffff; --focus: #0d7377;
    --brand: #c2410c; --session: #6d28d9;
    --shadow: 0 1px 2px rgba(23,27,33,.06), 0 10px 28px rgba(23,27,33,.07);
  }
  * , *::before, *::after { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    background: var(--bg); color: var(--ink);
    font: 18px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  h1, h2, h3, h4 { font-weight: 800; letter-spacing: -0.01em; text-wrap: balance; margin: 0; }
  code, .num, .repo { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  a { color: var(--accent); }
  :focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
  @media (prefers-reduced-motion: reduce) {
    * { transition: none !important; scroll-behavior: auto !important; }
  }

  .bar {
    position: sticky; top: 0; z-index: 5; display: flex; align-items: center;
    flex-wrap: wrap; gap: .5rem 1rem; padding: 1rem 1.5rem;
    background: var(--surface); border-bottom: 1px solid var(--border);
  }
  .bar .brand { font-weight: 800; font-size: 1.3rem; }
  /* the proofs mark and skill pill, as on every proofs page */
  .pf { display: inline-flex; align-items: center; gap: 10px; line-height: 1; white-space: nowrap; }
  .pf-wm { font: 600 19px/1 Georgia, Charter, "Iowan Old Style", serif; letter-spacing: -.01em; color: var(--ink); }
  .pf-wm i { color: var(--brand); font-style: italic; }
  .pf-sk { font: 600 12.5px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color: var(--brand);
           border: 1px solid color-mix(in srgb, var(--brand) 55%, transparent); border-radius: 999px; padding: 1px 9px; }
  .pf-sep { width: 1px; height: 18px; background: var(--border); margin: 0 2px; }
  .pf-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
  .bar .session { color: var(--session); font-weight: 700; }
  @media (max-width: 600px) { .pf-wm, .pf-sep { display: none; } }
  .bar .tag { color: var(--muted); }
  .bar .repo { color: var(--muted); font-size: 1rem; }
  .bar .counter {
    margin-left: auto; font-weight: 700; padding: .4rem .9rem; border-radius: 999px;
    background: var(--surface-alt); border: 1px solid var(--border);
    font-variant-numeric: tabular-nums;
  }

  .wrap { max-width: 1120px; margin: 0 auto; padding: 1.75rem 1.5rem 4rem;
          display: flex; flex-direction: column; gap: 2.25rem; }

  .empty { text-align: center; padding: 5rem 1.5rem; color: var(--muted); }
  .empty h2 { color: var(--ink); font-size: 1.9rem; margin-bottom: .5rem; }

  .verdict-wrap { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius);
                  background: var(--surface); box-shadow: var(--shadow); }
  table.verdict-table { border-collapse: collapse; width: 100%; min-width: 640px; }
  .verdict-table th, .verdict-table td { text-align: left; padding: .9rem 1.1rem;
                                          border-bottom: 1px solid var(--border); font-size: 1rem; }
  .verdict-table th { color: var(--muted); font-weight: 700; text-transform: uppercase;
                       letter-spacing: .04em; font-size: .85rem; background: var(--surface-alt); }
  .verdict-table tr:last-child td { border-bottom: none; }
  .verdict-table td.num { font-variant-numeric: tabular-nums; }

  .chip { display: inline-flex; align-items: center; padding: .3rem .75rem; border-radius: 999px;
          font-weight: 700; font-size: .95rem; color: #fff; white-space: nowrap; }
  .chip.small { font-size: .9rem; padding: .25rem .6rem; }

  .pr-card { background: var(--surface); border: 1px solid var(--border); border-left-width: 8px;
             border-radius: var(--radius); padding: 1.75rem; box-shadow: var(--shadow);
             display: flex; flex-direction: column; gap: 1.35rem; scroll-margin-top: 5rem; }
  .pr-head { display: flex; flex-wrap: wrap; align-items: baseline; gap: .75rem 1rem; }
  .pr-head h2 { font-size: 1.5rem; }
  .pr-meta { display: flex; flex-wrap: wrap; gap: .5rem 1.5rem; color: var(--muted); font-size: 1rem; }
  .pr-meta code { background: var(--surface-alt); padding: .15rem .45rem; border-radius: 6px; }
  .narrative { margin: 0; color: var(--ink); }

  .notice { background: var(--surface-alt); border: 1px solid var(--border); border-radius: 8px;
            padding: .9rem 1.1rem; font-size: 1rem; }
  .notice.warn { border-color: #b45309; }

  .viewer { display: flex; flex-direction: column; gap: .9rem; }
  .page-tabs { display: flex; flex-wrap: wrap; gap: .5rem; }
  .page-tab { border: 1px solid var(--border); background: var(--surface); border-radius: 8px;
              padding: .4rem .85rem; font-size: .95rem; cursor: pointer; color: var(--ink); }
  .page-tab[aria-pressed="true"] { border-color: var(--accent); font-weight: 700;
                                    background: var(--surface-alt); }
  .viewer-controls { display: flex; flex-wrap: wrap; gap: 1rem; }
  .segmented { display: inline-flex; border: 1px solid var(--border); border-radius: 999px;
               overflow: hidden; }
  .seg-btn { border: 0; background: var(--surface); color: var(--ink); padding: .6rem 1.2rem;
             font-size: 1rem; font-weight: 600; cursor: pointer; }
  .seg-btn + .seg-btn { border-left: 1px solid var(--border); }
  .seg-btn[aria-pressed="true"] { background: var(--accent); color: var(--accent-ink); }

  .shot-frame { position: relative; border: 1px solid var(--border); border-radius: 10px;
                overflow: hidden; background: var(--surface-alt); min-height: 240px;
                display: flex; align-items: center; justify-content: center; }
  .shot-img { display: block; max-width: 100%; height: auto; }
  /* The phone shot is shown at its TRUE phone width, never stretched across the card. */
  .shot-frame.is-phone { max-width: 390px; margin: 0 auto; width: 100%; }
  .shot-placeholder { display: none; padding: 2.5rem 1.5rem; text-align: center;
                       color: var(--muted); font-size: 1.05rem; max-width: 32rem; }
  .shot-caption { margin: 0; color: var(--muted); font-size: .95rem; }

  ol.findings { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .75rem; }
  .finding { display: flex; gap: .85rem; padding: 1rem 1.1rem; border: 1px solid var(--border);
             border-radius: 8px; background: var(--surface-alt); }
  .finding .num { font-weight: 800; color: var(--muted); min-width: 1.9rem;
                   font-variant-numeric: tabular-nums; }
  .finding .dot { width: .65rem; height: .65rem; border-radius: 50%; margin-top: .55rem; flex: none; }
  .finding-body h4 { font-size: 1.05rem; margin: 0 0 .3rem; }
  .finding-body p { margin: 0; color: var(--ink); }
  .finding-body .src { display: inline-block; margin-top: .4rem; font-size: .85rem;
                        text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }

  .decisions { display: flex; flex-direction: column; gap: .75rem; }
  .decision-option { display: flex; gap: .9rem; align-items: flex-start; border: 1px solid var(--border);
                      border-radius: 10px; padding: 1.05rem 1.15rem; cursor: pointer; }
  .decision-option:hover { border-color: var(--accent); }
  .decision-option input { width: 1.4rem; height: 1.4rem; margin-top: .15rem; accent-color: var(--accent); flex: none; }
  .decision-option .consequence { display: block; margin-top: .2rem; color: var(--muted); font-weight: 400; }
  .decision-option .rec { margin-left: .6rem; font-size: .8rem; font-weight: 700; color: var(--accent);
                           text-transform: uppercase; letter-spacing: .04em; }

  .copy-panel { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
                padding: 1.75rem; box-shadow: var(--shadow); display: flex; flex-direction: column; gap: 1rem; }
  .copy-panel p.consequence { margin: 0; color: var(--muted); }
  button.copy-btn { align-self: flex-start; background: var(--accent); color: var(--accent-ink);
                     border: 0; border-radius: 999px; padding: .9rem 1.9rem; font-size: 1.1rem;
                     font-weight: 700; cursor: pointer; }
  textarea.copy-fallback { width: 100%; box-sizing: border-box; font: inherit; padding: 10px;
    border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); color: inherit; }
  button.copy-btn:hover { filter: brightness(1.05); }
</style>
</head>
<body>
<main id="app"></main>
<script>
const DATA = __PAYLOAD__;
(function () {
  "use strict";
  var SIZES = ["phone", "desktop"];
  var decisions = Object.create(null);

  function el(tag, attrs) {
    var node = document.createElement(tag);
    var children = Array.prototype.slice.call(arguments, 2);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        var value = attrs[key];
        if (value === null || value === undefined || value === false) return;
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = value;
        else if (key.indexOf("on") === 0 && typeof value === "function") {
          node.addEventListener(key.slice(2), value);
        } else {
          node.setAttribute(key, value);
        }
      });
    }
    children.forEach(function (child) {
      if (child === null || child === undefined) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function fmtSize(size) { return size === "phone" ? "Phone" : "Desktop"; }
  function fmtLabel(label) { return label === "before" ? "Before (main)" : "After (this PR)"; }
  function humanizeDecision(value) {
    return {
      "merge-and-push": "Merge and push",
      "merge-hold-push": "Merge, hold the push",
      "send-back": "Send it back",
      "wait": "Wait",
    }[value] || value;
  }

  function groupPages(pairs) {
    var pages = [];
    var bySlug = Object.create(null);
    pairs.forEach(function (pair) {
      var key = pair.slug || pair.pageLabel || pair.path || "page";
      if (!bySlug[key]) {
        bySlug[key] = { key: key, label: pair.pageLabel || pair.path || key,
                        sizes: Object.create(null) };
        pages.push(bySlug[key]);
      }
      bySlug[key].sizes[pair.size] = pair;
    });
    return pages;
  }

  function buildViewer(pr) {
    var pairs = pr.pairs || [];
    var pages = groupPages(pairs);
    var viewer = el("div", { class: "viewer" });
    if (!pages.length) {
      var none = el("div", { class: "shot-placeholder",
        text: "No screenshots were captured for this PR." });
      none.style.display = "block";
      viewer.appendChild(none);
      return viewer;
    }

    var worstFinding = (pr.findings || [])[0];
    var worstSize = (worstFinding && worstFinding.evidence &&
                     SIZES.indexOf(worstFinding.evidence.size) >= 0)
      ? worstFinding.evidence.size : null;

    var state = { page: 0, size: null, label: "after" };
    if (worstSize) {
      for (var i = 0; i < pages.length; i++) {
        if (pages[i].sizes[worstSize]) { state.page = i; break; }
      }
    }
    state.size = (worstSize && pages[state.page].sizes[worstSize]) ? worstSize
      : (pages[state.page].sizes.phone ? "phone" : Object.keys(pages[state.page].sizes)[0]);

    var pageTabs = el("div", { class: "page-tabs" });
    var controls = el("div", { class: "viewer-controls" });
    var labelSeg = el("div", { class: "segmented", role: "tablist", "aria-label": "Before or after" });
    var sizeSeg = el("div", { class: "segmented", role: "tablist", "aria-label": "Screen size" });
    var frame = el("div", { class: "shot-frame" });
    var img = el("img", { class: "shot-img", "data-shot": "", alt: "" });
    var placeholder = el("div", { class: "shot-placeholder" });
    var caption = el("p", { class: "shot-caption" });
    frame.appendChild(img);
    frame.appendChild(placeholder);

    function currentPair() {
      return pages[state.page].sizes[state.size] || null;
    }

    function paint() {
      var pair = currentPair();
      var src = null;
      var note = "";
      if (!pair) {
        note = "This page was not photographed at " + state.size + " width.";
      } else if (pair.missing) {
        note = "No " + state.label + " shot: this pair proves nothing -- the file was missing.";
      } else if (pair.dropped) {
        note = "No " + state.label + " shot here -- it was dropped to keep the page under the size limit.";
      } else {
        src = pair[state.label];
        if (!src) {
          note = "No " + state.label + " shot available.";
        }
      }
      if (src) {
        img.setAttribute("src", src);
        img.alt = pr.title + " -- " + fmtLabel(state.label) + " -- " + pages[state.page].label +
          " -- " + fmtSize(state.size);
        img.style.display = "";
        placeholder.style.display = "none";
      } else {
        img.removeAttribute("src");
        img.alt = "";
        img.style.display = "none";
        placeholder.textContent = note;
        placeholder.style.display = "flex";
      }
      frame.classList.toggle("is-phone", state.size === "phone");
      caption.textContent = pages[state.page].label + " \\u00b7 " + fmtSize(state.size) +
        " \\u00b7 " + fmtLabel(state.label);
      Array.prototype.forEach.call(labelSeg.querySelectorAll("[data-label]"), function (btn) {
        btn.setAttribute("aria-pressed", String(btn.getAttribute("data-label") === state.label));
      });
      Array.prototype.forEach.call(sizeSeg.querySelectorAll("[data-size]"), function (btn) {
        btn.setAttribute("aria-pressed", String(btn.getAttribute("data-size") === state.size));
      });
      Array.prototype.forEach.call(pageTabs.querySelectorAll("[data-page]"), function (btn) {
        btn.setAttribute("aria-pressed", String(Number(btn.getAttribute("data-page")) === state.page));
      });
    }

    ["before", "after"].forEach(function (labelValue) {
      labelSeg.appendChild(el("button", {
        type: "button", class: "seg-btn", "data-label": labelValue,
        text: labelValue === "before" ? "Before" : "After",
        onclick: function () { state.label = labelValue; paint(); },
      }));
    });
    SIZES.forEach(function (sizeValue) {
      sizeSeg.appendChild(el("button", {
        type: "button", class: "seg-btn", "data-size": sizeValue,
        text: fmtSize(sizeValue),
        onclick: function () { state.size = sizeValue; paint(); },
      }));
    });
    if (pages.length > 1) {
      pages.forEach(function (page, idx) {
        pageTabs.appendChild(el("button", {
          type: "button", class: "page-tab", "data-page": String(idx), text: page.label,
          onclick: function () {
            state.page = idx;
            if (!pages[idx].sizes[state.size]) {
              state.size = pages[idx].sizes.phone ? "phone" : Object.keys(pages[idx].sizes)[0];
            }
            paint();
          },
        }));
      });
      viewer.appendChild(pageTabs);
    }

    controls.appendChild(labelSeg);
    controls.appendChild(sizeSeg);
    viewer.appendChild(controls);
    viewer.appendChild(frame);
    viewer.appendChild(caption);
    paint();
    return viewer;
  }

  function buildFindings(findings) {
    if (!findings || !findings.length) {
      return el("p", { class: "notice", text: "No findings were recorded." });
    }
    var colors = { blocker: "#b91c1c", warning: "#b45309", good: "#15803d" };
    var list = el("ol", { class: "findings" });
    findings.forEach(function (finding, idx) {
      var dot = el("span", { class: "dot",
        style: "background:" + (colors[finding.severity] || "#566173") });
      var body = el("div", { class: "finding-body" },
        el("h4", { text: finding.title || "Untitled finding" }),
        el("p", { text: finding.detail || "" }),
        el("span", { class: "src",
          text: finding.source === "human" ? "From review" : "From automated evidence" }));
      list.appendChild(el("li", { class: "finding" },
        el("span", { class: "num", text: String(idx + 1) }), dot, body));
    });
    return list;
  }

  function buildDecisions(pr) {
    var wrap = el("div", { class: "decisions" });
    DATA.decisions.forEach(function (option) {
      var inputId = "decision-" + pr.number + "-" + option.value;
      var input = el("input", {
        type: "radio", name: "decision-" + pr.number, value: option.value, id: inputId,
        onchange: function (event) {
          if (event.target.checked) {
            decisions[pr.number] = option.value;
            updateCounter();
          }
        },
      });
      var text = el("span", {},
        el("strong", { text: humanizeDecision(option.value) }),
        el("span", { class: "consequence", text: option.consequence }));
      var recommended = option.value === pr.recommendation
        ? el("span", { class: "rec", text: "Recommended" }) : null;
      wrap.appendChild(el("label", { class: "decision-option", "for": inputId },
        input, text, recommended));
    });
    return wrap;
  }

  function buildCard(pr) {
    var card = el("div", { class: "pr-card", id: "pr-" + pr.number,
      style: "border-left-color:" + pr.color });
    var chip = el("span", { class: "chip", style: "background:" + pr.color, text: pr.chip });
    card.appendChild(el("div", { class: "pr-head" }, chip,
      el("h2", { text: "PR #" + pr.number + " -- " + pr.title })));
    card.appendChild(el("div", { class: "pr-meta" },
      el("span", {}, "Branch ", el("code", { text: pr.branch || "--" })),
      el("span", { text: "Cost " + (pr.cost || "--") }),
      el("span", { text: "Tests " + (pr.tests || "--") })));
    if (pr.narrative) card.appendChild(el("p", { class: "narrative", text: pr.narrative }));
    if (pr.riseExplained) {
      card.appendChild(el("p", { class: "notice warn" },
        el("strong", { text: "Why merge anyway: " }), pr.riseExplained));
    }
    if (!pr.reviewed) {
      card.appendChild(el("p", { class: "notice warn",
        text: "This PR is not yet read by a reviewer -- the findings below are machine-only." }));
    }
    if (pr.absent) {
      card.appendChild(el("p", { class: "notice warn",
        text: "No automated evidence was found for this PR" +
          (pr.absentReason ? (": " + pr.absentReason) : ".") }));
    }
    if (pr.unmapped && pr.unmapped.length) {
      card.appendChild(el("p", { class: "notice" },
        el("strong", { text: "Changed but not screenshotted: " }),
        el("span", { text: pr.unmapped.join(", ") })));
    }
    card.appendChild(buildViewer(pr));
    card.appendChild(el("h3", { text: "Findings" }));
    if (pr.machineNote) {
      card.appendChild(el("p", { class: "notice warn",
        text: "Machine check: " + pr.machineNote }));
    }
    card.appendChild(buildFindings(pr.findings));
    card.appendChild(el("h3", { text: "Your decision" }));
    card.appendChild(buildDecisions(pr));
    return card;
  }

  function buildVerdictTable(prs) {
    var wrap = el("div", { class: "verdict-wrap" });
    var table = el("table", { class: "verdict-table" });
    table.appendChild(el("thead", {}, el("tr", {},
      el("th", { text: "PR" }), el("th", { text: "Verdict" }), el("th", { text: "Cost" }),
      el("th", { text: "Tests" }), el("th", { text: "Recommendation" }))));
    var tbody = el("tbody");
    prs.forEach(function (pr) {
      tbody.appendChild(el("tr", {},
        el("td", {}, el("a", { href: "#pr-" + pr.number,
          text: "#" + pr.number + " " + pr.title })),
        el("td", {}, el("span", { class: "chip small", style: "background:" + pr.color,
          text: pr.chip })),
        el("td", { class: "num", text: pr.cost || "--" }),
        el("td", { text: pr.tests || "--" }),
        el("td", { text: humanizeDecision(pr.recommendation) })));
    });
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
  }

  function buildExportText(prs) {
    return prs.map(function (pr) {
      var chosen = decisions[pr.number] || "(no decision yet)";
      return "PR #" + pr.number + " -- " + pr.title + "\\nBranch: " + (pr.branch || "--") +
        "\\nDecision: " + chosen;
    }).join("\\n\\n");
  }

  function buildCopyPanel(prs) {
    var panel = el("div", { class: "copy-panel" });
    panel.appendChild(el("h3", { text: "Copy my decisions" }));
    panel.appendChild(el("p", { class: "consequence",
      text: "One block per PR, in the order above. Paste this back to act on it." }));
    var button = el("button", { type: "button", class: "copy-btn", "data-copy": "",
      text: "Copy my decisions" });
    button.addEventListener("click", function () {
      var text = buildExportText(prs);
      var done = function () {
        button.textContent = "Copied";
        setTimeout(function () { button.textContent = "Copy my decisions"; }, 2000);
      };
      // No secure context (http on a LAN address) means no clipboard; a failed
      // write is the same story. Never say "Copied" unless it was.
      var fallback = function () {
        var box = panel.querySelector("textarea[data-copy-fallback]");
        if (!box) {
          box = el("textarea", { class: "copy-fallback", "data-copy-fallback": "", readonly: "",
            rows: "8", "aria-label": "Decisions to copy" });
          panel.appendChild(box);
        }
        box.value = text;
        box.focus();
        box.select();
        button.textContent = "Select all and copy from the box";
      };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        try {
          navigator.clipboard.writeText(text).then(done, fallback);
        } catch (err) {
          fallback();
        }
      } else {
        fallback();
      }
    });
    panel.appendChild(button);
    return panel;
  }

  function updateCounter() {
    var answered = Object.keys(decisions).length;
    Array.prototype.forEach.call(document.querySelectorAll("[data-counter]"), function (node) {
      node.textContent = answered + " of " + DATA.prs.length + " decided";
    });
  }

  function buildBar() {
    var mark = el("span", { class: "pf" },
      el("span", { class: "pf-wm", "aria-hidden": "true" }, "pro", el("i", { text: "o" }), "fs"),
      el("span", { class: "pf-sk", "aria-hidden": "true", text: "pr-qa" }),
      el("span", { class: "pf-sr", text: "Proofs, pr-qa" }),
      el("span", { class: "pf-sep", "aria-hidden": "true" }));
    return el("header", { class: "bar" }, mark,
      el("span", { class: "brand", text: DATA.project }),
      DATA.session ? el("span", { class: "tag", text: "\\u00b7" }) : null,
      DATA.session ? el("span", { class: "session", text: DATA.session }) : null,
      el("span", { class: "tag", text: "\\u00b7" }),
      el("span", { class: "repo", text: DATA.repo }),
      el("span", { class: "counter", "data-counter": "",
        text: "0 of " + DATA.prs.length + " decided" }));
  }

  function main() {
    var app = document.getElementById("app");
    app.appendChild(buildBar());
    var wrap = el("div", { class: "wrap" });
    if (!DATA.prs.length) {
      wrap.appendChild(el("div", { class: "empty" },
        el("h2", { text: "Nothing waiting" }),
        el("p", { text: "No open pull requests need a decision right now." })));
      if (DATA.skippedLine) {
        wrap.appendChild(el("p", { class: "notice skipped", text: DATA.skippedLine }));
      }
      app.appendChild(wrap);
      return;
    }
    wrap.appendChild(buildVerdictTable(DATA.prs));
    if (DATA.skippedLine) {
      wrap.appendChild(el("p", { class: "notice skipped", text: DATA.skippedLine }));
    }
    if (DATA.dropped && DATA.dropped.length) {
      wrap.appendChild(el("p", { class: "notice",
        text: DATA.dropped.length + " screenshot pair(s) were dropped to stay under the " +
          "page size limit: " + DATA.dropped.join("; ") }));
    }
    DATA.prs.forEach(function (pr) { wrap.appendChild(buildCard(pr)); });
    wrap.appendChild(buildCopyPanel(DATA.prs));
    app.appendChild(wrap);
  }

  main();
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
