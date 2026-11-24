---
name: visual-qa
version: 1.4.5
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

**House rules.** Same as every proofs capture skill; full text in `../../reference/house-rules.md`.

1. **Finish in this turn.** Build, smoke-check and screenshot before you reply; the next turn re-reads the whole session and costs more each time. Write big files (HTML, spec JSON, scripts) with the Write tool and never print them back with `cat`, `head` or `Read`; the helpers print short summaries.
2. **Stay in two folders.** Read only inside the project (the folder Claude Code started in) and the plugin folder. Do not read parent folders: their `CLAUDE.md` is already loaded for you. Write specs, scratch scripts, screenshots and pages only under `.proofs/` in the project, never the system temp folder, `$TMPDIR` or `~`. The exceptions are the Playwright install in `~/.cache/proofs-playwright` and pr-qa's `PROOFS_BASE_DIR` base folder, when it is set. Write the Playwright folder only with its one install line; never `ls` or Read it to see whether Playwright is there (it is outside the project, so the call is refused): the capture and `--smoke` report a missing install themselves, with exit 2 and the line to run.
3. **One command per Bash call.** No pipes, redirects, `;`, `&&`, `cd`, `$(...)` or `VAR=` in front: Claude Code matches its allow rules against the whole command, and any of those makes it ask (or, in `claude -p`, refuse).
4. **Use the helpers' own checks, not ad hoc tools.** Capture prints each shot's size and overflow; never run `file`, `magick`/`identify` or `sips`, and change your own mockups with Edit or Write, never `sed -i`.

- **Print "Commands this review will run"** before the first Bash call: one short list with the exact forms (the install, for example `npm install`; the capture line below; the style build if the project compiles styles; the type check if the project has one, in the form the project uses: `npx tsc --noEmit`, or for Vue `npx vue-tsc --noEmit`, or its own `npm run type-check` or `npm run build`). Then run them without further narration. The README's optional project block can pre-approve them.
- Run the branch under test on its own port (3311), never another session's server. Find the start command in the project's notes; install missing dependencies with the project's own command.
- Make the data look like production (realistic counts, long names, missing values), touching
  only the feature's own tables. **Note the starting state first and put it back after.**
- Write `.proofs/visual-qa/pages.json` with the Write tool (start from the example pages file bundled in this
  skill's scripts folder). One entry per page × state. **States to cover:** full, empty, long text, missing values, each role, and
  every sheet, dialog, open `<details>` and partial-page update, reached by clicking (`actions`) the way
  a person would. A partial-page update can leave a page no plain `goto` ever shows.
- Sign in through the real form with a `setup` hook (a sign-in example is bundled in the scripts folder). Read the
  password from the untracked env file inside the hook; never print it. If a page shows a
  secret, replace it in the DOM before capture.
- Run it exactly as written; Claude Code fills in `${CLAUDE_PLUGIN_ROOT}`, and the allow rule only matches the unquoted form. The helper starts the server, waits for the URL, runs the capture with `PROOFS_BASE_URL` set, then stops the server:

  ```bash
  python3 ${CLAUDE_PLUGIN_ROOT}/shared/capture/with_server.py --start "npm run dev -- --port 3311" --url http://localhost:3311/ -- node ${CLAUDE_PLUGIN_ROOT}/skills/visual-qa/scripts/capture.cjs .proofs/visual-qa/pages.json --out .proofs/visual-qa/before
  ```

  The port flag belongs to the dev server: `--port` for Vite (SvelteKit, Vue, Astro), Nuxt and Angular, `-p` or `--port` for Next.js; copy the project's own start command when its README or `CLAUDE.md` gives one, and read `package.json`'s `dev` script otherwise (`vite dev` means `--port`). Never start the server yourself with `run_in_background` or `&`: in `claude -p` the turn then never ends. If the helper prints `server: already answering at <url>; not started by this helper`, the shot may be of another app: rerun on a different port. Only when a server you were given is already running, drop the helper and run `node ${CLAUDE_PLUGIN_ROOT}/skills/visual-qa/scripts/capture.cjs .proofs/visual-qa/pages.json --out .proofs/visual-qa/before` alone.
  Each address is `base` and `path` joined with exactly one slash. A page that answers HTTP 400 or above, or renders an error page ("Not Found"), is a failed shot, not a finding: the capture lists it as FAILED, leaves it out of the evidence and exits 6; fix the `path` or the server and run it again. A malformed pages file stops with one line naming what is wrong (exit 1).
  Three viewports (1440, 1280, 390 CSS px; `--sizes 390,1280` picks some, and a plain width such as `1040` adds a desktop viewport just above a breakpoint), a first-screen and a full-page PNG each,
  named `<page>-<state>-<width>[-full].png`, plus `measures.json`, `summary.md` and a printed table.
  The 390 view is a true 390 px viewport, and the overflow is measured three ways. A page wider than the phone
  is a finding, not a failed capture: a phone lays it out wider and zooms out to fit, so the row reads, for example,
  `sideways scroll: 17px, zoomed`, and the other phone numbers are still taken. If Playwright is
  missing, the error prints the one-line install; run it once and rerun. If the install is declined, say the phone view is
  "not measured"; never fake it with Chrome `--window-size` below 500 (macOS headless Chrome lays the page out at 500 px).

## 2. Compare against the targets

The script measures and flags the first six; the rest come from `items` stats and your look.

| Measure | Target |
|---|---|
| Sideways scroll | 0, including content hidden by `overflow-x: hidden` (the `clipped` signal); wide tables scroll inside their own box |
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

A carousel that shows part of the next slide inside an `overflow: hidden` box may read as clipped; check it by eye.

Check the in-between widths (768 and 1024) for anything that changes at a breakpoint, such as
charts and grids.

## 4. Write the audit

`.proofs/visual-qa/audit.md`: one table per page (measure, target, value, PASS/FAIL), then the
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
- Build it under `.proofs/` and publish it; do not commit screenshots unless the
  project's notes say to.

## 6. After the picks: build, re-capture, show BEFORE → AFTER

Build the approved fixes on a branch (following the project's notes for branching, tests
and review), rerun steps 1–3 with `--out .proofs/visual-qa/after` and the
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
