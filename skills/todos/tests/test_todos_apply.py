"""Unit tests for scripts/todos_apply.py.

Standard library only.

Run:  python3 -m unittest discover skills/todos/tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from todos_apply import parse_export, match, plan
from todos_parse import parse

TODO = """### Yours

- [ ] **1. Connect GitHub.** 401 without it.

### Build

- [ ] **2. Surface the to-do id.** Two taps.

- [ ] **3. Merge agent-run-port.** Not merged yet.
"""

# This is the shape scripts/todos_page.py's build() actually emits, confirmed
# 2026-08-06 by driving the real generated page through jsdom (tick two boxes,
# type a note, click #copy). Two things the brief guessed wrong, neither of
# which affects parsing: the header reads "TODOS — my replies", not
# "WORKING LOG — my replies"; and each item's title arrives via the
# checkbox's data-title attribute (untruncated, "N. Title", no body text
# appended) rather than scraped, clipped label text. LINE_RE/NOTE_RE/FREE_RE
# below match the real output either way, since neither regex looks at the
# header line.
EXPORT = """TODOS — my replies

OPEN ITEMS — 2 / 3 done

  Yours
    [x] 1. Connect GitHub.
          note: used /web-setup
  Build
    [ ] 2. Surface the to-do id.
    [x] 3. Merge agent-run-port.

Anything else:
deploying tonight
"""


class TestParseExport(unittest.TestCase):
    def setUp(self):
        self.got = parse_export(EXPORT)

    def test_ticked_items_are_found(self):
        self.assertEqual(len(self.got["ticked"]), 2)

    def test_unticked_items_are_found(self):
        self.assertEqual(len(self.got["unticked"]), 1)

    def test_note_attaches_to_its_own_item(self):
        first = self.got["ticked"][0]
        self.assertIn("Connect GitHub", first["title"])
        self.assertEqual(first["note"], "used /web-setup")

    def test_item_without_a_note_gets_an_empty_one(self):
        self.assertEqual(self.got["ticked"][1]["note"], "")

    def test_freeform_is_captured(self):
        self.assertEqual(self.got["free"], "deploying tonight")

    def test_an_empty_export_is_not_an_error(self):
        empty = parse_export("TODOS — my replies\n\nOPEN ITEMS — none\n")
        self.assertEqual(empty["ticked"], [])
        self.assertEqual(empty["unticked"], [])


class TestMatch(unittest.TestCase):
    def setUp(self):
        self.items = parse(TODO)["items"]
        self.got = match(parse_export(EXPORT), self.items)

    def test_ticked_lines_match_back_to_real_items(self):
        self.assertEqual([i["n"] for i, _ in self.got["matched"]], [1, 3])

    def test_a_line_naming_no_known_item_is_reported_not_guessed(self):
        stray = {"ticked": [{"title": "99. Something invented that is not here.", "note": ""}],
                 "unticked": [], "free": ""}
        got = match(stray, self.items)
        self.assertEqual(got["matched"], [])
        self.assertEqual(len(got["unmatched"]), 1)

    def test_matching_survives_renumbering(self):
        # The number changes on every apply; the title does not. Assert the
        # SHIFTED number comes back, not just a count -- that's what proves
        # the match was made by title and not by a number that happened to
        # still line up.
        shifted = [dict(i, n=i["n"] + 10, id="t%d" % (i["n"] + 10))
                   for i in self.items]
        got = match(parse_export(EXPORT), shifted)
        self.assertEqual(sorted(i["n"] for i, _ in got["matched"]), [11, 13])

    def test_a_human_hand_truncated_title_still_matches(self):
        # The page always sends the full title via data-title, but a human
        # can hand-edit the paste before sending it -- the brief calls this
        # out explicitly. A prefix long enough to be unique should resolve,
        # even though it is not the full title.
        truncated = {"ticked": [{"title": "3. Merge agent-run", "note": ""}],
                     "unticked": [], "free": ""}
        got = match(truncated, self.items)
        self.assertEqual([i["n"] for i, _ in got["matched"]], [3])

    def test_ambiguous_exact_and_prefix_is_reported_not_guessed(self):
        # Fix round 1, 2026-08-06: ticking item 2 with a hand-truncated
        # "2. Connect GitHub" used to silently match item 1 -- an exact key
        # match was returned without checking whether it was ALSO a strict
        # prefix of a different item's key. It must refuse both, and name
        # both, instead.
        todo = """### Yours

- [ ] **1. Connect GitHub.** Body one.

- [ ] **2. Connect GitHub and Slack together.** Body two.
"""
        items = parse(todo)["items"]
        export = {"ticked": [{"title": "2. Connect GitHub", "note": ""}],
                  "unticked": [], "free": ""}
        got = match(export, items)
        self.assertEqual(got["matched"], [])
        self.assertEqual(len(got["unmatched"]), 1)
        self.assertIn("Connect GitHub.", got["unmatched"][0])
        self.assertIn("Connect GitHub and Slack together.", got["unmatched"][0])

    def test_ambiguous_exact_and_prefix_fixture_full_titles_still_match(self):
        # The fix must not make ordinary, unambiguous full-title pastes of
        # the SAME fixture noisy.
        todo = """### Yours

- [ ] **1. Connect GitHub.** Body one.

