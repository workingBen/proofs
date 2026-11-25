# Design rubric

The checklist design-review's critic scores every mockup option against, after the options are built and before the reader sees them. The aim is options a senior product designer would put in front of a client: each one a real answer to the request, none that "barely changed anything", none that quietly dropped something the owner liked.

**Who judges.** In an interactive session a separate helper with a fresh context judges; give it this file, the request, the current page's screenshots at 1280 and 390, each option's screenshots at the same widths, the section's captured elements, each option's inventory, the style guide's path (or, when there is none, the site's CSS tokens: colors, fonts, type sizes, radius and spacing), the profile when there is one, and the `--smoke` output, but not the designer's reasoning, so it judges what it sees. In `claude -p`, where a helper may not be available, the session checks its own work: after the build, go through this file criterion by criterion as a fresh checklist, not from memory. Either way, set `judged_by` on the item (`helper` or `self`) so the page says which one judged.

**Score the current page first.** Before any option, score the current page's section on the same six criteria and write them into the item as `before_scores` (format: `review-page.md`); the page shows them as a "Current page" row above the options. That is the baseline: an option that does not beat it has not answered the request (the bar, below).

**How to score.** Each criterion is a whole number from 1 to 5. The anchors below say what **1**, **3** and **5** look like; 2 and 4 sit between them. Look at the screenshot before reading the option's note, and score what is on the screen, not what the note says it does. Judge against the request and the current page, not an ideal page. Give a 5 only when you can name what you saw that earns it. A critic that scores every option 4 or 5 is not working: the scores must be able to fail an option, and the reader sees them.

Write the scores into the spec as `"scores": {"hierarchy": 4, "action": 5, "fold": 3, "grouping": 4, "fit": 5, "care": 5}` on each variant (format: `review-page.md`). For every score of 3 or below, put the reason in one plain line in the option's note.

## The six criteria

### `hierarchy`: one thing is clearly first

Look at the screenshot shrunk to a thumbnail (or squint): what do you see first, second, third? Count the type levels in the section (size, weight or color steps). The lead should be clearly larger or heavier than the next level, about 1.5 times its size or more, and the order the eye takes should match what the request says matters.

- **1**: two or more things compete for first at the same size and weight, or the first thing the eye lands on is decoration, navigation or a secondary link. The headline is barely bigger than the body text.
- **3**: there is a clear first, but the second and third levels blur (a subheading the size of body text, three buttons of equal weight), or the lead works at 1280 and shrinks to body size at 390.
- **5**: the eye goes first, second, third in the order the request needs, at both widths. Each level differs from its neighbor by one or two of size, weight and color, and there are no more than about three levels. Nothing secondary is louder than the lead.

### `action`: one clear action

Count the controls styled as primary in the section. Find where the reading path ends, then where the action is.

- **1**: no action can be seen, or two or more actions share the primary style, or the action is a plain link lost inside a paragraph.
- **3**: there is one primary action, but it sits above or apart from what it acts on, or it looks the same as the secondary actions (two outline buttons side by side), or at 390 it falls below the first screen.
- **5**: exactly one primary action, the strongest control in the section, placed where the reading path ends (after what it is and why). Secondary actions are visibly lesser (an outline button or a text link). At 390 it is at least 44 by 44 px and on the first screen when the section is.

A section whose job is not an action (an article body, a footer, a list of facts) scores on not competing: a 5 adds no control that pulls attention from the page's main action, and the reason line says "no action needed".

### `fold`: the first screen earns its space

The first screen is what the reader sees before scrolling: the top 800 px at 1280 and the top 844 px at 390, the window sizes the capture uses. It is the only part every visitor sees, so it has to say what this is, why it matters to the reader, and what to do next. For a section lower on the page, score its first window-height the same way, as the reader scrolls into it.

