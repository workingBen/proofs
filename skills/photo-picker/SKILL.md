---
name: photo-picker
version: 1.0.3
description: Use when the user wants to source and add real photos to an article/page and review candidates before anything is applied — builds an interactive Artifact gallery of real, appropriately-licensed candidate images per "slot" (a spot in the content that needs a photo), with the same four decision states as article-copy-edit and design-review (Keep None / Use Selected / Approve with Comment / Request Revision, where Revision means "search again, different direction"), a "Copy My Decisions" export, and an apply step that uploads the winning image to your image host and wires the URL into the real page.
---

# Photo Picker Tool

A human-in-the-loop process for sourcing and adding real photos to an article or page. Instead of guessing at one image per spot and dropping it in, or describing candidates in chat, build an interactive gallery the user browses and clicks through, then apply only what they picked. Sibling tool to `article-copy-edit` and `design-review`: same underlying loop, adapted for photo curation instead of text or layout.

## Why this exists

Artifacts can't send live clicks back into the conversation, the same constraint as the other two tools. So the loop is identical: build a review page, the user picks a decision per slot (optionally with a comment), the user clicks "Copy My Decisions", pastes the plain-text summary back into chat, and Claude applies exactly what was approved to the real page.

What's different from `design-review`'s variant gallery: the thing being compared isn't coded mockups of the same idea, it's genuinely different real photographs, sourced from the open web, for a spot that currently has no image (or an unrelated placeholder). Verification also has a distinctive failure mode this tool needs to guard against that the other two don't: a broken or hotlink-blocked image URL, which fails silently (blank box, no visible error) unless explicitly checked for.

## When to use

The user wants to add or replace photos on a specific article/page and wants to review real candidates before anything is applied, rather than have Claude unilaterally pick one. Signals: they ask "can you find some photos for X," ask for options before adding an image, or ask for something like this tool by name.

## The process

### 1. Identify the image "slots"

A slot is one spot in the content that needs a photo: a section, a topic, a mood. For each slot, note what it's illustrating and any framing constraints already established on the site (for example, an existing photo used elsewhere for the same subject that should be reused for consistency). This follows the "reuse the target page's own design system" principle the other two tools use for copy and layout: reuse the site's own existing photography where a real match already exists, rather than sourcing something new that duplicates it.

### 2. Source real candidates, always verified before presenting

- Use free-license stock sources (Pexels, Unsplash) for general photography; Open Library's cover API (`https://covers.openlibrary.org/b/olid/{OLID}-L.jpg`) or a publisher's own official cover CDN for book covers; the project's own image folder for reuse candidates.
- **Download and visually inspect every candidate with the Read tool before presenting it as an option.** A URL that returns 200 is not proof the image is right. Confirm it's actually the right subject, right book edition, right orientation, not a broken or placeholder image, by looking at it.
- Always disclose source and reuse-vs-new status per candidate (e.g., "already on site, reused from the pricing page" vs. "new, via Pexels").
- 1-3 candidates per slot is normal; a slot can have just one if nothing else is a real contender. Don't pad for the sake of options.

### 3. Build the review page as an Artifact, styled like the target page

Follow any design guidance your environment provides for published pages first. Utilitarian-but-polished register, same as the other two tools: this is a review tool, not editorial content.

- Reuse the target page's own design system (palette, type) where one exists.
- **Structure per slot:** slot title + short context note (what it's illustrating) + a **photo gallery**: clickable cards, one per candidate, each showing the image, a label (Option A/B/C), a note (source + framing rationale), and an "Already on site" badge where applicable. Clicking a card marks it selected (same click-to-select interaction as `design-review`'s variant gallery).
- Below the gallery, the same shared four-button action bar from the other two tools. Use plain text labels (or monochrome line icons), not emoji:

  | Button | State | Comment box | Meaning |
  |---|---|---|---|
  | Keep None | `deny` | optional | Don't add a photo to this slot. |
  | Use Selected | `accept` | optional | Add the currently-selected candidate exactly as shown. |
  | Approve with Comment | `accept-comment` | opens, expected | Add the selected candidate, but modify per the comment (e.g. crop, caption, placement). |
  | Request Revision | `revise` | opens, expected | None of these work. The comment explains what to try instead (different subject, different mood, different source); expect a follow-up round searching again for this slot. |

  For a multi-candidate slot, the action bar acts on whichever candidate is currently selected in the gallery.

