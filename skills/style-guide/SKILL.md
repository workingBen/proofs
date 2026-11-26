---
name: style-guide
version: 1.8.5
allowed-tools:
  - Read(/${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/shared/review_page/review_page.py *)
description: Use when the user wants site-wide design rules settled (type scale, spacing, color, card style, disclaimer placement), names a rule, or points out the same inconsistency across many pages. Differs from design-review, which changes one page; this audits the whole site and records accepted rules in docs/style-guide.html.
---

# Style Guide Tool

A human-in-the-loop process for auditing and codifying design consistency across an entire site, not one page at a time. Sibling tool to `article-copy-edit` and `design-review`: same Artifact-review loop, but the output is a persistent, living document instead of a one-shot set of edits.

**Results first.** Nothing matters more than a result the user wants. Save tokens by cutting waste, never by cutting a check, an option or a revise pass the result needs (full text: `../../reference/house-rules.md`).

Read the settings: `python3 ${CLAUDE_PLUGIN_ROOT}/shared/settings.py --print` (pre-approved). Use the values it shows wherever this file says *the style guide file* (`PROOFS_STYLE_GUIDE`) and *the design profile path* (`PROOFS_DESIGN_PROFILE`). `docs/style-guide.html` below is the style guide setting's default; use the setting's value in its place.

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

### 3. Build the review page with the shared builder

**Needs the whole plugin.** This skill reads shared files at `../../reference/` and `../../shared/`, relative to its folder. If they are missing, the skill was copied on its own: install the whole plugin (`/plugin install proofs@proofs`) rather than recreating them.

Write the content; the builder writes the page. Read `../../reference/review-page.md` first: it documents the spec and the command, `python3 ${CLAUDE_PLUGIN_ROOT}/shared/review_page/review_page.py .proofs/style-guide/spec.json --out .proofs/pages/<guide-name>.html`, with `"decisions": "style-guide"`. Do not hand-write the page's JavaScript. Follow any design guidance your environment provides for published pages, same as both siblings. Fill `project` with `name`, `session` and `repo`, taking the session name the way the `working-log` skill does (the session's own name, else one named for the work, kept for the life of the page): the page's header shows the proofs mark, this skill's name, the project and the session, so the user can match the page to its session at a glance.

- **Rendered examples, not screenshots, and not prose either.** Unlike `design-review`, build each example as real coded HTML/CSS using the site's actual classes and tokens (in `css`), rendered inline, not a screenshot of a live page. The point is to show the underlying recipe next to the visual. This cuts both ways: never substitute a *description* of the visual difference (for example, "the signup page uses a larger heading than the pricing page") for the difference itself. Class and token names carry no meaning to someone who doesn't read the codebase. Every item, including "current vs. proposed" and multi-variant items, renders the compared states side by side (or labeled Before/After) at their real size, color and weight, using real or representative copy from the site. The decision is "which of these two things I'm looking at do I prefer," never "which of these two labels."
- **Each item:** `label`, `category` (Typography, Spacing, Color, Components, ...), `recommended`, the rendered example plus its exact class or markup recipe in a `<code>` block in `body_html` (one example for an already-decided item; `variants` for an undecided one), and `reason_html`.
- **Turn on `"filters": true`** for any round past a handful of items: clickable category tabs with a live open count, each category with its own chip color on every item and tab. Keep the section headers (one section per category) too.
- **Turn on `"preview_toggle": true` whenever the site has both themes**, and write each example's dark values in `css` under `[data-preview="dark"]`. Several real inconsistencies are dark-mode-only contrast bugs a reviewer can't judge in one theme. A one-theme site doesn't need it.
- The preset shows the decision legend once near the top and a color-coded progress bar. Its four buttons:

  | Button | Comment box | Meaning |
  |---|---|---|
  | ✕ Deny | optional; a **"Works as Designed"** checkbox appears beside it | Reject the proposed style. Plain deny: nothing recorded, nothing changed, the comment is just a note. With the checkbox: the *current, existing* state is recorded as the ratified rule instead of the proposal, a positive confirmation that the status quo is intentional (for example, a denser card layout for admins than for customers). The comment becomes that rule's rationale. |
  | ↻ Request Revision | expected | Don't accept as shown; the comment explains what to try instead. Scoped follow-up round next time. |
  | ✓ Accept: Apply Everywhere Now | optional | Record as the official rule AND retrofit every page using something else, in the same apply pass. |
  | ✓ Accept: Record for Later | optional | Record as the official rule only. Retrofitting becomes a new entry in the project's to-do list (or ask where follow-up work is tracked), not done in this pass. |

  Four buttons, not five: the comment box is open on all four. Filled in on an Accept, it modifies the recorded rule (and the retrofit); on Deny it is just a reason unless "Works as Designed" is checked.

- **Export**, first line identifying the review (the bracketed title). An undecided item is left out entirely, not printed as `PENDING`; step 4 treats any missing number as pending. For an undecided item the chosen option is named, e.g. `ACCEPT (Record for Later: Option B)`.
  ```
  [Style Guide Audit — 2026-01-15]
  1. Body text size on disclaimer notes — ACCEPT (Apply Everywhere Now)
  2. Section spacing on landing pages — ACCEPT (Record for Later)
  3. Icon-header layout — ACCEPT (Apply Everywhere Now) — COMMENT: also apply to the account settings page
  4. H2 size on plain articles vs templated ones — REVISE — COMMENT: try matching the templated size instead of splitting the difference
  5. Hero header color — DENY
  6. Customer vs. admin card density — DENY (Works as Designed) — COMMENT: two audiences with genuinely different density needs, not drift
  ```

Deliver the page as "Where the page goes" below says (with `artifact`, that means publishing it with the `Artifact` tool). Use the same file path across revisions of the same audit round.

**Verify before publishing, every time.** The build runs its own check. Run `--smoke`. If it reports Playwright missing, run the one-line install it prints (it uses your installed Google Chrome and downloads no browser), then run `--smoke` again; if it still cannot run, say on the page and in chat that the self-check did not run. Then screenshot the page in both preview themes and check the coded examples don't add sideways scroll or overlap. Only publish after all of it passes.

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

Identical pattern to the sibling tools: scope the new Artifact to only the still-open items (every item without a final decision, not just the explicitly revised ones), carry the prior round's proposal forward on each card labeled "Round N," rebuild and republish to the same URL, and re-verify before every republish. If a prior round's already-decided item is worth keeping visible for context (for example, it's near a new item covering related ground), show it de-emphasized in `after_html` or a `history_html` rather than omitting it or presenting it as open again. It's there for continuity, not re-review.

When the guide is done, tell the user that design-review uses it for its mockups' tokens and its critic's `fit` score, together with an optional design profile (the design profile path setting, default `docs/design-profile.md`: the owner's references, rules and audience; neither file is ever required).

## Where the page goes

Before you publish or save the page, read `../../reference/where-the-page-goes.md` (the path is relative to this skill's folder). The project's `PROOFS_PAGES` setting picks artifact, file or wifi, and that file says what each means and how copy buttons must fall back.
