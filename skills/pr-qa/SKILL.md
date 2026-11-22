---
name: pr-qa
version: 1.6.0
allowed-tools:
  - Read(/${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/pr_qa_page.py *)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/pr_qa_findings.py *)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/pr_qa_plan.py *)
description: Use when open pull requests, especially ones an AI agent made unattended, need checking before merge and the user wants to see the change rather than read a diff, such as "QA the PRs", "check the agent's work" or screenshots before approving. Differs from visual-qa; it shows a PR's before and after, not a live page's problems.
---

# PR QA

## Overview

An unattended agent run ends at a **green test suite and a draft PR**. Green means
the suite passed — it does not mean the change is right, and it cannot mean the
change looks right. This skill closes that gap: run each PR's branch for real,
photograph it beside the main branch, and put one decision in front of the user per
PR.

**The core principle: show, then ask.** A diff asks the user to simulate a browser
in their head. A before/after pair at their actual phone width does not.

**A real result, from first use:** two PRs, both green, both from the same
pipeline. One was safe. The other passed 59 tests while adding a duplicate
migration that made merging impossible, rendering an empty date box on every
existing record, breaking a form's alignment, and surfacing the date of a note the
user had marked *private*. **No test could have caught any of the four.**

Where this skill says "the project's own notes", it means `CLAUDE.md` (or the
equivalent). How to run the app, set up an isolated checkout, merge, push or deploy
is that file's business, not this skill's; follow it.

## When to Use

- Draft PRs from an unattended agent run are waiting and someone has to decide.
- The user asks to "QA", "check", or "verify" a PR before merging.
- A change is visual and the user wants to see it, not read about it.
- You are about to recommend merging something you have not run.

**Do not use for:** reviewing code you are writing yourself (that is
`superpowers:requesting-code-review`), or a design question about something not yet
built (that is `design-review`).

## Scope: with no arguments, EVERY open PR

**`/proofs:pr-qa` with no arguments QAs every open pull request, not the ones under
discussion.** Enumerate them first, from the API or `gh` — never from memory or from
what the conversation happens to have mentioned. With the GitHub CLI:

```bash
gh pr list --state open --json number,title,headRefName,isDraft,createdAt
```

Without it, call the REST API (`https://api.github.com/repos/OWNER/REPO/pulls?state=open&per_page=100`)
with a token from `$GITHUB_TOKEN` or `gh auth token`. Read `<owner>/<repo>` from
`git remote -v`; never guess it.

This rule is here because of what it costs when scope comes from the conversation.
Picture three open PRs. Two landed minutes ago and are the ones being talked about;
both get QA'd and merged. The third, opened ten hours before either of them, is
never named, so it is never looked at, and it sits for another day. Nothing is wrong
with it: no CI failure, no comment, no note in the to-do list. It is simply not in
anyone's head. **Each batch was reviewed; nobody was counting the total.**

Say what you are covering before you start ("3 open: #2, #5, #6"), and if you
deliberately QA a subset, **say which ones you skipped and why** — a report that
silently covers two of three reads as though it covered everything.

