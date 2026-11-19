#!/usr/bin/env python3
"""Build a self-contained review page from a JSON spec, and check it.

Usage:
  review_page.py SPEC.json --out PAGE.html [--no-check]   build (then check)
  review_page.py --check PAGE.html                        node --check + structure
  review_page.py --smoke PAGE.html [--playwright DIR]     click through in Chromium

Three modes share one engine: "review" (decision buttons per item: design-review,
article-copy-edit, photo-picker, style-guide), "questions" (working-log questions
and QA checks) and "log" (the working log itself). The spec format is documented
in reference/review-page.md at the plugin root. Python 3 stdlib only; node is
needed for --check and --smoke, Playwright only for --smoke.
"""
import argparse
import base64
import html
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE = HERE / "engine.js"
STYLE = HERE / "style.css"
SMOKE = HERE / "smoke.cjs"

# Decision sets. Each button: state, label, label_variant (used when the item has
# variants), export, export_variant ({sel} = selected variant text), comment
# ("required" opens the box, "optional" keeps it closed), meaning (legend text).
PRESETS = {
    "copy-edit": {
        "variant_word": "Option", "pending": "PENDING", "mark_read": False,
        "buttons": [
            {"state": "deny", "label": "✕ Keep Original", "export": "DENY (Keep Original)", "comment": "optional"},
            {"state": "accept", "label": "✓ Use Edit", "export": "ACCEPT (Use Edit)", "comment": "optional"},
            {"state": "accept-comment", "label": "✓ Approve with Comment", "export": "ACCEPT WITH COMMENT", "comment": "required"},
            {"state": "revise", "label": "↻ Request Revision", "export": "REVISE", "comment": "required"},
        ]},
    "design-review": {
        "variant_word": "Variant", "pending": "PENDING", "mark_read": True,
        "buttons": [
            {"state": "deny", "label": "✕ Keep Original", "export": "DENY", "comment": "optional"},
            {"state": "accept", "label": "✓ Use Proposed", "label_variant": "✓ Use Selected",
             "export": "ACCEPT (Use Proposed)", "export_variant": "ACCEPT (Use Selected: {sel})", "comment": "optional"},
            {"state": "accept-comment", "label": "✓ Approve with Comment", "export": "ACCEPT WITH COMMENT",
             "export_variant": "ACCEPT WITH COMMENT (Use Selected: {sel})", "comment": "required"},
            {"state": "revise", "label": "↻ Request Revision", "export": "REVISE", "comment": "required"},
        ]},
    "photo-picker": {
        "variant_word": "Option", "pending": "PENDING", "mark_read": False,
        "buttons": [
            {"state": "deny", "label": "Keep None", "export": "DENY (Keep None)", "comment": "optional"},
            {"state": "accept", "label": "Use Selected", "export": "ACCEPT",
             "export_variant": "ACCEPT (Use Selected: {sel})", "comment": "optional"},
            {"state": "accept-comment", "label": "Approve with Comment", "export": "ACCEPT WITH COMMENT",
             "export_variant": "ACCEPT WITH COMMENT (Use Selected: {sel})", "comment": "required"},
            {"state": "revise", "label": "Request Revision", "export": "REVISE", "comment": "required"},
        ]},
    "style-guide": {
        "variant_word": "Option", "pending": None, "mark_read": False, "comment_always": True,
        "works_as_designed": True, "legend": True,
        "buttons": [
            {"state": "deny", "label": "✕ Deny", "export": "DENY", "comment": "optional",
             "meaning": "Reject the proposal. With Works as Designed checked, the current state becomes the rule."},
            {"state": "revise", "label": "↻ Request Revision", "export": "REVISE", "comment": "required",
             "meaning": "Try something else; the comment says what."},
            {"state": "accept-now", "label": "✓ Accept: Apply Everywhere Now", "export": "ACCEPT (Apply Everywhere Now)",
             "export_variant": "ACCEPT (Apply Everywhere Now: {sel})", "comment": "optional",
             "meaning": "Record the rule and retrofit every page now."},
            {"state": "accept-later", "label": "✓ Accept: Record for Later", "export": "ACCEPT (Record for Later)",
             "export_variant": "ACCEPT (Record for Later: {sel})", "comment": "optional",
             "meaning": "Record the rule; the retrofit becomes a to-do."},
        ]},
}
CATEGORY_COLORS = ["#2563eb", "#b45309", "#047857", "#9333ea", "#be123c", "#0e7490", "#4d7c0f", "#c2410c"]
MODES = ("review", "questions", "log")


