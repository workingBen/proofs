# A better designer inside design-review

Status: draft for the maintainer's approval, 2026-11-24. Nothing here is built yet.

## Why

design-review shows real rendered options, but the options themselves are the weak part. The maintainer's experience in another project: options "sometimes barely changed anything, or dropped an element I liked." He wants the designer to work **well beyond his own eye: truly professional**, so that picking an option is choosing between good designs, not rescuing a weak one.

Today, design-review reads the style guide only for colors and fonts, has no design rubric, nothing judges how good an option is, and nothing checks that the options differ from each other or from the page. style-guide never hands off to it.

## What success looks like

- On a test bench of first screens the maintainer dislikes, the upgraded designer's redesigns are rated higher, **blind**, than the current designer's, and higher than the originals.
- No option silently drops an element: every element of the section is accounted for (kept, moved or removed, with a reason).
- The options in an item really differ (layout or hierarchy, not only color or spacing), and none is a near-copy of the current page.
- Cost per design-review stays close to today's (target: under about $2.50 est. per run on the piw apps; today's runs cost $1.40 to $2.69).

## Goals

1. **Design profile (optional).** A short project file that says what "good" means here: the references the owner loves and dislikes and why, a few rules in plain words (for example "the first screen must earn its space: what it is, why, one action"), the audience (for example older readers need large type), and a pointer to the style guide for tokens.
2. **A real range per item:** three options, *careful* (fixes what was asked, keeps the structure), *step up* (a clearly better layout within the site's language) and *bold rethink* (a different hierarchy or layout).
3. **Element inventory:** before designing, list the section's elements from the capture; each option shows what it kept, moved and removed, and why. The reader can say "keep X" on accept.
4. **Critic pass:** after building the options and before publishing, score each against a written rubric and the measurable checks, revise or drop the weak ones once, and show the scores on the page.
5. **Measurable checks** on every mockup, run by the builder's `--smoke` (which already measures overflow and mid-word breaks): text contrast, tap-target size, line length, type sizes against the profile's or site's scale, alignment of edges.

## Non-goals

- No new skill. This lives in design-review (feature freeze: no new skills until the core three are clean twice in a row).
- No AI-generated images; mockups stay HTML/CSS from the site's own styles.
- Not a replacement for style-guide. style-guide stays the place site-wide rules are settled; the profile is a short taste note that can point at it.
- No real-brand redesigns in public. The test bench uses made-up names.

## Anti-goals (a failure even if it technically works)

- Options that look different but drop an element the owner liked.
- A profile or style guide becoming a **requirement**. With neither present, design-review must still work: it offers to create a short profile (three or four questions on a questions page), derives what it can from the site's CSS, and goes on.
- The bold option being reckless: breaking the site's brand, inventing copy, or changing words nobody picked.
- Cost or turns doubling (Astro run 3 already showed design-review can double its cost by over-measuring).
- A critic that always passes its own work. Its scores must be able to fail an option, and the page shows them.

## Constraints

- Must work headless under `claude -p` with today's allow rules: no subagents required, no network fetches, one command per Bash call, everything under `.proofs/`.
- Changing design-review **resets the core three's "clean twice" count** (honest-scoring plan D). The held-out React Router run is on a frozen version, so this ships **after** the held-out run, or the held-out run is done on the version before it.
- Every fix and check is tested on at least two stacks' apps (the fix rule).
- American English in everything.

## Approaches considered

1. **Profile → range → critic (chosen by the maintainer, 2026-11-24).** A short profile sets the bar; three options by role guarantee range; a critic pass with a rubric plus measured checks judges them. Profile and style guide optional: used when present, offered when missing, never required.
2. *Rubric only:* add a rubric and measurable checks to today's flow. Cheapest, but does nothing about timid options or dropped elements, the two things the maintainer named.
3. *Separate designer skill:* a new skill style-guide and design-review both call. Cleanest split, but ruled out by the feature freeze, and it adds a hand-off to break.

## The design

### 1. The design profile

- File: `.proofs/design-profile.md` is scratch; the profile is a project file, **`docs/design-profile.md`** by default (or the path in the `PROOFS_DESIGN_PROFILE` setting). *Builder's call is fine on the exact name.*
- Contents, each short: **References** (sites loved, liked, not for us, one line why each); **Rules** (three to seven plain sentences); **Audience**; **Tokens** (a pointer to the style guide, or "derived from the site's CSS").
- Missing profile: design-review says so in one line, offers to create one (a questions page with the reference and rules questions; the reader's answers become the file), and goes ahead without it this round, deriving tokens from the site's CSS and using the built-in rubric alone.
- style-guide, when it finishes, mentions that design-review can use its guide and a profile.

### 2. Element inventory

- From the before capture, list the section's elements: headings, body text blocks, buttons and links, images, lists, forms, badges. The capture already walks the DOM for its other checks; add an `elements` list per section to `measures.json`.
- Each option's card shows a compact table: element, kept / moved / removed, reason. A removed element is shown in the card's warning color.
- The export accepts a "keep X" comment, and applying a pick honors it.

### 3. The range

- Each requested item gets three options labeled **Careful**, **Step up** and **Bold**. One option is fine for a "Found by the capture" fix (no mockup needed, per 1.6.10).
- **Near-copy check:** `--smoke` compares each option's layout signature (the order, size and position of its top-level blocks) with the before and with the other options, and flags pairs above a similarity threshold. *Threshold is the builder's call, stated in the PR with its reason.*
- Words stay the same unless the reader picked a copy change (1.6.10 rule). A bold option that needs shorter copy says so and asks.

### 4. The critic pass

- A rubric in a new reference file, scored 1–5 per option: **hierarchy** (one thing is clearly first), **one clear action**, **the first screen earns its space**, **grouping** (related things together, space between groups larger than within), **fit with the profile and site**, **element care** (from the inventory).
- The measurable checks give pass/fail rows alongside.
- After the first build: any option below a bar (*builder's call, for example any score of 2 or any failed check*) is revised once or dropped, with the reason on the page. Then the "one build, at most one correction pass" rule applies as today.
- The page shows each option's scores in a small row under its note, so the reader sees why it is recommended.
- The critic runs in the same session, with a fresh written checklist. A separate-context critic (a subagent) is an option for interactive sessions only; see open question 2.

### 5. Measurable checks

Added to `--smoke` for mockups: contrast of text against its background (WCAG AA), tap targets under 44 by 44 px at 390, line length over about 80 characters at 1280, type sizes off the profile's or site's scale, left edges in a section that miss each other by a few pixels. Reported per option, like the mid-word check is today.

### 6. How it is tested

- **Test bench:** the first screens of the seven "Not for us" sites, rebuilt as static pages with made-up names and no real logos (private copies only; public site shows the made-up versions). Five are used while tuning; **two are held out** and never looked at until the final comparison.
- For each bench page: current designer vs upgraded designer, same request ("make this first screen something I'd like"). Score = the maintainer's **blind** rating of before / old / new, plus the critic score, plus the measured checks.
- Plus the usual piw runs: the change is tested on at least two stacks' apps, and scored with `bin/score-run`.

## Settled after the builder check

- **The bench comes first, as its own step, built interactively (not headless).** The seven sites are the maintainer's "Not for us" ratings of 2026-11-24: Vercel, Raycast, Whoop, GOV.UK, Mayo Clinic, Basecamp, Mailchimp. Each first screen is rebuilt by hand from a screenshot taken in an interactive session, with made-up names, made-up copy of the same length and shape, and no real logos or photos; the copies stay private. Five tune the designer and two are held out. The maintainer rates them blind on a questions page: for each bench page, the original, the old designer's result and the new one's, shown in shuffled order and unlabeled, each rated Love / Like / Not for us. *(Answered by plan J; the method is my call.)*
- **Timing.** The held-out React Router run has not happened yet. This work is built on a branch and **does not merge until that run is scored**. The two-stack tests use piw apps in local copies, not scored piw runs. *(Answered.)*
- **capture.cjs may change, additively.** The `elements` list is a new field in `measures.json`, and no existing field changes. visual-qa's and pr-qa's output stays the same, and their tests must pass unchanged. A "section" is a `section`, `header`, `footer`, `main > *` or landmark element; on pages with none, it is each direct child of `main`, or of `body` when there is no `main`, that is over 200 px tall. *(My call; threshold stated with its reason in the PR.)*
- **"Keep X" on accept** means the applied pick puts X back into the chosen layout during the apply step. If it cannot fit, the session says so and asks, instead of starting a new round. The export carries it as the comment, as it does today, so the decision engine does not change. *(My call.)*

## Left to the builder

Exact file names and settings, the near-copy threshold and layout signature, the critic's bar, the rubric's wording, and how the element table looks on the card, each stated in the PR with its reason.

## Open questions for the maintainer

1. **Three options for every item?** A misaligned button does not need a Bold rethink. My recommendation: three options (Careful, Step up, Bold) for redesign requests, and one option for a bug-sized fix or a "Found by the capture" item.
2. **Quality or cost, when they collide?** Three options, a critic and one revise pass may go over the $2.50 target. My recommendation: quality wins up to the existing $5 est. cap per run, and the PR reports the real cost.
3. **A separate critic?** A critic in its own fresh context (a helper) is more independent than the same session grading its own work, which is the "same model grades itself" weakness the scoring plan names. But it costs more, and `claude -p` cannot always use one. My recommendation: a separate critic in interactive sessions, with the same-session checklist as the fallback in `claude -p`; both use one rubric file.