**A start-of-session reminder is the other half of this.** A SessionStart hook that
says how many PRs are open and how old the oldest is keeps an unreviewed one from
going quiet between sessions. The proofs plugin ships it (`hooks/hooks.json`), but it
is off until you opt in. To turn it on for a project, run this from the project root
(it asks permission each time, on purpose):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/install_session_hook.py
```

That adds `"PROOFS_PR_REMINDER": "1"` to the `env` block of the project's
`.claude/settings.json` (and nothing else; it does nothing if it is already there).
No file path is written, so the settings file is safe to commit. With the variable
unset, the hook does nothing at all. With it set, the hook stays silent when there is
no token, no network, or no open PR, so it can never keep a session from starting.

## The Sequence

1. **Read each PR's diff first.** You cannot photograph a change until you know
   which page and which record exercises it. A screenshot of a page that does not
   show the change is worse than no screenshot: it looks like evidence.
2. **Screenshot BEFORE first, on the main branch.** Anything that migrates the
   database makes going back expensive. Take the before pair before you migrate
   anything.
3. **Run the branch for real** — check it out, migrate if needed, boot the app,
   log in, capture the after pair.
4. **Run the PR's own tests**, and say whether it added any. "Tests pass" and "this
   PR is tested" are different claims.
5. **Look for what tests cannot see** — the list below.
6. **Build the Artifact**, publish, and put the link in the working log if the
   project keeps one (see the `working-log` skill).
7. **Act on the export** the user pastes back, one decision per PR.

## The helper scripts

Everything above can be done by hand. These scripts take the mechanical parts, and
they ship inside this skill (in its `scripts/` folder, with tests in `tests/`).
Python 3, standard library only. Run each one exactly as written below; Claude Code
fills in `${CLAUDE_PLUGIN_ROOT}`, and the allow rule only matches the unquoted form.

`python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/pr_qa_collect.py --repo <owner>/<repo> --out <dir>` walks every
open PR, finds the newest run of a QA workflow for its branch (`--workflow` names
it; the default is `pr-qa.yml`), downloads the `pr-qa` artifact if there is one, and
writes `<dir>/meta.json` — one entry per PR with every mechanical field filled in
(`number`, `title`, `branch`, `dir`, `absent_reason`, …) and the judgment fields left
blank for a reviewing session to write after doing Steps 1–5 above. `--repo`
defaults to the origin remote. A PR with no evidence still gets an entry that says
why, because an omission that looks like coverage is worse than a gap.

| Field | What a session writes |
|---|---|
| `cost` | What the agent run cost — dollars, time, or both |
| `tests` | The PR's own test result, and whether it added tests |
| `narrative` | One or two sentences: what changed and why |
| `recommendation` | One of `merge-and-push`, `merge-hold-push`, `send-back`, `wait` |
| `human_findings` | What Step 5 found that the machine could not |

`python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/pr_qa_page.py --meta <dir>/meta.json --out <file>.html` renders
that skeleton into the Artifact described below (`--project` and `--repo` set the
top bar; both have defaults taken from the origin remote). Always pass `--session`, the
session name taken the way the `working-log` skill does: the bar starts with the proofs
mark and a `pr-qa` pill, then project · session · repo, so the user can tell which
session's QA this is.

`python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/pr_qa_findings.py --dir <evidence dir>` turns a PR's before and
after measurements (`before.json`, `after.json`, each a list of `shots`) into the
findings a machine can be sure of. It reports a *regression* (the after is worse
than the before for the same page at the same size), not a state the page was
already in.

`python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/pr_qa_plan.py --map pr_qa_pages.json --ids ids.json` decides which
URLs to photograph for a PR, from the list of changed files (on stdin, or
`--changed-file`). **Write your own map:** a JSON file whose `pages` entries have a
`name`, `match` (glob patterns against changed paths) and `urls` (`label` and
`path`, where `{placeholders}` are filled from `ids.json`). Nothing here knows your
app, so this skill ships no map and no sample-data script; write a map for your
routes and, if a page needs a particular record to show the change, a small script
that seeds one and writes its ids. When nothing matches, the plan says so instead of
falling back to a default page. Adding an entry is the cheapest part of the whole
pipeline: when a QA reports "no page mapped", add one.

**Bring your own producer.** Nothing here takes the screenshots for you. The scripts
read an evidence folder per PR, and you (or a workflow of yours) write it:
`before.json` and `after.json`, each `{"shots": [...]}`, where a shot has `label`
(`before` or `after`), `size` (`phone` or `desktop`), `slug`, `pageLabel`, `path`,
`file` (the PNG's name in the same folder), and optionally `overflow` (pixels of
sideways scroll), `scrollWidth`, `clientWidth`, `errors`, `redirected` and
`landedOn`. `python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/pr_qa_findings.py --dir <folder>` then writes the
`findings.json` the page reads; `plan.json` (from the plan script) is optional.
For `pr_qa_collect.py`, a CI workflow uploads that folder as an artifact named
`pr-qa`, and the collector unpacks it into a `pr-<number>` folder inside the output folder.

**Running the tests.** `python3 -m unittest discover skills/pr-qa/tests` from the
repo root. The page-behavior tests need jsdom: run `npm install jsdom` somewhere and
set `NODE_PATH` to that `node_modules` (or run from a folder that has it); without
it those tests skip rather than fail.

**The recommended decision is BADGED, never PRE-SELECTED. Do not "fix" this.** A
pre-checked recommendation is how a merge gets rubber-stamped by someone who never
looked, and it would make the page's own advice indistinguishable from the reader's
consent. An untouched PR exports `(no decision yet)` — which is the truth — rather
than a silent default. It reads as a missing feature and is not one.

**An empty `human_findings` renders as "not yet read by a reviewer," never as
"clean."** A PR nobody has looked at and a PR a human reviewed and found nothing
wrong with must not read the same on the page — the first is a gap, the second is a
result. Filling `human_findings` is what turns the first into the second; leaving it
empty keeps the gap visible on the page instead of letting it pass silently as
approval.

**No token, no run.** With no `--token`, no `$GITHUB_TOKEN` and no `gh auth token`,
the collector stops at once with a plain message (exit 2) before any network call.
A stale token reaches GitHub and comes back `401`; the collector catches that too
and says "token rejected" rather than showing a traceback.

## Screenshots: use the browser that is already here

**Start with plain Playwright and no `executablePath`.** `npx playwright install`
can fail in a locked-down environment whose network blocks Playwright's download
host — but that is a fact about *installing*, and it does not follow that you must
install anything. A resolvable `playwright` and a browser are usually already
present. Reach for a workaround only after the simple route actually throws.

**If the repo already has a screenshot script, read it and reuse it** rather than
writing a new login routine; it will already know the sign-in form and the traps
specific to the app. Otherwise start from this:

```js
const { chromium } = require('playwright');
const browser = await chromium.launch();               // no executablePath needed
const ctx = await browser.newContext({ viewport: { width: 390, height: 844 },
                                       deviceScaleFactor: 2 });
