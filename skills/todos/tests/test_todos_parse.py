"""Unit tests for scripts/todos_parse.py.

Standard library only -- these run in `Scripts tests`, which installs nothing
project-specific, and are discovered by that workflow rather than named in it.

Run:  python3 -m unittest discover skills/todos/tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from todos_parse import parse, GROUPS, VERIFY

CLEAN = """# TODO

### Yours

*Only you can clear these.*

- [ ] **1. Connect GitHub.** Cloud routines 401 without it.
  - `/web-setup`, or the GitHub App.

### Build

*I can do these.*

- [ ] **2. Surface the to-do id in the admin.** Makes the trigger two taps.
"""


class TestParse(unittest.TestCase):
    def test_finds_every_item(self):
        got = parse(CLEAN)
        self.assertEqual(len(got["items"]), 2)

    def test_item_fields(self):
        first = parse(CLEAN)["items"][0]
        self.assertEqual(first["n"], 1)
        self.assertEqual(first["group"], "Yours")
        self.assertEqual(first["title"], "Connect GitHub.")
        self.assertIn("Cloud routines 401", first["body"])

    def test_the_id_survives_a_renumber(self):
        """THE 2026-08-06 CORRUPTION, in one assertion.

        The id was `t%d % n` -- the item's POSITION. The published page stores
        each tick and note in localStorage under that id, so archiving one item
        and renumbering the rest silently handed the departed item's tick AND
        its note to whichever item slid into its slot. It happened for real:
        item 3 was archived, "Design review: where does Done live now?" moved
        from 4 to 3, and came back ticked carrying the archived item's note.

        SKILL.md already says numbers "are reassigned on every apply, so they
        are never the stable handle" -- which is why the EXPORT matches on
        title. The page just never got the same memo.
        """
        before = parse(CLEAN)["items"]
        # The same file with the first item gone and the rest renumbered -- what
        # every apply does.
        renumbered = CLEAN.replace("- [ ] **1. Connect GitHub.**", "").replace(
            "- [ ] **2. ", "- [ ] **1. ")
        after = parse(renumbered)["items"]

        moved = next(i for i in after if i["title"] == before[1]["title"])
        self.assertEqual(moved["n"], 1, "precondition: it really did renumber")
        self.assertEqual(moved["id"], before[1]["id"],
                         "the id must follow the item, not its position")

    def test_different_titles_get_different_ids(self):
        items = parse(CLEAN)["items"]
        self.assertNotEqual(items[0]["id"], items[1]["id"])

    def test_body_captures_sub_bullets(self):
        first = parse(CLEAN)["items"][0]
        self.assertIn("/web-setup", first["body"])

    def test_body_stops_at_the_next_item(self):
        first = parse(CLEAN)["items"][0]
        self.assertNotIn("Surface the to-do id", first["body"])

    def test_verify_is_derived_from_group_not_read(self):
        items = parse(CLEAN)["items"]
        self.assertEqual(items[0]["verify"], "none")   # Yours
        self.assertEqual(items[1]["verify"], "repo")   # Build
        self.assertEqual(VERIFY["Decide"], "none")
        self.assertEqual(VERIFY["Backlog"], "repo")
        self.assertEqual(VERIFY["Ongoing"], "repo")

    def test_line_numbers_are_one_based(self):
        first = parse(CLEAN)["items"][0]
        self.assertEqual(CLEAN.split("\n")[first["line"] - 1][:8], "- [ ] **")

    def test_empty_file_is_not_an_error(self):
        got = parse("")
        self.assertEqual(got["items"], [])
        self.assertEqual(got["unparsed"], [])

    def test_groups_are_a_closed_vocabulary(self):
        self.assertEqual(GROUPS, ["Yours", "Decide", "Build", "Backlog", "Ongoing"])

    def test_title_wrapping_across_lines(self):
        wrapped = """# TODO

### Yours

*Only you can clear these.*

- [ ] **1. Move the Acme gift shop content onto this
  app's own hosting.** `shop.html.erb` links out to `example.com`.
"""
        got = parse(wrapped)
        self.assertEqual(len(got["items"]), 1)
        first = got["items"][0]
        self.assertEqual(first["title"], "Move the Acme gift shop content onto this app's own hosting.")
        self.assertNotIn("\n", first["title"])
        self.assertNotIn("  ", first["title"])
        # Line number must be the first line of the item (7, after the heading and whitespace)
        self.assertEqual(first["line"], 7)

    def test_unclosed_bold_before_blank_line_produces_no_item(self):
        unclosed = """# TODO

### Yours

*Only you can clear these.*

- [ ] **1. This title is never closed

