"""Import approved before/after examples into the site and README.

Usage: python3 site-src/import_examples.py FINAL_DIR [--root REPO_ROOT]

FINAL_DIR holds manifest.json and one folder per example:
  <id>/before.jpg  <id>/after.jpg          a two-frame pair
  <id>/picker.jpg                          optional middle step (photo-picker)
  <id>/step1.jpg <id>/step2.jpg ...         or numbered steps instead
  <id>/wipe.gif                            optional animated wipe, used by the README

manifest.json is a list of entries, {"examples": [...]}, or {id: entry}. Each entry has
title, skill, caption (or a one-line "short" caption, preferred when present) and use ("hero", "featured" or "skill"), and may add labels
({"before": "...", "after": "..."}), view ("phone" or "desktop") and frames.

It replaces what it owns, so the manifest is always the full set:
  docs/examples/<id>/<frame>-<width>.webp and .jpg   resized, metadata stripped
  assets/examples/<id>/wipe.gif                      for the README (GitHub runs no scripts)
  site-src/examples.json                             read by build.py
  README.md, between the <!-- examples:grid --> markers

Needs ImageMagick (magick, or convert on version 6). Run build.py afterwards.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SITE = "https://workingben.github.io/proofs/"
WIDTHS = (480, 960)
JPG_Q, WEBP_Q = "78", "74"
README_GRID = 8
CAPTION_MAX = 90

# Best first. Ids not listed keep their manifest order, after these.
ORDER = [
    "c-retreat-look", "c-hero-photos-3step",
    "b-bed-map-report", "d-movie-page", "a-organ-table-to-gauges", "b-supplement-chart",
    "d-book-cover-wall", "a-report-stacks", "b-nine-devices", "e-card-back",
    "a-standards-scales", "a-biowell-table-to-chart", "a-improvement-scale", "b-bbi-plan",
    "d-booking-dates", "d-collection-slideshow", "x-copy-edit",
]
# Left out of the site even when the manifest lists them. To bring one back, delete it
# here and put its id in ORDER where it should appear.
SKIP = {
    "b-device-heat-table": "dropped",
    "e-stays-photos": "held",
}
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")
DEFAULT_LABELS = {"before": "Before", "picker": "The picker", "after": "After"}


def die(msg):
    sys.exit(f"import_examples: {msg}")


def magick():
    for name in ("magick", "convert"):
        if shutil.which(name):
            return [name]
    die("ImageMagick not found (install it, then run again)")


def identify(tool, path):
    cmd = (tool + ["identify"]) if tool == ["magick"] else ["identify"]
    out = subprocess.run(cmd + ["-format", "%w %h", path + "[0]"], capture_output=True, text=True, check=True)
    w, h = out.stdout.split()[:2]
    return int(w), int(h)


def entries(manifest):
    for key in ("examples", "items"):
        if isinstance(manifest, dict) and key in manifest:
            manifest = manifest[key]
            break
    if isinstance(manifest, dict):
        manifest = [dict(v, id=v.get("id", k)) for k, v in manifest.items()]
    if not isinstance(manifest, list):
        die("manifest.json must be a list, {\"examples\": [...]}, {\"items\": [...]} or {id: entry}")
    # Entries with a status must be approved; dropped and held ones stay out.
    return [e for e in manifest if e.get("status", "approved") == "approved"]


def use_of(entry):
    u = str(entry.get("use", "featured")).lower()
    if "hero" in u:
        return "hero"
    if u.startswith("skill") or u in ("none", "skip"):
        return "skill"
    return "featured"


def frame_files(folder, wanted=None):
    files = {os.path.splitext(f)[0].lower(): f for f in os.listdir(folder) if f.lower().endswith(IMG_EXT)}
    if wanted:
        names = [n for n in wanted if n in files]
    else:
        steps = sorted((n for n in files if re.fullmatch(r"step[-_]?\d+", n)), key=lambda n: int(re.sub(r"\D", "", n)))
        names = steps or [n for n in ("before", "picker", "after") if n in files]
    return [(n, os.path.join(folder, files[n])) for n in names]


def resize(tool, src, dst, width, quality):
    subprocess.run(tool + [src + "[0]", "-auto-orient", "-strip", "-resize", f"{width}x>",
                           "-quality", quality] + (["-interlace", "Plane"] if dst.endswith(".jpg") else []) + [dst],
                   check=True)


def readme_block(examples):
    """The README's See it work grid. The hero example leads it; the 30-second tour is the README's top picture."""
    gifs = [x for x in examples if x["gif"]]
    gifs.sort(key=lambda x: x["use"] != "hero")
    grid = [x for x in gifs if x["use"] != "skill"][:README_GRID]
    rows = ""
    for i in range(0, len(grid), 2):
        cells = ""
        for x in grid[i:i + 2]:
            cells += (f'<td width="50%" valign="top"><img src="{x["gif"]}" width="100%" '
                      f'alt="{esc(x["title"])}: before and after."><br>'
                      f'<b><a href="{SITE}{x["skill"]}.html">{x["skill"]}</a></b> · {esc(x["caption"])}</td>')
        rows += f"<tr>{cells}</tr>\n"
    grid_md = ""
    if rows:
        grid_md = ("## See it work\n\nReal pages, before and after one review. "
                   f"[See all of them, as sliders]({SITE}).\n\n<table>\n{rows}</table>")
    return grid_md


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def replace_block(text, name, body):
    rx = re.compile(rf"(<!-- examples:{name}:start -->\n).*?(\n?<!-- examples:{name}:end -->)", re.S)
    if not rx.search(text):
        return text, False
    return rx.sub(lambda m: m.group(1) + body + ("\n" if body else "") + m.group(2).lstrip("\n"), text), True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("final_dir")
    ap.add_argument("--root", default=REPO, help="repo root to write into (tests use a temp dir)")
    a = ap.parse_args(argv)
    src = os.path.abspath(a.final_dir)
    root = os.path.abspath(a.root)
    mpath = os.path.join(src, "manifest.json")
    if not os.path.isfile(mpath):
        die(f"no manifest.json in {src}")
    skills = {d for d in os.listdir(os.path.join(REPO, "skills")) if os.path.isfile(os.path.join(REPO, "skills", d, "SKILL.md"))}
    tool = magick()

    items = entries(json.load(open(mpath, encoding="utf-8")))
    rank = {i: n for n, i in enumerate(ORDER)}
    items = sorted(enumerate(items), key=lambda t: (rank.get(t[1].get("id"), len(ORDER)), t[0]))

    web_root = os.path.join(root, "docs", "examples")
    gif_root = os.path.join(root, "assets", "examples")
    for d in (web_root, gif_root):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)

    out, total = [], 0
    for _, e in items:
        xid = e.get("id")
        if xid in SKIP:
            print(f"skipped {xid} ({SKIP[xid]})", file=sys.stderr)
            continue
        if not xid or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", xid):
            die(f"bad or missing id: {xid!r}")
        e["caption"] = e.get("short") or e.get("caption")
        for k in ("title", "skill", "caption"):
            if not e.get(k):
                die(f"{xid}: missing {k}")
        if len(e["caption"]) > CAPTION_MAX:
            print(f"warning: {xid} caption is {len(e['caption'])} characters; keep it under {CAPTION_MAX}", file=sys.stderr)
        if e["skill"] not in skills:
            die(f"{xid}: unknown skill {e['skill']!r}")
        folder = os.path.join(src, xid)
        if not os.path.isdir(folder):
            die(f"{xid}: no folder {folder}")
        frames = frame_files(folder, e.get("frames"))
        if len(frames) < 2:
            die(f"{xid}: needs at least before and after images")
        w, h = identify(tool, frames[0][1])
        labels = dict(DEFAULT_LABELS, **(e.get("labels") or {}))
        os.makedirs(os.path.join(web_root, xid))
        fr = []
        for name, path in frames:
            fw, fh = identify(tool, path)
            if (fw, fh) != (w, h):
                print(f"warning: {xid}/{name} is {fw}x{fh}, first frame is {w}x{h}", file=sys.stderr)
            widths = sorted({min(x, w) for x in WIDTHS})
            for x in widths:
                for ext, q in (("webp", WEBP_Q), ("jpg", JPG_Q)):
                    dst = os.path.join(web_root, xid, f"{name}-{x}.{ext}")
                    resize(tool, path, dst, x, q)
                    total += os.path.getsize(dst)
            label = labels.get(name) or (f"Step {name[-1]}" if name.startswith("step") else name.title())
            fr.append({"name": name, "label": label, "widths": widths})
        gif = None
        if os.path.isfile(os.path.join(folder, "wipe.gif")):
            os.makedirs(os.path.join(gif_root, xid))
            shutil.copyfile(os.path.join(folder, "wipe.gif"), os.path.join(gif_root, xid, "wipe.gif"))
            gif = f"assets/examples/{xid}/wipe.gif"
        out.append({"id": xid, "title": e["title"], "skill": e["skill"], "caption": e["caption"],
                    "use": use_of(e), "view": e.get("view") or ("phone" if h > w else "desktop"),
                    "w": w, "h": h, "frames": fr, "gif": gif})

    os.makedirs(os.path.join(root, "site-src"), exist_ok=True)
    with open(os.path.join(root, "site-src", "examples.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_by": "site-src/import_examples.py", "examples": out}, f, indent=1, ensure_ascii=False)
        f.write("\n")

    readme = os.path.join(root, "README.md")
    if os.path.isfile(readme):
        text = open(readme, encoding="utf-8").read()
        text, ok = replace_block(text, "grid", readme_block(out))
        if not ok:
            print("warning: README.md is missing the examples markers; left as is", file=sys.stderr)
        open(readme, "w", encoding="utf-8").write(text)

    print(f"imported {len(out)} examples, {total // 1024} KB of site images; now run: python3 site-src/build.py")
    return out


if __name__ == "__main__":
    main()
