"""Unit tests for scripts/todos_adopt.py.

Run:  python3 -m unittest discover skills/todos/tests
"""
import contextlib
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from todos_adopt import split, verify_split, write_archives, check_preamble

# No leading "# TODO" title line here on purpose: content before the first
# "## " heading is its own concern (check_preamble), with its own dedicated
# fixture below (PREAMBLE_SPRAWL) -- not something verify_split checks.
# Keeping SPRAWL preamble-free keeps every test that reuses it focused on
# what it actually tests.
SPRAWL = """## Review cycle 2026-08-05 evening

- [x] Something done in August.

## Decisions — 2026-07-28

- [x] Something done in July.

## Design / Content

Undated, sits below a July section.
"""


class TestSplit(unittest.TestCase):
    def test_every_section_is_assigned_a_month(self):
        got = split(SPRAWL)
        self.assertEqual(len(got), 3)
        self.assertEqual(got[0][0], "2026-08")
        self.assertEqual(got[1][0], "2026-07")

    def test_undated_section_inherits_from_the_one_above(self):
        # The file is newest-first, so the undated tail is old.
        self.assertEqual(split(SPRAWL)[2][0], "2026-07")

    def test_section_bodies_are_kept_whole(self):
        body = split(SPRAWL)[0][2]
        self.assertIn("Something done in August", body)
        self.assertNotIn("Something done in July", body)

    def test_undated_first_section_falls_to_undated_bucket(self):
        # Nothing above the first section means nothing to inherit from.
        # This must produce a distinctly-named bucket, not silently merge
        # into whatever month happens to be checked next.
        text = ("# TODO\n\n## Design notes, no date\n\n"
                "- [ ] Some undated item.\n\n"
                "## Older decision 2026-06-01\n\n"
                "- [x] Something from June.\n")
        got = split(text)
        self.assertEqual(got[0][0], "undated")
        self.assertEqual(got[1][0], "2026-06")
        self.assertTrue(all(month != "undated" for month, _, _ in got[1:]),
                         "a dated section must never leak into the undated bucket")


class TestVerify(unittest.TestCase):
    def test_a_faithful_split_reports_nothing(self):
        # Fix round 3: each section is keyed on heading + body -- exactly
        # what write_archives emits -- not body alone, so the heading has
        # to be in the joined text too.
        joined = {"2026-08": "", "2026-07": ""}
        for month, heading, body in split(SPRAWL):
            joined[month] += heading + body + "\n"
        self.assertEqual(verify_split(SPRAWL, joined), [])

    def test_a_lossy_split_names_the_missing_section(self):
        joined = {"2026-08": "", "2026-07": ""}
        for month, heading, body in split(SPRAWL):
            if "07-28" in heading:
                continue  # drop one on purpose
            joined[month] += heading + body + "\n"
        missing = verify_split(SPRAWL, joined)
        self.assertEqual(len(missing), 1)
        self.assertIn("2026-07-28", missing[0])


# Fix round 1: verify_split gave a false all-clear when two same-month
# sections shared a body (or one body was a literal substring of another's)
# and one of them was dropped -- plain containment found a single leftover
# occurrence and called every copy present. These fixtures are built from
# BLOCK / SHORT_BODY+LONG_BODY concatenation, not free-hand prose, so the
# bodies are provably byte-identical (or provably one a literal substring of
# the other) rather than "close enough by eye".
#
# Fix round 3 keys every section on heading + body rather than body alone,
# which means two sections with the same body but *different* headings are
# just two distinct keys now -- each independently required and reported by
# its own heading, more precisely than before, not a multiplicity case at
# all. TWIN_SPRAWL is updated to what genuinely still needs multiplicity
# counting: the same heading text repeated verbatim (a literal copy-paste
# duplicate section), which is the one shape where two sections still
# collapse to the same key.
TWIN_HEADING = "## Duplicate section 2026-08-01"
TWIN_BLOCK = "\n\nDuplicate content line.\n\n"
TWIN_SPRAWL = TWIN_HEADING + TWIN_BLOCK + TWIN_HEADING + TWIN_BLOCK

