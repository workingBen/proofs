# Checkpoints — Handoff and Clear Between Features

Part of the `review-cycle` skill; read when SKILL.md points here.


A review cycle accumulates. By item 20 the context still carries item 1's file reads, diffs and test output, and every turn pays for all of it. A long session once merged 27 pull requests in a single context and ran out of its budget mid-flight: it died with a PR open and unverified, and the entire queue (what had been reported, what had shipped, what the user had said and no one had acted on) existed nowhere but the conversation. Checkpointing exists so that never has to be reconstructed under pressure.

A checkpoint is three things in order: **route everything durable to its real home, write a resume handoff, clear the context and resume from the file.**

## When to checkpoint

Checkpoint at the **next item boundary** after any one of these becomes true. Never mid-item. A session that dispatches its per-item work to subagents from the start will rarely reach these at all, and that is the point.

- **A major item just finished and the next queued item is unrelated.** *Major*: it needed its own branch and PR, or a subagent, or touched more than a handful of files, or took several rounds of tests to land. *Unrelated*: starting the next item means opening a different set of files, with no shared model, controller, view or feature area with the one just finished. **Both must hold.** A major item followed by three more tweaks to the same view is not a checkpoint point; the context you are carrying is the context the next item needs.
- **The checkpoint setting's number of items (`PROOFS_CHECKPOINT_ITEMS`, default 5) have shipped since the last checkpoint**, related or not. A count is here rather than left to judgment because a long session never recognized a boundary it was willing to stop at.
- **Context is more than half spent**, or a compaction or summarization warning has appeared. Being summarized by something you did not author *is* the failure mode: get ahead of it rather than waiting for a second signal.
- **The next item is visibly large**: something you can already see will take several PRs. Start it in a fresh context rather than on top of twenty finished ones.

Never checkpoint with an item in flight, a dirty working tree, or a PR whose merge state you have not read back.

## What a checkpoint does, in order

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

## What the checkpoint handoff must carry

A normal handoff describes the state of play. A checkpoint handoff must also carry enough to **restart the loop cold**, because the loop's own state lives only in the conversation:

- **The queue, in full**: every item received this session in the order received, each marked shipped (with PR number and *verified* merge state), flagged `[NEEDS INPUT]`, or not started. This is what makes the `[N/M]` progress line survive the clear; `M` cannot be recovered from git.
- **Merged versus deployed**: the last deployed commit, and what is owed to production (migrations especially). "27 PRs merged, nothing deployed" is a real state, and `git log` does not show it.
- **Open and unverified**: any PR left open, its branch, its worktree path, and specifically what has *not* been checked about it. The resumed context must never merge on the strength of a PR description.
- **What the user said that has not been acted on**: asides, preferences, overrides, "while you're in there" remarks, anything that changes how a later item should be done. This class of thing exists only in the transcript, and the clear is precisely what destroys it.
- **The decisions log**: every autonomous call made with a lowest-risk default and the assumption behind it, plus every question banked for the end-of-session batch. Those banked questions are the session's output; losing them means asking the user to report their own items back to you.
- **Session settings**: screenshots ON or OFF, the scratch path captures are written to, and the URL of every page published so far, **the tracking page first**, since it is the channel the user is replying through and a new one cannot be published over the tab they have open.

Every bullet naming a durable thing links the real home it was written to in step 2. **A checkpoint handoff containing something that is not also in one of those homes is a bug in the handoff.** A checkpoint is a handoff you are guaranteed to read back.

Name it by date, as the project's handoff folder convention says, with `-2`, `-3` for later ones the same day. Each checkpoint gets its own file rather than overwriting the previous one; open it with a line naming the file it supersedes, and a resumer always takes the newest.

## Resuming after a clear

First act in the new context, before touching any item: read the newest checkpoint handoff, then the project's to-do list.

**If there is no checkpoint handoff, recover the published page links before writing anything.** A clear can happen without one, since the user can clear whenever they like. Look wherever the project records the pages it publishes (a log file, its notes), or ask the user for the tracking page's link as a last resort. Publishing without it mints a second tracking page against a tab the user is not reading, so recover it *before* the first publish, not after. Re-announce the loop in one line (`[N/M]`, screenshots on or off, next item) and pick it up. The loop's rules are unchanged by the clear: still auto-advancing, still draining the no-input queue first, still banking flagged questions for one batch at the end.

**Do not re-read the files from finished items to "get oriented."** The handoff is the orientation. Re-reading them rebuilds exactly the context the checkpoint was paid to discard.

## Common mistakes

| Rationalization | Reality |
|---|---|
| "Clearing would lose context I need" | The context you're afraid to lose is exactly what the checkpoint writes down. What a clear actually loses is item 1's diffs and test output, which you are paying for on every turn. |
| "I'll checkpoint when the context actually gets tight" | A long session can stop with no warning it could act on. Checkpoint on the trigger (major + unrelated, the checkpoint count of items, half spent), not on a feeling. |
| Stopping at a checkpoint to wait for the user to clear the conversation | A paused loop is worse than a long context: the queue stops moving and the user has to restart it. Announce the checkpoint in one line and start the next item in the same turn. |
| Doing each item's reads, diffs and test output inline, then blaming the context | That is the accumulation the clear was invented to cure. Put the item in a subagent and keep the conclusion; the context never grows in the first place. |
| Writing the open decision, flagged item or gotcha into the handoff and nowhere else | A handoff is a pointer, never a store. File it in the project's to-do list, archive, field guide or decisions file first, then link it. |
| Checkpointing mid-item, or right after pushing, without reading the merge state back | Checkpoint only at an item boundary with a clean tree, and only after `state=MERGED` plus a non-null `mergedAt`. An unverified claim in a handoff is worse than no handoff. |
| Re-reading the finished items' files after a clear to get oriented | The handoff is the orientation; re-reading them rebuilds the exact context the checkpoint was paid to discard. |
