GROUPS = [
 ("Decide before it's built", ["design-review", "article-copy-edit", "photo-picker", "style-guide"]),
 ("Check what's built", ["visual-qa", "pr-qa"]),
 ("Talk on a page, not in the terminal", ["working-log", "todos"]),
 ("Keep long sessions on track", ["review-cycle", "changelog"]),
]
ORDER = [s for _, g in GROUPS for s in g]
