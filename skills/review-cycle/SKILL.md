---
name: review-cycle
version: 1.10.2
description: Use when the user opens a review session and feeds a stream of small bug reports or feature requests one at a time (often from a phone), wanting each worked to completion without stopping for questions, with anything too ambiguous, risky, or large flagged for later discussion instead of decided alone.
---

# Review Cycle Tool

A queue-processing workflow for a live review session: the user reports issues one at a time or in a batch; each is worked to completion (investigate, implement, test, commit, open a pull request, merge it) without stopping to ask questions, because the user isn't available for synchronous back-and-forth during the session. Sibling tool to `article-copy-edit`/`design-review`/`style-guide`, but there's no interactive review step mid-session: items either ship autonomously or get logged for a later in-person discussion. The user reviews once, on a tracking page that is built as the session runs.

**Test first.** If the superpowers plugin is installed, use `superpowers:test-driven-development` for each item's implementation; otherwise write the failing test first yourself, watch it fail, then make it pass.
**Debugging.** If the superpowers plugin is installed, use `superpowers:systematic-debugging` when a test failure's cause isn't immediately obvious; otherwise debug systematically: reproduce, form one hypothesis, test it, repeat.

## When to Use

- The user explicitly opens a session (e.g. "starting a review cycle," "let's do a review pass").
- Not for a single one-off request made in normal conversation; just handle it directly.
- Not for work that genuinely needs `design-review`, `style-guide`, `article-copy-edit`, or a full `brainstorming` cycle: route that to the escape hatch below instead of forcing it through this lightweight loop.

## Lifecycle

