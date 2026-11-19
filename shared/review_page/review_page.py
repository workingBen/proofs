#!/usr/bin/env python3
"""Build a self-contained review page from a JSON spec, and check it.

Usage:
  review_page.py SPEC.json --out PAGE.html [--no-check]   build (then check)
  review_page.py --check PAGE.html                        node --check + structure
  review_page.py --smoke PAGE.html [--playwright DIR]     click through in Chromium

Four modes share one engine: "review" (decision buttons per item: design-review,
article-copy-edit, photo-picker, style-guide), "questions" (a standalone questions
or QA checklist page), "session" (working-log's session page: questions, checks,
log and decided on one URL) and "log" (a log-only page). The spec format is documented
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
MODES = ("review", "questions", "log", "session")


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


def data_uri(path, data=None, mime=None):
    mime = mime or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return "data:%s;base64,%s" % (mime, base64.b64encode(path.read_bytes() if data is None else data).decode("ascii"))


# Screenshots (PNG and JPEG assets) are converted to WebP when the page is built,
# which makes a page of screenshots several times lighter with no visible change.
# The defaults are still being chosen; the spec keys image_quality / image_max_width
# and the env vars PROOFS_IMAGE_QUALITY / PROOFS_IMAGE_MAX_WIDTH override them
# (env first, then spec, then these).
DEFAULT_IMAGE_QUALITY = 70
DEFAULT_IMAGE_MAX_WIDTH = None  # None keeps the screenshot's own width
CONVERTIBLE = {".png", ".jpg", ".jpeg"}
WARN_PAGE_BYTES = 3 * 1024 * 1024
BLANK_GIF = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="


def image_settings(spec, env=None):
    env = os.environ if env is None else env
    def pick(env_key, spec_key, default, lo, hi):
        raw = env.get(env_key) or spec.get(spec_key)
        if raw in (None, ""):
            return default
        try:
            v = int(raw)
        except (TypeError, ValueError):
            raise SpecError("%s must be a whole number, got %r" % (spec_key, raw))
        if not lo <= v <= hi:
            raise SpecError("%s must be between %d and %d, got %d" % (spec_key, lo, hi, v))
        return v
    return {"quality": pick("PROOFS_IMAGE_QUALITY", "image_quality", DEFAULT_IMAGE_QUALITY, 1, 100),
            "max_width": pick("PROOFS_IMAGE_MAX_WIDTH", "image_max_width", DEFAULT_IMAGE_MAX_WIDTH, 16, 20000)}


def image_tool():
    """The first WebP encoder found: ("magick", path) or ("cwebp", path), else None."""
    for name in ("magick", "cwebp"):
        found = shutil.which(name)
        if found:
            return name, found
    return None


def image_width(path):
    """Pixel width of a PNG or JPEG, read from its header (stdlib only)."""
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big")
    i = 2
    while i + 9 < len(data) and data[:2] == b"\xff\xd8":
        if data[i] != 0xFF:
            i += 1
            continue
        marker, size = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            return int.from_bytes(data[i + 7:i + 9], "big")
        i += 2 + size
    return None


def encode_webp(path, quality, width, lossless, tool):
    """WebP bytes for one encoding (resized to width when given), or None on failure."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out.webp"
        name, exe = tool
        if name == "magick":
            cmd = ([exe, str(path)] + (["-resize", "%dx" % width] if width else [])
                   + (["-define", "webp:lossless=true"] if lossless else ["-quality", str(quality)]) + [str(out)])
        else:
            cmd = ([exe, "-quiet"] + (["-lossless"] if lossless else ["-q", str(quality)])
                   + (["-resize", str(width), "0"] if width else []) + [str(path), "-o", str(out)])
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0 or not out.is_file():
            return None
        return out.read_bytes()


def to_webp(path, settings, tool):
    """The smallest WebP for a PNG or JPEG, or None when the original is smaller.

    Both lossy (at the quality setting) and lossless are tried, because flat UI
    screenshots are often smaller lossless. When the screenshot is wider than
    max_width, the shrunk versions are tried too, and win only when actually
    smaller: shrinking a crisp shot can make the lossless file bigger. Never
    upscales."""
    q, mw = settings["quality"], settings["max_width"]
    width = image_width(path)
    widths = [None] + ([mw] if mw and width and width > mw else [])
    best = None
    for w in widths:
        for lossless in (False, True):
            data = encode_webp(path, q, w, lossless, tool)
            if data is not None and (best is None or len(data) < len(best)):
                best = data
    if best is None or len(best) >= path.stat().st_size:
        return None
    return best


