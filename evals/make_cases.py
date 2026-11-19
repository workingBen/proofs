"""Write the skill trigger eval cases from CASES below: one folder per case, prompt.md plus graders.

Each skill gets prompts that should fire it, and one near miss: a prompt meant for its nearest
sibling, which must fire the sibling and NOT this skill. Rerun after editing CASES:
    python3 evals/make_cases.py
Run the suite (scored on which skill fired, so no ablation arm):
    claude plugin eval . --ablation none --no-publish
"""
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))

# skill: ([prompts that should fire it], (sibling, near-miss prompt that should fire the sibling instead))
CASES = {
    "design-review": (
        ["The pricing page hero looks dated. Show me two or three redesign options next to the current page so I can pick one before you build anything.",
         "Before you change the card layout on the blog index, mock up a couple of versions against a screenshot of what's there now."],
        ("visual-qa", "Something looks off on the checkout page on phones: cramped, and the text is tiny. Go through it at desktop and phone sizes and tell me what's wrong.")),
    "visual-qa": (
        ["I just finished the new dashboard. Before we call it done, check how it looks at laptop and phone widths and measure anything that's off.",
         "The orders list looks cramped and empty at the same time on my laptop. Figure out what's wrong with the layout."],
        ("pr-qa", "There are three open pull requests from the overnight agent run. Show me before and after screenshots of each so I can decide which to merge.")),
    "pr-qa": (
        ["QA the open PRs before I merge them. I want to see what each one changed, not read diffs.",
         "The agent opened two pull requests last night. Can I see screenshots of what they change on desktop and phone before I approve them?"],
        ("visual-qa", "Audit the settings page at three screen sizes. I think the layout breaks on phones.")),
    "article-copy-edit": (
        ["Here's my editor's feedback on the sleep article: twelve line edits. Let's go through them together before anything changes in the file.",
         "Copy-edit my blog post about cold plunges and let me approve each change."],
        ("design-review", "The article page layout feels cramped. Show me a couple of layout options for the article template before you change it.")),
    "photo-picker": (
        ["The retreat article needs photos for the hero and two section breaks. Find some licensed options I can choose from.",
         "Source a few candidate images for the morning routine section and let me pick one."],
        ("design-review", "Should the hero photo be full-bleed or inset? Show me both layouts next to the current page.")),
    "style-guide": (
        ["Our pages have drifted: different heading sizes, card styles and spacing everywhere. Audit the whole site and help me settle on consistent rules.",
         "Codify our design conventions across the whole site so future pages stay consistent."],
        ("design-review", "Redesign just the footer of the home page. Show me a few options first.")),
    "working-log": (
        ["I can't read your terminal output reliably. From now on, talk to me through a page I can keep open and follow along.",
         "I'll be away for a few hours while you work through the backlog. Keep a running record I can catch up on and reply to when I'm back."],
        ("questions", "I just need a page with the three decisions you need from me about the pricing tiers, with buttons I can tap.")),
    "questions": (
        ["Before you start on the export feature I have four decisions for you to put to me: date format, file name, whether to include voided invoices, and the default month. I'm on my phone, so put them somewhere I can tap answers and paste them back.",
         "You have five open questions about the import feature piling up in chat. Put them on a page I can answer at my own pace and paste back."],
        ("qa-checklist", "The new upload flow just shipped. List the checks only I can do on my real phone and with production data, and let me mark each one pass or fail.")),
    "qa-checklist": (
        ["The new upload flow just shipped. List the checks only I can do on my real phone and with production data, and let me mark each one pass or fail.",
         "The fix is deployed and I'm the only one with access to production. Give me a run sheet of what to verify, with pass or fail for each."],
        ("questions", "Before you build the export, I need to decide the date format and the file name. Give me options I can tap.")),
    "todos": (
        ["Show me my open to-do list as something I can tick off, then archive what's done.",
         "Go through TODO.md with me. I want to mark which items are finished."],
        ("review-cycle", "I'm going to send you a stream of small bugs from my phone over the next hour. Work each one to completion without stopping to ask.")),
    "review-cycle": (
        ["I'm going to send you a stream of small bugs from my phone over the next hour. Work each one to completion without stopping to ask.",
         "Review session: I'll feed you bug reports and small feature requests one at a time. Fix each one, and flag anything risky for later."],
        ("todos", "What's still open on my to-do list? Give me a page where I can tick things off.")),
    "changelog": (
        ["Add a What's new page to the app that shows our changes month by month.",
         "We shipped the new search today. Add an entry to the changelog."],
        ("working-log", "Keep a running page of what you're doing this session that I can follow and reply to.")),
}

