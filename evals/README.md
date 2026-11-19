# Skill trigger evals

Does the right skill fire for a real request, and does it stay quiet when a sibling
is the right one? 36 cases, run with `claude plugin eval`:

- **fire-<skill>-1, -2:** two everyday requests that should fire that skill.
- **miss-<skill>:** a near miss meant for its nearest sibling (questions vs
  qa-checklist, design-review vs visual-qa, pr-qa vs visual-qa, todos vs
  review-cycle, …). It passes only if the sibling fires and this skill does not.

The cases are generated from `make_cases.py`; edit `CASES` there and rerun it rather
than editing the folders by hand.

```bash
python3 evals/make_cases.py
claude plugin eval . --ablation none -j 6 --no-publish
```

`--ablation none` because the score here is which skill fired; a no-plugin arm has
no skills to fire. Each case runs 3 times. `results/` is ignored by git.

## Last run

2026-11-19, Claude Code 2.1.311: **108 of 108 runs passed**: every skill 6 of 6 on
its own requests and 3 of 3 on its near miss. 3 min 14 s at `-j 6`.
