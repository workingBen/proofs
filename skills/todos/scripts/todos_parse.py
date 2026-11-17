"""Read TODO.md's open items, and everything in it that looks like work but is not.

The second half is the point. A parser that reports a confident count while
silently dropping what it cannot read reproduces the bug this skill exists to
fix: on 2026-08-06 eight live items were invisible to every count because they
were numbered list entries rather than checkboxes.

Run:  python3 scripts/todos_parse.py [TODO.md]     # prints JSON
"""
import hashlib
import json
import re
import sys

# Closed vocabulary, matched literally. A heading that is not one of these is
# not a group -- it is unparsed, and says so, rather than being guessed at.
GROUPS = ["Yours", "Decide", "Build", "Backlog", "Ongoing"]

# Derived from the group, never read from the file. A per-item flag would drift
# out of sync with the prose around it; a group heading cannot, because it is
# the thing a human reads to decide where to put the item.
VERIFY = {
    "Yours": "none",     # only the user can close it -- unverifiable from here
    "Decide": "none",    # his answer IS the deliverable
    "Build": "repo",     # check against code and git before archiving
    "Backlog": "repo",
    "Ongoing": "repo",
}

def stable_id(title):
    """A handle for one item that does NOT move when the list is renumbered.

    THIS WAS `"t%d" % n` -- the item's POSITION -- AND IT CORRUPTED REAL
    REPLIES. The published page keeps every tick and note in localStorage under
    this id, so archiving one item and renumbering the rest handed the departed
    item's tick and note to whatever slid into its slot. Observed 2026-08-06:
    item 3 was archived, "Design review: where does Done live now?" moved from 4
    to 3, and came back ticked, carrying the archived item's note. Silent, and
    indistinguishable from a real answer -- which is what made it dangerous.

    SKILL.md had already written the rule down for the export side: numbers "are
    reassigned on every apply, so they are never the stable handle". The page
    was simply never held to it.

    Keyed on the title, lowercased and stripped of everything but letters,
    digits and single spaces, so trivial re-punctuation does not reset an item's
    state. Two consequences worth stating plainly:

      - EDITING A TITLE RESETS THAT ITEM'S TICK AND NOTE. Correct: a rewritten
        title is usually a rewritten item, and a stale tick on it is exactly the
        false "done" this whole skill exists to stop.
      - The first page built after this change starts blank, because every id
        changed. That is the corrupted state clearing itself out, not a loss.

    A hash rather than the normalized title itself only to keep the attribute
    short; `todos_apply.match()` still does the real title matching, with its
    own ambiguity check, so a collision here costs shared tick state on the
    page and can never archive the wrong item.
    """
    normalized = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    return "t" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]


HEADING_RE = re.compile(r"^#{1,6}\s+(.*?)\s*$")
ITEM_START_RE = re.compile(r"^- \[ \] \*\*(\d+)\.\s*(.*)$")
ITEM_RE = re.compile(r"^- \[ \] \*\*(\d+)\.\s*(.+?)\*\*(.*)$")

# Anything that looks like work and did not become an item. Each rule names
# what it caught, because "8 unparsed" with no reason is just a worse silence.
# Anchored at column 0: a box or number indented under an open item is a
# sub-bullet -- ordinary body content, not a structural element of its own.
NUMBERED_RE = re.compile(r"^\d+\.\s+\*\*")
OPEN_BOX_RE = re.compile(r"^- \[ \]")
DONE_BOX_RE = re.compile(r"^- \[x\]", re.IGNORECASE)
# An indented box with no open item to own it is genuinely orphaned, not body.
INDENTED_BOX_RE = re.compile(r"^\s+- \[[ xX]\]")


