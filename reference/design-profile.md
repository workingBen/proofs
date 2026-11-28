# The design profile

A short project file that says what "good" means for this site: the references the owner loves and dislikes and why, a few rules in plain words, who the readers are, and where the tokens live. design-review's designer reads it before designing, and its critic scores `fit` against it (`design-rubric.md`).

**It is optional, and so is a style guide: both are used when present and never required.** With no profile, design-review says so in one line, offers to create one, and goes on this round without it: it derives the tokens from the site's CSS and uses the built-in rubric alone.

## Where it lives

`docs/design-profile.md` in the project, committed with the code: it is a project decision, not scratch, so it does not go under `.proofs/`. To keep it elsewhere, set `PROOFS_DESIGN_PROFILE` to its path, relative to the project folder, in the `env` block of the project's `.claude/settings.json` (not as a prefix in front of a command, which would stop the command matching its allow rule).

## What it holds

Four headings, each short, and one line under Rules. A profile longer than a screen is a style guide; settle site-wide rules in style-guide and point to it from Tokens.

- **References**: sites the owner rated **Love**, **Like** or **Not for us**, each with one line saying why. The why is what the designer uses; the name alone says little.
- **Rules**: three to seven plain sentences a critic can check on a screenshot, and one `Density:` line (below).
- **Audience**: who reads the site, and anything that changes the design for them (age, device, how much time they have).
- **Tokens**: a pointer to the style guide, or "derived from the site's CSS".

**The `Density:` line.** `Density: <value>. <one line saying why>.` The value is `dense`, `balanced` or `airy`. For example: `Density: dense. Many numbers on one screen; people scan, not read. Don't add padding.` Both Refine and Redesign modes read it: the critic uses it in `grouping`, `fit` and Refine's `keeps` (`design-rubric.md`), so a data-heavy tool stays dense. With no profile, the designer infers density from the page (a table- or number-heavy page counts as dense) and says so in one line.

## A filled example

For a made-up bicycle repair shop:

```markdown
# Design profile: Tidewater Bikes

## References
- Love: apple.com product pages. One product per screen, a big photo of the real thing, one action.
- Like: stripe.com. Dense information that still reads in order, thanks to spacing.
- Not for us: amazon.com product pages. Everything at once; nothing is first.

## Rules
- The first screen earns its space: what we fix, why us, one button to book.
- Show real bikes and real work, never stock photos of people smiling at laptops.
- One primary button per screen; everything else is a text link.
- Prices are shown, never "contact us for a quote".
- Open layouts with rules and space between groups, not a grid of cards.
- Density: balanced. Room to breathe around photos, tight lists in the price table.

## Audience
Local riders, many over 50, mostly on phones at the shop counter or the trailhead.
Body text at least 18px; buttons large enough to tap with gloves on.

## Tokens
docs/style-guide.html
```

## Creating one

When the profile is missing, offer to make it on two questions pages (the `questions` skill), so the reader can answer from a phone and each page's answers come back in one export. The rules need the references first, so they cannot share a page:

1. **First page: references and audience.**
   - **References.** List four to six sites: well-known public product sites that fit the request, plus any the reader names. For each, the reader picks **Love**, **Like** or **Not for us** and writes one line saying why. Leave room to add a site.
   - **Audience.** One free-text answer: who reads the site, and anything about them the design must allow for.
   - **Density**, asked next to Audience. One pick: `dense`, `balanced` or `airy`, with one line saying why. Recommend the one the capture suggests (a table- or number-heavy page is dense).
2. **Second page: rules.** From those answers, the capture and the request, propose three to seven rules, each a plain sentence a critic can check on a screenshot and each with a recommended keep or drop. The reader keeps, edits or drops each and can add one.

Then write the file at the profile path from both pages' answers (the `Density:` line goes under Rules), in the reader's own words, with Tokens pointing to the style guide when the project has one, else "derived from the site's CSS". Show the reader the file and use it from the next design pass on. Never invent references or rules the reader did not give or pick.
