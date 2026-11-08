"""Offline measurement of a verification stage (see docs/decisions/).

Question: does the verifier catch a known error, and does it catch more of them when it is NOT
shown the proposed reply?

Safety boundary: this module calls `llm.run` (claude -p with tools disabled) and nothing else.
It sends nothing anywhere and writes only into the output directory. tests/test_eval.py enforces
that by reading this file.

    python -m verify_study plan   --cases cases.json --n-inject 36 --n-control 12 --seed 1
    python -m verify_study run    --condition both --limit 6
    python -m verify_study report
"""
import argparse
import json
import math
import random
import re
import sys
from fractions import Fraction
from pathlib import Path

from . import llm
from .schemas import CHECK_IN, VERIFY_SCHEMA, load_prompt

KINDS = ("final", "step", "statement")
ALL_KINDS = KINDS + ("consistent",)          # DECISION-003: a wrong value carried through steps and answer
BLIND_SCHEMA = {"type": "object", "required": ["task_as_read", "independent_answer", "confidence"],
                "properties": {"task_as_read": {"type": "string"}, "independent_answer": {"type": "string"},
                               "confidence": {"type": "number"}}}
NUM = re.compile(r"\d+(?:[.,]\d+)?")
FORBIDDEN = ("McpClient", "Service(", "send_answer", "download_media", "delete_message",
             "INSERT ", "UPDATE ", "DELETE ", "subprocess")


# ---------- numbers ----------
VALUE = re.compile(r"\\frac\s*\{(\d+)\}\s*\{(\d+)\}|(\d+)\s*/\s*(\d+)|(\d+(?:[.,]\d+)?)")


def numbers(text):
    """Numeric values of a text as Fractions, in order: 11/10, \\frac{11}{10} and 1,1 are all 11/10
    (DECISION-003: B's comparator counted them as different numbers). Superscripts and signs are
    ignored on both sides."""
    out = []
    for m in VALUE.finditer(text or ""):
        a, b, c, d, e = m.groups()
        num, den = (a, b) if a else ((c, d) if c else (None, None))
        if num is not None:
            if int(den) == 0:
                continue
            out.append(Fraction(int(num), int(den)))
        else:
            out.append(Fraction(e.replace(",", ".")))
    return out


NUMBERING = re.compile(r"^\s*(?:№\s*)?\d+(?:\.\d+)*\s*(?:-\s*(?:masala|mashq|misol|topshiriq)\s*)?[.):](?!\d)\s*")


def strip_numbering(text):
    """Drop the task's own number ('79. ...', '2.8. ...'): it is not part of the task."""
    return NUMBERING.sub("", text or "", count=1)


def numeric_answer(final_answer, limit=80):
    """True for a short final answer that is made of numbers. Proofs, how-to questions and long
    prose answers cannot be compared by numbers, so the experiment leaves them out."""
    return bool(numbers(final_answer)) and len(final_answer or "") <= limit


def number_diff(blind, saved):
    """Numbers present in only one of two texts, as strings: {'only_blind': [...], 'only_saved': [...]}."""
    from collections import Counter
    cb, cs = Counter(map(str, numbers(blind))), Counter(map(str, numbers(saved)))
    return {"only_blind": sorted((cb - cs).elements()), "only_saved": sorted((cs - cb).elements())}


def agree(a, b):
    """Two texts say the same thing when they hold the same numbers (as a multiset); with no
    numbers at all, when the stripped lower-case text is equal."""
    na, nb = numbers(a), numbers(b)
    if na or nb:
        return sorted(na) == sorted(nb)
    return (a or "").strip().lower() == (b or "").strip().lower()


def bump(token):
    """A different number of the same shape: 12 -> 13, 0.5 -> 0.6, 9 -> 10."""
    if re.search(r"[.,]", token):
        sep = "." if "." in token else ","
        whole, frac = token.split(sep)
        last = str((int(frac[-1]) + 1) % 10)
        return whole + sep + frac[:-1] + last
    return str(int(token) + 1)


# ---------- error injection ----------
def split_blocks(message):
    return message.split("\n\n")