def embed_asset(path, settings, tool, report):
    size = path.stat().st_size
    if path.suffix.lower() in CONVERTIBLE:
        if tool is None:
            report["missing_tool"] = True
        else:
            data = to_webp(path, settings, tool)
            if data is not None:
                report["converted"] += 1
                report["before"] += size
                report["after"] += len(data)
                return data_uri(path, data, "image/webp")
    return data_uri(path)


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
    settings = image_settings(spec)
    tool = image_tool()
    report = {"converted": 0, "before": 0, "after": 0, "missing_tool": False, "settings": settings}
    for name, rel in (spec.get("assets") or {}).items():
        p = (path.parent / rel).resolve()
        if not p.is_file():
            raise SpecError("asset %r not found: %s" % (name, rel))
        assets[name] = embed_asset(p, settings, tool, report)
    spec["_assets"] = assets
    spec["_image_report"] = report
    return spec


def decisions_for(d):
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


# ------------------------------------------------------------------ sections
#
# A page is a frame (the mode: its chrome, tally and export header) around a list
# of sections. Each section has a kind, renders its own items and contributes its
# own block to the export, so one page can mix kinds.

KINDS = ("review", "questions", "links", "qa", "log", "decided")
DEFAULT_KIND = {"review": "review", "questions": "questions", "log": "log", "session": "log"}
DEFAULT_TITLE = {"questions": "Open — needs you", "qa": "QA after deploy — check these off",
                 "links": "Other pages waiting on you", "decided": "Decided"}
SESSION_TITLE = {"questions": "Waiting on you", "links": "Other pages waiting on you", "qa": "Checks for you",
                 "log": "Log", "decided": "Decided"}
# The session page's fixed order. Open questions come first, directly under the
# sticky bar: the reader must never scroll past reports to find what needs them.
SESSION_ORDER = ("questions", "links", "qa", "log", "decided")
# Kinds that ask the reader to act; on question and session pages they render
# before the heading, intro and facts.
ACTION_KINDS = ("questions", "links", "qa")
READ_ONLY_KINDS = ("links", "decided")


def flat_sections(spec):
    mode, secs = spec["mode"], []
    if mode == "review":
        return [{"items": spec.get("items", [])}]
    if spec.get("questions"):
        secs.append({"kind": "questions", "title": spec.get("questions_heading"), "items": spec["questions"]})
    if spec.get("links"):
        secs.append({"kind": "links", "title": spec.get("links_heading"), "items": spec["links"]})
    if spec.get("qa"):
        secs.append({"kind": "qa", "title": spec.get("qa_heading"), "intro_html": spec.get("qa_intro_html"),
                     "items": spec["qa"]})
    if mode in ("log", "session"):
        secs.append({"kind": "log", "title": spec.get("log_heading"), "items": spec.get("entries", [])})
    if spec.get("decided"):
        secs.append({"kind": "decided", "title": spec.get("decided_heading"), "items": spec["decided"]})
    return secs


def sections_of(spec):
    mode, secs = spec["mode"], spec.get("sections")
    if secs is None:  # flat shorthands
        secs = flat_sections(spec)
    ids = set()
    for i, sec in enumerate(secs):
        sec.setdefault("kind", DEFAULT_KIND[mode])
        if sec["kind"] not in KINDS:
            raise SpecError("section kind must be one of %s" % ", ".join(KINDS))
        if mode == "session" and sec["kind"] == "review":
            raise SpecError("a session page holds no review sections: design reviews and copy edits stay "
                            "their own page, linked from the session page with `links`")
        sec["id"] = str(sec.get("id") or "s%d" % (i + 1))
        if sec["id"] in ids:
            raise SpecError("duplicate section id %r" % sec["id"])
        ids.add(sec["id"])
        sec["items"] = sec.get("items") or []
        if mode == "session":
            sec["title"] = sec.get("title") or SESSION_TITLE[sec["kind"]]
    # Enforce the order (a stable sort, so sections of one kind keep theirs).
    if mode == "session":
        secs = sorted(secs, key=lambda s: SESSION_ORDER.index(s["kind"]))
    elif mode == "questions":
        secs = sorted(secs, key=lambda s: s["kind"] != "questions")
    return secs


