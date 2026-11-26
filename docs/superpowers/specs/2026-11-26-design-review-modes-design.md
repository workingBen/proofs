# design-review: Refine and Redesign modes (Proofs 1.10.0)

Status: draft for Ben's approval, 2026-11-26.

## Intent

The owner asked design-review to improve a page that already worked: the Host
Headroom dashboard, a data-heavy tool. design-review gave three redesigns
(Careful, Step up, Bold). The owner preferred the original to all three. Even
Careful added padding and lost what made the dashboard readable.

That is not a bug in one run. The skill and its rubric reward change:

- `--smoke` flags an option that is a near-copy of the current page.
- Step up must score higher than Careful, and Bold must rearrange the main blocks.
- Every option must beat the current page on `fold` or `hierarchy` for a vague
  request like "make this nicer".

So a page that should mostly stay as it is can't win. The fix gives
design-review a second mode for that case.

- **Refine** keeps the original page and offers small, separate changes. The
  reader says Yes or No to each one and watches a live preview of the result.
- **Redesign** is today's behavior: Careful, Step up and Bold.

## Goals

1. When the page works and the ask is to improve it, design-review uses Refine
   by default. It says which mode it picked, and the reader can switch.
2. In Refine, the reader sees each change on its own (a cropped before and
   after) and decides Yes or No. One full-page preview at the bottom updates as
   they tap, so what they see before Send is exactly what gets built (Ben's
   pick, `refine-combined`: "Live").
