"""Turn a pasted export back into decisions about TODO.md.

Matching is by TITLE, not by number or id. Numbers are reassigned on every
apply and `t7` means nothing pasted into a chat window, so the title is the
only stable handle between the page and the file.

The export format matched here is what scripts/todos_page.py's build() (in its
<script> block) actually emits -- confirmed 2026-08-06 by driving the real
generated page through jsdom, ticking boxes, and reading the captured clipboard
text back. Two things worth knowing that a first read of the JS would not make
obvious:
  - Each item line carries its full, untruncated title (the checkbox's
    data-title attribute, "N. Title", no body text appended) -- never the
    (possibly 96-char-clipped) label text a human sees on the page. The
    matcher below still copes with a truncated or hand-edited title, because
    a human can edit the paste before sending it even though the page itself
    never truncates what it copies.
  - The header line reads "TODOS — my replies", not anything else. It is
    never parsed -- LINE_RE/NOTE_RE/FREE_RE only look at item, note and
    freeform lines -- so its exact wording does not matter here.

Run:  python3 scripts/todos_apply.py export.txt [TODO.md]
"""
import json
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from todos_parse import parse

LINE_RE = re.compile(r"^\s+\[([ x])\]\s+(.+?)\s*$")
NOTE_RE = re.compile(r"^\s+note:\s*(.*)$")
FREE_RE = re.compile(r"^Anything else:\s*$")


def _key(title):
    """Compare on the leading sentence, lowercased, punctuation-insensitive.

    The real export always carries a full, untruncated title (see the module
    docstring), but a human can hand-edit the paste before sending it, and
    might shorten a title with an ellipsis of their own. Stripping at "..."
    and comparing only a lowercased, depunctuated prefix means both the
    machine-generated line and a hand-trimmed one resolve to the same item.

    A title's TERMINAL punctuation mark -- whichever of . ? ! : it ends on,
    if any -- is deliberately KEPT; every other punctuation mark, anywhere
    else in the title, is still stripped (fix round 1, 2026-08-06; generalized
    fix round 2, 2026-08-06, same principle, one character short the first
    time). The terminal mark is the only signal that distinguishes a genuine,
    complete, un-truncated title from a same-length truncation of a longer
    title that shares its opening words -- "Deploy now?" (a whole title)
    versus "Deploy now" (the first two words of "Deploy now or wait?"). Strip
    it like the rest of the punctuation and the two become the identical key:
    a correct, full paste of the SHORT item's own title would then be flagged
    ambiguous against the long one forever, with no paste able to tell them
    apart. Round 1 fixed this for "." alone and missed that "?", "!" and ":"
    end a title exactly as validly -- confirmed by review with "Deploy now?"
    vs "Deploy now or wait?". The rule is general on purpose so a third mark
    doesn't reopen the same bug a third time: the LAST character carries the
    completeness signal, whatever it is; nothing before it does.
    """
    title = re.sub(r"^\d+\.\s*", "", title.strip())
    title = title.split("...")[0].strip()
    terminal = title[-1] if title and title[-1] in ".?!:" else ""
    body = re.sub(r"[^a-z0-9 ]", "", title.lower()).strip()
    # No length cap (fix round 3, 2026-08-06; an earlier [:60] here was cut
    # AFTER the terminal mark was appended, so it wasn't just imprecision --
    # two items sharing a 60-character opening became permanently
    # indistinguishable, and `match()`'s own "retype it more specifically"
    # advice on an ambiguous row was a lie: no paste, however precise, could
    # produce a different key once both had been sheared to the same 60
    # characters. Keys are short in-memory strings compared once per pasted
    # row, not a hot loop, so there is nothing a cap here would be buying.
    return body + terminal


def parse_export(text):
    """Split a pasted export into ticked items, unticked items, and free text.

    Each ticked/unticked row is {"title": str, "note": str}; a `note:` line
    attaches to whichever item line most recently preceded it. Everything
    after a line reading "Anything else:" is captured verbatim as free text,
    stripped of leading/trailing blank lines.
    """
    ticked, unticked, free, in_free = [], [], [], False
    last = None
    for line in text.split("\n"):
        if FREE_RE.match(line):
            in_free = True
            continue
        if in_free:
            free.append(line)
            continue
        hit = LINE_RE.match(line)
        if hit:
            last = {"title": hit.group(2), "note": ""}
            (ticked if hit.group(1) == "x" else unticked).append(last)
            continue
        note = NOTE_RE.match(line)
        if note and last is not None:
            last["note"] = note.group(1).strip()
    return {"ticked": ticked, "unticked": unticked,
            "free": "\n".join(free).strip()}