const page = await ctx.newPage();
await page.goto(base + '/login');                      // your app's sign-in page
await page.fill('#email', EMAIL);                      // your form's field selectors
await page.fill('#password', PASS);
await page.click('form button[type=submit]');
await page.waitForURL(u => !String(u).includes('/login'), { timeout: 20000 });
await page.goto(base + path, { waitUntil: 'networkidle' });
await page.screenshot({ path: out, fullPage: true });
```

**Getting `require('playwright')` to resolve.** It resolves from the project, not
from your script, so a capture script parked outside the project dies with
`Cannot find module 'playwright'` even though the package is installed. Try these in
order; each works where the other does not:

1. Run it with the project's module path set, from the project root:
   `NODE_PATH=./node_modules node <your capture script>` (or keep the script inside
   the project).
2. If the project has no `package.json` at all, find the copy in the `npx` cache:

```js
function requirePlaywright() {
  try { return require('playwright'); } catch (_) { /* npx cache below */ }
  const path = require('path'), fs = require('fs');
  const cache = path.join(process.env.HOME, '.npm/_npx');
  for (const entry of fs.readdirSync(cache)) {
    const candidate = path.join(cache, entry, 'node_modules/playwright');
    if (fs.existsSync(candidate)) return require(candidate);
  }
  throw new Error('Playwright not found');
}
```

**Assert you are signed in before you save a pixel.** A failed login still returns
HTTP 200 — of the *login page* — and `fullPage: true` will happily photograph it. A
first run can capture four immaculate screenshots of the sign-in form. Check that
the URL is not your app's login page **and** that an element unique to the page
under test is present, and exit non-zero if not:

```js
if (page.url().includes('/login') || !(await page.locator(SELECTOR).count())) {
  throw new Error('refusing to save: not a signed-in page showing the change');
}
```

**Redact real customer data in the DOM before capturing.** Admin pages list real
people by name and email, and the shot goes into a shareable artifact. Overwrite the
cells with `page.evaluate` *before* `screenshot()`, so nothing real ever reaches the
PNG — cropping afterwards is not the same guarantee.

**If — and only if — the launch throws `Executable doesn't exist at
.../chromium_headless_shell-NNNN`**, the cached Playwright has pinned a build number
that this machine's browser folder does not carry. Point it at one that exists rather
than downloading anything:

```bash
ls /ms-playwright/                       # chromium-1234, chromium_headless_shell-1234, ...
```

```js
chromium.launch({ executablePath: "/ms-playwright/chromium-1234/chrome-linux64/chrome" })
```

(The folder is wherever your Playwright keeps its browsers; `PLAYWRIGHT_BROWSERS_PATH`
names it when it is set.)

**Last resort, for a Linux machine with no browser at all: `setup-browser.sh` in this
skill's folder.** It pulls `chromium-headless-shell` and its dependency closure from
Debian's archives and needs no root. It stays because the skill is portable and the
next environment may genuinely lack a browser.

```bash
# Redirect, never pipe -- a pipeline is a subshell and the exports are lost.
source path/to/pr-qa/setup-browser.sh > /dev/null   # sets CHROME_BIN, LD_LIBRARY_PATH
# MacAppCodeSignClone off: on a Mac, Google Chrome copies its whole app (~1.4 GB)
# into a temp folder per launch and can leave it behind. Harmless elsewhere.
"$CHROME_BIN" --headless --no-sandbox --disable-gpu --disable-dev-shm-usage \
  --disable-features=MacAppCodeSignClone --hide-scrollbars --screenshot=out.png --window-size=1440,900 "$URL"