def parse(text):
    """TODO.md text -> {"items": [...], "unparsed": [...], "groups": [...]}."""
    lines = text.split("\n")
    items, unparsed = [], []
    group = None
    current = None
    i = 0

    while i < len(lines):
        line = lines[i]
        i += 1
        line_num = i

        # Any heading closes the current group -- multi-word headings ("##
        # Closed in the 2026-08-06 stock-take") included. Only one of the
        # five group names reopens it; everything else (including no text
        # at all) leaves items below it outside any known group, same as an
        # unrecognized single-word heading always did.
        heading = HEADING_RE.match(line)
        if heading:
            text = heading.group(1)
            group = text if text in GROUPS else None
            current = None
            continue

        # Reconciliation: patterns that never match ITEM_RE/ITEM_START_RE at
        # all (wrong box, or a number where a checkbox belongs), so they can
        # be caught before those checks run.
        if DONE_BOX_RE.match(line):
            unparsed.append({
                "line": line_num, "text": line.strip(),
                "why": "a finished item is still in the live file -- it should "
                       "have moved to docs/todo-archive/",
            })
            continue

        if NUMBERED_RE.match(line):
            unparsed.append({
                "line": line_num, "text": line.strip(),
                "why": "numbered list entry, not a checkbox -- invisible to "
                       "every count of open items",
            })
            continue

        # Try simple single-line match first
        item = ITEM_RE.match(line)
        if item and group:
            n = int(item.group(1))
            current = {
                "n": n,
                "id": stable_id(item.group(2).strip()),
                "group": group,
                "verify": VERIFY[group],
                "title": item.group(2).strip(),
                "body": item.group(3).strip(),
                "line": line_num,
            }
            items.append(current)
            continue

        # Try multi-line match: start without closing **
        item_start = ITEM_START_RE.match(line)
        if item_start and group and not item:
            n = int(item_start.group(1))
            title_part = item_start.group(2)
            joined_lines = [title_part]
            start_line = line_num

            # Join lines until we find closing **, a blank line, next item, or
            # heading -- or any other line that starts a new structural
            # element (a finished item, a numbered entry). Without those last
            # two, an unclosed item swallows the next line whatever it is and
            # fabricates a garbled item out of two unrelated lines, silently
            # dropping the one it ate.
            joined_found_close = False
            while i < len(lines):
                next_line = lines[i]

                # Stop at blank line
                if next_line.strip() == "":
                    break
                # Stop at next item
                if next_line.startswith("- [ ] "):
                    break
                # Stop at heading
                if HEADING_RE.match(next_line):
                    break
                # Stop at a finished item
                if DONE_BOX_RE.match(next_line):
                    break
                # Stop at a numbered entry
                if NUMBERED_RE.match(next_line):
                    break

                joined_lines.append(next_line)
                i += 1

                # Check if we found the closing **
                if "**" in next_line:
                    joined_found_close = True
                    break

            # Single exit point: parse if possible, otherwise clear current.
            # This prevents any path from falling through with stale current.
            parsed_item = None
            if joined_found_close:
                # Parse the joined text (title_part already has number removed)
                joined_text = " ".join(line.strip() for line in joined_lines)
                # Pattern: title content ** body content (no number prefix needed)
                match = re.match(r"(.+?)\*\*(.*)$", joined_text)
                if match:
                    parsed_item = {
                        "n": n,
                        "id": stable_id(match.group(1).strip()),
                        "group": group,
                        "verify": VERIFY[group],
                        "title": match.group(1).strip(),
                        "body": match.group(2).strip(),
                        "line": start_line,
                    }

            # Ensure every path through item-start sets current appropriately.
            # A failure here is still reported -- it is the one place a
            # `- [ ] **N.` line that never closes would otherwise vanish with
            # no item and no unparsed entry, instead of just gluing onto the
            # previous item's body (the other paths this gate already blocks).
            if parsed_item:
                current = parsed_item
                items.append(current)
            else:
                current = None
                unparsed.append({
                    "line": start_line, "text": line.strip(),
                    "why": "open item that did not match the "
                           "`- [ ] **N. Title.**` shape",
                })
            continue

        # Reconciliation: an open box that reached here matched neither
        # ITEM_RE nor ITEM_START_RE above -- no group heading, or a shape
        # (like a missing dot after the number) neither regex accepts.
        if OPEN_BOX_RE.match(line) and not (item and group):
            unparsed.append({
                "line": line_num, "text": line.strip(),
                "why": "open item outside any known group heading"
                       if group is None else "open item that did not match the "
                       "`- [ ] **N. Title.**` shape",
            })
            continue

        # Reconciliation: an indented box with no open item to attach to is
        # orphaned rather than body content -- worth a distinct reason, since
        # calling it a top-level open/finished item would be false too.
        if current is None and INDENTED_BOX_RE.match(line):
            unparsed.append({
                "line": line_num, "text": line.strip(),
                "why": "an indented checkbox with no open item above it to "
                       "attach to -- orphaned, not a top-level entry",
            })
            continue

        if current is not None:
            if line.strip() == "" and not line.startswith(" "):
                current = None
            else:
                current["body"] = (current["body"] + "\n" + line).strip()

    return {"items": items, "unparsed": unparsed, "groups": list(GROUPS)}


def main(argv):
    path = argv[1] if len(argv) > 1 else "TODO.md"
    with open(path, encoding="utf-8") as handle:
        print(json.dumps(parse(handle.read()), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