# A prefix match below this length is cheap to get by accident -- "connect"
# alone would resolve to any item starting with that word. This is only the
# early guard, though; uniqueness (below) is what actually protects against a
# wrong silent match, because a floor can never rule out two items that both
# happen to be long enough and share a stem (fix round 1, 2026-08-06: a
# hand-truncated "2. Connect GitHub" matched item 1, "Connect GitHub.",
# because it was also an exact key AND a strict prefix of item 2's key --
# "Connect GitHub and Slack together." -- and the old code returned on the
# first hit without checking for a second).
#
# 8, not the ~12 first suggested for this fix: fix round 1's own second
# reproduction -- "2. Merge the" against "Merge the PR into main." / "Merge
# the docs site rebuild." -- keys at 9 characters ("merge the"), and that
# case has to come back ambiguous too, not silently pass through as a plain
# no-match. 8 still rules out a single common word (5-7 chars) matching by
# accident; the two-word case that must still be caught is 9.
PREFIX_FLOOR = 8


def _index_entries(items):
    """(key, item) pairs to match a pasted title against -- title alone, and
    title with the first line of body appended, since either can appear in a
    hand-edited paste."""
    entries = []
    for item in items:
        entries.append((_key(item["title"]), item))
        entries.append((_key(item["title"] + " " + item["body"].split("\n")[0]), item))
    return entries


def match(export, items):
    """Match each ticked export row back to a real TODO.md item, by title.

    Never by `n` or `id` -- both are reassigned on every apply (see the module
    docstring). For each row, every item whose key could plausibly be what
    was pasted is collected as a candidate -- an exact key match, or a prefix
    match (in either direction, to cope with a hand-truncated paste) at least
    PREFIX_FLOOR characters long. Exactly one candidate is a match. Zero or
    two-or-more both go to `unmatched`: zero because nothing named it, two-or-
    more because guessing between them would silently archive the wrong item
    -- the failure mode fix round 1 found. An ambiguous row's `unmatched`
    entry names every candidate, so a human can see what was ambiguous and
    retype it more specifically.
    """
    entries = _index_entries(items)
    matched, unmatched = [], []
    for row in export["ticked"]:
        row_key = _key(row["title"])
        # Keyed on item["id"], not Python's id(item) (fix round 3,
        # 2026-08-06): id() is a memory address, correct only by accident of
        # `items` being the parser's own list where every dict is a distinct
        # object. Anything that copies or reconstructs an item -- exactly
        # what this module's own tests do to simulate renumbering -- would
        # produce two equal-but-distinct dicts that both survive the dedupe,
        # turning a genuine single match into a false "ambiguous".
        candidates = {}
        if row_key:
            for key, item in entries:
                if not key:
                    continue
                if key == row_key:
                    candidates[item["id"]] = item
                    continue
                shortest = min(len(key), len(row_key))
                if shortest >= PREFIX_FLOOR and key[:shortest] == row_key[:shortest]:
                    candidates[item["id"]] = item
        found = list(candidates.values())
        if len(found) == 1:
            matched.append((found[0], row["note"]))
        elif len(found) == 0:
            unmatched.append(row["title"])
        else:
            found.sort(key=lambda i: i["n"])
            names = "; ".join("%d. %s" % (i["n"], i["title"]) for i in found)
            unmatched.append(
                '"%s" is ambiguous -- matches: %s' % (row["title"], names))
    return {"matched": matched, "unmatched": unmatched}


def plan(export, items):
    """Turn matched items into an archive/verify decision, by group.

    `Yours`/`Decide` items (verify == "none") can only be closed by the human
    who ticked them, so they go straight to `archive`. `Build`/`Backlog`/
    `Ongoing` items (verify == "repo") go to `verify` first -- a tick is a
    claim, not proof, and this is the point where it gets checked against the
    repo before anything is moved.
    """
    got = match(export, items)
    archive = [(i, n) for i, n in got["matched"] if i["verify"] == "none"]
    verify = [(i, n) for i, n in got["matched"] if i["verify"] == "repo"]
    return {"archive": archive, "verify": verify,
            "unmatched": got["unmatched"], "free": export["free"]}


def main(argv):
    with open(argv[1], encoding="utf-8") as handle:
        export = parse_export(handle.read())
    with open(argv[2] if len(argv) > 2 else "TODO.md", encoding="utf-8") as handle:
        items = parse(handle.read())["items"]
    result = plan(export, items)
    print(json.dumps({
        "archive": [{"n": i["n"], "title": i["title"], "note": n}
                    for i, n in result["archive"]],
        "verify": [{"n": i["n"], "title": i["title"], "note": n}
                   for i, n in result["verify"]],
        "unmatched": result["unmatched"], "free": result["free"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
