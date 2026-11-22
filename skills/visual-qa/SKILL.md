---
name: visual-qa
version: 1.3.1
allowed-tools:
  - Read(/${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(node ${CLAUDE_PLUGIN_ROOT}/skills/visual-qa/scripts/capture.cjs *)
description: Use when pointed at whole pages to find what is wrong with how they look, before saying any user-facing page is done, and when the user says a layout looks wrong, cramped, empty, too small or broken on a phone. Differs from design-review (options for a change already decided) and pr-qa (a PR's diff), since this finds the problems.
---

# Visual QA → design fixes

Tests prove behavior and reviewers read diffs; neither one sees a page. This skill looks at
whole pages the way a person uses them, measures them against fixed targets, and turns every
failure into a design fix the user approves before anything is built.

**Invoke as** `/proofs:visual-qa <path> [<path> …]` (for example, two page paths from your
site). With no paths, audit every page the current branch touches.

**REQUIRED SUB-SKILL:** the `design-review` skill, for step 5 (the review page and its
export). It ships in the same plugin.

## Why the numbers matter

An online store once shipped with every test green and every review approved, and the first person to
open it saw **one item per laptop screen**: each line 373 px tall in a column half the screen
wide. Nobody had looked, and nobody had a number to fail against. With targets, the same pages
went from 1 to 8 list lines, 4 to 13 table rows, and 1 to 2 tile rows.

## 0. Read the project first

From the project's notes (`CLAUDE.md`) and style guide, note: how to run the server,
how to sign in, the audience (older readers raise the text floor), the site's own fonts
and colors (mockups reuse them), and anything already decided that must not be "fixed". Set `minText` / `minTap` in
`pages.json` if the project's targets differ from 16 px / 44 px.

## 1. Capture real pages, real data, real states

- Run the branch under test on its own port, following the project's notes for how to
  start the site (never another session's server).
- Make the data look like production (realistic counts, long names, missing values), touching
  only the feature's own tables. **Note the starting state first and put it back after.**
- Write a `pages.json` in a scratch folder (start from the example pages file bundled in this
  skill's scripts folder). One entry per page × state. **States to cover:** full, empty, long text, missing values, each role, and
  every sheet, dialog, open `<details>` and partial-page update, reached by clicking (`actions`) the way
  a person would. A partial-page update can leave a page no plain `goto` ever shows.
- Sign in through the real form with a `setup` hook (a sign-in example is bundled in the scripts folder). Read the
  password from the untracked env file inside the hook; never print it. If a page shows a
  secret, replace it in the DOM before capture.
- Run it exactly as written; Claude Code fills in `${CLAUDE_PLUGIN_ROOT}`, and the allow rule only matches the unquoted form:

  ```bash
  node ${CLAUDE_PLUGIN_ROOT}/skills/visual-qa/scripts/capture.cjs pages.json --out before
  ```

  Three viewports (1440×900, 1280×800, 390×844), a first-screen and a full-page PNG each,
  named `<page>-<state>-<width>[-full].png`, plus `measures.json` and a printed summary table.
  Playwright is looked up in the project's `node_modules`, then in `PLAYWRIGHT_PATH`
  (a path to a `node_modules/playwright` directory), then in `~/.cache/proofs-playwright`.
  It launches Playwright's own browser if one is installed and otherwise your installed
  Google Chrome, so it downloads no browser, and every launch carries
  `--disable-features=MacAppCodeSignClone` (it stops Chrome on a Mac copying its whole
  app into a temp folder each time). If Playwright is missing, the error prints the
  one-line install.

## 2. Compare against the targets

The script measures and flags the first six; the rest come from `items` stats and your look.

| Measure | Target |
|---|---|
| Sideways scroll | 0 (wide tables scroll inside their own box) |
| Content width ÷ viewport (desktop) | ≥ 70%, capped near 1200 px and centered |
| Text size | ≥ `minText` (SVG text measured in rendered pixels) |
| Tap targets | ≥ `minTap` both ways; links inside running text exempt |
| Truncation | none while there is room beside it |
| Mid-word breaks ("Wildflo-wer") | none: `overflow-wrap: normal; word-break: normal`; put `<wbr>` after "/" in long compound names |
| Chrome before the first item | < 40% of the first screen |
| Items in the first screen (data pages) | list lines ≥ 6 at 1280 and ≥ 3 at 390; table rows ≥ 12; tile rows ≥ 2; phone cards ≥ 5 |
| Repeated item height | a list line is one row on desktop (≈ 72–82 px) |
| Repeated per-item controls | flag every one that could be shared or inline |

Targets are for data pages (lists, tables, stores, dashboards). On editorial pages (articles,
landing pages) keep the text, tap, scroll, truncation and break checks and judge density by eye.

## 3. Look at every screenshot yourself

Numbers miss things: a label sitting on a bar, two "Other" categories, a zero gutter, a button
that repeats the name beside it, a missing way back, a task that takes two steps where one would
do, a page inconsistent with its neighbors. **The session that will say "done" opens every
screenshot itself.** A helper's "looks fine" is not a look.

Check the in-between widths (768 and 1024) for anything that changes at a breakpoint, such as
charts and grids.

## 4. Write the audit

`<scratch>/audit.md`: one table per page (measure, target, value, PASS/FAIL), then the
problems ranked by how much they hurt a person using the page. Each problem names its page,
viewport, screenshot, the number, what is wrong in plain words, and a proposed fix.

## 5. Turn the problems into a design review

Follow the `design-review` skill's page mechanics, with these additions:

- Set `"skill": "visual-qa"` so the header names this skill, and fill `project` with the session name as `design-review` does.
- One item per problem (or per group of problems with one fix). BEFORE is the real screenshot,
  the user's own first if they sent one.
- 1–2 coded mockups per item, built from the page's real fonts, colors and data, each drawn to
  **prove** its target: a 1280×800 frame that visibly holds 8 list lines, a 390 frame with
  16 px text and 44 px buttons.
- Put the failing number and the target in each item's Reason.
- Anything that is the user's call rather than a layout fix becomes a question item.
- Build it in a scratch folder and publish it; do not commit screenshots unless the
  project's notes say to.

## 6. After the picks: build, re-capture, show BEFORE → AFTER

Build the approved fixes on a branch (following the project's notes for branching, tests
and review), rerun steps 1–3 with `--out after` and the
same `pages.json`, so the files line up name for name. Send AFTER screenshots beside BEFORE with
a table of the key numbers (BEFORE → AFTER) before merging. Pin any number worth keeping in a
test (a query budget, a row count).

## Common mistakes

| Mistake | Fix |
|---|---|
| Auditing only the page the user sent | Run every page of the feature; they should not find the next one |
| Measuring with a closed sheet or `<details>` | Open it with `actions` as its own state |
| Fixed aspect-ratio cards in a phone grid | Let cards take their content's height, recount |
| Counting a stretched link's text as the target | A link whose `::after` covers its row has the row's hit area |
| Leaving seeded data behind | Restore the starting state you noted |
| Reporting a helper's verdict | Open the screenshots yourself |

**Needs the whole plugin.** This skill reads shared files at `../../reference/` and `../../shared/`, relative to its folder. If they are missing, the skill was copied on its own: install the whole plugin (`/plugin install proofs@proofs`) rather than recreating them.

## Where the page goes

Before you publish or save the page, read `../../reference/where-the-page-goes.md` (the path is relative to this skill's folder). The project's `PROOFS_PAGES` setting picks artifact, file or wifi, and that file says what each means and how copy buttons must fall back.