class Ctx:
    def __init__(self, spec, secs):
        self.spec, self.n, self.seen = spec, 0, set()
        self.cats = []
        for sec in secs:
            if sec["kind"] == "review":
                sec["_dec"] = decisions_for(sec.get("decisions", spec.get("decisions", "copy-edit")))
                for it in sec["items"]:
                    if it.get("category") and it["category"] not in self.cats:
                        self.cats.append(it["category"])
        self.colors = dict(zip(self.cats, CATEGORY_COLORS * 4))
        self.colors.update(spec.get("category_colors") or {})

    def claim(self, ident, what):
        if not ident or ident in self.seen:
            raise SpecError("every %s needs an id unique on the page (got %r)" % (what, ident))
        self.seen.add(ident)


def render_review(sec, ctx):
    dec, out, items = sec["_dec"], [], []
    word = dec.get("variant_word", "Option")
    for it in sec["items"]:
        ctx.n += 1
        it.setdefault("num", str(ctx.n))
        it["id"] = str(it.get("id") or it["num"])
        if it["id"] in ctx.seen:
            raise SpecError("duplicate item id %r" % it["id"])
        ctx.claim(it["id"], "item")
        if not it.get("label"):
            raise SpecError("item %s needs a label" % it["id"])
        for i, v in enumerate(it.get("variants") or []):
            v.setdefault("key", chr(65 + i))
            v.setdefault("label", "%s %s" % (word, v["key"]))
        out.append(review_item(it, dec, ctx.colors))
        items.append({"id": it["id"], "num": it["num"], "label": it["label"], "category": it.get("category"),
                      "variants": [{"key": v["key"], "label": v["label"], "name": v.get("name", "")}
                                   for v in it.get("variants") or []],
                      "selected": it.get("selected")})
    js = {"items": items, "decisions": {k: dec.get(k) for k in
                                        ("buttons", "pending", "mark_read", "comment_always", "works_as_designed")}}
    return out, js


def notes_box(qid, label):
    return ('<div class="notes"><label for="n-%s">%s</label><textarea id="n-%s" data-note="%s"></textarea></div>'
            % (esc(qid), esc(label), esc(qid), esc(qid)))


def render_questions(sec, ctx):
    out, items, rnd = [], [], (ctx.spec.get("project") or {}).get("round", "?")
    for i, q in enumerate(sec["items"], 1):
        qid = q.get("qid")
        ctx.claim(qid, "question qid")
        ask, r = q.get("ask", qid), str(q.get("round", rnd))
        out.append('<div class="q" data-qid="%s" data-ask="%s" data-round="%s">' % (esc(qid), esc(ask), esc(r)))
        out.append('<div class="q-num">Question %d <span class="qid">· id: %s</span></div>' % (i, esc(qid)))
        out.append('<div class="q-ask">%s</div>' % esc(ask))
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
        out.append("</div>" + notes_box(qid, q.get("notes_label", "Or in your own words")) + "</div>")
        items.append({"qid": qid, "ask": ask, "round": r})
    return out, {"items": items}


def render_qa(sec, ctx):
    out, items = [], []
    for i, c in enumerate(sec["items"], 1):
        qid = c.get("qaid")
        ctx.claim(qid, "QA item qaid")
        check_text = c.get("check", qid)
        out.append('<div class="qa" data-qaid="%s" data-check="%s">' % (esc(qid), esc(check_text)))
        out.append('<div class="qa-num">QA %d <span class="qid">· id: %s</span></div>' % (i, esc(qid)))
        out.append('<div class="qa-what">%s</div>' % esc(check_text))
        if c.get("why_html"):
            out.append('<div class="qa-why">%s</div>' % c["why_html"])
        out.append('<div class="opts qa-opts">')
        for val, lab in (("PASS", "Pass"), ("FAIL", "Fail"), ("COULDN'T TEST", "Couldn't test")):
            out.append('<label class="opt"><input type="radio" name="%s" value="%s"><span class="opt-label">%s</span></label>'
                       % (esc(qid), esc(val), lab))
        out.append("</div>" + notes_box(qid, c.get("notes_label", "What happened")) + "</div>")
        items.append({"qaid": qid, "check": check_text})
    return out, {"items": items}


