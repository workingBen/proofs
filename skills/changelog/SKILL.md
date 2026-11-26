---
name: changelog
version: 1.3.4
description: Use when the user wants a signed-in changelog page for their app (or one per sub-app) backed by markdown files, and at the end of any session that shipped something a user would notice, to add a dated entry. Differs from todos; it records what shipped, not open work.
---

# Changelog Skill

Builds a signed-in-only changelog page (one per app or sub-app) backed by plain markdown files, shown as a vertical timeline with one section per calendar month. Also defines the ongoing habit of updating it. It works with any stack: this skill specifies the file format, the parsing and grouping rules, the page's behavior and the tests, and you write the code in whatever language and framework the project already uses.

**Results first.** Nothing matters more than a result the user wants. Save tokens by cutting waste, never by cutting a check, an option or a revise pass the result needs (full text: `../../reference/house-rules.md`).

**Needs the whole plugin.** This skill reads shared files at `../../reference/` and `../../shared/`, relative to its folder. If they are missing, the skill was copied on its own: install the whole plugin (`/plugin install proofs@proofs`) rather than recreating them.

Read the settings: `python3 ${CLAUDE_PLUGIN_ROOT}/shared/settings.py --print` (pre-approved). Use the values it shows wherever this file says *the changelog folder* (`PROOFS_CHANGELOG_DIR`). `docs/changelog/` below is that setting's default; use the setting's value in its place.

## When to use

- **Setup**: the user asks for a changelog page, or you're bringing this skill into a new project for the first time.
- **Maintenance** (the common case once set up): at the end of any session where you shipped something a user would notice (a feature, a redesign, a real bug fix), add a dated entry to the relevant app's current changelog file. Do this without being asked, the same way you'd update a project's own backlog file. Skip it for lint, refactor and typo-only sessions.

## What the project needs

- **A sign-in check** your app already has: a gate that redirects signed-out visitors to the sign-in page and returns them to the original destination afterward. Use the app's own, whatever it is called.
- **A markdown renderer** for entry bodies. Any markdown-to-HTML library works; it is called from one place in the shared view. If entries never need inline formatting, show them as plain escaped text instead.
- **Somewhere to keep the files**: a `docs/changelog/` folder, tracked in version control like any other source file.
- **A way to style a timeline.** If the project's CSS tooling scans source files for complete class names (utility-class frameworks do), **never build a class name by string interpolation** (`"bg-" + color + "-200"`). The scanner never sees the full string, and the style silently goes missing in production. Choose between complete literal class strings with a real conditional.

## Setup steps (new project, or first sub-app in this project)

### 1. File format

One markdown file per app: `docs/changelog/<app>.md`. Newest day first, forever. There is no separate archive file: past months stay in this same file, the page buckets them by calendar month when it renders, and the file only ever grows, so there is nothing to move and nothing that can silently vanish on an ephemeral production filesystem.

```markdown
## 2026-07-21
- Fixed broken link previews on the share page
- Added a switcher between the two plan types

## 2026-07-20
- ...
```

**Keep the file to exactly that shape.** The parser only ever sees `## <date>` headings and top-level `- ` bullets. A preamble, `###` subheadings, indented or nested bullets, `*`-style bullets and blank-line grouping are all silently invisible to it, not an error.

### 2. Parser

Write a small function that reads a file and returns a list of day groups, each with a `date` (the heading text) and `entries` (the bullet texts, with the `- ` prefix removed and whitespace trimmed). Rules:

- A missing file returns an empty list.
- A file with no `## ` headings returns an empty list.
- Lines inside a day that are not `- ` bullets are ignored.
- File order is preserved. The newest-first invariant of the file is what makes the next step cheap.

Reference implementation (Python; translate it to your stack):

```python
import datetime
import os
import re

def parse(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        text = f.read()
    chunks = re.split(r"^## ", text, flags=re.M)[1:]   # drop anything before the first heading
    groups = []
    for chunk in chunks:
        date_line, *rest = chunk.splitlines() or [""]
        entries = [l[2:].strip() for l in rest if l.startswith("- ")]
        groups.append({"date": date_line.strip(), "entries": entries})
    return groups
```

### 3. Grouping entries by month

Add a second function that buckets day groups by calendar month, relying on the parser's newest-first order so no separate sort is needed (grouping that preserves first-seen order is enough). A group whose date cannot be parsed goes into its own `(0, 0)` bucket instead of raising: the parser is deliberately lenient about headings, and a bad heading should degrade the page, not take it down.

