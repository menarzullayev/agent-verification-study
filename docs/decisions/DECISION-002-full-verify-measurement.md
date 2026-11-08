> Provenance: this decision was written in the private repository where the harness was first
> built (a Telegram study-group assistant). Names of groups and people never entered it. The
> dates are the dates of writing; third parties cannot verify the commit order of that repository.

# DECISION-002: run the full verify measurement now, 12 controls + 12 per error kind, A and B

Date: 2026-11-08
Status: accepted (owner chose Variant A)
Follows: DECISION-001

## Question
How is the measurement run, given 50 eligible saved jobs and a measured cost of about $0.07 and
18 s per call?

## Options considered
| Option | Summary | Trade-off |
|---|---|---|
| **A. Full run now (chosen)** | 12 controls + 12 each of final / step / statement, conditions A and B on the same cases. 96 calls, about $7, about 30 minutes. | n = 12 per cell: wide intervals (about +-20-25 points). |
| B. Condition A only, 50 jobs x 3 kinds | About 150 calls, about $11. | No A-vs-B comparison. |
| C. Wait for more jobs | No cost now. | The essay's "no results yet" stays. |
| D. Improve B's comparator first | A model compares answers. | B stops being a simple code check. |

## Analysis rule (fixed BEFORE the run, so the result cannot choose its own test)
- Cases are paired: A and B see the same corrupted case.
- Primary comparison: kinds `final` and `statement` pooled (24 injected cases). `step` is reported
  for A only; B cannot see steps (labelled not measurable in the report).
- H1 (the owner's hypothesis): a verifier that sees the reply (A) misses more errors than a blind
  one (B). H1 is **supported** only if both hold: (detection B - detection A) >= 0.15 on the pooled
  cells, and the exact two-sided McNemar test on the discordant pairs gives p < 0.10.
- Anything else is reported as **not supported** (including "inconclusive"), never as "no
  difference".
- False alarms on controls are reported for both conditions and are not hidden behind detection.
- Failed calls are counted and reported; a cell with errors is flagged, not silently shrunk.

## Why
- The pilots validated the tool; they say nothing about the verifier (n = 2-3 per cell).
- 12 per cell is the most the data supports; waiting costs the essay its first real number.

## Affected components
- `tools/verify_eval.py` (paired report), `tests/test_verify_eval.py`.
- Untouched: `tgsolver/`. Output: `~/.tg-solver/eval-verify/` (outside the repository, private data).

## Limits (repeated with the result)
Synthetic errors; 12 per cell; one domain (numeric maths tasks in Uzbek); one model family; B
differs from A in input and in comparator; deletions of a number from the statement are not
measured; step errors are measured for A only.

## Result (2026-11-08), analysis rule unchanged
96 calls, 0 errors, $5.58 (estimate was $7), 48 cases (57 eligible saved jobs).

| Condition | Control (false alarm) | final | statement | step |
|---|---|---|---|---|
| A (sees the reply) | 0/12 | 12/12 | 12/12 | 9/12 (95% CI 0.47-0.91) |
| B (blind) | 6/12 | 12/12 | 11/12 | not measurable* |

\* B never sees steps; its 6/12 on step cases is unrelated disagreement.

Paired, final + statement, 24 pairs: A 1.00, B 0.96, B-A -0.04, only-B-caught 0, only-A-caught 1,
exact McNemar p = 1.000. **H1 is NOT SUPPORTED** (rule: B-A >= 0.15 and p < 0.10).

## Reading the result (limits that must travel with it)
- **Ceiling effect.** The `final` corruption changes only the answer block while the steps keep the
  old value, so the reply contradicts itself and any reader sees it. A consistent wrong value
  (steps and answer agree) was not tested; that is the case where seeing the reply could anchor
  the verifier.
- **A missed 3 of 12 `step` errors** (a wrong intermediate value with a correct final answer). n = 12.
- **B's 6/12 false alarms are a comparator weakness, not a verifier verdict**: numbers are compared as
  tokens, so `11/10` and `1,1` differ, and a verbatim blind reading differs from a summarised saved
  statement. B is not interpretable until the comparator is fixed; any such change made after seeing
  this result is a post-hoc revision and must be disclosed as one.
- Synthetic errors, n = 12 per cell, one domain, one model family, as before.

## Next
The design weakness (easy, self-contradicting errors) is the highest-dependency issue: see DECISION-003.

## Addendum (2026-11-08, post-hoc): where the three `step` misses landed
After the result, the three cases A missed were located by diffing the original and the corrupted
reply. All three corruptions landed in problem-number headings of multi-problem replies (for example
"**4. ...**"), not in a computation step. A not flagging a changed heading number is reasonable, so
the `step` cell mixes two things: injections that hit a computation (A caught 9 of 9) and injections
that hit a heading (A caught 0 of 3).

This reclassification was made after seeing the result and has not been re-measured; the reported
9/12 stays the pre-registered figure. A `step` injection that skips headings is an open follow-up.