# Short's *body* is still a literal substring of Long's body -- keying on
# heading + body means their full keys no longer nest (the headings differ,
# so key_short is not a substring of key_long the way it would be under
# body-only keying), which is exactly what the round 3 redesign is for:
# this shape is no longer dangerous by construction. Kept as a regression
# check that a body-substring relationship between two different sections
# still resolves correctly, now via ordinary distinct-key accounting rather
# than via the longest-key-first masking that round 1 needed.
NEARTWIN_SHORT_BODY = "\n\nShared line.\n"
NEARTWIN_LONG_BODY = NEARTWIN_SHORT_BODY + "Extra unique line only in Long.\n\n"
NEARTWIN_SPRAWL = ("## Short 2026-08-01" + NEARTWIN_SHORT_BODY
                    + "## Long 2026-08-02" + NEARTWIN_LONG_BODY)


class TestVerifyMultiplicity(unittest.TestCase):
    def test_identical_twin_sections_one_dropped_is_caught(self):
        sections = split(TWIN_SPRAWL)
        self.assertEqual(sections[0][1] + sections[0][2],
                          sections[1][1] + sections[1][2],
                          "fixture must give both copies a byte-identical "
                          "heading and body")
        # Only the first copy made it into the archive; the second was
        # dropped.
        lossy = {sections[0][0]: sections[0][1] + sections[0][2]}
        verdict = verify_split(TWIN_SPRAWL, lossy)
        self.assertEqual(len(verdict), 1)
        self.assertIn("2 time", verdict[0])
        self.assertIn("1 time", verdict[0])

        # The same real (unmocked) verdict must stop write_archives cold.
        import unittest.mock
        import todos_adopt
        with tempfile.TemporaryDirectory() as tmp:
            with unittest.mock.patch.object(
                    todos_adopt, "verify_split", return_value=verdict):
                with self.assertRaises(AssertionError):
                    write_archives(TWIN_SPRAWL, tmp)
            self.assertEqual(os.listdir(tmp), [],
                             "nothing may be written when verification fails")

    def test_identical_twin_sections_both_present_is_fine(self):
        sections = split(TWIN_SPRAWL)
        honest = {}
        for month, heading, body in sections:
            honest[month] = honest.get(month, "") + heading + body
        self.assertEqual(verify_split(TWIN_SPRAWL, honest), [])

        with tempfile.TemporaryDirectory() as tmp:
            counts = write_archives(TWIN_SPRAWL, tmp)
            self.assertEqual(counts, {"2026-08": 2})
            self.assertTrue(os.path.exists(os.path.join(tmp, "2026-08.md")))

    def test_near_twin_substring_body_dropped_is_caught(self):
        sections = split(NEARTWIN_SPRAWL)
        short_body, long_body = sections[0][2], sections[1][2]
        self.assertIn(short_body, long_body,
                       "fixture must give Short a body that is a literal "
                       "substring of Long's body")
        self.assertNotEqual(short_body, long_body)

        # Keep only Long; Short's section never made it into the archive --
        # even though Short's body text is still technically "present",
        # embedded inside Long's.
        lossy = {sections[1][0]: sections[1][1] + sections[1][2]}
        verdict = verify_split(NEARTWIN_SPRAWL, lossy)
        self.assertEqual(len(verdict), 1)
        self.assertIn("Short", verdict[0])

    def test_near_twin_substring_both_present_is_fine(self):
        sections = split(NEARTWIN_SPRAWL)
        honest = {}
        for month, heading, body in sections:
            honest[month] = honest.get(month, "") + heading + body
        self.assertEqual(verify_split(NEARTWIN_SPRAWL, honest), [])


# Fix round 2: verify_split used to skip empty-body sections entirely
# (`if not body: continue`), so a dropped empty-body section was invisible
# to the check -- "" is a substring of everything, so checking presence by
# body text alone can never fail for it. B here is the last section in the
# file with nothing after its heading, so its body is genuinely "" (not
# just whitespace) -- the real shape that trips this.
EMPTY_BODY_SPRAWL = ("## A 2026-08-01\n\nSome content for A.\n\n"
                     + "## B 2026-08-02")


