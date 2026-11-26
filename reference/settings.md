# Proofs settings

Every setting Proofs reads, one table row each. The source of truth is `shared/settings.json`; `shared/settings.py` resolves and writes them, and the settings page (`/proofs:settings`) edits them. All keys start with `PROOFS_` and live in the `env` block of a Claude Code settings file.

**Where a value comes from**, strongest first: `.claude/settings.local.json`, `.claude/settings.json`, the user file, the process environment, the default. Files beat the environment because Claude Code copies them into the environment only at startup, so a change made mid-session wins; restart Claude Code for hooks to see it.

**Scope** is the file a setting is saved to when you do not choose one. User is `~/.claude/settings.json` (or `$CLAUDE_CONFIG_DIR/settings.json`), project is `.claude/settings.json` (committed, shared with the team), local is `.claude/settings.local.json` (this computer only).

**Never settings:** nothing here lowers a check. Contrast, the 44 px tap floor, line length, edges, off-center and near-copy checks are fixed, and `PROOFS_MIN_TEXT` and `PROOFS_MIN_TAP` can only go up. 390 and 1280 are always captured. Permissions are never touched.

Commands (the first three only read; `--set`, `--unset` and `--apply` write, so they ask each time):

```
python3 <plugin root>/shared/settings.py --print
python3 <plugin root>/shared/settings.py --json
python3 <plugin root>/shared/settings.py --spec
python3 <plugin root>/shared/settings.py --set KEY=VALUE [--scope user|project|local]
python3 <plugin root>/shared/settings.py --unset KEY [--scope user|project|local]
python3 <plugin root>/shared/settings.py --apply ROWS_DIR [--dry-run]
```

Exit codes: 0 ok, 1 an `--apply` row was skipped, 2 an invalid value or unknown key, 3 a settings file that cannot be read.

## Reading and cost

| Key | What it does | Default | Range | Scope |
|---|---|---|---|---|
| `PROOFS_COST_CAP_USD` | Design-review spend cap. An estimate Claude reasons about, not a limit it enforces. Design-review stays under it. | 5 $ est. | 1 to 100 $ est. | user |
| `PROOFS_PAGES` | Where pages go. How you read the pages Proofs builds. | artifact | one of artifact, file, wifi | user |
| `PROOFS_IMAGE_QUALITY` | Screenshot quality. Lower makes smaller pages, which load faster on a phone. | 70 | 1 to 100 | user |
| `PROOFS_IMAGE_MAX_WIDTH` | Screenshot widest size. Screenshots wider than this are scaled down. | 1600 px | 16 to 20000 px | user |
| `PROOFS_SEND_WAIT_MIN` | Send to Claude wait. How long a page waits before it says Claude has not picked up your message. | 5 min | 2 to 30 min | user |
| `PROOFS_PAGE_WARN_MB` | Page size warning. Proofs warns when a page is bigger than this. | 3 MB | 1 to 15 MB | user |

## Checks on this site

| Key | What it does | Default | Range | Scope |
|---|---|---|---|---|
| `PROOFS_SPELLING` | Spelling check. Flags British spellings in what the reader sees. | off | one of american, off | project |
| `PROOFS_MIN_TEXT` | Smallest text. Can only go up from 16 px. | 16 px | 16 to 32 (raise only) px | project |
| `PROOFS_MIN_TAP` | Smallest tap target. Can only go up from 44 px. | 44 px | 44 to 96 (raise only) px | project |
| `PROOFS_EXTRA_WIDTHS` | Extra capture widths. 390 and 1280 are always captured. | none | whole numbers 400 to 2560, separated by commas px | project |
| `PROOFS_DESIGN_OPTIONS` | Design options per item. Fewer is cheaper, with less to choose from. | 3 | one of 2, 3 | project |
| `PROOFS_CRITIC` | Who scores the options. Claude scoring its own work tends to pass it. | helper | one of helper, self | project |
| `PROOFS_CORRECTION_PASSES` | Correction passes. Rebuilds after the critic, at most. | 1 | one of 0, 1, 2 | project |
| `PROOFS_PHOTO_CANDIDATES` | Photo candidates per spot. photo-picker shows up to this many. | 3 | 1 to 6 | project |
| `PROOFS_QA_MOCKUPS` | Mockups per visual-qa item. Suggested fixes shown for each problem. | 2 | 1 to 3 | project |
| `PROOFS_CHECKPOINT_ITEMS` | Review-cycle checkpoint. Saves a handoff after this many items. | 5 items | 1 to 50 items | project |

## Running the app

| Key | What it does | Default | Range | Scope |
|---|---|---|---|---|
| `PROOFS_PORT` | Dev-server port. The port Proofs starts your app on for screenshots. | 3311 | 1024 to 65535 | project |
| `PROOFS_BASE_PORT` | Before-shot port. The port for the base copy of the app that pr-qa photographs for its before shot. | 3411 | 1024 to 65535 | project |
| `PROOFS_SERVER_TIMEOUT` | Server start timeout. How long to wait for the app to start answering. | 120 s | 10 to 900 s | project |
| `PROOFS_DESIGN_PROFILE` | Design profile file. Where design-review keeps what it learned about your site's look. | docs/design-profile.md | a path | project |
| `PROOFS_STYLE_GUIDE` | Style guide file. Where the style-guide skill records accepted rules. | docs/style-guide.html | a path | project |
| `PROOFS_CHANGELOG_DIR` | Changelog folder. Where the changelog skill keeps its markdown files. | docs/changelog | a path | project |
| `PROOFS_TODO_FILE` | To-do file. The open-work list the todos skill reads. | TODO.md | a path | project |
| `PROOFS_TODO_ARCHIVE_DIR` | To-do archive folder. Where finished to-dos are archived, one file per month. | docs/todo-archive | a path | project |
| `PROOFS_TODO_TITLE` | To-do title length. Longest title shown on the to-do page. | 96 chars | 40 to 200 chars | project |

## Pull requests

| Key | What it does | Default | Range | Scope |
|---|---|---|---|---|
| `PROOFS_PR_REMINDER` | PR reminder at session start. Lists open pull requests when a session begins. | off | on or off (1 or 0) | project |
| `PROOFS_AGENT_BRANCH_PREFIX` | Agent branch prefix. Pull requests on branches starting with this are labeled as AI-agent work. Separate several with commas. | agent/ | words separated by commas | project |
| `PROOFS_PR_REMINDER_TIMEOUT` | PR reminder network wait. How long the reminder waits for GitHub before giving up. | 5 s | 1 to 60 s | user |
| `PROOFS_QA_PATHS` | pr-qa visual paths. A pull request touching these paths counts as a visible change. Separate with commas. | app/,src/,lib/,public/,config/routes.rb | words separated by commas | project |
| `PROOFS_QA_WORKFLOW` | pr-qa workflow file. The GitHub workflow file pr-qa looks for. | pr-qa.yml | a path | project |
| `PROOFS_QA_MAP` | pr-qa page map file. Maps changed files to the pages to photograph. | pr_qa_pages.json | a path | project |

## This computer

| Key | What it does | Default | Range | Scope |
|---|---|---|---|---|
| `PROOFS_BROWSER_CHANNEL` | Browser. Which browser takes screenshots. Auto uses the bundled one, then Chrome. | auto | `auto` or a name | local |
| `PROOFS_PLAYWRIGHT` | Playwright folder. Where Playwright is installed. Auto checks the project, then the Proofs cache. | auto | `auto` or a name | local |
| `PROOFS_BASE_DIR` | pr-qa base folder. Where pr-qa checks out the base branch for its before shot. | .proofs/base | a path | local |
