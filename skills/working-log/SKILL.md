---
name: working-log
version: 1.6.1
description: Use when the user cannot reliably read terminal output, says your questions get lost in terminal output, prefers a durable page over chat scrollback, is answering from a phone, asks to answer several questions at once, wants a link to work through and paste answers back from, or wants open decisions reviewable asynchronously. Invoke as /proofs:working-log.
---

# Working Log

A published page that replaces chat as the channel Claude talks *to* the user through.

Chat scrollback is lossy: it cannot be re-read after a restart, it cannot be ticked
off, and if the user's terminal renders badly it is not a channel at all. This turns
Claude's side of the conversation into a page — newest message first, a **Read this**
tick per entry, option buttons where a question is being asked, and one
**Copy my replies** button producing plain text the user pastes back.

The user's direction still arrives through chat. **Pasting works when reading does
not**, and that asymmetry is the whole design.

## When to use

- The user says they cannot read terminal output, or output is garbled/truncated.
- They ask for `/proofs:working-log`, or for messages "in the artifact" rather than in chat.
- A long unattended run where they will return to a lot of accumulated state.
- Any point where you need a **confirmed read** — a credential to revoke, a
  destructive step, an assumption you are about to build on.
- Questions are piling up faster than the user can answer them inline, they are on
  a phone or away, or a decision needs mockups to be answerable at all: use the
  **questions-for-you mode** below.

Not for: the end-of-session recap of a `review-cycle` (that has its own summary
artifact), or a visual design review (`design-review` owns that shape). Don't use
the questions mode for a single blocking question you need answered right now (just
ask) or a yes/no you could have defaulted yourself. This is the ongoing channel
between those.

Where this skill mentions how the project handles files, worktrees, commits or
publishing habits, it defers to the project's own notes (`CLAUDE.md` or the
equivalent). Follow them.

## Required frontmatter — tie it to its project AND its session

The page carries a **fixed project bar** at the top, always visible, so the user can
tell one project's log from another's at a glance. This is not decoration: once two
projects both have a log, two tabs look identical without it.

```
PROJECT NAME · SESSION NAME · owner/repo · Working log
```

Take the project name from the repo's own `CLAUDE.md` (its overview line or
equivalent) and the slug from `git remote -v`. **Read them; do not guess** — a wrong
repo slug on a page about credentials is actively misleading.

**The session name is required, and it is the disambiguator.** One project can have
several logs open at once, because several sessions can run against the same repo at
once — and then the project bar is *identical on every tab*, which is the failure the
bar was supposed to prevent, one level down. The classic accident is pasting replies
into the wrong session. The session name is the only field that differs, so:

- **Put it first in the `<title>`**, before the project — `SESSION · PROJECT log`.
  Tab titles truncate from the right, and the field that tells tabs apart is useless
  if it is the part that gets cut.
- **Give it the accent in the project bar**, so it reads before anything else.
- **Put it in the export too** (see below). A pasted reply that lands in the wrong
  session is exactly the thing being prevented, and the paste is where it happens.

Take it from the session's own name if it has one; otherwise name it for the work
(`credential-rotation`, `pr-qa-review`) and keep it stable for the life of the log.

## Building it: the shared builder

Write the content; the builder writes the page. Read `../../reference/review-page.md` first: `"mode": "log"` for the working log, `"mode": "questions"` for questions-for-you, built with `python3 ../../shared/review_page/review_page.py spec.json --out log.html`. Do not hand-write the page's JavaScript. Load `artifact-design` first if it is available; this is a utilitarian tool page, not editorial: real type hierarchy, no hero.

The builder supplies the mechanics: the sticky project bar (session accented) and status bar ("N / M read", version marker, copy button), a **Read this** tick that dims an entry, option groups stored one answer per group (a second group never erases the first; an empty one exports as `(unanswered)`), a note per entry, an "Anything else" box, `localStorage` keyed per project AND session, and the copy-back export with its clipboard fallback. Its width and type are the settled defaults (1180px page, 17px body, 15.5px controls, 18px ticks): a 760px column of 15px text was the usual first draft and the usual complaint. Change them (`css`) only if the reader asks, then keep the change for the life of the log.

## Structure

1. **Project bar**: brand · **session** · repo · "Working log" (`project`).
2. **Status bar**: "N / M read" and a **version marker**, `v3 · updated <date> · entry N`. The reader reloads the same URL after every change and otherwise cannot tell whether the reload landed, so bump `version` on every republish, carry it into the export (`log: … · page v3` in `details`), and pass the same thing as the `Artifact` tool's `label`.
3. **Masthead** (`intro_html`): one paragraph saying what the page is and how to reply, plus **how to reopen it**, because the user will close the tab. If the project has an artifact-opener script or keeps a list of links, name it.
4. **Fact bar** (`facts`): 3-4 live facts: branch, tests passing, what is live, what is awaiting them.
5. **Messages, newest first** (`entries`): a title, a status (`Your move` / `Background` / `Queued` / `Done`), an id; a full-strength `lede` sentence with detail below; option groups **only where you are actually asking something**.
6. **Settled section** at the bottom (`after_html`): resolved entries, condensed to a line or two.

