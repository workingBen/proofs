# Launch changes: where the site pages changed meaning

Each line is a page feature whose promise changed so the site matches the merged skill.
Format: skill · feature label · before → after.

- review-cycle · Your Verdict on Each Fix · the summary buttons start with nothing selected (already stated on the page; confirmed against the skill, so a silent card reads as "no decision yet", never approval).
- review-cycle · One Fix, One Pull Request · merged as it goes, with no condition → merged as it goes unless your project requires human review, in which case the fixes land as open pull requests.
- changelog · A What's New Page · a ready-made page → a stack-neutral spec: Claude builds the page in your own language and framework from the file format, parsing rules and behavior.
- changelog · Colors That Survive the Build · always applied → applies when your CSS tooling scans for complete class names.
- changelog · Fits Your Stack · "swap in your own sign-in check and markdown tool" (implied a template) → uses the sign-in check and markdown renderer your app already has, in your language.
- photo-picker · Uploaded to Your Image Host · uploaded to a fixed host → uploaded to "your image host", following your project's notes; if none exists, Claude asks where images should live first.
- style-guide · Optional: A Hidden Address · unchanged in meaning, now stated as opt-in: served at an unlinked address only after your explicit approval.
- style-guide · Future Sessions Follow It · "says so if they don't" → proposes adding the pointer to your project instructions and waits for your go-ahead.
- pr-qa · Nothing Goes Quiet · every session starts with the open-PR count → opt-in: the hook ships with the plugin but is off until you turn it on with one command (`python3 scripts/install_session_hook.py`), which sets `PROOFS_PR_REMINDER=1` in the project's settings; no path is written into the project.
- pr-qa · Runs It for Real · the page implied a complete pipeline → the helper scripts need a pages map you write for your own routes, and you bring the screenshot producer (the scripts read the before and after evidence you write).
- pr-qa · Real People Stay Private · redaction happens automatically → your screenshot step is told to redact before capture.
- visual-qa · Signed In for Real · signs in through your real form → you write a small sign-in hook (an example is bundled) that reads the password from an untracked env file.
- visual-qa · Every State, Not Just One · states are found automatically → you list pages and states in a pages file (an example is bundled).
- article-copy-edit · What's Risky in Your Field? · Claude asks → Claude looks in your project notes first, asks once if they are silent, and records the answer.
- working-log · How to Get Back Here · the page always gives the command to reopen it → the exact command if your project has an opener script, otherwise the place the project keeps its links.
- working-log · (new section, Questions-for-you mode) · six features folded in from the retired batched-decisions skill: real buttons, the ask/why/pick, mockups, answers that can't be misfiled, a test checklist for you, and no building on guesses.
- (all nine page-producing skills) · Where the Page Goes (new feature) · new: a per-project `PROOFS_PAGES` setting sends review pages to a private claude.ai artifact, a local HTML file, or that file served on your Wi-Fi for a phone; falls back to a file when publishing is unavailable. README line ("No claude.ai artifacts? Pages open in your browser instead, or on your phone over Wi-Fi.") is in place.
- (lineup) · youtube-generation, token-diet, worktrees and batched-decisions pages are not published; the home page counts 10 skills.
