---
name: design-review
version: 1.10.0
allowed-tools:
  - Read(/${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/shared/review_page/review_page.py *)
  - Bash(node ${CLAUDE_PLUGIN_ROOT}/skills/visual-qa/scripts/capture.cjs *)
description: Use when the user wants to see and choose between rendered options for a visual or layout change before it is built, such as a redesign, a layout bug or "make this section nicer". Differs from visual-qa, which finds what is wrong, and article-copy-edit, which reviews wording; this compares coded mockups with the current page.
---

# Design Review Tool

A human-in-the-loop process for applying visual/layout redesigns to a page. Instead of building a redesign blind, or narrating it in chat, build an interactive review page showing the real current state against proposed variants, then apply only what the user approved. Sibling tool to `article-copy-edit`: same underlying loop, adapted for visual review instead of text.

## Why this exists

Artifacts can't send live clicks back into the conversation; there's no channel from a button in the rendered page back to Claude. So the loop is: build a review page, the user picks a decision per item (optionally with a comment), clicks "Copy My Decisions", pastes the plain-text summary back into chat, and Claude applies exactly what was approved to the real file.

What's different from a copy-edit review is *what's being reviewed*. A layout bug or a proposed redesign needs to be seen rendered, not described in prose, so "before" is a real screenshot of the live page, and "after" is one or more coded mockups built from the page's own real styling, not text.

## When to use

The user wants to change a page's visual design or layout (not its copy) and wants to review real rendered options before anything is built into the actual view. Signals: they ask for a redesign, describe a layout bug, or ask for something like this tool by name.

## The process

### 1. Identify the exact target page/section

Confirm the live route, and which specific section(s) are in scope. A whole-page redesign may still be broken into multiple numbered items, one per section, rather than one giant item.

### 2. Capture "before": always from the running app

The "before" is a screenshot of the page as the running app serves it today, never an image committed in the repo (it shows an older page).

**House rules.** Same as every proofs capture skill; full text in `../../reference/house-rules.md`.

1. **Finish in this turn.** Build, smoke-check and screenshot before you reply; the next turn re-reads the whole session and costs more each time. Write big files (HTML, spec JSON, scripts) with the Write tool and never print them back with `cat`, `head` or `Read`; the helpers print short summaries.
2. **Stay in two folders.** Read only inside the project (the folder Claude Code started in) and the plugin folder. Do not read parent folders: their `CLAUDE.md` is already loaded for you. Write specs, scratch scripts, screenshots and pages only under `.proofs/` in the project, never the system temp folder, `$TMPDIR` or `~`. The exceptions are the Playwright install in `~/.cache/proofs-playwright` and pr-qa's `PROOFS_BASE_DIR` base folder, when it is set. Write the Playwright folder only with its one install line; never `ls` or Read it to see whether Playwright is there (it is outside the project, so the call is refused): the capture and `--smoke` report a missing install themselves, with exit 2 and the line to run.
3. **One command per Bash call.** No pipes, redirects, `;`, `&&`, `cd`, `$(...)` or `VAR=` in front: Claude Code matches its allow rules against the whole command, and any of those makes it ask (or, in `claude -p`, refuse).
4. **Use the helpers' own checks, not ad hoc tools.** Capture prints each shot's size and overflow; never run `file`, `magick`/`identify` or `sips`, and change your own mockups with Edit or Write, never `sed -i`.

Then, in order:

1. **Find the start command** in the project's `CLAUDE.md` or README, then `package.json` scripts, `Procfile`, `bin/dev` or `manage.py runserver`. If none gives one, **ask the user**; do not switch to screenshots on your own. Missing dependencies are installed with the project's own install command, in the forms the README's `--project` allow block covers (for a Django app with no `.venv`: `python3 -m venv .venv`, then `.venv/bin/pip install -r requirements.txt`, then `--start ".venv/bin/python manage.py runserver 3311 --noreload"`). Do not probe first with `python3 -c "import ..."`: list the setup and run it.
2. **Print "Commands this review will run"** before the first Bash call: one short list with the exact forms (the install, for example `npm install`, or the two Python lines above; the capture line below; the style build if the project compiles styles, or the shot shows the old look; the type check if the project has one, for example `npx tsc --noEmit`). Then run them without further narration. The README's optional project block can pre-approve them.
3. **Write the pages file** with the Write tool at `.proofs/capture/pages.json`: a base URL, then one entry per page (start from the example pages file in the visual-qa skill's scripts folder).
4. **Capture with this command**, the same every time. It starts the server, waits for the URL, runs the capture with `PROOFS_BASE_URL` set, then stops the server. One permission prompt is expected.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/shared/capture/with_server.py --start "npm run dev -- -p 3311" --url http://localhost:3311/ -- node ${CLAUDE_PLUGIN_ROOT}/skills/visual-qa/scripts/capture.cjs .proofs/capture/pages.json --out .proofs/capture/before --sizes 390,1280
```

   - It renders a true 390 px phone viewport and writes `summary.md` with measured sideways overflow. **When `summary.md` shows sideways overflow at 390, state it as a finding with the numbers** (for example: the page is 455 px wide on a 390 px screen; the nav is cut off), and show the shot. Hedge only about what was not measured. Open the PNGs and confirm each shows the route you meant.
   - Use port 3311. If the helper prints `server: already answering at <url>; not started by this helper`, the shot may be of another app: rerun on a different port.
   - Use `--cwd DIR` when the server starts from another folder. Exit codes: 3 the server never answered (read `.proofs/server.log`), 4 it exited early, 5 another run holds the lock; any other nonzero is the capture's own.
   - **Never start the server yourself with `run_in_background` or `&`.** In `claude -p` the turn then never ends. The helper owns the server and leaves nothing running.
   - **Fallback only on failure, and say which was used.** Playwright missing: run the one-line install the capture prints, once, then rerun. Install declined or failing: take desktop shots with Chrome (`--window-size=1280,900` is fine, with `--disable-features=MacAppCodeSignClone`, which stops a Mac copying its 1.4 GB app per launch) and mark the phone view "not measured" on the page. **Never use Chrome `--window-size` below 500 for a phone shot:** macOS headless Chrome lays the page out at 500 px at narrower sizes. The Chrome browser extension tools are a last resort; if every call fails with "not connected", stop retrying.

**Match the live wording.** Local test data drifts from the live site; bring the real live text into the local copy before capturing, or the "before" pane won't match the picture in the user's head.

**When the app cannot start, stop and ask.** A setup or install command was refused, the dependencies are missing, or the helper exits 3 or 4 and you cannot fix it: write nothing yet, and ask the user to choose, before you build any mockup or page. Offer (a) the exact setup command(s) to approve, one per line in the forms above (for a Django app, `python3 -m venv .venv` and `.venv/bin/pip install -r requirements.txt`), after which you capture the live app, or (b) going ahead from the committed screenshots, labeled on the page as not live. End the turn with that question (in chat, or on a `questions` page if the project uses one); in `claude -p` too, since a refused command will not be approved mid-turn. Never build a review on committed screenshots unless the user chose (b).

With (b), take each screenshot's date from `git log -1 --format=%cs -- <file>`, write in that item's Reason "committed screenshot, last changed YYYY-MM-DD, not the live app", and say at the top of the page (`intro_html`) and in chat that the before is not live and why the app could not run.

Screenshot each in-scope section at the width(s) that matter. The builder embeds each as a data URI (step 4), so the page is self-contained.

No standing-audit section here; raise accessibility or readability points inline in an item's Reason.

### 3. Turn the redesign brief into discrete numbered items

Each item is one section or component:

- Give it 1-3 coded mockup variants: real HTML/CSS built from the target page's own fonts, colors, and spacing (the same "reuse the target page's own design system" principle as a copy review), not AI-generated images and not a text diff.
- A single-variant item works exactly like a copy-edit item: no gallery needed, just Original vs. the one proposed variant. Its accept button reads "Use Proposed", not "Use Selected": with nothing selectable, "Use Selected" reads as a control the reviewer has failed to find. The builder does this for any item without `variants`.
- Give every item a **Reason** and a **Recommended / Not Recommended** badge, the same convention as a copy review: your own honest judgment, independent of whether you present the item at all.

### 4. Build the review page with the shared builder

**Needs the whole plugin.** This skill reads shared files at `../../reference/` and `../../shared/`, relative to its folder. If they are missing, the skill was copied on its own: install the whole plugin (`/plugin install proofs@proofs`) rather than recreating them.

Write the content; the builder writes the page. Read `../../reference/review-page.md` first: it documents the spec and the command, `python3 ${CLAUDE_PLUGIN_ROOT}/shared/review_page/review_page.py .proofs/design-review/spec.json --out .proofs/pages/<review-name>.html`, with `"decisions": "design-review"`. Do not hand-write the page's JavaScript. Follow any design guidance your environment provides for published pages: "utilitarian but polished," not a landing page. Fill `project` with `name`, `session` and `repo`, taking the session name the way the `working-log` skill does (the session's own name, else one named for the work, kept for the life of the page): the page's header shows the proofs mark, this skill's name, the project and the session, so the user can match the page to its session at a glance.

- **Reuse the target page's own design system** for the mockups (the spec's `css`). Read the project's style guide for its colors and fonts, including dark mode if it has one, rather than trusting a list in this skill, and build against its tokens so the mockups render correctly in every theme the site supports. Give mockup panes their own explicit background rather than letting them inherit the review page's. If the project deliberately darkened its grays to pass contrast, don't "fix" a mockup by reaching back to stock framework grays.
- **Fonts and images.** Use the target page's own font the way the page itself gets it, never by downloading it. If the page links a font stylesheet (for example a Google Fonts `<link>` in its base template), copy that same `<link rel="stylesheet" href="...">` into the spec's `head_html`: the reader's browser loads it, as it does for the site. If the font files are in the project (a `woff2` under `static/` or `public/`), list them in `assets` and point `@font-face` at them from `css` with `src: url({{asset:name}}) format('woff2')`. Either way, end every `font-family` in `css` with a **fallback stack** that resembles the font and a generic family (for a geometric sans such as Space Grotesk: `"Space Grotesk", "Avenir Next", "Segoe UI", ui-sans-serif, system-ui, sans-serif`); the builder warns about a stack with no generic family. Never fetch a font or its CSS with `curl`, `wget` or a script: a network fetch asks for approval (and `claude -p` refuses it), and a linked stylesheet needs no fetch from you. A published artifact loads only Google Fonts stylesheets, so with any other font service say in the item's Reason that the mockup shows the fallback. **Never paste a font's base64 into the spec**: one 22 KB font is about 28,000 tokens, while an asset costs none. Put photos and the before screenshot in `assets` too. The builder embeds every asset **once**, however many mockups use it, and converts PNG and JPEG screenshots to WebP with a PNG or JPEG fallback for older Safari (`image_quality`, `image_max_width`; see the builder reference). Style a screenshot `<img>` by class, not with a `>` child selector: the builder wraps it in a `<picture>`.
- **One item per section**, each with the before screenshot in `body_html`, then either one proposal in `body_html` (the builder then labels the accept button "Use Proposed") or 2-3 `variants`. Every item gets `reason_html` and `recommended`.
- **Open decisions go first. Always.** Things needing a decision this round are the first section, above any recap, carried-forward context, or settled material (`after_html`, or a collapsed block). A reviewer should never scroll past what they have already read to reach the first open item.
- **"Mark as read" drops an item from the next round.** The page exports it as `READ`; next round, do not render that item again, not even dimmed. Carrying context forward applies to an *open* item's own history (`history_html`), not to items the reader has finished with.
- **The export's first line is the page's bracketed title**, because pasted decisions arrive in chat with no other context. The builder writes it, plus the variant letter:

  ```
  [Articles Index — Design Review]
  1. Article card layout — ACCEPT (Use Selected: Variant B)
  2. Read More button placement — ACCEPT WITH COMMENT — COMMENT: keep the button but make it teal, not amber
  3. Header spacing fix — REVISE — COMMENT: still too much white space, try tightening further
  4. Footer redesign — DENY
  5. Sidebar links — ACCEPT (Use Proposed) — READ
  ```

Deliver the page as "Where the page goes" below says (with `artifact`, that means publishing it with the `Artifact` tool). Redeploy to the same file path across revisions of the *same* review page; don't mint a new URL for revisions the user is already looking at.

**Verify before publishing, every time and not just the first.** The build runs its own check (script syntax, card and button counts). Run `--smoke`. If it reports Playwright missing, run the one-line install it prints (it uses your installed Google Chrome and downloads no browser), then run `--smoke` again; if it still cannot run, say on the page and in chat that the self-check did not run. `--smoke` already measures sideways scroll at 1280 and 390. For a look, run `node ${CLAUDE_PLUGIN_ROOT}/skills/visual-qa/scripts/capture.cjs .proofs/capture/review.json --out .proofs/capture/review --sizes 390,1280` with a pages file whose `base` is the `file://` URL of `.proofs/pages/` (an absolute path) and whose entry `path` is `/<review-name>.html` (capture.cjs builds each address as base plus path), then open the PNGs and check your coded mockups don't overlap. Never use Chrome `--window-size` for the phone view. Only publish after all of it passes.

### 5. Applying the decisions

When the user pastes back the copied summary, match items by number (and variant letter, where relevant).

- **`ACCEPT`**: translate the selected variant's markup into the real view or template. This is *not* a paste-in the way a copy edit is: the mockup used static stand-in content (a hardcoded example title and image) previewing what a loop over live records will render, so applying it means adapting the chosen structure and styling into the real template, wiring in loops, real image URLs and real data, not copying the mockup's HTML verbatim.
- **`ACCEPT WITH COMMENT`**: same translation, but the comment modifies the result first. Work out what the final design should be from the comment, then build that into the real view.
- **`DENY`**: leave the file untouched. A comment here is a note or reason, not an instruction to act on.
- **`REVISE`**: leave the file untouched for now; the comment is feedback for a follow-up round (see below), not an instruction to apply anything yet.
- **`PENDING`**: not reviewed yet; leave untouched.

Then rebuild styles if the project compiles them, verify against a real render, and commit following the project's own notes. The review tool changes nothing about how the actual change gets verified and shipped.

### 6. Follow-up rounds on `REVISE` items

Scope the new Artifact to only the still-open item(s). Carry the prior round's rejected proposal forward on each card in `history_html` (clearly labeled "Round 1," "Round 2," etc.) alongside the new one, rebuild and republish to the same URL, re-running the verification before every republish; a smaller page is not a lower-risk page. Items the reader marked read are dropped, not carried.

## Worked example

A review of a tab row on a mobile measurement screen: the row overflowed on a phone with no wrap or active state, and the list below never filtered by type. Two rounds:

- **Round 1**: one proposed variant per concern (layout, active state, filtered list) plus a first pass at a new "see all" modal. The reviewer accepted the tab-row item outright; the modal trigger was sent back ("too much whitespace next to the button") with a request for several genuinely different options, since there was no preference to start from.
- **Round 2**: scoped to just the still-open modal trigger, with four real alternatives (grid tile, icon-only button, plain text link, list-header link) instead of one refined guess. The list-header link was accepted.

What made this work, worth repeating:

- **Test the review page's own buttons by measuring, not by eye.** Round 1 shipped a mobile/desktop width toggle that looked fine but did nothing: the two-up gallery capped each preview's rendered width below the breakpoint it needed to cross. It was caught by measuring the element's bounding box before and after the click in a headless browser. Round 2 replaced the toggle with fixed-width mobile and desktop frames side by side (in their own `overflow-x: auto` container, so the page body never scrolls sideways), leaving no interaction to silently fail.
- **"I don't have a good option, show me a few" is itself a valid Round 2 request.** The reviewer doesn't have to know what they want. REVISE with a vague comment is exactly what a follow-up round is for, and four distinct answers served better than refining one guess in place.
- **Show the rejected first-round idea dimmed.** Round 1's proposal stayed on the same card as Round 2's new options, visually de-emphasized (dimmed, dashed border): enough context to see what changed without competing with the live decision.

## Where the page goes

Before you publish or save the page, read `../../reference/where-the-page-goes.md` (the path is relative to this skill's folder). The project's `PROOFS_PAGES` setting picks artifact, file or wifi, and that file says what each means and how copy buttons must fall back.