## Rules that matter

**Clear out what is settled.** The log's value is that the top of the page is what needs the user. An entry that is done moves to the Settled section as one or two lines, or goes entirely. A log that only grows is scrollback with extra steps.

**Ask only where you mean it.** Option buttons on an informational entry train the user to click past them. Most entries should have none.

**Say what a failure looks like.** When an entry asks the user to run something, give the success output *and* the most likely failure text. They often cannot read their own terminal — that is why this page exists.

**One entry per turn, at most.** If you have three things, they are usually one entry with three points. Numbered entries are for things that need separate answers.

## Export format

**A details block comes first, because pasted text arrives with no other context.** The reply may land in a different session from the one that wrote the page, and every field is something you would otherwise have to ask the user to restate.

```
WORKING LOG — my replies
project: Acme Widgets
session: invoice-export
repo: acme/widgets
log: 2026-03-14 · invoice-export · page v3
round: M12–M15 (M14 settled)
branch: invoice-export
pr: #12 — merged as 1a2b3c4d
exported: 2026-03-14 11:53

M6  [read]  Found it — the config change was never being used
      answer: Pushed — it worked
      note: had to add the workflow permission
M5  [unread]  Why the new setting changed nothing
```

`project` and `session` are the two that must never be omitted — they tell the receiving session whether the paste belongs to it. The rest (`details`) are per-log: carry whatever identifies *this* round of work, and drop fields that do not apply. `exported` is the page's local time, so a paste that sat in a buffer for an hour does not read as current. Unread entries export as `[unread]`: knowing what the user has *not* seen is as useful as knowing what they answered.

## Questions-for-you mode

One published Artifact per work-stream, republished to the **same URL** as questions accumulate. The user works through every open question in one pass, hits a copy button, and pastes a compact block back. Use it as its own page, or as the "Your move" entries of a working log; the mechanics are the same.

**Core principle: the page is an input surface, not a document.** The most common failure is a nicely typeset read-only page that tells the user to answer in chat by question number. That is the thing they were trying to get away from.

The builder's questions mode gives real radio controls, a notes field on every question ("Or in your own words", which invites the answer you didn't offer), the sticky "N of M answered" tally, Clear (with a confirm), persistence, the copy-back export, ~19px body type, and the default visual treatment: one dark world, a neutral near-black ground with a violet accent, chosen over a green-on-green alternative in a side-by-side comparison, the same in either theme. The accent marks selection and the primary action; green means answered or shipped, never "recommended". `../../shared/review_page/examples/questions.json` is a working example spec, and `log.json` beside it one for the log.

What stays yours:

1. **A stable `qid` on every question**, shown on the page and emitted in the export. A short slug, assigned once and never changed, even as the wording is edited or the question moves between rounds. Position and numbering are not stable; the slug is.
2. **Mockups for visual questions** (`mockups_html`). If the question is *where* something sits or *how* it looks, draw the options at the real width. Lettered descriptions of layouts are not answerable.
3. **Full option text** as each option's `value`, never a bare letter. "Q2: C" is meaningless out of context, and worse, it looks meaningful.
4. **A settled log** (`after_html`). Answered decisions stay on the page, compacted, never deleted: that log is why the user doesn't have to remember what they already told you.

### Questions export format

Answers come back as pasted text, possibly out of order, possibly from a different round, possibly while you are working on a different project, so the export identifies itself:

```
[working-log questions v1.2 — answers]
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

`project` / `stream` stop a block pasted into the wrong session from being applied to the wrong work. `round` and each question's `(raised rN)` say whether an answer is fresh or a late reply to something asked two rounds ago. `artifact` lets you republish the right URL. `sent` orders two pastes that arrived out of order. `(UNANSWERED)` is explicit because silence is ambiguous.

### Writing the questions

- **The ask, then why it matters, then the options.** Each option gets a real trade-off, not a label. "Overlay: covers the inputs you're about to fill" beats "Overlay".
- **Recommend one, and say why.** Mark it clearly. A menu with no recommendation pushes work back onto the user.
- **Include the option you think is wrong** if it's genuinely defensible. It's how you find out your recommendation was wrong.
- **Decisions the user delegated to you** go on the page too, as a stated call with the argument for it, plus an "overrule me" control. Never bury one in prose.
- **Keep a parked list.** Things you found but aren't doing this cycle, so they aren't silently dropped.

### Questions workflow

1. Write the spec and build the page to a stable file path. Publish with the `Artifact` tool.
2. Give the user the URL and say answers come back via the copy button.
3. **Stop at blocking questions.** Do work that doesn't depend on the answers; don't guess past one and build on the guess.
4. When answers arrive: apply them, move those questions into the settled log, add whatever new questions the answers raised, and **rebuild and republish the same file path** so the URL is unchanged.
5. Never mint a second URL for the same work-stream. The user has that tab open.

### Common mistakes

| Mistake | Why it fails |
|---|---|
| Read-only page, "answer in chat by letter" | This is the exact problem the user asked you to solve |
| Bare letters in the export | You get "Q2: C" with no record of what C was |
| Renumbering questions between rounds | A late answer to "Q2" lands on whatever is Q2 now |
| Deleting answered questions | Destroys the decision record; the user re-litigates settled things |
| New URL per round | Their open tab goes stale and they answer the wrong version |
| Prose describing a layout | If the question is visual, prose is unanswerable |
| Proceeding on a guess | You build on an assumption and throw the work away |

### QA checklists

The same page doubles as a QA run sheet (`qa` in the spec). When work ships that only the user can verify (a real device, real production data, a service the sandbox cannot reach), put the checks on the page rather than listing them in chat, where they scroll away for exactly the reason the questions did.

**Each item carries:**

- a stable `qaid`, same rules as `qid`: assign once, never renumber
- **what to do** (`check`), as an action the user performs, not a feature name
- **what "pass" looks like**, stated explicitly in `why_html`. "Expected: it deletes cleanly" is checkable; "verify deletion works" is not
- **why it is on the list**, usually the failure it used to produce, so the user can judge severity when it fails
- a notes prompt (`notes_label`) asking for the specific evidence you need. "Paste the image URL if it failed" beats "notes"

The page answers each with PASS / FAIL / COULDN'T TEST (the honest answer for a check blocked by an earlier failure) and counts QA separately in the tally (`all 3 answered · QA 2 of 7`), so QA items never inflate the open-questions number.

**Rules that matter:**

- **Order by consequence.** A crash or data-loss check goes first.
- **Say plainly which items you could not verify yourself, and why.** A check already green in automated tests is noise. A check you were structurally unable to run (no WebKit in the sandbox, no production credentials, an egress-blocked image host) is the whole reason the list exists. Mark those explicitly.
- **Name the expected non-bugs.** If shipped behavior will look broken but is simply not in scope yet, say so on the page, or it comes back as a regression report.
- **State dependencies between items.** "Depends on QA 2 passing first" saves a confusing FAIL.
- **Do not post a checklist before the work ships.** An unrunnable list teaches the user to ignore the section.

QA results export in their own block, after the decisions, with `(NOT CHECKED)` for an item the user has not reached, deliberately distinct from `(UNANSWERED)`:

```
--- QA results ---

QA qa-delete-item | Delete an item that has an attachment
  -> PASS

QA qa-photos | Do inspection photos appear at all — thumbnail and zoom
  -> FAIL
  note: still a broken glyph. URL: https://cdn.example.com/photos/abc123
```

## Publishing and verifying

Publish with `Artifact`, and **republish to the same file path every time** — the URL must not change, or the user loses the tab they have been using. Keep the favicon stable for the same reason.

**"Same path" includes the folder, and that is easier to break than it sounds.** Publishing from `/work/checkout-a/docs/log.html` and later from `/work/checkout-b/docs/log.html` is TWO paths: the second mints a new URL and silently strands the tab the user is working from, along with its `localStorage` ticks. So do not delete the folder you published from (for example by removing a git worktree) while the log is still live. The fix is cheap once you know it: recreate a folder at the ORIGINAL path, copy the file back, republish, and the original URL returns.

**Verify before every publish, including updates.** The build runs its own check (script syntax, entry counts, and that the `<title>` leads with the session name). Run `--smoke` when Playwright is available: it ticks, answers, types a note, copies, reloads, and checks for sideways scroll at 1280 and 390. Then take one screenshot of your content at a desktop and a phone width: the checks prove behavior, not that your own HTML (a grid in `detail_html`, a mockup) is readable. A grid child with no `grid-column` is auto-placed into the narrow first column, so set the default the safe way round (`.steps > li > * { grid-column: 2 }` with the number opting out). If you need a browser, the `pr-qa` skill explains how to get a headless one working.

Keep the spec and page where the project keeps its artifact sources (its own notes say where, and whether they are committed). The source is the only way to update a published artifact in place — a later session cannot always read the page back.

## The URL is per-session, and recoverable

**Republishing the log's file from a new session mints a NEW page.** The file path
only holds a URL within one session; a later session that publishes the same file
without passing `url` silently creates a second log and leaves the user's tab on the
first. That is deliberate for concurrent sessions — two sessions republishing one URL
overwrite each other's messages — so **two sessions must never share one log link**.

**So a `/clear` (or any reset) loses the URL, and this is how you get it back.**
Before publishing anything after a reset, look for the existing log, not after, when a
second page already exists:

1. Run `Artifact` with `action: "list"` and find the page titled
   `SESSION · PROJECT log`. If the project keeps a record of published links, check
   that too.
2. Read it (`action: "read"`, which is required anyway before writing to a page this
   context has not read).
3. Publish with `url:` set to that link, so the same page updates instead of a second
   one appearing.

The same lookup recovers any other page whose link was lost — a decisions review, a
field check — by its title.

## Where the page goes

Before you publish or save the page, read `../../reference/where-the-page-goes.md` (the path is relative to this skill's folder). The project's `PROOFS_PAGES` setting picks artifact, file or wifi, and that file says what each means and how copy buttons must fall back.