- **Sticky bottom bar:** running "X of N reviewed" + tally per state + "Copy My Decisions" button writing a plain-text numbered summary via `navigator.clipboard.writeText`. If the clipboard is missing or the write fails, show the summary in a selectable text box (select all) instead, and never show "Copied" on failure. **The export's first line must identify the gallery being reviewed**, same convention as `article-copy-edit` and `design-review`: pasted decisions arrive back in chat with no other context, and a bare `1. ... — ACCEPT` is ambiguous once more than one review is in flight (or, for this tool specifically, once a gallery spans multiple articles' slots the way the worked example below does, since the slot labels alone don't say which gallery they came from). Use a stable bracketed header matching the Artifact's own title:
  ```
  [How-To Guides — Photo Picker]
  1. Article One — Introduction section — ACCEPT (Use Selected: Option B, trail map)
  2. Article Two — Sourdough Bread — ACCEPT WITH COMMENT — COMMENT: crop tighter on the loaf, less background counter
  3. Article Two — Proofing Basket — DENY (Keep None)
  4. Article Three — Chain Repair — REVISE — COMMENT: too staged, find something that looks more like a real workshop
  ```
  Omit the `— COMMENT: ...` suffix for plain `ACCEPT`/`DENY` items with no comment.

Publish with the `Artifact` tool. Use a stable icon across revisions of the *same* review page: redeploy to the same file path for new rounds or added candidates, don't mint a new URL for a gallery the user is already looking at.

**Verify before publishing, every time.** Same script-syntax risk as the other two tools, plus this tool's own distinctive failure mode:
1. Extract the `<script>...</script>` contents to a `.js` file and run `node --check` on it.
2. Load the file in headless Playwright, assert the expected card/slot count rendered, click through a selection + decision on at least one slot, confirm `page.on('pageerror', ...)` came back empty.
3. **Explicitly check every embedded image actually loaded**: `page.$$eval('img', els => els.map(i => ({ complete: i.complete, natW: i.naturalWidth })))` and confirm every entry has `complete: true` and `natW > 0`. A broken image source renders as a blank box with no console error. This is the one failure mode unique to this tool, so check for it by name rather than assuming a clean `pageerror` log means the images are fine.

Only publish after all three pass. Embed images as base64 `data:` URIs directly in the HTML (download, verify with Read, base64-encode via a script, inject via placeholder replacement). The Artifact CSP blocks external image requests, and this also keeps large base64 blobs out of the conversation context. Downscale each image before embedding so the page stays well under the Artifact size limit, and do not commit the finished review page to the repository.

**Define a dark-theme override for every semantic color token, not just the base palette.** The first real use of this tool defined its amber tokens (used for the "revision requested" comment box and status pill) only in `:root`, with no `@media (prefers-color-scheme: dark)` or `:root[data-theme="dark"]` override, unlike the background, ink and accent tokens, which all got proper dark variants. In dark mode, the comment box's background stayed the light-mode pale yellow while its text color (the page's ink token, correctly following the theme) flipped to near-white, making the user's own revision note unreadable. The user caught it from a live screenshot. Fix: give every semantic-state color (amber for revise, and by the same logic red or blue for deny or comment if they're ever used for a filled text-bearing surface, not just a pill background) an explicit dark-mode pair, and use a dedicated ink token for text sitting on that surface (e.g. `--amber-ink`) rather than the page's general ink. A filled colored box needs its own contrast-safe text color independent of the page's light/dark state, not the page's own foreground color.

### 4. Applying the decisions

When the user pastes back the copied summary, match items by number.

- **`ACCEPT`**: download the selected candidate (if not already downloaded during sourcing), upload it to your image host using the project's established convention (the folder or naming scheme its notes name, overwriting rather than duplicating when the same image is re-uploaded), and wire the resulting URL into the real article/page content at that slot. If the project has no image host yet, ask the user where images should live before uploading anything.
- **`ACCEPT WITH COMMENT`**: same, but the comment modifies the result first (crop, caption, alt text, placement). Work out what the final placement should be, then apply that.
- **`DENY`**: leave the slot without a photo. A comment here is a note, not an instruction to act on.
- **`REVISE`**: add nothing yet. The comment is feedback for a follow-up round (see below).
- **`PENDING`**: not reviewed yet; leave untouched.

Rebuild, verify and commit per the project's normal workflow.

### 5. Follow-up rounds on `REVISE` items

Identical pattern to the other two tools: scope the new Artifact to only the still-open slots, carry the prior round's rejected candidates forward on each card (labeled "Round 1") alongside newly-sourced candidates ("Round 2"), republish to the same URL, and re-run the full verification step (including the per-image load check) before every republish.

## Worked example

Built and applied for three how-to articles (a hiking guide, a bread recipe and a bike-repair walkthrough), 8 slots across the three: a trail map, a summit view, a loaf close-up, a proofing-basket photo (one candidate was the site's own existing photo, reused for consistency), a flour-and-tools photo, a workshop photo, and a repair-stand photo. The static, non-interactive first draft of this gallery (built before this tool existed as a formal skill) is what prompted formalizing it: the user asked to be able to select or request revisions on it directly, the same way the other two tools already worked, rather than replying in prose.

## Where the page goes

Before you publish or save the page, read `../../reference/where-the-page-goes.md` (the path is relative to this skill's folder). The project's `PROOFS_PAGES` setting picks artifact, file or wifi, and that file says what each means and how copy buttons must fall back.
