---
name: todos
version: 1.3.2
allowed-tools:
  - Read(/${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/todos/scripts/todos_page.py *)
description: Use when the user wants to see and work their open to-do list ("show my todos", "what's still open"), tick items off and archive the done ones with evidence, or adopt the convention in a repo whose TODO.md has grown into a decision log. Differs from review-cycle; it closes existing items, not a stream of new requests.
---

# Todos

Read the settings: `python3 ${CLAUDE_PLUGIN_ROOT}/shared/settings.py --print` (pre-approved). Use the values it shows wherever this file says *the to-do file* (`PROOFS_TODO_FILE`) and *the to-do archive folder* (`PROOFS_TODO_ARCHIVE_DIR`). `TODO.md` and `docs/todo-archive/` below are their defaults; use the settings' values in their place.

## What this is

`TODO.md` holds only open work; everything finished lives in `docs/todo-archive/`,
verbatim, with the reasoning and the commit that closed it. The round-trip:
`python3 ${CLAUDE_PLUGIN_ROOT}/skills/todos/scripts/todos_page.py` turns `TODO.md`'s open items into a published,
tickable Artifact; the user ticks what is done, adds a note where they have one, and
pastes the copy-back export into chat; `python3 ${CLAUDE_PLUGIN_ROOT}/skills/todos/scripts/todos_apply.py` reads that
paste and turns it into a plan: what to archive outright, what to verify first, and
what didn't match anything. The scripts parse, render and match; they never decide
whether a claim holds up. That judgment belongs here, in this file, because it is
the part a script must not be trusted to get right on its own.

**Results first.** Nothing matters more than a result the user wants. Save tokens by cutting waste, never by cutting a check, an option or a revise pass the result needs (full text: `../../reference/house-rules.md`).

Run each script exactly as written below, from the project root; Claude Code fills in
`${CLAUDE_PLUGIN_ROOT}`, and the allow rule only matches the unquoted form. They need Python 3 and
nothing else.

## The convention

Five headings, a closed vocabulary the parser matches literally. A heading that
isn't one of these is not a group, it's unparsed:

```markdown
### Yours        only the user can do it, unverifiable from here
### Decide       needs the user's answer before any code
### Build        Claude can do it
### Backlog      real, ordered, not now
### Ongoing      long-running or date-gated
```

Items are `- [ ] **N. Title.** ...` followed by free-form sub-bullets, which the
parser carries through untouched as the item's body. The group an item sits under
is what determines how a tick on it gets handled; see "The verify policy" below.

Completed work goes to `docs/todo-archive/YYYY-MM.md`, newest section first, with a
`README.md` explaining what's there and how to grep it.

Two rules, both worth restating every time:

- **A finished item leaves the file.** Move it to the current month's archive with
  its evidence attached; never tick it and leave it sitting in `TODO.md`. A ticked
  box left in the live file is itself something the parser flags as unparsed.
- **A finding is not a task.** A root cause, a workaround, a standing rule: those
  go to a field guide, a runbook, or whatever doc actually owns them, not into the
  to-do list. A first stock-take of a long list routinely finds several "open"
  items that were never anything but notes.

## Running it

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/todos/scripts/todos_page.py TODO.md .proofs/pages/todos.html --session "<session name>"
```

The arguments are the to-do file, the output page and the session name (details below).

Then deliver the generated page as "Where the page goes" says (with `artifact`, publish it
with the `Artifact` tool). **Always republish to
that same path**, so the URL does not change; otherwise the user loses the tab they
were working from. Ticks and notes persist in the page's own `localStorage`, keyed
to that URL; a new path resets them. If the project does not commit published
pages, pass a different output path (a scratch folder) as the second argument and
keep using that one path every time.

**Ticks and notes are saved by the item's title, not its position.** Renumbering
the list never moves a tick or a note onto a different item. The flip side:
renaming an item clears its tick and note, because a rewritten title is usually a
rewritten item. The first page built after a rename starts blank for that item.

`todos_page.py` takes `TODO.md`, the output path, a project name and a repo slug as
positional arguments, in that order, all optional, plus `--session NAME` anywhere: always
pass it, the session name taken the way the `working-log` skill does, since the bar shows
the proofs mark, a `todos` pill, the project and the session. With none, it reads the project
name from the bold name under "About This App" in `CLAUDE.md` (falling back to the
repository name) and the repo slug from `git remote get-url origin`, and refuses to
guess if it can find neither. If the status bar reads `18 open · 3 unparsed`
instead of a clean `18 open`, read Troubleshooting below before telling the user the
count is final.

## The verify policy

This is the part that must not be softened, because a to-do file lies in exactly
this direction: in a first stock-take of a real project, seven of nineteen items
marked open turned out to be already built. A tick alone is not evidence for repo
work, and treating it as evidence is the bug this skill exists to close.

- **A tick on a `Yours` or `Decide` item is final.** The user revoking a credential,
  or answering a design question, is not something checkable from a repo, so their
  tick goes straight to the archive with their note, no second-guessing.
- **A tick on a `Build`, `Backlog` or `Ongoing` item starts a verification**, not an
  archive. Check it against the actual code and git history: a matching commit, a
  file that exists, a test that passes, a merged pull request. If the claim holds
  up, archive it with the evidence you checked. **If it does not hold up, the item
  stays open** in `TODO.md`, exactly where it was, with a new sub-bullet on it
  recording what you found and when: `- Checked <date>: not on main, branch still
  open.` Never archive repo work on the strength of a tick by itself.

## The apply steps

1. **Re-read `TODO.md` immediately before writing anything to it**, because other
   sessions or people may have changed it since the page was built. If the project
   runs several sessions against one checkout, follow the project's own notes
   (CLAUDE.md) for how to isolate this edit; the re-read is only sufficient when
   nothing else can write to the file mid-apply.
2. Run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/todos/scripts/todos_apply.py export.txt TODO.md` against the pasted
   export. It matches each ticked row back to a real item by title (numbers are
   reassigned on every apply, so they're never the stable handle) and prints a plan:
   `archive`, `verify`, `unmatched`, `free`.
3. **Never guess a match.** If a title in `unmatched` reads `"... is ambiguous --
   matches: N. Title A; M. Title B"`, the matcher found more than one item it could
   plausibly be and refused to pick. Hand the ambiguity back to the human with both
   candidates named and let them retype it more specifically. A wrong guess here
   archives the wrong item, and there is no undo once the commit lands.
4. For each item in `verify`, do the check described above. Split the result into
   what's now confirmed (archive it) and what isn't (leave it in `TODO.md`, add the
   sub-bullet).
5. By hand, append every item that's actually archiving (the plan's `archive` list
   plus whatever cleared verification in step 4) to `docs/todo-archive/<current
   month>.md`, newest section first. See "What lands in the archive" below for the
   exact shape. No script does this step; `todos_apply.py` only printed the plan in
   step 2.
6. By hand, rewrite `TODO.md` without the archived items and renumber what's left.
   This is exactly why the export names items by their full title rather than by
   number: `t7` means nothing once the next apply has renumbered everything, but
   the title still resolves.
7. Commit following the project's own notes, listing what was archived and what
   failed verification (and why) in the message. An unticked item was never touched
   by any of this; re-pasting the same export a second time is a no-op, because
   anything it names is already gone from `TODO.md`.

## What lands in the archive

Each archived entry carries four things: the item **verbatim** (title and body,
unedited; the reasoning is the valuable part, which is the whole reason this
moves instead of getting deleted), the **date** it was archived, the user's
**note** if they left one, and the **evidence**: the commit SHA, file path, or
whatever you actually checked to confirm repo work, or "ticked by the user" for a
`Yours`/`Decide` item with nothing further to verify.

## Adopt mode

For a repo whose `TODO.md` has never been through this: a decision log wearing a
to-do list's name, months of `- [x]` sitting next to a handful of genuinely open
items. Run once, then never again. Five steps; `python3 ${CLAUDE_PLUGIN_ROOT}/skills/todos/scripts/todos_adopt.py` does the
mechanical two in the middle, the judgment is the skill's:

1. **Audit.** Count `- [x]` against `- [ ]`, and note anything a first read flags
   as work in disguise: a numbered entry, a stray box outside any heading. Report
   the split before changing anything; this is the number the rest of the mode is
   checked against.
2. **Verify every open item** against code and git, same standard as the verify
   policy above. Assume the repo being adopted has several items that are already
   built; a first-time adoption is rarely cleaner.
3. Run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/todos/scripts/todos_adopt.py TODO.md docs/todo-archive/`. It splits every
   `## `-headed section of the original file into `docs/todo-archive/YYYY-MM.md`
   files, grouped by the date in each section's own heading (an undated section
   inherits the month of the section above it, since these files run newest-first).
