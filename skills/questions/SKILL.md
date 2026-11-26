---
name: questions
version: 1.4.0
allowed-tools:
  - Read(/${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/shared/review_page/review_page.py *)
description: Use when you need the user to answer or decide anything — one question or several piling up in chat, including decisions to answer later or from a phone — as real answer controls with a recommended pick and a copy-back export. On working-log's session page they still come from here, at the top. Checks: qa-checklist.
---

# Questions

Questions the user answers on a page instead of in chat: real controls, one pass,
one copy button, one pasted block back.

**Results first.** Nothing matters more than a result the user wants. Save tokens by cutting waste, never by cutting a check, an option or a revise pass the result needs (full text: `../../reference/house-rules.md`).

**Core principle: the page is an input surface, not a document.** The most common
failure is a nicely typeset read-only page that tells the user to answer in chat by
question number. That is the thing they were trying to get away from.

## When it starts on its own

**The first time a session has any question, confirmation or "please confirm you
read this" for the user, put it on a page — do not wait to be asked.** Chat still
gets a short copy of the question with the link, because chat is what the user
replies to; the page is what they answer on.

- **The project uses working-log's session page** (its notes say so, or the session
  already has one): add the question to that page's **Waiting on you** section and
  republish the same URL. The `working-log` skill owns that page; this skill owns
  how the questions on it are written.
- **Otherwise:** publish a standalone questions page (below), one per work-stream.

Not for: a single blocking question you need answered this second (just ask), a
yes/no you could have defaulted yourself, checks the user must run after a deploy
(the `qa-checklist` skill), or choosing between visual mockups of a page
(the `design-review` skill).

Where this skill mentions how the project handles files, commits or publishing, it
defers to the project's own notes (`CLAUDE.md` or the equivalent).

## Open questions come first

**Open questions are the first thing on the page, directly under the sticky bar,
highlighted for action.** Reports, context, screenshots and settled items go below
them or folded away. A reader who has to scroll past a report to find what you are
asking does not find it. The builder enforces this: on a questions page and on the
session page, the questions section renders first, and the heading, intro and facts
move below the sections that need action. The build's check fails a page where
anything comes before the open questions.

## Building it

**Needs the whole plugin.** This skill reads shared files at `../../reference/` and `../../shared/`, relative to its folder. If they are missing, the skill was copied on its own: install the whole plugin (`/plugin install proofs@proofs`) rather than recreating them.

Read `../../reference/review-page.md` first. Do not hand-write the page's JavaScript.

- **On the session page:** the `questions` list in working-log's session spec
  (`"mode": "session"`).
