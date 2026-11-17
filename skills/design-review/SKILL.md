---
name: design-review
version: 1.3.2
description: Use when the user wants to review a visual/layout design change to a page before it's built — builds an interactive Artifact showing the current live page (real screenshot) against 1-3 coded mockup variants per section, with the same four decision states as article-copy-edit (Keep Original / Use Selected / Approve with Comment / Request Revision), a Reason and Recommended/Not Recommended badge on every item, and a "Copy My Decisions" export the user pastes back to drive translating the approved mockup into the real view.
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
2. **Headless Chrome from the command line**, which needs nothing running. Use your platform's Chrome binary with `--headless --hide-scrollbars --virtual-time-budget=8000 --window-size=1200,2200 --screenshot=out.png URL`, then crop the section out with an image tool. It also screenshots `file://` URLs, which is how you verify the built review page itself (step 4).
3. **The Chrome browser extension tools** (open a tab, navigate, resize, screenshot). These need the extension actually connected. If it isn't, every call fails with a "not connected" error and there is nothing you can do about it from here. Don't burn turns retrying; fall back to option 2.

**Rebuild before screenshotting.** If the project compiles its styles (a CSS build step), run that build and restart the server first. Otherwise the screenshot shows the old look and you will review a design that isn't what you built. A stale stylesheet producing a misleading "before" picture happens in every stack.

**Match the live wording.** Local test data drifts from what editors have since changed on the live site, so a local screenshot can show different text than the user is looking at. Bring the real live text into the local copy before capturing, or the "before" pane won't match the picture in the user's head.

Screenshot each in-scope section at whichever viewport width(s) matter for this review (desktop, mobile, or both). Embed each screenshot as a base64 data URI directly in the Artifact HTML: no external image hosting, which keeps the page self-contained under the Artifact's content security policy.

There is no mandatory standing-audit section here (unlike a copy review's compliance step). If something accessibility- or readability-related comes up, raise it inline as a normal item's Reason, not as a separate always-on section.

### 3. Turn the redesign brief into discrete numbered items

Each item is one section or component:

- Give it 1-3 coded mockup variants: real HTML/CSS built from the target page's own fonts, colors, and spacing (the same "reuse the target page's own design system" principle as a copy review), not AI-generated images and not a text diff.
- A single-variant item works exactly like a copy-edit item: no gallery needed, just Original vs. the one proposed variant. **Label its accept button "Use Proposed", not "Use Selected".** With nothing selectable, "Use Selected" reads as a control the reviewer has failed to find, and they hesitate over whether their approval registered. The state is still `accept`; only the wording changes.
- Give every item a **Reason** and a **Recommended / Not Recommended** badge, the same convention as a copy review: your own honest judgment, independent of whether you present the item at all.

### 4. Build the review page as an Artifact, styled like the real page

Follow any design guidance your environment provides for published pages. This is a UI/tool, not editorial content: "utilitarian but polished," not a landing-page treatment.

- **Reuse the target page's own design system** for the mockups themselves. Read the project's style guide for its colors and fonts, including dark mode if it has one, rather than trusting a list in this skill. Build mockups against the project's own tokens so they render correctly in every theme the site supports, not just whichever one was active in the "before" screenshot. The Artifact itself is theme-aware, so give mockup panes their own explicit background rather than letting them inherit the review page's. If the project deliberately darkened its grays to pass contrast, don't "fix" a mockup by reaching back to stock framework grays that fail contrast.
- **Fonts and images.** Review pages cannot load web fonts from a font service, so a mockup left to fall back to a default font isn't showing the real design. Download the real fonts (the weights you need, the `woff2` files) and embed them as `@font-face` data URIs. Do the same for photos and the before screenshot, but embed each one **once**: put it in a CSS custom property on `:root` and reference the property, so an asset used in several mockups is not embedded once per use.
- **Structure per item:** number + location label + Recommended/Not-Recommended badge + status pill, the before screenshot, then either a single "proposed" pane (one variant) or a **variant gallery** (2-3 variants): clickable cards that mark the current selection. Below that, a Reason block, then the shared four-button action bar:

  | Button | State | Comment box | Meaning |
  |---|---|---|---|
  | ✕ Keep Original | `deny` | optional | Reject all variants, keep the current design. |
  | ✓ Use Selected (✓ Use Proposed, single-variant) | `accept` | optional | Ship the currently-selected variant exactly as shown. |
  | ✓ Approve with Comment | `accept-comment` | opens, expected | Ship the selected variant, but modify per the comment. |
  | ↻ Request Revision | `revise` | opens, expected | Don't ship anything yet. The comment explains what to try instead; expect a follow-up round on this item. |

  For a multi-variant item, the action bar acts on whichever variant is currently selected in the gallery; clicking a different variant before deciding is one click, not a separate step.

- **Mark the selection with a border, never a fill.** A selected variant card gets a border, a check mark, or a tinted edge, and must never take a solid background color. The mockup lives inside that card, and a strong fill competes with the very thing being reviewed, which is the one job the page has.

- **Open decisions go first. Always.** The things needing a decision this round sit at the top of the page, above any recap, carried-forward context, or already-settled material. A reviewer should never have to scroll past things they have already read to reach the first open item. Recap belongs below the decisions, or in a collapsed block.

- **Every item carries a "Mark as read" switch**, independent of its decision buttons. Read state is included in the "Copy My Decisions" export as a `READ` marker on the line. **On the next round, drop every item marked read**: do not render it again, not even dimmed. Carrying context forward applies to the *open* item's own history (Round 1's rejected proposal on the Round 2 card), not to items the reader has finished with.