def render_log(sec, ctx):
    out, items = [], []
    for e in sec["items"]:
        eid = e.get("id")
        ctx.claim(eid, "entry id")
        status = e.get("status", "Background")
        out.append('<article class="rp-entry" data-entry="%s">' % esc(eid))
        out.append('<header class="rp-entry-head"><span class="rp-num">%s</span><h3>%s</h3>'
                   '<span class="rp-status rp-status-%s">%s</span></header>'
                   % (esc(eid), esc(e.get("title", "")), slug(status), esc(status)))
        if e.get("lede"):
            out.append('<p class="rp-lede">%s</p>' % e["lede"])
        if e.get("detail_html"):
            out.append('<div class="rp-detail">%s</div>' % e["detail_html"])
        qnames = []
        if ctx.spec["mode"] == "session" and e.get("questions"):
            raise SpecError("entry %s: on a session page a question goes in `questions`, so it sits at the top "
                            "under Waiting on you, not inside a log entry" % eid)
        for g in e.get("questions") or []:
            q = g.get("q")
            if not q or q in qnames:
                raise SpecError("entry %s: every option group needs a unique q" % eid)
            qnames.append(q)
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
        items.append({"id": eid, "title": e.get("title", ""), "groups": qnames})
    return out, {"items": items}


def render_links(sec, ctx):
    out = ['<ul class="rp-links">']
    for ln in sec["items"]:
        if not ln.get("label") or not ln.get("url"):
            raise SpecError("every link needs a label and a url")
        status = ': <span class="rp-link-status">%s</span>' % esc(ln["status"]) if ln.get("status") else ""
        out.append('<li><b>%s</b>%s <a href="%s" target="_blank" rel="noopener">%s</a></li>'
                   % (esc(ln["label"]), status, esc(ln["url"]), esc(ln.get("link_text", "Open it"))))
    out.append("</ul>")
    return out, {"items": []}


def render_decided(sec, ctx):
    n = len(sec["items"])
    out = ['<details class="rp-decided"%s><summary>%d settled — show them</summary><ul>'
           % (" open" if sec.get("open") else "", n)]
    for d in sec["items"]:
        ident = '<span class="rp-num">%s</span> ' % esc(d["id"]) if d.get("id") else ""
        what = esc(d.get("title", ""))
        dec = ' — <span class="rp-decided-what">%s</span>' % esc(d["decision"]) if d.get("decision") else ""
        when = ' <span class="rp-decided-when">%s</span>' % esc(d["when"]) if d.get("when") else ""
        out.append("<li>%s%s%s%s</li>" % (ident, what, dec, when))
    out.append("</ul></details>")
    return out, {"items": []}


RENDER = {"review": render_review, "questions": render_questions, "qa": render_qa, "log": render_log,
          "links": render_links, "decided": render_decided}


