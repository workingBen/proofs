# The review page builder

Shared by `design-review`, `article-copy-edit`, `photo-picker`, `style-guide`,
`working-log`, `questions` and `qa-checklist`. You write the content (a JSON spec plus the HTML for each item); the
builder writes one self-contained HTML page with every mechanic already built and
tested. Do not hand-write the page's JavaScript.

```bash
python3 <plugin root>/shared/review_page/review_page.py .proofs/<name>.json --out .proofs/pages/<name>.html
python3 <plugin root>/shared/review_page/review_page.py --smoke .proofs/pages/<name>.html
```

The first builds the page and checks it; the second clicks through it in Chromium.

Use the absolute plugin root your skill showed you, unquoted, so the allow rule matches. Write the spec with your file tool; do not write a script to generate it, since every new script is one more approval.

Keep the spec under `.proofs/` and always give `--out .proofs/pages/<name>.html`:
`.proofs/` stays out of git, and `.proofs/pages/` is the only folder the optional
`open` allow rule covers, so a page saved anywhere else is not opened. A session or
log spec built with no `--out` goes to `.proofs/pages/<spec name>.html`. Keep the
spec: it is how you rebuild the next round.

## What every page gets, built in

- A header naming the page: the **proofs** wordmark, a pill with the skill's name,
  and the project and session (`project.name`, `project.session`, session accented).
  It starts the top bar on session, log and questions pages and adds no height; a
  review page, which has no top bar, gets it as a slim line above the heading. On a
  phone the wordmark drops and the pill stays. Screen readers hear "Proofs, design-review".
  A review or questions page with no `project.session` still builds, with a warning:
  the session is how the reader matches a page to the chat it belongs to.
  It also warns about British spellings in what the reader sees (`behaviour` → `behavior`); it is off unless the project sets `PROOFS_SPELLING` to `american` in the `env` block of its `.claude/settings.json` (not as a prefix in front of the command, which would stop the command matching its allow rule). <!-- british-ok: behaviour -->
- Decision buttons per item, one active at a time, all starting unselected, with
  `aria-pressed`. Choices that need a comment open the comment box and focus it; a
  comment typed under any other choice is still kept and exported.
- Variant galleries: clickable cards, the selection marked by a border and a check
  (never a fill), `aria-pressed` on each. The decision acts on the selected variant;
  until the user picks another, the spec's `"selected"` variant is selected, else the one marked
  `"recommended"`, else the first (a `"selected"` that names no variant is a spec error).
- Optional "Mark as read" switch (`READ` in the export), legend, category filter
  tabs with a live open count, and a light/dark preview switch for examples.
- A sticky bar: "X of N reviewed", a tally per decision, and the copy button.
- Copy: `navigator.clipboard.writeText`; if it is missing or fails, a selectable
  text box opens with the text selected. "Copied" shows only on success.
- `localStorage` persistence on every change, keyed per page (`storage_key`, else
  derived from the project, session or stream, and title). Wrapped so a blocked
  storage never breaks the page.
- Light and dark chrome from tokens on `:root` (questions mode: its single dark
  world). Every semantic color, including the amber revision box, has a dark pair.

## The spec

Common fields:

| Field | Meaning |
|---|---|
| `mode` | `review` (default), `questions`, `session` or `log` |
| `title` | the page `<title>`; review pages export `[title]` as the first line |
| `header` | override the export's first line (keep it bracketed) |
| `heading`, `intro_html`, `after_html` | top heading, intro, and anything below the items (recap, settled, parked) |
| `css` | your CSS, appended after the chrome: the target site's tokens, fonts, mockup styles. Fonts come the way the target page gets them: its own font `<link>` copied into `head_html`, or project font files in `assets` (`@font-face{src:url({{asset:name}}) format('woff2')}`); never downloaded, and never base64 pasted into the spec. End each `font-family` with a fallback stack and a generic family; the builder warns when one does not |
| `vars` | CSS variables set on `:root`, to retune the chrome's light values. Dark values go in `css` under `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {…} }` and `:root[data-theme="dark"]`; give every color you change a dark pair, and a filled box its own text color (as `--rp-amber-ink` does), or it goes unreadable in dark mode |
| `head_html` | extra `<head>` markup |
| `assets` | `{"name": "path/to/file.png"}`: the builder reads the files, so their bytes never pass through your context. Use one as `{{asset:name}}` (in an attribute, or in `css` as `url({{asset:name}})`) or as `var(--asset-name)`; each is embedded **once** however often it is used. PNG and JPEG become WebP when `magick` or `cwebp` is installed: the smaller of lossy (at `image_quality`) and lossless, or the original if that is smaller still (without either tool they are kept, and the build says so). Older Safari (before iOS 14) cannot show WebP, so a converted image also carries a **fallback**: the smallest of a JPEG at `image_quality`, a PNG shrunk to `image_max_width`, or the original (a PNG with transparency never becomes a JPEG; without `magick` the fallback is the original). An `<img src="{{asset:name}}">` becomes `<picture class="rp-pic"><source type="image/webp" srcset="…"><img src="fallback" …></picture>`, keeping every attribute on the `<img>` (`picture.rp-pic` is `display:contents`, but style the `<img>` by class, not with a `>` child selector). CSS uses (`url(…)`, `var(--asset-name)`) get the fallback, since CSS has no per-format fallback that older Safari reads. One HTML use is inlined and needs no JavaScript; repeated uses are filled in at load from one JSON map (`#rp-assets`) |
| `image_quality`, `image_max_width` | WebP quality (1–100, default 70) and the widest a screenshot may be, in pixels (default 1600): applied only when the shrunk file is actually smaller, and never upscales. Env vars `PROOFS_IMAGE_QUALITY` and `PROOFS_IMAGE_MAX_WIDTH` win over the spec |
| `storage_key` | the `localStorage` key, if the default is not stable enough |
| `project` | `{name, session, repo}` for the header, on every mode; take the session name the way the `working-log` skill does. Questions pages also use `stream`, `round`, `artifact` |
| `skill` | the skill named in the header's pill. Defaults: session and log pages `working-log`; questions pages `qa-checklist` when they hold only checks, else `questions`; review pages from the decisions preset (`design-review`, `copy-edit` → `article-copy-edit`, `style-guide`, `photo-picker`), and no pill for a custom set with no preset. `""` shows the wordmark alone |

### Frame and sections

A page is a **frame** around a list of **sections**. The frame is `mode`: it sets
the chrome, the tally and the export's header. Each section has a `kind` and
contributes its own block to the export, in page order:

| `kind` | Items | Export block |
|---|---|---|
| `review` | decision items (below) | one `N. label — DECISION…` line per item |
| `questions` | questions with radio options | `Q qid (raised rN) \| ask` blocks |
| `qa` | PASS / FAIL / COULDN'T TEST checks | `--- QA results ---` then `QA qaid \| check` blocks |
| `log` | log entries | `M6  [read]  Nov 19 - 3:54PM  title` lines (the time only when the entry has `when`) with answers and notes |
| `links` | `{label, status, url, link_text, state}`: other pages waiting on the reader, one line each. `state` is `open` (default: the status and an **Open it** link) or `in-progress` (the reader has answered and you are working: a muted *In progress* pill and a small **View page** link, listed after the open ones; when every link is in progress the heading becomes "Pages Claude is working on"). A `url` starting with `#` points into this page (`#questions`, `#checks`, `#log`, or a log entry id such as `#L12`): it opens in place and reads "Open questions above", "Open checks above" or "See it in the log below" | none |
| `decided` | `{id, title, decision, when}`: settled items, folded (`"open": true` unfolds) | none |