class SpecError(Exception):
    pass


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "page"


def resolve_files(obj, base):
    """Replace any string "@file:relative/path" with that file's text."""
    if isinstance(obj, dict):
        return {k: resolve_files(v, base) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_files(v, base) for v in obj]
    if isinstance(obj, str) and obj.startswith("@file:"):
        p = (base / obj[6:]).resolve()
        if not p.is_file():
            raise SpecError("@file not found: %s" % obj[6:])
        return p.read_text()
    return obj


def data_uri(path):
    mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return "data:%s;base64,%s" % (mime, base64.b64encode(path.read_bytes()).decode("ascii"))


def load_spec(spec_path):
    path = Path(spec_path)
    spec = json.loads(path.read_text())
    spec = resolve_files(spec, path.parent)
    mode = spec.get("mode", "review")
    if mode not in MODES:
        raise SpecError("mode must be one of %s" % ", ".join(MODES))
    spec["mode"] = mode
    if not spec.get("title"):
        raise SpecError("title is required")
    assets = {}
    for name, rel in (spec.get("assets") or {}).items():
        p = (path.parent / rel).resolve()
        if not p.is_file():
            raise SpecError("asset %r not found: %s" % (name, rel))
        assets[name] = data_uri(p)
    spec["_assets"] = assets
    return spec


def decisions_for(spec):
    d = spec.get("decisions", "copy-edit")
    if isinstance(d, str):
        if d not in PRESETS:
            raise SpecError("unknown decisions preset %r (have: %s)" % (d, ", ".join(PRESETS)))
        d = dict(PRESETS[d])
    elif isinstance(d, dict):
        base = dict(PRESETS.get(d.get("preset", ""), {}))
        base.update({k: v for k, v in d.items() if k != "preset"})
        d = base
    else:
        raise SpecError("decisions must be a preset name or an object")
    if not d.get("buttons"):
        raise SpecError("decisions need buttons")
    for b in d["buttons"]:
        for k in ("state", "label", "export"):
            if not b.get(k):
                raise SpecError("every decision button needs %s" % k)
    return d


# ---------------------------------------------------------------- review mode

def build_review(spec):
    dec = decisions_for(spec)
    word = dec.get("variant_word", "Option")
    sections = spec.get("sections")
    if sections is None:
        sections = [{"title": None, "items": spec.get("items", [])}]
    cats, items_js, n, seen = [], [], 0, set()
    for sec in sections:
        for it in sec.get("items", []):
            n += 1
            it.setdefault("num", str(n))
            it["id"] = str(it.get("id") or it["num"])
            if it["id"] in seen:
                raise SpecError("duplicate item id %r" % it["id"])
            seen.add(it["id"])
            if not it.get("label"):
                raise SpecError("item %s needs a label" % it["id"])
            for i, v in enumerate(it.get("variants") or []):
                v.setdefault("key", chr(65 + i))
                v.setdefault("label", "%s %s" % (word, v["key"]))
            if it.get("category") and it["category"] not in cats:
                cats.append(it["category"])
            items_js.append({"id": it["id"], "num": it["num"], "label": it["label"],
                             "category": it.get("category"),
                             "variants": [{"key": v["key"], "label": v["label"], "name": v.get("name", "")}
                                          for v in it.get("variants") or []],
                             "selected": it.get("selected")})
    colors = dict(zip(cats, CATEGORY_COLORS * 4))
    colors.update(spec.get("category_colors") or {})

    out = []
    if dec.get("legend"):
        out.append('<div class="rp-legend" aria-label="What each decision means">')
        for b in dec["buttons"]:
            out.append('<span class="rp-legend-item"><span class="rp-swatch rp-st-%s"></span><b>%s</b> %s</span>'
                       % (esc(b["state"]), esc(b["label"]), esc(b.get("meaning", ""))))
        out.append("</div>")
    if spec.get("preview_toggle"):
        out.append('<div class="rp-preview-toggle"><span>Examples shown in</span>'
                   '<button type="button" class="rp-chip-btn" data-preview-set="light" aria-pressed="true">Light</button>'
                   '<button type="button" class="rp-chip-btn" data-preview-set="dark" aria-pressed="false">Dark</button></div>')
    if spec.get("filters") and cats:
        out.append('<nav class="rp-filters" aria-label="Filter by category">'
                   '<button type="button" class="rp-chip-btn" data-filter="" aria-pressed="true">All <span data-count=""></span></button>')
        for c in cats:
            out.append('<button type="button" class="rp-chip-btn" data-filter="%s" aria-pressed="false" style="--cat:%s">%s <span data-count="%s"></span></button>'
                       % (esc(c), esc(colors[c]), esc(c), esc(c)))
        out.append("</nav>")
    for sec in sections:
        out.append('<section class="rp-section">')
        if sec.get("title"):
            out.append("<h2>%s</h2>" % esc(sec["title"]))
        if sec.get("intro_html"):
            out.append('<div class="rp-section-intro">%s</div>' % sec["intro_html"])
        if not sec.get("items"):
            out.append('<p class="rp-empty">%s</p>' % (sec.get("empty_html") or "Nothing in this section."))
        for it in sec.get("items", []):
            out.append(review_item(it, dec, colors))
        out.append("</section>")
    js = {"mode": "review", "header": spec.get("header") or "[%s]" % spec["title"],
          "items": items_js, "decisions": {k: dec.get(k) for k in
                                           ("buttons", "pending", "mark_read", "comment_always", "works_as_designed")}}
    return "\n".join(out), js