- [ ] **2. But this one is.** And it has content.
"""
        got = parse(unclosed)
        self.assertEqual(len(got["items"]), 1)
        self.assertEqual(got["items"][0]["n"], 2)

    def test_unclosed_title_does_not_corrupt_previous_item(self):
        """Unterminated title following a successful item must not corrupt it."""
        text = """# TODO

### Yours

*Only you can clear these.*

- [ ] **1. Closes fine.** Body text here.
- [ ] **2. This title never closes at all
  more continuation text
  even more
"""
        got = parse(text)
        self.assertEqual(len(got["items"]), 1)
        first = got["items"][0]
        self.assertEqual(first["n"], 1)
        self.assertEqual(first["body"], "Body text here.")
        # Critical: item 2's opening line must NOT be in item 1's body
        self.assertNotIn("- [ ] **2.", first["body"])
        self.assertNotIn("This title never closes", first["body"])
        # And continuation lines must not appear
        self.assertNotIn("more continuation text", first["body"])
        self.assertNotIn("even more", first["body"])

    def test_empty_title_does_not_corrupt_previous_item(self):
        """Malformed item with empty title (closing ** immediately) must not corrupt."""
        text = """# TODO

### Yours

*Only you can clear these.*

- [ ] **1. Fine.** Body.
- [ ] **2.**
"""
        got = parse(text)
        self.assertEqual(len(got["items"]), 1)
        first = got["items"][0]
        self.assertEqual(first["n"], 1)
        self.assertEqual(first["body"], "Body.")
        self.assertNotIn("- [ ] **2.", first["body"])

    def test_malformed_joined_title_does_not_corrupt_previous_item(self):
        """Item with odd pattern in join (asterisk then closing) must not corrupt."""
        text = """# TODO

### Yours

*Only you can clear these.*

- [ ] **1. Fine.** Body.
- [ ] **2. Title*
  *
"""
        got = parse(text)
        self.assertEqual(len(got["items"]), 1)
        first = got["items"][0]
        self.assertEqual(first["n"], 1)
        self.assertEqual(first["body"], "Body.")
        self.assertNotIn("Title", first["body"])
        self.assertNotIn("- [ ] **2.", first["body"])


MESSY = """# TODO

### Yours

- [ ] **1. Connect GitHub.** Fine, this one parses.

## Up Next

51. **Go through the reporting tool.** Raised 2026-07-21, not started.

### Build

- [x] **2. Something already done.** Should have left the file.

### Wishlist

