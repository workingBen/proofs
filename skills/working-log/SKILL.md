---
name: working-log
version: 1.5.2
description: Use when the user cannot reliably read terminal output, says your questions get lost in terminal or console output, simply prefers a durable page over chat scrollback, asks to answer several questions at once rather than one at a time, wants a link to work through at their own pace and paste answers back from, asks for open decisions to live somewhere reviewable asynchronously, or is answering from a phone — publishes a newest-first message log as an Artifact, with a read tick per entry, option buttons where you are asking something, a questions-for-you mode that batches many open questions into one answerable page, and a copy-back export they paste into chat. Invoke as /proofs:working-log to create or update it.
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

## Structure

1. **Project bar** (sticky, dark, always visible) — brand · **session** · repo ·
   "Working log". The session name is accented; see "Required frontmatter" above.
2. **Status bar** (sticky, under it) — "N / M read" and, on the right, a **version
   marker**: `v3 · updated <date> · entry N`, the version accented. The reason is
   practical: the reader reloads the same URL after every change and otherwise has no
   way to tell whether the reload landed. Bump it on every republish, carry it into
   the export (`log: … · page v3`), and pass the same thing as the `Artifact` tool's
   `label` so the version picker agrees with the page.
3. **Masthead** — one paragraph saying what the page is and how to reply.
4. **How to reopen it** — the exact way to get back to this page, because the user
   will close the tab. If the project has an artifact-opener script or keeps a list
   of links, name it.
5. **Fact bar** — 3-4 live facts: branch, tests passing, what is live, what is
   awaiting them.
6. **Messages, newest first.** Each entry:
   - a title, a status chip (`Your move` / `Background` / `Queued` / `Done`), a number
   - a lede sentence in full-strength text, detail below in muted text
   - option buttons **only where you are actually asking something**
   - a free-text note field
   - a **Read this** tick, which dims the card when set
7. **Settled section** at the bottom — resolved entries, condensed to a line or two.
8. **Copy my replies** — export, plus a free-text "anything else" box.

## Width and type — start here, don't rediscover it

A narrow column of small text is the usual first draft and the usual complaint: a
760px column with 15px text is too small and too narrow for a page someone works
through all day. These are the defaults that settled it:

- **`.page { max-width: 1180px }`** with 28px side padding — a margin rather than a
  column, using most of a wide screen.
- **17px body**, 34px h1, 20px entry titles, 17.5px lede, 16px detail.
- **Controls scale too, and matter most** — 15.5px option buttons and note fields,
  18px tick boxes. They are the part the reader actually operates.
- Long prose gets no per-paragraph `max-width` except the masthead intro (88ch).
  The measure runs long at this width; that is the trade, and the content is short
  blocks rather than essays.

Treat these as defaults, not as a ceiling: if the reader asks for something
different, change it and keep it for the life of the log.

## Rules that matter

**Clear out what is settled.** The log's value is that the top of the page is what
needs the user. An entry that is done moves to the Settled section as one or two
lines, or goes entirely. A log that only grows is scrollback with extra steps.

**Ask only where you mean it.** Option buttons on an informational entry train the
user to click past them. Most entries should have none.

**Say what a failure looks like.** When an entry asks the user to run something, give
the success output *and* the most likely failure text. They often cannot read their
own terminal — that is why this page exists.

**One entry per turn, at most.** If you have three things, they are usually one entry
with three points. Numbered entries are for things that need separate answers.

**Persist state in `localStorage`**, keyed per project AND session, so two logs open
at once cannot overwrite each other's ticks and answers.

**Store one answer per option group, keyed by its `data-q`, never one per entry.**
An entry that asks two questions with one `answer` field keeps only the last click,
and the export then shows one answer as though it were the whole reply — a second
click silently erases the first. Export every group by name, with `(unanswered)` for
an empty one, so a missing answer is visible.

## Export format

**A details block comes first, because pasted text arrives with no other context** —
not just a title line. The reply lands in a chat that may be a different session from
the one that wrote the page, and every field below is something you would otherwise
have to ask the user to restate.

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

`project` and `session` are the two that must never be omitted — they are what tell
the receiving session whether the paste belongs to it. The rest are per-log: carry
whatever identifies *this* round of work, and drop fields that do not apply.

`exported` is a local timestamp from the page, so a paste that sat in a buffer for an
hour does not read as current. Note `new Date()` is fine in page JS — the ban on it
applies to Workflow scripts, not to artifacts.

