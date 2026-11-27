# design-review Refine and Redesign modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give design-review a Refine mode: an exact snapshot of the current page, small switchable change layers with Yes/No/Revise, and a live combined preview at real desktop and phone widths, while today's behavior becomes Redesign mode.

**Architecture:** The visual-qa capture gains a snapshot writer, which saves each page's rendered DOM as standalone HTML. The review page builder gains a `refine` item type: the snapshot goes into `srcdoc` iframes at 1280 and 390, and each change's CSS is scoped under a `data-rc` attribute on the snapshot's `<html>`, which the engine toggles. `--smoke` measures fidelity, overlaps and design checks inside the frames. A separate `--crops` command renders each change's before and after crops. A `--match-preview` command compares the built page with the preview of the picked changes.

**Tech Stack:** Python 3 (review_page.py, unittest), Node + Playwright (capture.cjs, smoke.cjs), vanilla JS (engine.js), Markdown skill and reference files.

**Spec:** `docs/superpowers/specs/2026-11-26-design-review-modes-design.md`. Read it before any task. Section numbers below (§N) refer to it.

## Global Constraints

- Version **1.10.0**: `.claude-plugin/plugin.json` and design-review's `version` (bump with `bin/bump-version`). There is a CHANGELOG entry in the root CHANGELOG and in `skills/design-review/CHANGELOG.md`.
- American English everywhere: code, comments, test names and docs.
- No new skill, and no new setting. The cap of **3 to 8 changes** per page is fixed (§3).
- No existing check gets weaker. Contrast, tap targets (44 px), mid-word breaks, sideways scroll, line length, edges, brand kept and words unchanged all apply to every Refine state. The near-copy check doesn't run on Refine items, and only on them.
- Existing presets, exports and spec fields don't change behavior. Every current test still passes.
- Refine renders at 390 with no sideways page scroll (Ben reviews on an iPhone).
- House rules: one command per Bash call in skill text, nothing written outside `.proofs/` in a project, and no ad hoc tools.
- **Run tests in the foreground, never in the background. No more than two test runs at once on this machine.**
- The gate on the final head: the root suite `python3 -m unittest $(ls tests/test_*.py | sed 's#/#.#; s#\.py$##')`, the pr-qa and todos suites (`python3 -m unittest discover -s tests` inside each skill folder that has one), `bin/check-skills`, `bin/privacy-scan` and `bin/bump-version --check`.
- Stage explicit paths. Never `git add -A`.

## Review Focus

1. **A snapshot of a page whose CSS uses `@import`, `@font-face` with relative URLs, or cross-origin stylesheets.** A reader expects the base to look like the page. Unreadable cross-origin sheets must be fetched by `<link>` href and kept as links, not silently dropped (test in Task 2).
2. **Change CSS that leaks while the change is off**, for example a rule with a comma-separated selector where only the first part gets scoped. A reader expects "off" to mean the original (test in Task 3).
3. **A snapshot containing `</script>` or `"` in text, put into `srcdoc`.** The page must not break, and the frame must show the text (test in Task 3).
4. **An undecided page restored from the database** with some answers saved. A reader expects the preview to show exactly the saved Yes changes after reload (test in Task 4).
5. **A 390 phone viewing the 1280 frame.** A reader expects it scaled to fit, not scrolling the page sideways (test in Task 4).

---

### Task 1: Spike: a `srcdoc` iframe in a published artifact and `file://`

**Files:**
- Create: `docs/superpowers/spikes/2026-11-26-srcdoc-frame.html` (throwaway page; deleted in Task 8)
- Create: `docs/superpowers/spikes/2026-11-26-srcdoc-frame.md` (result note)

**Interfaces:**
- Produces: a decision recorded in the note: `iframe` or `container-queries`. Tasks 3 and 4 build the one it names.

