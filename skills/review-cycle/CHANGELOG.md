# Changelog

- **1.13.2** (2026-11-24): The per-item recipe stages files by name and opens the PR with `--body-file .proofs/pr-body.md` (what changed, why, how it was checked) instead of `--fill`, and a failed push is reported with the exact command, per the new `reference/commit-and-pr.md`. **Results first** (the maintainer's principle): nothing matters more than a result the user wants; save tokens by cutting waste, never by cutting a check, an option or a revise pass the result needs. Full text is rule 0 in `reference/house-rules.md`.
- **1.13.1** (2026-11-24): Stage only what the item changed: a lockfile an install rewrote stays out of the commit, or the PR body says why it is in (Angular run 1 committed one unasked).
- **1.13.0** (2026-11-22): The per-item push is now `git push -u origin HEAD`, which the opt-in `--commit` allow block permits; deleting the branch afterward still asks.
- **1.12.0** (2026-11-19): The tracking page's docked bar starts with the proofs mark, a `review-cycle` pill, the project and the session, reusing the shared builder's markup and CSS, so it is never mistaken for another session's page.
- **1.11.4** (2026-11-19): The tracking page is delivered as "Where the page goes" says rather than always via artifacts. Says plainly that it needs the whole plugin.
- **1.11.3** (2026-11-18): Description trimmed to the trigger and how it differs from its nearest sibling; the detail it used to carry is in the body. No change in behavior.
- **1.11.2** (2026-11-18): Checkpoints, The Tracking Page and End-of-Session Summary moved to `reference/` files in this skill's folder, each read when it applies (their Common Mistakes rows moved with them); SKILL.md keeps a short pointer and the trigger list. No change in behavior.
- **1.11.1** (2026-11-18): Moved 'Where the page goes' to a shared reference file and the changelog to CHANGELOG.md; no change in behavior.
- **1.11.0** (2026-11-17): Triage. Every item gets one lane (Fix, Design review, Visual QA, Copy edit, Photo, Style rule, To-do, Needs input), and the lane starts the matching skill in this plugin automatically: a design call becomes a published design review, a big feature becomes a to-do. Two new card states: In design review, Saved as a to-do.
- **1.10.2** (2026-11-17): Copy buttons now fall back to a selectable text box when the clipboard is unavailable (as on a Wi-Fi-served page), and `wifi` mode is limited to a private network you trust. The superpowers skills are optional, with a plain fallback when they are not installed.
- **1.10.1** (2026-11-16): New section "Where the page goes": a project can choose an artifact, a local file, or a file served on its own Wi-Fi.
- **1.10.0** (2026-11-16): Merged into proofs: generic, no project-specific steps.
