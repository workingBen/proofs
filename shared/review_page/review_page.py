#!/usr/bin/env python3
"""Build a self-contained review page from a JSON spec, and check it.

Usage:
  review_page.py SPEC.json --out PAGE.html [--no-check]   build (then check)
  review_page.py SPEC.json                                session/log: to .proofs/pages/SPEC.html
  review_page.py --check PAGE.html                        node --check + structure
  review_page.py --smoke PAGE.html [--playwright DIR]     click through in Chromium
       [--shots DIR]                                      (a Refine page: where its before shots are)
  review_page.py --match-preview PAGE.html --picks 1,3 --shots DIR
                                                          the built page against the Refine preview

Five modes share one engine: "review" (decision buttons per item: design-review,
article-copy-edit, photo-picker, style-guide), "questions" (a standalone questions
or QA checklist page), "session" (working-log's session page: questions, checks,
log and decided on one URL), "log" (a log-only page) and "settings" (the settings
page, from `shared/settings.py --spec`). The spec format is documented
in reference/review-page.md at the plugin root. Python 3 stdlib only; node is
needed for --check, --smoke and --match-preview, Playwright only for --smoke and --match-preview.
"""
import argparse
import base64
import html
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import settings as proofs_settings  # noqa: E402

HERE = Path(__file__).resolve().parent
ENGINE = HERE / "engine.js"
ANSWERS = HERE / "answers.cjs"
# The bar's sync indicator: hidden until the page's database answers (engine.js fills
# the icon and the word), so a page that cannot save never shows "Saved".
SYNC_HTML = ('<span class="rp-sync" data-sync hidden role="status" aria-live="polite">'
             '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true" fill="none" stroke="currentColor" '
             'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></svg>'
             '<span class="rp-sync-t"></span></span>')
# Send to Claude, beside Copy in every bar: hidden until the page's comments capability
# answers (engine.js), so a local file or a page published without it shows Copy alone.
# The short label drops " to Claude" on a phone. The message line under the bar says why
# the button is off, what a send did, and whether the session picked it up.
SEND_HTML = ('<button type="button" class="rp-send" data-send hidden disabled>'
             'Send<span class="rp-send-x"> to Claude</span></button>')
SEND_MSG_HTML = '<div class="rp-send-msg" data-send-msg role="status" aria-live="polite" hidden></div>'
# What to publish a page with: saved answers need db, Send to Claude needs comments. A
# non-empty capabilities object replaces the stored set, so always pass both.
CAPABILITIES = {"db": {}, "comments": {}}
STYLE = HERE / "style.css"
SMOKE = HERE / "smoke.cjs"
MATCH = HERE / "match.cjs"

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
    # design-review's Refine mode: one card per change of a `refine` item, then a
    # "Combined: 1, 3" line naming the Yes changes (render_refine, engine.js).
    "refine": {
        "variant_word": "Change", "pending": "PENDING", "mark_read": False,
        "buttons": [
            {"state": "accept", "label": "✓ Yes", "export": "YES"},
            {"state": "deny", "label": "✕ No", "export": "NO"},
            {"state": "revise", "label": "↻ Revise", "export": "REVISE", "comment": "required"},
        ]},
}
CATEGORY_COLORS = ["#2563eb", "#b45309", "#047857", "#9333ea", "#be123c", "#0e7490", "#4d7c0f", "#c2410c"]
MODES = ("review", "questions", "log", "session", "settings")
# Modes built with no --out go to .proofs/pages/<spec name>.html.
DEFAULT_OUT_MODES = ("log", "session", "settings")
# The skill named in the page's brand pill when the spec gives no `skill`: a review
# page takes it from its decisions preset (a custom set with no preset shows the
# wordmark alone), the other modes from their kind of page.
PRESET_SKILLS = {"copy-edit": "article-copy-edit", "design-review": "design-review",
                 "style-guide": "style-guide", "photo-picker": "photo-picker", "refine": "design-review"}


class SpecError(Exception):
    pass


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-") or "page"


def find_file(rel, base):
    """(path, tried): rel relative to the spec's folder first, then to the working directory
    (the project folder), where sessions usually write the path from (Django run 2 for assets,
    Vue run 1 for @file). path is None when neither has it; tried lists both, for the error."""
    tried = []
    for folder in (base, Path.cwd()):
        p = (folder / rel).resolve()
        if p not in tried:
            tried.append(p)
        if p.is_file():
            return p, tried
    return None, tried


def resolve_files(obj, base):
    """Replace any string "@file:relative/path" with that file's text."""
    if isinstance(obj, dict):
        return {k: resolve_files(v, base) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve_files(v, base) for v in obj]
    if isinstance(obj, str) and obj.startswith("@file:"):
        p, tried = find_file(obj[6:], base)
        if p is None:
            raise SpecError("@file not found: %s (tried %s)" % (obj[6:], " and ".join(map(str, tried))))
        return p.read_text()
    return obj


def data_uri(path, data=None, mime=None):
    mime = mime or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return "data:%s;base64,%s" % (mime, base64.b64encode(path.read_bytes() if data is None else data).decode("ascii"))


# Screenshots (PNG and JPEG assets) are converted to WebP when the page is built,
# which makes a page of screenshots several times lighter with no visible change.
# Older Safari (before iOS 14 and macOS Big Sur) cannot decode WebP, so every
# converted screenshot also carries a fallback (a JPEG, a shrunk PNG or the
# original, whichever is smallest) and an <img> becomes
# <picture><source type="image/webp" ...><img src="fallback"></picture>.
# The PROOFS_IMAGE_QUALITY / PROOFS_IMAGE_MAX_WIDTH settings (shared/settings.json: the
# settings files, then the environment) come first, then the spec keys image_quality /
# image_max_width, then the settings' defaults. The width limit is used only when the
# shrunk file is smaller.
CONVERTIBLE = {".png", ".jpg", ".jpeg"}
BLANK_GIF = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw=="


def image_settings(spec, env=None):
    env = os.environ if env is None else env
    eff = proofs_settings.effective(env=env)
    def pick(key, spec_key):
        entry = eff[key]
        raw = spec.get(spec_key)
        if entry["source"] != "default" or raw in (None, ""):
            return entry["value"]
        row = proofs_settings._row(key)
        try:
            v = int(raw)
        except (TypeError, ValueError):
            raise SpecError("%s must be a whole number, got %r" % (spec_key, raw))
        if not row["min"] <= v <= row["max"]:
            raise SpecError("%s must be between %d and %d, got %d" % (spec_key, row["min"], row["max"], v))
        return v
    return {"quality": pick("PROOFS_IMAGE_QUALITY", "image_quality"),
            "max_width": pick("PROOFS_IMAGE_MAX_WIDTH", "image_max_width")}


def image_tool():
    """The first WebP encoder found: ("magick", path) or ("cwebp", path), else None."""
    for name in ("magick", "cwebp"):
        found = shutil.which(name)
        if found:
            return name, found
    return None


# WebP's largest side. A full-page phone shot at 2x passes it (Vue run 1: 780 x 27188), and
# the encoder then fails, so to_webp scales such a shot down until it fits.
WEBP_MAX_DIM = 16383


def image_size(path):
    """(width, height) of a PNG or JPEG, read from its header (stdlib only), or (None, None)."""
    data = Path(path).read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    i = 2
    while i + 9 < len(data) and data[:2] == b"\xff\xd8":
        if data[i] != 0xFF:
            i += 1
            continue
        marker, size = data[i + 1], int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
        i += 2 + size
    return None, None


def image_width(path):
    """Pixel width of a PNG or JPEG, read from its header (stdlib only)."""
    return image_size(path)[0]


