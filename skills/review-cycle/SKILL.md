---
name: review-cycle
version: 1.12.0
description: Use when the user opens a review session ("starting a review cycle", "let's do a review pass") and feeds a stream of bug reports and requests, often from a phone, to be triaged and handled without questions; fixes ship, design calls go to design-review, big features become to-dos. Not for a single one-off request.
---

# Review Cycle Tool

A queue-processing workflow for a live review session: the user reports issues one at a time or in a batch; each is worked to completion (investigate, implement, test, commit, open a pull request, merge it) without stopping to ask questions, because the user isn't available for synchronous back-and-forth during the session. Every item is **triaged first** (see Triage below): easy fixes ship autonomously, and an item that needs a sibling skill in this plugin (`design-review`, `visual-qa`, `article-copy-edit`, `photo-picker`, `style-guide`, `todos`) gets that skill started for it automatically, without the user asking. There's still no blocking review step mid-session: a design review is published and waits for the user's picks while the queue keeps moving. The user reviews once, on a tracking page that is built as the session runs.

**Test first.** If the superpowers plugin is installed, use `superpowers:test-driven-development` for each item's implementation; otherwise write the failing test first yourself, watch it fail, then make it pass.
**Debugging.** If the superpowers plugin is installed, use `superpowers:systematic-debugging` when a test failure's cause isn't immediately obvious; otherwise debug systematically: reproduce, form one hypothesis, test it, repeat.

## When to Use

- The user explicitly opens a session (e.g. "starting a review cycle," "let's do a review pass").
- Not for a single one-off request made in normal conversation; just handle it directly.
- Items that need `design-review`, `visual-qa`, `article-copy-edit`, `photo-picker` or `style-guide` belong in the session too: triage routes them to that skill (below). Only a whole project that needs a full `brainstorming` cycle is out of scope; it is saved as a to-do.

## Lifecycle

