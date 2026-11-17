---
name: style-guide
version: 1.5.2
description: Use when the user wants to review and codify design/style consistency across the whole site (type scale, spacing, color, icon-header layout, card style, hero headers, disclaimer placement) rather than one page at a time — audits pages/templates for existing and candidate conventions, builds an interactive Artifact review with a 4-state decision model (Deny / Request Revision / Accept - Apply Everywhere Now / Accept - Record for Later), and persists accepted rules into a committed, re-publishable docs/style-guide.html that both the user and future Claude sessions consult.
---

# Style Guide Tool

A human-in-the-loop process for auditing and codifying design consistency across an entire site, not one page at a time. Sibling tool to `article-copy-edit` and `design-review`: same Artifact-review loop, but the output is a persistent, living document instead of a one-shot set of edits.

## Why this exists

Artifacts can't send live clicks back into the conversation; there's no channel from a button in the rendered page back to Claude. So the loop is the same as the sibling tools': build a review page, the user picks a decision per item, clicks "Copy My Decisions", pastes the plain-text summary back into chat, and Claude applies exactly what was decided.

What's different here: the review isn't scoped to one page, and a decision isn't a one-time edit. Each accepted item becomes a permanent rule in `docs/style-guide.html`, and the tool is meant to be re-run periodically. Each run reads what's already decided and only proposes what's new or still inconsistent.

## When to use

The user wants to establish or ratify a site-wide design convention, points out the same kind of inconsistency recurring across multiple pages, or asks for something like this tool ("a style guide") by name. Not for a single page's redesign; that's `design-review`.

## The process

### 1. Read the current guides first

If the project **already has a written style guide** (a Markdown file in `docs/`, a design-tokens file, or one linked from `CLAUDE.md`), read it first and treat every convention documented there as **already decided**. Don't re-propose those as candidate items in step 2; only ratify one if it surfaces naturally (for example, someone using a hardcoded color instead of the documented token). Many projects arrive with a guide already, and this tool builds on it rather than replacing it.

Then check whether `docs/style-guide.html` exists and has any real content (it may just be the initial stub; see its own header comment). This is the skill's own living, interactively audited guide. If the project also has a hand-written guide, that one stays the plain reference and the `.html` is what this skill builds up and republishes each run. If it has accepted-rule sections already, note each one's category and one-line rule statement so the audit in step 2 doesn't re-propose them either.

### 2. Audit the site for candidate items

Ask the user which folders hold the pages and templates to audit (public pages, signed-in screens, article templates, admin screens), or read the project's notes (`CLAUDE.md`) for a map of them. Scan those for:

- **Typography:** heading sizes, body text size, small-print and label text size, and whether visually similar content uses consistent sizes.
- **Spacing:** section gaps and card padding, specifically whether mobile has its own (smaller) values or inherits a desktop-sized default.
- **Color:** where the site's primary color or documented color tokens are used versus a hardcoded or framework-default color, and semantic color usage (success, warning, error).
- **Components:** icon-header layout (an icon box beside or above a title), badges, pills and chips, cards and panels, hero headers, and any other repeated building block.
- **Disclaimers:** where disclaimer and notice text sits on each kind of page, and whether it is consistent.
- **Dark mode:** if the site has one, check that new components and any third-party widgets are themed for it rather than silently left half-themed. Check, too, that pages deliberately kept light-only are on an explicit exception list.

**Skip anything already scheduled.** If the project's to-do list already has an open item that scopes a change (for example, enlarging fonts across a flow), that's a live, already-scoped change, not a candidate for this audit to re-decide.

For each inconsistency or notable convention not already covered by an existing guide, create a numbered candidate item as one of two kinds:

- **Already-decided:** a pattern this project has already settled on in practice (for example, a fix to how an icon header stacks), presented for ratification: "here's what we already did, confirm it's the official rule." Shows one rendered example (the current, correct version) plus its markup recipe.
- **Undecided:** a real inconsistency with no established winner (for example, competing font sizes for visually similar content). Presented as a recommended option plus 1-2 alternatives, same shape as a `design-review` multi-variant item.

