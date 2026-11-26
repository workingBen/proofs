GROUPS = [
 ("Decide before it's built", ["design-review", "article-copy-edit", "photo-picker", "style-guide"]),
 ("Check what's built", ["visual-qa", "pr-qa", "qa-checklist"]),
 ("Talk on a page, not in the terminal", ["working-log", "questions", "todos"]),
 ("Keep long sessions on track", ["review-cycle", "changelog"]),
]
ORDER = [s for _, g in GROUPS for s in g]

# Skills that ship in the plugin but have no site page yet: their pages wait on
# the owner's copy review. Remove a name here when its page is added to GROUPS.
NOT_YET_ON_SITE = {"settings"}