def review_item(it, dec, colors):
    iid, variants = esc(it["id"]), it.get("variants") or []
    rec = it.get("recommended")
    badge = ""
    if rec is not None:
        badge = '<span class="rp-badge %s">%s</span>' % (("rp-rec", "Recommended") if rec else ("rp-notrec", "Not recommended"))
    cat = ""
    if it.get("category"):
        cat = '<span class="rp-cat" style="--cat:%s">%s</span>' % (esc(colors[it["category"]]), esc(it["category"]))
    loc = '<span class="rp-loc">%s</span>' % esc(it["location"]) if it.get("location") else ""
    h = ['<article class="rp-item" id="item-%s" data-id="%s" data-category="%s">' % (iid, iid, esc(it.get("category") or "")),
         '<header class="rp-item-head"><span class="rp-num">%s</span><h3 class="rp-label">%s</h3>%s%s%s'
         '<span class="rp-pill" data-pill>Pending</span></header>' % (esc(it["num"]), esc(it["label"]), loc, cat, badge)]
    if it.get("history_html"):
        h.append('<div class="rp-history">%s</div>' % it["history_html"])
    if it.get("body_html"):
        h.append('<div class="rp-body">%s</div>' % it["body_html"])
    if variants:
        h.append('<div class="rp-gallery" role="group" aria-label="Choose one">')
        for v in variants:
            name = ' <span class="rp-vname">%s</span>' % esc(v["name"]) if v.get("name") else ""
            rv = ' <span class="rp-vrec">Recommended</span>' if v.get("recommended") else ""
            note = '<div class="rp-vnote">%s</div>' % v["note_html"] if v.get("note_html") else ""
            h.append('<div class="rp-variant" role="button" tabindex="0" aria-pressed="false" data-variant="%s">'
                     '<div class="rp-vhead"><span class="rp-vcheck" aria-hidden="true"></span>%s%s%s</div>'
                     '<div class="rp-vbody">%s</div>%s</div>'
                     % (esc(v["key"]), esc(v["label"]), name, rv, v.get("html", ""), note))
        h.append("</div>")
    if it.get("reason_html"):
        h.append('<div class="rp-reason"><b>Reason</b> %s</div>' % it["reason_html"])
    h.append('<div class="rp-actions">')
    for b in dec["buttons"]:
        label = b.get("label_variant", b["label"]) if variants else b["label"]
        h.append('<button type="button" class="btn rp-btn rp-st-%s" data-item="%s" data-choice="%s" aria-pressed="false">%s</button>'
                 % (esc(b["state"]), iid, esc(b["state"]), esc(label)))
    if dec.get("mark_read"):
        h.append('<label class="rp-read"><input type="checkbox" data-read="%s"> Mark as read</label>' % iid)
    h.append("</div>")
    always = dec.get("comment_always")
    h.append('<div class="rp-comment"%s><label for="comment-%s">Comment</label>'
             '<textarea id="comment-%s" data-comment="%s" rows="3"></textarea>'
             % ("" if always else " hidden", iid, iid, iid))
    if dec.get("works_as_designed"):
        h.append('<label class="rp-wad" hidden><input type="checkbox" data-wad="%s"> Works as Designed</label>' % iid)
    h.append("</div></article>")
    return "\n".join(h)