class TestVerifyEmptyBody(unittest.TestCase):
    def test_dropped_empty_body_section_is_caught(self):
        sections = split(EMPTY_BODY_SPRAWL)
        self.assertEqual(sections[1][2], "", "fixture must give B an empty body")
        # Only A's heading+body made it into the archive; B was dropped
        # entirely -- not even its heading.
        lossy = {sections[0][0]: sections[0][1] + sections[0][2]}
        verdict = verify_split(EMPTY_BODY_SPRAWL, lossy)
        self.assertEqual(len(verdict), 1)
        self.assertIn("## B 2026-08-02", verdict[0])

        import unittest.mock
        import todos_adopt
        with tempfile.TemporaryDirectory() as tmp:
            with unittest.mock.patch.object(
                    todos_adopt, "verify_split", return_value=verdict):
                with self.assertRaises(AssertionError):
                    write_archives(EMPTY_BODY_SPRAWL, tmp)
            self.assertEqual(os.listdir(tmp), [],
                             "nothing may be written when verification fails")

    def test_empty_body_section_correctly_written_is_fine(self):
        sections = split(EMPTY_BODY_SPRAWL)
        honest = {}
        for month, heading, body in sections:
            honest[month] = honest.get(month, "") + heading + body
        self.assertEqual(verify_split(EMPTY_BODY_SPRAWL, honest), [])

        with tempfile.TemporaryDirectory() as tmp:
            counts = write_archives(EMPTY_BODY_SPRAWL, tmp)
            self.assertEqual(counts, {"2026-08": 2})
            self.assertTrue(os.path.exists(os.path.join(tmp, "2026-08.md")))


# Fix round 3, part 1: the empty-body fallback in fix round 2 (`key = body
# if body else heading`) only fired when body == "" exactly. Two adjacent
# "## " headings -- the ordinary shape of an empty section -- give
# body == "\n" (whitespace, not ""), which is truthy, so the fallback never
# fires and the key becomes "\n" itself: a string present all over any
# multi-line archive. A here is that shape: immediately followed by another
# heading, nothing but a newline between them.
WS_BODY_SPRAWL = "## A 2026-08-01\n## B 2026-08-02\n\nSome content for B.\n"


class TestVerifyWhitespaceBody(unittest.TestCase):
    def test_dropped_whitespace_only_body_section_is_caught(self):
        sections = split(WS_BODY_SPRAWL)
        self.assertEqual(sections[0][2], "\n",
                          "fixture must give A a whitespace-only (not empty) body")
        # A dropped entirely; only B's heading+body written.
        lossy = {sections[0][0]: sections[1][1] + sections[1][2]}
        verdict = verify_split(WS_BODY_SPRAWL, lossy)
        self.assertEqual(len(verdict), 1)
        self.assertIn("## A 2026-08-01", verdict[0])

    def test_whitespace_only_body_section_correctly_written_is_fine(self):
        sections = split(WS_BODY_SPRAWL)
        honest = {}
        for month, heading, body in sections:
            honest[month] = honest.get(month, "") + heading + body
        self.assertEqual(verify_split(WS_BODY_SPRAWL, honest), [])


# Fix round 3, part 2 -- corrected in round 4: content before the first
# "## " heading (a title, an open list, standing rules -- whatever a
# file's owner put there) is invisible to split()'s per-section accounting
# entirely. On this repo's own TODO.md that is 188 lines.
#
# Round 3 made verify_split report this and refuse to write on it, which
# was wrong: unlike a dropped section, a preamble is not lost -- it is
# still sitting in the source file TODO.md, which the operator overwrites
# by hand afterward. Refusing meant write_archives could no longer write
# *any* realistic file, since nearly every markdown file opens with a
# title line. Round 4 splits it into its own function, check_preamble,
# which write_archives calls and warns loudly about (stderr) without
# blocking the write -- a "don't forget" problem, not an "already gone"
# problem, so it gets a different response, not the same one.
PREAMBLE_SPRAWL = ("# TODO\n\nOpen items:\n- [ ] Something urgent.\n\n"
                    "## Only section 2026-08-01\n\nSection body.\n")