def render_sections(spec):
    """Return (preamble html, [(kind, section html)], js sections)."""
    secs = sections_of(spec)
    ctx = Ctx(spec, secs)
    out, js, chunks = [], [], []
    first_dec = next((s["_dec"] for s in secs if s["kind"] == "review"), None)
    if first_dec and first_dec.get("legend"):
        out.append('<div class="rp-legend" aria-label="What each decision means">')
        for b in first_dec["buttons"]:
            out.append('<span class="rp-legend-item"><span class="rp-swatch rp-st-%s"></span><b>%s</b> %s</span>'
                       % (esc(b["state"]), esc(b["label"]), esc(b.get("meaning", ""))))
        out.append("</div>")
    if spec.get("preview_toggle"):
        out.append('<div class="rp-preview-toggle"><span>Examples shown in</span>'
                   '<button type="button" class="rp-chip-btn" data-preview-set="light" aria-pressed="true">Light</button>'
                   '<button type="button" class="rp-chip-btn" data-preview-set="dark" aria-pressed="false">Dark</button></div>')
    if spec.get("filters") and ctx.cats:
        out.append('<nav class="rp-filters" aria-label="Filter by category">'
                   '<button type="button" class="rp-chip-btn" data-filter="" aria-pressed="true">All <span data-count=""></span></button>')
        for c in ctx.cats:
            out.append('<button type="button" class="rp-chip-btn" data-filter="%s" aria-pressed="false" style="--cat:%s">%s <span data-count="%s"></span></button>'
                       % (esc(c), esc(ctx.colors[c]), esc(c), esc(c)))
        out.append("</nav>")
    mode = spec["mode"]
    for sec in secs:
        kind = sec["kind"]
        body, sjs = RENDER[kind](sec, ctx)
        if not sec["items"] and (mode == "session" or kind in READ_ONLY_KINDS
                                 or (kind in ("questions", "qa") and not sec.get("title"))):
            continue  # a section shows only when it has content
        h = ['<section class="rp-section rp-kind-%s" data-section="%s">' % (kind, esc(sec["id"]))]
        title = sec.get("title") or DEFAULT_TITLE.get(kind)
        if title:
            count = ""
            if mode == "session" and kind in ("questions", "qa"):
                n = len(sec["items"])
                count = ' <span class="rp-count">%d %s</span>' % (n, ("question" if kind == "questions" else "check")
                                                                 + ("" if n == 1 else "s"))
            h.append("<h2>%s%s</h2>" % (esc(title), count))
        if sec.get("intro_html"):
            h.append('<div class="rp-section-intro">%s</div>' % sec["intro_html"])
        if not sec["items"] and kind == "review":
            h.append('<p class="rp-empty">%s</p>' % (sec.get("empty_html") or "Nothing in this section."))
        h.extend(body)
        h.append("</section>")
        chunks.append((kind, "\n".join(h)))
        sjs.update({"id": sec["id"], "kind": kind})
        js.append(sjs)
    return "\n".join(out), chunks, js


def frame_js(spec):
    mode, proj = spec["mode"], spec.get("project") or {}
    if mode == "review":
        return {"header": spec.get("header") or "[%s]" % spec["title"]}
    if mode == "questions":
        for k in ("name", "stream"):
            if not proj.get(k):
                raise SpecError("questions mode needs project.%s" % k)
        asks = bool(spec.get("questions")) or any(s.get("kind") == "questions" and s.get("items")
                                                  for s in spec.get("sections") or [])
        return {"format": spec.get("format", "questions v1.3" if asks else "qa-checklist v1.0"),
                "verb": "answers" if asks else "results", "project": proj.get("name"),
                "stream": proj.get("stream"), "round": proj.get("round", "?"),
                "artifact": proj.get("artifact", "(the published URL of this page)")}
    for k in ("name", "session"):
        if not proj.get(k):
            raise SpecError("%s mode needs project.%s" % (mode, k))
    out = {"project": proj.get("name"), "session": proj.get("session"), "repo": proj.get("repo"),
           "details": spec.get("details") or []}
    if mode == "session":
        out["artifact"] = proj.get("artifact")
    return out


# --------------------------------------------------------------------- page