- **1**: the first screen is a lone big image, an empty band, a giant headline with nothing else, a navigation bar over blank space, or a carousel. At 390 the reader sees neither what the product is nor an action.
- **3**: it says what this is and has the action, but the why is missing or pushed below; or 1280 works and 390 loses the action below the fold; or an image takes more than half the screen and squeezes the text into a corner.
- **5**: at both widths the first screen carries what it is (named in the reader's terms), why it matters (one line of benefit or proof) and the one next step, with room around them. Big imagery is fine, and often right, when it shows the product or the outcome and the fold still carries the name and the action.

### `grouping`: related things together

Things that belong together sit closer to each other than to anything else, so the reader sees the groups from spacing alone. Check the space between groups against the space inside them, and check that each label sits next to what it labels.

- **1**: the same spacing everywhere, so groups dissolve into a list; a caption closer to the wrong image; a button floating halfway between two blocks; boxes inside boxes inside boxes.
- **3**: most groups read, but one element is ambiguous, or the gaps between sibling groups vary for no reason, or borders and cards do the grouping where space alone would (a profile may prefer open layouts).
- **5**: every group reads at a glance from spacing alone. The space between groups is clearly larger than the space within them, about twice. Sibling groups share the same spacing and a few shared left edges. At 390, stacking keeps each label with its thing.

### `fit`: fits the profile and the site

Judge against the profile when there is one (its References, Rules and Audience; format: `design-profile.md`), and always against the site's own tokens and voice: its colors, fonts, type scale, radius, spacing, button and card styles, and light and dark themes. With no profile, judge on the site alone and say "no profile" in the reason line.

- **1**: brings colors, fonts or a button style the site does not use; breaks a stated profile rule (for example, body text under the size the Audience line asks for); reads like a template rather than this site; leans toward a "Not for us" reference.
- **3**: uses the site's tokens, but one piece is off: a new radius, a type size off the site's scale, a shadow the site never uses, or a profile rule followed at 1280 and broken at 390.
- **5**: could go on the site tomorrow without any piece looking borrowed. Every color, font, radius and spacing comes from the site or its style guide, each profile rule holds at both widths, and where the profile names a "Love" reference, the option moves toward the quality its "why" line names without copying it.

### `care`: element care

Judge from the option's inventory against the section's captured elements: every heading, block of body text, button, link, image, list, form and badge. The page shows a captured element with no inventory row as "removed — no reason given".

- **1**: a captured element is missing with no reason, or something the owner might like (a photo, a testimonial, a badge, a price, a secondary link) is removed to make the layout easier; or words were rewritten that nobody picked; or copy was invented (a new headline, made-up numbers, placeholder quotes).
- **3**: every element is accounted for, but a removal's reason is weak ("cleaner", "simpler"), or a moved element lost its meaning (a disclaimer moved away from the claim it qualifies), or a small text change slipped in (casing, truncation) that nobody picked.
- **5**: every captured element has a row. Removals are few, and each has a reason the reader can accept or reject in one read ("repeats the nav link above"). The words are the page's own, unchanged unless the reader picked a copy change; where shorter copy would help, the note says so and asks.

## The measured checks

`--smoke` measures every option at 1280 and 390 and prints each failure as a problem line: text below WCAG AA contrast, tap targets under 44 by 44 px at 390, lines over 80 characters at 1280, left edges 1 to 6 px out of line, words broken mid-word, sideways scroll, and options that are near-copies of each other or of the current page.

- **Any failed design check means revise or drop, regardless of the scores.** A 5 everywhere does not excuse a contrast failure.
- **What a near-copy result means depends on the case, and it is never ignored silently.** The line stays in `problems`. Look at both shots (the two options, or the option and the current page), then either change the option or keep it with one line in the item's Reason saying what genuinely differs. Two options that are near-copies of each other fail unless the author, having looked, records what differs: without that, the reader is not being offered a choice. An option that is a near-copy of the current page fails for Step up and Bold, which must change the layout or hierarchy, on the same terms. For Careful it fails only when the problem in the request is still visible; a Careful that keeps the structure and visibly fixes the problem passes, and the note says so. For a one-option bug-sized fix or "Found by the capture" item it is expected and not a failure. How to read the score: it compares the blocks' reading order, columns, relative sizes and places, not their paint or spacing, and flags at 0.70. A recolor or a spacing-only change scores about 0.9 or more, and so does a faithful reproduction of the current page; one real change on its own lands near 0.70 (only a bigger heading about 0.6, only the buttons moved about 0.75); two real changes, or a different arrangement, fall well below. So a flag on an option meant to differ usually means it differs in one thing only: say which thing in the Reason, or change more.
- **"Not measured" notes are not failures, but you must look by eye.** `--smoke` writes "contrast not measured" for text over an image or gradient, which it cannot measure: open the screenshot and check each such line against the lightest and darkest part of the image behind it. If any letters cross a part of the image close to their own color, treat it as a contrast failure.
- **Off-scale type sizes are a note, not a failure.** Check that each one is deliberate, and count it in `fit`.

## The three roles

A redesign item has three options, each judged on the six criteria and on its role. A bug-sized fix or a "Found by the capture" item has one option with no role, scored the same way.

- **Careful** fixes what was asked and keeps the structure. It must still fix what was asked: if the problem in the request is still visible in Careful, score the criterion it belongs to 2 or below. A Careful that `--smoke` flags as a near-copy of the current page passes only when that fix is visible (the measured checks, above).
- **Step up** is a clearly better layout within the site's own language. It must be clearly better than Careful: at least one criterion higher and none lower. A Step up that scores the same as Careful is not a step up; revise it or drop it.
- **Bold** is a different hierarchy or layout: a different lead, a different order, or a different arrangement of the main blocks, never only new colors or spacing. It must differ from the other two and from the current page, and `--smoke` flags it as a near-copy when it does not. It is never reckless: a brand break scores `fit` 2 or below, invented copy or changed words score `care` 2 or below, and both are caught by the bar. A Bold that needs shorter copy says so in its note and asks instead of rewriting.

## The bar

**Any criterion at 2 or below, or any failed design check, means revise it once or drop it, with the reason on the page.**

**An option must also beat the current page** (its `before_scores`) on the criterion the request targets: `action` for "the button gets lost", `grouping` for "this section is a jumble". For a vague request such as "make this nicer", it must beat it on `fold` or `hierarchy`. An option that only ties the current page there is below the bar, however good its other scores: it is the option that "barely changed anything".

- **Revise once.** Fix what failed, rebuild, rerun `--smoke` and score again. Say what changed in the option's note, for example "Revised: the action was below the first screen at 390 (fold 2)."
- **Drop** an option that still misses the bar after its one revision, or that cannot be fixed without becoming another option. Say so in the item's reason, for example "Dropped Bold: it needed a headline nobody wrote (care 2)." Never publish an option below the bar without saying so.
- If dropping would leave an item with no option, keep the best one, mark the score that failed in its note, and say on the page that it did not clear the bar. Do not start another round; the one build, at most one correction pass rule still applies.
- **Recommend** the option with the highest total that clears the bar; on a tie, the one that best answers the request. Never recommend an unscored option or one below the bar.

Results first (`house-rules.md` rule 0): never skip the critic, the measured checks or the revise pass to save cost.
