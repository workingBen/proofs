# Changelog

- **1.6.1** (2026-11-22): `pr_qa_findings.py` says "not measured" instead of "clean" when the evidence holds no measurements.
- **1.6.0** (2026-11-22): Runs its scripts (`pr_qa_page.py`, `pr_qa_findings.py` and `pr_qa_plan.py`) through `${CLAUDE_PLUGIN_ROOT}` and pre-approves them and reads of the plugin's own files, so a session no longer asks permission for each one.
- **1.5.1** (2026-11-21): The headless Chrome command adds `--disable-features=MacAppCodeSignClone`. On a Mac, Google Chrome copies its whole app (about 1.4 GB) into a temp folder on every launch and deletes it only on a normal quit, so screenshot runs left those copies behind.
- **1.5.0** (2026-11-19): The top bar starts with the proofs mark and a `pr-qa` pill, then project · session · repo; the "PR QA" label is gone. New `--session` flag on `pr_qa_page.py`; without it the page builds and says it has no session.
- **1.4.5** (2026-11-19): Says plainly that it needs the whole plugin, for anyone who copies one skill folder on its own.
- **1.4.4** (2026-11-18): Description trimmed to the trigger and how it differs from its nearest sibling; the detail it used to carry is in the body. No change in behavior.
- **1.4.3** (2026-11-18): Moved 'Where the page goes' to a shared reference file and the changelog to CHANGELOG.md; no change in behavior.
- **1.4.2** (2026-11-17): Copy buttons now fall back to a selectable text box when the clipboard is unavailable (as on a Wi-Fi-served page), and `wifi` mode is limited to a private network you trust. The session reminder now ships as a plugin hook that stays off until `PROOFS_PR_REMINDER=1` is set (the installer sets it); no path is written into project settings. Invocations use `/proofs:pr-qa`.
- **1.4.1** (2026-11-16): New section "Where the page goes": a project can choose an artifact, a local file, or a file served on its own Wi-Fi.
- **1.4.0** — Merged into proofs: generic, no project-specific steps.
