---
name: questions
version: 1.0.1
description: Use when you have a question, decision or confirmation for the user that must not scroll away in chat, or several piling up — asks them as real answer controls with a stable id, a recommended option, notes and a copy-back export. Questions only; qa-checklist covers checks, design-review visual options, and working-log hosts these on its session page.
---

# Questions

Questions the user answers on a page instead of in chat: real controls, one pass,
one copy button, one pasted block back.

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
  `python3 ../../shared/review_page/review_page.py spec.json --out questions.html`.
  `../../shared/review_page/examples/questions.json` is a working example.

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

1. Write the spec and build the page to a stable file path. Publish it.
2. Give the user the URL in chat with a one-line copy of what you are asking.
3. **Stop at blocking questions.** Do work that doesn't depend on the answers; don't
   guess past one and build on the guess.
4. When answers arrive: apply them, move those questions to `decided`, add whatever
   new questions the answers raised, and **rebuild and republish the same file path**
   so the URL is unchanged.
5. Never mint a second URL for the same work-stream. The user has that tab open.

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

The build runs its own check, including the questions-first order. Run `--smoke`
when Playwright is available: it answers, types a note, copies, reloads, confirms
the questions sit directly under the sticky bar, and checks for sideways scroll at
1280 and 390. Then look at one screenshot at a desktop and a phone width: the checks
prove behavior, not that your mockups are readable.

## Where the page goes

Before you publish or save the page, read `../../reference/where-the-page-goes.md` (the path is relative to this skill's folder). The project's `PROOFS_PAGES` setting picks artifact, file or wifi, and that file says what each means and how copy buttons must fall back.