```

**Two traps that cost real time**, both worth knowing before your first screenshot:
`isMobile: true` rescales a page that overflows sideways, so `locator.screenshot()`
silently captures a band *above* the element it names — set the viewport width
alone, which is what drives every breakpoint. And never `await` all of
`document.images` when some images live on a host the machine cannot reach: those
fire neither `load` nor `error` and the wait hangs forever. Race a timeout.

**Viewports:** desktop `1440x900`, phone `390x844`, `deviceScaleFactor: 2`. Take
**both for every PR**, even a desktop-only change — the user checks their phone
first.

### The four things that ruin a screenshot run

Run this pre-flight list before the first shot. The examples are for a Rails app with
Tailwind; translate them to your stack.

- **Unstyled pages.** Build the stylesheet before booting (for example
  `bin/rails tailwindcss:build`), or every shot is unstyled and worthless. A fresh
  checkout has no build and fails this way.
- **Missing settings in a separate working folder.** Untracked files such as `.env`
  and `node_modules` do not follow a new checkout or worktree. Link or copy them in
  from the main checkout, or the database fails with an error that reads like a
  database problem and is not. How to set one up is in the project's own notes.
- **Port collisions.** Other projects and other sessions may be on this machine.
  Pick a high port and say which one you used.
- **A record that does not show the change.** Find or create one that does. Say in
  the report which record you used and why.

## What to look for that the tests cannot

This is where the value is. Every one of these was found in real use.

| Look for | Why tests miss it |
|---|---|
| **Two PRs adding the same migration** | Each passes alone; merging both fails on "column already exists" |
| **New column, no backfill, no nil guard** | Fixtures have values; existing production rows do not |
| **Alignment and wrapping** | No assertion describes a layout |
| **A private/hidden record reaching a visible field** | Scoping is invisible to a test that never creates a private record |
| **A whole page sitting outside a lock or permission check the others honor** | Nothing asserts "this page was included"; the suite stays green while one page is readable when it should not be |
| **A comment that contradicts the code** | Nothing asserts on prose |
| **Whether the PR added tests at all** | A green suite says nothing about coverage of *this* change |
| **Whether the reported bug reproduces** | The fix may be real and the diagnosis wrong |

**Say so when a bug does not reproduce.** On first use, a "mobile overlap" fix was
merged after measurement at three phone heights showed **no overlap at any of
them** — the real cause was iOS Safari's wider native date control, which a Linux
machine cannot render. The change was still an improvement, but calling it a
*confirmed fix* would have been false, and the user needed to check it on a real
phone. **A QA that only confirms is not a QA.**

## The Artifact

**REQUIRED SUB-SKILL: load `artifact-design` before writing the page.**

Structure, in order:

1. **Project bar** — proofs mark and `pr-qa` pill · brand · session · `owner/repo`. Read them from `CLAUDE.md` and
   `git remote -v`; never guess a repo slug.
2. **Verdict table up top** — PR, ticket, cost, test result, your recommendation.
   The user should be able to stop reading here and still decide.
3. **One card per PR**, ordered *worst first* — the one that must not be merged
   goes at the top, with a status chip and a colored left border.
4. **The screenshot viewer** — two segmented controls per PR, **Before/After** and
   **Desktop/Phone**, swapping one `<img>`. Both default to the view that shows the
   change best (usually After + whichever size the change is about).

   **The phone shot must render at its TRUE phone width — cap the frame at 390px and
   center it.** A bare `img { width: 100% }` stretches a 390px capture across a
   ~900px card, a 2.3x enlargement in which giant type and a single column read as a
   *desktop* screenshot. A user once reported exactly that: "the phone screenshots
   are fullscreen desktop." They were not — the capture was correct at 390x844 and
   only the display was wrong, which is the worst version of this bug, because the
   evidence looks broken while the run was fine. Toggle a class with the size
   control rather than styling the `<img>` once:

   ```css
   .shotwrap img { display: block; width: 100%; height: auto; }
   .shotwrap.is-phone { max-width: 390px; margin: 0 auto; }
   ```
   ```js
   wrap.classList.toggle('is-phone', view.size === 'phone');
   ```

   Capture at `deviceScaleFactor: 2` so the PNG is 780px wide and stays crisp when
   shown at 390. **Assert it**: the jsdom check below must confirm the phone view
   adds the constraint and the desktop view removes it — a purely visual regression
   is invisible to every other test in this skill.
5. **Findings**, numbered, each one sentence of what and one of why it matters.
6. **The decision**, as radio options with a one-line consequence under each, and
   the recommended one marked (badged, never pre-selected; see above). Always
   include a "wait — I will QA it myself" option: the user is allowed to not decide.
7. **Copy my decisions** — plain text, one block per PR, that they paste back. A PR
   the user did not touch exports "(no decision yet)".

**Embed the images as `data:` URIs.** A strict CSP blocks every external request, so
a `src` pointing anywhere is a broken image. Eight PNGs is about 1.5 MB base64,
well inside the 16 MB limit — but check, and say so if you have to drop a pair.

**Put the QA on its own page, not in the working log.** A megabyte of base64 makes
every later log update slow to publish. Link it from a working-log entry instead.

**Verify before publishing.** Extract the `<script>`, `node --check` it, then load
the page in **jsdom** (`runScripts: 'dangerously'`, stub `navigator.clipboard`) and
assert: every image `src` starts with `data:image/png;base64,`, flipping
before/after actually changes the `src`, **selecting Phone adds the `is-phone`
constraint and Desktop removes it**, the decision counter increments, and the
export contains a decision line per PR. One bad escape kills the whole script
silently and leaves a page that looks fine and does nothing.

**Compare whole `src` values, never a prefix.** Asserting the four captures are
distinct by hashing `img.src.slice(0, 200)` reports 3 of 4 — every PNG data URI
shares a long identical header, so the slice collides and a correct page fails its
own test. Compare the full string, or hash the source files.

## Decisions, and what each one means

State the *action*, not the label — "merge" is ambiguous, and the difference
matters when pushing to the main branch needs permission. How this project merges,
pushes and deploys is in its own notes; follow them.

| Option | What you actually do |
|---|---|
| **Merge and push** | Merge the PR, push. Say if a deploy or migration is needed. |
| **Merge, hold the push** | Merge locally; nothing leaves the machine. |
| **Send it back** | The findings become the brief for another attempt. |
| **Wait — I will QA it myself** | Nothing. |

**Two traps in acting on the answer:**

- **A draft PR cannot be merged through the REST API** — it 405s with "Pull Request
  is still a draft". Mark it ready first, which is GraphQL-only
  (`markPullRequestReadyForReview`), then merge.
- **"Send it back" may not be executable by you.** If the agent's brief comes from a
  ticket you can only read, you cannot inject findings into it. Check before you
  offer the option, and if it needs the user to edit the ticket, say so rather than
  quietly doing the work yourself instead.

## Common Mistakes

- **Screenshotting the main branch twice.** Confirm the branch is actually checked
  out and migrated; identical before/after pairs are the giveaway.
- **Leaving the repo dirty.** Migrations rolled back, the main branch checked out,
  extra worktrees removed. Someone else may be using this machine.
- **Recommending a merge you did not run.** If the app would not boot, say that.
- **Burying the bad news.** Worst PR first, verdict in the table at the top.
- **Publishing images you have not looked at.** Read every screenshot before it goes
  in the page. A blank or unstyled shot presented as evidence is worse than none.

**Needs the whole plugin.** This skill reads shared files at `../../reference/` and `../../shared/`, relative to its folder. If they are missing, the skill was copied on its own: install the whole plugin (`/plugin install proofs@proofs`) rather than recreating them.

## Where the page goes

Before you publish or save the page, read `../../reference/where-the-page-goes.md` (the path is relative to this skill's folder). The project's `PROOFS_PAGES` setting picks artifact, file or wifi, and that file says what each means and how copy buttons must fall back.
