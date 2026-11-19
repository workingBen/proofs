---
name: qa-checklist
version: 1.0.0
description: Use when shipped work needs checks only the user can run — a real phone, production data, a service you cannot reach — as a PASS / FAIL / COULDN'T TEST list ordered by consequence, with its own export. Checks only: decisions go to questions, visual options to design-review, and working-log hosts the list on its session page.
---

# QA Checklist

A run sheet for the checks you could not do yourself, answered on a page instead of
in chat, where a list of "please verify" items scrolls away for exactly the reason
questions do.

## When it starts on its own

**The first time shipped work has a check only the user can run, put it on a page —
do not wait to be asked.** Chat gets a short copy with the link.

- **The project uses working-log's session page:** add the checks to that page's
  **Checks for you** section (it sits directly under Waiting on you) and republish
  the same URL. The `working-log` skill owns that page; this skill owns how the
  checks on it are written.
- **Otherwise:** publish a standalone checklist page (below).

Not for: decisions or confirmations (the `questions` skill), choosing between
mockups (the `design-review` skill), or checks already green in automated tests.

**Do not post a checklist before the work ships.** An unrunnable list teaches the
user to ignore the section.

## Building it

Read `../../reference/review-page.md` first. Do not hand-write the page's JavaScript.

- **On the session page:** the `qa` list in working-log's session spec.
- **Standalone:** `"mode": "questions"` with only a `qa` list, built with
  `python3 ../../shared/review_page/review_page.py spec.json --out checks.html`.
  `../../shared/review_page/examples/qa-checklist.json` is a working example. A page
  with checks and no questions exports as `[qa-checklist v1.0 — results]`; set
  `copy_label` to "Copy my results".

If the same standalone page also asks questions, the questions render first (the
`questions` skill's questions-first rule) and the checks follow.

## Each check carries

- a stable `qaid`, assigned once and never renumbered
- **what to do** (`check`), as an action the user performs, not a feature name
- **what "pass" looks like**, stated explicitly in `why_html`. "Expected: it deletes
  cleanly" is checkable; "verify deletion works" is not
- **why it is on the list**, usually the failure it used to produce, so the user can
  judge severity when it fails
- a notes prompt (`notes_label`) asking for the specific evidence you need. "Paste the
  image URL if it failed" beats "notes"

The page answers each with PASS / FAIL / COULDN'T TEST (the honest answer for a check
blocked by an earlier failure) and counts checks in their own tally (`QA 2 of 7`, or
`checks 2 of 7` on the session page), so they never inflate the open-questions number.

## Rules that matter

- **Order by consequence.** A crash or data-loss check goes first.
- **Say plainly which items you could not verify yourself, and why.** A check you
  were structurally unable to run (no WebKit in the sandbox, no production
  credentials, an egress-blocked image host) is the whole reason the list exists.
  Mark those explicitly.
- **Name the expected non-bugs.** If shipped behavior will look broken but is simply
  not in scope yet, say so on the page, or it comes back as a regression report.
- **State dependencies between items.** "Depends on qa-photos passing first" saves a
  confusing FAIL.
- **Clear what is done.** When results come back, passed checks leave the list
  (onto the session page's Decided list, or the standalone page's settled notes);
  a FAIL stays until its fix ships and is checked again.

## Export format

Results export in their own block. `(NOT CHECKED)` marks an item the user has not
reached, deliberately distinct from a question's `(UNANSWERED)`:

```
[qa-checklist v1.0 — results]
project: acme-app
stream:  attachments release
round:   1
artifact: <the page's published URL>
sent:    2026-07-27T21:58Z

--- QA results ---

QA qa-delete-item | Delete an item that has an attachment
  -> PASS

QA qa-photos | Do inspection photos appear at all — thumbnail and zoom
  -> FAIL
  note: still a broken glyph. URL: https://cdn.example.com/photos/abc123
```

On the session page the same `--- QA results ---` block arrives inside
working-log's export, after the questions.

## Verifying

The build runs its own check. Run `--smoke` when Playwright is available, then look
at one screenshot at a desktop and a phone width. Republish to the same file path so
the URL never changes.

## Where the page goes

Before you publish or save the page, read `../../reference/where-the-page-goes.md` (the path is relative to this skill's folder). The project's `PROOFS_PAGES` setting picks artifact, file or wifi, and that file says what each means and how copy buttons must fall back.