```python
def month_key(date_string):
    try:
        d = datetime.date.fromisoformat(date_string)
    except ValueError:
        return (0, 0)
    return (d.year, d.month)

def group_by_month(groups):
    months = {}
    for g in groups:
        months.setdefault(month_key(g["date"]), []).append(g)
    return [{"year": y, "month": m, "groups": gs} for (y, m), gs in months.items()]
```

### 4. The timeline view

One shared view or component renders a list of `{label, items}` groups as a vertical timeline: a month or day label with a thin rule beside it, then a vertical line with a dot per entry. Each item is either a plain string (one line, run through the markdown renderer) or a `{title, meta}` pair (a title line plus a muted second line). The view takes the line and dot colors as parameters, so each app can have its own accent.

Put each entry's rendered markdown into **one container element** that is not itself a paragraph. Markdown renderers usually return paragraph-wrapped blocks, and nesting a paragraph inside a paragraph makes the browser silently close the outer one early, so the entry renders outside its own bullet. The tests below pin this.

### 5. The page and its two routes

Per app, two routes and one handler. The shared page logic is the same for every app, so keep it in one place (a shared module, mixin or base class) and let each app supply only its file path, its accent color and its two link builders.

```
GET  <app-root>/changelog                 current month's timeline, plus an Archive section
GET  <app-root>/changelog/<year>/<month>  one past month, with a link back to the current page
```

Behavior:

- **Both routes sit behind the sign-in check.** Signed-out visitors are redirected to sign in and returned afterward.
- **The current month** shows as the timeline. If there are no entries this month, show an empty timeline, not an error.
- **Every past month is an archive link** with its month name and an entry count, such as "July 2026 · 4", linking to its own month page. The `(0, 0)` bucket shows as a non-link "Undated" chip with its count.
- **A month page shows only that month**, with a "Back to Changelog" link, and nothing from other months.
- **An empty or missing file shows "Nothing here yet."** The file for a new app will not exist yet, and that is fine.
- **Name the page's link builders so they do not shadow the framework's own route helpers**, if your framework generates helpers from route names. A wrapper named the same as the helper it calls recurses forever.

Convention: whatever an app or sub-app's own root path is, its changelog lives at that root plus `changelog`. Routing between sub-apps is one file per app, as the project's notes say: ask the project's notes (or the user) which apps exist and which file each uses, rather than guessing.

Add a new accent color the first time a third app needs one. Don't build a general token system speculatively.

### 6. Tests

Don't stop at a working page. The two bugs most likely to bite are both silent, and both are cheap to pin. Write these in the project's own test framework.

**Parser tests**

- Parses several day groups and preserves file order.
- A missing file returns an empty list.
- A file with no day headings returns an empty list.
- Non-bullet lines inside a day are ignored.

**Month grouping tests**

- Day groups are bucketed by year and month, newest month first.
- **The regression that matters most:** a heading the parser can't date (`## Unreleased`) lands in its own `(0, 0)` bucket rather than raising mid-render.

**Page tests.** Let the tests substitute the file path the page reads, so they never touch the project's real changelog files, and write fixture files to a temporary location.

- Signed-out visitors are redirected to sign in.
- Signed-in users see the current month's entry, **and the entry's text sits inside the exact container element the view uses.** That assertion is the regression for nested paragraphs described above.
- Entries from a past month do not appear on the current page; an archive link to that month does.
- A past-month page shows only that month, and includes a link back to the current changelog.

**Per sub-app**, add a much shorter file: signed-out redirect and signed-in render, once per mount (path-prefix and its own host, if both exist). One gotcha if the project uses host-based routes with a cookie-based session: **set the test host before signing in.** A session cookie with no configured cookie domain is host-only, so signing in on the default test host and then switching hosts leaves the cookie behind, and the test reads as an auth bug.

### 7. Point the project's own notes at this habit

Add a short section to wherever the project documents its conventions (its notes file for agents, a contributing guide):

```markdown
## Release notes

The changelog page (and one per sub-app) is a signed-in-only page backed by `docs/changelog/*.md`. At the end of any session that ships something a user would notice, add a dated entry to the relevant app's current file.
```

## The ongoing habit

Once set up, this is the part that matters every session after: before finishing a session where you shipped a feature, redesign or real bug fix, open the relevant `docs/changelog/<app>.md` and add (or extend) today's `## YYYY-MM-DD` section with 1-3 plain-language bullets. Don't log lint, refactor or typo-only work. Don't ask the user first: this is a standing habit, like updating a backlog file.
