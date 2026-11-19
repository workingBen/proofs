---
name: working-log
version: 1.7.1
description: Use when the user cannot reliably read terminal output, prefers a durable page to chat, or is on a phone, and the first time a session has a question, confirmation or check for them — keeps one session page (waiting on you, checks, log, decided) at one URL. It owns that page; questions and qa-checklist write its sections.
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
3. **Log**: newest message first, a **Read this** tick per entry.
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
projects both have a session page, two tabs look identical without it.

```
PROJECT NAME · SESSION NAME · owner/repo · Session page
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
(`credential-rotation`, `pr-qa-review`) and keep it stable for the life of the page.

## Building it: the shared builder

**Needs the whole plugin.** This skill reads shared files at `../../reference/` and `../../shared/`, relative to its folder. If they are missing, the skill was copied on its own: install the whole plugin (`/plugin install proofs@proofs`) rather than recreating them.

Write the content; the builder writes the page. Read `../../reference/review-page.md` first: `"mode": "session"`, built with `python3 ../../shared/review_page/review_page.py spec.json --out session.html`; `../../shared/review_page/examples/session.json` is a working example. Do not hand-write the page's JavaScript. Load `artifact-design` first if it is available; this is a utilitarian tool page, not editorial: real type hierarchy, no hero.

The builder supplies the mechanics: the sticky project bar (session accented) and status bar (one tally across sections, version marker, copy button), the fixed section order, sections hidden when empty, the questions-first check, a **Read this** tick and a note per log entry, an "Anything else" box, `localStorage` keyed per project AND session, and the combined copy-back export with its clipboard fallback. Its width and type are the settled defaults (1180px page, 17px body): a 760px column of 15px text was the usual first draft and the usual complaint. Change them (`css`) only if the reader asks, then keep the change for the life of the page.

## Structure

The spec's fields, in the order the page shows them:

1. **Project bar**: brand · **session** · repo · "Session page" (`project`).
2. **Status bar**: the tally ("1 of 2 answered · checks 0 of 1 · 3 / 5 read") and a **version marker**, `v3 · updated <date> · entry N`. The reader reloads the same URL after every change and otherwise cannot tell whether the reload landed, so bump `version` on every republish, carry it into the export (`details`), and pass the same thing as the `Artifact` tool's `label`.
3. **Waiting on you** (`questions`, then `links`): open questions, directly under the sticky bar, highlighted. Write them by the `questions` skill. `links` are other pages waiting on the user: `{label, status, url}`, as "Design review: 3 decisions open".
4. **Checks for you** (`qa`): written by the `qa-checklist` skill.
5. **About this page** (`heading`, `intro_html`, `facts`): what the page is, how to reply, **how to reopen it** (the user will close the tab; name the project's artifact-opener script or list of links if it has one), and 3-4 live facts (branch, tests, what is live). This is context, so it sits below everything that needs action.
6. **Log, newest first** (`entries`): a title, a status (`Background` / `Queued` / `Done`), an id; a full-strength `lede` sentence with detail below. Log entries do not ask: a question goes in `questions`, and the builder refuses an entry with option buttons.
7. **Decided** (`decided`): settled items, `{id, title, decision, when}`, one line each, folded.

## Rules that matter

**Open questions are the first thing on the page.** Reports, context, screenshots and settled items go below them or folded away. The user should never scroll to find what you are asking; the builder enforces the order and its check fails a page that breaks it.

**Clear out what is settled.** The top of the page is what needs the user. An answered question leaves Waiting on you at once for Decided; a log entry that is done becomes a Decided line or goes entirely. A page that only grows is scrollback with extra steps.

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

M6  [read]  Found it — the config change was never being used
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

## Where the page goes

Before you publish or save the page, read `../../reference/where-the-page-goes.md` (the path is relative to this skill's folder). The project's `PROOFS_PAGES` setting picks artifact, file or wifi, and that file says what each means and how copy buttons must fall back.