- **Sticky bottom bar:** running "X of N reviewed" + a tally per state + a "Copy My Decisions" button that writes a plain-text numbered summary to the clipboard via `navigator.clipboard.writeText`. If the clipboard is missing or the write fails, show the summary in a selectable text box (select all) instead, and never show "Copied" on failure. **The export's first line must identify the page being reviewed**: pasted decisions arrive back in chat with no other context, and a bare `1. ... — ACCEPT` is ambiguous once more than one review is in flight. Use a stable bracketed header matching the Artifact's own title, and include the selected variant letter for multi-variant items:

  ```
  [Articles Index — Design Review]
  1. Article card layout — ACCEPT (Use Selected: Variant B)
  2. Read More button placement — ACCEPT WITH COMMENT — COMMENT: keep the button but make it teal, not amber
  3. Header spacing fix — REVISE — COMMENT: still too much white space, try tightening further
  4. Footer redesign — DENY
  5. Sidebar links — ACCEPT (Use Proposed) — READ
  ```

  Omit the `— COMMENT: ...` suffix entirely for plain `ACCEPT`/`DENY` items with no comment.

Publish with the `Artifact` tool. Redeploy to the same file path across revisions of the *same* review page; don't mint a new URL for revisions the user is already looking at.

**Verify before publishing, every time and not just the first.** A single bad escape in hand-authored JavaScript can silently kill the entire script, leaving a structurally fine page with nothing clickable and no visible error. Before publishing:

1. Extract the `<script>` contents to a `.js` file and run `node --check` on it.
2. Drive the built file through a real DOM, in whatever browser or DOM tool the project has (a headless browser, or jsdom installed into a scratch folder). Stub `navigator.clipboard.writeText` to capture the export, collect `window` `error` events and `console.error` calls, then assert: the expected item, variant and card counts rendered; choosing a variant moves the selection (`aria-pressed`); each decision button sets the right state and opens the comment box where it should; the "Mark as read" switch writes the `READ` marker; and the exported text has the right header, variant letter, and comment suffix. Assert the error list is empty last.
3. Screenshot the review page itself and check the coded mockups don't introduce unintended horizontal scroll or overlapping elements. A mockup is only useful if it renders cleanly on its own terms.

Only publish after all three pass.

### 5. Applying the decisions

When the user pastes back the copied summary, match items by number (and variant letter, where relevant).

- **`ACCEPT`**: translate the selected variant's markup into the real view or template. This is *not* a paste-in the way a copy edit is: the mockup used static stand-in content (a hardcoded example title and image) previewing what a loop over live records will render, so applying it means adapting the chosen structure and styling into the real template, wiring in loops, real image URLs and real data, not copying the mockup's HTML verbatim.
- **`ACCEPT WITH COMMENT`**: same translation, but the comment modifies the result first. Work out what the final design should be from the comment, then build that into the real view.
- **`DENY`**: leave the file untouched. A comment here is a note or reason, not an instruction to act on.
- **`REVISE`**: leave the file untouched for now; the comment is feedback for a follow-up round (see below), not an instruction to apply anything yet.
- **`PENDING`**: not reviewed yet; leave untouched.