- [ ] **Step 1:** Write the spike page. It holds two `srcdoc` iframes, 1280 and 390 wide, the 1280 one scaled with `transform: scale()` to fit. The page inside has a media query at 600 px that changes a heading's color, and a style rule scoped under `html[data-rc~="c1"]`. A button on the outer page toggles `data-rc="c1"` on each frame's `contentDocument.documentElement`. A line of text on the outer page reports `getComputedStyle` of the heading inside each frame after the toggle.
- [ ] **Step 2:** Open it via `file://` in headless Chromium (Playwright, through `shared/review_page/launch.cjs`). Expected: the 390 frame shows the phone color, the 1280 frame the desktop color, and the toggle changes both reports.
- [ ] **Step 3:** Hand the page to the controller to publish as an artifact. The controller opens it and asks Ben to open it on his iPhone. The answers are recorded in the note: does it render, does the toggle work, are both widths correct.
- [ ] **Step 4:** Write the note: `iframe` if every check passes in both places, else `container-queries` with what failed. Commit both files.

### Task 2: Snapshot writer in the capture

**Files:**
- Create: `skills/visual-qa/scripts/snapshot.cjs`
- Modify: `skills/visual-qa/scripts/capture.cjs` (a `--snapshot` flag; after each page's 1280 shot, call `snapshotPage`)
- Test: `tests/test_visual_qa_capture.py` (new class `Snapshot`), fixture `tests/fixtures/capture/snapshot/` (a page with a linked stylesheet, an `@font-face` with a relative URL, an `<img>`, a `<canvas>` drawn by script, an inline `<svg>`, and a `<script>` that adds a paragraph)

**Interfaces:**
- Produces: `async snapshotPage(page, outDir, name) -> {file, assets, bytes, canvases, external}`. It writes `<outDir>/<name>-snapshot.html` and `<outDir>/<name>-snapshot-assets/*`. `assets` lists relative paths, `canvases` is the count rasterized, and `external` lists cross-origin stylesheet hrefs kept as `<link>`. `measures.json` gains `snapshot: {file, bytes}` on the page's 1280 entry.

- [ ] **Step 1: Write the failing tests**
  - `test_snapshot_keeps_script_added_content_and_drops_scripts`: the snapshot holds the script-added paragraph, and there's no `<script>` element.
  - `test_snapshot_inlines_same_origin_css_and_rewrites_urls`: no `<link rel=stylesheet>` for the same-origin sheet, a `<style>` holding its rules, and the font URL points into `-snapshot-assets/`.
  - `test_snapshot_rasterizes_canvas_and_keeps_svg`: `canvases == 1`, an `<img>` where the canvas was with the canvas's width and height, and the `<svg>` unchanged.
  - `test_snapshot_keeps_cross_origin_sheet_as_link`: Review Focus 1.
  - `test_snapshot_renders_like_the_page`: a screenshot of the snapshot opened by `file://` at 1280 has a pixel difference ratio under 0.01 against the capture's own 1280 shot (the same shared helper as Task 5).
- [ ] **Step 2:** Run `python3 -m unittest tests.test_visual_qa_capture.Snapshot -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `snapshotPage`. Serialize `document.documentElement.outerHTML` after the capture's scroll-through. Read each `document.styleSheets` entry's `cssRules` (catching cross-origin errors, which go to `external`). Copy `url()` targets and `<img src>`/`srcset` targets into the assets folder. Swap each `<canvas>` for an `<img>` of `toDataURL()`. Remove `<script>` and `on*` attributes. Add `<base>`-free relative paths.
- [ ] **Step 4:** Run the class. Expected: PASS. Then the whole capture test file. Expected: PASS.
- [ ] **Step 5:** Commit.

### Task 3: The `refine` item in the builder

**Files:**
- Modify: `shared/review_page/review_page.py` (the `refine` preset in `PRESETS`; `PRESET_SKILLS["refine"] = "design-review"`; `check_refine_fields(it)`; `render_refine(it, ctx)`; export)
- Modify: `reference/review-page.md` (the Refine item fields)
- Test: `tests/test_review_page.py` (new class `Refine`), fixture `tests/fixtures/review_page/refine/` (a small snapshot plus a spec with 3 changes)

**Interfaces:**
- Consumes: the snapshot file from Task 2 (`base: {"from": ".proofs/capture/before/home-snapshot.html"}`, relative like `before_sections`).
- Produces: the spec shape below. Tasks 4 to 6 read it.
  - The item has `"kind": "refine"`, `base`, `changes`, optional `before_scores`, `set_scores`, `judged_by`, `crops` (Task 6) and `location`.
  - Each change has `id` (`[a-z0-9-]+`, unique on the page), `label`, `why_html`, `targets` (a list of selectors), `css`, optional `swaps` (`[{selector, html}]`), `removes` (`[{element, reason}]`), `scores` (`{gain, keeps}`, 1 to 5) and `recommended`.
  - Export: `N. <label> — YES|NO|REVISE[ — COMMENT: …]`, one per change, numbered on from the page's running number. After them, `Combined: <comma-separated numbers of YES changes>`, or `Combined: none`.
  - Preset buttons: `{"state":"accept","label":"✓ Yes","export":"YES"}`, `{"state":"deny","label":"✕ No","export":"NO"}` and `{"state":"revise","label":"↻ Revise","export":"REVISE","comment":"required"}`. Pending is `PENDING`.
  - In the HTML, each frame is `<iframe class="rp-rc-frame" data-rc-width="1280|390" srcdoc="…">` (or the container-query form if Task 1 says so). Each change's CSS goes into one `<style data-rc-css>` inside the snapshot, every selector prefixed `html[data-rc~="<id>"] `. Swaps are `<template data-rc-swap="<id>" data-rc-target="<selector>">`.

- [ ] **Step 1: Write the failing tests**
  - `test_refine_export_lists_each_change_and_the_combined_line`: two YES and one NO export as `1. … — YES`, `2. … — NO`, `3. … — YES`, then `Combined: 1, 3`.
  - `test_refine_scopes_every_selector_of_a_comma_list`: `.a, .b > c { color: red }` becomes two prefixed selectors (Review Focus 2). An `@media` block's inner rules get prefixed, and `@font-face`/`@keyframes` pass through.
  - `test_refine_srcdoc_survives_quotes_and_script_text`: a snapshot with `"` and a literal `</script>` in a `<pre>` builds, `check()` passes, and the frame's text shows it (Review Focus 3).
  - `test_refine_rejects_more_than_eight_changes` and `test_refine_rejects_fewer_than_one`: SpecError naming the cap.
  - `test_refine_rejects_duplicate_change_ids`, `test_refine_rejects_a_change_with_no_targets`, `test_refine_rejects_scores_out_of_range`.
  - `test_refine_recommending_an_unscored_change_is_an_error_when_judged`: mirrors the variant rule.
  - `test_refine_items_get_no_near_copy_check`: the page's smoke config marks refine items as exempt.
  - `test_refine_set_scores_use_the_six_criteria_and_show_against_the_current_page`: `set_scores` is validated like `scores`, and shown as a "Your picks together (recommended)" row under `before_scores`.
  - `test_refine_removes_lines_show_on_the_card`: each `removes` entry shows with its reason in the deny color.
  - `test_capture_findings_number_on_after_the_changes`: a page with 3 changes and a "Found by the capture" section exports the capture items as 4, 5 and so on.
  - `test_existing_presets_unchanged`: the export of the existing design-review fixture is byte-identical to before.
- [ ] **Step 2:** Run `python3 -m unittest tests.test_review_page.Refine -v`. Expected: FAIL.
- [ ] **Step 3:** Implement `check_refine_fields(it) -> None` (raises SpecError) and `render_refine(it, ctx) -> str`, plus `scope_css(css: str, change_id: str) -> str`. Use a small tokenizer over rule blocks, not a regex over the whole text.
- [ ] **Step 4:** Run the class, then the whole file. Expected: PASS.
- [ ] **Step 5:** Document the fields in `reference/review-page.md` and commit.

### Task 4: Live toggling in the engine

**Files:**
- Modify: `shared/review_page/engine.js` (refine wiring), `shared/review_page/style.css` (the `.rp-rc-*` classes)
- Test: `tests/test_review_page.py` (class `RefineBrowser`, run through Playwright like the existing browser tests)

**Interfaces:**
- Consumes: the HTML from Task 3.
- Produces: `window.rpRefine.state() -> {on: string[], view: "picks"|"original"}`, read by `--smoke` in Task 5.

- [ ] **Step 1: Write the failing tests**
  - `test_yes_turns_the_layer_on_in_both_frames`: after tapping Yes on change `c2`, both frames' `<html>` has `data-rc` containing `c2`, and a targeted element's computed style changed.
  - `test_no_and_pending_leave_it_off`.
  - `test_undecided_cards_start_off_even_when_recommended`.
  - `test_original_toggle_shows_no_layers_and_back`.
  - `test_swap_replaces_the_element_while_on_and_restores_it_off`.
  - `test_reload_restores_saved_answers_into_the_preview`: Review Focus 4, using the answers fixture the db tests already use.
  - `test_390_viewport_has_no_sideways_scroll_and_1280_frame_fits`: Review Focus 5. At a 390 viewport, `scrollWidth <= 390`, and the 1280 frame's rendered box fits the column.
  - `test_each_frame_uses_its_own_width_layout`: the fixture's 600 px media query differs between frames.
- [ ] **Step 2:** Run the class. Expected: FAIL.
- [ ] **Step 3:** Implement the wiring. On a decision change, recompute the YES set and write it to every frame's `data-rc`, after the frame's `load` event. Swaps are applied from templates and restored from a kept clone. Frame scale is `column width / frame width`, recomputed on resize.
- [ ] **Step 4:** Run the class, then the whole file. Expected: PASS.
- [ ] **Step 5:** Commit.

### Task 5: `--smoke` for Refine, and `--match-preview`

**Files:**
- Create: `shared/review_page/fidelity.cjs`
- Modify: `shared/review_page/smoke.cjs`, `shared/review_page/review_page.py` (the `--match-preview` command, the smoke result keys)
- Test: `tests/test_review_page.py` (class `RefineSmoke`)

**Interfaces:**
- Consumes: `designChecks` (designchecks.cjs), `midWordBreaks`, `layoutSignature`/`similarity` (signature.cjs), and `rpRefine` from Task 4.
- Produces:
  - `fidelity.cjs`: `async compareShots(pngA, pngB) -> {pixelRatio, signature}` and `FIDELITY = {pixelRatio: <builder's value>, signature: <builder's value>}`, with each value's reason in a comment and in the PR. Task 2's test uses `compareShots` too.
  - smoke result keys: `refine.fidelity` (per width), `refine.overlaps` (`[{a, b, element, property}]`), and problems lines worded `item N (Refine): base differs from the page at 390 (pixel ratio 0.031)`, `item N (Refine): changes 2 and 5 both change font-weight on .total`, and `item N (Refine), change 3 on: <design check line>`, plus the same for `all changes on`.
  - `review_page.py --match-preview PAGE --picks 1,3 --shots DIR`: exit 0 on a match. Otherwise exit 1, with one line per width saying what differed.

- [ ] **Step 1: Write the failing tests**
  - `test_fidelity_flags_a_base_that_does_not_match_the_before_shot`: a fixture base with one extra margin produces a problem line.
  - `test_fidelity_passes_the_exact_snapshot`.
  - `test_overlap_names_both_changes_the_element_and_the_property`.
  - `test_design_checks_run_on_each_change_alone_and_all_on`: a change that drops contrast below AA shows `change N on:`.
  - `test_no_near_copy_line_for_refine_items`.
  - `test_match_preview_passes_identical_and_fails_a_different_build`.
- [ ] **Step 2:** Run the class. Expected: FAIL.
- [ ] **Step 3:** Implement. Smoke reads the before shot path from the item's `base` (the snapshot's sibling `<name>-default-<width>.png`). For overlap, record each element's computed style with the change off, then on, and intersect `{element, property}` sets pairwise.
- [ ] **Step 4:** Run the class, then the whole file. Expected: PASS.
- [ ] **Step 5:** Commit.