# ------------------------------------------------------------- questions mode

def build_questions(spec):
    proj = spec.get("project") or {}
    for k in ("name", "stream"):
        if not proj.get(k):
            raise SpecError("questions mode needs project.%s" % k)
    qs, qa, seen = spec.get("questions") or [], spec.get("qa") or [], set()
    out = []
    if qs:
        out.append('<h2>%s</h2>' % esc(spec.get("questions_heading", "Open — needs you")))
    for i, q in enumerate(qs, 1):
        qid = q.get("qid")
        if not qid or qid in seen:
            raise SpecError("every question needs a unique qid (got %r)" % qid)
        seen.add(qid)
        out.append('<div class="q" data-qid="%s" data-ask="%s" data-round="%s">'
                   % (esc(qid), esc(q.get("ask", qid)), esc(q.get("round", proj.get("round", "?")))))
        out.append('<div class="q-num">Question %d <span class="qid">· id: %s</span></div>' % (i, esc(qid)))
        out.append('<div class="q-ask">%s</div>' % esc(q.get("ask", qid)))
        if q.get("why_html"):
            out.append('<div class="q-why">%s</div>' % q["why_html"])
        if q.get("mockups_html"):
            out.append('<div class="frames">%s</div>' % q["mockups_html"])
        out.append('<div class="opts">')
        for o in q.get("options") or []:
            rec = ' <span class="rec">— RECOMMENDED</span>' if o.get("recommended") else ""
            note = '<span class="opt-note">%s</span>' % o["note_html"] if o.get("note_html") else ""
            out.append('<label class="opt"><input type="radio" name="%s" value="%s"><span><span class="opt-label">%s%s</span>%s</span></label>'
                       % (esc(qid), esc(o.get("value") or o["label"]), esc(o["label"]), rec, note))
        out.append("</div>")
        out.append('<div class="notes"><label for="n-%s">%s</label><textarea id="n-%s" data-note="%s"></textarea></div></div>'
                   % (esc(qid), esc(q.get("notes_label", "Or in your own words")), esc(qid), esc(qid)))
    if qa:
        out.append('<h2>%s</h2>' % esc(spec.get("qa_heading", "QA after deploy — check these off")))
        if spec.get("qa_intro_html"):
            out.append('<p class="fine">%s</p>' % spec["qa_intro_html"])
    for i, c in enumerate(qa, 1):
        qid = c.get("qaid")
        if not qid or qid in seen:
            raise SpecError("every QA item needs a unique qaid (got %r)" % qid)
        seen.add(qid)
        out.append('<div class="qa" data-qaid="%s" data-check="%s">' % (esc(qid), esc(c.get("check", qid))))
        out.append('<div class="qa-num">QA %d <span class="qid">· id: %s</span></div>' % (i, esc(qid)))
        out.append('<div class="qa-what">%s</div>' % esc(c.get("check", qid)))
        if c.get("why_html"):
            out.append('<div class="qa-why">%s</div>' % c["why_html"])
        out.append('<div class="opts qa-opts">')
        for val, lab in (("PASS", "Pass"), ("FAIL", "Fail"), ("COULDN'T TEST", "Couldn't test")):
            out.append('<label class="opt"><input type="radio" name="%s" value="%s"><span class="opt-label">%s</span></label>'
                       % (esc(qid), esc(val), lab))
        out.append("</div>")
        out.append('<div class="notes"><label for="n-%s">%s</label><textarea id="n-%s" data-note="%s"></textarea></div></div>'
                   % (esc(qid), esc(c.get("notes_label", "What happened")), esc(qid), esc(qid)))
    js = {"mode": "questions", "format": spec.get("format", "working-log questions v1.2"),
          "project": proj.get("name"), "stream": proj.get("stream"), "round": proj.get("round", "?"),
          "artifact": proj.get("artifact", "(the published URL of this page)"),
          "questions": [{"qid": q["qid"], "ask": q.get("ask", q["qid"]),
                         "round": str(q.get("round", proj.get("round", "?")))} for q in qs],
          "qa": [{"qaid": c["qaid"], "check": c.get("check", c["qaid"])} for c in qa]}
    return "\n".join(out), js


