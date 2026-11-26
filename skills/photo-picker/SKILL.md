---
name: photo-picker
version: 1.3.4
allowed-tools:
  - Read(/${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/shared/review_page/review_page.py *)
description: Use when the user wants real photos found for an article or page and wants to pick from candidates before any is added, such as "find some photos for this" or "show me options for the hero image". Differs from design-review; it compares sourced, licensed photographs for one spot, not coded layouts, then uploads the winner.
---

# Photo Picker Tool

A human-in-the-loop process for sourcing and adding real photos to an article or page. Instead of guessing at one image per spot and dropping it in, or describing candidates in chat, build an interactive gallery the user browses and clicks through, then apply only what they picked. Sibling tool to `article-copy-edit` and `design-review`: same underlying loop, adapted for photo curation instead of text or layout.

**Results first.** Nothing matters more than a result the user wants. Save tokens by cutting waste, never by cutting a check, an option or a revise pass the result needs (full text: `../../reference/house-rules.md`).

Read the settings: `python3 ${CLAUDE_PLUGIN_ROOT}/shared/settings.py --print` (pre-approved). Use the values it shows wherever this file says *the candidate count*.

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
- Up to the candidates-per-spot setting (default 3) candidates per slot is normal; a slot can have just one if nothing else is a real contender. Don't pad for the sake of options.

### 3. Build the review page with the shared builder

**Needs the whole plugin.** This skill reads shared files at `../../reference/` and `../../shared/`, relative to its folder. If they are missing, the skill was copied on its own: install the whole plugin (`/plugin install proofs@proofs`) rather than recreating them.

Write the content; the builder writes the page. Read `../../reference/review-page.md` first: it documents the spec and the command, `python3 ${CLAUDE_PLUGIN_ROOT}/shared/review_page/review_page.py .proofs/photo-picker/spec.json --out .proofs/pages/<picker-name>.html`, with `"decisions": "photo-picker"`. Do not hand-write the page's JavaScript. Follow any design guidance your environment provides for published pages first; utilitarian-but-polished, same as the other two tools. Fill `project` with `name`, `session` and `repo`, taking the session name the way the `working-log` skill does (the session's own name, else one named for the work, kept for the life of the page): the page's header shows the proofs mark, this skill's name, the project and the session, so the user can match the page to its session at a glance.

- Reuse the target page's own design system (palette, type) where one exists, in the spec's `css`.
- **One item per slot:** `label` (slot title), `location` (what it illustrates), and the candidates as `variants`, each with `name` (a short subject, exported after the option letter), the image, and `note_html` giving its source, framing rationale, and "Already on site" where it is reused. Option labels are A/B/C. Use plain text labels or monochrome line icons, never emoji.
- **Images go in `assets`**, never as external URLs: the Artifact CSP blocks external requests, and an asset placeholder keeps the base64 out of the conversation. Downscale each image before embedding so the page stays well under the Artifact size limit, and do not commit the finished page to the repository.
- The decisions: **Keep None** (no photo in this slot), **Use Selected** (add the selected candidate as shown), **Approve with Comment** (add it, modified per the comment: crop, caption, placement), **Request Revision** (none of these work; the comment says what to search for instead).
- **The export's first line names the gallery**, because pasted decisions arrive with no other context, and a gallery can span several articles' slots. The builder writes the bracketed title:
  ```
  [How-To Guides — Photo Picker]
  1. Article One — Introduction section — ACCEPT (Use Selected: Option B, trail map)
  2. Article Two — Sourdough Bread — ACCEPT WITH COMMENT — COMMENT: crop tighter on the loaf, less background counter
  3. Article Two — Proofing Basket — DENY (Keep None)
  4. Article Three — Chain Repair — REVISE — COMMENT: too staged, find something that looks more like a real workshop
  ```

Deliver the page as "Where the page goes" below says (with `artifact`, that means publishing it with the `Artifact` tool). Use a stable icon across revisions of the *same* review page: redeploy to the same file path for new rounds or added candidates, don't mint a new URL for a gallery the user is already looking at.

**Verify before publishing, every time.** The build runs its own check. `--smoke` also fails on **any image that did not load**: a broken image renders as a blank box with no console error, the one failure mode unique to this tool. Run `--smoke`. If it reports Playwright missing, run the one-line install it prints (it uses your installed Google Chrome and downloads no browser), then run `--smoke` again; if it still cannot run, say on the page and in chat that the self-check did not run. Then open the page and look at every candidate yourself. Only publish after both pass.

### 4. Applying the decisions

When the user pastes back the copied summary, match items by number.

- **`ACCEPT`**: download the selected candidate (if not already downloaded during sourcing), upload it to your image host using the project's established convention (the folder or naming scheme its notes name, overwriting rather than duplicating when the same image is re-uploaded), and wire the resulting URL into the real article/page content at that slot. If the project has no image host yet, ask the user where images should live before uploading anything.
- **`ACCEPT WITH COMMENT`**: same, but the comment modifies the result first (crop, caption, alt text, placement). Work out what the final placement should be, then apply that.
- **`DENY`**: leave the slot without a photo. A comment here is a note, not an instruction to act on.
- **`REVISE`**: add nothing yet. The comment is feedback for a follow-up round (see below).
- **`PENDING`**: not reviewed yet; leave untouched.

Rebuild, verify and commit per the project's normal workflow.

### 5. Follow-up rounds on `REVISE` items

Identical pattern to the other two tools: scope the new Artifact to only the still-open slots, carry the prior round's rejected candidates forward on each card (labeled "Round 1") alongside newly-sourced candidates ("Round 2"), rebuild and republish to the same URL, and re-run the full verification (including the image load check) before every republish.

## Worked example

Built and applied for three how-to articles (a hiking guide, a bread recipe and a bike-repair walkthrough), 8 slots across the three: a trail map, a summit view, a loaf close-up, a proofing-basket photo (one candidate was the site's own existing photo, reused for consistency), a flour-and-tools photo, a workshop photo, and a repair-stand photo. The static, non-interactive first draft of this gallery (built before this tool existed as a formal skill) is what prompted formalizing it: the user asked to be able to select or request revisions on it directly, the same way the other two tools already worked, rather than replying in prose.

## Where the page goes

Before you publish or save the page, read `../../reference/where-the-page-goes.md` (the path is relative to this skill's folder). The project's `PROOFS_PAGES` setting picks artifact, file or wifi, and that file says what each means and how copy buttons must fall back.