### Task 6: `--crops`

**Files:**
- Create: `shared/review_page/crops.cjs`
- Modify: `shared/review_page/review_page.py` (the `--crops PAGE --out DIR` command; the item's `crops` field embeds them as assets on the next build)
- Test: `tests/test_review_page.py` (class `RefineCrops`)

**Interfaces:**
- Produces: `<DIR>/<change-id>-<before|after>-<1280|390>.png` and `<DIR>/crops.json` (`{id: {width: {x, y, w, h}}}`). The spec's item `"crops": ".proofs/design-review/crops"` makes each card show its four crops.

- [ ] **Step 1: Write the failing tests**
  - `test_crops_cover_the_union_of_targets_plus_margin`: the box in `crops.json` contains every target's box plus the builder's margin.
  - `test_crops_before_and_after_differ_only_inside_the_box`.
  - `test_a_card_shows_four_crops_when_crops_is_set`.
  - `test_a_target_hidden_at_390_gives_a_note_not_a_crash`.
- [ ] **Step 2:** Run the class. Expected: FAIL.
- [ ] **Step 3:** Implement. Crops come from the built page's frames, each at its own width, with that one change on and then off.
- [ ] **Step 4:** Run the class, then the whole file. Expected: PASS.
- [ ] **Step 5:** Commit.

### Task 7: Skill, rubric, profile and docs

**Files:**
- Modify: `skills/design-review/SKILL.md`, `reference/design-rubric.md`, `reference/design-profile.md`, `README.md` (the design-review line), `CHANGELOG.md`, `skills/design-review/CHANGELOG.md`, `.claude-plugin/plugin.json` (via `bin/bump-version`)
- Test: `tests/test_skill_guidance.py` (class `RefineGuidance`)

**Interfaces:**
- Consumes: every command and field from Tasks 2 to 6, by those exact names.

- [ ] **Step 1: Write the failing tests.** Each asserts that the text is present, the same way the existing guidance tests do.
  - SKILL.md names "Refine mode" and "Redesign mode", gives the mode rule of §1 and the one-line mode statement, and runs the capture with `--snapshot` in Refine.
  - SKILL.md orders the Refine flow: snapshot, changes, critic build, `--smoke`, `--crops`, rebuild, publish.
  - SKILL.md's apply step runs `--match-preview` and states the YES-plus-REVISE rule (§7).
  - SKILL.md gives the Redesign fallback that offers Refine.
  - The rubric has a Refine section with `gain` and `keeps` anchors at 1, 3 and 5, the bar (`gain` ≥ 3, `keeps` ≥ 4, no failed check) and the set rule (no worse on any criterion, better on one).
  - The profile has the `Density:` line with `dense`, `balanced` and `airy`, and the creation flow asks it with Audience.
  - Every new command form appears in the skill's `allowed-tools` (or the README's allow block), as `test_command_forms.py` requires.