Give every item a **Reason** and a **Recommended/Not Recommended** badge, same convention as the sibling tools.

### 3. Build the review page as an Artifact

Follow any design guidance your environment provides for published pages, same as both siblings.

- **Rendered examples, not screenshots, and not prose either.** Unlike `design-review`, build each example as real coded HTML/CSS using the site's actual classes and tokens, rendered inline in the Artifact, not a screenshot of a live page. The point is to show the underlying recipe next to the visual, which a screenshot can't do. This cuts both ways: never substitute a *description* of the visual difference (for example, a line of text reading "the signup page uses a larger heading than the pricing page") for the difference itself. Class and token names carry no meaning to someone who doesn't read the codebase. Every item, including "current vs. proposed" and multi-variant items, renders the actual compared states side by side (or clearly labeled Before/After) at their real size, color and weight, using real or representative copy from the site. The decision is then "which of these two things I'm looking at do I prefer," never "which of these two labels do I prefer."
- **Clickable category filter tabs.** For any round past a handful of items, render the category list (Typography, Spacing, Color, and so on, plus a live count per category) as clickable filter buttons near the top, not just static section headers. Clicking one scrolls to or isolates that category, so reviewing a big audit doesn't require scrolling past everything. Keep the section headers too; the tabs are a navigation aid on top of them, not a replacement. Only list categories that actually have an item in this round.
- **Colored category chips.** Give each category its own distinct badge color, reused consistently for that category's chip on every item and on its filter tab. It makes scanning a long round by eye much faster than uniform-colored labels.
- **A decision-state legend**, once near the top of the page (not per item): a small key mapping each of the four decision colors (Deny, Revise, Accept-now, Accept-later) to its meaning, so the color-coded progress bar and per-item button states stay legible without re-reading the button row on every item.
- **A light/dark preview switch whenever the site has both themes.** A small toggle near the top flips every rendered example between the site's light and dark values, independent of the review page's own chrome theme (which stays on its own light/dark handling, unaffected by the toggle). This matters because several real inconsistencies are dark-mode-only contrast bugs a reviewer can't judge from seeing the recipe in one theme. A site with only one theme doesn't need the switch.
- **Structure per item:** number + category label + Recommended/Not-Recommended badge, the rendered example(s) (a single example for an already-decided item, a clickable variant gallery for an undecided one), the exact class or markup recipe in a `<code>` block, a Reason block, then the decision bar:

  | Button | Comment box | Meaning |
  |---|---|---|
  | ✕ Deny | optional; a **"Works as Designed"** checkbox sits next to the comment box | Reject the proposed style. Plain deny (checkbox unchecked): nothing recorded, nothing changed, the comment is just a note. With the checkbox checked: the *current, existing* state is recorded as the ratified rule instead of the proposal, a positive confirmation that the status quo is intentional and correct, not silence. Use this when two things that look inconsistent are actually deliberately different (for example, a denser card layout for admins than for customers). The comment becomes that rule's rationale in `docs/style-guide.html`. |
  | ↻ Request Revision | opens, expected | Don't accept as shown; the comment explains what to try instead. Scoped follow-up round next time. |
  | ✓ Accept: Apply Everywhere Now | optional | Record as the official rule AND retrofit every page currently using something else to match it, in the same apply pass. |
  | ✓ Accept: Record for Later | optional | Record as the official rule only. Retrofitting existing pages becomes a new entry in the project's to-do list (or ask where follow-up work should be tracked if the project has no to-do list), not done in this pass. |

  Four buttons, not five. An optional comment box is available on **all four**: leaving it blank on any of them is a plain decision; filling it in on an Accept modifies the recorded rule (and the retrofit, if also applying now); filling it in on Deny is just a reason unless "Works as Designed" is checked, in which case it's the rule's rationale. There's no separate "Approve with Comment" button competing with the Accepts, and no separate "Confirm as Designed" button competing with Deny.

