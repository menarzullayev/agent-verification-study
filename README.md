# Agent verification study

Does a verifier that is **shown** a reply miss more errors than one that is **not**?
A small offline measurement of a verification stage for LLM-written replies, with the analysis rule fixed before the data was collected.

**Status:** finished, small sample. Read the limits before the numbers.

## Result in short

- On corrupted replies, the verifier that sees the reply caught **every** injected error of three kinds
  (a changed final answer, a changed statement, a wrong value carried through steps and answer): **36 of 36**, with **0 of 24** false alarms on unmodified replies.
- The hypothesis "seeing the reply makes the verifier miss more errors" was **not supported**.
  In the second run the comparison with the blind verifier **could not be interpreted**, because the blind side failed its own validity gate (3 of 12 controls flagged, limit 2).
- The one place the verifier seemed to miss errors, intermediate steps (9 of 12), turned out to be mostly a measurement artifact: all three misses were in problem-number headings, not in computation steps. This was found after the result and is **not re-measured**.
- Much of the value is in how the instrument failed. Five pilots each found a defect in the harness before the measurement was usable (see below).

## Results

Run 1 ([DECISION-002](docs/decisions/DECISION-002-full-verify-measurement.md)): 96 calls, 0 errors, $5.58, 48 cases.

| Condition | Controls flagged | final | statement | step |
|---|---|---|---|---|
| A: verifier sees the reply | 0/12 | 12/12 | 12/12 | 9/12 |
| B: blind verifier | 6/12 | 12/12 | 11/12 | not measurable |

Paired on final + statement (24 pairs): A 1.00, B 0.96, B−A −0.04, exact McNemar p = 1.000. Hypothesis not supported.

Run 2 ([DECISION-003](docs/decisions/DECISION-003-consistent-error-test.md)): 48 calls, 0 errors, $2.07, a wrong value that is *consistent* through steps and answer.

| Condition | Controls flagged | consistent |
|---|---|---|
| A | 0/12 | 12/12 |
| B (value-based comparator) | 3/12 | 12/12 |

B's validity gate failed (3/12 is above 20%), so the pre-registered verdict is **not interpretable**.
Diagnostic: one flag came from an extra number in explanatory text (comparator), two from run-to-run variance of the blind model.

## What this does not show

- Nothing about verifiers in general. One model family does both the solving and the verifying, one domain (short numeric maths tasks), synthetic errors, **12 cases per cell**.
- A catching 100% of these errors is a ceiling, not proof that anchoring cannot happen. Harder, realistic errors (for example a misread image shared by the solver and the checker) were not tested.
- The blind verifier's comparison is two changes at once (no reply shown, and a code comparator instead of a model), so a difference between A and B has two possible causes.
- Deleted numbers in a statement, and errors in steps for the blind verifier, are not measured.

## How the instrument failed

Each item was found by running the harness on real data and reading the result, then fixed with a test:

1. Chat context and the author's recent photos were missing, so a task posted in an earlier message reached the verifier as unreadable.
2. Proofs and how-to questions have no number to compare; the blind side flagged every one. They are now excluded.
3. A task's own number ("79. ...") was treated as part of the task.
4. A decimal ("3.5") was cut as if it were numbering.
5. The first error kind used up the whole pool, leaving none for the others (round-robin now).
6. A summarised statement compared with a verbatim reading produced false alarms (only a substitution counts now).
7. `11/10` and `1,1` counted as different numbers (post-hoc fix, disclosed).

## Use it with your own cases

Requires the `claude` CLI on the path. A measured call costs about $0.07 and takes about 18 seconds.

```
python -m verify_study plan   --cases examples/cases.sample.json --n-inject 3 --n-control 1 --seed 1
python -m verify_study run    --condition both
python -m verify_study report
python -m unittest discover -s tests          # no network, no model calls
```

A case is a JSON object:

```json
{"case": "id", "kind": "task", "problem_statement": "x + 12 = 20", "final_answer": "8",
 "message": "**Shart.** x + 12 = 20 ni yeching.\n\nQadam: x = 20 - 12 = 8.\n\n## Javob\n\n$8$",
 "chat_text": "<chat>...</chat>", "images": [], "language": "uz"}
```

`message` is split into blocks by blank lines. The error injector relies on the layout of the original system's replies: a first block that starts with `**Shart.**` (the statement), steps in between, and the answer last.
Error kinds: `final`, `step`, `statement`, `consistent`.

## Safety boundary

The measurement module calls `llm.run` (headless `claude -p` with tools disabled) and nothing else; it sends nothing anywhere and writes only into the output directory.
A test reads the module source and fails if it mentions a client, a send, or a database write.

## Provenance

The harness was first built inside a private repository for a Telegram study-group assistant, and the cases come from that assistant's saved jobs.
**That data is not published and cannot be.** The decision files were committed before each run there; third parties cannot verify the commit order, so treat the "fixed in advance" statements as the author's account.
`verify_study/adapters/tg_solver.py` documents how the cases were rebuilt.
The verifier prompt in `verify_study/prompts/` is the one used in the measurement.

## Layout

```
verify_study/eval.py          harness: numbers, injection, plan, conditions, metrics, paired analysis, CLI
verify_study/llm.py           headless Claude call with structured output
verify_study/adapters/        how cases were rebuilt from the private assistant's data (documentation)
verify_study/prompts/         verifier and blind-solver prompts
docs/decisions/               DECISION-001..003: question, options, rule, result, limits
tests/test_eval.py            offline tests, including negative tests for every rule
examples/cases.sample.json    synthetic cases (made up)
```

## License

MIT. See `LICENSE`.