- [ ] **Step 2:** Run `python3 -m unittest tests.test_skill_guidance.RefineGuidance -v`. Expected: FAIL.
- [ ] **Step 3:** Write the text, in plain words, with American spelling, keeping Redesign's text as it is apart from the density line and the fallback. Bump to 1.10.0 and write both CHANGELOG entries.
- [ ] **Step 4:** Run the full gate (Global Constraints). Expected: all green.
- [ ] **Step 5:** Commit.

### Task 8 (controller): Acceptance on real pages, then merge

Run by the main session, not a subagent.

- [ ] **Step 1:** Delete the Task 1 spike page, keep its note, and commit.
- [ ] **Step 2:** Build the Host Headroom dashboard (`host-headroom --html OUT`, served from a folder). Run design-review on it with Ben's original "improve this" request through the feature branch's plugin, in Refine. Publish the review and have Ben pick.
- [ ] **Step 3:** Build Ben's picks, then run `--match-preview`. Expected: exit 0.
- [ ] **Step 4:** Ben rates the built result against the original with the toggle: Less, Equal or More. Pass is More (spec, How we'll know).
- [ ] **Step 5:** On one bench page, an "improve this" request gets Refine and a "redesign this" request gets Redesign.
- [ ] **Step 6:** Run the gate on the exact head, open the PR (the body lists every threshold with its reason, plus the acceptance results), merge with `gh pr merge --merge`, then `git push origin --delete <branch>`.