- **Sticky bottom bar:** running "X of N reviewed" + a tally per state + "Copy My Decisions", same mechanism as the siblings (`navigator.clipboard.writeText`). If the clipboard is missing or the write fails, show the summary in a selectable text box (select all) instead, and never show "Copied" on failure. Export format, first line identifying the review:
  ```
  [Style Guide Audit — 2026-01-15]
  1. Body text size on disclaimer notes — ACCEPT (Apply Everywhere Now)
  2. Section spacing on landing pages — ACCEPT (Record for Later)
  3. Icon-header layout — ACCEPT (Apply Everywhere Now) — COMMENT: also apply to the account settings page
  4. H2 size on plain articles vs templated ones — REVISE — COMMENT: try matching the templated size instead of splitting the difference
  5. Hero header color — DENY
  6. Customer vs. admin card density — DENY (Works as Designed) — COMMENT: two audiences with genuinely different density needs, not drift
  ```
  Omit the `— COMMENT: ...` suffix for items with no comment. An item the user never decided on simply doesn't appear in the pasted export at all (nothing to copy): its number is absent, not present as a `PENDING` line. Step 4's apply logic treats any number missing from the summary as still pending.

Publish with the `Artifact` tool, same file path across revisions of the same audit round.

**Verify before publishing, every time.** Same requirement as both siblings:
1. Extract the contents of the page's `script` element and run `node --check` on it.
2. Load the file in a headless browser (Playwright or similar), assert the expected item count rendered, click through a decision (including selecting a variant, for an undecided item) on at least one already-decided and one undecided item, and confirm page errors came back empty.
3. Screenshot the Artifact page itself and check the coded examples don't introduce unintended horizontal scroll or overlapping elements.

Only publish after all three pass.

### 4. Applying the decisions

When the user pastes back the summary, match items by number.