# ------------------------------------------------------------------- log mode

def build_log(spec):
    proj = spec.get("project") or {}
    for k in ("name", "session"):
        if not proj.get(k):
            raise SpecError("log mode needs project.%s" % k)
    entries, seen, out = spec.get("entries") or [], set(), []
    for e in entries:
        eid = e.get("id")
        if not eid or eid in seen:
            raise SpecError("every entry needs a unique id (got %r)" % eid)
        seen.add(eid)
        status = e.get("status", "Background")
        out.append('<article class="rp-entry" data-entry="%s">' % esc(eid))
        out.append('<header class="rp-entry-head"><span class="rp-num">%s</span><h3>%s</h3>'
                   '<span class="rp-status rp-status-%s">%s</span></header>'
                   % (esc(eid), esc(e.get("title", "")), slug(status), esc(status)))
        if e.get("lede"):
            out.append('<p class="rp-lede">%s</p>' % e["lede"])
        if e.get("detail_html"):
            out.append('<div class="rp-detail">%s</div>' % e["detail_html"])
        groups = e.get("questions") or []
        qnames = set()
        for g in groups:
            q = g.get("q")
            if not q or q in qnames:
                raise SpecError("entry %s: every option group needs a unique q" % eid)
            qnames.add(q)
            out.append('<fieldset class="rp-opts" data-q="%s">' % esc(q))
            if g.get("label"):
                out.append("<legend>%s</legend>" % esc(g["label"]))
            for o in g.get("options") or []:
                out.append('<label class="rp-opt"><input type="radio" name="%s::%s" value="%s"><span>%s</span></label>'
                           % (esc(eid), esc(q), esc(o), esc(o)))
            out.append("</fieldset>")
        out.append('<div class="rp-entry-foot"><label class="rp-note-label">Note<textarea data-note="%s" rows="2"></textarea></label>'
                   '<label class="rp-tick"><input type="checkbox" data-tick="%s"> Read this</label></div></article>'
                   % (esc(eid), esc(eid)))
    js = {"mode": "log", "project": proj.get("name"), "session": proj.get("session"), "repo": proj.get("repo"),
          "details": spec.get("details") or [],
          "entries": [{"id": e["id"], "title": e.get("title", ""), "groups": [g["q"] for g in e.get("questions") or []]}
                      for e in entries]}
    return "\n".join(out), js


# --------------------------------------------------------------------- page