- [ ] **2. Connect GitHub and Slack together.** Body two.
"""
        items = parse(todo)["items"]
        export = {"ticked": [{"title": "1. Connect GitHub.", "note": ""},
                              {"title": "2. Connect GitHub and Slack together.", "note": ""}],
                  "unticked": [], "free": ""}
        got = match(export, items)
        self.assertEqual([i["n"] for i, _ in got["matched"]], [1, 2])
        self.assertEqual(got["unmatched"], [])

    def test_ambiguous_shared_prefix_is_reported_not_guessed(self):
        # Second reproduction from fix round 1: a short, shared-stem prefix
        # ("Merge the") over the floor length matches both items.
        todo = """### Build

- [ ] **1. Merge the PR into main.** x

- [ ] **2. Merge the docs site rebuild.** y
"""
        items = parse(todo)["items"]
        export = {"ticked": [{"title": "2. Merge the", "note": ""}],
                  "unticked": [], "free": ""}
        got = match(export, items)
        self.assertEqual(got["matched"], [])
        self.assertEqual(len(got["unmatched"]), 1)
        self.assertIn("Merge the PR into main.", got["unmatched"][0])
        self.assertIn("Merge the docs site rebuild.", got["unmatched"][0])

    def test_ambiguous_shared_prefix_fixture_full_titles_still_match(self):
        todo = """### Build

- [ ] **1. Merge the PR into main.** x

- [ ] **2. Merge the docs site rebuild.** y
"""
        items = parse(todo)["items"]
        export = {"ticked": [{"title": "1. Merge the PR into main.", "note": ""},
                              {"title": "2. Merge the docs site rebuild.", "note": ""}],
                  "unticked": [], "free": ""}
        got = match(export, items)
        self.assertEqual([i["n"] for i, _ in got["matched"]], [1, 2])
        self.assertEqual(got["unmatched"], [])

    def test_terminal_question_mark_disambiguates_a_full_title_paste(self):
        # Fix round 2, 2026-08-06: round 1 kept only the sentence-ending
        # period as the completeness signal in _key(), so a title ending in
        # "?" (or "!" or ":") was still stripped bare and came back FALSELY
        # ambiguous even on an exact, correct, untruncated paste of its own
        # title. Generalized to any terminal mark from ". ? ! :".
        todo = """### Build

- [ ] **1. Deploy now?** x

- [ ] **2. Deploy now or wait?** y
"""
        items = parse(todo)["items"]
        export = {"ticked": [{"title": "1. Deploy now?", "note": ""}],
                  "unticked": [], "free": ""}
        got = match(export, items)
        self.assertEqual([i["n"] for i, _ in got["matched"]], [1])
        self.assertEqual(got["unmatched"], [])

    def test_terminal_mark_truncation_is_still_reported_ambiguous(self):
        # The generalized fix must not weaken the guard it is built on top
        # of: a genuine truncation (no terminal mark at all) of the longer
        # item, sharing the shorter item's exact opening words, is still
        # ambiguous.
        todo = """### Build

- [ ] **1. Deploy now?** x

- [ ] **2. Deploy now or wait?** y
"""
        items = parse(todo)["items"]
        export = {"ticked": [{"title": "2. Deploy now", "note": ""}],
                  "unticked": [], "free": ""}
        got = match(export, items)
        self.assertEqual(got["matched"], [])
        self.assertEqual(len(got["unmatched"]), 1)
        self.assertIn("Deploy now?", got["unmatched"][0])
        self.assertIn("Deploy now or wait?", got["unmatched"][0])

    def test_a_row_shorter_than_the_floor_does_not_guess_from_a_short_stem(self):
        # Pins PREFIX_FLOOR downward, not just up (fix round 3, 2026-08-06:
        # review found 8->6 and 8->3 left every other test in this file
        # green). "Log the event." and "Load the config." diverge inside 8
        # characters ("log " vs "load"); a 3-character paste ("Log") is
        # shorter than PREFIX_FLOOR and must not resolve to either one --
        # not matched, and (since only one of the two shares that 3-char
        # stem) not ambiguous either, just plain unmatched. At the default
        # floor of 8 this row never even reaches the prefix comparison.
        # Verified by hand against a floor of 3, where this row silently
        # matches item 1 -- see the fix-round-3 report section for the
        # before/after transcript.
        todo = """### Build

- [ ] **1. Log the event.** x

- [ ] **2. Load the config.** y
"""
        items = parse(todo)["items"]
        export = {"ticked": [{"title": "2. Log", "note": ""}],
                  "unticked": [], "free": ""}
        got = match(export, items)
        self.assertEqual(got["matched"], [])
        self.assertEqual(got["unmatched"], ["2. Log"])


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.got = plan(parse_export(EXPORT), parse(TODO)["items"])

    def test_yours_items_go_straight_to_the_archive(self):
        self.assertEqual([i["n"] for i, _ in self.got["archive"]], [1])

    def test_repo_items_go_to_verification_first(self):
        self.assertEqual([i["n"] for i, _ in self.got["verify"]], [3])

    def test_unticked_items_appear_in_neither(self):
        touched = [i["n"] for i, _ in self.got["archive"] + self.got["verify"]]
        self.assertNotIn(2, touched)

    def test_free_text_passes_through(self):
        self.assertEqual(self.got["free"], "deploying tonight")

    def test_unmatched_passes_through(self):
        stray = dict(parse_export(EXPORT))
        stray["ticked"] = stray["ticked"] + [{"title": "99. Not real.", "note": ""}]
        got = plan(stray, parse(TODO)["items"])
        self.assertEqual(got["unmatched"], ["99. Not real."])


if __name__ == "__main__":
    unittest.main(verbosity=2)
