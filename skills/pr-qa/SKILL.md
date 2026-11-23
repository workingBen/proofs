---
name: pr-qa
version: 1.9.2
allowed-tools:
  - Read(/${CLAUDE_PLUGIN_ROOT}/**)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/pr_qa_page.py *)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/pr_qa_findings.py *)
  - Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/pr_qa_plan.py *)
  - Bash(node ${CLAUDE_PLUGIN_ROOT}/skills/visual-qa/scripts/capture.cjs *)
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

## Default path: one turn, page first

The whole flow for a PR whose app runs with one start command. The goal is a built page in this turn: before and after shots, findings, page, then the extras.

**House rules.** Same as every proofs capture skill; full text in `../../reference/house-rules.md`.

1. **Finish in this turn.** Build, smoke-check and screenshot before you reply; the next turn re-reads the whole session and costs more each time. Write big files (HTML, spec JSON, scripts) with the Write tool and never print them back with `cat`, `head` or `Read`; the helpers print short summaries.
2. **Stay in two folders.** Read only inside the project (the folder Claude Code started in) and the plugin folder. Do not read parent folders: their `CLAUDE.md` is already loaded for you. Write specs, scratch scripts, screenshots and pages only under `.proofs/` in the project, never the system temp folder, `$TMPDIR` or `~`. The exceptions are the Playwright install in `~/.cache/proofs-playwright` and pr-qa's `PROOFS_BASE_DIR` base folder, when it is set. Write the Playwright folder only with its one install line; never `ls` or Read it to see whether Playwright is there (it is outside the project, so the call is refused): the capture and `--smoke` report a missing install themselves, with exit 2 and the line to run.
3. **One command per Bash call.** No pipes, redirects, `;`, `&&`, `cd`, `$(...)` or `VAR=` in front: Claude Code matches its allow rules against the whole command, and any of those makes it ask (or, in `claude -p`, refuse).
4. **Use the helpers' own checks, not ad hoc tools.** Capture prints each shot's size and overflow; never run `file`, `magick`/`identify` or `sips`, and change your own mockups with Edit or Write, never `sed -i`.

**Steps.**

1. **List every command once, up front, in one message**, with the exact text and literal paths (no variables): the eleven lines below, the `cp .env <base folder>/<app-dir>/.env` line if the app has a `.env` (it goes before the install in the base folder), the install in the checkout (`npm ci`) if its `node_modules` is missing or the PR's diff touches `package.json` or the lockfile (run it after `gh pr checkout`, before the after capture), the `pr_qa_page.py --smoke` call and the `open .proofs/pages/pr-qa.html` call from step 4 (both stated extras, not among the eleven), and the Playwright install line if `capture.cjs` reports Playwright missing. Playwright lives in `~/.cache/proofs-playwright`, one install per machine (`npm install --prefix ~/.cache/proofs-playwright playwright@1.61.1`); do not install it in the system temp folder or the project. Then run them without further narration.
2. **Write `.proofs/capture/pages.json`** with the Write tool: the pages the diff touches (`pr_qa_plan.py` when a map exists), each with a `name` and `path`. **Pick the widths from the diff.** `390,1440` is the default. If the PR's added lines use a responsive prefix, 1440 and 390 sit on either side of the new layout but never at its tightest, so add one width just above that breakpoint to both capture lines (Tailwind's defaults; use the project's own if its config changes them): `sm:` 656, `md:` 784, `lg:` 1040, `xl:` 1280, `2xl:` 1552. An `lg:` two-column hero, for example, takes `--sizes 390,1040,1440`. Add at most two extra widths (the two breakpoints the changed layout leans on most) and name any you left out on the page.
3. **Run the commands in order.** Replace `<n>` with the PR number, `<base>` with its target branch and `<app-dir>` with the folder holding `package.json` (use `.` when it is the root), and the ports with free high ones. The first line, `printenv PROOFS_BASE_DIR`, prints the `PROOFS_BASE_DIR` setting, or nothing (exit 1) when it is not set. If it printed a path, use `<PROOFS_BASE_DIR>/<repo folder>-pr-qa-base` as the base folder, written literally in every line that names it; otherwise the base folder is `.proofs/base`. If the app has a `.env`, copy it with one extra Bash call (`cp .env <base folder>/<app-dir>/.env`, literal paths) before the install; never Read or Write it, because secrets must not enter the transcript. **`gh pr checkout <n>` is not optional: the after shot must be the PR's code.** If the session is already on the PR branch it still runs (it is a no-op), so the path is the same every time. If the PR's diff touches `package.json` or the lockfile, run the project's install (`npm ci`) in the checkout now, before the after capture; this is a stated extra, not one of the eleven, and so is the `--smoke` call in step 4. Skip every `npm ci` line when `<app-dir>` has no `package.json` (a static site). **No GitHub PR (branches compared locally): 11 Bash calls (before the extras from step 4 and the `cp .env` calls; when the app has a `.env` that is two extra calls here, one into the base folder and one into the branch worktree), and your own checkout is never touched.** Run the eleven lines with these changes: skip `git fetch origin` and `gh pr list` (no remote, so no GitHub PRs to list; nine lines remain, and the extra `git worktree remove` plus the install in that worktree bring the total to 11; the `--smoke` check from step 4 is a stated extra on top, as in the default path); use the local `<base>` branch in place of `origin/<base>` (`--detach` lets it be the branch checked out now); in place of `gh pr checkout <n>`, put the branch in the same slot with `git worktree add --detach .proofs/base <branch>`, copy `.env` and install there as for the base, take the after capture with `--cwd .proofs/base/<app-dir>`, then `git worktree remove --force .proofs/base` again; use the branch name in place of `<n>`.

```bash
printenv PROOFS_BASE_DIR
git fetch origin
gh pr list --state open --json number,title
git worktree add --detach .proofs/base origin/<base>
npm ci --prefix .proofs/base/<app-dir>
python3 ${CLAUDE_PLUGIN_ROOT}/shared/capture/with_server.py --cwd .proofs/base/<app-dir> --start "npm run dev -- -p 3411" --url http://localhost:3411/ -- node ${CLAUDE_PLUGIN_ROOT}/skills/visual-qa/scripts/capture.cjs .proofs/capture/pages.json --out .proofs/evidence/pr-<n> --sizes 390,1440 --evidence before
git worktree remove --force .proofs/base
gh pr checkout <n>
python3 ${CLAUDE_PLUGIN_ROOT}/shared/capture/with_server.py --start "npm run dev -- -p 3411" --url http://localhost:3411/ -- node ${CLAUDE_PLUGIN_ROOT}/skills/visual-qa/scripts/capture.cjs .proofs/capture/pages.json --out .proofs/evidence/pr-<n> --sizes 390,1440 --evidence after
python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/pr_qa_findings.py --dir .proofs/evidence/pr-<n> --out .proofs/evidence/pr-<n>/findings.json
python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/pr_qa_page.py --meta .proofs/evidence/meta.json --out .proofs/pages/pr-qa.html --session "<session name>"
```

4. **Write `.proofs/evidence/meta.json`** with the Write tool before the last line (shape: see the helper scripts below). List every other open PR from `gh pr list` that is not on the page in a top-level `skipped`: `{"prs": [...entries...], "skipped": [{"number": 2, "reason": "not requested"}]}` (a bare list of entries still works and means none skipped). If you were asked for one PR, still list the others in `skipped` with the reason; the page shows them as one line, `Other open PRs: #2 (not requested)`, under the verdict table. Then build the page with that last line (it prints the page's size) and run `python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/pr_qa_page.py --smoke .proofs/pages/pr-qa.html` before you report: it opens the page in a real browser and checks for page or console errors, images that did not load, decision radios that will not check and an empty copy button, prints one JSON line (`ok`, `problems`) and exits 0 only when ok. Exit 2 means Playwright is missing: say so instead of calling the page checked. Fix every problem it names and rebuild. **The page is built in this turn, before any extra checks.** Open it with one Bash call, exactly `open .proofs/pages/pr-qa.html`; if that is refused, do not retry: print the path and the command. Before and after share one `--out` folder: every file is prefixed `before-` or `after-`, and any width besides 1440 and 390 (a breakpoint width from step 2, or 1280) is labeled with its width on the page, "(1040)", so it reads differently from 1440.
5. **Only then, polish if time allows:** menu taps (an `actions` entry in pages.json), more states, the PR's own tests (in `claude -p`, only if their command is pre-approved; otherwise say on the page they were not run). A phone measurement that the capture's `innerWidth` guard rejected, or any phone view you could not take because Playwright is missing, goes on the page as "not measured" (the guard aborts the whole run, so rerun that line with `--sizes 1440`), never as a pass, and never gets a Chrome `--window-size` substitute.

Do not ask the user which capture method to use. Use the one above; if it fails, use the fallback in design-review step 2 and say on the page which one ran. The capture helper adds `.proofs/` to `.git/info/exclude` the first time it runs; you do not need to. `git status` may list `.proofs/` until then; ignore it.

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
2. **Screenshot BEFORE first, from a base worktree.** Anything that migrates the
   database makes going back expensive, so take the before pair before you
   migrate anything.

   **First pick the base worktree path, `<base-dir>`:**
   `$PROOFS_BASE_DIR/<repo folder name>-pr-qa-base` if the `PROOFS_BASE_DIR`
   setting is set, else `.proofs/base` (repo folder name = basename of
   `git rev-parse --show-toplevel`). Some setups block `git worktree add` inside
   code folders except one sanctioned folder; for them, set `PROOFS_BASE_DIR` to
   that folder, as an absolute path (no `~`, no relative path), in the `env` block
   of `.claude/settings.json` (project or user level). Resolve it **once**
   (`printenv PROOFS_BASE_DIR`, which prints nothing when it is unset), confirm the folder exists, and write the
   **literal resolved path** in every later command (`git worktree add`, `--cwd`,
   the log path `<base-dir>/.proofs/server.log`,
   `git worktree remove`): shell variables do not survive between Bash calls, and
   hooks read literal paths. If `<base-dir>` already shows in `git worktree list`,
   run `git worktree remove --force <base-dir>` only if it is this repo's own
   leftover pr-qa base; otherwise stop and ask.

   The capture helper adds `.proofs/` to `.git/info/exclude` the first time it runs;
   you do not need to. `git status` may list `.proofs/` until then; ignore it.

   ```bash
   git fetch origin
   git worktree add --detach <base-dir> origin/<base>
   ```

   (`<base>` here is the PR's target branch.) Copy untracked settings (`.env`) into `<base-dir>`, then
   **install dependencies there** with the project's own install (`npm ci`,
   `bundle install`, ...). Do not symlink `node_modules`: Next.js with Turbopack
   returned HTTP 500 through a symlinked one. Build the stylesheet there too.
   Capture the before pair through the helper (step 3) with `--cwd <base-dir>` and
   read both PNGs. **Then remove the base worktree at once**
   (`git worktree remove --force <base-dir>`, the literal path), before you check
   out the branch, migrate or run any tests. It is a full second copy of the project
   inside the repo: `info/exclude` hides it from git, not from test runners, linters
   or `tsc` that walk the tree, so the PR's test run could pick up the base's files.
3. **Run the branch for real**: with the before pair taken and `<base-dir>` removed,
   check it out, migrate if needed, and capture the
   after pair through the same helper from the PR checkout (no `--cwd`). Both
   shots use the helper, which starts the server, waits for the URL, runs the
   capture and always stops the server, so nothing dies between turns.
   - **Find the start command** in the project's `CLAUDE.md`, README, `package.json`
     scripts, `Procfile` or `bin/dev`; if none gives one, **ask the user**.
   - **Pick free high ports.** A server already answering at `--url` is treated as
     ready and left running, so a reused port would be captured by mistake.
   - **The capture command is the default path's `capture.cjs` line**, run through
     `with_server.py --cwd <base-dir>` for the before run, and the same line with no `--cwd`
     for the after run. Exit codes: 3 the server never answered (read `<base-dir>/.proofs/server.log`
     for the before run, `.proofs/server.log` for the after run), 4 it exited early, 5
     another run holds the lock; anything else is the capture's own. 3 is also `capture.cjs`'s untrusted-width exit and 2 with "Playwright not found" is the missing install; the stderr line says which. Exit 0 does not
     prove the page is right: read each PNG and confirm it shows the route you meant.
     Never start a server yourself with `run_in_background` or `&`: in `claude -p` the
     turn then never ends.
4. **Run the PR's own tests**, and say whether it added any. "Tests pass" and "this
   PR is tested" are different claims.

   **Not a Node app?** Use the project's own toolchain in the same slots, in the
   exact forms the README's `--project` allow block covers (it reads the stack from
   the project's marker files; `--stack` names it when there are none). For a
   Django app: `python3 -m venv .venv` and `.venv/bin/pip install -r requirements.txt`
   in place of `npm ci`, `--start ".venv/bin/python manage.py runserver 3411 --noreload"`
   for the helper, and `.venv/bin/python manage.py test` for the tests; the before
   run can start the checkout's `.venv` by its path. Other forms (the system Python running
   `manage.py`, `source .venv/bin/activate`, `python3 -c ...`) are not covered, so they ask.
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
| `rise_explained` | Only when a merge is recommended over a finding that rose: one sentence naming the elements and why they are acceptable. Renders under "Why merge anyway" |
| `human_findings` | What Step 5 found that the machine could not |

`python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/pr_qa_page.py --meta <dir>/meta.json --out <file>.html` renders
that skeleton into the Artifact described below (`--project` and `--repo` set the
top bar; both have defaults taken from the origin remote). Always pass `--session`, the
session name taken the way the `working-log` skill does: the bar starts with the proofs
mark and a `pr-qa` pill, then project · session · repo, so the user can tell which
session's QA this is.

`python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/pr_qa_findings.py --dir <evidence dir> --out <evidence dir>/findings.json` turns a PR's before and
after measurements (`before.json`, `after.json`, each a list of `shots`) into the
findings a machine can be sure of. It reports a *regression* (the after is worse
than the before for the same page at the same size), not a state the page was
already in.
With no layout measurements in `before.json` and `after.json` (`overflow`,
`scrollWidth`, `smallTargets`, `errors`), the verdict is `unknown`, "not measured",
never `clean`. Pass `--out <dir>/findings.json` to save it; stdout then carries a one-line summary.

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
`landedOn`. `python3 ${CLAUDE_PLUGIN_ROOT}/skills/pr-qa/scripts/pr_qa_findings.py --dir <folder> --out <folder>/findings.json` then writes the
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

## Screenshots: the default path first

The default path's `capture.cjs` line is the capture, and it is chosen, not offered. It
needs Playwright (from `PROOFS_PLAYWRIGHT`, the project, or `~/.cache/proofs-playwright`);
install it once into that folder when `capture.cjs` says it is missing. If Playwright cannot be
installed, the phone views are "not measured"; never substitute a Chrome `--window-size` shot for them.

**If the repo already has a screenshot script, read it and reuse it** for sign-in: it
already knows the form and the traps specific to the app. `capture.cjs` takes an
`actions` entry per page for clicks, waits and `eval` steps (no `fill`; use `setup` or `eval` for form input), and `signin.example.cjs` in the
visual-qa scripts folder shows a login. Only if `capture.cjs` cannot do what a page needs,
write a Playwright script of your own with a 390 by 844 viewport at `deviceScaleFactor: 2`.

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
source path/to/pr-qa/setup-browser.sh   # sets CHROME_BIN, LD_LIBRARY_PATH
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
  do not follow a new checkout or worktree: copy them in. Install dependencies in
  the worktree (`npm ci`, `bundle install`) and do not symlink `node_modules`.
  Without the settings, the database fails with an error that reads like a database
  problem and is not.
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

This section is for a page you build by hand; `pr_qa_page.py` already does all of it.

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
a `src` pointing anywhere is a broken image. `pr_qa_page.py` embeds each shot as a
WebP (a JPEG when that is smaller), scaling a page taller than WebP's 16383 px down to
fit, so six full-page shots of a long page come to about 2.6 MB, not 14 MB of PNG
(Vue run 1). With neither ImageMagick nor cwebp installed the PNGs go in as they are;
check the size it prints, and say so if you have to drop a pair.

**Put the QA on its own page, not in the working log.** A megabyte of base64 makes
every later log update slow to publish. Link it from a working-log entry instead.

**Verify before publishing (a hand-built page only).** Extract the `<script>`, `node --check` it, then load
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

Never recommend a merge when a finding rose and you have not named the elements
and said why it is acceptable (`rise_explained`); otherwise recommend `send-back`
or `wait`. The page builder refuses the combination.

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
  the base worktree removed (step 2 removes it right after the before shots; check
  it is gone) with `git worktree remove --force <base-dir>` (default
  `.proofs/base`; use the literal path), as in step 3, so `git worktree list` is
  clean. Someone else may be using this machine.
- **Recommending a merge you did not run.** If the app would not boot, say that.
- **Burying the bad news.** Worst PR first, verdict in the table at the top.
- **Publishing images you have not looked at.** Read every screenshot before it goes
  in the page. A blank or unstyled shot presented as evidence is worse than none.

**Needs the whole plugin.** This skill reads shared files at `../../reference/` and `../../shared/`, relative to its folder. If they are missing, the skill was copied on its own: install the whole plugin (`/plugin install proofs@proofs`) rather than recreating them.

## Where the page goes

Before you publish or save the page, read `../../reference/where-the-page-goes.md` (the path is relative to this skill's folder). The project's `PROOFS_PAGES` setting picks artifact, file or wifi, and that file says what each means and how copy buttons must fall back.
