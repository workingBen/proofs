---
name: design-review
version: 1.4.1
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

### 2. Capture "before": a real screenshot, not a description

Start the site locally using this project's own start command and port (check the project's notes, `CLAUDE.md`, for how). Free the port first only if a stale process of your own is holding it; never kill a process you did not start. Then poll until the route answers with a 200 before proceeding:

```bash
for i in $(seq 1 20); do code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:PORT/ROUTE); [ "$code" = "200" ] && break; sleep 1; done
```

Take the screenshot with the first of these that the project has:

1. **A browser-automation tool** the project already uses (Playwright or similar). Best: scriptable, repeatable, and it can also measure the page.
2. **Headless Chrome from the command line**, which needs nothing running. Use your platform's Chrome binary with `--headless --hide-scrollbars --virtual-time-budget=8000 --window-size=1200,2200 --screenshot=out.png URL`, then crop the section out with an image tool. It also screenshots `file://` URLs, which is how you look at the built review page itself (step 4).
3. **The Chrome browser extension tools** (open a tab, navigate, resize, screenshot). These need the extension actually connected. If it isn't, every call fails with a "not connected" error and there is nothing you can do about it from here. Don't burn turns retrying; fall back to option 2.

**Rebuild before screenshotting.** If the project compiles its styles (a CSS build step), run that build and restart the server first. Otherwise the screenshot shows the old look and you will review a design that isn't what you built. A stale stylesheet producing a misleading "before" picture happens in every stack.

**Match the live wording.** Local test data drifts from what editors have since changed on the live site, so a local screenshot can show different text than the user is looking at. Bring the real live text into the local copy before capturing, or the "before" pane won't match the picture in the user's head.

Screenshot each in-scope section at whichever viewport width(s) matter for this review (desktop, mobile, or both). The builder embeds each one as a data URI (step 4): no external image hosting, which keeps the page self-contained under the Artifact's content security policy.

There is no mandatory standing-audit section here (unlike a copy review's compliance step). If something accessibility- or readability-related comes up, raise it inline as a normal item's Reason, not as a separate always-on section.

### 3. Turn the redesign brief into discrete numbered items

Each item is one section or component:

- Give it 1-3 coded mockup variants: real HTML/CSS built from the target page's own fonts, colors, and spacing (the same "reuse the target page's own design system" principle as a copy review), not AI-generated images and not a text diff.
- A single-variant item works exactly like a copy-edit item: no gallery needed, just Original vs. the one proposed variant. Its accept button reads "Use Proposed", not "Use Selected": with nothing selectable, "Use Selected" reads as a control the reviewer has failed to find. The builder does this for any item without `variants`.
- Give every item a **Reason** and a **Recommended / Not Recommended** badge, the same convention as a copy review: your own honest judgment, independent of whether you present the item at all.

### 4. Build the review page with the shared builder

Write the content; the builder writes the page. Read `../../reference/review-page.md` first: it documents the spec and the command, `python3 ../../shared/review_page/review_page.py spec.json --out page.html`, with `"decisions": "design-review"`. Do not hand-write the page's JavaScript. Follow any design guidance your environment provides for published pages: "utilitarian but polished," not a landing page.

- **Reuse the target page's own design system** for the mockups (the spec's `css`). Read the project's style guide for its colors and fonts, including dark mode if it has one, rather than trusting a list in this skill, and build against its tokens so the mockups render correctly in every theme the site supports. Give mockup panes their own explicit background rather than letting them inherit the review page's. If the project deliberately darkened its grays to pass contrast, don't "fix" a mockup by reaching back to stock framework grays.
- **Fonts and images.** Review pages cannot load web fonts from a font service, so download the real fonts (the `woff2` weights you need) and embed them as `@font-face` data URIs in `css`. Put photos and the before screenshot in `assets`, so each is embedded **once** and referenced from every mockup that uses it.
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

Publish with the `Artifact` tool. Redeploy to the same file path across revisions of the *same* review page; don't mint a new URL for revisions the user is already looking at.

**Verify before publishing, every time and not just the first.** The build runs its own check (script syntax, card and button counts); run `--smoke` too when Playwright is available. Then screenshot the page at a desktop and a phone width and check your coded mockups don't add sideways scroll or overlap. Only publish after all of it passes.

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