1. On open, confirm you're ready and invite items one at a time or in a batch. **Screenshots are ON by default.** State it as a one-line announcement with an opt-out, not a question: *"Screenshots ON — tell me if you want them OFF."* Do not make the user answer a question before they can start feeding items. If they turn them off, note it and skip the Screenshot Capture step for the rest of the session; otherwise follow it. Skip one item's shot only when capturing it for that particular feature is genuinely hard (an awkward-to-reach state, a flow that won't screenshot cleanly), a case-by-case call and not a reason to disable screenshots for the session; note the skip and the reason in the backlog entry. (Screenshots cost real per-item time, an extra browser run beyond what the fix already needs, but these reports usually come from a phone and a width-matched before/after is the fastest way to confirm a fix landed.)
2. **Set up the session's working copy once, at open** (see Per-Item Workflow, step 3). Then **the moment the first batch of items is in hand, publish the tracking page** (see The Tracking Page below): one card per reported item with its *before* evidence, before the first fix ships. It is republished after every item, and it is the same page the end-of-session summary lands on.
3. Every message after that is one or more queue items. **Start working them immediately and advance automatically.** The user does NOT need to say "start," "go," "next," or "continue" between items. When one item finishes, pick up the next queued one on your own. The only thing that ends the loop is the user saying they're done (or going quiet after the last item). A checkpoint (below) **pauses** the loop across a cleared conversation and is not an end.
4. An item arriving mid-item queues behind the current one. Never interrupt in-flight work to jump to something new.
5. **Drain the no-input queue first, then batch the input questions.** Within the queue, fully complete every item you can finish **without the user's input** (autonomous fixes, investigations, bug debugging, questions you can answer from the code) before surfacing anything that genuinely needs the user. Items that hit the escape hatch (below) still get logged the moment you encounter them, but you do **not** stop to ask about them inline: collect their questions and present them **as a single batch at the end**, once nothing autonomous is left. One consolidated round of design and decision questions beats a scattered interruption per flagged item. A **bug or investigation is not an escape-hatch item** just because it's hard: debug it autonomously (see systematic-debugging), and defer it only if, after real investigation, it turns out to need a specific decision or piece of information only the user has. Then defer just that specific question to the end batch.

## Per-Item Workflow

1. **Investigate**: read the report, grep and read the relevant code, scope it before deciding anything.
2. **Escape-hatch check**: log the item and skip to the next one, without attempting an implementation, whenever it is:
   - An **ambiguous UX/design call**: multiple reasonable designs exist and picking one is a matter of taste. Even if you *can* make a defensible choice, don't. This is exactly the kind of call that normally goes through `design-review`/`style-guide` with the user. Documenting the assumption you'd have made is not a substitute for flagging.
   - **Irreversible or destructive**: data migrations, deleting user data, hard-to-roll-back schema changes, risky payments or auth changes.
   - **Large or multi-system**: scope that would normally get its own `brainstorming` + plan cycle, not a small fix.
   - **Unclear or underspecified** in a way you can't resolve with a low-risk default.
   - Anything else you'd want a second opinion on, for any reason. This discretion is intentionally unbounded.
3. **Otherwise, build it autonomously:**
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
   - **You open the PR and you merge it. The PR is a record and a CI gate, not an approval gate.** If an item passed the escape-hatch check, it ships in the same turn; do not park it awaiting review. The user opened a review cycle so they would not have to approve things one by one. Merge once the local suite is green; if CI is broken or unavailable for reasons unrelated to the item, say so in the progress line and merge anyway.
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
   ```
   `M` is the count of items received so far in the session; it grows if the user adds more mid-session.
7. **Checkpoint check.** If a trigger in Checkpoints (below) has fired, checkpoint now, at this boundary, before starting anything else.
8. **Move to the next queued item IMMEDIATELY, in the same turn.** A progress line is a status broadcast, not a pause: do not stop after it, do not summarize, and do not wait for the user to say "continue." Keep taking items until the queue is genuinely empty.
   - The user opened a review cycle precisely so they could hand over a stream of items and walk away. Stopping to report after each one recreates the back-and-forth the tool exists to avoid, and it strands work that was already unblocked.
   - The only legitimate reasons to stop mid-queue: the queue is empty; every remaining item is blocked on a flagged decision; or something genuinely destructive needs confirming. The user saying they're done also ends it.
   - "The turn is getting long" is NOT a reason to stop. Neither is "the user might want to redirect me": they will say so if they do.
   - This applies to work you discover as well as work you were handed: if finishing an item reveals the next one is unblocked, start it.

## Checkpoints — Handoff and Clear Between Features

A review cycle accumulates. By item 20 the context still carries item 1's file reads, diffs and test output, and every turn pays for all of it. A long session once merged 27 pull requests in a single context and ran out of its budget mid-flight: it died with a PR open and unverified, and the entire queue (what had been reported, what had shipped, what the user had said and no one had acted on) existed nowhere but the conversation. Checkpointing exists so that never has to be reconstructed under pressure.

A checkpoint is three things in order: **route everything durable to its real home, write a resume handoff, clear the context and resume from the file.**

### When to checkpoint

Checkpoint at the **next item boundary** after any one of these becomes true. Never mid-item. A session that dispatches its per-item work to subagents from the start will rarely reach these at all, and that is the point.

- **A major item just finished and the next queued item is unrelated.** *Major*: it needed its own branch and PR, or a subagent, or touched more than a handful of files, or took several rounds of tests to land. *Unrelated*: starting the next item means opening a different set of files, with no shared model, controller, view or feature area with the one just finished. **Both must hold.** A major item followed by three more tweaks to the same view is not a checkpoint point; the context you are carrying is the context the next item needs.
- **Five items have shipped since the last checkpoint**, related or not. A count is here rather than left to judgment because a long session never recognized a boundary it was willing to stop at.
- **Context is more than half spent**, or a compaction or summarization warning has appeared. Being summarized by something you did not author *is* the failure mode: get ahead of it rather than waiting for a second signal.
- **The next item is visibly large**: something you can already see will take several PRs. Start it in a fresh context rather than on top of twenty finished ones.

Never checkpoint with an item in flight, a dirty working tree, or a PR whose merge state you have not read back.

### What a checkpoint does, in order

1. **Verify the state before writing it down.** For every PR since the last checkpoint:

   ```bash
   gh pr view <N> --json state,mergedAt --jq '"state=\(.state) mergedAt=\(.mergedAt)"'
   ```

   `state=MERGED` with a non-null `mergedAt` is the only proof a merge merged. Confirm the working tree is clean, the suite is green, and every branch and worktree is accounted for. A checkpoint that records an unverified claim is worse than no checkpoint: the next context has no way to doubt it.

2. **Route every durable thing to its real home, and commit it.** The handoff is a pointer, never the store. The kinds of thing, and where each goes, are the project's to name; the routing is the rule. As its notes say, projects typically have:

   | If it is... | It goes in... |
   |---|---|
   | open work, including anything flagged `[NEEDS INPUT]` | the project's to-do list |
   | a finished item and its evidence | the project's archive of finished work |
   | a non-obvious codebase or environment gotcha | the project's field guide or notes file |
   | a close call worth re-examining on a date | the project's decisions file |
   | a rule for how to work in this repository | the project's notes file for agents |

   If something has no home in that table, it is open work: it goes in the to-do list. In a project with fewer of these, the backlog file absorbs open work and decisions.

3. **Write the checkpoint handoff** (contents below) in the project's handoff folder, as its notes say, and commit it alongside the routing edits from step 2, so the pointers and their targets land together.

4. **Keep going. Do not stop, and do not make the user do the clearing.** A session cannot clear its own context, since no tool exposes that. So the checkpoint's job is **not** to beg for a clear; it is to make one unnecessary, and to be a safe place to land if the user clears anyway. Three rules:

   - **Prevent the accumulation instead of curing it.** The context that used to force a clear was item 1's file reads, diffs and test output. Those belong in a **subagent**, whose context dies with it and which hands back only a conclusion. From the checkpoint onward, dispatch each item's investigate-and-build to an implementer rather than doing it inline. That is the actual fix; clearing was only ever the fallback. Tell each implementer to run tests in the foreground.
   - **Announce in one line, then continue in the same turn.** Name the checkpoint file and the counts, and **immediately start the next item**: no stopping, no waiting for a reply. A paused loop is a worse failure than a long context, because the queue stops moving and the user has to restart it.

     ```
     Checkpoint: <handoff file>. [N/M] done, <k> queued. Continuing with <next item>.
     ```
   - **If the user does clear, resume from the file without being told to.** The handoff is written to be read cold, so a cleared session picks the loop up from it. Mention a paste-ready resume line **only** if the user asks how to clear, or if a harness limit has actually been hit, never as a routine chore at every checkpoint.

### What the checkpoint handoff must carry

A normal handoff describes the state of play. A checkpoint handoff must also carry enough to **restart the loop cold**, because the loop's own state lives only in the conversation:

- **The queue, in full**: every item received this session in the order received, each marked shipped (with PR number and *verified* merge state), flagged `[NEEDS INPUT]`, or not started. This is what makes the `[N/M]` progress line survive the clear; `M` cannot be recovered from git.
- **Merged versus deployed**: the last deployed commit, and what is owed to production (migrations especially). "27 PRs merged, nothing deployed" is a real state, and `git log` does not show it.
- **Open and unverified**: any PR left open, its branch, its worktree path, and specifically what has *not* been checked about it. The resumed context must never merge on the strength of a PR description.
- **What the user said that has not been acted on**: asides, preferences, overrides, "while you're in there" remarks, anything that changes how a later item should be done. This class of thing exists only in the transcript, and the clear is precisely what destroys it.
- **The decisions log**: every autonomous call made with a lowest-risk default and the assumption behind it, plus every question banked for the end-of-session batch. Those banked questions are the session's output; losing them means asking the user to report their own items back to you.
- **Session settings**: screenshots ON or OFF, the scratch path captures are written to, and the URL of every page published so far, **the tracking page first**, since it is the channel the user is replying through and a new one cannot be published over the tab they have open.

Every bullet naming a durable thing links the real home it was written to in step 2. **A checkpoint handoff containing something that is not also in one of those homes is a bug in the handoff.** A checkpoint is a handoff you are guaranteed to read back.

Name it by date, as the project's handoff folder convention says, with `-2`, `-3` for later ones the same day. Each checkpoint gets its own file rather than overwriting the previous one; open it with a line naming the file it supersedes, and a resumer always takes the newest.

### Resuming after a clear

First act in the new context, before touching any item: read the newest checkpoint handoff, then the project's to-do list.

**If there is no checkpoint handoff, recover the published page links before writing anything.** A clear can happen without one, since the user can clear whenever they like. Look wherever the project records the pages it publishes (a log file, its notes), or ask the user for the tracking page's link as a last resort. Publishing without it mints a second tracking page against a tab the user is not reading, so recover it *before* the first publish, not after. Re-announce the loop in one line (`[N/M]`, screenshots on or off, next item) and pick it up. The loop's rules are unchanged by the clear: still auto-advancing, still draining the no-input queue first, still banking flagged questions for one batch at the end.

**Do not re-read the files from finished items to "get oriented."** The handoff is the orientation. Re-reading them rebuilds exactly the context the checkpoint was paid to discard.

## The Tracking Page — one artifact, published at intake, updated per item

The session's artifact is its record **from the first item, not the last**. A user who resumes a session that shipped seven PRs they never saw has nothing to react to; a page that exists from the first item lets them follow along and correct course early. The end-of-session summary below is the **last republish of this page**, not a separate page built at the end.

1. **Publish it as soon as the first batch of items is in hand**, before the first fix ships. One card per reported item, in the order reported, each seeded with its **before** evidence.
2. **Capture the before FIRST, and treat that as blocking.** Once the fix is in the working tree, the old state cannot be recaptured without stashing it back out. Use the user's own screenshot when they sent one (almost always a phone, so mobile); otherwise capture both viewports yourself **before touching the code**. An item whose before was never captured is an item the user cannot review.
3. **Republish to the same URL after every item**, adding the after shots, a line on what changed, the PR or commit, and the card's new state. Never mint a second page: a new page against a tab the user already has open is invisible to them. Its URL belongs in the checkpoint handoff.
4. **Every card carries a state and a note from the moment it exists.** A reported item the user can still redirect is worth more than a shipped one they can only complain about:

   | Card state | When | What it offers the user |
   |---|---|---|
   | **Reported** | queued, not started | a note: add detail, change the ask, drop it |
   | **In progress** | being worked now | the same note: it reaches you before the fix lands |
   | **Shipped** | built, verified, before/after shown | Looks right / Comment / Request revision / Revert it, plus a note |
   | **Flagged** | needs the user's input | the banked question, and a note answering it |

   **No button on a shipped card is pre-selected.** A card nobody has touched exports as "(no decision yet)", never as approval: a pre-selected default makes a skipped card look like a considered yes, and the page can't tell the difference. An untouched card is not a reason to revert or revise anything.
5. **One `Copy My Decisions` export covering every card in any state**, plain text, pasted back into chat. A note on a *Reported* card is a scope change to fold in before building; a note on a *Shipped* card is a revision item on top of it.
6. **The header carries the counts** (reported / in progress / shipped / flagged) and each card its state badge, so a glance on a phone answers "what has happened."
7. **It must be navigable, not just complete.** By item 20 the page is longer than anything anyone will scroll on a phone, and a card that needs the user is indistinguishable from twenty that do not. So the page carries:
   - **A docked bar**: `position: sticky; top: 0`, never `position: fixed`. A fixed bar overlays the document and **intercepts clicks on whatever sits under it**, which is how a decision button at the foot of a page becomes unclickable; a sticky bar occupies real space and cannot.
   - **Filter buttons with live counts**: Needs you / Being built / Merged / All, defaulting to **Needs you**, so the page opens on the user's work and not on the archive.
   - **Pagination**, about five cards a page, with a page counter and disabled ends. One long scroll is what makes items unfindable.
   - **A banner that answers "is anything waiting on me?" before they scroll at all**, and that says *nothing needs an answer* when nothing does. A stale count that implies the user owes replies is worse than no count: it sends them looking for items that do not exist.
8. **Watch the page budget.** Embedded `data:` images blow the Artifact size limit (about 16 MB) quickly: downscale each capture to its viewport width and re-encode (JPEG at about 0.7 quality) before embedding, and do not commit image-heavy review pages to the repository.

## End-of-Session Summary

When the user says they're done, or goes quiet after the last item, do two things. **The artifact here is the final republish of the tracking page, at its existing URL**, not a second page built from scratch.

**If the session checkpointed, the summary covers the whole session, not the surviving context.** Build it from the checkpoint handoffs plus the to-do list: those are the record; your context only holds the last stretch. Republish to the **URL recorded in the handoff** rather than publishing a second page, and write a final handoff that names the checkpoints it supersedes.

1. **A short chat summary**: items shipped (1 line + commit each), items flagged for discussion (1 line + reason each), anything left mid-queue.
2. **The published tracking page**, recapping the session as a standalone page the user can revisit or share later (follow any design guidance your environment provides for published pages, same as the sibling tools). Structure:
   - Header: date, item counts (shipped / flagged / total).
   - **Shipped** section: one card per item: title, one-line summary of the fix, commit SHA linked to the repository's commit URL if the remote is a known host (GitHub or GitLab), and the before/after screenshots if screenshot capture applied to that item.
     - **Mobile/Desktop toggle:** when an item has screenshots at both viewports, show a small segmented control (Mobile / Desktop) on that card that switches which before/after pair is shown, **mobile selected by default**, since these reports usually originate from a phone. Don't show both viewports stacked at once; that is what causes mismatched mobile-before/desktop-after comparisons. If only one viewport has a screenshot for that item, show it directly with a small label naming the viewport, no toggle.
   - **Flagged for discussion** section: one card per item: title, the reason it was escalated, and which follow-up path it was routed to (`design-review`, `style-guide`, `brainstorming`, or "needs your decision" for anything else).
   - **Left mid-queue** section (only if the session ended before an item finished): what state it's in and what's needed to pick it back up.
   - **A decision per shipped item, and an export.** Seeing a before/after with nowhere to say "not quite" makes the page a dead end. Each shipped card carries four buttons, **none of them pre-selected**:

     | State | Means | What you do with it |
     |---|---|---|
     | **Looks right** | Nothing wanted. | Nothing. |
     | **Comment** | A remark worth keeping, no change asked for. | Record it where it belongs: the project's decisions file or the archive entry. |
     | **Request revision** | The fix is wrong or incomplete. | A new queue item, scoped to the user's words, on top of the shipped one. |
     | **Revert it** | Ship it back out. | Revert the commit, then ask what should replace it. |

     Plus a free-text note on every card, and one **Copy My Decisions** button producing plain text the user pastes back into chat. A card with no button pressed and no note exports as "(no decision yet)". Flagged items keep their own note field; the user's answer to a banked question arrives the same way.
   - This is still a record first: it does not block and nothing waits on it. It starts private; the user shares it if they want to.

## Common Mistakes

| Rationalization | Reality |
|---|---|
| "I'll capture the before when I get to the screenshots" | The before is gone the moment you edit the file. Capture it at intake, before the first change, or that item has nothing to review against. |
| "I'll build the artifact at the end, when I know what shipped" | The page is published at intake and republished per item. An item the user can still redirect while it is *Reported* is worth more than one they can only complain about after it ships. |
| Pre-selecting "Looks right" so a silent page reads as agreement | A skipped card then looks like a considered yes. Leave every button unpressed; an untouched card exports as "(no decision yet)". |
| Giving the docked bar `position: fixed` | It intercepts clicks on the controls beneath it, so a decision button at the page foot stops working, silently. Use `position: sticky; top: 0`. |
| Setting the page's bottom padding on a bare type selector (`main { padding-block: ... }`) | A class on the same element (`.wrap { padding: 0 20px }`) wins on specificity and zeroes it, so the bar lands on top of the last card. Use `main.wrap`, and verify by clicking the last control in a headless browser. |
| Publishing a fresh artifact each time instead of republishing the tracked URL | A new page against the tab the user already has open is invisible to them. Republish the recorded URL; recover it from where the project records published pages if a clear lost it. |
| "This UX call is ambiguous, but I can make a reasonable choice and just note what I'd have asked" | Documenting the assumption doesn't substitute for flagging. Ambiguous UX/design decisions always escalate, full stop. |
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
| Flagging a bug to the batch just because it's hard to debug | Bugs and investigations aren't escape-hatch items. Debug them autonomously; defer only a specific decision or fact the user alone holds, and only after real investigation. |
| "Clearing would lose context I need" | The context you're afraid to lose is exactly what the checkpoint writes down. What a clear actually loses is item 1's diffs and test output, which you are paying for on every turn. |
| "I'll checkpoint when the context actually gets tight" | A long session can stop with no warning it could act on. Checkpoint on the trigger (major + unrelated, five items, half spent), not on a feeling. |
| Stopping at a checkpoint to wait for the user to clear the conversation | A paused loop is worse than a long context: the queue stops moving and the user has to restart it. Announce the checkpoint in one line and start the next item in the same turn. |
| Doing each item's reads, diffs and test output inline, then blaming the context | That is the accumulation the clear was invented to cure. Put the item in a subagent and keep the conclusion; the context never grows in the first place. |
| Writing the open decision, flagged item or gotcha into the handoff and nowhere else | A handoff is a pointer, never a store. File it in the project's to-do list, archive, field guide or decisions file first, then link it. |
| Checkpointing mid-item, or right after pushing, without reading the merge state back | Checkpoint only at an item boundary with a clean tree, and only after `state=MERGED` plus a non-null `mergedAt`. An unverified claim in a handoff is worse than no handoff. |
| Re-reading the finished items' files after a clear to get oriented | The handoff is the orientation; re-reading them rebuilds the exact context the checkpoint was paid to discard. |

## Portability

This skill assumes:
- A repository-root backlog file (a to-do list; `TODO.md` by convention) is the source of truth for queue state. If the target project uses a different backlog location or format, adapt the entry templates above to it.
- The project uses GitHub pull requests (`gh` authenticated) and the session may merge its own PRs to the main branch without human approval. **Verify both before adopting the skill in a new project.** If the project requires human review on every PR, the loop still works, but say at session open that items will land as open PRs rather than merged ones, and treat that as the session's shipping definition.
- **Check whether merging deploys.** Landing on the main branch should be safe for the target project: no auto-deploy-on-merge, or the project owner has explicitly accepted that. If the project auto-deploys, get that turned off first, or add an explicit "hold for manual deploy" step after the merge. Never call a merged item "deployed" unless you have confirmed it is.
- The checkpoint protocol assumes somewhere to put a dated handoff (the project's handoff folder, as its notes say) and a real home per kind of durable thing (its to-do list, archive, field guide, decisions file and notes file for agents). **The routing is the rule; the file names are the project's.** In a project with fewer of these, the backlog file absorbs open work and decisions, and the handoff still may not be the only home for anything.
- Uses the `Artifact` tool for the tracking page, which carries a decision per shipped item and a copy-back export. **Mid-session the loop still has no blocking review step by design**: that is what keeps it fast. The user reviews on the page when they choose, and nothing waits on it.

## Where the page goes

The project chooses with `PROOFS_PAGES`, set in the project's `.claude/settings.json` "env" block (or a line in CLAUDE.md: "proofs pages: file"). Values:

- `artifact`: publish as a private claude.ai artifact (a link that opens on phone and computer). This is the default when publishing is available.
- `file`: save the page as an HTML file (default folder `.proofs/pages/`; add it to .gitignore) and open it in the browser (`open` on macOS, `xdg-open` on Linux, `start` on Windows). This is the default when artifacts are not available. Reuse the same file path for later rounds so the page updates in place instead of piling up.
- `wifi`: same as `file`, plus serve only a folder that holds this review's page(s) (for example `.proofs/pages/<review-name>/`, so older pages are not listed to the network) on the local network (`python3 -m http.server <port> --bind <the computer's local IP>` from that folder) and print the address so a phone on the same Wi-Fi can open it. This mode never uploads the page and never uses a public tunnel. Stop the server when the review is done. Use `wifi` only on a private network you trust, never on public or shared Wi-Fi.

If `artifact` is chosen but publishing fails or is not available, fall back to `file` and say so in one line. Everything on the page works the same in every mode. The page's copy button gives the user text to paste back. Copy buttons must fall back to a selectable text box (select all) when `navigator.clipboard` is missing or the write fails (a page served over http on a local IP is not a secure context, so the clipboard is often unavailable), and must never show "Copied" unless the copy actually succeeded.

## Changelog

- **1.10.2** (2026-11-17): Copy buttons now fall back to a selectable text box when the clipboard is unavailable (as on a Wi-Fi-served page), and `wifi` mode is limited to a private network you trust. The superpowers skills are optional, with a plain fallback when they are not installed.
- **1.10.1** (2026-11-16): New section "Where the page goes": a project can choose an artifact, a local file, or a file served on its own Wi-Fi.
- **1.10.0** (2026-11-16): Merged into proofs: generic, no project-specific steps.
