# Proofs Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One settings list that every Proofs script and skill reads, plus a settings page (layout B, the owner's pick) where the owner changes them and saves through Send to Claude. Ships as Proofs 1.9.0.

**Architecture:** One data table (`shared/settings.json`) holds every setting: key, label, help, group, scope, type, default, limits. `shared/settings.py` resolves and writes values in Claude Code's own settings files (`env` block, `PROOFS_*` keys only), and `shared/settings.cjs` gives the Node scripts the same values. The page is a new review-page mode, `settings`, built from `settings.py --spec`. Its answers are saved like every other card, and the session applies them with `settings.py --set`.

**Tech Stack:** Python 3 stdlib, Node (no new dependencies), the existing review-page builder and engine (`shared/review_page/`), unittest.

**Spec:** the settings inventory (`2026-11-25-settings-inventory.md`, which the controller supplies: S1–S12, M1–M14, K1–K20, sections a and b) and the layout B mockup the owner picked in the design review (`optB.html` + `mock.css`, also supplied by the controller). Scope is decided: **the 12 SETTINGs plus every MAYBE**; the KEEP FIXED items stay fixed.

## Global Constraints

- American English in everything, including identifiers.
- No new runtime dependencies; Python stdlib only; Node built-ins only.
- **Settings write only `env` keys starting with `PROOFS_`**, in `~/.claude/settings.json` (user; `$CLAUDE_CONFIG_DIR/settings.json` when that is set), `.claude/settings.json` (project) or `.claude/settings.local.json` (local). Every other key in those files is kept byte-for-byte in meaning: load, change one key, dump with `indent=2`, keep a trailing newline.
- **Raise-only floors:** `PROOFS_MIN_TEXT` ≥ 16, `PROOFS_MIN_TAP` ≥ 44. Nothing lowers a KEEP FIXED rule (contrast 4.5:1/3:1, the 44 px design-check tap floor in `designchecks.cjs`, 80-char lines, edges, off-center 16 px, near-copy 0.70).
- 390 and 1280 are always captured; `PROOFS_EXTRA_WIDTHS` only adds widths (400–2560).
- `PROOFS_DESIGN_OPTIONS` is 2 or 3; `PROOFS_CORRECTION_PASSES` is 0, 1 or 2.
- The spend cap is an estimate the model plans around, never an enforced stop, and every place that shows it says so.
- Retire the CLAUDE.md line "proofs pages: file" as a second source for `PROOFS_PAGES`.
- Tests run in the FOREGROUND. At most two test runs at once on the machine.
- Gate (all green on the final commit): root `python3 -m unittest $(ls tests/test_*.py | sed 's#/#.#; s#\.py$##')`; `python3 -m unittest discover -s tests` inside `skills/pr-qa` and `skills/todos`; `bin/check-skills`; `bin/privacy-scan`; `bin/bump-version --check`.
- Version 1.9.0 (plugin.json and every place `bin/bump-version` updates), with a CHANGELOG entry.
- Stage explicit paths; never `git add -A`.

## Review Focus

1. **A value typed on the page that is out of range** (text floor 14, port 99999, "abc" in a number, quality 0). Expected: the page shows the reason under the field and leaves it out of the pending list. `--set` refuses it too, exit 2, and writes nothing. Tests are in Tasks 1 and 5.
2. **A settings file with other content or none at all** (permissions, hooks, a missing file, a file with no `env`). Expected: `--set` creates or merges and keeps every other key. Invalid JSON exits 3 untouched. Tests are in Task 1.
3. **A value written mid-session.** Claude Code put the old value into the environment at startup, so the environment and the file disagree. Expected: the file wins, and `--print` notes "restart Claude Code to pass it to hooks". Tests are in Task 1.
4. **A page opened after its settings changed elsewhere.** The row carries the value the page showed (`from`). Expected: `--apply` skips a row whose `from` no longer matches the current value and reports it, rather than silently overwriting. Tests are in Task 6.
5. **Send tapped with nothing answered** (the owner did this on 2026-11-26). Expected: the button stays off with one line of reason until at least one answer is saved, on every page kind. Tests are in Task 4.

