---
name: article-copy-edit
version: 1.2.2
description: Use when the user gives copy-edit feedback (line edits, recommendations) for an article or page and wants to review it human-in-the-loop before anything is applied to the file — builds an interactive Artifact styled like the real page, with a mandatory Claims & Compliance audit as its own first section, four explicit decision states per change (Keep Original / Use Edit / Approve with Comment / Request Revision), a Reason and Recommended/Not Recommended label on every item, a "Copy My Decisions" export the user pastes back to drive the actual file edits, and a scoped follow-up-round pattern for anything marked Request Revision.
---

# Article Copy-Edit Review Tool

A human-in-the-loop process for applying copy-edit feedback to an article or page. Instead of applying edits blind, or narrating each one in chat, build an interactive review page the user reads and clicks through, then apply only what they accepted.

## Why this exists

Artifacts can't send live clicks back into the conversation; there's no channel from a button in the rendered page back to Claude. So the loop is: build a review page, the user picks a decision on each item (optionally with a comment), clicks "Copy My Decisions", pastes the plain-text summary back into chat, and Claude applies exactly the accepted edits (with any comment-driven tweaks) to the real file.

## When to use

The user hands you copy-edit feedback (their own, or a third party's) for a specific article or page and wants to go through it deliberately rather than have you apply it all at once. Signals: they say "let's review this together," paste a batch of proposed edits, or ask for something like this tool by name.

Its sibling, `design-review`, runs the same loop for visual and layout changes. Both use the same four decision states and the same "Copy My Decisions" export.

## The process

### 1. Identify the exact target file and read it in full

Cross-reference quoted "Original" text in the feedback against the real file to find the exact file. Don't guess from a title alone; read enough of the file to confirm every quote actually appears verbatim. Get exact current line numbers and context for each edit location. You need them both for the review page and for applying changes later.

### 2. Run the Claims & Compliance audit: mandatory, always on, first section

First, find out what is risky in this project's field. Look in the project's notes (`CLAUDE.md`) and any existing style or compliance guidance. If neither says, **ask the user once**: "What kinds of claims are risky or regulated in your field?" Health and wellness claims, and environmental or product-safety claims, are only examples. A financial, legal, food, or software site has different ones. Keep the answer in the project's notes so you don't have to ask again.

Then, before turning the user's own feedback into items, do a fresh pass over the **entire current article or page** (not just the lines the feedback happens to touch). Check the project's list of risky claims first, then these general risks:

- **Guarantee or certainty language** ("ensures," "guaranteed," "you only pay for the results you achieve") without a "results vary / not guaranteed" qualifier nearby.
- **Diagnosis, cure, or professional-authority implications**: wording that makes the author or business sound like it diagnoses, treats, or certifies something it has no standing to. Copy should never blur that line.
- **Outcome-tied pricing**, or claims that imply a specific measurable result is promised.
- **Before/after or results content** (photos, case studies, testimonials) with no "individual results vary" or "not typical" disclosure nearby.
- **Missing or unclear disclosure where one is legally required.** In particular, flag any page that recommends products through affiliate links but lacks the disclosure the FTC requires (a clear statement that the site may earn a commission), even if fixing it is out of scope for this particular review.
- **Anything that would read, in isolation, as a claim the page's own disclaimer (if it has one) contradicts.** Titles and headings are the highest-risk spot, since they're what gets pulled into browser tabs, social previews, and search results.

This audit runs **regardless of whether the user's feedback mentions compliance at all**. It's a separate, standing check, not something triggered only when a recommendation happens to raise one.

Findings become their own numbered items in a section titled **"Claims & Compliance"**, always rendered **first**, above the copy-edit and recommendation sections. Include it even if it's empty: show a plain "No compliance concerns found in this pass" state rather than omitting the section, so its absence is visibly a checked box, not a skipped one. Same card structure as every other item (Reason, Recommended/Not Recommended, four decision buttons). A compliance finding being "Recommended" means recommended to fix.

### 3. Turn the feedback into discrete numbered items

Each item is one self-contained change:
- **Line edits** (existing text to proposed text): pull the exact current text from the file, not from the feedback's possibly paraphrased quote of it.
- **New additions** (a whole new section, a call to action, an intro paragraph): "original" is a short italic note describing what's there today (usually "nothing"), "edit" is the proposed new content, and a `where` field says where it would go.
- **Alternatives that conflict** (e.g., two different proposed titles for the same H1): present both as separate items, but say explicitly in each one's reason that accepting it supersedes the other.
- **Non-visual changes** (alt text, meta tags): still get a card, but show the before/after as `<code>` snippets instead of rendered prose.

Give every item, edit or addition alike:
- A **Reason**: why this specific change is an improvement (or why it's proposed despite reservations).
- A **Recommended / Not Recommended** badge: your own honest editorial judgment, independent of whether you're going to present the item at all. If you have a real reservation (compliance risk, factual risk, conflict with established site copy elsewhere), mark it Not Recommended and say why in the reason. Don't silently omit it, and don't silently soften your opinion to make the badge match what you think the user wants to hear. The point of the badge is that the user can see your take before they decide, and overrule it.

### 4. Build the review page as an Artifact, styled like the real page

Follow any design guidance your environment provides for published pages. This is a UI/tool, not editorial content: treat it with the "utilitarian but polished" register, not a landing-page treatment.

- **Reuse the target page's own design system.** Don't invent a new palette; pull colors and type straight from the article or page you're editing. Reuse the site's own before/after colors for "original" and "edit" if it has an established pairing, and make them work in both light and dark mode. That makes the review page's own logic legible for free. If the site themes through CSS variables or tokens, pull the review page's light/dark handling from those same variables instead of inventing a separate scheme.
- **Highlight word-level diffs**, not just whole-paragraph swaps. Wrap the specific changed spans in `<del>`/`<ins>` (or similar) so the user can see at a glance what actually changed, styled in the before/after accent colors.
- **Section order:** Claims & Compliance (always first, always present even if empty), then Copy Edits, then Proposed Additions & Recommendations.
- **Structure per item:** number + location label + Recommended/Not-Recommended badge + status pill, an "Original" pane and an "Edit" pane (rendered in the page's real typography), a Reason block, then **four mutually exclusive decision buttons**. Only one is active per item; all start unselected (pending).

- **The Original and Edit panes always hold the literal, verbatim text, never a paraphrase or a description of the change.** "Reframes the argument around cost instead of speed" is a summary for the Reason block; the Edit pane needs the actual sentence a reader would see if it shipped. This applies even when the source feedback (a third party's notes, an AI review, etc.) only describes a change in prose: write out the real replacement text yourself rather than passing along a description as if it were the edit. A user was once left unable to act on a "Not Recommended" edit because the pane summarized what changed instead of showing it, and had to ask for the actual copy before deciding.

- **Four decision states, not two-plus-a-modifier.** Accept/Deny with a comment as an orthogonal add-on is ambiguous: Claude has to *infer* whether a comment on a still-pending item means "ship this, but tweak it" or "not yet, try again." Make that distinction a button, not an inference:

  | Button | State | Comment box | Meaning |
  |---|---|---|---|
  | ✕ Keep Original | `deny` | optional | Reject the change outright. |
  | ✓ Use Edit | `accept` | optional | Ship the proposed edit exactly as shown. |
  | ✓ Approve with Comment | `accept-comment` | opens, expected | Ship it, but modify per the comment. The comment is a change instruction, not a footnote. |
  | ↻ Request Revision | `revise` | opens, expected | Don't ship anything yet. The comment explains what's wrong or what to try instead; expect a follow-up round on this item specifically. |

  `accept-comment` and `revise` open the same kind of `<textarea>` immediately on click (no separate toggle step), since a comment is the point of picking either one:

  Each decision button has the class `btn` (the handler below selects `.btn[data-choice]`) and carries `data-item` (the item id) and `data-choice` (`deny`, `accept`, `accept-comment`, or `revise`), and one hidden `<textarea>` with `id="comment-<item id>"` sits beside them. The handler:

  ```js
  document.querySelectorAll('.btn[data-choice]').forEach(b => b.addEventListener('click', () => {
    const box = document.getElementById('comment-' + b.dataset.item);
    const needsComment = b.dataset.choice === 'accept-comment' || b.dataset.choice === 'revise';
    box.style.display = needsComment ? 'block' : 'none';
    if (needsComment) box.focus();
  }));
  ```
  A comment typed under `deny` or plain `accept` is still captured and exported (someone may want to leave a note without changing the decision type); it just isn't *required* the way it is for the other two.

- **Sticky bottom bar:** running "X of N reviewed" + a tally per state + a "Copy My Decisions" button that writes a plain-text numbered summary to the clipboard via `navigator.clipboard.writeText`. If the clipboard is missing or the write fails, show the summary in a selectable text box (select all) instead, and never show "Copied" on failure. **The export's first line must identify the page or article being reviewed.** Pasted decisions arrive back in chat with no other context, and across a multi-page review queue there's no way to tell which page a bare `1. ... — ACCEPT` refers to without it. Use a stable bracketed header naming the page, matching the Artifact's own title:
  ```
  [Pricing Page — Copy-Edit Review]
  12. New — Introduction to the Method — ACCEPT WITH COMMENT — COMMENT: swap "proprietary" for "our own"
  13. Alternate — SEO-Optimized Title — DENY (Keep Original)
  14. Whole page — missing disclosure — REVISE — COMMENT: don't call it "not typical," I don't want to imply that
  ```
  Omit the `— COMMENT: ...` suffix entirely for plain `ACCEPT`/`DENY` items with no comment; don't print an empty one. `ACCEPT WITH COMMENT` and `REVISE` always carry a comment by construction.

Publish with the `Artifact` tool. Redeploy to the same file path when you add fields or fix bugs; don't mint a new URL for revisions the user is already looking at.

**Verify the script actually runs before publishing; don't just eyeball it.** A single bad escape (e.g. an apostrophe in a hand-authored JS string, `'Claude\\'s Fix'` instead of `"Claude's Fix"`) throws a `SyntaxError` that silently kills the *entire* `<script>` block. The page loads and looks fine structurally, but zero cards render and nothing is clickable, with no visible error unless someone opens devtools. The user can only find out by looking at an empty page. Before publishing:
1. Extract the contents of the page's `script` element to a `.js` file and run `node --check` on it.
2. Load the actual file in a headless browser (Playwright or similar), assert the expected card count rendered, click through an Accept/Deny/Comment on at least one item, and check that page errors came back empty.

Only publish after both pass. Do this on every revision, not just the first.

### 5. Applying the decisions

When the user pastes back the copied summary, match items by number.

- **`ACCEPT`**: apply the edit exactly as proposed.
- **`ACCEPT WITH COMMENT`**: apply the edit, but the comment is a change instruction that modifies it first. Don't ship the edit verbatim and separately guess at the comment; read the comment, work out what the final text should be, and apply *that*.
- **`DENY`**: leave the file untouched. A comment here is a note or reason, not an instruction to act on.
- **`REVISE`**: leave the file untouched *for now*. The comment is feedback for a follow-up round on this specific item (see below). Don't apply anything from it yet, and don't treat it as an implicit accept.
- **`PENDING`**: not reviewed yet; leave untouched, don't chase it.

Note anything you skipped and why. Verify and commit following the project's own notes (`CLAUDE.md`). The review tool changes nothing about how the actual file edit gets verified and shipped.

### 6. Follow-up rounds on `REVISE` items

When one or more items come back `REVISE`, build a new round rather than silently iterating in chat. The same human-in-the-loop principle applies to round 2 as to round 1.

- **Scope the new Artifact to only the still-open items, but "still open" means every item without a final decision, not just the ones marked `REVISE`.** Don't re-show items already resolved (`ACCEPT`, `ACCEPT WITH COMMENT`, `DENY`): they're already applied or settled, and re-litigating them wastes the user's attention and risks a stray click undoing a done decision. But a `PENDING` item from the prior round (never decided at all, just not part of that round's revision batch) is not resolved either. Dropping it when you rescope to "the items sent back for revision" silently deletes the user's only path to ever deciding it. Carry every non-final item forward into each new round, not just the ones explicitly revised. If only one item is open, the whole page is one card.
- **Carry the history forward on each card.** Show the prior round's proposal, clearly labeled ("Round 1 (requested revision)"), with the user's own revision comment quoted or summarized so they have full context without scrolling back through chat. Then show the new proposal, labeled "Round 2 proposal" (increment further if it goes another round). Don't make the user re-explain what they already told you.
- **Republish to the same Artifact URL**, per the "same file path" guidance above. This applies to every follow-up round, not just typo-fix revisions of the same round.
- **Re-run the verification step** (script syntax check + headless click-through) before every republish. A smaller page is not a lower-risk page.

## Where the page goes

The project chooses with `PROOFS_PAGES`, set in the project's `.claude/settings.json` "env" block (or a line in CLAUDE.md: "proofs pages: file"). Values:

- `artifact`: publish as a private claude.ai artifact (a link that opens on phone and computer). This is the default when publishing is available.
- `file`: save the page as an HTML file (default folder `.proofs/pages/`; add it to .gitignore) and open it in the browser (`open` on macOS, `xdg-open` on Linux, `start` on Windows). This is the default when artifacts are not available. Reuse the same file path for later rounds so the page updates in place instead of piling up.
- `wifi`: same as `file`, plus serve only a folder that holds this review's page(s) (for example `.proofs/pages/<review-name>/`, so older pages are not listed to the network) on the local network (`python3 -m http.server <port> --bind <the computer's local IP>` from that folder) and print the address so a phone on the same Wi-Fi can open it. This mode never uploads the page and never uses a public tunnel. Stop the server when the review is done. Use `wifi` only on a private network you trust, never on public or shared Wi-Fi.

If `artifact` is chosen but publishing fails or is not available, fall back to `file` and say so in one line. Everything on the page works the same in every mode. The page's copy button gives the user text to paste back. Copy buttons must fall back to a selectable text box (select all) when `navigator.clipboard` is missing or the write fails (a page served over http on a local IP is not a secure context, so the clipboard is often unavailable), and must never show "Copied" unless the copy actually succeeded.

## Changelog

- **1.2.2** (2026-11-17): Copy buttons now fall back to a selectable text box when the clipboard is unavailable (as on a Wi-Fi-served page), and `wifi` mode is limited to a private network you trust.
- **1.2.1** (2026-11-16): New section "Where the page goes": a project can choose an artifact, a local file, or a file served on its own Wi-Fi.
- **1.2.0** (2026-11-16): Merged into proofs: generic, no project-specific steps.
