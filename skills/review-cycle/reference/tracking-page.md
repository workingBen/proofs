# The Tracking Page — one artifact, published at intake, updated per item

Part of the `review-cycle` skill; read when SKILL.md points here.


The session's artifact is its record **from the first item, not the last**. A user who resumes a session that shipped seven PRs they never saw has nothing to react to; a page that exists from the first item lets them follow along and correct course early. The end-of-session summary (`end-of-session-summary.md`, beside this file) is the **last republish of this page**, not a separate page built at the end.

1. **Publish it as soon as the first batch of items is in hand**, before the first fix ships. One card per reported item, in the order reported, each seeded with its **before** evidence.
2. **Capture the before FIRST, and treat that as blocking.** Once the fix is in the working tree, the old state cannot be recaptured without stashing it back out. Use the user's own screenshot when they sent one (almost always a phone, so mobile); otherwise capture both viewports yourself **before touching the code**. An item whose before was never captured is an item the user cannot review.
3. **Republish to the same URL after every item**, adding the after shots, a line on what changed, the PR or commit, and the card's new state. Never mint a second page: a new page against a tab the user already has open is invisible to them. Its URL belongs in the checkpoint handoff.
4. **Every card carries a state and a note from the moment it exists.** A reported item the user can still redirect is worth more than a shipped one they can only complain about:

   | Card state | When | What it offers the user |
   |---|---|---|
   | **Reported** | queued, not started | a note: add detail, change the ask, drop it |
   | **In progress** | being worked now | the same note: it reaches you before the fix lands |
   | **Shipped** | built, verified, before/after shown | Looks right / Comment / Request revision / Revert it, plus a note |
   | **In design review** | sent to `design-review` or another sibling skill | a link to that skill's page, where the user decides |
   | **Saved as a to-do** | too big for the session | where it was saved, and a note to change its scope |
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

## Common mistakes

| Rationalization | Reality |
|---|---|
| "I'll capture the before when I get to the screenshots" | The before is gone the moment you edit the file. Capture it at intake, before the first change, or that item has nothing to review against. |
| "I'll build the artifact at the end, when I know what shipped" | The page is published at intake and republished per item. An item the user can still redirect while it is *Reported* is worth more than one they can only complain about after it ships. |
| Pre-selecting "Looks right" so a silent page reads as agreement | A skipped card then looks like a considered yes. Leave every button unpressed; an untouched card exports as "(no decision yet)". |
| Giving the docked bar `position: fixed` | It intercepts clicks on the controls beneath it, so a decision button at the page foot stops working, silently. Use `position: sticky; top: 0`. |
| Setting the page's bottom padding on a bare type selector (`main { padding-block: ... }`) | A class on the same element (`.wrap { padding: 0 20px }`) wins on specificity and zeroes it, so the bar lands on top of the last card. Use `main.wrap`, and verify by clicking the last control in a headless browser. |
| Publishing a fresh artifact each time instead of republishing the tracked URL | A new page against the tab the user already has open is invisible to them. Republish the recorded URL; recover it from where the project records published pages if a clear lost it. |
