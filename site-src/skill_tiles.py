"""Build the README's skill tiles: docs/cards/<skill>.jpg with the skill's name, top-pick label and one-line
description drawn under it, as docs/cards/tiles/<skill>.jpg. A README cannot style text, and only pictures wrap
from two across (laptop) to one per row (phone). Run after changing a card or a line below:
    python3 site-src/skill_tiles.py
Since 2026-11-21 the README lists the skills as grouped text instead of these tiles, so nothing links
them now; they are kept in case the README goes back to pictures."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import import_examples as ie  # noqa: E402  (same colors, fonts and band layout as the example tiles)

REPO = os.path.dirname(HERE)
# (skill, top-pick label or "", description) in README order: most useful first
TILES = [
    ('working-log', 'Most used', "One page per session: what's waiting on you first, then the log, with one Copy button."),
    ('design-review', 'Start here', 'Your live page next to three scored mockups per section, one for a small fix. You pick, Claude builds it.'),
    ('pr-qa', 'Critical for UI changes', 'Before and after screenshots of each open pull request, with one decision per PR.'),
    ('questions', '', "Claude's questions on a page, with real buttons, its pick marked and one Copy."),
    ('visual-qa', '', 'Measures pages at three screen sizes, finds layout problems, and designs the fixes.'),
    ('article-copy-edit', '', 'Line edits shown on your real article, with a claims check first.'),
    ('review-cycle', '', 'Report bugs and ideas as they come; each is fixed, reviewed or saved for later.'),
    ('qa-checklist', '', "The checks only you can run, each marked Pass, Fail or Couldn't test."),
    ('todos', '', 'Your to-do list as a tickable page. Done items are checked before they are archived.'),
    ('photo-picker', '', 'Licensed photo candidates for every spot that needs one, in a gallery you choose from.'),
    ('style-guide', '', 'Audits the whole site for one consistent look and saves the rules you accept.'),
    ('changelog', '', 'A "What\'s new" page split by month, updated at the end of every session that ships something.'),
]


def main():
    tool = ie.magick()
    out_dir = os.path.join(REPO, "docs", "cards", "tiles")
    os.makedirs(out_dir, exist_ok=True)
    bands = {}
    for name, pick, text in TILES:
        bands[name] = os.path.join(out_dir, name + ".band.png")
        label = f"{name}  ·  ★ {pick}" if pick else name
        ie.caption_band(tool, {"skill": label, "caption": text}, bands[name])
    band_h = max(ie.identify(tool, f)[1] for f in bands.values())
    for name, _, _ in TILES:
        subprocess.run(tool + [os.path.join(REPO, "docs", "cards", name + ".jpg"), "-resize", f"{ie.TILE_CELL[0]}x",
                               "(", bands[name], "-background", ie.TILE_BG, "-gravity", "north", "-extent", f"{ie.TILE_CELL[0]}x{band_h}", ")",
                               "-append", "-quality", "85", os.path.join(out_dir, name + ".jpg")], check=True)
        os.remove(bands[name])
    print(f"built {len(TILES)} skill tiles in docs/cards/tiles")


if __name__ == "__main__":
    main()
