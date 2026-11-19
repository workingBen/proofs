# Changelog

- **1.1.0** (2026-11-19): Description sharpened: this skill fires whenever Claude needs the user to answer or decide anything, including several decisions to answer later or from a phone, and still supplies the questions on working-log's session page. Found by the ambiguous trigger evals, where such a request fired working-log instead.
- **1.0.1** (2026-11-19): Says plainly that it needs the whole plugin, for anyone who copies one skill folder on its own.
- **1.0.0** (2026-11-18): New skill, split out of working-log's questions-for-you mode: batched questions with real controls, a stable qid, notes, a recommended option, a Decided list and the questions export (now `[questions v1.3 — answers]`). Starts on its own the first time a session has a question for the user. New rule: open questions are the first thing on the page, directly under the sticky bar, and the builder enforces it. Works on working-log's session page or as its own page.
