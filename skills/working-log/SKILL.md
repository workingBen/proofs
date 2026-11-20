---
name: working-log
version: 1.10.1
description: Use when the user cannot reliably read terminal output, prefers a durable page to chat, is stepping away, and the first time a session has something waiting on them — keeps one session page (waiting on you, checks, log, decided) at one URL. It owns that page and the log; questions and qa-checklist write its other sections.
---

# Working Log

One published page per session that replaces chat as the channel Claude talks *to*
the user through: the **session page**.

Chat scrollback is lossy: it cannot be re-read after a restart, it cannot be ticked
off, and if the user's terminal renders badly it is not a channel at all. The session
page holds everything that needs the user, in this order, each section shown only
when it has content:

1. **Waiting on you**: open questions and confirmations (written by the `questions`
   skill), plus one-line links to other pages that need them.
2. **Checks for you**: checks only the user can run (written by the `qa-checklist` skill).
3. **Log**: newest message first, a **Read this** tick per entry. A ticked entry folds to one line under **Read** at the bottom of the log; unticking it brings the full card back.
4. **Decided**: settled items, folded away.

One **Copy my replies** button exports every section's block as plain text the user
pastes back. The user's direction still arrives through chat. **Pasting works when
reading does not**, and that asymmetry is the whole design.

## When it starts on its own

**The first time a session has any question, confirmation or check for the user,
start the session page (or update it), without being asked.** Chat still gets a short
copy with the link, because chat is what the user replies to. After that, every
question, answer and decision goes on the page *and* in chat.

Also start it when:

- The user says they cannot read terminal output, or output is garbled/truncated.
- They ask for `/proofs:working-log`, or for messages "in the artifact" rather than in chat.
- A long unattended run where they will return to a lot of accumulated state.
- You need a **confirmed read**: a credential to revoke, a destructive step, an
  assumption you are about to build on.

Not for: the end-of-session recap of a `review-cycle` (it has its own summary page).
**Design reviews and copy edits stay their own pages** (`design-review`,
`article-copy-edit`); the session page links to them in Waiting on you with a one-line
status, for example "Design review: 3 decisions open". A project that does not use the
session page can still use `questions` and `qa-checklist` as standalone pages.

Where this skill mentions how the project handles files, worktrees, commits or
publishing habits, it defers to the project's own notes (`CLAUDE.md` or the
equivalent). Follow them.

## Required frontmatter — tie it to its project AND its session

The page carries a **fixed project bar** at the top, always visible, so the user can
tell one project's page from another's at a glance. This is not decoration: once two
projects both have a session page, two tabs look identical without it. The builder starts
it with the proofs mark and a `working-log` pill, which tell this page from a design
review or a checklist; every proofs page carries the same header.

```
proofs [working-log] │ PROJECT NAME · SESSION NAME · owner/repo
```

Take the project name from the repo's own `CLAUDE.md` (its overview line or
equivalent) and the slug from `git remote -v`. **Read them; do not guess** — a wrong
repo slug on a page about credentials is actively misleading.

**The session name is required, and it is the disambiguator.** One project can have
several session pages open at once, because several sessions can run against the same repo at
once — and then the project bar is *identical on every tab*, which is the failure the
bar was supposed to prevent, one level down. The classic accident is pasting replies
into the wrong session. The session name is the only field that differs, so:

- **Put it first in the `<title>`**, before the project — `SESSION · PROJECT session`.
  Tab titles truncate from the right, and the field that tells tabs apart is useless
  if it is the part that gets cut.
- **Give it the accent in the project bar**, so it reads before anything else.
- **Put it in the export too** (see below). A pasted reply that lands in the wrong
  session is exactly the thing being prevented, and the paste is where it happens.

Take it from the session's own name if it has one; otherwise name it for the work
(`credential-rotation`, `pr-qa-review`).

**Follow renames.** The user renames sessions as the work changes, and a page still
carrying the old name is the wrong-session paste waiting to happen. Before every
republish, read the session's current name: a rename notice in the conversation, or the
"This session is …" line from listing agents. If it changed, update `session` and the
`<title>`, keep publishing to the same file path so the URL stays, and say so in one log
entry. The `localStorage` key changes with the name, so earlier ticks reset; mention it.
A name taken from a handoff note is a guess, not the session's name; check before the
first publish.

## Building it: the shared builder

**Needs the whole plugin.** This skill reads shared files at `../../reference/` and `../../shared/`, relative to its folder. If they are missing, the skill was copied on its own: install the whole plugin (`/plugin install proofs@proofs`) rather than recreating them.

