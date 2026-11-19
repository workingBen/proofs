# The review page builder

Shared by `design-review`, `article-copy-edit`, `photo-picker`, `style-guide` and
`working-log`. You write the content (a JSON spec plus the HTML for each item); the
builder writes one self-contained HTML page with every mechanic already built and
tested. Do not hand-write the page's JavaScript.

Paths below are relative to a skill's folder (`skills/<name>/`).

```bash
python3 ../../shared/review_page/review_page.py spec.json --out page.html   # build, then check
python3 ../../shared/review_page/review_page.py --smoke page.html          # click through in Chromium
```

Build in a scratch folder, not the repo. Keep `spec.json` beside the page: it is
how you rebuild the next round.

## What every page gets, built in

- Decision buttons per item, one active at a time, all starting unselected, with
  `aria-pressed`. Choices that need a comment open the comment box and focus it; a
  comment typed under any other choice is still kept and exported.
- Variant galleries: clickable cards, the selection marked by a border and a check
  (never a fill), `aria-pressed` on each. The decision acts on the selected variant;
  the first variant is selected until the user picks another (`"selected"` changes that).
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
| `mode` | `review` (default), `questions` or `log` |
| `title` | the page `<title>`; review pages export `[title]` as the first line |
| `header` | override the export's first line (keep it bracketed) |
| `heading`, `intro_html`, `after_html` | top heading, intro, and anything below the items (recap, settled, parked) |
| `css` | your CSS, appended after the chrome: the target site's tokens, fonts, mockup styles |
| `vars` | CSS variables set on `:root`, to retune the chrome's light values. Dark values go in `css` under `@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {…} }` and `:root[data-theme="dark"]`; give every color you change a dark pair, and a filled box its own text color (as `--rp-amber-ink` does), or it goes unreadable in dark mode |
| `head_html` | extra `<head>` markup |
| `assets` | `{"name": "path/to/file.png"}`: embedded once as `--asset-name` on `:root`, and `{{asset:name}}` anywhere in the HTML becomes its `data:` URI |
| `storage_key` | the `localStorage` key, if the default is not stable enough |

Any string value written as `"@file:relative/path.html"` is replaced by that file's
contents, so long item HTML can live in its own files. Fields ending in `_html` are
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

Items go in `sections` (`title`, `intro_html`, `empty_html` shown when the section
has no items, `items`) or a flat `items` list. Item fields:

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

`project`: `name`, `stream`, `round`, `artifact` (the published URL). `format`
defaults to `working-log questions v1.2`. `bar_title_html` sets the sticky bar.

- `questions`: `[{qid, round, ask, why_html, mockups_html, options: [{label, value, note_html, recommended}], notes_label}]`. `value` (the exported text) defaults to `label`; write the full option text.
- `qa`: `[{qaid, check, why_html, notes_label}]`, answered PASS / FAIL / COULDN'T TEST.

The bar carries the tally ("N of M answered · QA x of y") and Clear (with a
confirm). The export is the `[format — answers]` block with project, stream, round,
artifact and a UTC `sent` stamp, one `Q qid (raised rN) | ask` per question with
`-> answer` or `(UNANSWERED)` and its notes, then `--- QA results ---` with
`(NOT CHECKED)` for an untouched check.

### `log` mode

`project`: `name`, `session`, `repo`. `version`, `updated` (or `marker`) fill the
status bar's version marker. `details`: `[[key, value], …]` printed after project,
session and repo in the export. `facts`: `[[label, html], …]`. Make `title` lead
with the session: `SESSION · PROJECT log`.

`entries`, newest first: `[{id, title, status, lede, detail_html, questions: [{q, label, options: [text, …]}]}]`.
Each entry gets a note field and a "Read this" tick; the page ends with an
"Anything else" box. The export is `WORKING LOG — my replies`, the details block,
`exported:` (local time), then `M6  [read]  title` per entry with `answer:` per
option group (`answer (q):` when there are several, `(unanswered)` when empty) and
`note:` lines.

## Checking

The build runs `--check` itself: it extracts the page's script and runs
`node --check`, then confirms the item cards and decision buttons match the spec,
ids are unique, every `{{asset:…}}` resolved, and a log's title leads with the
session. It exits 1 and says why when anything fails.

`--smoke` needs Playwright (`--playwright DIR`, `PROOFS_PLAYWRIGHT`, or one
resolvable from the current folder). It clicks a variant and every decision on the
first item, types a comment, ticks read, copies, reloads to prove persistence,
forces a clipboard failure to prove the fallback, checks every image loaded, and
checks for sideways scroll at 1280 and 390. Without Playwright, open the page in a
browser and do those clicks yourself.

Then look at the page: take a screenshot at a desktop and a phone width (or open it)
and check your own mockups render cleanly. The builder proves the mechanics; only
looking proves the content.