def page(spec):
    mode = spec["mode"]
    js = frame_js(spec)
    preamble, chunks, js["sections"] = render_sections(spec)
    js["mode"] = mode
    proj = spec.get("project") or {}
    js["key"] = spec.get("storage_key") or "proofs:%s:%s" % (mode, slug("%s %s %s" % (
        proj.get("name", ""), proj.get("session", proj.get("stream", "")), spec["title"])))
    css_vars = "".join("%s:%s;" % (k, v) for k, v in (spec.get("vars") or {}).items())
    assets = "/*rp-assets*/"
    html_out = ['<!doctype html>', '<html lang="en">', "<head>", '<meta charset="utf-8">',
                '<meta name="viewport" content="width=device-width, initial-scale=1">',
                "<title>%s</title>" % esc(spec["title"]), spec.get("head_html", ""),
                "<style>\n%s\n:root{%s%s}\n%s\n</style>" % (STYLE.read_text(), css_vars, assets, spec.get("css", "")),
                "</head>", '<body class="rp rp-mode-%s">' % mode]
    if mode in ("log", "session"):
        repo = ' · <span>%s</span>' % esc(proj["repo"]) if proj.get("repo") else ""
        first = next((s["items"][0] for s in js["sections"] if s["kind"] == "log" and s["items"]), None)
        marker = spec.get("marker") or " · ".join(x for x in (
            spec.get("version") and '<b>%s</b>' % esc(spec["version"]),
            spec.get("updated") and "updated %s" % esc(spec["updated"]),
            first and "entry %s" % esc(first["id"])) if x)
        html_out.append('<div class="rp-topbars"><div class="rp-projectbar"><span class="rp-pb-x">%s · </span><b class="rp-session">%s</b><span class="rp-pb-x">%s · %s</span></div>'
                        % (esc(proj["name"]), esc(proj["session"]), repo,
                           "Session page" if mode == "session" else "Working log"))
        html_out.append('<div class="rp-statusbar"><span id="rp-tally"></span><span class="rp-marker">%s</span>'
                        '<button type="button" class="rp-copy" data-copy>Copy<span class="rp-copy-x"> my replies</span></button></div></div>' % marker)
    elif mode == "questions":
        html_out.append('<div class="bar"><div class="bar-title">%s</div><div class="tally" id="rp-tally">—</div>'
                        '<button class="ghost" id="rp-clear" type="button">Clear</button>'
                        '<button class="copy" type="button" data-copy>%s</button></div>'
                        % (spec.get("bar_title_html") or esc(proj["name"]), esc(spec.get("copy_label", "Copy my answers"))))
    html_out.append('<main class="rp-main" data-preview="light">')
    context = []
    if spec.get("heading"):
        context.append('<h1 class="rp-h1">%s</h1>' % esc(spec["heading"]))
    if spec.get("intro_html"):
        context.append('<div class="rp-intro">%s</div>' % spec["intro_html"])
    if mode in ("log", "session") and spec.get("facts"):
        context.append('<dl class="rp-facts">%s</dl>' % "".join(
            "<div><dt>%s</dt><dd>%s</dd></div>" % (esc(k), v) for k, v in spec["facts"]))
    if mode in ("questions", "session"):
        # What needs the reader comes first, directly under the sticky bar; the
        # heading, intro and facts are context and go below it.
        action = [h for k, h in chunks if k in ACTION_KINDS]
        rest = [h for k, h in chunks if k not in ACTION_KINDS]
        if context and action:
            context = ['<div class="rp-context">'] + context + ["</div>"]
        html_out.extend(action + context + ([preamble] if preamble else []) + rest)
    else:
        html_out.extend(context + [preamble] + [h for _, h in chunks])
    if spec.get("after_html"):
        html_out.append('<div class="rp-after">%s</div>' % spec["after_html"])
    if mode in ("log", "session"):
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
    return place_assets(text, spec["_assets"])


def place_assets(text, assets):
    """Put each asset's bytes in the page exactly once. A font in @font-face is
    inlined there; other CSS uses (url({{asset:x}}) or var(--asset-x)) read the :root variable; a single HTML use with no CSS use
    gets the data URI inline; several HTML uses point at the variable and a small
    script copies it into each attribute when the page loads."""
    root, fill = [], False
    # @font-face cannot read CSS variables, so a font's data URI goes inline there.
    text = re.sub(r"@font-face\s*\{(?:[^{}]|\{\{asset:[\w-]+\}\})*\}",
                  lambda m: re.sub(r"\{\{asset:([\w-]+)\}\}",
                                   lambda a: assets.get(a.group(1), a.group(0)), m.group(0)), text)
    for k, v in assets.items():
        ph = "{{asset:%s}}" % k
        for q in ("", "'", '"'):
            text = text.replace("url(%s%s%s)" % (q, ph, q), "var(--asset-%s)" % k)
        css_use = ("var(--asset-%s)" % k) in text
        html_uses = text.count(ph)
        if html_uses == 1 and not css_use:
            text = text.replace(ph, v)
            continue
        if html_uses:
            text, n = re.subn(r'([\w-]+)=(\\?)"%s\\?"' % re.escape(ph),
                              lambda m: '%s=%s"%s%s" data-rp-asset=%s"%s %s%s"' % (
                                  m.group(1), m.group(2), BLANK_GIF, m.group(2), m.group(2), m.group(1), k, m.group(2)),
                              text)
            fill = fill or n > 0
            text = text.replace(ph, v)  # anything left is not an attribute: inline it
        if css_use or html_uses:
            root.append("--asset-%s:url(%s);" % (k, v))
    text = text.replace("/*rp-assets*/", "".join(root), 1)
    if fill:
        text = text.replace("</body></html>", "<script>\n%s\n</script>\n</body></html>" % ASSET_FILL, 1)
    return text


