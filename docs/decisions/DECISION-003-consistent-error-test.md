> Provenance: this decision was written in the private repository where the harness was first
> built (a Telegram study-group assistant). Names of groups and people never entered it. The
> dates are the dates of writing; third parties cannot verify the commit order of that repository.

# DECISION-003: test H1 with consistent (propagated) errors

Date: 2026-11-08
Status: accepted (owner chose Variant A)
Follows: DECISION-002

## Question
DECISION-002 could not test H1: its `final` errors made the reply contradict itself, which any
reader sees (A caught 12/12). Which error type tests whether seeing the reply makes the verifier
miss errors?

## Options considered
| Option | Summary | Trade-off |
|---|---|---|
| **A. Consistent (propagated) error (chosen)** | The final answer's number is changed everywhere it appears after the statement (steps and answer). | Synthetic; the arithmetic in the steps becomes wrong but the text agrees with itself. |
| B. Model-written subtle wrong solution | Another model rewrites the reply with one plausible mistake. | Most realistic; a generator model enters the experiment; costlier. |
| C. Accept DECISION-002 and stop | Report "H1 not supported". | The ceiling effect stays; "no anchoring" would be an unsafe conclusion. |
| D. Fix only B's comparator | Re-measure B. | The main test of H1 is not done. |

## Decision
A. New kind `consistent`: take the first number of the final answer that is at least 3 (digits 0-2 are
mostly structure: indices, exponents, coefficients; changing them everywhere would rewrite the text, not
a value; refined on 2026-11-08 BEFORE any run of this kind), change it, and replace every
whole-number occurrence of it in all blocks after the statement block and in the stored final
answer. Skipped when it occurs in fewer than two of those blocks (then it is not "carried through").

## Post-hoc revision (disclosed)
B's comparator is changed AFTER seeing DECISION-002's data: fractions and decimals are compared as
values (`11/10` = `1,1`), because B's 6/12 false alarms on controls came from that. B's earlier
cells are not re-scored (raw model outputs were not stored); B's control false-alarm rate is
re-measured in this run.

## Analysis rule (fixed BEFORE the run)
- Cells: `consistent` (12 cases) and `control` (12 cases, disjoint), conditions A and B on the same
  cases, 48 calls.
- **Validity gate:** the A-vs-B comparison is interpretable only if B's false alarms on controls are
  at most 20 percent (2 of 12). Otherwise the verdict is "NOT INTERPRETABLE" and H1 is not tested.
- H1 supported only if the gate passes AND (detection B - detection A) >= 0.15 AND exact two-sided
  McNemar p < 0.10 on the 12 `consistent` pairs. With 12 pairs this needs B to catch at least 5
  cases that A misses (and A none).
- Otherwise reported as NOT SUPPORTED (includes inconclusive). Errored pairs are counted as left out.

## Affected components
`tools/verify_eval.py` (kind, comparator, `--kinds`, gate), `tests/test_verify_eval.py`.
Untouched: `tgsolver/`.

## Limits
Synthetic; 12 per cell; one domain; one model family; the carried-through arithmetic is wrong in
the steps, which a careful verifier can recompute: that is the point of the test, not a flaw.

## Result (2026-11-08), rule and gate unchanged
48 calls, 0 errors, $2.07, 24 cases (12 consistent + 12 controls, disjoint).

| Condition | Control (false alarm) | consistent |
|---|---|---|
| A (sees the reply) | 0/12 | 12/12 (95% CI 0.76-1.00) |
| B (blind, value-based comparator) | 3/12 (25%) | 12/12 |

**B validity gate FAILS** (3/12 = 25% > 20%), so the pre-registered verdict is
**H1: NOT INTERPRETABLE**. The paired numbers (B-A = 0.00, p = 1.000) are not used as evidence.

## What the gate failure was (diagnostic, not a re-score)
The three flagged controls were re-run once. Case 1: the answers agree in substance; the blind
answer adds an explanatory "98%", and an extra number counts as a difference (comparator).
Cases 2 and 3: on the re-run the blind answer agrees with the saved one, so the first-run
disagreement was run-to-run variance of the blind model. All three replies had been sent; nothing
here shows an incorrect sent reply. The value-based comparison halved B's control false alarms
compared with DECISION-002 (6/12 to 3/12), on different case sets.

## What can be said
- A is valid on its own: 0/12 false alarms, 12/12 detection of consistent errors, 12/12 and 12/12 on
  `final` and `statement` (DECISION-002). A recomputes the arithmetic, so a self-agreeing wrong
  value does not slip through on this data.
- H1 is therefore not supported on any tested error kind: A has no misses to compare against B,
  independent of B's validity (A is at 100% on three kinds).
- A's only observed weakness is `step`: 9/12 (DECISION-002), a wrong intermediate value with a
  correct final answer.
- Limits unchanged: synthetic errors, n = 12 per cell, one domain, one model family; B's
  usable comparison needs repeated sampling and a comparator that ignores explanatory numbers.
