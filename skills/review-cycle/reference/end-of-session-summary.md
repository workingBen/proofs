# End-of-Session Summary

Part of the `review-cycle` skill; read when SKILL.md points here.


When the user says they're done, or goes quiet after the last item, do two things. **The artifact here is the final republish of the tracking page, at its existing URL**, not a second page built from scratch.

**If the session checkpointed, the summary covers the whole session, not the surviving context.** Build it from the checkpoint handoffs plus the to-do list: those are the record; your context only holds the last stretch. Republish to the **URL recorded in the handoff** rather than publishing a second page, and write a final handoff that names the checkpoints it supersedes.

1. **A short chat summary**: items shipped (1 line + commit each), items flagged for discussion (1 line + reason each), anything left mid-queue.
2. **The published tracking page**, recapping the session as a standalone page the user can revisit or share later (follow any design guidance your environment provides for published pages, same as the sibling tools). Structure:
   - Header: date, item counts (shipped / flagged / total).
   - **Shipped** section: one card per item: title, one-line summary of the fix, commit SHA linked to the repository's commit URL if the remote is a known host (GitHub or GitLab), and the before/after screenshots if screenshot capture applied to that item.
     - **Mobile/Desktop toggle:** when an item has screenshots at both viewports, show a small segmented control (Mobile / Desktop) on that card that switches which before/after pair is shown, **mobile selected by default**, since these reports usually originate from a phone. Don't show both viewports stacked at once; that is what causes mismatched mobile-before/desktop-after comparisons. If only one viewport has a screenshot for that item, show it directly with a small label naming the viewport, no toggle.
   - **Sent to review** section: one card per item routed to a sibling skill, with that page's link and whether the user has decided yet.
   - **Saved as to-dos** section: one card per item, with where it was saved.
   - **Flagged for discussion** section: one card per item: title and the banked question.
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