Include unread entries as `[unread]` — knowing what the user has *not* seen is as
useful as knowing what they answered.

## Questions-for-you mode

One published Artifact per work-stream, republished to the **same URL** as questions
accumulate. The user works through every open question in one pass, hits a copy
button, and pastes a compact block back. Use it as its own page, or as the "Your move"
section of a working log (the entries whose status chip is `Your move`, meaning they wait on the user); the mechanics are the same.

**Core principle: the page is an input surface, not a document.** The most common
failure is a nicely typeset read-only page that tells the user to answer in chat by
question number. That is the thing they were trying to get away from.

`questions-template.html` in this skill directory is a working reference: tokens, sticky
tally bar, question cards, mockup frames, `localStorage` and the clipboard export.
Adapt it. Don't ship it verbatim.

### Required elements

A questions page missing any of these fails the user's actual request:

1. **Real controls.** Radio inputs per question, not lettered prose. A `<textarea>` for
   notes on every question: the notes are where the answer you didn't anticipate arrives.
2. **A stable `qid` on every question**, shown on the page and emitted in the export.
   Assign it once; never renumber.
3. **A copy-back export.** A button that puts a parseable block on the clipboard. Fall
   back to `window.prompt` when `navigator.clipboard` is unavailable (it is, in some
   embedded viewers).
4. **Persistence.** Save to `localStorage` on every change and restore on load. They
   will close the tab mid-pass.
5. **A tally.** "2 of 8 answered" in a sticky header, so what is outstanding is visible
   without scrolling.
6. **Mockups for visual questions.** If the question is *where* something sits or *how*
   it looks, draw the options at the real width. Lettered descriptions of layouts are
   not answerable.
7. **Large body type.** About 19px. This gets read on phones and skimmed at speed.
8. **A settled log.** Answered decisions stay on the page, compacted, never deleted:
   that log is why the user doesn't have to remember what they already told you.
9. **A Clear button beside Copy**, with a confirm.

### Questions export format

Answers come back as pasted text, possibly out of order, possibly from a different
round, possibly while you are working on a different project. The export has to be
self-identifying.

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

- **`project` / `stream`**: the same user runs several projects and work-streams.
  Without these, a block pasted into the wrong session gets applied to the wrong work.
- **`round`** and per-question **`(raised rN)`**: tells you whether an answer is fresh
  or a late reply to something you asked two rounds ago.
- **`artifact`**: lets you republish the right URL rather than minting a new one.
- **`sent`**: orders two pastes that arrived out of order.
- **A stable `qid` per question**: a short slug, assigned once and never changed, even
  as the wording is edited or the question moves between rounds. Position and numbering
  are not stable; the slug is.
- **`(UNANSWERED)`** stated explicitly: silence is ambiguous, an explicit marker is not.
- Put the **full option text** in the export, never a bare letter. "Q2: C" is
  meaningless out of context, and worse, it looks meaningful.

### Writing the questions

- **The ask, then why it matters, then the options.** Each option gets a real
  trade-off, not a label. "Overlay: covers the inputs you're about to fill" beats "Overlay".
- **Recommend one, and say why.** Mark it clearly. A menu with no recommendation pushes
  work back onto the user.
- **Include the option you think is wrong** if it's genuinely defensible. It's how you
  find out your recommendation was wrong.
- **Decisions the user delegated to you** go on the page too, as a stated call with the
  argument for it, plus an "overrule me" control. Never bury one in prose.
- **Keep a parked list.** Things you found but aren't doing this cycle, so they aren't
  silently dropped.

### Questions workflow

1. Write the page to a stable file path. Publish with the `Artifact` tool.
2. Give the user the URL and say answers come back via the copy button.
3. **Stop at blocking questions.** Do work that doesn't depend on the answers; don't
   guess past one and build on the guess.
4. When answers arrive: apply them, move those questions into the settled log, add
   whatever new questions the answers raised, and **republish the same file path** so
   the URL is unchanged.
5. Never mint a second URL for the same work-stream. The user has that tab open.

### Common mistakes

| Mistake | Why it fails |
|---|---|
| Read-only page, "answer in chat by letter" | This is the exact problem the user asked you to solve |
| Bare letters in the export | You get "Q2: C" with no record of what C was |
| Export with no project/stream header | A block pasted into the wrong session gets applied to the wrong work |
| Renumbering questions between rounds | A late answer to "Q2" lands on whatever is Q2 now |
| Deleting answered questions | Destroys the decision record; the user re-litigates settled things |
| New URL per round | Their open tab goes stale and they answer the wrong version |
| Prose describing a layout | If the question is visual, prose is unanswerable |
| No notes field | Forces every answer into your predefined options |
| Proceeding on a guess | You build on an assumption and throw the work away |