Write the content; the builder writes the page. Read `../../reference/review-page.md` first: `"mode": "session"`, built with `python3 ../../shared/review_page/review_page.py spec.json --out session.html`; `../../shared/review_page/examples/session.json` is a working example. Do not hand-write the page's JavaScript. Load `artifact-design` first if it is available; this is a utilitarian tool page, not editorial: real type hierarchy, no hero.

The builder supplies the mechanics: the sticky project bar (session accented) and status bar (one tally across sections, version marker, copy button), the fixed section order, sections hidden when empty, the questions-first check, a **Read this** tick and a note per log entry, an "Anything else" box, `localStorage` keyed per project AND session, and the combined copy-back export with its clipboard fallback. Its width and type are the settled defaults (1180px page, 17px body): a 760px column of 15px text was the usual first draft and the usual complaint. Change them (`css`) only if the reader asks, then keep the change for the life of the page.

## Structure

The spec's fields, in the order the page shows them:

1. **Project bar**: proofs mark and `working-log` pill · project · **session** · repo (`project`).
2. **Status bar**: the tally ("1 of 2 answered · checks 0 of 1 · 3 / 5 read") and a **version marker**, `v3 · updated <date> · entry N`. The reader reloads the same URL after every change and otherwise cannot tell whether the reload landed, so bump `version` on every republish, carry it into the export (`details`), and pass the same thing as the `Artifact` tool's `label`.
3. **Waiting on you** (`questions`, then `links`): open questions, directly under the sticky bar, highlighted. Write them by the `questions` skill. `links` are other pages waiting on the user: `{label, status, url, state}`, as "Design review: 3 decisions open". `state` is `open` (the default, with an **Open it** link) or `in-progress` once the user has answered that page and you are working on it: it stays listed, muted and after the open ones, until the page needs them again.
4. **Checks for you** (`qa`): written by the `qa-checklist` skill.
5. **About this page** (`heading`, `intro_html`, `facts`): what the page is, how to reply, **how to reopen it** (the user will close the tab; name the project's artifact-opener script or list of links if it has one), and 3-4 live facts (branch, tests, what is live). This is context, so it sits below everything that needs action.
6. **Log, newest first** (`entries`): a title, a status (`Background` / `Queued` / `Done`), an id, and `when` on every new entry: the user's local time you wrote it, as `2026-11-19T15:54` (the page shows `Nov 19 - 3:54PM`); a full-strength `lede` sentence with detail below. Log entries do not ask: a question goes in `questions`, and the builder refuses an entry with option buttons.
7. **Decided** (`decided`): settled items, `{id, title, decision, when}`, one line each, folded.

## Rules that matter

**Open questions are the first thing on the page.** Reports, context, screenshots and settled items go below them or folded away. The user should never scroll to find what you are asking; the builder enforces the order and its check fails a page that breaks it.

**Clear out what is settled.** The top of the page is what needs the user. An answered question leaves Waiting on you at once for Decided; a log entry that is done becomes a Decided line or goes entirely. A page that only grows is scrollback with extra steps.

**A paste updates the page first, before any other work.** When the user pastes an export (from this page or any page linked from it), republish the session page before you start on what it asks: mark each answered page's link `"state": "in-progress"`, move answered questions to Decided, and log what you are about to do. When a linked page is ready for the user again, flip its link back to `open` with its new status in the same republish. A page that still shows answered work as waiting on them reads as stale, and they stop trusting it.

**Say what a failure looks like.** When an entry asks the user to run something, give the success output *and* the most likely failure text. They often cannot read their own terminal — that is why this page exists.

**One entry per turn, at most.** If you have three things, they are usually one entry with three points.

## Export format

**A details block comes first, because pasted text arrives with no other context.** The reply may land in a different session from the one that wrote the page, and every field is something you would otherwise have to ask the user to restate. Then one block per section that has content, in page order:

```
WORKING LOG — my replies
project: Acme Widgets
session: invoice-export
repo: acme/widgets
artifact: <the page's published URL>
page: v4
branch: invoice-export
exported: 2026-03-14 11:53

--- Questions ---

Q csv-dates (raised r2) | Which date format should the CSV export use?
  -> ISO dates (2026-03-14)

--- QA results ---

QA qa-export-file | Export last month's invoices and open the file
  -> FAIL
  note: totals off by one cent

--- Log ---

M6  [read]  Mar 14 - 3:54PM  Found it — the config change was never being used
M5  [unread]  Why the new setting changed nothing
      note: thanks

anything else:
ship it
```

`project` and `session` are the two that must never be omitted — they tell the receiving session whether the paste belongs to it. The rest (`details`) are per-session: carry whatever identifies *this* round of work. `exported` is the page's local time, so a paste that sat in a buffer for an hour does not read as current. Unread entries export as `[unread]`: knowing what the user has *not* seen is as useful as knowing what they answered. The question and QA blocks are the `questions` and `qa-checklist` formats.

## Publishing and verifying

Publish with `Artifact`, and **republish to the same file path every time** — the URL must not change, or the user loses the tab they have been using. Keep the favicon stable for the same reason.

**"Same path" includes the folder, and that is easier to break than it sounds.** Publishing from `/work/checkout-a/docs/log.html` and later from `/work/checkout-b/docs/log.html` is TWO paths: the second mints a new URL and silently strands the tab the user is working from, along with its `localStorage` ticks. So do not delete the folder you published from (for example by removing a git worktree) while the page is still live. The fix is cheap once you know it: recreate a folder at the ORIGINAL path, copy the file back, republish, and the original URL returns.

**Verify before every publish, including updates.** The build runs its own check (script syntax, section order, questions first, and that the `<title>` leads with the session name). Run `--smoke` when Playwright is available: it ticks, answers, types a note, copies, reloads, confirms the questions sit directly under the sticky bar, and checks for sideways scroll at 1280 and 390. Then take one screenshot of your content at a desktop and a phone width: the checks prove behavior, not that your own HTML (a grid in `detail_html`, a mockup) is readable. A grid child with no `grid-column` is auto-placed into the narrow first column, so set the default the safe way round (`.steps > li > * { grid-column: 2 }` with the number opting out). If you need a browser, the `pr-qa` skill explains how to get a headless one working.

Keep the spec and page where the project keeps its artifact sources (its own notes say where, and whether they are committed). The source is the only way to update a published artifact in place — a later session cannot always read the page back.

## The URL is per-session, and recoverable

**Republishing the page's file from a new session mints a NEW page.** The file path
only holds a URL within one session; a later session that publishes the same file
without passing `url` silently creates a second page and leaves the user's tab on the
first. That is deliberate for concurrent sessions — two sessions republishing one URL
overwrite each other's messages — so **two sessions must never share one session page**.

**So a `/clear` (or any reset) loses the URL, and this is how you get it back.**
Before publishing anything after a reset, look for the existing page, not after, when a
second page already exists:

1. Run `Artifact` with `action: "list"` and find the page titled
   `SESSION · PROJECT session` (older pages: `SESSION · PROJECT log`). If the project keeps a record of published links, check
   that too.
2. Read it (`action: "read"`, which is required anyway before writing to a page this
   context has not read).
3. Publish with `url:` set to that link, so the same page updates instead of a second
   one appearing.

The same lookup recovers any other page whose link was lost — a decisions review, a
field check — by its title.

## When the session is done: clean up after yourself

A finished session should leave nothing behind but its results. Pages, scratch
folders, worktrees and handoff notes pile up across sessions until nobody can tell
what is live, so the session that made them removes them.

**Keep the list as you go.** Every time the session creates something that would
outlive it, note it in the spec's `details` or a log entry: a published page (title
and link), a local folder, a git worktree or branch, a handoff or memory note. Only
what this session made goes on the list; another session's pages and files are never
yours to remove, even when they look abandoned. A page or folder you **resumed** from a
handoff was made by earlier sessions and may still hold other topics' work (another
project's steps in old log entries, for example): read it before listing it, and if it
does, name those topics in the question so the user knows what a delete takes with it.

**Ask once, at the end.** When nothing is waiting on the user, put one question in
Waiting on you that shows the whole list and offers **Delete all of it** /
**Keep some (note)** / **Keep everything**, with what each item is and its size. Say
plainly that deletes cannot be undone. Results the user keeps using (videos, files
on their desktop, merged code) are not on the list.

**Then do it, in this order:** local renders and scratch files; worktrees and merged
branches; handoff notes (move any still-useful fact, such as where source files live,
into a lasting note first); other published pages; **the session page last**, since it
is how the user follows along. Report what was removed and what was kept, and why,
in chat and as the page's final entry before it goes. If an item turns out to hold
unfinished work, keep it and say so instead of deleting it.

Deleting a published page asks the user to confirm each one, and that prompt may only
appear in a terminal, not on a phone. Ask where they are before a batch of deletes;
if they cannot confirm, give them the links to delete from instead.

## Where the page goes

Before you publish or save the page, read `../../reference/where-the-page-goes.md` (the path is relative to this skill's folder). The project's `PROOFS_PAGES` setting picks artifact, file or wifi, and that file says what each means and how copy buttons must fall back.