Then rebuild styles if the project compiles them, verify against a real render, and commit following the project's own notes. The review tool changes nothing about how the actual change gets verified and shipped.

### 6. Follow-up rounds on `REVISE` items

Scope the new Artifact to only the still-open item(s). Carry the prior round's rejected proposal forward on each card (clearly labeled "Round 1," "Round 2," etc.) alongside the new one, republish to the same URL, and re-run the full verification step before every republish; a smaller page is not a lower-risk page. Items the reader marked read are dropped, not carried.

## Worked example

A review of a tab row on a mobile measurement screen: the row overflowed on a phone with no wrap or active state, and the list below never filtered by type. Two rounds:

- **Round 1**: one proposed variant per concern (layout, active state, filtered list) plus a first pass at a new "see all" modal. The reviewer accepted the tab-row item outright; the modal trigger was sent back ("too much whitespace next to the button") with a request for several genuinely different options, since there was no preference to start from.
- **Round 2**: scoped to just the still-open modal trigger, with four real alternatives (grid tile, icon-only button, plain text link, list-header link) instead of one refined guess. The list-header link was accepted.

What made this work, worth repeating:

- **Test the review page's own buttons by measuring, not by eye.** Round 1 shipped a mobile/desktop width toggle that looked fine but did nothing: the two-up gallery capped each preview's rendered width below the breakpoint it needed to cross. It was caught by measuring the element's bounding box before and after the click in a headless browser. Round 2 replaced the toggle with fixed-width mobile and desktop frames side by side (in their own `overflow-x: auto` container, so the page body never scrolls sideways), leaving no interaction to silently fail.
- **"I don't have a good option, show me a few" is itself a valid Round 2 request.** The reviewer doesn't have to know what they want. REVISE with a vague comment is exactly what a follow-up round is for, and four distinct answers served better than refining one guess in place.
- **Show the rejected first-round idea dimmed.** Round 1's proposal stayed on the same card as Round 2's new options, visually de-emphasized (dimmed, dashed border): enough context to see what changed without competing with the live decision.

## Where the page goes

The project chooses with `PROOFS_PAGES`, set in the project's `.claude/settings.json` "env" block (or a line in CLAUDE.md: "proofs pages: file"). Values:

- `artifact`: publish as a private claude.ai artifact (a link that opens on phone and computer). This is the default when publishing is available.
- `file`: save the page as an HTML file (default folder `.proofs/pages/`; add it to .gitignore) and open it in the browser (`open` on macOS, `xdg-open` on Linux, `start` on Windows). This is the default when artifacts are not available. Reuse the same file path for later rounds so the page updates in place instead of piling up.
- `wifi`: same as `file`, plus serve only a folder that holds this review's page(s) (for example `.proofs/pages/<review-name>/`, so older pages are not listed to the network) on the local network (`python3 -m http.server <port> --bind <the computer's local IP>` from that folder) and print the address so a phone on the same Wi-Fi can open it. This mode never uploads the page and never uses a public tunnel. Stop the server when the review is done. Use `wifi` only on a private network you trust, never on public or shared Wi-Fi.

If `artifact` is chosen but publishing fails or is not available, fall back to `file` and say so in one line. Everything on the page works the same in every mode. The page's copy button gives the user text to paste back. Copy buttons must fall back to a selectable text box (select all) when `navigator.clipboard` is missing or the write fails (a page served over http on a local IP is not a secure context, so the clipboard is often unavailable), and must never show "Copied" unless the copy actually succeeded.

## Changelog

- **1.3.2** (2026-11-17): Copy buttons now fall back to a selectable text box when the clipboard is unavailable (as on a Wi-Fi-served page), and `wifi` mode is limited to a private network you trust.
- **1.3.1** (2026-11-16): New section "Where the page goes": a project can choose an artifact, a local file, or a file served on its own Wi-Fi.
- **1.3.0** (2026-11-16): Merged into proofs: generic, no project-specific steps. Includes: open decisions at the top, a "Mark as read" switch per item (read items leave the next round), selection marked with a border rather than a fill, and "Use Proposed" for single-option items.