3. Each change is a layer on one exact copy of the current page that can be
   turned on and off (Ben's pick, `refine-build`: "Layers on one copy of your
   page").
4. The critic scores Refine changes on whether they *keep what works*, as well
   as whether they improve the page. There's no near-copy penalty in Refine.
5. The design profile gets a **density** line, so data-heavy tools stay dense in
   both modes.

## Non-goals

- No new skill. Proofs has a freeze on new skills; this is a mode inside
  design-review.
- No new setting unless the build needs one. The change cap below is fixed.
- Redesign's rubric and roles stay as they are, apart from the density line and
  the "offer Refine" fallback below.
- Prerendering every combination of answers. It doubles with each change.

## Anti-goals (failures even if it technically works)

- **A Refine that drifts.** The copy of the page doesn't match the real page, so
  the reader approves changes against a page that isn't theirs. The copy has to
  look identical, checked by measurement, not by eye.
- **Padding creep.** Changes that spread a dense page out. The density line and
  the "keeps what works" score exist to catch this.
- **A preview that lies.** The combined preview shows something the build won't
  match: changes that interact, or a layer that only works in the copy.
- **Changes that are really a redesign.** Moved sections, new hierarchy or new
  copy, sneaked in as "refinements".
- Anything that weakens an existing check (contrast, tap targets, mid-word
  breaks, brand kept, words unchanged).

## Approaches considered

For the live preview, Ben was offered three ways to make each change
switchable:

1. **Layers on one copy of the page (picked).** One exact copy of the current
   page. Each change is a layer: style rules plus, at most, a swap of single
   elements, turned on by an attribute on the copy. The crops and the preview
   all come from the same copy. Limit: no rearranging sections (Redesign's
   job). Two changes to the same spot become one change.
2. **One alternate per section.** Each change rewrites a whole section, and the
   preview stacks the ones the reader picked. That allows bigger changes, but
   only one per section, and every rewrite risks the drift seen on Host Headroom.
3. **Prerender every combination.** Exact, but 2^N renders: 64 for six changes.

For how the combined preview behaves, Ben picked **live** over "a second round
after Send" (an extra trip every review) and over "all changes shown, fixed"
(the reader never sees the exact mix they picked).

## The design

### 1. Choosing the mode

The skill picks the mode in step 1, after reading the request and the capture:

- **Refine** when the page exists, renders, and the capture shows no blocking
  flaw in the sections in scope (sideways scroll, blank content, broken layout),
  *and* the request asks to improve, polish, tidy, tighten or "make it nicer"
  without asking for a new layout.
- **Redesign** when the request says redesign, new layout, rethink or "show me
  something different"; when there is no current page (a new page); or when the
  section in scope is broken.
- A bug-sized fix stays the one-option item it is today, in either mode.

It states the mode in one line in chat and in `intro_html`, for example:
"Refine: your page works, so these are small changes you can take or leave.
Say 'redesign' for full alternatives." The reader switches by saying so, and
the next round uses the other mode. In `claude -p` it states the line and goes
on.

**Fallback:** if every Redesign option misses the bar on beating the current
page, the page says so and offers Refine for the next round. A Refine with no
change that clears its bar says the page already works and lists what it
looked at.

### 2. The copy of the page (the "base")

Refine builds on a **static snapshot of the rendered page** taken from the
running app during the before capture, not a hand-coded mockup:

- The DOM as rendered, with its stylesheets inlined and scripts removed (the
  same approach as this repo's `bin/page-snapshot`). Images and fonts go
  through the builder's `assets`, so each is embedded once.
- It sits in the review page **isolated in both directions**: the review
  chrome's CSS can't restyle it, and its CSS can't restyle the chrome. The
  mechanism is the builder's call (shadow DOM is the expected fit, because the
  page script can reach it to toggle layers and `--smoke` can measure inside
  it). It has to work inside a published artifact and in a `file://` page.
- **Fidelity check:** `--smoke` screenshots the base with every layer off at
  1280 and 390 and compares it with the before capture. A base that doesn't
  match is a problem line, and the review isn't published on it. The measure
  and its threshold are the builder's call; the PR says what they are and why.
- Scope: the whole page or the sections in scope, whichever the request names.
  A long page is cropped to the sections in scope plus their neighbors, so the
  page stays well under the 16 MB artifact limit.

### 3. A change (a "layer")

Each change is one entry in the item's new `changes` list:

- `id`, `label` (plain words, such as "Bolder totals"), `why_html` (one or two
  sentences: what it fixes and why), and `targets` (the selectors it touches).
- `css`: rules that apply only while the change is on. The builder scopes them
  under the base's on-attribute, so a change can't leak when it is off.
- Optional `swaps`: replace a single element's markup while the change is on.
  This is for small things like an icon, a badge or a control style. Never a
  section, and never new words.
- `inventory` is unnecessary: a layer can't remove an element without saying
  so, so a swap or `display:none` on a captured element must carry a `removes`
  line with a reason, shown on the card.

What a change may do: spacing, size, weight, alignment, color from the site's
own palette (or the profile's Love references), borders and rules, small swaps
of single elements. What it may not do: reorder or regroup sections, change or
add words, touch the brand, or add padding to a page whose profile says
`dense` unless that is the change's stated purpose and the reader can see it.

**Overlap:** `--smoke` turns each change on alone, records which elements'
computed styles change, and flags two changes that change the same property
on the same element. The designer merges them into one change, or makes them
touch different things. Every change on alone and all changes on together are
measured with the full set of design checks (contrast, tap targets, mid-word
breaks, sideways scroll, line length, edges). There's no near-copy check in
Refine.

**How many:** 3 to 8 changes per page. Fewer is fine when that's all the page
needs. More than 8 is a sign the page wants a Redesign.

### 4. The Refine review page

From the top:

1. The mode line and the request.
2. **One card per change:** label, `why_html`, and a cropped before and after
   at 1280 and 390. The crops are rendered from the base with that one layer
   off and on, cut to the union of its targets plus a margin. Then the
   critic's scores, the Recommended or Not Recommended badge, the buttons
   **Yes** / **No** / **Revise** (Revise needs a comment), and an optional
   comment box.
3. **The combined preview:** the base with every Yes layer on, in a desktop
   frame (1280, scaled to fit the column) and a phone frame (390). It updates
   the moment a card's answer changes. A small toggle flips the preview
   between "with your picks" and "original", the same toggle Ben used in the
   blind rating.
4. The sticky bar as on every review page: tally, Copy, Send to Claude, and
   answers saved to the page's database.

Undecided cards start **off** in the preview. Recommended cards are not
pre-turned-on, so the preview shows only what the reader chose.

The export, under the page's bracketed title, adds one line per change and a
summary line, for example:

```
[Host Headroom dashboard — Design Review (Refine)]
1. Bolder totals — YES
2. Tighter row spacing — NO
3. Status color on the alert column — REVISE — COMMENT: amber, not red
Combined: 1
```

A new decisions preset, `refine`, gives these buttons and this export. The
existing presets don't change.

### 5. The critic in Refine

The critic (same helper rules as today: fresh context, shots and inventory
only, no designer reasoning) scores each change and then the combination:

- **Each change**, from its crops at both widths:
  - `gain`: how much it improves what it says it fixes (1 to 5).
  - `keeps`: whether it keeps what already works: density, grouping,
    readability, every element and every word, brand untouched (1 to 5).
    Padding added to a dense page, a lost element, or a weaker read scores 2
    or below.
  - The bar: `gain` 3 or more, `keeps` 4 or more, and no failed design check.
    A change below the bar is revised once per correction pass or dropped,
    with the reason on the page.
- **The recommended set** (every change it recommends, on together) scores on
  the six existing criteria against the current page's `before_scores`. It
  must be no worse on any criterion and better on at least one. If it isn't,
  the critic says which change caused it, and that change loses its
  recommendation.
- There's no near-copy penalty, and no "must beat the current page" rule for
  each change on its own: a change only has to help without hurting.

`reference/design-rubric.md` gets a Refine section with anchors for `gain`
and `keeps`, written the same way as the existing criteria.

### 6. The density line in the design profile

`reference/design-profile.md` gets a fifth short heading or a line under Rules:

```
Density: dense. Many numbers on one screen; people scan, not read. Don't add padding.
```

Its value is `dense`, `balanced` or `airy`, with one line saying why. Both
modes read it. The critic uses it in `grouping`, `fit` and Refine's `keeps`.
With no profile, the designer infers density from the page (a table- or
number-heavy page counts as dense) and says so in one line. Creating a profile
asks the density question on the first questions page, next to Audience.

### 7. Applying the picks

Only changes marked YES are built into the real templates and CSS, translated
the way design-review applies a picked variant today (real classes, the
site's tokens, no pasted snapshot markup). REVISE goes to a follow-up round
scoped to those changes, on the same base. Everything in step 5 of the skill
(build, type check, capture with `--compare`, every breakpoint) applies
unchanged.

### 8. Redesign mode

Unchanged, apart from three things:
- it reads the density line;
- it falls back to offering Refine when no option clears the bar;
- the skill text names it "Redesign mode", so the two modes are easy to tell
  apart.

## Constraints

- Works in an interactive session and in `claude -p`, with the house rules:
  one command per Bash call, stay in the project and plugin folders, and no
  ad hoc tools.
- Phone first: Ben reviews from an iPhone. Crops and the combined preview
  must read at 390 without the page scrolling sideways.
- American English. Every existing check keeps its strength ("No setting can
  weaken a check").
- Results first, within the spend cap setting.
- Tests in the existing suites (root, and the review page tests); the gate is
  the same as for 1.9.0. Version 1.10.0.

## How we'll know it works

1. **Rerun the Host Headroom dashboard request in Refine.** Ben compares the
   original with the combined result of his own picks, using the toggle, and
   rates it Less, Equal or More. Pass: More, with no change he accepted that
   he later wants back out.
2. **One page from the designer bench** (piw-handoff/bench) in Refine, rated
   the same way, so the result isn't one page's luck.
3. **A redesign request on a broken bench page** still gets Redesign, to show
   the mode choice works both ways.

## Left to the builder

- How the base is isolated (shadow DOM expected), how the snapshot is taken
  (inside the capture, or as a sibling script), and how its fidelity is
  measured, with thresholds and reasons in the PR.
- How crops are rendered (Playwright on the built review page is the obvious
  route) and the crop margin.
- How overlap between changes is detected, and the exact `--smoke` lines.
- The spec field names beyond `changes`, `css`, `swaps`, `targets`, `removes`
  and the `refine` preset, as long as `reference/review-page.md` documents
  them.
- How the desktop frame scales on a phone.
