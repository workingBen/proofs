---
name: design-review
version: 1.8.3
allowed-tools:
  - Read(/${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/shared/review_page/review_page.py *)
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

The "before" is a screenshot of the page as the running app serves it today. Do not use images committed in the repo as the "before" because they happen to be there: they show an older page, and the user will review a design against something that is no longer live.

1. **Find the project's start command.** Look in the project's `CLAUDE.md` or README first, then `package.json` scripts, `Procfile`, `bin/dev`, or `manage.py runserver`. If none of them gives one, **ask the user** for it; do not switch to screenshots on your own. If dependencies are missing (no `node_modules`, no installed bundle), install them with the project's own install command; that is not a reason to fall back to repo images.
   **Pick a free port.** Check that nothing answers on it (`curl -s -o /dev/null http://localhost:PORT/` fails), and start the server on that port. The helper treats a server that already answers at `--url` as ready and leaves it running, so a stale or unrelated app on a reused port would be captured as the "before" and left running.
2. **Rebuild first.** If the project compiles its styles (a CSS build step), run that build before the capture, or the screenshot shows the old look.
3. **Start, wait, capture and stop in one call to the helper.** It starts the server, waits until the URL answers, runs your capture command with `PROOFS_BASE_URL` set to that URL, then always stops the server. It is not pre-approved, so the user may get one permission prompt; that is expected. Example, with Chrome from the command line. Set `CHROME` inside the `sh -c` capture command, never in front of `python3`: the command has to start with `python3 ${CLAUDE_PLUGIN_ROOT}/shared/capture/with_server.py` or it will not match the allow rule for unattended runs, and a variable set in an earlier Bash call is gone by the next one anyway. Pick the binary that exists: `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome` (macOS), `google-chrome`, `google-chrome-stable` or `chromium` (Linux, e.g. `CHROME=google-chrome;`).

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/shared/capture/with_server.py --start "npm run dev -- -p 3311" \
  --url http://localhost:3311/ -- sh -c 'CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"; "$CHROME" --headless --disable-features=MacAppCodeSignClone \
  --hide-scrollbars --virtual-time-budget=8000 --window-size=390,2200 --screenshot=before-390.png "$PROOFS_BASE_URL"'
```

   - Use `--cwd DIR` when the server starts from another folder. For several widths, chain the Chrome commands inside one `sh -c`: each helper call restarts the server.
   - Exit codes: 3 means the server never answered (read `.proofs/server.log`), 4 means it exited early, 5 means another run holds the lock; any other nonzero code is the capture command's own.
   - Exit 0 only means the capture command succeeded: headless Chrome also exits 0 on a blank or error page. Read the PNG and confirm it shows the route you meant.
   - The helper writes its log, pid and lock files to `.proofs/` in the project. Leave that folder untracked (add it to `.gitignore` if the project has one).
   - A headless capture at 390 px wide works. A project's own browser automation (Playwright or similar) also works as the capture command, and is better when you need to measure the page: pass it after `--` the same way, and launch Chrome with `--disable-features=MacAppCodeSignClone` in its `args`.
4. **Never start the server yourself with `run_in_background` or `&`.** In `claude -p` the turn then never ends, and when the turn is stopped the server dies with it. The helper owns the server for exactly as long as the capture runs and leaves nothing running.
5. **Why the Chrome flag stays.** On a Mac, Google Chrome copies its whole app (about 1.4 GB) into a temp folder on every launch and deletes the copy only when quit normally, so each screenshot without `--disable-features=MacAppCodeSignClone` can leave one behind. The flag is in every command above. Headless Chrome also screenshots `file://` URLs, which is how you look at the built review page itself (step 4). The Chrome browser extension tools are a last resort, and only when connected: if every call fails with "not connected", stop retrying.

**Match the live wording.** Local test data drifts from what editors have since changed on the live site, so a local screenshot can show different text than the user is looking at. Bring the real live text into the local copy before capturing, or the "before" pane won't match the picture in the user's head.

**Only when the app cannot run** (the helper exits 3 or 4 and you cannot fix it, or the project has no way to run), a committed screenshot may stand in. Then:

- Take its date from `git log -1 --format=%cs -- <file>`, and write in that item's Reason: "committed screenshot, last changed YYYY-MM-DD".
- Tell the user in chat, and on the review page, that the "before" is a committed screenshot and not the live page, with why the app could not run.

Screenshot each in-scope section at whichever viewport width(s) matter for this review (desktop, mobile, or both). The builder embeds each one as a data URI (step 4): no external image hosting, which keeps the page self-contained wherever it is opened.

There is no mandatory standing-audit section here (unlike a copy review's compliance step). If something accessibility- or readability-related comes up, raise it inline as a normal item's Reason, not as a separate always-on section.

### 3. Turn the redesign brief into discrete numbered items

Each item is one section or component:

- Give it 1-3 coded mockup variants: real HTML/CSS built from the target page's own fonts, colors, and spacing (the same "reuse the target page's own design system" principle as a copy review), not AI-generated images and not a text diff.
- A single-variant item works exactly like a copy-edit item: no gallery needed, just Original vs. the one proposed variant. Its accept button reads "Use Proposed", not "Use Selected": with nothing selectable, "Use Selected" reads as a control the reviewer has failed to find. The builder does this for any item without `variants`.
- Give every item a **Reason** and a **Recommended / Not Recommended** badge, the same convention as a copy review: your own honest judgment, independent of whether you present the item at all.

### 4. Build the review page with the shared builder

**Needs the whole plugin.** This skill reads shared files at `../../reference/` and `../../shared/`, relative to its folder. If they are missing, the skill was copied on its own: install the whole plugin (`/plugin install proofs@proofs`) rather than recreating them.

Write the content; the builder writes the page. Read `../../reference/review-page.md` first: it documents the spec and the command, `python3 ${CLAUDE_PLUGIN_ROOT}/shared/review_page/review_page.py spec.json --out page.html`, with `"decisions": "design-review"`. Do not hand-write the page's JavaScript. Follow any design guidance your environment provides for published pages: "utilitarian but polished," not a landing page. Fill `project` with `name`, `session` and `repo`, taking the session name the way the `working-log` skill does (the session's own name, else one named for the work, kept for the life of the page): the page's header shows the proofs mark, this skill's name, the project and the session, so the user can match the page to its session at a glance.

- **Reuse the target page's own design system** for the mockups (the spec's `css`). Read the project's style guide for its colors and fonts, including dark mode if it has one, rather than trusting a list in this skill, and build against its tokens so the mockups render correctly in every theme the site supports. Give mockup panes their own explicit background rather than letting them inherit the review page's. If the project deliberately darkened its grays to pass contrast, don't "fix" a mockup by reaching back to stock framework grays.
- **Fonts and images.** Review pages cannot load web fonts from a font service, so download the real fonts (the `woff2` weights you need) and list them in `assets`, then point `@font-face` at them from `css` with `src: url({{asset:name}}) format('woff2')`. **Never paste a font's base64 into the spec**: one 22 KB font is about 28,000 tokens, while an asset costs none. Put photos and the before screenshot in `assets` too. The builder embeds every asset **once**, however many mockups use it, and converts PNG and JPEG screenshots to WebP with a PNG or JPEG fallback for older Safari (`image_quality`, `image_max_width`; see the builder reference). Style a screenshot `<img>` by class, not with a `>` child selector: the builder wraps it in a `<picture>`.
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

**Verify before publishing, every time and not just the first.** The build runs its own check (script syntax, card and button counts). Run `--smoke`. If it reports Playwright missing, run the one-line install it prints (it uses your installed Google Chrome and downloads no browser), then run `--smoke` again; if it still cannot run, say on the page and in chat that the self-check did not run. Then screenshot the page at a desktop and a phone width and check your coded mockups don't add sideways scroll or overlap. Only publish after all of it passes.

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