---

### Task 1: The settings table and resolver

**Files:**
- Create: `shared/settings.json`, `shared/settings.py`
- Modify: `shared/allow_block.py` (pre-approve `--print` only)
- Test: `tests/test_settings.py`, `tests/test_allow_block.py`

**Interfaces:**
- Produces: `settings.json`, a list of `{key, label, help, group, scope, type, default, min?, max?, raise_only?, choices?, unit?, advanced}`. `type` is one of `int`, `choice`, `bool`, `text`, `list`, `path`, `auto`. `group` is one of `read`, `checks`, `app`, `prs`, `computer` (titles "Reading and cost", "Checks on this site", "Running the app", "Pull requests", "This computer"). `scope` is one of `user`, `project`, `local`.
- Produces in `settings.py`:
  - `load_table() -> list[dict]`
  - `get(key, *, cwd=None, env=None, home=None) -> value`, typed, so an int is an int.
  - `effective(*, cwd=None, env=None, home=None) -> dict[key, {"value", "source", "default", "note"}]`. `source` is one of `local`, `project`, `user`, `environment`, `default`.
  - `validate(key, raw: str) -> value`, which raises `SettingError` (with the message the page and CLI show).
  - `set_value(key, raw, scope=None, *, cwd=None, home=None) -> Path`, which writes the file and returns its path. `scope` defaults to the table's scope.
  - `unset(key, scope=None, ...)`.
- CLI: `--print` (a human table), `--json` (the `effective()` output), `--set KEY=VALUE [--scope user|project|local]`, `--unset KEY [--scope …]`. Exit codes: 0 ok, 2 invalid value or unknown key, 3 unreadable settings file.

The table holds every row from the inventory: S1 `PROOFS_COST_CAP_USD` (int, default 5, 1–100, unit "$ est."); S2 `PROOFS_PAGES` (choice artifact/file/wifi, default artifact); S3 `PROOFS_SPELLING` (choice american/off, default off); S4 `PROOFS_PR_REMINDER` (bool, default off; stored as "1"/"0"); S5 `PROOFS_AGENT_BRANCH_PREFIX` (list, default `agent/`); S6 `PROOFS_DESIGN_PROFILE` (path, `docs/design-profile.md`); S7 `PROOFS_PORT` 3311 and `PROOFS_BASE_PORT` 3411 (int 1024–65535); S8 `PROOFS_SERVER_TIMEOUT` (int 10–900, s); S9 `PROOFS_IMAGE_QUALITY` (1–100, 70) and `PROOFS_IMAGE_MAX_WIDTH` (16–20000, 1600); S10 `PROOFS_BROWSER_CHANNEL` and `PROOFS_PLAYWRIGHT` (auto, local); S11 `PROOFS_BASE_DIR` (path, `.proofs/base`, local); S12 `PROOFS_MIN_TEXT` (16, raise-only, max 32) and `PROOFS_MIN_TAP` (44, raise-only, max 96). The maybes are all `advanced: true`: M1 `PROOFS_EXTRA_WIDTHS` (list of ints 400–2560, default empty); M2 `PROOFS_DESIGN_OPTIONS` (choice 2/3, default 3); M3 `PROOFS_CRITIC` (choice helper/self, default helper); M4 `PROOFS_CORRECTION_PASSES` (choice 0/1/2, default 1); M5 `PROOFS_PHOTO_CANDIDATES` (1–6, 3); M6 `PROOFS_QA_MOCKUPS` (1–3, 2); M7 `PROOFS_CHECKPOINT_ITEMS` (1–50, 5); M8 `PROOFS_PR_REMINDER_TIMEOUT` (1–60 s, 5); M9 `PROOFS_QA_PATHS` (list, `app/,src/,lib/,public/,config/routes.rb`); M10 `PROOFS_QA_WORKFLOW` (`pr-qa.yml`) and `PROOFS_QA_MAP` (`pr_qa_pages.json`); M11 `PROOFS_SEND_WAIT_MIN` (2–30, 5, user); M12 `PROOFS_TODO_TITLE` (40–200, 96); M13 `PROOFS_CHANGELOG_DIR` (`docs/changelog`), `PROOFS_TODO_FILE` (`TODO.md`), `PROOFS_TODO_ARCHIVE_DIR` (`docs/todo-archive`) and `PROOFS_STYLE_GUIDE` (`docs/style-guide.html`); M14 `PROOFS_PAGE_WARN_MB` (1–15, 3, user). Labels and help are the mockup's wording.

