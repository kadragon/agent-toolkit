# One-time FSRS Upgrade Offer

Moved out of SKILL.md *Running a round → step 1*. Applies only when `status` reports `fsrs_available: false` and `fsrs_notice_seen: false`.

**Offer the FSRS upgrade once.** `status` also reports `fsrs_available`. If it's `false` and
`fsrs_notice_seen` is `false`, the script is running on the SM-2 fallback — tell the user, one
time, that installing FSRS gives measurably better scheduling (fewer reviews for the same
retention) and offer to install it before the round:

> 📈 지금은 SM-2 스케줄러로 진행 중입니다. FSRS(`py-fsrs`)를 설치하면 같은 암기 효과에
> 리뷰 횟수가 줄어듭니다. 설치할까요? — `python3 -m pip install --user fsrs`

Install into **the same interpreter that runs the quiz** so `import fsrs` will resolve —
derive it from the `python`/`python3` you invoke `$Q` with (e.g. `<that-python> -m pip install
--user fsrs`; on an externally-managed environment add `--break-system-packages`, or use the
user's venv/`uv pip install fsrs`). This needs the user's go-ahead — installing a package is
their call, so ask, don't run it silently. After they install, no code change is needed: the
next `status`/`record` picks FSRS up automatically. Whether they install or decline, mark the
notice so you don't nag next time, then proceed with the round either way:

```sh
Q=<dir-of-the-repo-quiz-SKILL.md>/scripts/quiz_state.py
python3 "$Q" --repo <repo-root> config --seen-fsrs-notice
```

If `fsrs_available` is already `true`, skip all of this — FSRS is in use.
