# Changelog

- **1.2.0** (2026-11-22): Runs its scripts (`review_page.py`) through `${CLAUDE_PLUGIN_ROOT}` and pre-approves them and reads of the plugin's own files, so a session no longer asks permission for each one.
- **1.1.0** (2026-11-19): The page's header now starts with the proofs mark and a `qa-checklist` pill, then the project and the session (accented), in the sticky bar with no added height. Fill `project.session`; a page without it still builds, with a warning.
- **1.0.1** (2026-11-19): Says plainly that it needs the whole plugin, for anyone who copies one skill folder on its own.
- **1.0.0** (2026-11-18): New skill, split out of working-log's QA checklists: checks only the user can run, PASS / FAIL / COULDN'T TEST, ordered by consequence, with its own tally, its own export block and `(NOT CHECKED)` marker. A checks-only page now exports as `[qa-checklist v1.0 — results]`. Works on working-log's session page (Checks for you) or as its own page.