def page(spec):
    mode = spec["mode"]
    body, js = {"review": build_review, "questions": build_questions, "log": build_log}[mode](spec)
    proj = spec.get("project") or {}
    key = spec.get("storage_key") or "proofs:%s:%s" % (mode, slug("%s %s %s" % (
        proj.get("name", ""), proj.get("session", proj.get("stream", "")), spec["title"])))
    js["key"] = key
    css_vars = "".join("%s:%s;" % (k, v) for k, v in (spec.get("vars") or {}).items())
    assets = "".join("--asset-%s:url(%s);" % (k, v) for k, v in spec["_assets"].items())
    head = spec.get("head_html", "")
    css = STYLE.read_text()
    extra = spec.get("css", "")
    html_out = ['<!doctype html>', '<html lang="en">', "<head>", '<meta charset="utf-8">',
                '<meta name="viewport" content="width=device-width, initial-scale=1">',
                "<title>%s</title>" % esc(spec["title"]), head,
                "<style>\n%s\n:root{%s%s}\n%s\n</style>" % (css, css_vars, assets, extra),
                "</head>", '<body class="rp rp-mode-%s">' % mode]
    if mode == "log":
        repo = ' · <span>%s</span>' % esc(proj["repo"]) if proj.get("repo") else ""
        marker = spec.get("marker") or " · ".join(x for x in (
            spec.get("version") and '<b>%s</b>' % esc(spec["version"]),
            spec.get("updated") and "updated %s" % esc(spec["updated"]),
            spec.get("entries") and "entry %s" % esc(spec["entries"][0]["id"])) if x)
        html_out.append('<div class="rp-projectbar">%s · <b class="rp-session">%s</b>%s · Working log</div>'
                        % (esc(proj["name"]), esc(proj["session"]), repo))
        html_out.append('<div class="rp-statusbar"><span id="rp-tally"></span><span class="rp-marker">%s</span>'
                        '<button type="button" class="rp-copy" data-copy>Copy my replies</button></div>' % marker)
    elif mode == "questions":
        html_out.append('<div class="bar"><div class="bar-title">%s</div><div class="tally" id="rp-tally">—</div>'
                        '<button class="ghost" id="rp-clear" type="button">Clear</button>'
                        '<button class="copy" type="button" data-copy>%s</button></div>'
                        % (spec.get("bar_title_html") or esc(proj["name"]), esc(spec.get("copy_label", "Copy my answers"))))
    html_out.append('<main class="rp-main" data-preview="light">')
    if spec.get("heading"):
        html_out.append('<h1 class="rp-h1">%s</h1>' % esc(spec["heading"]))
    if spec.get("intro_html"):
        html_out.append('<div class="rp-intro">%s</div>' % spec["intro_html"])
    if mode == "log" and spec.get("facts"):
        html_out.append('<dl class="rp-facts">%s</dl>' % "".join(
            "<div><dt>%s</dt><dd>%s</dd></div>" % (esc(k), v) for k, v in spec["facts"]))
    html_out.append(body)
    if spec.get("after_html"):
        html_out.append('<div class="rp-after">%s</div>' % spec["after_html"])
    if mode == "log":
        html_out.append('<section class="rp-export"><h2>Copy my replies</h2><label class="rp-note-label">Anything else'
                        '<textarea data-extra rows="3"></textarea></label>'
                        '<button type="button" class="rp-copy" data-copy>Copy my replies</button></section>')
    html_out.append("</main>")
    if mode == "review":
        html_out.append('<div class="rp-bar"><div class="rp-progress" aria-hidden="true"></div><span id="rp-tally"></span>'
                        '<button type="button" class="rp-copy" data-copy>%s</button></div>'
                        % esc(spec.get("copy_label", "Copy My Decisions")))
    html_out.append('<div class="rp-fallback" hidden role="dialog" aria-label="Copy the text"><div class="rp-fallback-in">'
                    '<p>Copying was blocked here, so nothing was copied. The text is selected: copy it with Cmd+C or Ctrl+C.</p>'
                    '<textarea readonly></textarea><button type="button" data-close>Close</button></div></div>')
    html_out.append('<div class="rp-flash" role="status" aria-live="polite">Copied — paste it back to me</div>')
    spec_json = json.dumps(js, ensure_ascii=False).replace("<", "\\u003c")
    html_out.append('<script type="application/json" id="rp-spec">%s</script>' % spec_json)
    html_out.append("<script>\n%s\n</script>" % ENGINE.read_text())
    html_out.append("</body></html>")
    text = "\n".join(html_out)
    for k, v in spec["_assets"].items():
        text = text.replace("{{asset:%s}}" % k, v)
    return text


# -------------------------------------------------------------------- check

SCRIPT_RX = re.compile(r"<script(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>(.*?)</script>", re.S | re.I)