- [ ] **3. Under a heading nobody defined.**
"""


class TestReconciliation(unittest.TestCase):
    def setUp(self):
        self.got = parse(MESSY)

    def test_only_the_valid_item_is_an_item(self):
        self.assertEqual([i["n"] for i in self.got["items"]], [1])

    def test_numbered_entry_is_reported_not_dropped(self):
        hits = [u for u in self.got["unparsed"] if "reporting tool" in u["text"]]
        self.assertEqual(len(hits), 1)
        self.assertIn("numbered", hits[0]["why"])

    def test_ticked_box_in_the_live_file_is_reported(self):
        hits = [u for u in self.got["unparsed"] if "already done" in u["text"]]
        self.assertEqual(len(hits), 1)
        self.assertIn("finished", hits[0]["why"])

    def test_item_under_an_unknown_heading_is_reported(self):
        hits = [u for u in self.got["unparsed"] if "nobody defined" in u["text"]]
        self.assertEqual(len(hits), 1)
        self.assertIn("group", hits[0]["why"])

    def test_every_unparsed_entry_carries_a_line_and_a_reason(self):
        self.assertTrue(self.got["unparsed"])
        for u in self.got["unparsed"]:
            self.assertIsInstance(u["line"], int)
            self.assertTrue(u["why"])
            self.assertTrue(u["text"])

    def test_a_clean_file_reconciles_to_nothing(self):
        self.assertEqual(parse(CLEAN)["unparsed"], [])

    def test_digit_without_dot_is_reported_and_not_glued(self):
        """Carried finding: `- [ ] **2 Title**` (no dot after the digit) matches
        neither ITEM_RE nor ITEM_START_RE, so before reconciliation it silently
        glued onto the previous item's body instead of vanishing or erroring."""
        text = """# TODO

### Yours

- [ ] **1. First item.** Body of first.
- [ ] **2 Title without a dot** Should not glue onto item one.
"""
        got = parse(text)
        self.assertEqual(len(got["items"]), 1)
        first = got["items"][0]
        self.assertEqual(first["body"], "Body of first.")
        hits = [u for u in got["unparsed"] if "Title without a dot" in u["text"]]
        self.assertEqual(len(hits), 1)
        self.assertNotIn("Title without a dot", first["body"])

    def test_unclosed_item_before_a_done_box_does_not_swallow_it(self):
        """Fix round 1, Critical 1: the join loop only stopped at a blank
        line, the next open item, or a heading. A done-box line right after
        an unclosed item got eaten into the join and vanished -- fabricating
        a garbled item ('Never closes - [x]') with unparsed left at 0."""
        text = """# TODO

### Build

- [ ] **1. Never closes
- [x] **2. Done thing.** body
"""
        got = parse(text)
        self.assertFalse(
            any("- [x]" in i["title"] for i in got["items"]),
            "no item should be fabricated out of the unclosed line and the done box",
        )
        self.assertEqual(len(got["unparsed"]), 2)
        unclosed_hits = [u for u in got["unparsed"] if "Never closes" in u["text"]]
        done_hits = [u for u in got["unparsed"] if "Done thing" in u["text"]]
        self.assertEqual(len(unclosed_hits), 1)
        self.assertEqual(len(done_hits), 1)
        self.assertIn("finished", done_hits[0]["why"])

    def test_nested_checkbox_stays_in_the_owning_items_body(self):
        """Fix round 1, Critical 2: DONE_BOX_RE/OPEN_BOX_RE matched anywhere
        on the line, so an indented sub-bullet checkbox inside a valid item
        got stolen out of its body and reported as a false top-level 'a
        finished item is still in the live file'."""
        text = """# TODO

### Build

- [ ] **1. Real item.** Body line.
  - [x] a nested sub-bullet
  - more body
"""
        got = parse(text)
        self.assertEqual(len(got["items"]), 1)
        first = got["items"][0]
        self.assertIn("a nested sub-bullet", first["body"])
        self.assertIn("more body", first["body"])
        self.assertEqual(got["unparsed"], [])

    def test_indented_box_with_no_open_item_is_reported_as_orphaned(self):
        """Fix round 1, Critical 2's stated exception: an indented box line
        with nothing open above it is not body content -- it must still be
        reported, but with a why that says orphaned, not the top-level
        open/finished wording (which would be false: it isn't a top-level
        entry)."""
        text = """# TODO

### Build

  - [ ] an indented box with nothing open above it
"""
        got = parse(text)
        self.assertEqual(got["items"], [])
        hits = [u for u in got["unparsed"] if "indented box with nothing open" in u["text"]]
        self.assertEqual(len(hits), 1)
        self.assertIn("orphaned", hits[0]["why"])
        self.assertNotIn("finished item is still in the live file", hits[0]["why"])
        self.assertNotIn("outside any known group heading", hits[0]["why"])

    def test_multiword_heading_closes_the_group(self):
        """Fix round 2: HEADING_RE required a single \\w+, so a heading like
        '## Closed in the 2026-08-06 stock-take' was not recognized as a
        heading at all -- the current group persisted across it, and
        archived work under it was reported as a live item. This is the
        coordinator's exact fixture (this repo's own TODO.md:189 has the
        same heading shape)."""
        text = """# TODO

### Ongoing

- [ ] **1. Real ongoing item.** x

## Closed in the 2026-08-06 stock-take

- [ ] **2. This is ARCHIVED work, not open.** y
"""
        got = parse(text)
        self.assertEqual(len(got["items"]), 1)
        self.assertEqual(got["items"][0]["n"], 1)
        hits = [u for u in got["unparsed"] if "ARCHIVED work" in u["text"]]
        self.assertEqual(len(hits), 1)
        self.assertIn("outside any known group", hits[0]["why"])

    def test_group_reopens_after_an_unrecognized_heading_between_sections(self):
        """A multi-word (or otherwise unrecognized) heading must still close
        the group, but the fix must not prevent re-entering a real group
        afterwards."""
        text = """# TODO

### Ongoing

- [ ] **1. Item one.** body one

## Random notes, not a group

### Build

- [ ] **2. Item two.** body two
"""
        got = parse(text)
        self.assertEqual([i["n"] for i in got["items"]], [1, 2])
        self.assertEqual(got["items"][0]["group"], "Ongoing")
        self.assertEqual(got["items"][1]["group"], "Build")
        self.assertEqual(got["unparsed"], [])

    def test_heading_with_punctuation_or_case_mismatch_closes_the_group(self):
        """A heading that merely resembles a group name (wrong case, extra
        punctuation) is not a match against the closed vocabulary and must
        still close the current group rather than being ignored."""
        text = """# TODO

### Yours

- [ ] **1. Fine.** body

## yours (lowercase, not a match)

- [ ] **2. Should not inherit Yours.** body
"""
        got = parse(text)
        self.assertEqual(len(got["items"]), 1)
        hits = [u for u in got["unparsed"] if "Should not inherit" in u["text"]]
        self.assertEqual(len(hits), 1)
        self.assertIn("outside any known group", hits[0]["why"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