def webp_widths(width, height, max_width):
    """The widths to try a WebP at: None (as is) and max_width when the shot is wider, keeping
    only those whose sides fit WebP's limit; a shot too tall for any gets one width that fits."""
    widths = [None] + ([max_width] if max_width and width and width > max_width else [])
    if not (width and height):
        return widths
    def fits(w):
        w = w or width
        return w <= WEBP_MAX_DIM and height * w // width <= WEBP_MAX_DIM
    ok = [w for w in widths if fits(w)]
    return ok or [max(1, min(WEBP_MAX_DIM, width * WEBP_MAX_DIM // height))]


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
    smaller: shrinking a crisp shot can make the lossless file bigger. A shot taller
    than WebP allows is scaled down to fit. Never upscales."""
    q, mw = settings["quality"], settings["max_width"]
    best = None
    for w in webp_widths(*image_size(path), mw):
        for lossless in (False, True):
            data = encode_webp(path, q, w, lossless, tool)
            if data is not None and (best is None or len(data) < len(best)):
                best = data
    if best is None or len(best) >= path.stat().st_size:
        return None
    return best


def has_alpha(path):
    """True when a PNG may have transparent pixels (an alpha channel or a tRNS chunk)."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    return data[25] in (4, 6) or data.find(b"tRNS", 0, max(data.find(b"IDAT"), 0)) != -1


def encode_fallback(path, quality, width, fmt):
    """JPEG or PNG bytes from ImageMagick (resized to width when given), or None on failure."""
    exe = shutil.which("magick")
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / ("out." + fmt)
        cmd = ([exe, str(path)] + (["-resize", "%dx" % width] if width else [])
               + (["-quality", str(quality)] if fmt == "jpg" else []) + ["-strip", str(out)])
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0 or not out.is_file():
            return None
        return out.read_bytes()


def to_fallback(path, settings):
    """(bytes, mime) of the smallest image every browser can show, for older Safari.

    Tries a JPEG at the quality setting (never for a PNG with transparency, which a
    JPEG would turn black), and for a screenshot wider than max_width the shrunk
    JPEG and shrunk PNG too. The original wins when it is smallest, and is all
    there is without ImageMagick."""
    q, mw = settings["quality"], settings["max_width"]
    ext = path.suffix.lower()
    best = (path.read_bytes(), "image/png" if ext == ".png" else "image/jpeg")
    width = image_width(path)
    widths = [None] + ([mw] if mw and width and width > mw else [])
    fmts = (["jpg"] if ext != ".png" or not has_alpha(path) else []) + (["png"] if ext == ".png" else [])
    for w in widths:
        for fmt in fmts:
            if fmt == "png" and w is None:
                continue  # the original PNG is already a candidate
            data = encode_fallback(path, q, w, fmt)
            if data is not None and len(data) < len(best[0]):
                best = (data, "image/jpeg" if fmt == "jpg" else "image/png")
    return best


def embed_asset(path, settings, tool, report):
    """{"img": data URI every browser shows, "webp": WebP data URI or None}."""
    size = path.stat().st_size
    if path.suffix.lower() in CONVERTIBLE:
        if tool is None:
            report["missing_tool"] = True
        else:
            data = to_webp(path, settings, tool)
            if data is not None:
                fb, mime = to_fallback(path, settings)
                report["converted"] += 1
                report["before"] += size
                report["after"] += len(data)
                report["fallback"] += len(fb)
                return {"img": data_uri(path, fb, mime), "webp": data_uri(path, data, "image/webp")}
    return {"img": data_uri(path), "webp": None}


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
    report = {"converted": 0, "before": 0, "after": 0, "fallback": 0, "missing_tool": False, "settings": settings}
    for name, rel in (spec.get("assets") or {}).items():
        p, tried = find_file(rel, path.parent)
        if p is None:
            raise SpecError("asset %r not found: %s (tried %s)" % (name, rel, " and ".join(map(str, tried))))
        assets[name] = embed_asset(p, settings, tool, report)
    spec["_assets"] = assets
    spec["_image_report"] = report
    spec["_base"] = path.parent
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

KINDS = ("review", "questions", "links", "qa", "log", "decided", "settings")
DEFAULT_KIND = {"review": "review", "questions": "questions", "log": "log", "session": "log", "settings": "settings"}
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
# A link is "open" (the page waits on the reader) or "in-progress" (the reader has
# answered and Claude is working on it): still listed, so it is not lost, but after
# the open ones and without the call to action.
LINK_STATES = ("open", "in-progress")
# A session page asks only in `questions`; its log entries report, so none waits on the user.
ENTRY_STATUSES = ("Background", "Queued", "Done")
WIP_LINKS_TITLE = "Pages Claude is working on"


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
    if mode == "settings":
        return [{"kind": "settings", "id": "settings", "items": settings_rows(spec)}]
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
        if sec["kind"] == "links":
            for ln in sec["items"]:
                if ln.get("state", "open") not in LINK_STATES:
                    raise SpecError("a link's state must be one of %s" % ", ".join(LINK_STATES))
            sec["items"] = sorted(sec["items"], key=lambda ln: ln.get("state") == "in-progress")
            if sec["items"] and all(ln.get("state") == "in-progress" for ln in sec["items"]):
                sec["title"] = sec.get("title") or WIP_LINKS_TITLE
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
        self.spec, self.n, self.seen, self.anchors = spec, 0, set(), set()
        self.cats, self.refine = [], None
        for sec in secs:
            if sec["kind"] == "review":
                raw = sec.get("decisions", spec.get("decisions", "copy-edit"))
                sec["_dec"] = decisions_for(raw)
                sec["_preset"] = raw if isinstance(raw, str) else (raw or {}).get("preset")
                for it in sec["items"]:
                    if it.get("category") and it["category"] not in self.cats:
                        self.cats.append(it["category"])
        self.colors = dict(zip(self.cats, CATEGORY_COLORS * 4))
        self.colors.update(spec.get("category_colors") or {})

    def claim(self, ident, what):
        if not ident or ident in self.seen:
            raise SpecError("every %s needs an id unique on the page (got %r)" % (what, ident))
        self.seen.add(ident)


ROLES = {"careful": "Careful", "step-up": "Step up", "bold": "Bold"}
STATUSES = ("kept", "moved", "removed")
SCORE_DIMS = (("hierarchy", "Hierarchy"), ("action", "Action"), ("fold", "Fold"),
              ("grouping", "Grouping"), ("fit", "Fit"), ("care", "Care"))
JUDGED_BY = {"helper": "Judged by a separate helper", "self": "Checked by the designer itself"}


def check_scores(where, sc):
    """Scores are an object of SCORE_DIMS keys, each a whole number from 1 to 5; None is fine."""
    if sc is None:
        return
    if not isinstance(sc, dict):
        raise SpecError("%s: scores must be an object" % where)
    for k, val in sc.items():
        if k not in dict(SCORE_DIMS):
            raise SpecError("%s: unknown score %r (use %s)" % (where, k, ", ".join(d for d, _ in SCORE_DIMS)))
        if isinstance(val, bool) or not isinstance(val, int) or not 1 <= val <= 5:
            raise SpecError("%s: score %s must be a whole number from 1 to 5, got %r" % (where, k, val))


def _capture_row(where, ref, base):
    """The measures.json result a {"from", "page", "width", "state"} reference names."""
    rel = ref.get("from")
    if not isinstance(rel, str) or not rel:
        raise SpecError("%s: \"from\" must name the capture's measures.json" % where)
    p, tried = find_file(rel, base)
    if p is None:
        raise SpecError("%s: %s not found (tried %s)" % (where, rel, " and ".join(map(str, tried))))
    try:
        data = json.loads(p.read_text())
    except ValueError as e:
        raise SpecError("%s: %s is not JSON (%s)" % (where, rel, e))
    page, width, state = ref.get("page"), str(ref.get("width", "")), ref.get("state", "default")
    rows = [r for r in (data.get("results") if isinstance(data, dict) else None) or []
            if isinstance(r, dict) and isinstance(r.get("measures"), dict)]
    for r in rows:
        if r.get("page") == page and str(r.get("viewport")) == width and r.get("state", "default") == state:
            return r["measures"], "%s at %s" % (page, width)
    have = ", ".join("%s at %s%s" % (r.get("page"), r.get("viewport"),
                                     "" if r.get("state", "default") == "default" else " (%s)" % r.get("state"))
                     for r in rows) or "nothing"
    raise SpecError("%s: no capture of %s at %s%s in %s; it has: %s"
                    % (where, page, width, "" if state == "default" else " (%s)" % state, rel, have))


def resolve_before(it, base):
    """before_sections / before_font_sizes given as {"from": measures.json, ...} become the captured
    section object and the page's fontSizes list, so a session never copies them out by hand."""
    iid = it["id"]
    ref = it.get("before_sections")
    if isinstance(ref, dict) and "from" in ref:
        where = "item %s: before_sections" % iid
        m, at = _capture_row(where, ref, base)
        secs = [s for s in m.get("sections") or [] if isinstance(s, dict)]
        found = [s for s in secs if s.get("label") == ref.get("label")]
        if not found:
            raise SpecError("%s: no section labeled %r in %s (%s); it has: %s"
                            % (where, ref.get("label"), ref["from"], at,
                               ", ".join(str(s.get("label")) for s in secs) or "no sections"))
        it["before_sections"] = found[0]
    ref = it.get("before_font_sizes")
    if isinstance(ref, dict) and "from" in ref:
        m, _ = _capture_row("item %s: before_font_sizes" % iid, ref, base)
        it["before_font_sizes"] = m.get("fontSizes") or []


def check_designer_fields(it):
    """Validate role, inventory, scores and judged_by on an item and its variants (plain one-line errors)."""
    iid = it["id"]
    jb = it.get("judged_by")
    if jb is not None and (not isinstance(jb, str) or jb not in JUDGED_BY):
        raise SpecError("item %s: judged_by %r must be helper or self" % (iid, jb))
    # before_sections: one section object from the capture's measures.json (its `elements` drive
    # the inventory's "removed" rows and smoke's near-copy check); before_font_sizes: its fontSizes.
    bs = it.get("before_sections")
    if bs is not None and not (isinstance(bs, dict) and isinstance(bs.get("elements"), list)):
        raise SpecError("item %s: before_sections must be one captured section object with an elements list "
                        "(from measures.json), got %s" % (iid, type(bs).__name__))
    fs = it.get("before_font_sizes")
    if fs is not None and not (isinstance(fs, list) and all(
            isinstance(n, (int, float)) and not isinstance(n, bool) for n in fs)):
        raise SpecError("item %s: before_font_sizes must be a list of numbers (measures.json's fontSizes), got %r"
                        % (iid, fs))
    # before_scores: the critic's scores for the current page, the baseline every option must beat.
    check_scores("item %s, current page" % iid, it.get("before_scores"))
    variants = it.get("variants") or []
    owners = [("item %s" % iid, it)] if not variants else []
    owners += [("item %s, variant %s" % (iid, v["key"]), v) for v in variants]
    for where, o in owners:
        if o.get("role") is not None and (not isinstance(o["role"], str) or o["role"] not in ROLES):
            raise SpecError("%s: unknown role %r (use %s)" % (where, o["role"], ", ".join(ROLES)))
        inv = o.get("inventory")
        if inv is not None:
            if not isinstance(inv, list):
                raise SpecError("%s: inventory must be a list" % where)
            for row in inv:
                if not isinstance(row, dict) or not str(row.get("element") or "").strip():
                    raise SpecError("%s: every inventory row needs an element" % where)
                if row.get("status") not in STATUSES:
                    raise SpecError("%s: inventory status %r must be kept, moved or removed"
                                    % (where, row.get("status")))
                if "brand" in row and not isinstance(row["brand"], bool):
                    raise SpecError("%s: inventory brand on %r must be true or false, got %r"
                                    % (where, row["element"], row["brand"]))
        check_scores(where, o.get("scores"))
    if len(variants) >= 2 and (it.get("judged_by") or any(v.get("scores") for v in variants)):
        unscored = [v for v in variants if not v.get("scores")]
        picked = [v["key"] for v in unscored if v.get("recommended")]
        if it.get("selected") in [v["key"] for v in unscored]:
            picked.append(it["selected"])
        if picked:
            raise SpecError("item %s: variant %s is recommended but has no scores" % (iid, picked[0]))


def _norm(text):
    return " ".join(str(text or "").split()).lower()


def inventory_table(inv, before):
    """Compact inventory table. A captured element with no row reads as removed, no reason given."""
    # A row marked "brand" (a logo, wordmark, company or product name) carries a small Brand tag,
    # so the reader sees at a glance that the option kept the brand, or did not.
    rows = [(str(r["element"]), r["status"], r.get("reason") or "", False, r.get("brand") is True)
            for r in inv or []]
    if before and inv is not None:
        have = {_norm(r[0]) for r in rows}
        for el in before.get("elements") or []:
            name = (el.get("text") or "").strip() or el.get("kind") or ""
            if name and _norm(name) not in have:
                have.add(_norm(name))
                rows.append((" ".join(name.split()), "removed", "", True, False))
    if not rows:
        return ""
    body = "".join('<tr class="rp-inv-%s%s"><td>%s%s</td><td>%s</td><td>%s</td></tr>'
                   % (st, " rp-inv-brand" if brand else "", esc(el),
                      ' <span class="rp-inv-brandtag">Brand</span>' if brand else "",
                      st + (" — no reason given" if missing else ""), esc(why))
                   for el, st, why, missing, brand in rows)
    return ('<div class="rp-inv rp-scroll"><table><thead><tr><th>Element</th><th>Status</th><th>Reason</th></tr></thead>'
            '<tbody>%s</tbody></table></div>' % body)


def score_row(sc):
    if not sc:
        return '<div class="rp-scores rp-unscored">Not scored</div>'
    return '<div class="rp-scores">%s</div>' % " · ".join(
        "%s <b>%d</b>" % (lab, sc[k]) for k, lab in SCORE_DIMS if k in sc)


def render_review(sec, ctx):
    dec, out, items = sec["_dec"], [], []
    word = dec.get("variant_word", "Option")
    for it in sec["items"]:
        if it.get("kind") == "refine":
            h, js_items = refine_entry(it, sec, ctx)
            out.append(h)
            items.extend(js_items)
            continue
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
        keys = [v["key"] for v in it.get("variants") or []]
        if it.get("selected") is not None and it["selected"] not in keys:
            raise SpecError("item %s: selected %r is not one of its variants (%s)"
                            % (it["id"], it["selected"], ", ".join(keys) or "it has none"))
        resolve_before(it, ctx.spec.get("_base") or Path.cwd())
        check_designer_fields(it)
        out.append(review_item(it, dec, ctx.colors))
        items.append({"id": it["id"], "num": it["num"], "label": it["label"], "category": it.get("category"),
                      "variants": [{"key": v["key"], "label": v["label"], "name": v.get("name", ""),
                                    "recommended": bool(v.get("recommended"))}
                                   for v in it.get("variants") or []],
                      "selected": it.get("selected"),
                      "before_font_sizes": it.get("before_font_sizes") or [],
                      "before_sections": it.get("before_sections"),
                      # Smoke's near-copy check is about layouts: only design reviews get it.
                      "design_review": sec.get("_preset") == "design-review"})
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
        item = {"qid": qid, "ask": ask, "round": r}
        if not q.get("options"):
            item["text"] = True  # only a text box: what the reader types is the answer
        items.append(item)
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


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def short_when(value):
    """"2026-11-19T15:54" -> "Nov 19 - 3:54PM". The string is already the author's
    local time, so it is only reformatted, never converted."""
    m = re.match(r"^\d{4}-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?$", str(value).strip())
    if not m or not 1 <= int(m.group(1)) <= 12 or int(m.group(3)) > 23:
        raise SpecError("`when` must be an ISO-8601 local date and time like 2026-11-19T15:54, got %r" % value)
    mon, day, hour, minute = (int(g) for g in m.groups())
    return "%s %d - %d:%02d%s" % (MONTHS[mon - 1], day, (hour % 12) or 12, minute, "AM" if hour < 12 else "PM")


def render_log(sec, ctx):
    out, items = ['<h3 class="rp-read-head" hidden>Read</h3>'], []
    for e in sec["items"]:
        eid = e.get("id")
        ctx.claim(eid, "entry id")
        status = e.get("status", "Background")
        when = short_when(e["when"]) if e.get("when") else None
        out.append('<article class="rp-entry" id="%s" data-entry="%s">' % (esc(eid), esc(eid)))
        out.append('<header class="rp-entry-head"><span class="rp-num">%s</span><h3>%s</h3>%s'
                   '<span class="rp-status rp-status-%s">%s</span></header>'
                   % (esc(eid), esc(e.get("title", "")),
                      '<time class="rp-when" datetime="%s">%s</time>' % (esc(e["when"]), when) if when else "",
                      slug(status), esc(status)))
        if e.get("lede"):
            out.append('<p class="rp-lede">%s</p>' % e["lede"])
        if e.get("detail_html"):
            out.append('<div class="rp-detail">%s</div>' % e["detail_html"])
        qnames = []
        if ctx.spec["mode"] == "session":
            asks = (e.get("questions") or status not in ENTRY_STATUSES
                    or re.sub(r"<[^>]+>", "", e.get("lede") or "").strip().endswith("?"))
            if asks:
                raise SpecError("entry %s: on a session page a question goes in `questions`, so it sits at the top "
                                "under Waiting on you, not inside a log entry (entry status must be one of %s, "
                                "and its lede must not ask)" % (eid, ", ".join(ENTRY_STATUSES)))
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
                   '<label class="rp-tick"><input type="checkbox" data-tick="%s"> <span class="rp-tick-l">Read this</span></label></div></article>'
                   % (esc(eid), esc(eid)))
        items.append({"id": eid, "title": e.get("title", ""), "groups": qnames, "when": when})
    return out, {"items": items}


IN_PAGE_TEXT = {"questions": "Open questions above", "checks": "Open checks above", "log": "See the log below"}
SECTION_ANCHOR = {"questions": "questions", "qa": "checks", "log": "log", "decided": "decided"}


def render_links(sec, ctx):
    out = ['<ul class="rp-links">']
    for ln in sec["items"]:
        if not ln.get("label") or not ln.get("url"):
            raise SpecError("every link needs a label and a url")
        status = ': <span class="rp-link-status">%s</span>' % esc(ln["status"]) if ln.get("status") else ""
        # A link into this same page (#questions, #checks, #log, #L12) stays on the page and
        # says where it goes; "Open it" would just reload the page the reader is already on.
        if ln["url"].startswith("#"):
            target = ln["url"][1:]
            text = ln.get("link_text") or IN_PAGE_TEXT.get(target, "See it in the log below")
            out.append('<li><b>%s</b>%s <a href="%s">%s</a></li>' % (esc(ln["label"]), status, esc(ln["url"]), esc(text)))
            continue
        if ln.get("state") == "in-progress":
            out.append('<li class="rp-link-wip"><b>%s</b>%s <span class="rp-wip">In progress</span>'
                       ' <a class="rp-link-quiet" href="%s" target="_blank" rel="noopener">%s</a></li>'
                       % (esc(ln["label"]), status, esc(ln["url"]), esc(ln.get("link_text", "View page"))))
            continue
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


# ------------------------------------------------------------- settings
#
# The settings page (layout B, picked in the 1.9.0 design review): a sticky save bar, a
# sidebar of the five groups and one group's pane. The rules a value must pass (min, max,
# raise_only, choices, item_type) are the table rows of shared/settings.json, embedded in
# the page's spec, and engine.js checks a typed value against them the way settings.py
# validate does: no number is copied into the page's code.

SETTING_TYPES = ("int", "choice", "bool", "list", "text", "path", "auto")
SETTING_SOURCES = ("default", "environment", "user", "project", "local")
SETTING_FILES = {"user": "~/.claude/settings.json", "project": ".claude/settings.json",
                 "local": ".claude/settings.local.json"}
SCOPE_LEDE = {"user": "Saved for you, in <code>%s</code>, on every project.",
              "project": "Saved for this project, in <code>%s</code>, so everyone on it gets them.",
              "local": "Saved for this computer only, in <code>%s</code>."}
SCOPE_ROW = {"user": "Saved for you only, in <code>%s</code>.",
             "project": "Saved for this project, in <code>%s</code>.",
             "local": "Saved for this computer only, in <code>%s</code>."}
# The KEEP FIXED list, in the reader's words: quality floors no setting may lower.
SETTINGS_FIXED_HTML = ("<b>Fixed on purpose.</b> Contrast, the 44 px tap floor, line length, off-center and "
                       "near-copy checks can’t be turned down. No setting can weaken a check.")
SETTINGS_NONE_TEXT = "Pick a new value below, then Send to Claude or Copy: Claude saves it to your settings."


def settings_rows(spec):
    """The table rows, in table order, each with the value the spec gives (validated as
    settings.py would), its source and note, and `from`: the value as settings.py writes it.
    The rules always come from shared/settings.json; a spec row only brings value, source
    and note. A table key the spec leaves out shows its default."""
    given = spec.get("settings")
    if not isinstance(given, list) or not given:
        raise SpecError("settings mode needs `settings`: the rows `shared/settings.py --spec` prints")
    table = {r["key"]: r for r in proofs_settings.load_table()}
    by = {}
    for s in given:
        key = (s or {}).get("key")
        if key not in table:
            raise SpecError("%r is not a Proofs setting (see shared/settings.json)" % key)
        if key in by:
            raise SpecError("setting %s is listed twice" % key)
        by[key] = s
    rows = []
    for key, base in table.items():
        if base["type"] not in SETTING_TYPES:
            raise SpecError("setting %s has an unknown type %r" % (key, base["type"]))
        s = by.get(key, {})
        value = s.get("value")
        if value is None:
            value = base["default"]
        try:
            value = proofs_settings._parse(base, proofs_settings._canonical(base, value))
        except proofs_settings.SettingError as e:
            raise SpecError("%s: %s" % (key, e))
        source = s.get("source") or "default"
        if source not in SETTING_SOURCES:
            raise SpecError("setting %s: source must be one of %s" % (key, ", ".join(SETTING_SOURCES)))
        rows.append(dict(base, id=key, value=value, source=source, note=s.get("note") or "",
                         **{"from": proofs_settings._canonical(base, value)}))
    return rows


def setting_shown(row, value, unit=True):
    """A value as the page shows it: On/Off, a choice's label, a list with commas or none."""
    if isinstance(value, bool):
        text = "On" if value else "Off"
    elif isinstance(value, list):
        text = ", ".join(str(v) for v in value) or "none"
    elif row["type"] == "choice":
        text = (row.get("choice_labels") or {}).get(str(value), str(value))
    else:
        text = str(value)
    if not unit or not row.get("unit") or value == []:
        return text
    # "$ est." reads as "$5 est.", not "5 $ est."
    return "$%s %s" % (text, row["unit"][2:]) if row["unit"].startswith("$ ") else "%s %s" % (text, row["unit"])


def setting_text(row):
    """What a text box holds at first: the value, lists joined with ", "."""
    v = row["value"]
    return ", ".join(str(x) for x in v) if isinstance(v, list) else str(v)


def setting_control(row):
    key, lab = esc(row["id"]), 'aria-labelledby="set-lab-%s"' % esc(row["id"])
    kind, value = row["type"], row["value"]
    if kind == "int":
        unit = '<span class="rp-set-unit">%s</span>' % esc(row["unit"]) if row.get("unit") else ""
        return ('<span class="rp-set-num"><input class="rp-set-in rp-set-in-num" inputmode="numeric" autocomplete="off" '
                'data-set-in="%s" %s value="%s">%s</span>' % (key, lab, esc(value), unit))
    if kind == "choice":
        labels = [(c, (row.get("choice_labels") or {}).get(c, c)) for c in row["choices"]]
        # Long labels stack on a phone instead of squeezing three to a line.
        stack = any(len(t) > 16 for _, t in labels) or (len(labels) > 2 and sum(len(t) for _, t in labels) > 24)
        return ('<span class="rp-set-seg%s" role="group" %s>%s</span>'
                % (" rp-set-seg-stack" if stack else "", lab, "".join(
                    '<button type="button" class="rp-set-seg-b" data-set-choice="%s" aria-pressed="%s">%s</button>'
                    % (esc(c), "true" if c == row["from"] else "false", esc(t)) for c, t in labels)))
    if kind == "bool":
        return ('<button type="button" class="rp-set-tog" role="switch" aria-checked="%s" data-set-tog %s>'
                '<span class="rp-set-tog-t" aria-hidden="true"></span><span data-set-tog-l>%s</span></button>'
                % ("true" if value else "false", lab, "On" if value else "Off"))
    box = ('<input class="rp-set-in rp-set-in-text" spellcheck="false" autocapitalize="off" autocomplete="off" '
           'data-set-in="%s" %s value="%s"%s%%s>' % (key, lab, esc(setting_text(row)),
                                                    ' placeholder="none"' if kind == "list" else ""))
    if kind == "auto":
        auto = value == "auto"
        return ('<span class="rp-set-auto" data-set-auto%s><span>auto</span>'
                '<button type="button" class="rp-set-link" data-set-change>Change</button></span>'
                % ("" if auto else " hidden")) + box % (" hidden" if auto else "")
    return box % ""


def setting_mark(row):
    if row["from"] == proofs_settings._canonical(row, row["default"]):
        return '<span class="rp-set-mark" data-set-mark hidden></span>'
    return ('<span class="rp-set-mark" data-set-mark>Changed · default %s · '
            '<button type="button" class="rp-set-link" data-set-reset>Reset</button></span>'
            % esc(setting_shown(row, row["default"])))


def render_settings(sec, ctx):
    files = dict(SETTING_FILES, **(ctx.spec.get("files") or {}))
    rows, groups = sec["items"], list(proofs_settings.GROUP_TITLES.items())
    for r in rows:
        ctx.claim(r["id"], "setting")
        if r["group"] not in proofs_settings.GROUP_TITLES:
            raise SpecError("setting %s has an unknown group %r" % (r["id"], r["group"]))
    groups = [(g, t) for g, t in groups if any(r["group"] == g for r in rows)]
    out = ['<div class="rp-set-split">', '<nav class="rp-set-nav" aria-label="Setting groups">',
           '<label class="rp-set-search"><span class="rp-sr">Search settings</span><input class="rp-set-in" '
           'type="search" placeholder="Search settings" autocomplete="off" data-set-search></label>']
    for i, (g, title) in enumerate(groups):
        out.append('<a class="rp-set-nav-i%s" href="#set-%s" data-set-nav="%s"%s><span class="rp-set-dot" data-set-dot>'
                   '</span><span class="rp-set-nav-t">%s</span><span class="rp-set-nav-n" data-set-n>%d</span></a>'
                   % (" rp-set-nav-on" if not i else "", esc(g), esc(g), ' aria-current="true"' if not i else "",
                      esc(title), sum(1 for r in rows if r["group"] == g)))
    out.append("</nav>")
    out.append('<div class="rp-set-pane"><p class="rp-set-none" data-set-none hidden>No setting matches that search.</p>')
    for i, (g, title) in enumerate(groups):
        mine = [r for r in rows if r["group"] == g]
        scopes = [r["scope"] for r in mine]
        scope = max(scopes, key=lambda s: (scopes.count(s), -scopes.index(s)))
        out.append('<div class="rp-set-group" data-set-group="%s" id="set-%s"%s>' % (esc(g), esc(g), " hidden" if i else ""))
        out.append('<h1 class="rp-set-h1">%s</h1>' % esc(title))
        out.append('<p class="rp-set-lede">%s</p>' % (SCOPE_LEDE[scope] % esc(files[scope])))
        for adv in (False, True):
            part = [r for r in mine if bool(r.get("advanced")) == adv]
            if not part:
                continue
            if adv:
                out.append('<h2 class="rp-set-h2" data-set-adv-h>Advanced</h2>')
            out.append('<div class="rp-set-list">')
            for r in part:
                key = esc(r["id"])
                where = ('<p class="rp-set-where">%s</p>' % (SCOPE_ROW[r["scope"]] % esc(files[r["scope"]]))
                         if r["scope"] != scope else "")
                note = '<p class="rp-set-note">%s</p>' % esc(r["note"]) if r.get("note") else ""
                out.append('<div class="rp-set-row" data-set-row="%s"><div class="rp-set-rl">'
                           '<div class="rp-set-lab" id="set-lab-%s">%s</div><p class="rp-set-help">%s</p>%s%s%s</div>'
                           '<div class="rp-set-rc"><div class="rp-set-ctl">%s</div>'
                           '<p class="rp-set-err" data-set-err aria-live="polite" hidden></p></div></div><!--/row-->'
                           % (key, key, esc(r["label"]), esc(r["help"]), where, note, setting_mark(r),
                              setting_control(r)))
            out.append("</div>")
        out.append("</div><!--/group-->")
    out.append('<p class="rp-set-fixed">%s</p>' % (ctx.spec.get("fixed_html") or SETTINGS_FIXED_HTML))
    out.append("</div></div>")
    return out, {"items": rows, "groups": [[g, t] for g, t in groups]}


RENDER = {"review": render_review, "questions": render_questions, "qa": render_qa, "log": render_log,
          "links": render_links, "decided": render_decided, "settings": render_settings}


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
        anchor = SECTION_ANCHOR.get(kind)
        anchor = ' id="%s"' % anchor if anchor and anchor not in ctx.anchors else ""
        if anchor:
            ctx.anchors.add(SECTION_ANCHOR[kind])
        h = ['<section class="rp-section rp-kind-%s" data-section="%s"%s>' % (kind, esc(sec["id"]), anchor)]
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
        return {"header": spec.get("header") or "[%s]" % spec["title"], "session": proj.get("session")}
    if mode == "settings":
        if not proj.get("name"):
            raise SpecError("settings mode needs project.name")
        return {"project": proj.get("name"), "repo": proj.get("repo"),
                "bool_true": list(proofs_settings.BOOL_TRUE), "bool_false": list(proofs_settings.BOOL_FALSE)}
    if mode == "questions":
        for k in ("name", "stream"):
            if not proj.get(k):
                raise SpecError("questions mode needs project.%s" % k)
        asks = bool(spec.get("questions")) or any(s.get("kind") == "questions" and s.get("items")
                                                  for s in spec.get("sections") or [])
        return {"format": spec.get("format", "questions v1.3" if asks else "qa-checklist v1.0"),
                "verb": "answers" if asks else "results", "project": proj.get("name"),
                "stream": proj.get("stream"), "session": proj.get("session"), "round": proj.get("round", "?"),
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

def skill_name(spec, js_sections):
    """The skill a page belongs to, for its brand pill; None shows the wordmark alone."""
    if "skill" in spec:
        return spec["skill"] or None
    mode = spec["mode"]
    if mode == "settings":
        return "settings"
    if mode in ("log", "session"):
        return "working-log"
    if mode == "questions":
        kinds = {s["kind"] for s in js_sections if s["items"]}
        return "qa-checklist" if "qa" in kinds and "questions" not in kinds else "questions"
    secs = spec.get("sections") or [spec]
    d = next((s.get("decisions", spec.get("decisions", "copy-edit")) for s in secs
              if s.get("kind", "review") == "review"), None)
    preset = d if isinstance(d, str) else (d or {}).get("preset")
    return PRESET_SKILLS.get(preset)


def brand(skill):
    """The proofs wordmark and skill pill that start every page's top line, so one
    skill's page reads apart from another's. Screen readers get one plain phrase."""
    pill = '<span class="rp-sk" aria-hidden="true">%s</span>' % esc(skill) if skill else ""
    return ('<span class="rp-brand"><span class="rp-wm" aria-hidden="true">pro<i>o</i>fs</span>%s'
            '<span class="rp-sr">Proofs%s</span><span class="rp-brand-sep" aria-hidden="true"></span></span>'
            % (pill, ", " + esc(skill) if skill else ""))


def page(spec):
    mode = spec["mode"]
    js = frame_js(spec)
    preamble, chunks, js["sections"] = render_sections(spec)
    js["mode"] = mode
    proj = spec.get("project") or {}
    # Stamped on each answer saved to the page's database, so a reader of the rows can
    # tell which build of the page an answer was given on.
    js["page_version"] = spec.get("version") or hashlib.sha1(
        json.dumps(js, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]
    # How long the page waits for Claude's republish before saying "Not picked up yet": the
    # PROOFS_SEND_WAIT_MIN setting, in ms, unless the spec states send_wait_ms itself.
    js["send_wait_ms"] = spec.get("send_wait_ms") or proofs_settings.get("PROOFS_SEND_WAIT_MIN") * 60000
    # The version the reader sees ("now v14" after Claude republishes); page_version may be a hash.
    js["version"] = spec.get("version") or ""
    js["key"] = spec.get("storage_key") or "proofs:%s:%s" % (mode, slug("%s %s %s" % (
        proj.get("name", ""), proj.get("session", proj.get("stream", "")), spec["title"])))
    mark = brand(skill_name(spec, js["sections"]))
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
        html_out.append('<div class="rp-topbars"><div class="rp-projectbar">%s<span class="rp-pb-x">%s · </span><b class="rp-session">%s</b><span class="rp-pb-x">%s</span></div>'
                        % (mark, esc(proj["name"]), esc(proj["session"]), repo))
        html_out.append('<div class="rp-statusbar"><span id="rp-tally"></span><span class="rp-marker">%s</span>'
                        '%s<button type="button" class="rp-copy" data-copy>Copy<span class="rp-copy-x"> my replies</span></button>%s</div>%s</div>'
                        % (marker, SYNC_HTML, SEND_HTML, SEND_MSG_HTML))
    elif mode == "questions":
        html_out.append('<div class="bar">%s<div class="bar-title">%s</div><div class="tally" id="rp-tally">—</div>'
                        '%s<button class="ghost" id="rp-clear" type="button">Clear</button>'
                        '<button class="copy" type="button" data-copy>%s</button>%s%s</div>'
                        % (mark, (spec.get("bar_title_html") or esc(proj["name"])) + (
                            '<span class="rp-sess"> · <b class="rp-session">%s</b></span>' % esc(proj["session"])
                            if proj.get("session") else ""), SYNC_HTML, esc(spec.get("copy_label", "Copy my answers")),
                           SEND_HTML, SEND_MSG_HTML))
    html_out.append('<main class="rp-main" data-preview="light">')
    if mode in ("review", "settings"):
        # project · session, then the repo (dropped on phones, separator and all). Each
        # separator belongs to the part after it, so it hides with that part, and on a
        # phone, where the parts wrap, none is drawn (Rails run 1: a dot ended a line).
        sep = '<span class="rp-sep"> · </span>'
        where = esc(proj.get("name") or "")
        if proj.get("session"):
            where += '<span class="rp-wp">%s<b class="rp-session">%s</b></span>' % (sep if where else "", esc(proj["session"]))
        if proj.get("repo"):
            where += '<span class="rp-pb-x">%s%s</span>' % (sep if where else "", esc(proj["repo"]))
        html_out.append('<div class="rp-brandline">%s%s</div>' % (
            mark, '<span class="rp-where">%s</span>' % where if where else ""))
    if mode == "settings":
        # The save bar: sticky at the top, above the sidebar and the pane. Send to Claude is
        # its one primary; engine.js fills the count and one "Label old → new" per change.
        html_out.append('<div class="rp-set-save" data-set-save><div class="rp-set-save-t"><b data-set-count>No changes yet</b>'
                        '<span data-set-list>%s</span></div><div class="rp-set-save-a">%s'
                        '<button type="button" class="rp-set-btn" data-copy>Copy</button>%s</div>%s</div>'
                        % (esc(SETTINGS_NONE_TEXT), SYNC_HTML, SEND_HTML, SEND_MSG_HTML))
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
        html_out.append('<div class="rp-bar">%s<div class="rp-progress" aria-hidden="true"></div><span id="rp-tally"></span>'
                        '%s<button type="button" class="rp-copy" data-copy>%s</button>%s</div>'
                        % (SEND_MSG_HTML, SYNC_HTML, esc(spec.get("copy_label", "Copy My Decisions")), SEND_HTML))
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
    """Put each asset's bytes in the page once (a fallback for older browsers
    aside). A font in @font-face is inlined there. CSS uses (url({{asset:x}}) or
    var(--asset-x)) read a :root variable holding the format every browser shows.
    An <img src="{{asset:x}}"> of a WebP-converted screenshot becomes a <picture>
    whose <source> offers the WebP and whose <img> keeps the fallback, so older
    Safari still shows it. A single HTML use is inlined and works without
    JavaScript; several uses carry data-rp-asset="ATTR NAME FORMAT" and a small
    script copies the data URI in from one JSON map (#rp-assets) when the page loads."""
    root, shared = [], {}
    # @font-face cannot read CSS variables, so a font's data URI goes inline there.
    text = re.sub(r"@font-face\s*\{(?:[^{}]|\{\{asset:[\w-]+\}\})*\}",
                  lambda m: re.sub(r"\{\{asset:([\w-]+)\}\}",
                                   lambda a: assets[a.group(1)]["img"] if a.group(1) in assets else a.group(0),
                                   m.group(0)), text)
    uses = {}
    for k, v in assets.items():
        ph = "{{asset:%s}}" % k
        for q in ("", "'", '"'):
            text = text.replace("url(%s%s%s)" % (q, ph, q), "var(--asset-%s)" % k)
        if ("var(--asset-%s)" % k) in text:
            root.append("--asset-%s:url(%s);" % (k, v["img"]))
        uses[k] = text.count(ph)

    def fill(k, attr, fmt):
        """Attribute text for one use: the data URI inline, or a placeholder the script fills."""
        if uses[k] == 1:
            return '%s="%s"' % (attr, assets[k][fmt])
        shared.setdefault(k, {})[fmt] = assets[k][fmt]
        # A <source> with no srcset is skipped, so the <img> shows until the script runs.
        blank = 'src="%s" ' % BLANK_GIF if attr == "src" else ""
        return '%sdata-rp-asset="%s %s %s"' % (blank, attr, k, fmt)

    def picture(m):
        tag = m.group(0)
        src = re.search(r'\ssrc="\{\{asset:([\w-]+)\}\}"', tag)
        if not src or src.group(1) not in assets or not assets[src.group(1)]["webp"]:
            return tag
        k = src.group(1)
        img = tag[:src.start()] + " " + fill(k, "src", "img") + tag[src.end():]
        source = '<source type="image/webp" %s>' % fill(k, "srcset", "webp")
        return '<picture class="rp-pic">%s%s</picture>' % (source, img)

    text = re.sub(r"<img\b[^<>]*>", picture, text, flags=re.I)
    for k, v in assets.items():
        ph = "{{asset:%s}}" % k
        if uses[k] > 1:
            def attr(m, k=k):
                shared.setdefault(k, {})["img"] = assets[k]["img"]
                e = m.group(2)
                return '%s=%s"%s%s" data-rp-asset=%s"%s %s img%s"' % (m.group(1), e, BLANK_GIF, e, e, m.group(1), k, e)
            text = re.sub(r'([\w-]+)=(\\?)"%s\\?"' % re.escape(ph), attr, text)
        text = text.replace(ph, v["img"])  # anything left is not an attribute: inline it
    text = text.replace("/*rp-assets*/", "".join(root), 1)
    if shared:
        text = text.replace("</body></html>", '<script type="application/json" id="rp-assets">%s</script>\n'
                            "<script>\n%s\n</script>\n</body></html>" % (json.dumps(shared), ASSET_FILL), 1)
    return text


# Old Safari is the reason this exists, so it is plain ES5 with no NodeList.forEach
# and no CSS-variable read back (getComputedStyle returned nothing usable there).
ASSET_FILL = """(function () {
  var map = JSON.parse(document.getElementById("rp-assets").textContent);
  var els = document.querySelectorAll("[data-rp-asset]");
  for (var i = 0; i < els.length; i++) {
    var p = els[i].getAttribute("data-rp-asset").split(" "), a = map[p[1]];
    if (a && a[p[2]]) els[i].setAttribute(p[0], a[p[2]]);
  }
})();"""


def size_warning(text, spec):
    """A warning line when the page is over the PROOFS_PAGE_WARN_MB setting, naming the largest assets."""
    warn_bytes = proofs_settings.get("PROOFS_PAGE_WARN_MB") * 1024 * 1024
    total = len(text.encode())
    if total <= warn_bytes:
        return None
    size = lambda v: len(v) if isinstance(v, str) else sum(len(x or "") for x in v.values())
    big = sorted(spec["_assets"].items(), key=lambda kv: -size(kv[1]))[:3]
    names = ", ".join("%s (%d KB)" % (k, size(v) // 1024) for k, v in big)
    return ("warning: the page is %.1f MB, over %d MB. Largest assets: %s. Lower image_quality "
            "or set image_max_width, or split the review." % (total / 1048576, warn_bytes // 1048576, names or "none"))


def image_line(spec):
    r = spec.get("_image_report") or {}
    if r.get("converted"):
        return ("images: %d converted to WebP (smaller of lossy at quality %d and lossless%s) (%d KB -> %d KB), "
                "plus a %d KB fallback for older Safari, which cannot show WebP") % (
            r["converted"], r["settings"]["quality"],
            ", max width %d" % r["settings"]["max_width"] if r["settings"]["max_width"] else "",
            r["before"] // 1024, r["after"] // 1024, r.get("fallback", 0) // 1024)
    if r.get("missing_tool"):
        return "images: no magick or cwebp found, so screenshots were embedded as they are (install ImageMagick or libwebp to shrink them)"
    return None


def designer_extras(o, scored, before):
    """Inventory table and score row for one proposal (a variant, or a one-option item)."""
    out = inventory_table(o.get("inventory"), before)
    if o.get("scores") or scored:
        out += score_row(o.get("scores"))
    return out


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
    scored = bool(it.get("judged_by")) or any(v.get("scores") for v in variants)
    if it.get("before_scores"):
        h.append('<div class="rp-scores rp-before-scores"><span class="rp-scores-label">Current page</span> %s</div>'
                 % " · ".join("%s <b>%d</b>" % (lab, it["before_scores"][k]) for k, lab in SCORE_DIMS
                              if k in it["before_scores"]))
    if not variants:
        # A score row only when a critic was meant to judge it: copy-edit and capture items get none.
        h.append(designer_extras(it, bool(it.get("judged_by")), it.get("before_sections")))
    if variants:
        # stack_variants: one variant per row, so a desktop mockup gets the card's full width
        # instead of about 490 px beside its sibling at a 1280 px window (SvelteKit run 1).
        h.append('<div class="rp-gallery%s" role="group" aria-label="Choose one">'
                 % (" rp-stack" if it.get("stack_variants") else ""))
        for v in variants:
            name = ' <span class="rp-vname">%s</span>' % esc(v["name"]) if v.get("name") else ""
            if v.get("role"):
                name = ' <span class="rp-vrole">%s</span>%s' % (ROLES[v["role"]], name)
            rv = ' <span class="rp-vrec">Recommended</span>' if v.get("recommended") else ""
            note = '<div class="rp-vnote">%s</div>' % v["note_html"] if v.get("note_html") else ""
            h.append('<div class="rp-variant" role="button" tabindex="0" aria-pressed="false" data-variant="%s">'
                     '<div class="rp-vhead"><span class="rp-vcheck" aria-hidden="true"></span>%s%s%s</div>'
                     '<div class="rp-vbody">%s</div>%s%s</div>'
                     % (esc(v["key"]), esc(v["label"]), name, rv, v.get("html", ""),
                        designer_extras(v, scored, it.get("before_sections")), note))
        h.append("</div>")
    if it.get("judged_by"):
        h.append('<div class="rp-judged">%s</div>' % JUDGED_BY[it["judged_by"]])
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


# ------------------------------------------------------------------- refine
#
# design-review's Refine mode (reference/review-page.md, "Refine items"): one item of
# "kind": "refine" holds a base (the capture's static snapshot of the page) and 1 to 8
# changes. Each change is its own card, decision and export line; the combined preview
# shows the base in two iframes (1280 and 390), each carrying every change's CSS scoped
# under html[data-rc~="<id>"], so a change applies only while the engine has its id in
# the frame's data-rc.

REFINE_MAX = 8
REFINE_ID = re.compile(r"[a-z0-9-]+\Z")
REFINE_SCORES = (("gain", "Gain"), ("keeps", "Keeps"))
REFINE_WIDTHS = ((1280, "Desktop, 1280 px"), (390, "Phone, 390 px"))
# At-rules whose blocks hold style rules, which get scoped; any other block at-rule
# (@font-face, @keyframes, @page, @property, @counter-style) passes through as written.
# @scope is refused: its inner selectors match from the scope root, so a prefix above it
# would not decide whether the change is on.
CSS_NESTED_AT = ("media", "supports", "container", "layer", "document", "starting-style")
HIDES = re.compile(r"display\s*:\s*none", re.I)
# Types mimetypes may not know, for the snapshot's fonts and images.
SNAPSHOT_MIME = {".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".otf": "font/otf",
                 ".svg": "image/svg+xml", ".webp": "image/webp", ".avif": "image/avif", ".ico": "image/x-icon"}


def _css_skip(css, i):
    """The index past a string, comment or backslash escape (Tailwind's .md\\:flex, .a\\,b) that
    starts at i, or i itself when none does."""
    c = css[i]
    if c == "\\":
        return min(i + 2, len(css))
    if c in "\"'":
        j = i + 1
        while j < len(css) and css[j] != c:
            j += 2 if css[j] == "\\" else 1
        return min(j + 1, len(css))
    if css.startswith("/*", i):
        j = css.find("*/", i + 2)
        return len(css) if j < 0 else j + 2
    return i


def _css_scan(css, i, stops):
    """The index of the first character in stops outside strings, comments, () and [], or len(css)."""
    depth = 0
    while i < len(css):
        j = _css_skip(css, i)
        if j != i:
            i = j
            continue
        c = css[i]
        if c in "([":
            depth += 1
        elif c in ")]":
            depth = max(0, depth - 1)
        elif depth == 0 and c in stops:
            return i
        i += 1
    return i


def _css_block_end(css, i):
    """css[i] is "{": the index of the "}" that closes it, or -1 when nothing does."""
    depth = 0
    while i < len(css):
        j = _css_skip(css, i)
        if j != i:
            i = j
            continue
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if not depth:
                return i
        i += 1
    return -1


def _css_uncomment(css):
    out, i = [], 0
    while i < len(css):
        j = _css_skip(css, i)
        if j == i:
            out.append(css[i])
            i += 1
        else:
            if not css.startswith("/*", i):
                out.append(css[i:j])
            i = j
    return "".join(out)


def _css_prelude(head):
    """A rule's prelude with comments dropped and each whitespace run made one space, except
    inside strings and escapes ([title="a  b"] keeps both spaces)."""
    out, i = "", 0
    while i < len(head):
        j = _css_skip(head, i)
        if j != i:
            out += " " if head.startswith("/*", i) and not out.endswith(" ") else (
                "" if head.startswith("/*", i) else head[i:j])
            i = j
        elif head[i].isspace():
            out += "" if out.endswith(" ") else " "
            i += 1
        else:
            out += head[i]
            i += 1
    return out.strip()


def _css_split(prelude):
    """A selector list's parts, split on the commas outside :is(), [attr] and strings."""
    parts, i = [], 0
    while True:
        j = _css_scan(prelude, i, ",")
        parts.append(prelude[i:j].strip())
        if j >= len(prelude):
            return parts
        i = j + 1


def _scope_selector(sel, attr):
    """html and :root are the frame's own root, so the attribute goes on them, not above them.
    Known limit: only a leading html or :root is seen. One inside a pseudo-class
    (:is(html.dark) .a, :not(:root) .b) gets the plain prefix, and so never matches."""
    m = re.match(r"(?i)(html|:root)(?![\w-])", sel)
    return "html" + attr + sel[m.end():] if m else "html%s %s" % (attr, sel)


def _scope_rules(css, attr, where):
    rules, i, n = [], 0, len(css)
    while True:
        while i < n and (css[i].isspace() or css.startswith("/*", i)):
            i = _css_skip(css, i) if css.startswith("/*", i) else i + 1
        if i >= n:
            return rules
        end = _css_scan(css, i, "{;}")
        head = css[i:end]
        if end < n and css[end] == ";" and head.lstrip().startswith("@"):
            rules.append(head.strip() + ";")  # @import, @charset, @layer a, b;
            i = end + 1
            continue
        if end >= n or css[end] != "{":
            raise SpecError("%s: css must be rules (selector { ... }); this has no block of its own: %r"
                            % (where, head.strip()[:60] or css[end:end + 1]))
        close = _css_block_end(css, end)
        if close < 0:
            raise SpecError("%s: css has a { that is never closed, after %r" % (where, head.strip()[:60]))
        prelude, body = _css_prelude(head), css[end + 1:close]
        if prelude.startswith("@"):
            name = re.match(r"@([\w-]*)", prelude).group(1).lower()
            if name == "scope":
                raise SpecError("%s: css cannot use @scope (its rules match from the scope root, so the "
                                "change could not be turned off); write the selectors out instead" % where)
            if name in CSS_NESTED_AT:
                rules.append("%s { %s }" % (prelude, "\n".join(_scope_rules(body, attr, where))))
            else:
                rules.append(css[i:close + 1].strip())
        else:
            sels = _css_split(prelude)
            if not all(sels):
                raise SpecError("%s: css has an empty selector in %r" % (where, prelude[:60]))
            rules.append("%s {%s}" % (", ".join(_scope_selector(s, attr) for s in sels), body))
        i = close + 1


def scope_css(css: str, change_id: str) -> str:
    """Prefix every selector of css with html[data-rc~="<change_id>"], so the rules apply only
    while the change is on: each part of a selector list, the rules inside @media, @supports,
    @container and @layer blocks; @font-face, @keyframes and statements pass through."""
    return "\n".join(_scope_rules(css, '[data-rc~="%s"]' % change_id, "change %s" % change_id))


def _score_pairs(sc, dims):
    return " · ".join("%s <b>%d</b>" % (lab, sc[k]) for k, lab in dims if k in sc)


def check_refine_fields(it) -> None:
    """Validate a refine item: base, 1 to 8 changes, their fields, and the scores (SpecError, one line)."""
    iid = it["id"]
    base = it.get("base")
    if not (isinstance(base, dict) and isinstance(base.get("from"), str) and base["from"]):
        raise SpecError('item %s: base must be {"from": "<the capture\'s -snapshot.html>"}, got %r' % (iid, base))
    changes = it.get("changes")
    count = len(changes) if isinstance(changes, list) else 0
    if not 1 <= count <= REFINE_MAX:
        raise SpecError("item %s: %d changes; a Refine item holds 1 to %d (more than %d says the page wants "
                        "a Redesign)" % (iid, count, REFINE_MAX, REFINE_MAX))
    jb = it.get("judged_by")
    if jb is not None and (not isinstance(jb, str) or jb not in JUDGED_BY):
        raise SpecError("item %s: judged_by %r must be helper or self" % (iid, jb))
    check_scores("item %s, current page" % iid, it.get("before_scores"))
    check_scores("item %s, your picks together" % iid, it.get("set_scores"))
    for key in ("location", "crops"):
        if it.get(key) is not None and not (isinstance(it[key], str) and it[key]):
            raise SpecError("item %s: %s must be a string" % (iid, key))
    for c in changes:
        if not isinstance(c, dict):
            raise SpecError("item %s: every change must be an object" % iid)
        cid = c.get("id")
        if not isinstance(cid, str) or not REFINE_ID.match(cid):
            raise SpecError("item %s: change id %r must be lowercase letters, digits and hyphens ([a-z0-9-]+)"
                            % (iid, cid))
        where = "change %s" % cid
        for key, what in (("label", "a label"), ("why_html", "why_html"), ("css", "css")):
            if not (isinstance(c.get(key), str) and c[key].strip()):
                raise SpecError("%s needs %s" % (where, what))
        t = c.get("targets")
        if not (isinstance(t, list) and t and all(isinstance(s, str) and s.strip() for s in t)):
            raise SpecError("%s: targets must be a non-empty list of selectors, got %r" % (where, t))
        if "</style" in c["css"].lower():
            raise SpecError("%s: css must not contain </style>" % where)
        for sw in c.get("swaps") or []:
            if not (isinstance(sw, dict) and isinstance(sw.get("selector"), str) and sw["selector"].strip()
                    and isinstance(sw.get("html"), str)):
                raise SpecError("%s: every swap needs a selector and html" % where)
            if "</template" in sw["html"].lower():
                raise SpecError("%s: a swap's html must not contain </template>" % where)
        removes = c.get("removes")
        if removes is not None and not isinstance(removes, list):
            raise SpecError("%s: removes must be a list" % where)
        for r in removes or []:
            if not (isinstance(r, dict) and str(r.get("element") or "").strip() and str(r.get("reason") or "").strip()):
                raise SpecError("%s: every removes line needs an element and a reason" % where)
        if HIDES.search(_css_uncomment(c["css"])) and not removes:
            raise SpecError("%s hides an element (display: none) but has no removes line saying what and why" % where)
        if c.get("swaps") and not removes:
            raise SpecError("%s swaps an element but has no removes line saying what it replaces and why" % where)
        sc = c.get("scores")
        if sc is not None:
            if not isinstance(sc, dict):
                raise SpecError("%s: scores must be an object" % where)
            for k, val in sc.items():
                if k not in dict(REFINE_SCORES):
                    raise SpecError("%s: unknown score %r (use gain, keeps)" % (where, k))
                if isinstance(val, bool) or not isinstance(val, int) or not 1 <= val <= 5:
                    raise SpecError("%s: score %s must be a whole number from 1 to 5, got %r" % (where, k, val))
        if c.get("recommended") is not None and not isinstance(c["recommended"], bool):
            raise SpecError("%s: recommended must be true or false" % where)
        scope_css(c["css"], cid)  # a css error is a spec error now, not a broken frame later
    if jb or any(c.get("scores") for c in changes):
        for c in changes:
            if c.get("recommended") and not c.get("scores"):
                raise SpecError("item %s: change %s is recommended but has no scores" % (iid, c["id"]))


# PNG chunks that tell the browser how to color the pixels. Lossless WebP keeps the pixel
# values but none of these the same way: in Chrome, a gAMA PNG through ImageMagick changed
# 99.8% of its pixels and an ICC (iCCP) one through cwebp 48%. A PNG carrying one, or 16 bits
# a channel (ImageMagick rounds them), goes into the base as it is.
PNG_COLOR_CHUNKS = (b"gAMA", b"cHRM", b"iCCP", b"cICP", b"mDCV", b"cLLI")


def png_is_plain(data):
    """True for an 8-bit PNG with none of PNG_COLOR_CHUNKS before its pixels."""
    if data[:8] != b"\x89PNG\r\n\x1a\n" or len(data) < 33 or data[24] != 8:
        return False
    pos = 8
    while pos + 8 <= len(data):
        kind = data[pos + 4:pos + 8]
        if kind in PNG_COLOR_CHUNKS:
            return False
        if kind == b"IDAT":
            return True
        pos += 12 + int.from_bytes(data[pos:pos + 4], "big")
    return False


def snapshot_asset(path, tool, cache):
    """A data URI for one file of the snapshot's assets folder, made once per page. A plain
    PNG (png_is_plain) becomes lossless WebP when that is smaller: never lossy, and never
    resized, because the base must render pixel for pixel like the page (an image's natural
    size is layout)."""
    if path not in cache:
        mime = SNAPSHOT_MIME.get(path.suffix.lower())
        data = None
        if path.suffix.lower() == ".png" and tool is not None and png_is_plain(path.read_bytes()):
            data = encode_webp(path, 100, None, True, tool)
            if data is not None and len(data) >= path.stat().st_size:
                data = None
        cache[path] = data_uri(path, data, "image/webp") if data is not None else data_uri(path, mime=mime)
    return cache[path]


def load_snapshot(it, base, cache):
    """The base snapshot's HTML with every reference into its sibling assets folder
    (<name>-snapshot-assets/<file>, a relative path) replaced by that file's data URI."""
    rel = it["base"]["from"]
    p, tried = find_file(rel, base)
    if p is None:
        raise SpecError("item %s: base: %s not found (tried %s)" % (it["id"], rel, " and ".join(map(str, tried))))
    text = p.read_text()
    # Where the before shots are: --smoke looks beside the snapshot (fidelity.cjs shotNames).
    # Relative to the working directory, so the page names no folder above the project.
    try:
        it["_base_path"] = os.path.relpath(p, Path.cwd())
    except ValueError:  # another drive
        it["_base_path"] = rel
    folder = p.parent / (p.stem + "-assets")
    tool = image_tool()
    if folder.is_dir():
        for f in sorted(folder.iterdir(), key=lambda f: -len(f.name)):
            ref = "%s/%s" % (folder.name, f.name)
            if f.is_file() and ref in text:
                uri = snapshot_asset(f, tool, cache)
                text = text.replace("./" + ref, uri).replace(ref, uri)
    left = re.search(r"%s/[^\s\"')]*" % re.escape(folder.name), text)
    if left:
        raise SpecError("item %s: base refers to %s, which is not in %s" % (it["id"], left.group(0), folder))
    return text


def refine_base(it, base, cache):
    """The snapshot as each frame shows it: every change's scoped CSS in one <style data-rc-css>
    at the end of its <head>, and each swap as a <template> at the end of its <body>."""
    doc = load_snapshot(it, base, cache)
    css = "\n".join("/* %s */\n%s" % (c["id"], scope_css(c["css"], c["id"])) for c in it["changes"])
    style = "<style data-rc-css>\n%s\n</style>\n" % css
    head = re.search(r"</head\s*>", doc, re.I)
    if head:
        doc = doc[:head.start()] + style + doc[head.start():]
    else:
        body = re.search(r"<body\b", doc, re.I)
        at = body.start() if body else 0
        doc = doc[:at] + style + doc[at:]
    tpl = "".join('<template data-rc-swap="%s" data-rc-target="%s">%s</template>\n'
                  % (esc(c["id"]), esc(sw["selector"]), sw["html"])
                  for c in it["changes"] for sw in c.get("swaps") or [])
    if tpl:
        ends = list(re.finditer(r"</body\s*>", doc, re.I))
        at = ends[-1].start() if ends else len(doc)
        doc = doc[:at] + tpl + doc[at:]
    return doc


def render_refine(it, ctx) -> str:
    """The change cards, then the combined preview: both frames of the base, the current
    page's scores and the recommended set's, and the picks/original toggle."""
    dec, iid = it["_dec"], it["id"]
    scored = bool(it.get("judged_by")) or any(c.get("scores") for c in it["changes"])
    h = []
    for c in it["changes"]:
        body = ['<div class="rp-rc-why">%s</div>' % c["why_html"]]
        if c.get("removes"):
            body.append('<ul class="rp-rc-removes">%s</ul>' % "".join(
                '<li class="rp-rc-remove"><b>Removes</b> %s — %s</li>' % (esc(r["element"]), esc(r["reason"]))
                for r in c["removes"]))
        # Filled with the change's before and after crops at 1280 and 390 when the item names `crops`.
        body.append('<div class="rp-rc-crops" data-rc-crops="%s"></div>' % esc(c["id"]))
        if c.get("scores"):
            body.append('<div class="rp-scores">%s</div>' % _score_pairs(c["scores"], REFINE_SCORES))
        elif scored:
            body.append('<div class="rp-scores rp-unscored">Not scored</div>')
        card = review_item({"id": c["id"], "num": c["_num"], "label": c["label"],
                            "location": c.get("location") or it.get("location"),
                            "recommended": c.get("recommended"), "body_html": "\n".join(body)}, dec, ctx.colors)
        h.append(card.replace('<article class="rp-item" ', '<article class="rp-item" data-rc-change="%s" '
                              % esc(c["id"]), 1))
    p = ['<div class="rp-rc-preview" data-rc-preview="%s" data-rc-base="%s">' % (esc(iid), esc(it["_base_path"])),
         '<div class="rp-rc-head"><h3 class="rp-rc-title">Your picks together</h3>'
         '<div class="rp-rc-view" role="group" aria-label="Show the preview">'
         '<button type="button" class="rp-chip-btn" data-rc-view="picks" aria-pressed="true">With your picks</button>'
         '<button type="button" class="rp-chip-btn" data-rc-view="original" aria-pressed="false">Original</button>'
         '</div></div>',
         '<p class="rp-rc-note">Each change you answer Yes turns on here.</p>']
    for key, label, cls in (("before_scores", "Current page", "rp-before-scores"),
                            ("set_scores", "Your picks together (recommended)", "rp-set-scores")):
        if it.get(key):
            p.append('<div class="rp-scores %s"><span class="rp-scores-label">%s</span> %s</div>'
                     % (cls, label, _score_pairs(it[key], SCORE_DIMS)))
    if it.get("judged_by"):
        p.append('<div class="rp-judged">%s</div>' % JUDGED_BY[it["judged_by"]])
    # The snapshot is on the page once, as a JSON string the engine gives both frames as
    # their srcdoc. Every "<" is escaped, so a "</script>" in the page's text cannot end it.
    p.append('<script type="application/json" id="rp-rc-base-%s">%s</script>'
             % (esc(iid), json.dumps(it["_doc"], ensure_ascii=False).replace("<", "\\u003c")))
    p.append('<div class="rp-rc-frames">')
    for width, caption in REFINE_WIDTHS:
        p.append('<figure class="rp-rc-fig" data-rc-fig="%d"><figcaption>%s</figcaption><div class="rp-rc-box">'
                 '<iframe class="rp-rc-frame" data-rc-width="%d" width="%d" title="The page with your picks, %s">'
                 '</iframe></div></figure>' % (width, caption, width, width, caption))
    p.append("</div></div>")
    return "\n".join(h + ["\n".join(p)])


def refine_entry(it, sec, ctx):
    """Validate, number and render one refine item: (html, one JS item per change)."""
    it["id"] = str(it.get("id") or "refine")
    if sec.get("_preset") != "refine":
        raise SpecError('item %s: a refine item needs the "refine" decisions preset (its section has %r)'
                        % (it["id"], sec.get("_preset")))
    if ctx.refine is not None:
        raise SpecError("item %s: one refine item per page (item %s is one already)" % (it["id"], ctx.refine))
    ctx.refine = it["id"]
    check_refine_fields(it)
    ctx.claim(it["id"], "item")
    for c in it["changes"]:
        ctx.claim(c["id"], "change")
        ctx.n += 1
        c["_num"] = str(ctx.n)
    it["_dec"] = sec["_dec"]
    it["_doc"] = refine_base(it, ctx.spec.get("_base") or Path.cwd(), {})
    js = [{"id": c["id"], "num": c["_num"], "label": c["label"], "category": None, "variants": [],
           "selected": None, "before_font_sizes": [], "before_sections": None,
           # Measured inside the frames, never as mockups: no near-copy check (spec §3).
           "design_review": False, "near_copy": False, "refine": it["id"]} for c in it["changes"]]
    return render_refine(it, ctx), js


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
    for rid, base in re.findall(r'<script type="application/json" id="(rp-rc-base-[^"]+)">(.*?)</script>', text, re.S):
        try:
            if not isinstance(json.loads(base), str):
                raise ValueError("not a string")
        except ValueError as e:
            errs.append("%s is not valid JSON: %s" % (rid, e))
    title = re.search(r"<title>(.*?)</title>", text, re.S)
    if not title or not title.group(1).strip():
        errs.append("page has no <title>")
    ids = re.findall(r'\sid="([^"]+)"', text)
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        errs.append("duplicate element ids: %s" % ", ".join(dup))
    # An in-page link must land somewhere: "Open questions above" with no questions
    # left on the page sends the reader to nothing (a stale link after they answered).
    for target in re.findall(r'<li[^>]*>.*?<a href="#([^"]+)"', text):
        if target not in ids:
            errs.append("link to #%s, but nothing on the page has that id (answered already? mark the link in-progress)"
                        % target)
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
        for sec in secs:
            if sec["kind"] == "settings":
                keys = re.findall(r'<div class="rp-set-row" data-set-row="([^"]+)"', text)
                want = [it["id"] for it in sec["items"]]
                if sorted(keys) != sorted(want):
                    errs.append("settings: %d rows on the page for %d settings" % (len(keys), len(want)))
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
    errs.extend(image_errors(text))
    return errs


def image_errors(text):
    """Images older Safari would show as a broken "?": a <picture> with no non-WebP
    <img> fallback, or a placeholder the fill script has nothing to fill from."""
    errs = []
    m = re.search(r'<script type="application/json" id="rp-assets">(.*?)</script>', text, re.S)
    try:
        shared = json.loads(m.group(1)) if m else {}
    except ValueError as e:
        return ["rp-assets is not valid JSON: %s" % e]
    for i, pic in enumerate(re.findall(r"<picture\b.*?</picture>", text, re.S), 1):
        img = re.search(r"<img\b[^<>]*>", pic)
        src = img and re.search(r'\ssrc="([^"]*)"', img.group(0))
        if not src:
            errs.append("picture %d has no <img src> fallback" % i)
        elif src.group(1).startswith("data:image/webp"):
            errs.append("picture %d falls back to WebP, which older Safari cannot show" % i)
    for tag in re.findall(r"<[a-z]+\b[^<>]*\bdata-rp-asset=\"[^\"]*\"[^<>]*>", text):
        attr, name, fmt = (re.search(r'data-rp-asset="([^"]*)"', tag).group(1).split(" ") + ["", "", ""])[:3]
        if not (shared.get(name) or {}).get(fmt):
            errs.append("shared image %r (%s) has nothing in rp-assets to fill it from" % (name, fmt or "?"))
    for tag in re.findall(r"<img\b[^<>]*>", text):
        if BLANK_GIF in tag and "data-rp-asset=" not in tag:
            errs.append("an <img> is left with the blank placeholder and nothing fills it")
    return errs


NO_SESSION = "no session name: the reader can't tell which session this page belongs to (set project.session)"

# British spelling (regex, word-bounded and case-insensitive) -> American form of the stem.
# The stem is the literal text before the first "(" in the key.
BRITISH = {
    r"behaviour(s)?": "behavior",
    r"colour(s|ed|ing|ful)?": "color",
    r"favour(s|ed|ing|ite|ites)?": "favor",
    r"honour(s|ed|ing)?": "honor",
    r"labour": "labor",
    r"neighbour(s|hood)?": "neighbor",
    r"flavour(s)?": "flavor",
    r"labell(ed|ing)": "label",
    r"modell(ed|ing)": "model",
    r"travell(ed|ing|er)": "travel",
    r"grey(s|er|ish)?": "gray",
    r"centre(s)?": "center",
    r"centred": "centered",
    r"metre(s)?": "meter",
    r"litre(s)?": "liter",
    r"fibre(s)?": "fiber",
    r"theatre(s)?": "theater",
    r"defence(s)?": "defense",
    r"catalogue(s)?": "catalog",
    r"catalogued": "cataloged",
    r"analys(e|ed|ing)": "analyz",
    **{r"%sis(e|es|ed|ing|ation|ations)" % stem: stem + "iz" for stem in (
        "organ", "recogn", "real", "priorit", "summar", "normal", "anonym", "custom",
        "optim", "minim", "maxim", "standard", "categor", "emphas")},
}
_BRITISH_RE = [(re.compile(r"\b(?:%s)\b" % pat, re.I), re.match(r"[a-z]+", pat).group(), us)
               for pat, us in BRITISH.items()]


def _scan(text, where, seen, out):
    for rx, stem, us in _BRITISH_RE:
        for m in rx.finditer(text):
            key = m.group(0).lower()
            if key not in seen:
                seen.add(key)
                out.append('british spelling "%s" (American: "%s") in %s' % (key, us + key[len(stem):], where))


def page_spelling_warnings(text):
    """The same check on a built page, where the reader's text lives (rp-spec keeps only a
    trimmed spec). Scripts, styles and code are dropped, tags go with their URLs (alt and title
    text is kept), and each hit is named by the nearest preceding element id."""
    text = re.sub(r"<(script|style|code)\b.*?</\1>", " ", text, flags=re.S | re.I)
    seen, out, where = set(), [], "the page"
    for chunk in re.split(r"(<[^>]*>)", text):
        if chunk.startswith("<"):
            m = re.search(r'\sid="([^"]+)"', chunk)
            where = m.group(1) if m else where
            for attr in re.findall(r'\s(?:alt|title)="([^"]*)"', chunk):
                _scan(html.unescape(attr), where, seen, out)
        else:
            _scan(html.unescape(chunk), where, seen, out)
    return out


GENERIC_FONTS = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif",
                 "ui-sans-serif", "ui-monospace", "ui-rounded", "math", "emoji", "fangsong"}
FONT_KEYWORDS = {"inherit", "initial", "unset", "revert", "revert-layer"}


def font_warnings(text):
    """Each font-family stack (in a <style> or a style attribute) that does not end in a
    generic family. A mockup font that fails to load then falls to the browser default
    instead of something that resembles it. @font-face names are not stacks."""
    css = " ".join(re.findall(r"<style\b[^>]*>(.*?)</style>", text, re.S | re.I))
    css = re.sub(r"@font-face\s*\{[^}]*\}", " ", css)
    attrs = [html.unescape(a) for a in re.findall(r'\sstyle="([^"]*)"', text)]
    out = []
    for value in re.findall(r"font-family\s*:\s*([^;}]+)", " ; ".join([css] + attrs)):
        value = value.strip()
        low = value.lower()
        if not value or low.startswith("var(") or low in FONT_KEYWORDS:
            continue
        last = low.rsplit(",", 1)[-1].strip().strip("\"'")
        if last in GENERIC_FONTS or last.startswith("var("):
            continue
        line = ("font-family %s has no fallback stack: end it with fonts that resemble it and a generic family "
                "(sans-serif, serif, monospace or system-ui), or a font that does not load shows the browser "
                "default" % value)
        if line not in out:
            out.append(line)
    return out


def warnings(path):
    """Problems worth saying that still leave a working page: older specs keep building."""
    m = re.search(r'<script type="application/json" id="rp-spec">(.*?)</script>', Path(path).read_text(), re.S)
    try:
        spec = json.loads(m.group(1)) if m else {}
    except ValueError:
        return []
    out = [NO_SESSION] if spec.get("mode") in ("review", "questions") and not spec.get("session") else []
    text = Path(path).read_text()
    bare = [t for t in re.findall(r"<img\b[^<>]*>", re.sub(r"<picture\b.*?</picture>", "", text, flags=re.S))
            if 'src="data:image/webp' in t]
    if bare:
        out.append("%d <img> show WebP with no fallback, so older Safari shows a broken image "
                   "(use a PNG or JPEG asset and the builder adds one)" % len(bare))
    out.extend(font_warnings(text))
    if proofs_settings.get("PROOFS_SPELLING") == "american":
        out.extend(page_spelling_warnings(text))
    return out


HOW_TO_PY = ("Install Google Chrome, or point PROOFS_BROWSER_CHANNEL at another installed channel. "
             "No browser download is needed: "
             "npm install --prefix ~/.cache/proofs-playwright playwright@1.61.1")


def find_playwright(arg):
    for c in (arg, os.environ.get("PROOFS_PLAYWRIGHT")):
        if c and (Path(c) / "package.json").is_file():
            return str(Path(c).resolve())
    cached = Path.home() / ".cache" / "proofs-playwright" / "node_modules" / "playwright"
    if (cached / "package.json").is_file():
        return str(cached.resolve())
    node = shutil.which("node")
    if node:
        r = subprocess.run([node, "-e", "console.log(require.resolve('playwright/package.json'))"],
                           capture_output=True, text=True, cwd=os.getcwd())
        if r.returncode == 0:
            return str(Path(r.stdout.strip()).parent)
    return None


def smoke(path, playwright=None, shots=None):
    """Click through the page in headless Chromium. Returns (ok, result dict). shots: the folder
    a Refine page's before shots are in, when not beside its base snapshot."""
    pw = find_playwright(playwright)
    if not pw:
        return None, {"error": "Playwright not found. " + HOW_TO_PY}
    r = subprocess.run([shutil.which("node"), str(SMOKE), pw, str(Path(path).resolve())]
                       + ([str(Path(shots).resolve())] if shots else []),
                       capture_output=True, text=True, timeout=600)
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return False, {"error": (r.stdout + r.stderr).strip()[-2000:]}
    return not res.get("problems"), res


def match_preview(page_path, picks, shots, playwright=None):
    """--match-preview: the built page's shots in `shots` against the Refine preview with the
    picked changes on (fidelity.cjs comparePicks). Prints one line per width; returns the exit
    code: 0 on a match, 1 when a width differs or has no shot, 2 when it cannot be measured."""
    pw = find_playwright(playwright)
    if not pw:
        print("match-preview: Playwright not found. " + HOW_TO_PY, file=sys.stderr)
        return 2
    nums = [n.strip() for n in str(picks).split(",") if n.strip()]
    if not nums:
        print("match-preview: --picks needs the numbers of the changes answered Yes, such as 1,3", file=sys.stderr)
        return 2
    r = subprocess.run([shutil.which("node"), str(MATCH), pw, str(Path(page_path).resolve()), ",".join(nums),
                        str(Path(shots).resolve())], capture_output=True, text=True, timeout=600)
    try:
        res = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print("match-preview: " + (r.stdout + r.stderr).strip()[-2000:], file=sys.stderr)
        return 2
    if res.get("error"):
        print("match-preview: " + res["error"], file=sys.stderr)
        return 2
    for line in res["lines"]:
        print(line)
    return 0 if res["match"] else 1


def answers(page_path, rows):
    """Print a page's answers from its database rows, as its Copy export. Returns the exit code."""
    node = shutil.which("node")
    if not node:
        print("node is not installed: use the page's Copy button instead", file=sys.stderr)
        return 2
    r = subprocess.run([node, str(ANSWERS), str(page_path), str(rows)], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spec", nargs="?", help="JSON spec to build")
    ap.add_argument("--out", help="where to write the page (a session or log page defaults to .proofs/pages/SPEC.html)")
    ap.add_argument("--no-check", action="store_true", help="skip the check after building")
    ap.add_argument("--check", metavar="PAGE", help="check a built page")
    ap.add_argument("--smoke", metavar="PAGE", help="click through a built page in headless Chromium")
    ap.add_argument("--playwright", help="folder of an installed playwright package")
    ap.add_argument("--match-preview", metavar="PAGE", help="compare the built page's shots (--shots) with "
                    "PAGE's Refine preview with the picked changes (--picks) on")
    ap.add_argument("--picks", help="with --match-preview: the numbers of the changes answered Yes, such as 1,3")
    ap.add_argument("--shots", metavar="DIR", help="with --match-preview: the folder of the capture of the built "
                    "page; with --smoke: where a Refine page's before shots are, when not beside its base")
    ap.add_argument("--answers", metavar="PAGE", help="print PAGE's answers from its database rows (--rows) "
                    "as the same text its Copy button makes")
    ap.add_argument("--rows", metavar="PATH", help="with --answers: the out_dir ArtifactData list wrote, or a JSON file")
    a = ap.parse_args(argv)
    if a.answers:
        if not a.rows:
            ap.error("--answers needs --rows (the folder ArtifactData list wrote with out_dir)")
        return answers(a.answers, a.rows)
    if a.match_preview:
        if not (a.picks and a.shots):
            ap.error("--match-preview needs --picks (such as 1,3) and --shots (the capture's folder)")
        return match_preview(a.match_preview, a.picks, a.shots, a.playwright)
    if a.check or a.smoke:
        target = a.check or a.smoke
        errs = check(target)
        for w in warnings(target):
            print("warning: " + w, file=sys.stderr)
        for e in errs:
            print("check: " + e, file=sys.stderr)
        if errs:
            return 1
        if a.smoke:
            ok, res = smoke(target, a.playwright, a.shots)
            print(json.dumps(res, indent=2, ensure_ascii=False))
            if ok is None:
                return 2
            return 0 if ok else 1
        print("check: ok (%s)" % target)
        return 0
    if not a.spec:
        ap.error("give SPEC.json --out PAGE.html, or --check PAGE, or --smoke PAGE")
    try:
        spec = load_spec(a.spec)
        if not a.out:
            if spec["mode"] not in DEFAULT_OUT_MODES:
                ap.error("give --out PAGE.html (only a session or log page has a default)")
            # Under .proofs/pages/, the one folder the optional `open` allow rule covers.
            a.out = str(Path(".proofs", "pages", Path(a.spec).stem + ".html"))
        text = page(spec)
    except (SpecError, ValueError, KeyError) as e:
        print("spec error: %s" % e, file=sys.stderr)
        return 1
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(text)
    parts = Path(a.out).resolve().parts
    if ".proofs" in parts:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            import proofs_dir
            proofs_dir.ensure_excluded(Path(*parts[:parts.index(".proofs")]))
        except Exception:
            pass
    print("wrote %s (%d KB)" % (a.out, len(text.encode()) // 1024))
    print("publish with capabilities: %s (saved answers need db, Send to Claude needs comments; "
          "a republish that leaves capabilities out keeps them)" % json.dumps(CAPABILITIES))
    for line in (image_line(spec), size_warning(text, spec)):
        if line:
            print(line)
    if a.no_check:
        return 0
    errs = check(a.out)
    for e in errs:
        print("check: " + e, file=sys.stderr)
    for w in warnings(a.out):
        print("warning: " + w, file=sys.stderr)
    if not errs:
        print("check: ok")
    return 1 if errs else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except proofs_settings.SettingsFileError as e:  # one line naming the file, not a traceback
        print("review_page: %s" % e, file=sys.stderr)
        sys.exit(3)