ASSET_FILL = """document.querySelectorAll("[data-rp-asset]").forEach(function (el) {
  var p = el.getAttribute("data-rp-asset").split(" ");
  var v = getComputedStyle(document.documentElement).getPropertyValue("--asset-" + p[1]).trim();
  var m = v.match(/^url\\(["']?([\\s\\S]*?)["']?\\)$/);
  if (m) el.setAttribute(p[0], m[1]);
});"""


def size_warning(text, spec):
    """A warning line when the page is over WARN_PAGE_BYTES, naming the largest assets."""
    total = len(text.encode())
    if total <= WARN_PAGE_BYTES:
        return None
    big = sorted(spec["_assets"].items(), key=lambda kv: -len(kv[1]))[:3]
    names = ", ".join("%s (%d KB)" % (k, len(v) // 1024) for k, v in big)
    return ("warning: the page is %.1f MB, over %d MB. Largest assets: %s. Lower image_quality "
            "or set image_max_width, or split the review." % (total / 1048576, WARN_PAGE_BYTES // 1048576, names or "none"))


def image_line(spec):
    r = spec.get("_image_report") or {}
    if r.get("converted"):
        return "images: %d converted to WebP (smaller of lossy at quality %d and lossless%s) (%d KB -> %d KB)" % (
            r["converted"], r["settings"]["quality"],
            ", max width %d" % r["settings"]["max_width"] if r["settings"]["max_width"] else "",
            r["before"] // 1024, r["after"] // 1024)
    if r.get("missing_tool"):
        return "images: no magick or cwebp found, so screenshots were embedded as they are (install ImageMagick or libwebp to shrink them)"
    return None


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


# -------------------------------------------------------------------- check

SCRIPT_RX = re.compile(r"<script(?![^>]*\bsrc=)(?![^>]*application/json)[^>]*>(.*?)</script>", re.S | re.I)


def section_html(text, sid):
    m = re.search(r'<section class="rp-section[^"]*" data-section="%s">(.*?)</section>' % re.escape(html.escape(sid, quote=True)), text, re.S)
    return m.group(1) if m else ""


def rendered_kinds(text):
    return re.findall(r'<section class="rp-section rp-kind-([\w-]+)"', text)


def order_errors(text, mode):
    """Open questions first, directly under the sticky bar; a session page in its fixed order."""
    errs, kinds = [], rendered_kinds(text)
    m = re.search(r'<main class="rp-main"[^>]*>\s*(<[^>]+>)', text)
    first = m.group(1) if m else ""
    if "questions" in kinds and 'rp-kind-questions' not in first:
        errs.append("open questions must be the first thing under the sticky bar")
    if mode == "session":
        idx = [SESSION_ORDER.index(k) for k in kinds if k in SESSION_ORDER]
        if idx != sorted(idx):
            errs.append("session sections out of order: %s (want %s)" % (", ".join(kinds), ", ".join(SESSION_ORDER)))
    return errs


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
        mode, secs = spec.get("mode"), spec.get("sections") or []
        for sec in secs:
            if sec["kind"] == "review":
                n = len(re.findall(r'<article class="rp-item"', section_html(text, sec["id"])))
                if n != len(sec["items"]):
                    errs.append("section %s: %d item cards for %d items" % (sec["id"], n, len(sec["items"])))
                need = len(sec["decisions"]["buttons"])
                for it in sec["items"]:
                    got = len(re.findall(r'data-item="%s" data-choice=' % re.escape(html.escape(it["id"], quote=True)), text))
                    if got != need:
                        errs.append("item %s has %d decision buttons, expected %d" % (it["id"], got, need))
        if mode == "review" and not spec.get("header", "").startswith("["):
            errs.append("export header must be bracketed")
        if mode in ("log", "session") and title and not html.unescape(title.group(1)).startswith(spec.get("session") or "\0"):
            errs.append("%s <title> must lead with the session name" % mode)
        if mode in ("questions", "session"):
            errs.extend(order_errors(text, mode))
        if not any(sec["items"] for sec in secs):
            errs.append("page has no items in any section")
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
        spec = load_spec(a.spec)
        text = page(spec)
    except (SpecError, ValueError, KeyError) as e:
        print("spec error: %s" % e, file=sys.stderr)
        return 1
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(text)
    print("wrote %s (%d KB)" % (a.out, len(text.encode()) // 1024))
    for line in (image_line(spec), size_warning(text, spec)):
        if line:
            print(line)
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