4. That same run **proves the split before writing anything**: it asserts every
   original section's body is byte-identical inside its archive file, scoped to the
   correct month, and refuses to write a single file if any section doesn't match;
   `write_archives()` raises rather than leaving a half-written directory. This is
   comparison, not a line count; a line tally is satisfied by the wrong lines
   landing in the wrong place.
5. **Rewrite** the surviving open items into the five-heading convention above, and
   **report every reclassification**: what step 2 found already built (and so
   moved straight to the archive instead of staying open), what turned out to be a
   finding rather than a task and went to a field guide or runbook instead, and
   which group each remaining item landed in and why.

## Troubleshooting

**A non-zero `unparsed` count means the item count is not trustworthy, full stop.**
`todos_page.py`'s status bar makes this visible on purpose: `18 open · 3 unparsed`,
never a bare `18` that hides what the parser gave up on. Each unparsed entry names
a line number and a reason: a finished item still marked `- [x]` in the live file,
a numbered entry instead of a checkbox, an open item outside any known heading, or
a `- [ ] **N. Title` that never found its closing `**`. Every one of these is real
work the count is currently dropping.

**Fix the `TODO.md` lines it names; do not adjust the parser to match the file.**
The reconciliation pass exists because a parser that quietly drops what it can't
read reproduces the exact bug this skill was built to fix: live items once went
invisible to every count because they were numbered entries rather than
checkboxes, and nobody noticed because the count looked confident. Loosening
the parser's patterns to swallow a malformed line hides the next version of that
bug instead of fixing this one. Re-run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/todos/scripts/todos_page.py` after
editing `TODO.md` and confirm `unparsed` reads `0` before treating the page's count
as real.

## Tests

`python3 -m unittest discover tests` from this skill's folder runs the parser, page,
apply, adopt and round-trip tests. The round-trip and page-behavior tests execute
the generated page's JavaScript in jsdom; without it they skip with a loud banner.
To run them, install jsdom (`npm install jsdom`) and point `NODE_PATH` at its
`node_modules`.

**Needs the whole plugin.** This skill reads shared files at `../../reference/` and `../../shared/`, relative to its folder. If they are missing, the skill was copied on its own: install the whole plugin (`/plugin install proofs@proofs`) rather than recreating them.

## Where the page goes

Before you publish or save the page, read `../../reference/where-the-page-goes.md` (the path is relative to this skill's folder). The project's `PROOFS_PAGES` setting picks artifact, file or wifi, and that file says what each means and how copy buttons must fall back.