def replace_token(text, old, new, last=False):
    """Replace one whole-number occurrence of `old` (so 8 never matches inside 28); None if absent."""
    hits = [m for m in NUM.finditer(text) if m.group() == old]
    if not hits:
        return None
    m = hits[-1] if last else hits[0]
    return text[:m.start()] + new + text[m.end():]


def replace_all_tokens(text, old, new):
    """Every whole-number occurrence of `old` replaced (8 never matches inside 28)."""
    return NUM.sub(lambda m: new if m.group() == old else m.group(), text)


def inject(case, kind):
    """Return a corrupted copy of the case (reply, final answer, statement) or None when the
    reply has no number to corrupt for this kind. The answer key is recorded in 'injected'."""
    msg, fin, stmt = case["message"], case["final_answer"], case["problem_statement"]
    blocks = split_blocks(msg)
    if kind == "consistent":
        # the first number of the final answer is changed everywhere after the statement block, steps
        # and answer alike: the reply agrees with itself and only the arithmetic is wrong
        j = next((i for i, b in enumerate(blocks) if b.lstrip().startswith("**Shart")), None)
        tail = list(range(0 if j is None else j + 1, len(blocks)))
        # digits 0-2 are mostly structure (indices, exponents, "2x"): changing them everywhere would
        # rewrite the text, not a value, so the corrupted number is the first one that is at least 3
        toks = [t for t in NUM.findall(fin) if Fraction(t.replace(",", ".")) >= 3]
        if not toks or not tail:
            return None
        old = toks[0]
        new = bump(old)
        carried = [i for i in tail if any(m.group() == old for m in NUM.finditer(blocks[i]))]
        if len(carried) < 2:                         # not carried through a step: that is a `final` error
            return None
        for i in tail:
            blocks[i] = replace_all_tokens(blocks[i], old, new)
        msg = "\n\n".join(blocks)
        fin = replace_all_tokens(fin, old, new)
    elif kind == "final":
        toks = NUM.findall(fin)
        if not toks:
            return None
        old = toks[0]
        new = bump(old)
        changed = replace_token(msg, old, new, last=True)
        if changed is None:
            return None
        msg = changed
        fin = replace_token(fin, old, new)
    elif kind == "step":
        fin_tokens = set(NUM.findall(fin))
        idx = [i for i, b in enumerate(blocks[1:-1], 1)
               if not b.lstrip().startswith("**Shart") and NUM.search(b) and not (set(NUM.findall(b)) <= fin_tokens)]
        if not idx:
            return None
        i = idx[len(idx) // 2]
        old = [t for t in NUM.findall(blocks[i]) if t not in fin_tokens][0]
        new = bump(old)
        blocks[i] = replace_token(blocks[i], old, new)
        msg = "\n\n".join(blocks)
    elif kind == "statement":
        # the statement often starts with the task's own number ("79. ..."), which the **Shart.**
        # block leaves out: only a number that the reply's statement block really contains is corrupted
        j = next((i for i, b in enumerate(blocks) if b.lstrip().startswith("**Shart")), None)
        if j is None:
            return None
        toks = [t for t in NUM.findall(stmt) if t in NUM.findall(blocks[j])]
        if not toks:
            return None
        old = toks[0]
        new = bump(old)
        s2, b2 = replace_token(stmt, old, new, last=True), replace_token(blocks[j], old, new, last=True)
        if s2 is None or b2 is None:
            return None
        stmt, blocks[j] = s2, b2
        msg = "\n\n".join(blocks)
    else:
        raise ValueError(kind)
    out = dict(case, message=msg, final_answer=fin, problem_statement=stmt)
    out["injected"] = {"kind": kind, "old": old, "new": new}
    return out


def build_plan(cases, n_inject, n_control, seed, kinds=KINDS):
    """Disjoint controls and injected cases; injected cases are spread over the given error kinds."""
    rng = random.Random(seed)
    pool = cases[:]
    rng.shuffle(pool)
    per_kind = max(1, n_inject // len(kinds))
    got, injected, used = {k: 0 for k in kinds}, [], set()
    progress = True
    while progress:                                   # round-robin: no kind can use up the whole pool
        progress = False
        for kind in kinds:
            if got[kind] >= per_kind:
                continue
            for c in pool:
                if c["case"] in used:
                    continue
                bad = inject(c, kind)
                if bad:
                    injected.append(bad)
                    used.add(c["case"])
                    got[kind] += 1
                    progress = True
                    break
    controls = [dict(c, injected=None) for c in pool if c["case"] not in used][:n_control]
    return controls + injected


# ---------- conditions ----------
def verify_input(case):
    return (f"{case['chat_text']}\n\nMode: {case['kind']}\n<solution>\nTask as read: {case['problem_statement']}\n"
            f"Final answer: {case['final_answer']}\n\n{case['message']}\n</solution>\n\n"
            "No drawing accompanies this reply; set figure_ok to true and bad_figures to [].")


def condition_a(case, model, timeout, call=llm.run):
    """Today's verifier: it is shown the proposed reply."""
    v = call(model, load_prompt("verify") + CHECK_IN.get(case["language"], ""), verify_input(case),
             VERIFY_SCHEMA, case["images"], timeout)
    return {"detected": v["verdict"] != "correct" or v.get("statement_matches", True) is False,
            "verdict": v["verdict"]}


def condition_b(case, model, timeout, call=llm.run):
    """Blind verifier: sees only the chat; Python compares its answer and its reading with the reply's."""
    v = call(model, load_prompt("verify_blind"), case["chat_text"], BLIND_SCHEMA, case["images"], timeout)
    answer_ok = agree(v["independent_answer"], case["final_answer"])
    blind_read, saved_read = strip_numbering(v["task_as_read"]), strip_numbering(case["problem_statement"])
    diff = number_diff(blind_read, saved_read)
    # the saved statement is a summary and the blind reading is verbatim (pilot 4: 28 extra numbers on
    # one side), so only a SUBSTITUTION counts: a number the other side lacks on BOTH sides (4 -> 3).
    # A number dropped or added on one side only is not flagged; this tool does not measure that.
    reading_ok = not (diff["only_blind"] and diff["only_saved"])
    return {"detected": v["independent_answer"] != "UNREADABLE" and not (answer_ok and reading_ok),
            "unreadable": v["independent_answer"] == "UNREADABLE", "answer_ok": answer_ok, "reading_ok": reading_ok,
            # numbers only (never the task text): which numbers differ when the readings disagree
            "reading_diff": diff}


CONDITIONS = {"A": condition_a, "B": condition_b}

# cells that must never be read as a detection rate: B never sees the steps, so a flag on a step case
# is an unrelated disagreement (pilot 5: 2 of 2 step cases flagged, neither through the injected step)
NOT_MEASURABLE = {("B", "step"): "not a detection rate: B never sees the steps; counts unrelated disagreement"}


# ---------- metrics ----------
def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def summarize(results):
    """results: list of {condition, injected(kind or None), detected, error}. Errors are counted, not hidden."""
    out = {}
    for r in results:
        key = (r["condition"], r["injected"] or "control")
        s = out.setdefault(key, {"n": 0, "detected": 0, "errors": 0})
        if r.get("error"):
            s["errors"] += 1
            continue
        s["n"] += 1
        s["detected"] += 1 if r["detected"] else 0
    for s in out.values():
        s["rate"] = s["detected"] / s["n"] if s["n"] else None
        s["ci95"] = wilson(s["detected"], s["n"])
    return out


# ---------- paired analysis (rule fixed in DECISION-002 before the run) ----------
PAIRED_KINDS = ("final", "statement")        # B cannot see steps, so step is not compared
H1_MIN_DIFF, H1_MAX_P = 0.15, 0.10


def mcnemar_exact(b, c):
    """Exact two-sided McNemar p on the discordant pairs: b = only B caught, c = only A caught."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def paired(results, kinds=PAIRED_KINDS):
    """A and B on the same corrupted cases. A pair needs a result without an error from both
    conditions; the pairs left out are counted, never dropped silently."""
    by = {}
    for r in results:
        if r["injected"] in kinds:
            by.setdefault((r["case"], r["injected"]), {})[r["condition"]] = r
    pairs, left_out = [], 0
    for res in by.values():
        a, b = res.get("A"), res.get("B")
        if a is None or b is None or a.get("error") or b.get("error"):
            left_out += 1
            continue
        pairs.append((bool(a["detected"]), bool(b["detected"])))
    n = len(pairs)
    only_b = sum(1 for a, b in pairs if b and not a)
    only_a = sum(1 for a, b in pairs if a and not b)
    rate_a = sum(a for a, _ in pairs) / n if n else None
    rate_b = sum(b for _, b in pairs) / n if n else None
    diff = None if n == 0 else rate_b - rate_a
    p = mcnemar_exact(only_b, only_a)
    return {"pairs": n, "left_out": left_out, "rate_A": rate_a, "rate_B": rate_b, "diff_B_minus_A": diff,
            "only_B_caught": only_b, "only_A_caught": only_a, "mcnemar_p": p,
            "H1_supported": bool(n and diff >= H1_MIN_DIFF and p < H1_MAX_P)}


B_MAX_FALSE_ALARM = 0.20                      # DECISION-003 validity gate


def b_gate(results):
    """B is a usable comparison only if it rarely flags an unmodified reply. Returns the counts and
    whether the gate passes; None when B has no control result."""
    c = [r for r in results if r["condition"] == "B" and r["injected"] is None and not r.get("error")]
    if not c:
        return None
    fa = sum(1 for r in c if r["detected"])
    return {"controls": len(c), "false_alarms": fa, "rate": fa / len(c), "valid": fa / len(c) <= B_MAX_FALSE_ALARM}


def h1_verdict(results, kinds=PAIRED_KINDS):
    """The pre-registered verdict: the validity gate first, then the H1 rule on the paired cells."""
    pr, gate = paired(results, kinds), b_gate(results)
    if gate is None or not gate["valid"]:
        return "NOT INTERPRETABLE (B's false alarms on controls: " + (
            "none measured" if gate is None else f"{gate['false_alarms']}/{gate['controls']} > {B_MAX_FALSE_ALARM:.0%}") + ")"
    return "SUPPORTED" if pr["H1_supported"] else "NOT SUPPORTED (includes inconclusive)"


def assert_no_network(source):
    """The harness must not be able to reach Telegram or write state; returns the offending tokens."""
    body = re.sub(r"FORBIDDEN = \(.*?\)\n", "", source, flags=re.S)       # the list itself is not a use
    return [t for t in FORBIDDEN if t in body]


# ---------- CLI ----------
def load_input_cases(a, ap):
    """Cases from a JSON file, or from a private tg-solver data directory through the adapter."""
    if a.adapter == "tg-solver":
        from .adapters.tg_solver import load_cases
        return load_cases(a.data)
    if not a.cases:
        ap.error("--cases FILE is required with the json adapter")
    cases = json.loads(a.cases.read_text(encoding="utf-8"))
    need = {"case", "kind", "problem_statement", "final_answer", "message", "chat_text", "images", "language"}
    for c in cases:
        missing = need - set(c)
        if missing:
            ap.error(f"case {c.get('case')!r} lacks fields: {sorted(missing)}")
    return cases


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "run", "report"])
    ap.add_argument("--n-inject", type=int, default=60)
    ap.add_argument("--n-control", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--kinds", default=",".join(KINDS), help=f"error kinds to inject, from {','.join(ALL_KINDS)}")
    ap.add_argument("--condition", choices=["A", "B", "both"], default="both")
    ap.add_argument("--limit", type=int, default=0, help="run at most this many (case, condition) pairs")
    ap.add_argument("--cases", type=Path, help="JSON file: a list of cases (see README for the schema)")
    ap.add_argument("--adapter", choices=["json", "tg-solver"], default="json")
    ap.add_argument("--data", type=Path, default=Path.home() / ".tg-solver", help="tg-solver data directory (adapter only)")
    ap.add_argument("--model", default="opus", help="model for the verifier (default: opus)")
    ap.add_argument("--timeout", type=int, default=600, help="seconds per call")
    ap.add_argument("--out", type=Path, default=Path("verify-study-output"))
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    plan_f, res_f = a.out / "plan.json", a.out / "results.jsonl"

    if a.cmd == "plan":
        cases = load_input_cases(a, ap)
        kinds = tuple(k for k in a.kinds.split(",") if k)
        bad = [k for k in kinds if k not in ALL_KINDS]
        if bad:
            ap.error(f"unknown error kind(s): {bad}; choose from {ALL_KINDS}")
        plan = build_plan(cases, a.n_inject, a.n_control, a.seed, kinds)
        plan_f.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        kinds = {}
        for c in plan:
            k = (c["injected"] or {}).get("kind", "control")
            kinds[k] = kinds.get(k, 0) + 1
        print(f"eligible cases: {len(cases)} | planned: {len(plan)} | by kind: {kinds} | plan: {plan_f}")
        return 0

    if a.cmd == "run":
        plan = json.loads(plan_f.read_text(encoding="utf-8"))
        done = set()
        if res_f.exists():
            for line in res_f.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                done.add((r["case"], r["condition"], r["injected"]))
        conds = ["A", "B"] if a.condition == "both" else [a.condition]
        model, timeout = a.model, a.timeout
        ran = 0
        with res_f.open("a", encoding="utf-8") as out:
            for case in plan:
                kind = (case["injected"] or {}).get("kind")
                for cond in conds:
                    if (case["case"], cond, kind) in done:
                        continue
                    if a.limit and ran >= a.limit:
                        break
                    rec = {"case": case["case"], "condition": cond, "injected": kind}
                    try:
                        rec.update(CONDITIONS[cond](case, model, timeout))
                        rec["usage"] = llm.last_usage
                    except Exception as e:                      # recorded, never hidden
                        rec["error"] = f"{type(e).__name__}: {str(e)[:200]}"
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out.flush()
                    ran += 1
        print(f"ran {ran} calls -> {res_f}")
        return 0

    results = [json.loads(l) for l in res_f.read_text(encoding="utf-8").splitlines()]
    print(f"{'condition':<10}{'kind':<12}{'n':>4}{'detected':>10}{'rate':>8}   95% CI   errors")
    for (cond, kind), s in sorted(summarize(results).items()):
        rate = "-" if s["rate"] is None else f"{s['rate']:.2f}"
        lo, hi = s["ci95"]
        print(f"{cond:<10}{kind:<12}{s['n']:>4}{s['detected']:>10}{rate:>8}   {lo:.2f}-{hi:.2f}   {s['errors']}"
              + (f"   <- {NOT_MEASURABLE[(cond, kind)]}" if (cond, kind) in NOT_MEASURABLE else ""))
    usage = [r["usage"] for r in results if r.get("usage")]
    if usage:
        print(f"calls: {len(results)} | cost: ${sum(u.get('cost') or 0 for u in usage):.2f}")
    gate = b_gate(results)
    if gate:
        print(f"\nB validity gate (false alarms on controls <= {B_MAX_FALSE_ALARM:.0%}): "
              f"{gate['false_alarms']}/{gate['controls']} -> {'passes' if gate['valid'] else 'FAILS'}")
    f = lambda x: "-" if x is None else f"{x:.2f}"
    for label, kinds in (("final + statement", PAIRED_KINDS), ("consistent", ("consistent",))):
        pr = paired(results, kinds)
        if pr["pairs"] or pr["left_out"]:
            print(f"\npaired ({label}): pairs={pr['pairs']} left_out={pr['left_out']} "
                  f"A={f(pr['rate_A'])} B={f(pr['rate_B'])} B-A={f(pr['diff_B_minus_A'])} "
                  f"only_B_caught={pr['only_B_caught']} only_A_caught={pr['only_A_caught']} McNemar p={pr['mcnemar_p']:.3f}")
            print(f"H1 (A misses more than B; needs B-A >= {H1_MIN_DIFF}, p < {H1_MAX_P} and the gate): "
                  f"{h1_verdict(results, kinds)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