- **`ACCEPT (Apply Everywhere Now)`**: retrofit every matching page or template immediately, in this session, folding in any comment first. Then write the rule into `docs/style-guide.html` (step 5).
- **`ACCEPT (Record for Later)`**: write the rule into `docs/style-guide.html` only (step 5), folding in any comment first. Add a new entry to the project's to-do list (or ask where follow-up work should be tracked if the project has no to-do list) describing the retrofit that's now owed (which pages, what the rule is), so it has a path to ever getting done, not just a line in a document.
- **`DENY`**: leave everything untouched. A comment here is a note or reason, not an instruction to act on.
- **`DENY (Works as Designed)`**: leave the code untouched (there's no proposed change to apply; the existing states ARE the rule), but do write a rule into `docs/style-guide.html` (step 5) documenting that the current, possibly multiple-looking states are each intentional, using the comment as the rationale. This is the one Deny variant that still produces a style-guide entry.
- **`REVISE`**: leave everything untouched for now; the comment is feedback for a follow-up round (step 7).
- **`PENDING`**: not reviewed yet; leave untouched.

### 5. Persisting to `docs/style-guide.html`

For every accepted rule (either Accept flavor), add or update its own section under the matching category heading (Typography / Spacing / Color / Components), each containing: the rendered example, the exact class or markup recipe in a `<code>` block, and a one-line rule statement. If `docs/style-guide.html` doesn't exist yet, create it on the first accepted rule, starting with its header comment (`<!-- artifact-url: <the published URL, once there is one> -->`) followed by the page itself. Keep the file's own leading HTML comment (`<!-- artifact-url: ... -->`, see the file's header) up to date if the Artifact URL ever changes. It shouldn't, since this file always republishes to the same URL.

Commit the file following the project's own notes (`CLAUDE.md`). Republish it as an Artifact to that same recorded URL so there's always a live, visual, browsable copy in sync with the committed one.

### 5b. Optional: serve the guide at an unlinked address on the live site

This step is **optional and opt-in. Never set it up without the user's explicit approval.** Ask first, and do nothing if the answer isn't a clear yes. It makes the guide public on the real domain, so it is the user's call.

If they approve: serve the committed `docs/style-guide.html` from the site itself at a hidden address (for example, a path named styleguide). It's public (no sign-in) but not linked from any menu, so only people with the link find it. Have the route read the committed file straight off disk and render it with no layout, so committing the file (step 5) is the only publish step the route ever needs. It always shows whatever is currently committed.

- **Several guides:** if the project has sub-components with their own guides that intentionally diverge (say, an admin area and a customer area), keep a small mapping from a URL prefix to a file path, with one default entry for the bare address.
- **Reserved names:** if the project has a catch-all route keyed off a single URL segment (a public profile by username is the common case), add `styleguide` to whatever reserved-word list guards it, so no user can claim that name. If there's no such catch-all, there's nothing to add.

Use the project's own framework conventions to add the route; follow its notes for how.

### 6. Enforcement

Check that the project's own instructions file (`CLAUDE.md` or the equivalent) actually points future work at the style guide(s): `docs/style-guide.html`, plus any hand-written guide. **Don't assume it does.** When this skill is brought into a new project, that pointer is usually missing, and without it future sessions never consult the guide. If it's missing, propose adding it and wait for the user's go-ahead, since that file is theirs.

### 7. Follow-up rounds on `REVISE` items

Identical pattern to the sibling tools: scope the new Artifact to only the still-open items (every item without a final decision, not just the explicitly revised ones), carry the prior round's proposal forward on each card labeled "Round N," republish to the same URL, and re-verify before every republish. If a prior round's already-decided item is worth keeping visible for context (for example, it's near a new item covering related ground), render it visually de-emphasized (reduced opacity, say) rather than omitting it or presenting it as open again. It's there for continuity, not re-review.

## Where the page goes

The project chooses with `PROOFS_PAGES`, set in the project's `.claude/settings.json` "env" block (or a line in CLAUDE.md: "proofs pages: file"). Values:

- `artifact`: publish as a private claude.ai artifact (a link that opens on phone and computer). This is the default when publishing is available.
- `file`: save the page as an HTML file (default folder `.proofs/pages/`; add it to .gitignore) and open it in the browser (`open` on macOS, `xdg-open` on Linux, `start` on Windows). This is the default when artifacts are not available. Reuse the same file path for later rounds so the page updates in place instead of piling up.
- `wifi`: same as `file`, plus serve only a folder that holds this review's page(s) (for example `.proofs/pages/<review-name>/`, so older pages are not listed to the network) on the local network (`python3 -m http.server <port> --bind <the computer's local IP>` from that folder) and print the address so a phone on the same Wi-Fi can open it. This mode never uploads the page and never uses a public tunnel. Stop the server when the review is done. Use `wifi` only on a private network you trust, never on public or shared Wi-Fi.

If `artifact` is chosen but publishing fails or is not available, fall back to `file` and say so in one line. Everything on the page works the same in every mode. The page's copy button gives the user text to paste back. Copy buttons must fall back to a selectable text box (select all) when `navigator.clipboard` is missing or the write fails (a page served over http on a local IP is not a secure context, so the clipboard is often unavailable), and must never show "Copied" unless the copy actually succeeded.

## Changelog

- **1.5.2** (2026-11-17): Copy buttons now fall back to a selectable text box when the clipboard is unavailable (as on a Wi-Fi-served page), and `wifi` mode is limited to a private network you trust.
- **1.5.1** (2026-11-16): New section "Where the page goes": a project can choose an artifact, a local file, or a file served on its own Wi-Fi.
- **1.5.0** (2026-11-16): Merged into proofs: generic, no project-specific steps.
