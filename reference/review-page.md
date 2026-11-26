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
- On a published claude.ai artifact with the `db` capability, every answer is also
  saved in the artifact's own database, so you can read it without a Copy and paste
  (see "Answers without Copy" below). Without it the page works exactly as before.
- A sync indicator in the sticky bar (the bottom bar on a review page): **Saved**,
  **Saving…** or **Not saved yet**, a small icon plus the word, read out politely to
  screen readers. It shows only once the page's database answers, so a local file or a
  page published without `db` shows nothing and never a false "Saved".
- A **Send to Claude** button beside Copy, which wakes the session that published the
  page (see "Send to Claude" below). It shows only once the page's `comments`
  capability answers, so a local file or a page published without it shows Copy alone.
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
| `image_quality`, `image_max_width` | WebP quality (1–100, default 70) and the widest a screenshot may be, in pixels (default 1600): applied only when the shrunk file is actually smaller, and never upscales. The settings `PROOFS_IMAGE_QUALITY` and `PROOFS_IMAGE_MAX_WIDTH` (a settings file or the environment) win over the spec |
| `send_wait_ms` | Milliseconds the page waits after Send to Claude before saying "Not picked up yet". Default: the `PROOFS_SEND_WAIT_MIN` setting (5 minutes) |
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
| `stack_variants` | `true` puts one variant per row (about 1,050 px wide at a 1280 px window instead of about 500 beside a sibling), for a desktop mockup. `--smoke` prints every mockup box's width as `mockup_widths` |
| variant `role` | `careful`, `step-up` or `bold`: shown as "Careful", "Step up", "Bold" in the variant head. Unknown value is a spec error |
| variant `inventory` | `[{element, status, reason}]`, `status` is `kept`, `moved` or `removed`; a compact table under the mockup, removed rows in the deny color. `element` matches a captured element of `before_sections` by its text (its kind when it has none), ignoring case and extra spaces; a captured element with no row shows "removed — no reason given". Optional `brand`: `true` on a row for a logo, wordmark, company or product name, brand color or tagline shows a small "Brand" tag after the element (in the deny color when the row is removed); anything but `true` or `false` is a spec error |
| variant `scores` | `{hierarchy, action, fold, grouping, fit, care}`, each a whole number 1 to 5, one line under the mockup. In an item where any variant is scored, an unscored one says "Not scored", and recommending (or `selected`) an unscored variant is a spec error |
| `before_sections` | the current page's section this item changes: **one** section object from the before capture's `measures.json` (`label`, `top`, `left`, `width`, `height` and an `elements` list; `layout` when the capture has it). Better, name it and the builder reads it: `{"from": ".proofs/capture/before/measures.json", "page": "home", "width": 1280, "label": "Hero"}` (`"state"` defaults to `default`; `from` is relative to the spec's folder, then the working directory). Drives the inventory's "removed — no reason given" rows and `--smoke`'s near-copy check against the page. A list, a string, an object without an `elements` list, or a label the file does not have (the error lists the labels it has) is a spec error |
| `before_font_sizes` | the page's own type scale: a list of numbers, measures.json's `fontSizes`, or `{"from": …, "page": …, "width": 1280}` to read it from the file. `--smoke` notes each mockup text size more than 1 px from all of them. Anything but a list of numbers is a spec error |
| `before_scores` | the critic's scores for the current page, the baseline every option must beat (`design-rubric.md`): same keys and 1 to 5 checks as `scores`, errors naming "current page". Shown once per item above its options as a row labeled "Current page"; none, no row |
| `judged_by` | `helper` ("Judged by a separate helper") or `self` ("Checked by the designer itself"); none, no line |
| `inventory`, `scores` on an item with no `variants` | the single proposal's inventory and scores, validated and shown the same way; no `role` needed. Its score row shows only when it has `scores` or `judged_by` ("Not scored" when only `judged_by`), so copy-edit and capture items show none |
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

- `questions`: `[{qid, round, ask, why_html, mockups_html, options: [{label, value, note_html, recommended}], notes_label}]`. `value` (the exported text) defaults to `label`; write the full option text. A question with `options: []` shows only its text box: what the reader types is the answer (it counts in the tally, marks the card answered, and exports as `-> <text>`).
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

## Answers without Copy: the page's database

On a published claude.ai artifact, the page saves every answer, note and read tick in
the artifact's own small database. You read them there yourself, so the reader does
not have to copy and paste. Copy my replies still works exactly as before and stays
the fallback.

**Publish with the `db` and `comments` capabilities.** On the first publish, pass
`capabilities: {"db": {}, "comments": {}}` to the `Artifact` tool (the build prints
this line). A republish to the same file path (or `url`) that leaves `capabilities`
out keeps them; never pass `capabilities: {}`, which removes them. A non-empty object
replaces the stored set, so the first publish that adds `comments` to an older page
must name `db` too. Nothing else is needed: no access rules and no `user` capability.
A page built before Proofs 1.6.8 has no database code, and one built before 1.8.0 has
no Send to Claude button; rebuild it.

**What the page saves.** One document per card in the collection `proofs-answers`,
read back when the page opens, so a second device shows the same answers. Opening the
page writes nothing. Typing is saved about 0.8 s after the reader pauses
(`DB_DEBOUNCE_MS`); a tap (an option, a decision, a variant, a read tick) is saved at
once; and leaving a text box, switching apps or leaving the page (`blur`,
`visibilitychange`, `pagehide`) sends whatever is still waiting. The document id is `<section id>.<item id>` (`s1.filter-placement`);
characters other than letters, digits and `_ - . ~ : @ +` become `_`, plus a short hash.

| Field | Meaning |
|---|---|
| `id`, `section` | the card's id (`qid`, `qaid`, entry id or review item id) and its section's id |
| `kind` | `question`, `qa`, `log`, `review`, or `extra` (the "Anything else" box: document `_page.extra`) |
| `answer` | question: the option's `value`, the typed text on a text-box-only question, or `null`; qa: `PASS`, `FAIL`, `COULDN'T TEST` or `null`; log: `{group: option}`; review: the decision state (`accept`, `deny`, ...) or `null` |
| `note` | the typed text: a note or a review comment. A text-box-only question (`options: []`) stores what was typed in `answer` instead; rows written before 1.6.9 carry it in `note`, and the page and `--answers` still read them |
| `read` | the read tick (log entries, review items) |
| `variant`, `works_as_designed` | review items only: the picked variant key, and the deny checkbox |
| `updated_at` | when the reader's browser wrote it (ISO 8601, UTC) |
| `page_version`, `page` | which build of the page (the spec's `version`, else a hash of it) and its storage key |

A cleared answer is written as a document with `answer: null` and an empty `note`,
not deleted. Rows outlive republishes: a card kept on the next version keeps its
answer, so reuse an id only for the same question. A card you drop stays in the
database, but the page and `--answers` ignore it.

**Read the answers.** Read the database first, and a pasted Copy export second:

1. `ArtifactData` with `action: "list"`, `url: <the page's URL>`,
   `collection: "proofs-answers"`, `out_dir: ".proofs/answers/<name>"` (each document
   is saved as `<out_dir>/proofs-answers/<id>.json`). A page with more than 100 cards:
   add `query: {"limit": 1000}`.
2. `python3 <plugin root>/shared/review_page/review_page.py --answers .proofs/pages/<name>.html --rows .proofs/answers/<name>`
   prints them as the same text the page's Copy button makes, from the page's own
   engine, so you handle both the same way. Its `sent:` (or `exported:`) line is the
   newest `updated_at`.
3. An empty list means nobody has answered on the published page yet (or they are
   on an older build): ask for the Copy export as before.

**When both arrive and differ**, compare card by card: the newer wins (`updated_at`
for a row, the export's `sent:` / `exported:` stamp for a paste), and say in chat which
one you used and why.

**The sync indicator.** **Saved**: every change is in the store. **Saving…**: a write
is out, or typing is waiting out the 0.8 s pause. **Not saved yet**: a change has not
reached the store; the page keeps retrying with backoff (1 s, doubling, up to 30 s,
and at once when the device comes back online), and Copy stays the way out. On a phone
the bar stays one line: Saved and Saving… show the icon alone (the word is still read
out), and Not saved takes the tally's place until it lands. A change the page never got
to send (the tab closed mid-write) is kept in `localStorage`; on the next load the
indicator says Not saved yet and the page pushes it, unless the stored row is newer.

**When the page cannot save** (a local file, `wifi` mode, an older viewer, a signed-out
viewer, or a viewer who may not write), it keeps working from `localStorage` and Copy
alone, and never blocks or breaks Copy. A refused write stops the saving and leaves the
indicator at Not saved yet. The page's `<body>` carries `data-answers-db`: `on`,
`off`, `unreachable` (no answer in 10 s) or `error`.

**Privacy.** Anyone the page is shared with at Contributor level or above can write
answers, and anyone who can open it can read them. Pages are private by default; share
one only with the people who should answer it, and never ask for a password, key or
other secret on one.

## Send to Claude

A database write starts no turn, so answers saved on the page used to sit unread until
the reader pasted the Copy export anyway. **Send to Claude**, beside Copy in the bar,
posts a short comment with the `comments` capability's `sendToClaude`, which wakes the
session that published the page. Copy stays the fallback.

**When it is on.** The button is enabled only while `canSendToClaude()` answers
`available`, checked when the page opens and again whenever it is shown (switching
back to the tab or app). Otherwise it stays visible but off, with one line under the
bar saying why:

| `canSendToClaude()` | The line |
|---|---|
| `no_session` | This page's Claude session isn't listening; use Copy |
| `writers_only` | Only editors can send; use Copy |
| `off`, anything else | Not available here; use Copy |

**What a tap does.** It saves first: pending answers are sent to the database at once
and the send waits (up to 5 s) for the bar to say **Saved**. If they do not land, it
sends nothing and says "Nothing was sent: your answers are not saved on the page yet.
Use Copy." Then it calls `sendToClaude({anchor, text})`, anchored on the button, where
`text` (under 4 KiB) is a pointer to the rows, not the export:
`<session> page <version>: answered <ids> (<n> of <total>). Read proofs-answers on this artifact.`,
plus `Anything else: <the box>` when it is filled (cut to fit; the database holds
everything). **Sent** shows only after the promise resolves, and nothing ever retries
by itself.

| Result | The line | The button |
|---|---|---|
| sent | Sent. This page updates when Claude has read your answers (usually under a minute). The reply is also in the comments. | on |
| `consent_required` | Not sent. Allow commenting when asked, then tap again. | on |
| `claude_unavailable` | Nothing was sent; use Copy. | rechecked |
| `rate_limited` | Not sent: too many sends just now. Wait a minute, then tap again. | off for a minute |
| `forbidden`, `not_granted`, `capability_*` | Not sent: this view can't send to Claude. Use Copy. | off |
| anything else | Not sent (`code`). Tap again, or use Copy. | on |

**Closing the loop.** The `comments` capability is write-only: the page cannot read
the reply in the thread. So the confirmation is a republish. After a send the page
keeps `{sentAt, fromVersion}` in `localStorage` (under `<storage key>:sent`). On the
next load, a page whose version differs says, in green, "Claude picked up your answers
(sent 9:01 PM, now v14)" and forgets the send; the same version more than 5 minutes
later says "Not picked up yet. The session may be busy or closed; Copy still works."

### Sent to Claude: what the session does

The send arrives as a `<task-notification>` of type `artifact-auto-react` naming the
artifact and the thread, after the harness has already posted an automatic reply.

1. **Republish the page first, before any other work.** Read the rows (`ArtifactData`
   `list` of `proofs-answers`, then `review_page.py --answers`), apply them exactly as a
   paste (answered questions to Decided, a log entry "Got your answers"), and republish
   to the same file path. Open views reload by themselves; that is what the reader sees.
2. **Never post a second reply** in the thread.
3. Do the work, then resolve the thread with `ArtifactComments`.

**Limits.** It works only while the publishing session is open and its watch on the
page is armed (every publish arms it). After `/clear`, a closed terminal or a new
session, the button reports `no_session` and Copy is the way; a new session re-arms it
by watching the URL the user gives it. Editors only: a reviewer the page is shared with
uses Copy. The automatic reply is posted by the harness, not by the page or the
session.

## Checking

The build runs `--check` itself: it extracts the page's script and runs
`node --check`, then confirms the item cards and decision buttons match the spec,
ids are unique, every `{{asset:…}}` resolved, every `<picture>` ends in a PNG or JPEG `<img>`
and every shared image has something to fill it from, a log or session page's title leads
with the session, open questions are the first thing in the page's main column, and a
session page's sections are in order. It exits 1 and says why when anything fails.

The build also prints how many screenshots became WebP and how much smaller they got, and how big their fallbacks are, and **warns (without failing) when the page passes 3 MB** (the `PROOFS_PAGE_WARN_MB` setting), naming the largest assets. Large pages load slowly on a phone and can hit a viewer's size limit; lower `image_quality`, set `image_max_width`, or split the review.

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
bar as the page opens, checks the sync indicator stays hidden with no database, copies, reloads to prove persistence,
forces a clipboard failure to prove the fallback, checks every image loaded (shared images included, none left
blank) and every `<picture>` has a PNG or JPEG `<img>` fallback, and
checks for sideways scroll at 1280 and 390. On a review page it also flags any word a mockup
breaks mid-word ("authenticat|ion"), naming the item and variant, the same measure
visual-qa's capture uses. On a design-review page only, it also measures every option
(and a one-option item's `.rp-mockup`) for contrast (any CSS color, oklch included; text
faded by `opacity` is composited), tap targets, line length, left edges and off-scale
type, and compares options for near-copies; what it cannot measure goes in `notes`, as
does a one-option item with no `.rp-mockup` and a one-option fix that keeps the page's
layout (expected, not a failure). Other kinds of page get none of these design checks:
a style guide's examples are deliberately small or low in contrast. A headless 390 px viewport renders correctly;
the smoke check measures sideways scroll at 390 itself.

Then look at the page: take a screenshot at a desktop and a phone width (or open it)
and check your own mockups render cleanly. The builder proves the mechanics; only
looking proves the content.