Every section takes `id` (default `s1`, `s2`, …), `kind` (default: the mode's own
kind), `title`, `intro_html`, `items`, and a `review` section its own `decisions`
(default: the page's). Ids of items must be unique across the whole page. Kinds
can be mixed on one page. The flat shorthands below (`items`, `questions`, `links`,
`qa`, `entries`, `decided`) are the same thing with one section per kind.

**Open questions come first.** On `questions` and `session` pages the builder puts
the sections that need the reader (`questions`, then `links`, then `qa`) directly
under the sticky bar, and moves `heading`, `intro_html` and `facts` below them; a
`questions` page also moves its questions sections ahead of any others. `links` and
`decided` sections, and any empty section on a session page, are not shown.

Any string value written as `"@file:relative/path.html"` is replaced by that file's
contents, so long item HTML can live in its own files. Like an asset path, it is
looked up next to the spec first, then in the working directory; the error names both. Fields ending in `_html` are
inserted as written; every other text field is escaped.

### `review` mode

`decisions` is a preset name, or an object `{"preset": "...", ...overrides}`:

| Preset | Buttons → export |
|---|---|
| `copy-edit` | Keep Original → `DENY (Keep Original)`, Use Edit → `ACCEPT (Use Edit)`, Approve with Comment → `ACCEPT WITH COMMENT`, Request Revision → `REVISE`; undecided → `PENDING` |
| `design-review` | Keep Original → `DENY`; Use Proposed → `ACCEPT (Use Proposed)`, or with variants Use Selected → `ACCEPT (Use Selected: Variant B)`; `ACCEPT WITH COMMENT` (with variants `ACCEPT WITH COMMENT (Use Selected: Variant B)`); `REVISE`; `PENDING`; Mark as read on |
| `photo-picker` | Keep None → `DENY (Keep None)`, Use Selected → `ACCEPT (Use Selected: Option B, trail map)`, `ACCEPT WITH COMMENT (Use Selected: …)`, `REVISE`; `PENDING` |
| `style-guide` | Deny → `DENY`, or `DENY (Works as Designed)` with its checkbox; Request Revision → `REVISE`; `ACCEPT (Apply Everywhere Now)`; `ACCEPT (Record for Later)` (with variants `… : Option B)`); comment box always open; legend on; undecided items left out of the export |

Override keys: `buttons` (each `state`, `label`, `label_variant`, `export`,
`export_variant` with `{sel}`, `comment`: `required` or `optional`, `meaning`),
`pending` (`null` leaves undecided items out), `mark_read`, `comment_always`,
`works_as_designed`, `legend`, `variant_word`.

Export line: `N. label — DECISION[ — READ][ — COMMENT: text]`, the comment on one
line, no comment suffix when the box is empty.

Items go in `review` sections (`empty_html` is shown when one has no items) or a
flat `items` list. Item fields:

| Field | Meaning |
|---|---|
| `label` | required; shown and exported |
| `id`, `num` | default to the running number across sections |
| `location` | a small label after the title (file and line, route) |
| `recommended` | `true` / `false` badge; omit for none |
| `category` | chip, filter tab (`"filters": true`), color (`category_colors` to set) |
| `body_html` | what is being judged: before/after panes, screenshot, recipe |
| `variants` | `[{html, name, note_html, recommended, key, label}]`; `key` defaults to A, B, C and `label` to "Variant A" or "Option A" |
| `history_html` | earlier rounds, shown dimmed above the body |
| `reason_html` | the Reason block |

Page switches: `filters`, `preview_toggle` (examples get `[data-preview="dark"]` on
`.rp-main`; write the dark values in your `css`), `copy_label`.

Helper classes for item HTML: `.rp-panes` (side-by-side panes that stack on a phone),
`.rp-pane` and `.rp-pane-label`, `.rp-scroll` (sideways scroll inside, never the
page), `.rp-shot` (a screenshot), and `<del>` / `<ins>` inside `.rp-panes` for
word-level diffs.

### `questions` mode

A standalone questions page (the `questions` skill) or checklist (the `qa-checklist`
skill). `project`: `name`, `session`, `stream`, `round`, `artifact` (the published URL).
`format` defaults to `questions v1.3`, or `qa-checklist v1.0` on a page with checks
and no questions, whose export says `results` instead of `answers`.
`bar_title_html` sets the sticky bar's title (default `project.name`); the session follows it.

`questions` and `qa` sections, or the flat `questions` and `qa` lists:

- `questions`: `[{qid, round, ask, why_html, mockups_html, options: [{label, value, note_html, recommended}], notes_label}]`. `value` (the exported text) defaults to `label`; write the full option text.
- `qa`: `[{qaid, check, why_html, notes_label}]`, answered PASS / FAIL / COULDN'T TEST.

The bar carries the tally ("N of M answered · QA x of y") and Clear (with a
confirm). The export is the `[format — answers]` (or `— results]`) block with project, stream, round,
artifact and a UTC `sent` stamp, one `Q qid (raised rN) | ask` per question with
`-> answer` or `(UNANSWERED)` and its notes, then `--- QA results ---` with
`(NOT CHECKED)` for an untouched check.

### `session` mode

Working-log's session page: one URL per session. `project`: `name`, `session`,
`repo`, `round` (default for questions), `artifact`. `version`, `updated`, `details`,
`facts`, `heading`, `intro_html` as in `log` mode. Content: `questions`, `links`,
`qa`, `entries`, `decided` (or `sections` of those kinds).

The page always shows them in this order, whatever order the spec uses, each only
when it has items: **Waiting on you** (questions, then links titled "Other pages
waiting on you"), **Checks for you** (qa), the heading, intro and facts, **Log**,
**Decided**. A section's `title` overrides those names. Question and check cards take
the page's light and dark tokens. A `review` section is refused (design reviews stay
their own page; link them), and so is a log entry with option groups (questions go
in `questions`).

The status bar tallies all of it ("1 of 2 answered · checks 0 of 1 · 3 / 5 read").
The export is `WORKING LOG — my replies`, project, session, repo, `artifact:` when
set, the details, `exported:` (local time), then a block per section with content:
`--- Questions ---` with the `Q` blocks, `--- QA results ---` with the `QA` blocks,
`--- Log ---` with the entry lines, and `anything else:`.
`examples/session.json` is a working spec.

### `log` mode

A log-only page, kept for pages made before the session page.

`project`: `name`, `session`, `repo`. `version`, `updated` (or `marker`) fill the
status bar's version marker. `details`: `[[key, value], …]` printed after project,
session and repo in the export. `facts`: `[[label, html], …]`. Make `title` lead
with the session: `SESSION · PROJECT log`.

A `log` section, or the flat `entries` list, newest first: `[{id, title, status, when, lede, detail_html, questions: [{q, label, options: [text, …]}]}]`. `when` is the author's local time as ISO 8601 (`2026-11-19T15:54`), shown after the title and in the export as `Nov 19 - 3:54PM`; it is reformatted, never converted between time zones. Read entries keep it on their one-line row, except on phones.
Each entry gets a note field and a "Read this" tick (a ticked entry folds to one line under "Read" at the bottom of the log); the page ends with an
"Anything else" box. The export is `WORKING LOG — my replies`, the details block,
`exported:` (local time), then `M6  [read]  title` per entry with `answer:` per
option group (`answer (q):` when there are several, `(unanswered)` when empty) and
`note:` lines.

## Checking

The build runs `--check` itself: it extracts the page's script and runs
`node --check`, then confirms the item cards and decision buttons match the spec,
ids are unique, every `{{asset:…}}` resolved, every `<picture>` ends in a PNG or JPEG `<img>`
and every shared image has something to fill it from, a log or session page's title leads
with the session, open questions are the first thing in the page's main column, and a
session page's sections are in order. It exits 1 and says why when anything fails.

The build also prints how many screenshots became WebP and how much smaller they got, and how big their fallbacks are, and **warns (without failing) when the page passes 3 MB**, naming the largest assets. Large pages load slowly on a phone and can hit a viewer's size limit; lower `image_quality`, set `image_max_width`, or split the review.

`--smoke` needs Playwright (`--playwright DIR`, `PROOFS_PLAYWRIGHT`,
`~/.cache/proofs-playwright`, or one resolvable from the current folder). It uses the
bundled browser if there is one and otherwise your installed Google Chrome, and it
downloads no browser. One-line install:
`npm install --prefix ~/.cache/proofs-playwright playwright@1.61.1`.
Every skill that builds a page says the same thing:
Run `--smoke`. If it reports Playwright missing, run the one-line install it prints (it uses your installed Google Chrome and downloads no browser), then run `--smoke` again; if it still cannot run, say on the page and in chat that the self-check did not run.
The install is an `npm install`, so it may ask permission once; that is expected.
The smoke check clicks a variant and every decision on the
first item (or answers the first question and check, and ticks the first entry),
types a comment, ticks read, confirms open questions sit directly under the sticky
bar, copies, reloads to prove persistence,
forces a clipboard failure to prove the fallback, checks every image loaded (shared images included, none left
blank) and every `<picture>` has a PNG or JPEG `<img>` fallback, and
checks for sideways scroll at 1280 and 390. A headless 390 px viewport renders correctly;
the smoke check measures sideways scroll at 390 itself.

Then look at the page: take a screenshot at a desktop and a phone width (or open it)
and check your own mockups render cleanly. The builder proves the mechanics; only
looking proves the content.
