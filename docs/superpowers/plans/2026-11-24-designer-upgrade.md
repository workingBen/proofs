# Designer Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** design-review produces options a professional would sign off on: a real range per item, every element of the section accounted for, measured and rubric-scored by a critic before the reader sees them.

**Architecture:** Three additive layers on today's flow. The capture gains an `elements` list per section. The builder gains per-variant `role`, `inventory` and `scores` fields, and `--smoke` gains design checks and a near-copy check per mockup. The skill text gains the profile, range, inventory, critic and "keep X" steps, backed by two new reference files (rubric, profile).

**Tech Stack:** Node (Playwright) for capture and smoke; Python 3 stdlib `unittest` for the builder and tests; markdown skills.

**Spec:** `docs/superpowers/specs/2026-11-24-designer-design.md` (approved 2026-11-24). Read it first.

## Global Constraints

- **Start from main after 1.6.10 merges** (1.6.10 edits `capture.cjs`, `midword.cjs`, design-review's SKILL.md and adds the "Results first" house rule). Branch `feat/designer`, worktree `__agent-projects/proofs-wt-designer-impl` off a fresh `origin/main`.
- **Does not merge until the held-out React Router run is scored** (it runs on the version before this). Push and open the PR; the main session merges later.
- Additive only in `capture.cjs`: no existing `measures.json` field changes; visual-qa and pr-qa tests pass unchanged.
- Version **1.7.0** via `bin/bump-version 1.7.0`; CHANGELOG lines per skill touched.
- Results first: never cut an option, check or the critic to save cost; the $5 est. per-run cap is the only limit.
- Headless-safe: one command per Bash call, everything under `.proofs/`, no network fetch, no subagent required in `claude -p`.
- American English. Stage explicit paths. Tests in the FOREGROUND (≤600000 ms per call; split the root suite by module if needed). At most two test runs on the laptop at once. No GitHub Actions, no `open`, no private context.
- Every threshold chosen is listed in the PR body with its reason.
- Fix rule: each check is tested on fixtures AND on two piw apps (Astro + one of Vue/SvelteKit/Next.js) before the PR.

## Review Focus

1. **A page with no `section`/landmark elements** (a single `div` soup): the capture must still produce sections (direct children of `main`, else `body`, over 200 px tall), never an empty list. Test in Task 1.
2. **A mockup with text over an image or gradient:** contrast can't be measured from one background color; report it as `contrast: not measured` for that element, never as a pass or a fail. Test in Task 2.
3. **One-variant items** (bug-sized fixes, capture items): no near-copy check between variants, no role label required, and no warning about a missing range. Test in Tasks 3 and 4.
4. **A variant whose inventory omits an element the capture listed:** the builder treats an element missing from the inventory as "removed, no reason" and shows the warning, rather than silently passing. Test in Task 4.
5. **Critic scores missing on some variants** (critic skipped or failed): the page says "not scored" on those variants and the item cannot be `recommended` on a variant that wasn't scored, unless the item has one variant. Test in Task 4.

---

### Task 1: Section element inventory in the capture

**Files:**
- Modify: `skills/visual-qa/scripts/capture.cjs` (`measure()` and the measures written at ~line 754)
- Create: `tests/fixtures/capture/inventory.html`, `tests/fixtures/capture/inventory-divs.html`
- Test: `tests/test_visual_qa_capture.py` (new class `SectionInventory`)

**Interfaces:**
- Produces: each result's `measures.sections: [{id, tag, label, top, height, elements: [{kind, text, tag, top, left, width, height}]}]`, `kind` ∈ `heading|text|button|link|image|list|form|badge`. `label` = the section's first heading text, else its id/class, else `section N`. Plus `measures.fontSizes: [number]` (distinct computed text sizes on the page, px, sorted). Also summarized in `summary.md` under "Sections" (one line per section: label, element counts by kind).

- [ ] **Step 1:** Write `inventory.html` (a header, two `section`s, a footer; each with a heading, a paragraph, a button, an image, a 3-item list) and `inventory-divs.html` (same content as `div`s inside `main`, each over 200 px tall).
- [ ] **Step 2:** Write tests `test_sections_are_listed_with_their_elements` (4 sections; section 2 has 1 heading, 1 text, 1 button, 1 image, 1 list, in DOM order with positions) and `test_div_only_page_falls_back_to_main_children` (4 sections from `main > *`). Also `test_existing_measures_fields_unchanged` (keys present before this task are all still present with the same types on the existing fixtures).
- [ ] **Step 3:** Run `python3 -m unittest tests.test_visual_qa_capture.SectionInventory -v` → FAIL (no `sections`).
- [ ] **Step 4:** Implement inside `measure()`: section = `section, header, footer, main > *, [role=region], [role=banner], [role=contentinfo]`, deduped by outermost; fallback = direct children of `main` (else `body`) taller than 200 px (*200: shorter blocks are bars and dividers, not sections*). Cap 40 elements per section, 30 sections per page.
- [ ] **Step 5:** Run the class → PASS; then the whole module and `tests.test_pr_qa*` modules → PASS unchanged.
- [ ] **Step 6:** Commit `capture: list each section's elements in measures.json`.

### Task 2: Design checks on every mockup in `--smoke`

**Files:**
- Create: `shared/review_page/designchecks.cjs`
- Modify: `shared/review_page/smoke.cjs` (call it per variant box, as `midWordBreaks` is called)
- Test: `tests/test_review_page.py` (new class `DesignChecks`), fixtures under `tests/fixtures/review_page/`

**Interfaces:**
- Produces: `designChecks(page, boxSelector, {width}) -> Promise<{contrast: [{text, ratio, needed}], unmeasured: [{text, reason}], smallTargets: [{text, w, h}], longLines: [{text, chars}], edges: [{a, b, px}]}>`; smoke JSON gains `design_checks: [{item, variant, width, ...thatObject}]`, and each non-empty list adds one line to `problems` in the form `item 2 (Hero), Variant B: 3 text elements below AA contrast at 1280px`.

- [ ] **Step 1:** Fixture spec with one item, three variants: A clean; B with gray-on-white text (#999 on #fff, 2.85:1), a 30×30 button and a 120-character line; C with text on a `linear-gradient` background.
- [ ] **Step 2:** Tests (plus `test_off_scale_size_is_a_note` with `before_font_sizes: [16, 20, 32]` and a 27px heading): `test_low_contrast_is_reported_with_its_ratio` (B, ratio ≈2.85, needed 4.5), `test_small_target_at_390` (B, 30×30), `test_long_line_at_1280` (B, ≥120 chars), `test_text_on_gradient_is_unmeasured_not_failed` (C in `unmeasured`, not `contrast`), `test_clean_variant_has_no_design_problems` (A).
- [ ] **Step 3:** Run → FAIL.
- [ ] **Step 4:** Implement. Contrast: WCAG relative luminance of computed color vs the nearest ancestor's opaque `background-color`; any ancestor with a `background-image` → `unmeasured`. Needed: 4.5, or 3.0 for text ≥24px or ≥18.66px bold. Tap targets: `a, button, [role=button], input, select` under 44×44 at 390 (*44: Apple HIG and WCAG 2.5.5*). Line length: rendered characters per line over 80 at 1280 (*80: upper bound of the usual 45–80 readable range*). Edges: left edges of a section's direct block children within 1–6 px of each other but not equal (*≤6 px reads as a mistake, more reads as a choice*). Off scale: a mockup text size more than 1 px from every size in the item's `before_font_sizes` (the page's `measures.fontSizes`, copied into the spec by the skill), reported as a note, not a problem line; skipped when the item has none.
- [ ] **Step 5:** Run class → PASS; run `tests.test_review_page` whole → PASS.
- [ ] **Step 6:** Commit `smoke: contrast, tap target, line length and edge checks on every mockup`.

### Task 3: Near-copy check in `--smoke`

**Files:**
- Create: `shared/review_page/signature.cjs`
- Modify: `shared/review_page/smoke.cjs`
- Test: `tests/test_review_page.py` (class `NearCopy`)

**Interfaces:**
- Consumes: optional item field `before_sections` (the matching `measures.sections[i]` from Task 1, copied into the spec by the skill).
- Produces: `layoutSignature(page, boxSelector) -> [{kind, x, y, w, h}]` normalized to the box (0–1), and `similarity(sigA, sigB) -> number` (0–1). smoke JSON gains `near_copies: [{item, a, b, score}]` (`b` may be `"before"`), each adding a problem line `item 1 (Hero): Variant A and the current page are near-copies (0.94)`.

- [ ] **Step 1:** Tests: `test_identical_variants_flagged` (two variants with the same markup but different colors → flagged), `test_different_layouts_pass` (stacked vs two-column → not flagged), `test_variant_matching_before_sections_flagged`, `test_one_variant_item_has_no_pair_check`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement: signature = the box's elements by the Task 1 kinds, positions normalized; similarity = mean best-match IoU over elements of the same kind, penalized by count difference. Threshold 0.85 (*builder to tune on the two piw apps; state the final number and why*).
- [ ] **Step 4:** Run → PASS. Commit `smoke: flag options that are near-copies of each other or of the page`.

### Task 4: Roles, inventory and scores on the review page

**Files:**
- Modify: `shared/review_page/review_page.py` (`review_item()` ~line 955, spec validation), `shared/review_page/style.css`
- Modify: `reference/review-page.md` (field table ~line 139)
- Test: `tests/test_review_page.py` (class `DesignerFields`)

**Interfaces:**
- Consumes: variant fields `role` ∈ `careful|step-up|bold`; `inventory: [{element, status: kept|moved|removed, reason}]`; `scores: {hierarchy, action, fold, grouping, fit, care}` (1–5 each) and item field `judged_by` ∈ `helper|self`; item field `before_sections` (Task 3).
- Produces: rendered role label in the variant head ("Careful", "Step up", "Bold"), a compact inventory table (removed rows in `--rp-deny`), a one-line score row, and "Judged by a separate helper" / "Checked by the designer itself" under the item. Spec errors (plain one line) for: unknown role, unknown status, a score outside 1–5, `recommended` on an unscored variant in a multi-variant item.

- [ ] **Step 1:** Tests: `test_roles_render_as_labels`, `test_removed_element_is_marked`, `test_inventory_missing_a_captured_element_counts_as_removed` (an element in `before_sections` absent from the inventory renders as "removed — no reason given"), `test_scores_render_and_unscored_says_not_scored`, `test_recommending_an_unscored_variant_is_a_spec_error`, `test_one_variant_item_needs_no_role_or_scores`, `test_judged_by_line`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement the validation and rendering; document the fields in `reference/review-page.md`.
- [ ] **Step 4:** Run class, then the whole module, then `--smoke` on the fixture page at 390 → no sideways scroll (the inventory table scrolls inside its own box). Commit `review page: option roles, element inventory and critic scores`.

### Task 5: Rubric and profile reference files

**Files:**
- Create: `reference/design-rubric.md`, `reference/design-profile.md`
- Test: `tests/test_skill_guidance.py` (class `DesignerReferences`)

**Interfaces:**
- Produces: the rubric's six criteria with the keys Task 4 uses (`hierarchy`, `action`, `fold`, `grouping`, `fit`, `care`), what 1, 3 and 5 look like for each, and **the bar: any criterion at 2 or below, or any failed design check, means revise once or drop, with the reason on the page**. The profile file documents the default path `docs/design-profile.md` (or `PROOFS_DESIGN_PROFILE`), its four headings (References, Rules, Audience, Tokens), a filled example, and the creation flow (a `questions` page: loved/liked/not-for-us references with one line why, then 3–7 rules, then audience).

- [ ] **Step 1:** Tests: rubric names all six keys and contains "2 or below"; profile names `docs/design-profile.md`, `PROOFS_DESIGN_PROFILE` and the four headings; neither file names a private project or person (reuse the privacy-scan helper's term check).
- [ ] **Step 2:** Run → FAIL. Write both files. Run → PASS. Commit `reference: design rubric and design profile`.

### Task 6: design-review and style-guide skill text

**Files:**
- Modify: `skills/design-review/SKILL.md`, `skills/style-guide/SKILL.md`, both CHANGELOGs, README's design-review section
- Test: `tests/test_skill_guidance.py` (class `DesignerGuidance`)

**Interfaces:**
- Consumes: Tasks 1–5's fields, checks and files, by name.

Text to add to design-review (the implementer writes the prose; the test pins the phrases):
- **Profile:** read the profile if present; if missing, say so in one line, offer to create one (Task 5's flow), and go on without it this round. Never require it.
- **Range:** three options, `role` Careful / Step up / Bold, for a redesign request; one option for a bug-sized fix or a "Found by the capture" item. Options must differ in layout or hierarchy; `--smoke`'s near-copy line is a problem to fix.
- **Inventory:** copy the section's `measures.sections` entry into the item as `before_sections`, and the page's `measures.fontSizes` as `before_font_sizes`; every option carries `inventory`.
- **Critic:** after the build and `--smoke`, the options are judged against `reference/design-rubric.md`: by a **separate helper with a fresh context when the session can start one**, given only the rubric, the mockup shots, `before_sections` and the profile; otherwise (`claude -p`) by the session itself against the same file. Record `scores` and `judged_by`. Below the bar: revise once or drop, then the existing "at most one correction pass" rule.
- **Keep X:** an `ACCEPT WITH COMMENT` that says keep an element puts it back during the apply step; if it cannot fit, say so and ask.
- style-guide: one line at its end: design-review uses this guide and an optional `docs/design-profile.md`.

- [ ] **Step 1:** Tests pin: "Careful", "Step up", "Bold", "one option for a bug-sized fix", "before_sections", "inventory", "design-rubric.md", "separate helper", "judged_by", "Never require it", "keep" in step 5, and style-guide's "design-profile.md". Also: design-review still passes every existing `HouseRules` test.
- [ ] **Step 2:** Run → FAIL. Write the text. Run → PASS. `bin/check-skills` → OK.
- [ ] **Step 3:** `bin/bump-version 1.7.0`, CHANGELOG lines. Commit `design-review: profile, real range, inventory and a critic pass (1.7.0)`.

### Task 7: Two-stack trial and the PR

**Files:** none committed beyond fixes it finds (each fix gets its own test).

- [ ] **Step 1:** In a scratch copy of piw `astro/` and piw `vue/` (via `git archive`, `cp -c -R` node_modules when present; check ≥2 GB free), run the capture with `--sizes 390,1280` and confirm `sections` is sensible on both (counts match what the page visibly has).
- [ ] **Step 2:** Build a hand-written three-option review spec for each app's hero (Careful/Step up/Bold, inventories, scores) and run `--smoke`: design checks and near-copy lines fire only where they should. Tune the near-copy threshold here; record the final number.
- [ ] **Step 3:** Full gate: root suite (split by module), pr-qa and todos suites (counts via `grep -E "^Ran|^OK"`), `bin/check-skills`, privacy scan. Stop every server.
- [ ] **Step 4:** Push `feat/designer`, open the PR with: what changed per layer, every threshold and why, the two-app results, "does not merge until the held-out React Router run is scored". **Don't merge.**

### Task 8 (main session, after the PR): the test bench and the blind comparison

Not Proofs code; private, in `__agent-projects/piw-handoff/bench/` (never committed to a public repo).

- [ ] **Step 1:** Screenshot the first screen of Vercel, Raycast, Whoop, GOV.UK, Mayo Clinic, Basecamp, Mailchimp (interactive session). Rebuild each as a static page with a made-up name, same-length made-up copy, no logos or photos. Pick 2 at random as held out; record which in `bench/heldout.txt` before looking at any results.
- [ ] **Step 2:** For the 5 tuning pages: run design-review at 1.6.10 and at the branch on "make this first screen something I'd like"; apply each run's recommended option.
- [ ] **Step 3:** Then the 2 held-out pages, same way, once.
- [ ] **Step 4:** A blind rating page (questions skill) per bench page: original, old result, new result, shuffled and unlabeled, each Love / Like / Not for us. The maintainer rates.
- [ ] **Step 5:** Results to the session page: new beats old and beats the original on the held-out two = pass. Then the designer PR merges once the React Router run is scored.