# Harder round: requests a reasonable person could word either way. Each names the ONE right
# skill and why, and passes only if that skill fires and no other proofs skill does. A case that
# was a genuine coin flip was dropped rather than graded.
# (case name, right skill, why it is that one, prompt)
AMBIGUOUS = [
    ("phone-tonight", "qa-checklist", "Only the user has the phone and production; Claude cannot run it.",
     "The menu fix is live on production. I'll check it on my own phone tonight. What should I look at?"),
    ("phones-look-right", "visual-qa", "Claude can measure the page at phone width itself.",
     "Does the new menu look right on phones? Check it before we call it done."),
    ("list-cross-off", "todos", "The user's own list, to tick off.",
     "What's left on my list? I want to cross off what's finished."),
    ("pr-mobile", "pr-qa", "An open PR, judged by what it changes.",
     "Is this pull request ok to merge? I mostly care whether it breaks anything on mobile."),
    ("ask-later", "questions", "Several decisions, answered later from a phone.",
     "You'll hit a few decisions while building the import: column names, date handling, what to do with duplicates. Ask me instead of guessing; I'll answer later from my phone."),
    ("stepping-away", "working-log", "A running record for an absent user, with decisions in it.",
     "I'm stepping away for the afternoon. Keep me posted as you go, and leave anything you need me to decide where I can answer it."),
    ("weak-intro", "article-copy-edit", "Wording of an article, approved line by line.",
     "The intro of the sleep article is weak. Rewrite it, but let me approve the changes before they go in."),
    ("buttons-differ", "style-guide", "Consistency across the whole site, not one page.",
     "Our buttons look different on every page. Sort that out so they match everywhere."),
    ("shipped-today", "changelog", "Users reading what shipped, not the session record.",
     "Write up what we shipped today so our users can see it."),
    ("little-fixes", "review-cycle", "A stream of small items worked one by one.",
     "I've got a bunch of little fixes for the app. I'll send them one at a time as I find them."),
    ("ugly-hero", "photo-picker", "A new photo, not a new layout.",
     "The hero image on the retreat page is ugly. Find me a better one."),
]
# Plain coding requests: no proofs skill should fire.
NONE = [
    ("typo", "Fix the typo 'recieve' in the signup form."),
    ("regex", "What does this regex match: ^[0-9]{3}-[0-9]{4}$ ?"),
    ("unit-test", "Add a unit test for the price calculator."),
]
SKILLS = list(CASES)

PROMPT = """---
max_turns: 3
timeout_seconds: 180
allowed_tools: [Skill]
runs: 3
---
{prompt}
"""


def fired(skill, should=True):
    """A tool_used grader on the Skill tool. Its input is JSON like {"skill":"proofs:questions"},
    and input_match is a regex over that text, so match the name between a quote or colon and a quote."""
    rng = "" if should else "min: 0\nmax: 0\narm: both\n"
    return f"---\ntype: tool_used\ntool: Skill\ninput_match: '[\":]{skill}\"'\n{rng}---\n"


def none_other(skills):
    """No proofs skill outside `skills` fired."""
    alt = "|".join(x for x in SKILLS if x not in skills)
    return f"---\ntype: tool_used\ntool: Skill\ninput_match: '[\":]({alt})\"'\nmin: 0\nmax: 0\narm: both\n---\n"


def write(name, prompt, graders):
    d = os.path.join(HERE, name)
    os.makedirs(os.path.join(d, "graders"))
    with open(os.path.join(d, "prompt.md"), "w") as f:
        f.write(PROMPT.format(prompt=prompt))
    for g, body in graders.items():
        with open(os.path.join(d, "graders", g + ".md"), "w") as f:
            f.write(body)


def main():
    for e in os.listdir(HERE):
        if e.startswith(("fire-", "miss-", "ambiguous-", "none-")):
            shutil.rmtree(os.path.join(HERE, e))
    for skill, (fires, (sib, miss)) in CASES.items():
        for i, p in enumerate(fires, 1):
            write(f"fire-{skill}-{i}", p, {"fired": fired(skill)})
        write(f"miss-{skill}", miss, {"sibling-fired": fired(sib), "not-fired": fired(skill, False)})
    for name, right, _why, p in AMBIGUOUS:
        write(f"ambiguous-{name}", p, {"right-fired": fired(right), "no-other": none_other([right])})
    for name, p in NONE:
        write(f"none-{name}", p, {"no-proofs-skill": none_other([])})


if __name__ == "__main__":
    main()