def check(path):
    text = Path(path).read_text()
    errs = []
    node = shutil.which("node")
    if not node:
        errs.append("node is not installed; it is needed for the syntax check")
    scripts = SCRIPT_RX.findall(text)
    if not scripts:
        errs.append("no inline <script> found")
    for i, s in enumerate(scripts):
        if not node:
            break
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(s)
        r = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
        os.unlink(f.name)
        if r.returncode:
            errs.append("script %d fails node --check:\n%s" % (i + 1, r.stderr.strip()))
    m = re.search(r'<script type="application/json" id="rp-spec">(.*?)</script>', text, re.S)
    spec = None
    if not m:
        errs.append("no rp-spec block: was this page made by review_page.py?")
    else:
        try:
            spec = json.loads(m.group(1))
        except ValueError as e:
            errs.append("rp-spec is not valid JSON: %s" % e)
    title = re.search(r"<title>(.*?)</title>", text, re.S)
    if not title or not title.group(1).strip():
        errs.append("page has no <title>")
    ids = re.findall(r'\sid="([^"]+)"', text)
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errs.append("duplicate element ids: %s" % ", ".join(dup))
    if spec:
        mode = spec.get("mode")
        if mode == "review":
            n = len(re.findall(r'<article class="rp-item"', text))
            if n != len(spec["items"]):
                errs.append("%d item cards for %d items" % (n, len(spec["items"])))
            for it in spec["items"]:
                need = len(spec["decisions"]["buttons"])
                got = len(re.findall(r'data-item="%s" data-choice=' % re.escape(html.escape(it["id"], quote=True)), text))
                if got != need:
                    errs.append("item %s has %d decision buttons, expected %d" % (it["id"], got, need))
            if not spec.get("header", "").startswith("["):
                errs.append("export header must be bracketed")
        if mode == "log" and title and not html.unescape(title.group(1)).startswith(spec.get("session") or "\0"):
            errs.append("log <title> must lead with the session name")
        if mode == "questions" and len(re.findall(r'class="q" data-qid=', text)) + len(re.findall(r'class="qa" data-qaid=', text)) == 0:
            errs.append("questions page has no questions or QA items")
    for name in re.findall(r"\{\{asset:([\w-]+)\}\}", text):
        errs.append("unresolved asset placeholder {{asset:%s}}" % name)
    return errs


def find_playwright(arg):
    for c in (arg, os.environ.get("PROOFS_PLAYWRIGHT")):
        if c and (Path(c) / "package.json").is_file():
            return str(Path(c).resolve())
    node = shutil.which("node")
    if node:
        r = subprocess.run([node, "-e", "console.log(require.resolve('playwright/package.json'))"],
                           capture_output=True, text=True, cwd=os.getcwd())
        if r.returncode == 0:
            return str(Path(r.stdout.strip()).parent)
    return None


def smoke(path, playwright=None):
    """Click through the page in headless Chromium. Returns (ok, result dict)."""
    pw = find_playwright(playwright)
    if not pw:
        return None, {"error": "Playwright not found: pass --playwright DIR or set PROOFS_PLAYWRIGHT"}
    r = subprocess.run([shutil.which("node"), str(SMOKE), pw, str(Path(path).resolve())],
                       capture_output=True, text=True, timeout=180)
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return False, {"error": (r.stdout + r.stderr).strip()[-2000:]}
    return not res.get("problems"), res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spec", nargs="?", help="JSON spec to build")
    ap.add_argument("--out", help="where to write the page")
    ap.add_argument("--no-check", action="store_true", help="skip the check after building")
    ap.add_argument("--check", metavar="PAGE", help="check a built page")
    ap.add_argument("--smoke", metavar="PAGE", help="click through a built page in headless Chromium")
    ap.add_argument("--playwright", help="folder of an installed playwright package")
    a = ap.parse_args(argv)
    if a.check or a.smoke:
        target = a.check or a.smoke
        errs = check(target)
        for e in errs:
            print("check: " + e, file=sys.stderr)
        if errs:
            return 1
        if a.smoke:
            ok, res = smoke(target, a.playwright)
            print(json.dumps(res, indent=2, ensure_ascii=False))
            if ok is None:
                return 2
            return 0 if ok else 1
        print("check: ok (%s)" % target)
        return 0
    if not a.spec or not a.out:
        ap.error("give SPEC.json --out PAGE.html, or --check PAGE, or --smoke PAGE")
    try:
        text = page(load_spec(a.spec))
    except (SpecError, ValueError, KeyError) as e:
        print("spec error: %s" % e, file=sys.stderr)
        return 1
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(text)
    print("wrote %s (%d KB)" % (a.out, len(text.encode()) // 1024))
    if a.no_check:
        return 0
    errs = check(a.out)
    for e in errs:
        print("check: " + e, file=sys.stderr)
    if not errs:
        print("check: ok")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