1. On open, confirm you're ready and invite items one at a time or in a batch. **Screenshots are ON by default.** State it as a one-line announcement with an opt-out, not a question: *"Screenshots ON — tell me if you want them OFF."* Do not make the user answer a question before they can start feeding items. If they turn them off, note it and skip the Screenshot Capture step for the rest of the session; otherwise follow it. Skip one item's shot only when capturing it for that particular feature is genuinely hard (an awkward-to-reach state, a flow that won't screenshot cleanly), a case-by-case call and not a reason to disable screenshots for the session; note the skip and the reason in the backlog entry. (Screenshots cost real per-item time, an extra browser run beyond what the fix already needs, but these reports usually come from a phone and a width-matched before/after is the fastest way to confirm a fix landed.)
2. **Set up the session's working copy once, at open** (see Per-Item Workflow, step 3). Then **the moment the first batch of items is in hand, publish the tracking page** (see The Tracking Page below, and its reference file): one card per reported item with its *before* evidence, before the first fix ships. It is republished after every item, and it is the same page the end-of-session summary lands on.
3. Every message after that is one or more queue items. **Start working them immediately and advance automatically.** The user does NOT need to say "start," "go," "next," or "continue" between items. When one item finishes, pick up the next queued one on your own. The only thing that ends the loop is the user saying they're done (or going quiet after the last item). A checkpoint (below) **pauses** the loop across a cleared conversation and is not an end.
4. An item arriving mid-item queues behind the current one. Never interrupt in-flight work to jump to something new.
5. **Drain the no-input queue first, then batch the input questions.** Within the queue, fully complete every item you can finish **without the user's input** (autonomous fixes, investigations, bug debugging, questions you can answer from the code) before surfacing anything that genuinely needs the user. Items triaged to **Needs input** (below) still get logged the moment you encounter them, but you do **not** stop to ask about them inline: collect their questions and present them **as a single batch at the end**, once nothing autonomous is left, together with the links to every design review started this session. One consolidated round beats a scattered interruption per item. A **bug or investigation is not a Needs input item** just because it's hard: debug it autonomously (see systematic-debugging), and defer it only if, after real investigation, it turns out to need a specific decision or piece of information only the user has. Then defer just that specific question to the end batch.

## Per-Item Workflow

1. **Investigate**: read the report, grep and read the relevant code, scope it before deciding anything.
2. **Triage it into one lane** (see Triage below). Only the **Fix** lane continues to step 3. Every other lane is handled the way its row says, logged (step 4) and shown on the tracking page, and then you move on to the next item without waiting.
3. **Fix lane: build it autonomously:**
   - Resolve any remaining ambiguity yourself with the lowest-risk default; record the assumption in the backlog entry (below). Never stop to ask.
   - TDD: test first, then implementation.
   - Run the relevant test suite; confirm it's green.
   - Self-review the diff before committing.
   - **Ship it as its own pull request: one item, one branch, one PR, merged as you go.** Never commit on the main branch. The sequence per item:
     ```bash
     git fetch origin main                            # from the session's working copy
     git checkout -b <type>/<short-slug> origin/main   # fresh off main, not off the last item
     # ... commit the work, explicit paths only ...
     git push origin <branch>
     gh pr create --fill                               # body: the report, the fix, test evidence
     gh pr merge <n> --merge                           # NOT --delete-branch; see below
     git push origin --delete <branch>
     ```
   - **You open the PR and you merge it. The PR is a record and a CI gate, not an approval gate.** If triage put an item in the Fix lane, it ships in the same turn; do not park it awaiting review. The user opened a review cycle so they would not have to approve things one by one. Merge once the local suite is green; if CI is broken or unavailable for reasons unrelated to the item, say so in the progress line and merge anyway.
   - **Work the whole session in one worktree** (a separate working copy of the repository, made with `git worktree add`), created once at session open off a freshly fetched `origin/main`. It keeps the session's edits from colliding with anything else happening in the checkout. The per-item branches are cut inside it. Don't create a worktree per item: that is per-item overhead the loop can't afford.
   - Combine items into one PR **only** when they touch the same code and would conflict or read as nonsense apart. Two fixes to the same partial in the same sitting are one PR; two unrelated fixes are never one PR just because they arrived together.
   - Each PR carries its own docs, backlog edit and screenshots, never a follow-up PR for those.
   - Confirm merging to the main branch is actually safe for the target project first (see Portability).
   - **`gh pr merge --delete-branch` fails AFTER the merge has landed** when another worktree holds the main branch (`fatal: 'main' is already used by worktree at ...`), and it reads exactly like the merge failed. That is why the recipe uses plain `--merge` followed by an explicit branch delete. If you hit it anyway, check `gh pr view <n> --json state` before retrying.
4. **Log the item** in the backlog file (see Portability), using whichever of these applies:

   Flagged:
   ```
   - [NEEDS INPUT] <short title> — <one-line reason for flag>
   ```

   Sent to another skill:
   ```
   - [IN REVIEW] <short title> — <skill>: <page link>
   ```

   Saved for later:
   ```
   - [TO-DO] <short title> — saved to <to-do list>: <one-line scope>
   ```

   Autonomous, at intake:
   ```
   - [ ] <short title>
     - What: <the report, restated>
     - Why: <root cause / user-facing motivation>
     - Approach: <what you're going to do>
     - Risk/assumptions: <any default you chose instead of asking>
   ```
   flipped to on completion:
   ```
   - [x] <short title> — shipped (PR #<n>, <commit-sha>): <one-line summary>
   ```
5. **Screenshot capture (on by default; skip only if the user turned it off at session open).** The *before* is captured **at intake, before any code changes**: it is the one shot that cannot be taken later, and the tracking page is seeded with it. Take it yourself when the item comes in, at both a phone and a desktop width, unless the user sent their own screenshot (almost always a phone photo) for that width. Then for a shipped item with a visible UI change, capture the "after" state once the fix is verified working, **at both a mobile and a desktop viewport**. Reuse whatever live browser check the fix already needed rather than opening a fresh one just for this. Pair each viewport with the "before" evidence available *at that same viewport*. **Never pair a before/after across mismatched viewports** (for example, the user's mobile phone photo against your desktop-width "after"): the comparison is misleading because layout, wrapping and spacing differ by width, not just by the fix. If a "before" only exists at one viewport, the summary shows that item's Mobile/Desktop toggle with only that one populated (labeled, not silently duplicated into the other slot) rather than faking a pair.
   - **Capture technique:** use a scriptable, real-viewport tool (for example Playwright with `page.setViewportSize()`) for both widths. Mobile around 390x844 (a common phone size) and desktop around 1440x900 are suggestions; use whatever the project's real users have. Don't rely on resizing a live interactive browser session's window and hoping the page reflows: a resize call can report success while the actual rendered content stays at its previous width. Verify the capture actually reflowed (for example, check for a mobile nav pattern like a hamburger menu, or that an element hidden at small widths is genuinely absent) before trusting it as "mobile."
   - Save all captures under a session-scoped scratch path and note the paths (and which viewport each is) in the backlog entry.
   - Skip entirely for non-visual fixes (bug in server logic, timing, accessibility-only, and so on): there's nothing to show.
6. **Emit a progress line** (visibility only, no question, no response needed):
   ```
   [N/M] <short title> — shipped (PR #<n>, merged). <count> remaining.
   [N/M] <short title> — flagged [NEEDS INPUT]: <reason>. <count> remaining.
   [N/M] <short title> — <skill> started (<page link>). <count> remaining.
   [N/M] <short title> — saved as a to-do (<where>). <count> remaining.
   ```
   `M` is the count of items received so far in the session; it grows if the user adds more mid-session.
7. **Checkpoint check.** If a trigger in Checkpoints (below) has fired, checkpoint now, at this boundary, before starting anything else (`reference/checkpoints.md`).
8. **Move to the next queued item IMMEDIATELY, in the same turn.** A progress line is a status broadcast, not a pause: do not stop after it, do not summarize, and do not wait for the user to say "continue." Keep taking items until the queue is genuinely empty.
   - The user opened a review cycle precisely so they could hand over a stream of items and walk away. Stopping to report after each one recreates the back-and-forth the tool exists to avoid, and it strands work that was already unblocked.
   - The only legitimate reasons to stop mid-queue: the queue is empty; every remaining item is blocked on a flagged decision; or something genuinely destructive needs confirming. The user saying they're done also ends it.
   - "The turn is getting long" is NOT a reason to stop. Neither is "the user might want to redirect me": they will say so if they do.
   - This applies to work you discover as well as work you were handed: if finishing an item reveals the next one is unblocked, start it.

## Triage — every item gets a lane, and a lane can start another skill

The user hands over a mixed stream on purpose: a typo, a broken button, "this page feels cramped on my phone", "we need a booking calendar". **Sort each item into exactly one lane before doing anything else, and start the skill its lane names on your own.** The user should never have to say "do a design review for that one": recognizing that an item needs one is this skill's job.

| Lane | When | What happens | Card state |
|---|---|---|---|
| **Fix** | Clear, small, reversible; one reasonable outcome | Build, test, PR, merge (Per-Item Workflow, step 3) | Reported → In progress → Shipped |
| **Design review** | More than one reasonable design, or a matter of taste: a new section, a layout change, "make this nicer" | Run `design-review` for it: before screenshot, 1–3 coded mockups, its own published page. Link that page from the item's card | In design review |
| **Visual QA** | A page "looks wrong", cramped, too small or broken at some width, without a specific fix named | Run `visual-qa` on the page(s). It measures, then hands its fixes to `design-review` | In design review |
| **Copy edit** | Rewording an article or page copy beyond a typo, or anything that makes a claim | Run `article-copy-edit` on the text | In design review |
| **Photo** | A spot needs a new or better picture | Run `photo-picker` for that spot | In design review |
| **Style rule** | The same look is inconsistent across many pages, or the user names a rule | Run `style-guide` | In design review |
| **To-do** | A real feature or multi-system change: its own `brainstorming` and plan cycle | Save it to the project's to-do list (use `todos` if the project has it) with the user's words, a one-line scope and the open questions. Don't build it | Saved as a to-do |
| **Needs input** | Irreversible or destructive (data migrations, deleting data, payments, auth), or unclear in a way no low-risk default resolves, or anything else you'd want a second opinion on (this discretion is intentionally unbounded) | Bank one specific question for the end batch | Flagged |

**A bug is a Fix even when it is hard.** Debug it autonomously; it becomes Needs input only if real investigation shows that a decision or fact only the user has is missing.

**Started skills never block the queue.** Publish the design-review (or visual-qa, copy-edit, photo-picker, style-guide) page, put its link on the item's card, and move straight to the next item. The user decides on that page whenever they like. When their export comes back, the picks are a new **Fix** item at the front of the queue, built the usual way. One page per item; several design items from the same session may share one review page as separate items.

**When you are unsure between Fix and Design review, choose Design review.** Making a taste call yourself and noting what you would have asked is not a substitute: the user opened the session so the calls that are theirs reach them as a page they can look at.

**Say the lane in the progress line** so the stream stays readable:

```
[3/9] Booking calendar: saved as a to-do (TODO.md, "Booking calendar"). 6 remaining.
[4/9] Pricing page header: design review started (<page link>). 5 remaining.
```

## Checkpoints — Handoff and Clear Between Features

Checkpoint at the next item boundary (never mid-item) once a major item has finished and the next is unrelated, five items have shipped since the last checkpoint, context is half spent, or the next item is visibly large. **When one fires, and first thing after any clear, read `reference/checkpoints.md`** (in this skill's folder) and follow it: verify, route, write the handoff, keep going.

## The Tracking Page — one artifact, published at intake, updated per item

One page per session, published as soon as the first batch is in hand and republished to the same URL after every item; the end-of-session summary is its last republish. **Read `reference/tracking-page.md` before you first publish it.** Its docked bar starts with the proofs mark, a `review-cycle` pill, the project and the session, as every proofs page does.

## End-of-Session Summary

When the user says they're done, or goes quiet after the last item, **read `reference/end-of-session-summary.md`** and follow it.

## Common Mistakes

| Rationalization | Reality |
|---|---|
| "This UX call is ambiguous, but I can make a reasonable choice and just note what I'd have asked" | Documenting the assumption doesn't substitute for asking. Ambiguous UX/design decisions always go to `design-review`, started by you, full stop. |
| "I'll flag this design item and let the user ask for a design review later" | Starting the review is your job. Triage puts it in the Design review lane and you run `design-review` now, publish its page, link it from the card, and keep going. |
| "This feature is big, so I'll start building the first piece" | A feature that needs its own plan is a To-do. Save it with the user's words and a scope line; don't half-build it inside a review cycle. |
| Waiting on a design review's picks before starting the next item | Started skills never block the queue. Publish, link, move on; the picks come back as a new Fix item. |
| "I'll open the PR and leave it for them to review" | The PR is a record, not an approval gate. You open it and you merge it, same turn, once the suite is green. |
| "These all arrived in one session, so they're one PR" | One item, one branch, one PR. Combine only when the items touch the same code and would conflict or read as nonsense apart. |
| "I'll branch off the previous item's branch; it's already checked out" | Every item branches off a freshly fetched `origin/main`. Stacking makes each PR carry the one before it. |
| "I'll commit this one straight to main, it's a one-liner" | Never. Size is not the criterion. Branch, PR, merge. |
| Fixing the item without ever touching the backlog file | Every item gets a backlog entry. Shipped items are logged *and* checked off, not shipped silently. |
| Asking at session open whether the user wants screenshots | Screenshots are ON by default: announce it with an opt-out. Making them answer a question before they can feed the first item is friction the default exists to remove. |
| Stopping to ask a clarifying question | The user isn't available mid-session; resolve with the lowest-risk default and note it, or flag it. Never block on a question. |
| "I'll report what I've shipped and let them tell me to keep going" | A progress line is not a pause. Start the next item in the same turn; the user handed over a queue so they wouldn't have to keep saying "continue." |
| "This turn is very long, I'll wrap up and continue next turn" | Length is not a stopping condition. Only an empty queue, an all-blocked queue, or a destructive action needing confirmation is. |
| Interrupting the flow to ask about each design/decision item as you hit it | Log it, keep draining everything you can finish without the user, and present all the input-needed questions as one consolidated batch at the end. |
| Flagging a bug to the batch just because it's hard to debug | Bugs and investigations aren't Needs input items. Debug them autonomously; defer only a specific decision or fact the user alone holds, and only after real investigation. |

## Portability

This skill assumes:
- A repository-root backlog file (a to-do list; `TODO.md` by convention) is the source of truth for queue state. If the target project uses a different backlog location or format, adapt the entry templates above to it.
- The project uses GitHub pull requests (`gh` authenticated) and the session may merge its own PRs to the main branch without human approval. **Verify both before adopting the skill in a new project.** If the project requires human review on every PR, the loop still works, but say at session open that items will land as open PRs rather than merged ones, and treat that as the session's shipping definition.
- **Check whether merging deploys.** Landing on the main branch should be safe for the target project: no auto-deploy-on-merge, or the project owner has explicitly accepted that. If the project auto-deploys, get that turned off first, or add an explicit "hold for manual deploy" step after the merge. Never call a merged item "deployed" unless you have confirmed it is.
- The checkpoint protocol assumes somewhere to put a dated handoff (the project's handoff folder, as its notes say) and a real home per kind of durable thing (its to-do list, archive, field guide, decisions file and notes file for agents). **The routing is the rule; the file names are the project's.** In a project with fewer of these, the backlog file absorbs open work and decisions, and the handoff still may not be the only home for anything.
- Uses a tracking page (delivered as "Where the page goes" says), which carries a decision per shipped item and a copy-back export. **Mid-session the loop still has no blocking review step by design**: that is what keeps it fast. The user reviews on the page when they choose, and nothing waits on it.

**Needs the whole plugin.** This skill reads shared files at `../../reference/` and `../../shared/`, relative to its folder. If they are missing, the skill was copied on its own: install the whole plugin (`/plugin install proofs@proofs`) rather than recreating them.

## Where the page goes

Before you publish or save the page, read `../../reference/where-the-page-goes.md` (the path is relative to this skill's folder). The project's `PROOFS_PAGES` setting picks artifact, file or wifi, and that file says what each means and how copy buttons must fall back.
