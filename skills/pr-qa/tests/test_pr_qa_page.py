"""Unit tests for scripts/pr_qa_page.py.

Standard library only, plus node+jsdom for the page-behavior test -- these
must run offline. The jsdom tests skip unless `jsdom` resolves via NODE_PATH or
./node_modules.

Run:  python3 -m unittest discover skills/pr-qa/tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
from pr_qa_page import (
    load_evidence, effective_verdict, merge_findings, order_prs,
    VERDICT_RANK, SEVERITY_RANK,
    data_uri, pair_shots, embed, MAX_PAGE_BYTES,
    render, build, validate_meta, ABSENT, smoke, load_meta, skipped_line,
)


def write_evidence(directory, findings=None, shots=None, plan=None):
    """A minimal but REAL evidence directory, shaped like a QA run's evidence."""
    os.makedirs(directory, exist_ok=True)
    findings = findings if findings is not None else {
        "findings": [], "counts": {"blocker": 0, "warning": 0, "good": 0},
        "verdict": "clean", "unmapped_changes": [], "pages_covered": ["/x"]}
    shots = shots if shots is not None else [
        {"label": "after", "size": "phone", "file": "after-x-phone.png", "slug": "x",
         "pageLabel": "X", "path": "/x", "overflow": 0, "errors": []}]
    for name, body in (("findings.json", findings),
                       ("after.json", {"shots": shots}),
                       ("before.json", {"shots": [dict(s, label="before",
                                                       file=s["file"].replace("after-", "before-"))
                                                  for s in shots]}),
                       ("plan.json", plan or {"pages": [], "unmatched_changes": []})):
        with open(os.path.join(directory, name), "w", encoding="utf-8") as handle:
            json.dump(body, handle)
    for shot in shots:
        for label in ("before", "after"):
            path = os.path.join(directory, shot["file"].replace("after-", f"{label}-"))
            # Bytes vary by BOTH label and size, so a page that genuinely
            # differs between before/after or between phone/desktop actually
            # produces a different data: URI -- a fixture that emitted the
            # same bytes for every view let a broken Before/After or
            # Desktop/Phone control pass silently (found 2026-08-05).
            marker = f"{label}:{shot.get('size', '')}".encode("ascii")
            with open(path, "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\n" + marker.ljust(32, b"0"))


def node_env(case, root):
    """Environment for the jsdom-driven tests; skips them when jsdom is missing.

    jsdom is found through NODE_PATH (if you set it) or ./node_modules.
    """
    paths = [os.path.join(root, "node_modules"), os.path.join(os.getcwd(), "node_modules")]
    if os.environ.get("NODE_PATH"):
        paths.append(os.environ["NODE_PATH"])
    env = dict(os.environ, NODE_PATH=os.pathsep.join(paths))
    probe = subprocess.run(["node", "-e", "require('jsdom')"], capture_output=True, env=env)
    if probe.returncode != 0:
        case.skipTest("jsdom is not installed (npm install jsdom, or set NODE_PATH)")
    return env


class LoadEvidenceTest(unittest.TestCase):
    def test_reads_findings_shots_and_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_evidence(tmp)
            evidence = load_evidence(tmp)
            self.assertEqual(evidence["verdict"], "clean")
            self.assertEqual(len(evidence["after"]), 1)
            self.assertEqual(len(evidence["before"]), 1)
            self.assertTrue(evidence["present"])

    def test_a_missing_directory_is_absent_evidence_not_a_crash(self):
        evidence = load_evidence("/nonexistent/path")
        self.assertFalse(evidence["present"])
        self.assertEqual(evidence["verdict"], "unknown")
        self.assertEqual(evidence["after"], [])


class EffectiveVerdictTest(unittest.TestCase):
    def test_a_human_blocker_overrides_a_clean_machine_verdict(self):
        evidence = {"present": True, "verdict": "clean"}
        human = [{"severity": "blocker", "title": "duplicate migration", "detail": "..."}]
        self.assertEqual(effective_verdict(evidence, human), "hold")

    def test_no_human_findings_on_present_evidence_keeps_the_machine_verdict(self):
        self.assertEqual(effective_verdict({"present": True, "verdict": "look"}, []), "look")

    def test_absent_evidence_is_unknown_not_clean(self):
        self.assertEqual(effective_verdict({"present": False, "verdict": "unknown"}, []), "unknown")

    def test_a_human_blocker_overrides_absent_evidence_too(self):
        """A reviewer wrote 'do not merge' on a PR with no screenshots. The old
        code returned "unknown" (chip: "Not reviewed") before it ever looked at
        human_findings -- silently discarding the one finding that mattered
        most."""
        evidence = {"present": False, "verdict": "unknown"}
        human = [{"severity": "blocker", "title": "do not merge", "detail": "..."}]
        self.assertEqual(effective_verdict(evidence, human), "hold")