**Resolution order:** local file > project file > user file > the process environment > the default. Files win over the environment because Claude Code copies the files into the environment only at startup, so a mid-session `--set` must still take effect. When the environment value differs from the winning file value, `note` = "restart Claude Code to pass the new value to hooks". The project root is the nearest folder above `cwd` that holds `.claude/` or `.git`.

- [ ] **Step 1: Write the failing tests** in `tests/test_settings.py`, each in a temp home and project:
  - `test_table_has_every_inventory_key`: the exact key set above, and no key is missing a label, help, group or scope.
  - `test_default_when_nothing_set`: `get("PROOFS_PORT") == 3311`, source `default`.
  - `test_file_order`: local beats project, project beats user, user beats environment.
  - `test_file_beats_stale_env`: env `PROOFS_PORT=3311` with project file `3099` gives `get` 3099 and a `note` naming a restart.
  - `test_raise_only_floor`: `validate("PROOFS_MIN_TEXT","14")` raises with "can only go up from 16"; `"18"` returns 18.
  - `test_rejects_bad_values`: port "99999", quality "0", "abc", options "4", extra widths "300" all raise.
  - `test_set_keeps_other_keys`: a project file with `permissions` and `hooks` keeps them unchanged after `--set PROOFS_PORT=3099`.
  - `test_set_creates_missing_file_and_env_block`.
  - `test_set_refuses_non_proofs_key`: exit 2.
  - `test_invalid_json_exit_3_untouched`: the file's bytes are unchanged.
  - `test_unset_removes_only_that_key`.
  - `test_claude_config_dir_is_the_user_file`.
  - `test_json_output_shape`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_settings -v`. Expected: FAIL (no module).
- [ ] **Step 3: Implement** `settings.json` and `settings.py` to the interfaces above.
- [ ] **Step 4: Add** `Bash(python3 ${CLAUDE_PLUGIN_ROOT}/shared/settings.py --print)` and `… --json)` to `allow_block.py`'s block, with a test in `tests/test_allow_block.py`. `--set` stays unapproved: it writes a settings file, so the owner sees each write.
- [ ] **Step 5: Run** `python3 -m unittest tests.test_settings tests.test_allow_block -v`. Expected: PASS.
- [ ] **Step 6: Commit** `shared/settings.json shared/settings.py shared/allow_block.py tests/test_settings.py tests/test_allow_block.py` with the message "settings: one table and resolver for every Proofs setting".

### Task 2: The scripts read the settings

**Files:**
- Create: `shared/settings.cjs`
- Modify: `shared/review_page/review_page.py` (image quality/width, spelling, page warning, Send wait baked into the page), `shared/review_page/engine.js:282` (`SEND_STALE_MS` from `S.send_wait_ms`), `shared/capture/with_server.py` (the `--timeout` default), `skills/visual-qa/scripts/capture.cjs` (the `minText`/`minTap` defaults, extra widths), `skills/pr-qa/scripts/open_prs_session_start.py` (reminder, prefixes, network wait), `skills/pr-qa/scripts/pr_qa_plan.py` and `pr_qa_collect.py` (visual paths, workflow and map names), `skills/pr-qa/scripts/pr_qa_findings.py:35` (the tap floor reads `PROOFS_MIN_TAP`), `skills/todos/scripts/todos_page.py:17` (title length)
- Test: add to `tests/test_review_page.py`, `tests/test_with_server.py`, `tests/test_visual_qa_capture.py`, `tests/test_send_to_claude.py`, and the pr-qa and todos suites

**Interfaces:**
- Consumes: `settings.get` (Task 1). The skill folders import it by path, as they already import `shared/` modules.
- Produces: `settings.cjs`, `get(key, {cwd, env, home}) -> value`. It reads the same table and files in the same order. Spec field `send_wait_ms`.

- [ ] **Step 1: Write the failing tests.** For each consumer, setting the value in a temp project file changes what it does, and an explicit flag still wins over the setting:
  - `with_server` with no `--timeout` uses `PROOFS_SERVER_TIMEOUT`, and `--timeout 30` still wins.
  - The capture's default `minText` is 18 when set, and `pages.json` `minText` still wins, but not below the setting's floor of 16.
  - `PROOFS_EXTRA_WIDTHS=1024` adds 1024 to `--sizes 390,1280`.
  - The todo title is cut at the set length.
  - The reminder labels `claude/` branches when the prefixes are `agent/,claude/`.
  - `pr_qa_plan` treats `web/` as visual when it is listed.
  - The page-size warning fires at the set number of MB.
  - A built page carries `send_wait_ms` = 10 × 60000 when the setting is 10, and `pickupNote` says "Not picked up yet" only after that wait.
  - `review_page` spelling and image values come from the files.
  - **Duplicates removed:** `grep` finds no literal 44 tap floor in `pr_qa_findings.py`, and no `96` in `todos_page.py`.
- [ ] **Step 2: Run** the touched suites. Expected: the new tests FAIL.
- [ ] **Step 3: Implement** each consumer as one call to `settings.get` (or `settings.cjs` `get`) in place of its constant. Keep the existing explicit flags and spec keys as overrides.
- [ ] **Step 4: Run** the touched suites, then the full gate. Expected: PASS.
- [ ] **Step 5: Commit** the listed files, with the message "settings: scripts read one source instead of copied constants".

### Task 3: The skills read the settings, not literal numbers

**Files:**
- Modify: `reference/house-rules.md` (rule 0: the spend cap is `PROOFS_COST_CAP_USD`, an estimate, for every skill), `reference/where-the-page-goes.md:5` (drop the CLAUDE.md fallback; `PROOFS_PAGES` only), `skills/design-review/SKILL.md` (ports, cap, option count, critic, correction passes, profile path), `skills/visual-qa/SKILL.md` (port, floors, mockups per item), `skills/pr-qa/SKILL.md` (ports, base folder, paths), `skills/photo-picker/SKILL.md` (candidates), `skills/review-cycle/SKILL.md` (checkpoint), `skills/changelog/SKILL.md`, `skills/todos/SKILL.md`, `skills/style-guide/SKILL.md` (doc paths), `reference/review-page.md` (5-minute Send wait, image values)
- Test: `tests/test_skill_guidance.py` (the `$5` assertion near line 922 becomes a wording check), `tests/test_command_forms.py`, `bin/check-skills`

**Interfaces:**
- Consumes: `settings.py --print` (Task 1).

Every skill that uses a setting adds one line at its start: "Read the settings: `python3 ${CLAUDE_PLUGIN_ROOT}/shared/settings.py --print` (pre-approved). Use the values it shows wherever this file says *the port*, *the spend cap*, and so on." Each literal value becomes "the port setting (default 3311)". The command examples keep `3311` as the shown default, so the command-form tests still match the allow rules. Add one sentence: "use the setting's value in its place".

- [ ] **Step 1: Write the failing tests** in `test_skill_guidance.py`:
  - `test_every_skill_using_a_setting_reads_settings_first`: a table of skill → keys.
  - `test_cap_is_one_setting_stated_in_house_rules`: house-rules names `PROOFS_COST_CAP_USD` and "estimate". No SKILL.md states a dollar amount except as "default $5".
  - `test_where_the_page_goes_has_no_claude_md_fallback`: the string "proofs pages: file" appears nowhere.
  - `test_design_review_option_count_and_passes_read_settings`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_skill_guidance -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Edit** the files above.
- [ ] **Step 4: Run** `tests.test_skill_guidance`, `tests.test_command_forms` and `bin/check-skills`. Expected: PASS.
- [ ] **Step 5: Commit** the listed files, with the message "settings: skills read the settings instead of literal numbers".

### Task 4: Send stays off until something is answered

**Files:**
- Modify: `shared/review_page/engine.js` (`sendCheck`, lines 836–849, and the hook that re-runs it after every saved change)
- Test: `tests/test_send_to_claude.py`, plus `shared/review_page/smoke.cjs` if its Send states need the new case

**Interfaces:**
- Produces: `SEND_WHY.none = "Answer something first: Send sends your saved answers."`. `answeredCount(S, st) -> int`, the same count `sendText` uses.

- [ ] **Step 1: Write the failing tests:**
  - `test_send_off_with_nothing_answered`: the button is visible and disabled, and the line shows `SEND_WHY.none`.
  - `test_send_turns_on_after_first_answer_saved`: it turns on once at least one answer is saved and the bar says Saved.
  - `test_clearing_the_last_answer_turns_it_off_again`.
  - `test_anything_else_alone_counts`: text in the "Anything else" box alone counts as an answer.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_send_to_claude -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** `sendCheck` disables the button when `answeredCount === 0` (with the "Anything else" box empty), even if `canSendToClaude()` is available. Re-run `sendCheck` on every state change.
- [ ] **Step 4: Run** `tests.test_send_to_claude` and `tests.test_sync_indicator`. Expected: PASS.
- [ ] **Step 5: Commit** `shared/review_page/engine.js tests/test_send_to_claude.py` (and `smoke.cjs` if it was touched), with the message "Send to Claude: off until something is answered".

### Task 5: The settings page (layout B)

**Files:**
- Modify: `shared/review_page/review_page.py` (mode `settings`: validate the spec, render, check, `--answers`), `shared/review_page/engine.js` (section kind `settings`), `shared/review_page/style.css` (the layout B styles, ported from `mock.css` and renamed from `sx-` to `rp-set-`), `shared/review_page/smoke.cjs` (clicking through the settings mode), `shared/settings.py` (`--spec`, which prints a builder spec of the effective settings)
- Create: `shared/review_page/examples/settings.json`
- Test: `tests/test_settings_page.py`

**Interfaces:**
- Consumes: `effective()` and `validate` rules (Task 1), and the Send gating (Task 4).
- Produces:
  - Spec `{"mode": "settings", "project": {…}, "version", "settings": [<the table row + value, source, note>], "send_wait_ms"}`.
  - The answer row (kind `setting`): `{id: KEY, section: "settings", kind: "setting", answer: "<new raw value>" | null, from: "<value shown>", scope, note: "", updated_at}`.
  - The export line: `SET KEY=VALUE (scope; was OLD)`.
  - `--answers PAGE --rows DIR` prints the same lines.

Layout as picked in the mockup:
- A sticky save bar at the top: "N changes not saved yet", one "Label old → new" per change, Copy, and Send to Claude, the only primary.
- A sidebar of the five groups, each with its count and a dot when one of its settings is changed or pending, and a search box above it that filters the rows across all groups.
- The pane shows one group: its title as an h1, then a line saying where it is saved and in which file.
- The group's main rows, then an "Advanced" heading over its advanced rows, with no per-row Advanced tag.
- A row is a label, the help, then a status line: "Changed · default X · Reset", or "Not saved · was X" with an amber left rule.
- The control by type: a number box with its unit; a segmented choice; a switch for `bool`; a mono text box for text, list and path; an auto value with Change.
- The "Fixed on purpose" note, from the KEEP FIXED list.
- Below 720 px: the sidebar stacks above the pane, and segmented controls span the full width.
- Light and dark from the `--rp-*` tokens. The proofs wordmark with a `settings` pill.

**Validation on the page** mirrors `validate`. A refused value shows its reason under the field, in the deny color, and is left out of the pending list and the saved row.

- [ ] **Step 1: Write the failing tests** in `tests/test_settings_page.py`:
  - `test_spec_from_settings_py_builds_and_checks`.
  - `test_every_table_key_has_one_row`.
  - `test_groups_and_counts_match_the_table`.
  - `test_raise_only_field_refuses_lower_value_with_reason` (node, via the engine).
  - `test_pending_change_shows_in_save_bar_and_saves_row_with_from`.
  - `test_reset_writes_default_as_answer`.
  - `test_export_and_answers_print_SET_lines`.
  - `test_search_filters_across_groups`.
  - `test_smoke_settings_page_clean`: `--smoke` reports no problems at 1280 and 390, every tap ≥ 44, no sideways scroll.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_settings_page -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the mode, the engine kind, the CSS, `--spec` and the example.
- [ ] **Step 4: Run** `tests.test_settings_page`, `tests.test_review_page` and `tests.test_answers_db`, then build `examples/settings.json` with `--smoke`. Expected: PASS and `problems: []`.
- [ ] **Step 5: Commit**, with the message "settings page: layout B review-page mode".

### Task 6: The settings skill, docs and release

**Files:**
- Create: `skills/settings/SKILL.md`, `reference/settings.md` (every key: what it does, its default and range, its scope, its file)
- Modify: `shared/settings.py` (`--apply ROWS_DIR`: applies saved rows, skipping stale ones), `README.md` (a status-table row for settings, and how to open it), `CHANGELOG.md`, `.claude-plugin/plugin.json` and whatever `bin/bump-version` updates to 1.9.0
- Test: `tests/test_settings.py` (apply), `tests/test_check_skills.py` / `bin/check-skills`

**Interfaces:**
- Consumes: everything above.
- Produces: `settings.py --apply DIR [--dry-run]`. It reads the `proofs-answers` rows of kind `setting` and applies each with `set_value`. It skips, and lists, a row whose `from` differs from the current value or whose value fails `validate`. It prints `APPLIED KEY old → new (scope file)` and `SKIPPED KEY: reason`. Exit 0 when everything applied, 1 when any row was skipped.

What the skill does:
1. On "open Proofs settings" (or `/proofs:settings`): `settings.py --spec` to `.proofs/settings/spec.json`, build, `--smoke`, publish as an artifact with `db` and `comments`. On a later open, republish to the same file path.
2. On a Send: list `proofs-answers`, run `--apply --dry-run`, then `--apply`, then rebuild from `--spec` and republish **first**. Show every applied and skipped line in chat. Never post a second reply in the thread; resolve the thread.
3. Write only `PROOFS_*` env keys. Never touch permissions.

Note that this skill is new surface under the feature freeze. The owner approved the settings page itself (plan L), so the skill is just its entry point.

- [ ] **Step 1: Write the failing tests:**
  - `test_apply_applies_and_reports`.
  - `test_apply_skips_stale_from_and_invalid`, exit 1, with the file unchanged for the skipped keys.
  - `test_apply_dry_run_writes_nothing`.
  - `test_settings_skill_passes_check_skills`.
  - `test_reference_lists_every_key`.
- [ ] **Step 2: Run** the tests. Expected: FAIL.
- [ ] **Step 3: Implement** `--apply`, and write `SKILL.md`, the reference, the README row and the CHANGELOG entry. Run `bin/bump-version 1.9.0`.
- [ ] **Step 4: Run the full gate** (Global Constraints). Expected: everything green.
- [ ] **Step 5: Commit**, with the message "Proofs 1.9.0: settings page and one settings source". Push `feat/settings`. Do not merge: the controller gates it again and merges.