### Questions-for-you mode: visual treatment

**Default to a single dark world: a neutral near-black ground with a violet accent.**
Not a green one, not a light counterpart. It was chosen over a green-on-green
alternative in a side-by-side comparison, so start here rather than re-deriving a
palette per project. (This applies to the questions page; a working log keeps its own
width and type defaults above.)

| Token | Value | Used for |
|---|---|---|
| `--ground` / `--raised` / `--sunk` | `#0e0e14` / `#16161f` / `#0a0a0f` | page, cards, insets |
| `--ink` / `--ink-soft` / `--ink-faint` | `#ececf1` / `#a8a8b8` / `#6f6f82` | body, descriptions, labels |
| `--rule` | `#262632` | borders |
| `--accent` / `--accent-soft` | `#a855f7` / `rgba(168,85,247,.14)` | selected option, primary button, open-question rail |
| `--good` | `#4ade80` | answered state, shipped items |
| `--warn` | `#fbbf24` | highlights inside mockups |

Commit to it as one visual world: define the tokens once and let `[data-theme="light"]`
and `[data-theme="dark"]` resolve to the same values, so the viewer's toggle can't drop
the page into a scheme they didn't ask for. A deliberate single-theme design is allowed
by Artifact design guidance; this is one.

Reserve the accent for **selection and the primary action**. Green means answered or
shipped, never "recommended": the accent already carries that.

Also worth keeping: the tally reads **"N of M answered"**, not "N open", and the notes
label reads **"Or in your own words"**, which invites the answer you didn't offer.

### QA checklists

The same page doubles as a QA run sheet. When work ships that only the user can verify
(a real device, real production data, a service the sandbox cannot reach), put the
checks on the page rather than listing them in chat, where they scroll away for exactly
the reason the questions did. A QA item reuses the same machinery: one control group,
one notes field, one export block.

**Each item carries:**

- a stable `qaid`, same rules as `qid`: assign once, never renumber
- **what to do**, as an action the user performs, not a feature name
- **what "pass" looks like**, stated explicitly. "Expected: it deletes cleanly" is
  checkable; "verify deletion works" is not
- **why it is on the list**, usually the failure it used to produce, so the user can
  judge severity when it fails
- three states: PASS / FAIL / COULDN'T TEST. The third is the honest answer for a check
  blocked by an earlier failure; without it the user guesses or silently skips
- a notes field prompted for the specific evidence you need. "Paste the image URL if it
  failed" beats "notes"

**Rules that matter:**

- **Order by consequence.** A crash or data-loss check goes first.
- **Say plainly which items you could not verify yourself, and why.** A check already
  green in automated tests is noise. A check you were structurally unable to run (no
  WebKit in the sandbox, no production credentials, an egress-blocked image host) is the
  whole reason the list exists. Mark those explicitly.
- **Name the expected non-bugs.** If shipped behavior will look broken but is simply not
  in scope yet, say so on the page, or it comes back as a regression report.
- **State dependencies between items.** "Depends on QA 2 passing first" saves a
  confusing FAIL.
- **QA counts separately in the tally** (`all 3 answered · QA 2 of 7`). QA items are not
  open questions and must not inflate that number.
- **Do not post a checklist before the work ships.** An unrunnable list teaches the user
  to ignore the section.

QA results export in their own block, after the decisions:

```
--- QA results ---

QA qa-delete-item | Delete an item that has an attachment
  -> PASS

QA qa-photos | Do inspection photos appear at all — thumbnail and zoom
  -> FAIL
  note: still a broken glyph. URL: https://cdn.example.com/photos/abc123
```

`(NOT CHECKED)` marks an item the user has not reached, deliberately distinct from
`(UNANSWERED)` for questions, so an unfinished QA pass is never mistaken for an
undecided question.

Follow any design guidance your environment provides for published pages when writing
the page; this section governs the mechanics and the default visual treatment.

## Building it

Load `artifact-design` first if it is available. This is a utilitarian tool page, not editorial: real
type hierarchy and considered spacing, no hero.

Write the HTML to a file, publish with `Artifact`, and **republish to the same file
path every time** — the URL must not change, or the user loses the tab they have
been using. Keep the favicon stable for the same reason.