class NotMeasuredTest(unittest.TestCase):
    UNMEASURED = {"present": True, "verdict": "unknown", "measured": False}

    def test_unmeasured_evidence_with_a_human_warning_reads_look_first(self):
        self.assertEqual(effective_verdict(self.UNMEASURED, [{"severity": "warning"}]), "look")

    def test_unmeasured_evidence_without_human_findings_stays_unknown(self):
        self.assertEqual(effective_verdict(self.UNMEASURED, []), "unknown")

    def test_a_human_finding_of_only_good_does_not_escalate(self):
        self.assertEqual(effective_verdict(self.UNMEASURED, [{"severity": "good"}]), "unknown")

    def test_old_findings_files_count_as_measured(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_evidence(tmp)
            self.assertIs(load_evidence(tmp)["measured"], True)

    def test_not_measured_note_is_on_the_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_evidence(tmp, findings={
                "findings": [], "counts": {}, "verdict": "unknown", "measured": False,
                "note": "not measured: nothing to compare"})
            evidence = load_evidence(tmp)
        pr = {"number": 1, "title": "T", "verdict": "unknown", "evidence": evidence}
        self.assertIn("not measured: nothing to compare",
                      render([pr], [], "Sample Project", "acme/widgets"))


class OrderTest(unittest.TestCase):
    def test_worst_first_and_unknown_outranks_clean(self):
        prs = [{"number": 1, "verdict": "clean"}, {"number": 2, "verdict": "hold"},
               {"number": 3, "verdict": "unknown"}, {"number": 4, "verdict": "look"}]
        self.assertEqual([p["number"] for p in order_prs(prs)], [2, 3, 4, 1])

    def test_ties_break_by_pr_number_so_the_order_is_stable(self):
        prs = [{"number": 9, "verdict": "look"}, {"number": 3, "verdict": "look"}]
        self.assertEqual([p["number"] for p in order_prs(prs)], [3, 9])


class MergeFindingsTest(unittest.TestCase):
    def test_human_and_machine_findings_are_tagged_with_their_source(self):
        evidence = {"present": True, "findings": [
            {"severity": "warning", "title": "m", "detail": "d"}]}
        human = [{"severity": "blocker", "title": "h", "detail": "d"}]
        merged = merge_findings(evidence, human)
        self.assertEqual([f["source"] for f in merged], ["human", "machine"])
        self.assertEqual([f["severity"] for f in merged], ["blocker", "warning"])


class EmbedTest(unittest.TestCase):
    def _pr(self, tmp, shots):
        write_evidence(tmp, shots=shots)
        return {"number": 1, "verdict": "look", "evidence": load_evidence(tmp)}

    def test_a_shot_becomes_a_png_data_uri(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "a.png")
            with open(path, "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\n")
            self.assertTrue(data_uri(path).startswith("data:image/png;base64,"))

    def test_pairs_carry_both_sizes_and_both_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            shots = [{"label": "after", "size": size, "file": f"after-x-{size}.png",
                      "slug": "x", "pageLabel": "X", "path": "/x",
                      "overflow": 0, "errors": []} for size in ("phone", "desktop")]
            pairs = pair_shots(self._pr(tmp, shots)["evidence"])
            self.assertEqual({p["size"] for p in pairs}, {"phone", "desktop"})
            for pair in pairs:
                self.assertIn("before", pair)
                self.assertIn("after", pair)

    def test_a_pair_over_budget_is_dropped_whole_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            shots = [{"label": "after", "size": size, "file": f"after-{slug}-{size}.png",
                      "slug": slug, "pageLabel": slug, "path": f"/{slug}",
                      "overflow": 0, "errors": []}
                     for slug in ("a", "b") for size in ("phone", "desktop")]
            pr = self._pr(tmp, shots)
            embedded, dropped = embed([pr], budget_bytes=200)
            kept = [p for p in embedded[0]["pairs"] if p.get("before") and p.get("after")]
            # A half-embedded pair would break the Before/After control silently.
            for pair in kept:
                self.assertTrue(pair["before"].startswith("data:image/png;base64,"))
                self.assertTrue(pair["after"].startswith("data:image/png;base64,"))
            self.assertTrue(dropped, "over budget must report what went")
            self.assertIn("PR #%d" % 1, dropped[0])

    def test_a_budget_dropped_pair_survives_in_pairs_rather_than_vanishing(self):
        """A pair the budget could not afford was still photographed. Dropping
        it from `pairs` entirely made the viewer misreport it as never
        captured -- the true story is "captured, but too expensive to embed
        alongside worse PRs"."""
        with tempfile.TemporaryDirectory() as tmp:
            shots = [{"label": "after", "size": size, "file": f"after-{slug}-{size}.png",
                      "slug": slug, "pageLabel": slug, "path": f"/{slug}",
                      "overflow": 0, "errors": []}
                     for slug in ("a", "b") for size in ("phone", "desktop")]
            pr = self._pr(tmp, shots)
            embedded, dropped = embed([pr], budget_bytes=200)
            pairs = embedded[0]["pairs"]
            self.assertEqual(len(pairs), 4, "every captured pair must survive, embedded or not")
            not_kept = [p for p in pairs if not (p.get("before") and p.get("after"))]
            self.assertTrue(not_kept, "the budget must actually have dropped something")
            for pair in not_kept:
                self.assertTrue(pair.get("dropped"), "a budget-dropped pair must be flagged as such")
                self.assertFalse(pair.get("missing"), "dropped is not the same claim as missing")
                self.assertIsNone(pair.get("before"))
                self.assertIsNone(pair.get("after"))

    def test_nothing_is_dropped_silently_when_it_all_fits(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, dropped = embed([self._pr(tmp, None)])
            self.assertEqual(dropped, [])

    def test_a_before_shot_with_no_matching_after_still_becomes_a_pair(self):
        """pr_qa_findings.py already flags this as a finding ("no after shot"):
        the after-pass failed on this one page. Before this fix, pair_shots
        iterated evidence["after"] only, so the page was simply absent from
        the viewer -- an evidence gap rendered as coverage instead of a gap."""
        with tempfile.TemporaryDirectory() as tmp:
            write_evidence(tmp, shots=[
                {"label": "after", "size": "phone", "file": "after-x-phone.png",
                 "slug": "x", "pageLabel": "X", "path": "/x",
                 "overflow": 0, "errors": []}])
            before_path = os.path.join(tmp, "before.json")
            with open(before_path, encoding="utf-8") as handle:
                before_data = json.load(handle)
            before_data["shots"].append({
                "label": "before", "size": "phone", "file": "before-y-phone.png",
                "slug": "y", "pageLabel": "Y", "path": "/y"})
            with open(before_path, "w", encoding="utf-8") as handle:
                json.dump(before_data, handle)
            with open(os.path.join(tmp, "before-y-phone.png"), "wb") as handle:
                handle.write(b"\x89PNG\r\n\x1a\nbefore-only")

            evidence = load_evidence(tmp)
            pairs = pair_shots(evidence)
            self.assertIn("y", {p["slug"] for p in pairs},
                          "a before-only page must still appear as a pair")
            missing_after = next(p for p in pairs if p["slug"] == "y")
            self.assertIsNotNone(missing_after["beforeFile"])
            self.assertIsNone(missing_after["afterFile"])

            embedded, _ = embed([{"number": 1, "verdict": "look", "evidence": evidence}])
            rendered_pair = next(p for p in embedded[0]["pairs"] if p["slug"] == "y")
            self.assertTrue(rendered_pair.get("missing"),
                            "no after shot means the pair proves nothing -- it "
                            "must be flagged, not silently dropped")
            self.assertIsNone(rendered_pair.get("before"))
            self.assertIsNone(rendered_pair.get("after"))


import subprocess


JSDOM_DRIVER = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
// `url` MUST be a real origin. Left at the default `about:blank`, the page is an
// opaque origin and any localStorage access throws a bare `DOMException {}` with
// no message -- which reads as a bug in the page and is not. Cost 2026-08-05.
const dom = new JSDOM(fs.readFileSync(process.argv[2], 'utf8'),
                      { runScripts: 'dangerously', url: 'https://claude.ai/code/artifact/x' });
const { window } = dom;
window.navigator.clipboard = { writeText: t => { window.__copied = t; return Promise.resolve(); } };
const out = {};
const img = window.document.querySelector('[data-shot]');
out.firstSrc = img && img.getAttribute('src').slice(0, 30);
// Flip Before/After and confirm the picture actually changes.
const before = img && img.getAttribute('src');
const toggle = window.document.querySelector('[data-label="before"]');
if (toggle) toggle.click();
out.changedOnFlip = !!img && img.getAttribute('src') !== before;
// The phone view must carry the 390px cap class; the desktop view must not.
const frame = window.document.querySelector('.shot-frame');
out.phoneClassOnPhone = !!frame && frame.classList.contains('is-phone');
// Flip Desktop/Phone.
const afterFlip = img && img.getAttribute('src');
const sizeToggle = window.document.querySelector('[data-size="desktop"]');
if (sizeToggle) sizeToggle.click();
out.changedOnSize = !!img && img.getAttribute('src') !== afterFlip;
out.phoneClassOnDesktop = !!frame && frame.classList.contains('is-phone');
const phoneToggle = window.document.querySelector('[data-size="phone"]');
if (phoneToggle) phoneToggle.click();
out.phoneClassAfterBack = !!frame && frame.classList.contains('is-phone');
if (sizeToggle) sizeToggle.click();
// A decision registers and the counter moves.
const radio = window.document.querySelector('input[type=radio][value="merge-and-push"]');
if (radio) { radio.checked = true; radio.dispatchEvent(new window.Event('change', { bubbles: true })); }
out.counter = (window.document.querySelector('[data-counter]') || {}).textContent;
const copy = window.document.querySelector('[data-copy]');
if (copy) copy.click();
Promise.resolve().then(() => {
  out.export = window.__copied || '';
  console.log(JSON.stringify(out));
});
"""


XSS_DRIVER = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
const dom = new JSDOM(fs.readFileSync(process.argv[2], 'utf8'),
                      { runScripts: 'dangerously', url: 'https://claude.ai/code/artifact/x' });
const { window } = dom;
const doc = window.document;
const out = {};
const app = doc.getElementById('app');
out.appChildren = app ? app.children.length : 0;
out.hasOnerrorImg = !!doc.querySelector('img[onerror]');
out.pwned = !!window.__pwned;
const h2 = doc.querySelector('.pr-head h2');
out.titleRendered = !!(h2 && h2.textContent.indexOf('onerror') !== -1);
console.log(JSON.stringify(out));
"""


DROPPED_PAIR_DRIVER = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
const dom = new JSDOM(fs.readFileSync(process.argv[2], 'utf8'),
                      { runScripts: 'dangerously', url: 'https://claude.ai/code/artifact/x' });
const doc = dom.window.document;
const img = doc.querySelector('[data-shot]');
const placeholder = doc.querySelector('.shot-placeholder');
console.log(JSON.stringify({
  hasSrc: !!(img && img.getAttribute('src')),
  placeholder: placeholder ? placeholder.textContent : null,
}));
"""


DOM_CHECKS_DRIVER = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
const dom = new JSDOM(fs.readFileSync(process.argv[2], 'utf8'),
                      { runScripts: 'dangerously', url: 'https://claude.ai/code/artifact/x' });
const doc = dom.window.document;
const out = {};
out.hasUnreviewedNotice = Array.prototype.some.call(
  doc.querySelectorAll('.notice.warn'),
  function (n) { return n.textContent.indexOf('not yet read by a reviewer') !== -1; });
out.hasEmptyState = !!doc.querySelector('.empty');
var bar = doc.querySelector('header.bar');
out.barText = bar ? bar.textContent : '';
out.barSession = bar && bar.querySelector('.session') ? bar.querySelector('.session').textContent : null;
out.barFirst = bar && bar.firstElementChild ? bar.firstElementChild.className : '';
var withSrc = doc.querySelectorAll('[src]');
out.srcCount = withSrc.length;
out.badSrc = Array.prototype.filter.call(withSrc, function (n) {
  return n.getAttribute('src').indexOf('data:') !== 0;
}).length;
console.log(JSON.stringify(out));
"""


class RenderTest(unittest.TestCase):
    def _page(self, tmp, title="A change", human_findings=None):
        write_evidence(os.path.join(tmp, "pr-1"), findings={
            "findings": [{"severity": "blocker", "title": "sideways at 390px",
                          "detail": "23px over.", "evidence": {}}],
            "counts": {"blocker": 1, "warning": 0, "good": 0}, "verdict": "hold",
            "unmapped_changes": [], "pages_covered": ["/x"]},
            # Both sizes for the same page, not just phone: the fixture's PNG
            # bytes now vary by size as well as label, so this is what makes
            # the Desktop/Phone control's test genuinely falsifiable, rather
            # than only ever finding a placeholder-vs-image difference.
            shots=[{"label": "after", "size": size, "file": f"after-x-{size}.png",
                    "slug": "x", "pageLabel": "X", "path": "/x",
                    "overflow": 0, "errors": []} for size in ("phone", "desktop")])
        prs = [{"number": 1, "title": title, "branch": "agent/todo-31",
                "cost": "$1.84", "tests": "59 pass, 0 added",
                "recommendation": "merge-and-push", "narrative": "Does a thing.",
                "human_findings": human_findings if human_findings is not None else [],
                "verdict": "hold",
                "evidence": load_evidence(os.path.join(tmp, "pr-1"))}]
        embedded, dropped = embed(prs)
        return render(embedded, dropped, "Sample Project", "acme/widgets")

    def _run_dom_checks(self, html):
        """Run DOM_CHECKS_DRIVER against a rendered page and return its
        parsed JSON. Used for the three assertions (finding 4) that must
        inspect the DOM the script actually builds, not the raw HTML string
        -- PAGE_TEMPLATE contains all three literals unconditionally, so a
        plain substring search on `html` cannot ever falsify them."""
        with tempfile.TemporaryDirectory() as tmp:
            page = os.path.join(tmp, "page.html")
            with open(page, "w", encoding="utf-8") as handle:
                handle.write(html)
            driver = os.path.join(tmp, "drive-dom.js")
            with open(driver, "w", encoding="utf-8") as handle:
                handle.write(DOM_CHECKS_DRIVER)
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            env = node_env(self, root)
            run = subprocess.run(["node", driver, page], capture_output=True,
                                 text=True, cwd=root, env=env)
            self.assertEqual(run.returncode, 0, run.stderr)
            return json.loads(run.stdout.strip().splitlines()[-1])

    def test_every_image_in_the_dom_is_a_data_uri(self):
        """`assertNotIn('src="http', html)` searched the raw HTML string, but
        the DOM is built entirely in JS -- no `<img src=...>` is ever written
        by hand, so that string can never appear and the assertion could
        never fail. Check what actually lands on an `<img>` element instead."""
        with tempfile.TemporaryDirectory() as tmp:
            out = self._run_dom_checks(self._page(tmp))
            self.assertGreater(out["srcCount"], 0,
                               "the page must render at least one element with a src")
            self.assertEqual(out["badSrc"], 0,
                             "every rendered src must be a data: URI")

    def test_unreviewed_notice_appears_only_without_human_findings(self):
        """The literal "not yet read by a reviewer" lives unconditionally in
        PAGE_TEMPLATE's JS source, so `assertIn(..., html)` passed even for a
        fully-reviewed PR. It must appear in the rendered DOM for an
        unreviewed PR and be ABSENT once a reviewer has left a finding."""
        with tempfile.TemporaryDirectory() as tmp:
            unreviewed = self._run_dom_checks(self._page(tmp, human_findings=[]))
            reviewed = self._run_dom_checks(self._page(tmp, human_findings=[
                {"severity": "good", "title": "Looks fine", "detail": "Checked by hand."}]))
        self.assertTrue(unreviewed["hasUnreviewedNotice"],
                        "an unreviewed PR must show the notice")
        self.assertFalse(reviewed["hasUnreviewedNotice"],
                         "a reviewed PR must not show the notice")

    def test_the_project_bar_names_the_real_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("acme/widgets", self._page(tmp))

    def test_the_bar_starts_with_the_proofs_mark_skill_and_session(self):
        page = render([], [], "Sample Project", "acme/widgets", "pr-qa-review")
        out = self._run_dom_checks(page)
        self.assertEqual(out["barFirst"], "pf")
        self.assertIn("proofspr-qaProofs, pr-qaSample Project", out["barText"])
        self.assertEqual(out["barSession"], "pr-qa-review")
        # an older call with no session still renders, just without it
        self.assertIsNone(self._run_dom_checks(render([], [], "P", "o/r"))["barSession"])

    def test_empty_state_renders_only_with_no_open_prs(self):
        """"Nothing waiting" also lives unconditionally in PAGE_TEMPLATE, so
        `assertIn(..., html)` passed even with PRs present. The empty-state
        element must render when there are no PRs and must NOT render when
        there are."""
        with tempfile.TemporaryDirectory() as tmp:
            with_prs = self._run_dom_checks(self._page(tmp))
        without_prs = self._run_dom_checks(
            render([], [], "Sample Project", "acme/widgets"))
        self.assertFalse(with_prs["hasEmptyState"],
                         "a page with open PRs must not show the empty state")
        self.assertTrue(without_prs["hasEmptyState"],
                        "a page with no open PRs must show the empty state")

    def test_the_script_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "page.html")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(self._page(tmp))
            script = self._page(tmp).split("<script>")[1].split("</script>")[0]
            js = os.path.join(tmp, "page.js")
            with open(js, "w", encoding="utf-8") as handle:
                handle.write(script)
            check = subprocess.run(["node", "--check", js], capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, check.stderr)

    def test_the_page_behaves_when_actually_run(self):
        """One bad escape kills the script silently and leaves a page that
        looks fine and does nothing. Only running it proves otherwise."""
        with tempfile.TemporaryDirectory() as tmp:
            page = os.path.join(tmp, "page.html")
            with open(page, "w", encoding="utf-8") as handle:
                handle.write(self._page(tmp))
            driver = os.path.join(tmp, "drive.js")
            with open(driver, "w", encoding="utf-8") as handle:
                handle.write(JSDOM_DRIVER)
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            # NODE_PATH, not cwd: node resolves `require` from the SCRIPT's
            # directory, and the driver is in a tmpdir. cwd=root does nothing.
            env = node_env(self, root)
            run = subprocess.run(["node", driver, page], capture_output=True,
                                 text=True, cwd=root, env=env)
            self.assertEqual(run.returncode, 0, run.stderr)
            out = json.loads(run.stdout.strip().splitlines()[-1])
            self.assertTrue(out["firstSrc"].startswith("data:image/png;base64,"))
            self.assertTrue(out["changedOnFlip"], "Before/After did not change the image")
            self.assertTrue(out["changedOnSize"], "Desktop/Phone did not change the image")
            self.assertTrue(out["phoneClassOnPhone"], "Phone view lacks the is-phone cap")
            self.assertFalse(out["phoneClassOnDesktop"], "Desktop view kept the is-phone cap")
            self.assertTrue(out["phoneClassAfterBack"], "Returning to Phone did not re-add is-phone")
            self.assertIn("1", out["counter"] or "")
            self.assertIn("PR #%d" % 1, out["export"])
            self.assertIn("merge-and-push", out["export"])

    COPY_DRIVER = r"""
const fs = require('fs');
const { JSDOM } = require('jsdom');
const mode = process.argv[3];
const dom = new JSDOM(fs.readFileSync(process.argv[2], 'utf8'),
                      { runScripts: 'dangerously', url: 'http://192.168.1.5:8000/page.html' });
const { window } = dom;
if (mode === 'ok') window.navigator.clipboard = { writeText: t => Promise.resolve() };
if (mode === 'reject') window.navigator.clipboard = { writeText: t => Promise.reject(new Error('denied')) };
const radio = window.document.querySelector('input[type=radio][value="merge-and-push"]');
if (radio) { radio.checked = true; radio.dispatchEvent(new window.Event('change', { bubbles: true })); }
const copy = window.document.querySelector('[data-copy]');
copy.click();
setTimeout(() => {
  const box = window.document.querySelector('textarea[data-copy-fallback]');
  console.log(JSON.stringify({ label: copy.textContent, box: box ? box.value : null }));
}, 50);
"""

    def _copy(self, mode):
        with tempfile.TemporaryDirectory() as tmp:
            page = os.path.join(tmp, "page.html")
            with open(page, "w", encoding="utf-8") as handle:
                handle.write(self._page(tmp))
            driver = os.path.join(tmp, "copy.js")
            with open(driver, "w", encoding="utf-8") as handle:
                handle.write(self.COPY_DRIVER)
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            env = node_env(self, root)
            run = subprocess.run(["node", driver, page, mode], capture_output=True,
                                 text=True, cwd=root, env=env)
            self.assertEqual(run.returncode, 0, run.stderr)
            return json.loads(run.stdout.strip().splitlines()[-1])

    def test_copy_says_copied_only_on_success(self):
        out = self._copy("ok")
        self.assertEqual(out["label"], "Copied")
        self.assertIsNone(out["box"])

    def test_copy_falls_back_to_a_text_box_without_a_clipboard(self):
        out = self._copy("missing")
        self.assertNotEqual(out["label"], "Copied")
        self.assertIn("merge-and-push", out["box"] or "")

    def test_copy_falls_back_to_a_text_box_when_the_write_fails(self):
        out = self._copy("reject")
        self.assertNotEqual(out["label"], "Copied")
        self.assertIn("merge-and-push", out["box"] or "")

    def test_a_closing_script_tag_in_a_title_cannot_blank_the_page(self):
        """The brief's own stated failure mode: json.dumps does not escape
        "<", so an unescaped payload lets a PR title close the <script> tag
        early and inject arbitrary markup into the live DOM."""
        payload_title = 'Fix </script><img src=x onerror="window.__pwned=1"><script>//'
        with tempfile.TemporaryDirectory() as tmp:
            page = os.path.join(tmp, "page.html")
            with open(page, "w", encoding="utf-8") as handle:
                handle.write(self._page(tmp, title=payload_title))
            driver = os.path.join(tmp, "drive-xss.js")
            with open(driver, "w", encoding="utf-8") as handle:
                handle.write(XSS_DRIVER)
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            env = node_env(self, root)
            run = subprocess.run(["node", driver, page], capture_output=True,
                                 text=True, cwd=root, env=env)
            self.assertEqual(run.returncode, 0, run.stderr)
            out = json.loads(run.stdout.strip().splitlines()[-1])
            self.assertGreater(out["appChildren"], 0,
                               "the page must still render its cards, not go blank")
            self.assertFalse(out["hasOnerrorImg"], "an attacker payload must not reach the DOM")
            self.assertFalse(out["pwned"], "the injected onerror handler must never run")
            self.assertTrue(out["titleRendered"],
                            "the title text itself must still make it to the page, safely")

    def test_a_budget_dropped_pair_renders_the_size_limit_placeholder(self):
        """A pair the byte budget dropped IS present in `pairs` (before/after
        None, `dropped: True`) -- the viewer must say it was dropped for size,
        never that the page was never photographed."""
        with tempfile.TemporaryDirectory() as tmp:
            write_evidence(os.path.join(tmp, "pr-1"))
            prs = [{"number": 1, "title": "A change", "branch": "agent/todo-31",
                    "cost": "$1.84", "tests": "1 pass", "recommendation": "wait",
                    "narrative": "", "human_findings": [], "verdict": "look",
                    "evidence": load_evidence(os.path.join(tmp, "pr-1"))}]
            # A budget too small for even one pair guarantees it survives as
            # dropped rather than embedded.
            embedded, dropped = embed(prs, budget_bytes=10)
            self.assertTrue(dropped)
            self.assertEqual(len(embedded[0]["pairs"]), 1)
            self.assertTrue(embedded[0]["pairs"][0].get("dropped"))
            page = os.path.join(tmp, "page.html")
            with open(page, "w", encoding="utf-8") as handle:
                handle.write(render(embedded, dropped, "Sample Project",
                                    "acme/widgets"))
            driver = os.path.join(tmp, "drive-dropped.js")
            with open(driver, "w", encoding="utf-8") as handle:
                handle.write(DROPPED_PAIR_DRIVER)
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            env = node_env(self, root)
            run = subprocess.run(["node", driver, page], capture_output=True,
                                 text=True, cwd=root, env=env)
            self.assertEqual(run.returncode, 0, run.stderr)
            out = json.loads(run.stdout.strip().splitlines()[-1])
            self.assertFalse(out["hasSrc"], "a dropped pair must never get a real <img src>")
            self.assertIn("dropped to keep the page under the size limit", out["placeholder"] or "")
            self.assertNotIn("not photographed", out["placeholder"] or "")


class RenderDefaultsTest(unittest.TestCase):
    def test_an_empty_string_field_falls_back_not_blank(self):
        """`skeleton()` always writes `cost`/`tests`/`recommendation` as ""
        rather than omitting the key, so `pr.get(key, default)` never fires --
        the documented "Recommended" badge and the em-dash placeholders never
        appeared. `or` must treat "" the same as a missing key."""
        pr = {"number": 1, "title": "T", "branch": "b", "cost": "", "tests": "",
              "recommendation": "", "narrative": "", "human_findings": [],
              "verdict": "unknown", "evidence": dict(ABSENT), "pairs": []}
        html = render([pr], [], "Sample Project", "acme/widgets")
        self.assertIn('"recommendation": "wait"', html)
        self.assertIn('"cost": "\\u2014"', html)
        self.assertIn('"tests": "\\u2014"', html)


class BuildValidationTest(unittest.TestCase):
    """meta.json is hand-written by a session; nothing else checks its shape.
    A mistyped severity or recommendation must crash build(), not silently
    downgrade a blocker to a gray "clean" dot sorted to the bottom."""

    def _write_meta(self, tmp, entries):
        path = os.path.join(tmp, "meta.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(entries, handle)
        return path

    def test_an_invalid_human_finding_severity_raises_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta_path = self._write_meta(tmp, [{
                "number": 9, "title": "T", "branch": "b", "dir": None,
                "absent_reason": "", "cost": "", "tests": "", "narrative": "",
                "recommendation": "", "human_findings": [
                    {"severity": "critical", "title": "x", "detail": "y"}]}])
            out_path = os.path.join(tmp, "page.html")
            with self.assertRaises(ValueError) as ctx:
                build(meta_path, out_path, "Sample Project", "acme/widgets")
            message = str(ctx.exception)
            self.assertIn("critical", message)
            self.assertIn("9", message)
            for valid in ("blocker", "warning", "good"):
                self.assertIn(valid, message)

    def test_an_invalid_recommendation_raises_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta_path = self._write_meta(tmp, [{
                "number": 4, "title": "T", "branch": "b", "dir": None,
                "absent_reason": "", "cost": "", "tests": "", "narrative": "",
                "recommendation": "ship-it-now", "human_findings": []}])
            out_path = os.path.join(tmp, "page.html")
            with self.assertRaises(ValueError) as ctx:
                build(meta_path, out_path, "Sample Project", "acme/widgets")
            message = str(ctx.exception)
            self.assertIn("ship-it-now", message)
            self.assertIn("4", message)

    def test_a_valid_meta_builds_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta_path = self._write_meta(tmp, [{
                "number": 3, "title": "T", "branch": "b", "dir": None,
                "absent_reason": "no run", "cost": "", "tests": "", "narrative": "",
                "recommendation": "wait", "human_findings": [
                    {"severity": "good", "title": "x", "detail": "y"}]}])
            out_path = os.path.join(tmp, "page.html")
            build(meta_path, out_path, "Sample Project", "acme/widgets")
            self.assertTrue(os.path.exists(out_path))

    def test_validate_meta_directly_names_offending_value_and_pr(self):
        with self.assertRaises(ValueError) as ctx:
            validate_meta([{"number": 42, "recommendation": "nope",
                            "human_findings": []}])
        self.assertIn("42", str(ctx.exception))
        self.assertIn("nope", str(ctx.exception))


class RiseGateTest(unittest.TestCase):
    """A merge recommendation over a finding that rose needs a stated reason."""

    RISE = {"findings": [{"severity": "warning", "title": "X at desktop: new small tap targets",
                          "detail": '"A" 10x10px', "evidence": {"rise": True}}],
            "counts": {"blocker": 0, "warning": 1, "good": 0}, "verdict": "look",
            "unmapped_changes": [], "pages_covered": ["/x"]}

    def _build(self, tmp, recommendation, **extra):
        evidence = os.path.join(tmp, "ev")
        write_evidence(evidence, findings=self.RISE)
        entry = {"number": 17, "title": "T", "branch": "b", "dir": evidence,
                 "absent_reason": "", "cost": "", "tests": "", "narrative": "",
                 "recommendation": recommendation, "human_findings": []}
        entry.update(extra)
        meta = os.path.join(tmp, "meta.json")
        with open(meta, "w", encoding="utf-8") as handle:
            json.dump([entry], handle)
        out = os.path.join(tmp, "page.html")
        return build(meta, out, "Sample Project", "acme/widgets")

    def test_merge_with_unexplained_rise_refuses(self):
        for rec in ("merge-and-push", "merge-hold-push"):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(SystemExit) as ctx:
                    self._build(tmp, rec)
                self.assertIn("17", str(ctx.exception))
                self.assertIn("rise_explained", str(ctx.exception))

    def test_rise_check_tolerates_string_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._build(tmp, "merge-and-push",
                        rise_explained="Footer links only.",
                        human_findings=[{"severity": "good", "title": "x",
                                         "detail": "y", "evidence": "see shot 3"}])

    def test_send_back_with_a_rise_is_fine(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._build(tmp, "send-back")

    def test_merge_with_rise_explained_renders_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = self._build(tmp, "merge-and-push",
                               rise_explained="The new links are footer legal text.")
            self.assertIn("Why merge anyway", page)
            self.assertIn("The new links are footer legal text.", page)


REAL_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d4944415478da63f8cfc0f01f0005000201fe2a2b6c0b0000000049454e44ae426082")


class SkippedTest(unittest.TestCase):
    """The page names every open PR it did not cover, and why."""

    def _build(self, tmp, skipped=None, prs=True):
        entries = []
        if prs:
            evidence = os.path.join(tmp, "ev")
            write_evidence(evidence)
            entries = [{"number": 3, "title": "T", "branch": "b", "dir": evidence,
                        "absent_reason": "", "cost": "", "tests": "", "narrative": "",
                        "recommendation": "wait", "human_findings": []}]
        meta = os.path.join(tmp, "meta.json")
        body = entries if skipped is None else {"prs": entries, "skipped": skipped}
        with open(meta, "w", encoding="utf-8") as handle:
            json.dump(body, handle)
        return build(meta, os.path.join(tmp, "page.html"), "Sample Project", "acme/widgets")

    def test_skipped_line_rendered(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = self._build(tmp, [{"number": 2, "reason": "not requested"}])
            self.assertIn("Other open PRs: #2 (not requested)", page)

    def test_skipped_line_joins_several(self):
        self.assertEqual(
            skipped_line([{"number": 2, "reason": "not requested"},
                          {"number": 5, "reason": "draft"}]),
            "Other open PRs: #2 (not requested); #5 (draft)")

    def test_skipped_line_ignores_entries_without_a_number(self):
        self.assertEqual(
            skipped_line([{"reason": "draft"}, {"number": None}, {"number": 5, "reason": "draft"}]),
            "Other open PRs: #5 (draft)")
        self.assertEqual(skipped_line([{"reason": "draft"}]), "")

    def test_skipped_empty_renders_nothing(self):
        for skipped in (None, []):
            with tempfile.TemporaryDirectory() as tmp:
                page = self._build(tmp, skipped)
                self.assertNotIn("Other open PRs: #", page)
                self.assertIn('"skippedLine": ""', page)

    def test_skipped_line_shows_with_zero_prs(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "..", "..", "..", "shared", "review_page"))
        import review_page
        pw = review_page.find_playwright(None)
        if not pw:
            self.skipTest("Playwright is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            self._build(tmp, [{"number": 2, "reason": "not requested"}], prs=False)
            script = os.path.join(tmp, "dom.cjs")
            with open(script, "w", encoding="utf-8") as handle:
                handle.write(
                    "const {chromium}=require(process.argv[2]);"
                    "const {launchChromium}=require(process.argv[4]);"
                    "(async()=>{const b=await launchChromium(chromium,process.env);"
                    "const p=await b.newPage();await p.goto('file://'+process.argv[3]);"
                    "console.log(await p.locator('#app').innerText());await b.close()})()")
            launch = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                                  "shared", "review_page", "launch.cjs"))
            r = subprocess.run(["node", script, pw, os.path.join(tmp, "page.html"), launch],
                               capture_output=True, text=True)
            self.assertIn("Other open PRs: #2 (not requested)", r.stdout, r.stderr)
            self.assertIn("Nothing waiting", r.stdout)

    def test_a_bare_list_meta_still_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = os.path.join(tmp, "m.json")
            with open(meta, "w", encoding="utf-8") as handle:
                json.dump([{"number": 1}], handle)
            self.assertEqual(load_meta(meta), ([{"number": 1}], []))


class SmokeTest(unittest.TestCase):
    """--smoke drives the built page in a real browser."""

    def _page(self, tmp, real_images=True, prs=True):
        evidence = os.path.join(tmp, "ev")
        entries = []
        if prs:
            write_evidence(evidence)
            if real_images:
                for name in os.listdir(evidence):
                    if name.endswith(".png"):
                        with open(os.path.join(evidence, name), "wb") as handle:
                            handle.write(REAL_PNG)
            entries = [{"number": 3, "title": "T", "branch": "b", "dir": evidence,
                        "absent_reason": "", "cost": "", "tests": "", "narrative": "",
                        "recommendation": "merge-and-push", "human_findings": []}]
        meta = os.path.join(tmp, "meta.json")
        with open(meta, "w", encoding="utf-8") as handle:
            json.dump(entries, handle)
        out = os.path.join(tmp, "page.html")
        build(meta, out, "Sample Project", "acme/widgets")
        return out

    def _smoke(self, path):
        ok, result = smoke(path)
        if ok is None:
            self.skipTest("Playwright is not installed: " + result["error"])
        return ok, result

    def test_smoke_passes_on_built_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, result = self._smoke(self._page(tmp))
            self.assertTrue(ok, result)
            self.assertEqual(result["problems"], [])

    def test_smoke_reports_broken_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, result = self._smoke(self._page(tmp, real_images=False))
            self.assertFalse(ok)
            self.assertTrue(any("image" in p for p in result["problems"]), result)

    def test_smoke_zero_prs_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, result = self._smoke(self._page(tmp, prs=False))
            self.assertTrue(ok, result)

    def test_smoke_cli_missing_playwright_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            page = self._page(tmp)
            script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "scripts", "pr_qa_page.py")
            env = dict(os.environ, HOME=tmp, PROOFS_PLAYWRIGHT="", PATH=os.path.dirname(sys.executable))
            r = subprocess.run([sys.executable, script, "--smoke", page],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("playwright@1.61.1", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
