> Provenance: this decision was written in the private repository where the harness was first
> built (a Telegram study-group assistant). Names of groups and people never entered it. The
> dates are the dates of writing; third parties cannot verify the commit order of that repository.

# DECISION-001: verify measurement runs offline, never against the live service

Date: 2026-11-08
Status: accepted (owner chose Variant A)

## Question
How is the detection rate of the independent `verify` stage measured, given that the service is
live (`live = True`) and replies go out in the owner's name?

## Options considered
| Option | Summary | Trade-off |
|---|---|---|
| **A. Offline harness (chosen)** | A tool under `tools/` replays saved jobs, injects known errors, calls `llm.run` only. | Synthetic errors, not the live distribution. No risk to live replies. |
| B. Make `verify` blind in production now | Verifier never sees the reply; Python compares final answers. | Change without a measurement; live reply quality at risk. |
| C. Shadow mode in production | Blind verifier runs beside the real one and only logs. | Extra opus call per job; touches live code. |
| D. Do nothing | Keep the plan on paper. | The stated intention to measure stays unfulfilled. |

## Decision
A. The harness reads `~/.tg-solver` read-only, never imports the Telegram client, never writes to
`state.db`, and never sends anything. A production change to `verify` (B or C) is a later decision
that needs the harness result first.

## Why
- Ground truth does not exist in the saved data: 75 stored verdicts (71 correct, 3 incorrect,
  1 unsure) only mean "a second call agreed". Injected errors give a known answer key.
- Today `verify` is shown the proposed reply (`prompts/verify.md`, `service.process`), and both
  solve and verify run on `opus`. Whether that lets errors through is the open question.

## Affected components
- New: `tools/verify_eval.py`, `tests/test_verify_eval.py`, `prompts/verify_blind.md`.
- Untouched: `tgsolver/` (service, store, llm, prompts used in production).

## Known limits (must be repeated with any result)
- Errors are synthetic; the sample is small; one domain (maths tasks in Uzbek); one model family.
- Condition B changes both the input (no reply) and the comparator (code, not a model), so a
  difference between A and B has two causes.
- B cannot see intermediate steps by construction; it can only catch final-answer and statement
  errors.

## Harness validation pilots (2026-11-08): NOT the experiment
Five small pilots on the saved jobs were used to validate the harness, and each found a defect
that was fixed (tests 249 -> 288): missing chat context and images, non-numeric tasks (proofs,
how-to questions), a task-number prefix, decimal numbering cut as numbering, plan starvation across
error kinds, and a reading comparator that flagged a summarised statement.

Last pilot (9 cases, 18 calls, 0 errors, $1.32, 5.4 minutes, about $0.07 and 18 s per call):

| Condition | Control (false alarm) | final | statement | step |
|---|---|---|---|---|
| A (sees the reply) | 0/3 | 2/2 | 2/2 | 1/2 |
| B (blind) | 0/3 | 2/2 | 2/2 | not measurable* |

\* B never sees the steps, so a flag on a step case is an unrelated disagreement (it flagged 2 of 2).

n is 2-3 per cell: this validates the tool, it is not evidence about the verifier. The one A miss
is a single case.

Eligible data: 50 saved jobs (numeric answer, no drawing, no earlier answers). The designed
60 injected + 30 control is not possible; the data supports 12 per error kind + 12 controls
(96 calls, about $7, about 30 minutes).