**"Same path" includes the folder, and that is easier to break than it sounds.**
Publishing from `/work/checkout-a/docs/log.html` and later from
`/work/checkout-b/docs/log.html` is TWO paths: the second mints a new URL and
silently strands the tab the user is working from, along with its `localStorage`
ticks. So do not delete the folder you published from (for example by removing a
git worktree) while the log is still live. The fix is cheap once you know it:
recreate a folder at the ORIGINAL path, copy the file back, republish, and the
original URL returns. Recreating the path is enough.

**Verify before every publish, including updates.** One bad escape in hand-authored
JS silently kills the whole script, leaving a page that looks fine and does nothing.
Extract the `<script>` contents, `node --check` it, then load the file in jsdom
(`runScripts: 'dangerously'`, stub `navigator.clipboard`) and assert: the expected
entry count, that a tick updates the counter, that an option registers, and that the
export contains the right details block (project and session at minimum), a read
marker, an unread marker and a note. Assert the `<title>` leads with the session name.
Flush a microtask before asserting on anything a `.then()` writes.

**Then take ONE screenshot, because jsdom has no layout engine.** It proves the
behavior and says nothing whatever about whether the page is readable — a log can
pass every assertion above while a note sits in a 26px grid column rendering one word
per line. Wrap the file in the publish skeleton first — `<!doctype html>`, charset and
viewport, and the small reset (zero body margin, 14px system font) — or you are
photographing a different page from the one the artifact serves. Shoot 1280 and 390,
and assert two things a picture makes obvious and an assertion does not:
`document.documentElement.scrollWidth - clientWidth` is **0** at both widths, and
no text block is absurdly narrow — for a grid row, query `.steps > li > *` and
expect nothing under ~120px except the step number itself. If you need a browser,
the `pr-qa` skill explains how to get a headless one working.

The specific trap, since it will recur: **a grid child with no `grid-column` is
auto-placed into the narrow first column.** Set the default the safe way round —
`.steps > li > * { grid-column: 2 }` with the number opting out — rather than
declaring `grid-column: 2` on each child, where the one that forgets is the one
that breaks.

Keep the source file where the project keeps its artifact sources (its own notes say
where, and whether it is committed). The source file is the only way to update a
published artifact in place — a later session cannot always read the page back.

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

The project chooses with `PROOFS_PAGES`, set in the project's `.claude/settings.json` "env" block (or a line in CLAUDE.md: "proofs pages: file"). Values:

- `artifact`: publish as a private claude.ai artifact (a link that opens on phone and computer). This is the default when publishing is available.
- `file`: save the page as an HTML file (default folder `.proofs/pages/`; add it to .gitignore) and open it in the browser (`open` on macOS, `xdg-open` on Linux, `start` on Windows). This is the default when artifacts are not available. Reuse the same file path for later rounds so the page updates in place instead of piling up.
- `wifi`: same as `file`, plus serve only a folder that holds this review's page(s) (for example `.proofs/pages/<review-name>/`, so older pages are not listed to the network) on the local network (`python3 -m http.server <port> --bind <the computer's local IP>` from that folder) and print the address so a phone on the same Wi-Fi can open it. This mode never uploads the page and never uses a public tunnel. Stop the server when the review is done. Use `wifi` only on a private network you trust, never on public or shared Wi-Fi.

If `artifact` is chosen but publishing fails or is not available, fall back to `file` and say so in one line. Everything on the page works the same in every mode. The page's copy button gives the user text to paste back. Copy buttons must fall back to a selectable text box (select all) when `navigator.clipboard` is missing or the write fails (a page served over http on a local IP is not a secure context, so the clipboard is often unavailable), and must never show "Copied" unless the copy actually succeeded.

## Changelog

- **1.5.2** (2026-11-17): Copy buttons now fall back to a selectable text box when the clipboard is unavailable (as on a Wi-Fi-served page), and `wifi` mode is limited to a private network you trust. Removed the unused COMMAND.md; invocation is `/proofs:working-log`; `artifact-design` is used if available.
- **1.5.1** (2026-11-16): New section "Where the page goes": a project can choose an artifact, a local file, or a file served on its own Wi-Fi.
- **1.5.0** (2026-11-17): Absorbed batched-decisions: a questions-for-you mode.
- **1.4.0** (2026-11-16): Merged into proofs: generic, no project-specific steps.