NO_PREAMBLE_SPRAWL = "## Only section 2026-08-01\n\nSection body.\n"


class TestCheckPreamble(unittest.TestCase):
    def test_non_blank_preamble_produces_a_message(self):
        msg = check_preamble(PREAMBLE_SPRAWL)
        self.assertIsNotNone(msg)
        self.assertIn("will NOT be carried into any archive", msg)
        self.assertIn("by hand", msg)

    def test_no_preamble_produces_no_message(self):
        self.assertIsNone(check_preamble(NO_PREAMBLE_SPRAWL))


class TestWriteArchivesPreambleWarning(unittest.TestCase):
    def test_preamble_bearing_file_writes_successfully_and_warns(self):
        # This is round 4's actual regression: round 3 made verify_split
        # treat the preamble as section loss, so write_archives refused
        # here. It must write cleanly again, and still surface the warning.
        with tempfile.TemporaryDirectory() as tmp:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                counts = write_archives(PREAMBLE_SPRAWL, tmp)
            self.assertEqual(counts, {"2026-08": 1})
            self.assertTrue(os.path.exists(os.path.join(tmp, "2026-08.md")))
        self.assertIn("WARNING", stderr.getvalue())
        self.assertIn("will NOT be carried into any archive", stderr.getvalue())

    def test_file_with_no_preamble_writes_with_no_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                counts = write_archives(NO_PREAMBLE_SPRAWL, tmp)
            self.assertEqual(counts, {"2026-08": 1})
        self.assertEqual(stderr.getvalue(), "")


# Fix round 3, part 3: nothing in the suite pinned that verify_split checks
# archives[month] specifically rather than, say, every archive concatenated
# -- the docstring's headline claim, and the one thing split()'s date rule
# could plausibly get wrong. A section that is textually present but only
# under the WRONG month's key must still be reported missing.
class TestVerifyMonthScoping(unittest.TestCase):
    def test_section_misfiled_into_the_wrong_month_is_reported(self):
        sections = split(SPRAWL)
        months = {m for m, _, _ in sections}
        self.assertEqual(months, {"2026-08", "2026-07"},
                          "fixture must span two months for this to test anything")

        # Every section's heading+body dumped under "2026-07", including
        # the one that actually belongs to "2026-08" -- and no "2026-08"
        # key at all. A checker that searched the concatenation of every
        # archive (instead of scoping to archives[month]) would find the
        # 2026-08 section's text sitting right there in "2026-07" and call
        # it present.
        misfiled = {"2026-07": ""}
        for month, heading, body in sections:
            misfiled["2026-07"] += heading + body

        verdict = verify_split(SPRAWL, misfiled)
        self.assertEqual(len(verdict), 1)
        self.assertIn("2026-08", verdict[0])
        self.assertIn("Review cycle", verdict[0])


class TestWriteArchives(unittest.TestCase):
    def test_writes_one_file_per_month_and_counts_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            counts = write_archives(SPRAWL, tmp)
            self.assertEqual(counts, {"2026-08": 1, "2026-07": 2})
            self.assertTrue(os.path.exists(os.path.join(tmp, "2026-08.md")))
            self.assertTrue(os.path.exists(os.path.join(tmp, "2026-07.md")))

    def test_refuses_to_write_when_verification_fails(self):
        # Patch the verifier rather than adding a test-only argument to
        # production code: what is under test is that write_archives REFUSES
        # on a bad verdict, not how the verdict was reached.
        import unittest.mock
        import todos_adopt
        with tempfile.TemporaryDirectory() as tmp:
            with unittest.mock.patch.object(
                    todos_adopt, "verify_split", return_value=["## A section"]):
                with self.assertRaises(AssertionError):
                    write_archives(SPRAWL, tmp)
            self.assertEqual(os.listdir(tmp), [],
                             "nothing may be written when verification fails")


if __name__ == "__main__":
    unittest.main(verbosity=2)
