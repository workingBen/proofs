#!/usr/bin/env python3
"""The mechanical findings, including the one a regression check catches."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import json
import tempfile
from io import StringIO
from contextlib import redirect_stdout

from pr_qa_findings import compare, summarize, measured, unmeasured_routes, main, already_on_main


def shot(label="after", slug="admin-contacts-14", size="phone", overflow=0,
         client=390, small=None, errors=None, redirected=False, overflowing=None):
    return {
        "label": label, "slug": slug, "size": size, "pageLabel": "Contact page",
        "path": "/admin/contacts/14", "landedOn": "http://x/admin/contacts/14",
        "redirected": redirected, "overflow": overflow, "clientWidth": client,
        "scrollWidth": client + overflow, "smallTargets": small or [],
        "errors": errors or [], "overflowing": overflowing or [],
    }


class OverflowTest(unittest.TestCase):
    def test_pr_2s_actual_numbers_are_a_blocker(self):
        # 390px viewport, 413px of content, against a clean before.
        before = [shot("before", overflow=0)]
        after = [shot(overflow=23, overflowing=[
            {"tag": "button", "text": "Clear", "right": 413, "past": 23}])]
        found = compare(before, after)
        self.assertEqual(found[0]["severity"], "blocker")
        self.assertIn("scrolls sideways", found[0]["title"])
        self.assertIn("23px over", found[0]["detail"])
        self.assertIn("Clear", found[0]["detail"])

    def test_pre_existing_overflow_is_not_the_prs_fault(self):
        # The rule that keeps the real finding from being buried.
        before = [shot("before", overflow=20)]
        after = [shot(overflow=20)]
        self.assertEqual(compare(before, after), [])

    def test_making_it_worse_is_reported_even_when_it_was_already_bad(self):
        found = compare([shot("before", overflow=20)], [shot(overflow=43)])
        self.assertEqual(found[0]["severity"], "blocker")
        self.assertIn("against 20px before", found[0]["detail"])

    def test_sub_pixel_noise_is_not_a_finding(self):
        self.assertEqual(compare([shot("before", overflow=0)], [shot(overflow=1)]), [])

    def test_a_fix_is_reported_as_good_news(self):
        found = compare([shot("before", overflow=23)], [shot(overflow=0)])
        self.assertEqual(found[0]["severity"], "good")
        self.assertIn("fixed", found[0]["title"])

    def test_desktop_overflow_is_only_a_warning(self):
        found = compare([shot("before", size="desktop", client=1440)],
                        [shot(size="desktop", client=1440, overflow=23)])
        self.assertEqual(found[0]["severity"], "warning")


class TapTargetTest(unittest.TestCase):
    def test_a_new_small_control_on_a_phone_is_a_warning(self):
        after = [shot(small=[{"tag": "button", "text": "Clear", "width": 31, "height": 20}])]
        found = compare([shot("before")], after)
        self.assertEqual(found[0]["severity"], "warning")
        self.assertIn("31x20px", found[0]["detail"])

    def test_a_control_that_was_already_small_is_not_news(self):
        small = [{"tag": "button", "text": "Clear", "width": 31, "height": 20}]
        self.assertEqual(compare([shot("before", small=small)], [shot(small=small)]), [])

    def test_small_targets_named_at_desktop(self):
        def t(n):
            return {"tag": "a", "text": f"Link {n}", "width": 20, "height": 18}
        before = [shot("before", size="desktop", client=1440, small=[t(0)])]
        after = [shot(size="desktop", client=1440, small=[t(0), t(1), t(2), t(3)])]
        found = [f for f in compare(before, after) if f["title"].endswith("new small tap targets")]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "warning")
        self.assertTrue(found[0]["evidence"]["rise"])
        for n in (1, 2, 3):
            self.assertIn(f'"Link {n}" 20x18px', found[0]["detail"])
        self.assertNotIn("Link 0", found[0]["detail"])

    def test_small_target_detail_caps_at_four_and_counts_the_rest(self):
        small = [{"tag": "a", "text": f"L{n}", "width": 10, "height": 10} for n in range(6)]
        found = compare([shot("before")], [shot(small=small)])
        self.assertIn("and 2 more", found[0]["detail"])

    def test_a_new_off_center_row_is_a_warning(self):
        # Angular run 1: a flex row inside a text-align:center column sat at the left at 390.
        events = {"tag": "a", "text": "Events", "left": 0, "right": 164}
        before = [dict(shot("before"), offCenter=[], offCenterCount=0)]
        after = [dict(shot(), offCenter=[events], offCenterCount=1)]
        found = [f for f in compare(before, after) if "off-center" in f["title"]]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "warning")
        self.assertIn('"Events" (0px left, 164px right)', found[0]["detail"])

    def test_an_off_center_row_that_was_already_there_is_not_news(self):
        events = {"tag": "a", "text": "Events", "left": 0, "right": 164}
        before = [dict(shot("before"), offCenter=[events], offCenterCount=1)]
        after = [dict(shot(), offCenter=[events], offCenterCount=1)]
        self.assertEqual(compare(before, after), [])

    def test_an_older_before_without_off_center_is_not_a_zero_baseline(self):
        events = {"tag": "a", "text": "Events", "left": 0, "right": 164}
        after = [dict(shot(), offCenter=[events], offCenterCount=1)]
        self.assertEqual(compare([shot("before")], after), [])

    def test_a_new_off_center_column_is_a_warning(self):
        # Astro run 1: a section's max-width column began 128 px right of the ones around it.
        steps = {"kind": "edge", "tag": "div", "text": "Steps", "edge": 232, "neighbors": 104}
        before = [dict(shot("before"), offColumns=[], offColumnCount=0)]
        after = [dict(shot(), offColumns=[steps], offColumnCount=1)]
        found = [f for f in compare(before, after) if "column" in f["title"]]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "warning")
        self.assertIn('"Steps" (edge at 232px, the columns around it at 104px)', found[0]["detail"])
        self.assertEqual(compare([dict(shot("before"), offColumns=[steps], offColumnCount=1)], after), [])
        self.assertEqual(compare([shot("before")], after), [])

    def test_a_blank_shot_is_never_clean(self):
        # Astro run 1: shots blank below the hero (sections that fade in on scroll) scored "clean".
        blank = {"flagged": True, "image": True, "hidden": True, "colorShare": 0.97, "hiddenBlocks": 9}
        for side in ("before", "after"):
            with self.subTest(side=side):
                before = [dict(shot("before"), blank=blank if side == "before" else {"flagged": False})]
                after = [dict(shot(), blank=blank if side == "after" else {"flagged": False})]
                found = compare(before, after)
                self.assertEqual(len(found), 1, found)
                self.assertIn("blank", found[0]["title"])
                self.assertIn(side, found[0]["title"])
                self.assertEqual(found[0]["severity"], "warning")
                self.assertIn("nothing there was checked", found[0]["detail"])
                self.assertNotEqual(summarize(found)["verdict"], "clean")

    def test_small_text_rise_named(self):
        old = [{"text": "Old a", "px": 11}, {"text": "Old b", "px": 11}]
        new = [{"text": "New c", "px": 11.5}, {"text": "New d", "px": 10}]
        before = [dict(shot("before"), smallText=old, smallTextCount=2)]
        after = [dict(shot(), smallText=old + new, smallTextCount=4)]
        found = [f for f in compare(before, after) if f["title"].endswith("new text below the size floor")]
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["evidence"]["rise"])
        self.assertIn('"New c" 11.5px', found[0]["detail"])
        self.assertIn('"New d" 10px', found[0]["detail"])
        self.assertNotIn("Old a", found[0]["detail"])

    def test_repeated_label_rise_detected(self):
        edit = {"tag": "a", "text": "Edit", "width": 20, "height": 18}
        before = [shot("before", size="desktop", client=1440, small=[edit])]
        after = [shot(size="desktop", client=1440, small=[edit] * 4)]
        found = [f for f in compare(before, after) if f["title"].endswith("new small tap targets")]
        self.assertEqual(len(found), 1)
        self.assertIn("Edit", found[0]["detail"])
        self.assertTrue(found[0]["evidence"]["rise"])
        self.assertEqual(found[0]["detail"].count('"Edit"'), 3)

    def test_relabel_same_count_is_not_a_rise(self):
        def link(text):
            return {"tag": "a", "text": text, "width": 20, "height": 18}
        before = [shot("before", size="desktop", client=1440, small=[link("Updated 3 min ago")])]
        after = [shot(size="desktop", client=1440, small=[link("Updated 4 min ago")])]
        found = [f for f in compare(before, after) if f["title"].endswith("new small tap targets")]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["severity"], "warning")
        self.assertIn("Updated 4 min ago", found[0]["detail"])
        self.assertFalse(found[0]["evidence"].get("rise"))

    def test_count_rise_sets_rise(self):
        def link(text):
            return {"tag": "a", "text": text, "width": 20, "height": 18}
        before = [shot("before", size="desktop", client=1440, small=[link("Updated 3 min ago")])]
        after = [shot(size="desktop", client=1440,
                      small=[link("Updated 4 min ago"), link("Edit")])]
        found = [f for f in compare(before, after) if f["title"].endswith("new small tap targets")]
        self.assertTrue(found[0]["evidence"]["rise"])

    def test_no_finding_when_counts_flat(self):
        small = [{"tag": "a", "text": "x", "width": 10, "height": 10}]
        text = [{"text": "tiny", "px": 11}]
        before = [dict(shot("before", size="desktop", client=1440, small=small),
                       smallText=text, smallTextCount=1)]
        after = [dict(shot(size="desktop", client=1440, small=small),
                      smallText=text, smallTextCount=1)]
        self.assertEqual(compare(before, after), [])


class EvidenceIntegrityTest(unittest.TestCase):
    def test_a_redirect_means_the_pair_is_worthless_and_says_so(self):
        found = compare([shot("before")], [shot(redirected=True)])
        self.assertEqual(found[0]["severity"], "blocker")
        self.assertIn("not of that page", found[0]["title"])

    def test_a_redirect_suppresses_its_own_overflow_finding(self):
        # Otherwise a login page's layout gets reported as the PR's regression.
        found = compare([shot("before")], [shot(redirected=True, overflow=99)])
        self.assertEqual(len(found), 1)

    def test_a_missing_after_shot_is_reported(self):
        found = compare([shot("before")], [])
        self.assertEqual(found[0]["severity"], "warning")
        self.assertIn("no after shot", found[0]["title"])

    def test_a_new_js_error_is_a_blocker(self):
        found = compare([shot("before")], [shot(errors=["TypeError: x is not a function"])])
        self.assertEqual(found[0]["severity"], "blocker")
        self.assertIn("TypeError", found[0]["detail"])

    def test_a_pre_existing_js_error_is_not(self):
        err = ["TypeError: old"]
        self.assertEqual(compare([shot("before", errors=err)], [shot(errors=err)]), [])


class SummaryTest(unittest.TestCase):
    def test_blockers_sort_above_warnings(self):
        after = [shot(overflow=23), shot(slug="other", small=[
            {"tag": "a", "text": "y", "width": 10, "height": 10}])]
        before = [shot("before"), shot("before", slug="other")]
        sev = [f["severity"] for f in compare(before, after)]
        self.assertEqual(sev, sorted(sev, key=lambda s: {"blocker": 0, "warning": 1}[s]))

    def test_verdicts(self):
        self.assertEqual(summarize(compare([shot("before")], [shot(overflow=23)]))["verdict"], "hold")
        self.assertEqual(summarize(compare([shot("before")], [shot()]))["verdict"], "clean")

    def test_unmapped_changes_are_carried_into_the_summary(self):
        # A QA that covered less than it looks like must say so.
        out = summarize([], {"unmatched_changes": ["app/views/new.html.erb"], "pages": []})
        self.assertEqual(out["unmapped_changes"], ["app/views/new.html.erb"])


def bare(label="after", redirected=False, slug="x"):
    return {"label": label, "slug": slug, "size": "phone", "path": "/x",
            "file": f"{label}-x-phone.png", "redirected": redirected}


class NotMeasuredTest(unittest.TestCase):
    def test_no_shots_is_not_measured(self):
        out = summarize(compare([], []), measured=measured([], []))
        self.assertEqual(out["verdict"], "unknown")
        self.assertFalse(out["measured"])

    def test_shots_without_measurements_are_not_measured(self):
        before, after = [bare("before")], [bare("after")]
        out = summarize(compare(before, after), measured=measured(before, after))
        self.assertEqual(out["verdict"], "unknown")
        self.assertIn("not measured", out["note"])

    def test_only_after_measured_is_not_measured(self):
        self.assertFalse(measured([bare("before", slug="s")], [shot(slug="s", overflow=0)]))

    def test_a_redirect_blocker_still_holds_when_unmeasured(self):
        before, after = [bare("before")], [bare("after", redirected=True)]
        out = summarize(compare(before, after), measured=measured(before, after))
        self.assertEqual(out["verdict"], "hold")

    def test_measured_clean_is_still_clean(self):
        before, after = [shot("before")], [shot("after")]
        out = summarize(compare(before, after), measured=measured(before, after))
        self.assertEqual(out["verdict"], "clean")
        self.assertTrue(out["measured"])

    def test_cli_writes_not_measured_for_an_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(StringIO()) as buf:
            main(["--dir", tmp])
        self.assertEqual(json.loads(buf.getvalue())["verdict"], "unknown")


    def test_out_flag_writes_file_and_prints_summary_only(self):
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(StringIO()) as buf:
            dest = os.path.join(tmp, "findings.json")
            main(["--dir", tmp, "--out", dest])
            with open(dest, encoding="utf-8") as handle:
                written = json.load(handle)
        self.assertEqual(written["verdict"], "unknown")
        printed = buf.getvalue()
        self.assertLess(len(printed.splitlines()), 4)
        self.assertIn("unknown", printed)
        self.assertIn(dest, printed)
        self.assertNotIn('"findings"', printed)


def run(before, after):
    return summarize(compare(before, after), measured=measured(before, after),
                     unmeasured=unmeasured_routes(before, after))


class PartialMeasurementTest(unittest.TestCase):
    def test_mixed_routes_are_unknown_and_name_the_unmeasured_one(self):
        before = [shot("before", slug="a"), dict(bare("before"), slug="b", pageLabel="Bare page")]
        after = [shot("after", slug="a"), dict(bare("after"), slug="b", pageLabel="Bare page")]
        out = run(before, after)
        self.assertEqual(out["verdict"], "unknown")
        self.assertIn("Bare page at phone", out["note"])

    def test_a_bare_before_is_not_a_zero_baseline(self):
        out = run([bare("before", slug="s")], [shot("after", slug="s", overflow=30)])
        self.assertEqual(out["counts"]["blocker"], 0)
        self.assertEqual(out["verdict"], "unknown")

    def test_a_bare_after_does_not_hide_behind_a_measured_before(self):
        out = run([shot("before", slug="s", overflow=30)], [bare("after", slug="s")])
        self.assertEqual(out["verdict"], "unknown")

    def test_unmeasured_plus_a_machine_warning_is_look(self):
        # "gone" was measured before but has no after shot (a warning); the
        # other route is bare on both sides (unmeasured).
        out = run([shot("before", slug="gone"), bare("before")], [bare("after")])
        self.assertEqual(out["verdict"], "look")



class CaptureFailureTest(unittest.TestCase):
    """SvelteKit run 1: both sides were SvelteKit's 404 page (base + path made "//"),
    and the findings called them "verdict: clean; 0 finding(s)"."""

    def run_dir(self, before, after):
        with tempfile.TemporaryDirectory() as tmp:
            for label, body in (("before", before), ("after", after)):
                with open(os.path.join(tmp, f"{label}.json"), "w") as fh:
                    json.dump(body, fh)
            out = os.path.join(tmp, "findings.json")
            buf = StringIO()
            with redirect_stdout(buf):
                main(["--dir", tmp, "--out", out])
            with open(out) as fh:
                return json.load(fh), buf.getvalue()

    def test_listed_capture_failures_are_never_clean(self):
        fail = {"page": "home", "viewport": "1440", "path": "/", "url": "http://x//", "status": 404,
                "error": "http://x// answered HTTP 404; this is not the page"}
        result, line = self.run_dir({"shots": [], "failures": [fail]}, {"shots": [], "failures": [fail]})
        self.assertEqual(result["verdict"], "unknown")
        self.assertFalse(result["measured"])
        self.assertIn("capture failed", result["note"])
        self.assertIn("HTTP 404", result["note"])
        self.assertIn("capture failed", line)

    def test_a_failure_on_one_side_spoils_a_clean_pair(self):
        fail = {"page": "home", "viewport": "390", "path": "/", "url": "http://x//", "status": 404,
                "error": "answered HTTP 404"}
        result, _ = self.run_dir({"shots": [shot("before")], "failures": [fail]}, {"shots": [shot()]})
        self.assertNotEqual(result["verdict"], "clean")
        self.assertEqual(result["capture_failures"][0]["status"], 404)

    def test_a_shot_from_an_error_status_is_never_clean(self):
        # An older capture, or a hand-made shot, that still carries the status.
        bad = dict(shot(), status=404)
        result, _ = self.run_dir({"shots": [dict(shot("before"), status=404)]}, {"shots": [bad]})
        self.assertNotEqual(result["verdict"], "clean")
        self.assertIn("HTTP 404", result["note"])

    def test_a_blocker_still_holds_when_a_capture_also_failed(self):
        fail = {"page": "about", "viewport": "390", "path": "/about", "url": "http://x/about", "status": 500,
                "error": "answered HTTP 500"}
        result, _ = self.run_dir({"shots": [shot("before", overflow=0)]},
                                 {"shots": [shot(overflow=23)], "failures": [fail]})
        self.assertEqual(result["verdict"], "hold")
        self.assertIn("capture failed", result["note"])


class AlreadyOnMainTest(unittest.TestCase):
    """Astro run 2: the capture caught the steps column 128 px off and "tem|plate" breaking
    mid-word, both already on main, and pr-qa's page left them out entirely. They are listed
    apart, labeled, and never change the verdict."""

    def pair(self, **extra):
        base = dict(offCenter=[], offColumns=[], midWord=[], untitled=[], untitledCount=0)
        before = dict(shot("before", slug="home-default", size="desktop", client=1440), **base)
        after = dict(shot(slug="home-default", size="desktop", client=1440), **base)
        for k, v in extra.items():
            before[k] = v
            after[k] = v
        return before, after

    def test_flaws_on_both_sides_are_listed_apart_and_do_not_change_the_verdict(self):
        col = {"kind": "edge", "text": "Get your dream website", "tag": "div", "edge": 232, "neighbors": 104}
        before, after = self.pair(offColumns=[col], midWord=["tem|plate"], untitledCount=2,
                                  untitled=[{"text": "#1 most starred", "tag": "section", "id": "proof", "height": 155},
                                            {"text": "6K GITHUB STARS", "tag": "section", "id": "stats", "height": 244}])
        found = compare([before], [after])
        self.assertEqual(found, [])
        result = summarize(found, measured=measured([before], [after]),
                           already=already_on_main([before], [after]))
        self.assertEqual(result["verdict"], "clean")
        notes = result["already_on_main"]
        titles = " ".join(n["title"] for n in notes)
        self.assertIn("off-center", titles)
        self.assertIn("mid-word", titles)
        self.assertIn("without a heading", titles)
        detail = " ".join(n["detail"] for n in notes)
        self.assertIn("Get your dream website", detail)
        self.assertIn("tem|plate", detail)
        self.assertIn("#1 most starred", detail)
        self.assertTrue(all(n["severity"] == "note" for n in notes))
        self.assertEqual(result["counts"], {"blocker": 0, "warning": 0, "good": 0})

    def test_pre_existing_overflow_is_listed_too(self):
        before = shot("before", overflow=12)
        after = shot(overflow=12)
        notes = already_on_main([before], [after])
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("scrolls sideways", notes[0]["title"])
        self.assertIn("12px", notes[0]["detail"])

    def test_a_flaw_only_the_pr_adds_is_a_finding_not_a_note(self):
        before, after = self.pair()
        after = dict(after, midWord=["authentic|ation"], untitledCount=1,
                     untitled=[{"text": "Stats band", "tag": "section", "id": "", "height": 200}])
        found = compare([before], [after])
        titles = [f["title"] for f in found]
        self.assertTrue(any("mid-word" in t for t in titles), titles)
        self.assertTrue(any("without a heading" in t for t in titles), titles)
        self.assertTrue(all(f["severity"] == "warning" for f in found), found)
        self.assertEqual(already_on_main([before], [after]), [])

    def test_a_flaw_the_pr_fixed_is_not_listed(self):
        before, after = self.pair()
        before = dict(before, midWord=["tem|plate"])
        self.assertEqual(already_on_main([before], [after]), [])

    def test_older_captures_without_the_fields_list_nothing(self):
        self.assertEqual(already_on_main([shot("before")], [shot()]), [])

    def test_cli_writes_already_on_main(self):
        before, after = self.pair(midWord=["tem|plate"])
        with tempfile.TemporaryDirectory() as tmp:
            for label, s in (("before", before), ("after", after)):
                with open(os.path.join(tmp, f"{label}.json"), "w") as handle:
                    json.dump({"shots": [s]}, handle)
            out = os.path.join(tmp, "findings.json")
            with redirect_stdout(StringIO()) as buf:
                main(["--dir", tmp, "--out", out])
            result = json.load(open(out))
            self.assertEqual(result["verdict"], "clean")
            self.assertEqual(len(result["already_on_main"]), 1)
            self.assertIn("1 already on main", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