- **Standalone:** `"mode": "questions"` with a `questions` list, built with
  `python3 ${CLAUDE_PLUGIN_ROOT}/shared/review_page/review_page.py .proofs/questions.json --out .proofs/pages/questions.html`.
  `../../shared/review_page/examples/questions.json` is a working example.
  Fill `project` with `name`, `session` and `repo`, taking the session name the way the `working-log` skill does (the session's own name, else one named for the work, kept for the life of the page): the page's header shows the proofs mark, this skill's name, the project and the session, so the user can match the page to its session at a glance.

The builder supplies real radio controls, a notes field on every question ("Or in
your own words", which invites the answer you didn't offer), the sticky "N of M
answered" tally, Clear (with a confirm, standalone page), persistence, the copy-back
export with its clipboard fallback, and the visual treatment. The standalone page
is one dark world, a neutral near-black ground with a violet accent, the same in
either theme; on the session page the same cards take the log's light and dark
tokens. The accent marks selection and the primary action; green means answered,
never "recommended".

## What stays yours

1. **A stable `qid` on every question**, shown on the page and emitted in the export.
   A short slug, assigned once and never changed, even as the wording is edited or
   the question moves between rounds. Position and numbering are not stable; the slug is.
2. **Mockups for visual questions** (`mockups_html`). If the question is *where*
   something sits or *how* it looks, draw the options at the real width. Lettered
   descriptions of layouts are not answerable.
3. **Full option text** as each option's `value`, never a bare letter. "Q2: C" is
   meaningless out of context, and worse, it looks meaningful.
4. **A settled log** (`decided`). Answered questions leave the open list at once and
   go to the Decided list, compacted, never deleted: that list is why the user doesn't
   have to remember what they already told you.

## Writing the questions

- **The ask, then why it matters, then the options.** Each option gets a real
  trade-off, not a label. "Overlay: covers the inputs you're about to fill" beats "Overlay".
- **Recommend one, and say why** (`recommended: true`). A menu with no recommendation
  pushes work back onto the user.
- **Include the option you think is wrong** if it's genuinely defensible. It's how
  you find out your recommendation was wrong.
- **Decisions the user delegated to you** go on the page too, as a stated call with
  the argument for it, plus an "overrule me" option. Never bury one in prose.
- **Keep a parked list.** Things you found but aren't doing this cycle, so they
  aren't silently dropped (below the questions, in `after_html`).

## Export format

Answers come back as pasted text, possibly out of order, possibly from a different
round, possibly while you are working on a different project, so the export
identifies itself:

```
[questions v1.3 — answers]
project: acme-app
stream:  suggestion dropdown
round:   2
artifact: <the page's published URL>
sent:    2026-07-27T21:58Z

Q spec-approval (raised r2) | Does the written spec match what you agreed?
  -> Approved - write the implementation plan
  note: check the flip-up on a short viewport

Q placement (raised r1) | Where should the dropdown sit on the item row?
  -> (UNANSWERED)
```

`project` / `stream` stop a block pasted into the wrong session from being applied to
the wrong work. `round` and each question's `(raised rN)` say whether an answer is
fresh or a late reply to something asked two rounds ago. `artifact` lets you
republish the right URL. `sent` orders two pastes that arrived out of order.
`(UNANSWERED)` is explicit because silence is ambiguous. On the session page the
same `Q` blocks arrive under `--- Questions ---` inside working-log's export.

## Workflow

1. Write the spec and build the page to a stable file path. Publish it with `capabilities: {"db": {}, "comments": {}}`.
2. Give the user the URL in chat with a one-line copy of what you are asking.
3. **Stop at blocking questions.** Do work that doesn't depend on the answers; don't
   guess past one and build on the guess.
4. When answers arrive (read from the page's database, pasted, or announced by a **Send to Claude** that woke you): apply them, move those questions to `decided`, add whatever
   new questions the answers raised, and **rebuild and republish the same file path**
   so the URL is unchanged. Do this before any other work the answers ask for.
5. Never mint a second URL for the same work-stream. The user has that tab open.

A question with `options: []` and a `notes_label` is a text-box question: what the reader types is the answer, and it exports as `-> <text>`.

**Read answers from the page first.** A published page saves every answer in its own database when you publish it with `capabilities: {"db": {}, "comments": {}}` (a republish that leaves `capabilities` out keeps both; the first publish of an older page must name both, and never pass `{}`). Before you ask for a paste, and whenever the user says they answered, read them: `ArtifactData` `list` of `proofs-answers` with `out_dir`, then `review_page.py --answers <page> --rows <out_dir>` prints the same text as the Copy export. The database comes first and a pasted export second; if they differ, the newer (`updated_at` against the export's stamp) wins, and say so. Anyone the page is shared with can write answers; pages are private by default. Details: "Answers without Copy" in `../../reference/review-page.md`. The page's bar says **Saved**, **Saving…** or **Not saved yet**; if the user says it shows Not saved yet, ask for the Copy export, which always has everything.

## Sent to Claude: what the session does

The page's bar has **Send to Claude** beside Copy (the page must be published with `capabilities: {"db": {}, "comments": {}}`). A tap saves the answers, then posts a short comment ("<session> page vN: answered q1, q2 (2 of 3). Read proofs-answers on this artifact.") that wakes this session. It arrives as a `<task-notification>` of type `artifact-auto-react` naming the artifact and the thread, after the harness has already posted an automatic reply there.

1. **Republish the page first, before any other work.** Read `proofs-answers` with `ArtifactData` `list` and `review_page.py --answers`, apply them exactly as you would a paste (answered questions move to Decided, a log entry "Got your answers"), and republish to the same file path. That republish is the user's confirmation: open views reload by themselves and the bar says "Claude picked up your answers". The page cannot read the comment thread, so a reply there alone looks like nothing happened.
2. **Never post a second reply** in the thread: the harness already replied.
3. Do the work the answers ask for, then resolve the thread with `ArtifactComments`.

**Limits.** It works only while the session that published the page is open and its watch on the page is armed (every publish arms it). After `/clear`, a closed terminal or a new session, the button says the session isn't listening and Copy is the way; a new session re-arms it by watching the URL the user gives it. Editors only: a reviewer the page is shared with uses Copy. The automatic reply is posted by the harness, not by the page or the session.

## Common mistakes

| Mistake | Why it fails |
|---|---|
| Read-only page, "answer in chat by letter" | This is the exact problem the user asked you to solve |
| Questions below a report or log | The user scrolls past what needs them, or never finds it |
| Bare letters in the export | You get "Q2: C" with no record of what C was |
| Renumbering questions between rounds | A late answer to "Q2" lands on whatever is Q2 now |
| Deleting answered questions | Destroys the decision record; the user re-litigates settled things |
| New URL per round | Their open tab goes stale and they answer the wrong version |
| Prose describing a layout | If the question is visual, prose is unanswerable |
| Proceeding on a guess | You build on an assumption and throw the work away |

## Verifying

The build runs its own check, including the questions-first order. `--smoke`
answers, types a note, copies, reloads, confirms the questions sit directly under
the sticky bar, and checks for sideways scroll at 1280 and 390.
Run `--smoke`. If it reports Playwright missing, run the one-line install it prints (it uses your installed Google Chrome and downloads no browser), then run `--smoke` again; if it still cannot run, say on the page and in chat that the self-check did not run.
Then look at one screenshot at a desktop and a phone width: the checks
prove behavior, not that your mockups are readable.

## Where the page goes

Before you publish or save the page, read `../../reference/where-the-page-goes.md` (the path is relative to this skill's folder). The project's `PROOFS_PAGES` setting picks artifact, file or wifi, and that file says what each means and how copy buttons must fall back.
