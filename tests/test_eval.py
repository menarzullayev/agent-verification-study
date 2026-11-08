"""tools/verify_eval.py (DECISION-001): the offline measurement must be able to measure misses,
must corrupt replies the way it claims, and must not be able to reach Telegram."""
import random
import unittest
from fractions import Fraction
from pathlib import Path

from verify_study import eval as ve
from verify_study.adapters import tg_solver as adapter

SRC = Path(ve.__file__).read_text(encoding="utf-8")
ADAPTER_SRC = Path(adapter.__file__).read_text(encoding="utf-8")
MSG = ("**Shart.** $x + 12 = 20$ tenglamani yeching.\n\n"
       "Ikkala tomondan 12 ni ayiramiz.\n\n"
       "Demak $x = 20 - 12$ va $20 - 12 = 8$.\n\n"
       "## Javob\n\n$8$")
CASE = {"case": "g_1", "kind": "task", "problem_statement": "x + 12 = 20", "final_answer": "8", "message": MSG,
        "chat_text": "<chat>\nNEW id=1 10:00 A: x+12=20 ni yeching\n</chat>", "images": [], "language": "uz"}


def blind_reply(answer, reading="x + 12 = 20"):
    return lambda model, system, text, schema, images, timeout: {
        "task_as_read": reading, "independent_answer": answer, "confidence": 0.9}


class Numbers(unittest.TestCase):
    def test_agree_ignores_wording_and_order(self):
        self.assertTrue(ve.agree("x = 8", "8"))
        self.assertTrue(ve.agree("3, 5", "5 va 3"))
        self.assertTrue(ve.agree("0.5", "0,5"))

    def test_agree_rejects_a_different_number(self):
        self.assertFalse(ve.agree("8", "9"))
        self.assertFalse(ve.agree("3, 5", "3"))

    def test_numbers_are_fractions(self):
        self.assertEqual(ve.numbers("1,5 va 2"), [Fraction(3, 2), Fraction(2)])

    def test_bump_changes_the_number_and_keeps_its_shape(self):
        self.assertEqual(ve.bump("12"), "13")
        self.assertEqual(ve.bump("9"), "10")
        self.assertEqual(ve.bump("0.5"), "0.6")
        self.assertEqual(ve.bump("0,9"), "0,0")      # shape kept; still different from the original
        self.assertNotEqual(ve.bump("0,9"), "0,9")


class Injection(unittest.TestCase):
    def test_final_changes_answer_and_the_answer_block_only(self):
        bad = ve.inject(CASE, "final")
        self.assertEqual(bad["final_answer"], "9")
        self.assertTrue(bad["message"].endswith("$9$"))
        self.assertIn("20 - 12 = 8", bad["message"])               # the steps still say 8
        self.assertEqual(bad["injected"], {"kind": "final", "old": "8", "new": "9"})

    def test_step_keeps_the_final_answer_and_the_statement(self):
        bad = ve.inject(CASE, "step")
        self.assertEqual(bad["final_answer"], "8")
        self.assertEqual(bad["problem_statement"], CASE["problem_statement"])
        self.assertTrue(bad["message"].endswith("$8$"))
        before, after = MSG.split("\n\n"), bad["message"].split("\n\n")
        changed = [i for i, (x, y) in enumerate(zip(before, after)) if x != y]
        self.assertEqual(len(before), len(after))
        self.assertEqual(len(changed), 1)                       # exactly one step block
        self.assertNotIn(changed[0], (0, len(before) - 1))      # never the statement or the answer block
        inj = bad["injected"]
        self.assertEqual(inj["kind"], "step")
        self.assertNotEqual(inj["old"], inj["new"])
        self.assertIn(inj["new"], after[changed[0]])

    def test_statement_changes_the_task_in_both_places_but_not_the_answer(self):
        bad = ve.inject(CASE, "statement")
        self.assertEqual(bad["problem_statement"], "x + 13 = 20")
        self.assertIn("x + 13 = 20", bad["message"].split("\n\n")[0])
        self.assertEqual(bad["final_answer"], "8")

    def test_statement_skips_the_tasks_own_number(self):
        """Found on the real jobs: '79. Formulasi ...' starts with a task number the reply leaves out."""
        numbered = dict(CASE, problem_statement="79. x + 12 = 20",
                        message=MSG)
        bad = ve.inject(numbered, "statement")
        self.assertEqual(bad["injected"]["old"], "12")
        self.assertEqual(bad["problem_statement"], "79. x + 13 = 20")
        self.assertIn("79. x", bad["problem_statement"])

    def test_a_number_is_replaced_whole_never_inside_a_longer_number(self):
        case = dict(CASE, final_answer="8", message=MSG.replace("Ikkala", "28 ta. Ikkala"))
        bad = ve.inject(case, "final")
        self.assertIn("28 ta.", bad["message"])                   # the 8 inside 28 is untouched
        self.assertTrue(bad["message"].endswith("$9$"))
        self.assertIsNone(ve.replace_token("28 va 18", "8", "9"))

    def test_the_original_case_is_not_mutated(self):
        before = dict(CASE)
        for kind in ve.KINDS:
            ve.inject(CASE, kind)
        self.assertEqual(CASE, before)

    def test_a_reply_without_a_number_for_that_kind_is_skipped_not_faked(self):
        plain = dict(CASE, final_answer="yechim yo'q", message="**Shart.** Isbotlang.\n\nIsbot.\n\n## Javob\n\nyo'q")
        self.assertIsNone(ve.inject(plain, "final"))
        self.assertIsNone(ve.inject(plain, "statement"))

    def test_plan_has_disjoint_controls_and_spreads_kinds(self):
        cases = [dict(CASE, case=f"g_{i}") for i in range(12)]
        plan = ve.build_plan(cases, n_inject=6, n_control=3, seed=1)
        controls = [c for c in plan if c["injected"] is None]
        injected = [c for c in plan if c["injected"]]
        self.assertEqual(len(controls), 3)
        self.assertEqual(sorted(c["injected"]["kind"] for c in injected), ["final", "final", "statement",
                                                                           "statement", "step", "step"])
        self.assertFalse({c["case"] for c in controls} & {c["case"] for c in injected})
        self.assertEqual(len({c["case"] for c in injected}), len(injected))     # one corruption per case


class PlanBalance(unittest.TestCase):
    """Found on the real data: 48 eligible jobs, and the first error kind took all of them."""

    def test_a_small_pool_is_shared_evenly_between_the_error_kinds(self):
        cases = [dict(CASE, case=f"g_{i}") for i in range(9)]
        plan = ve.build_plan(cases, n_inject=30, n_control=30, seed=3)
        kinds = [c["injected"]["kind"] for c in plan if c["injected"]]
        self.assertEqual({k: kinds.count(k) for k in ve.KINDS}, {"final": 3, "step": 3, "statement": 3})
        self.assertEqual([c for c in plan if c["injected"] is None], [])          # nothing left for controls

    def test_a_kind_the_pool_cannot_support_does_not_starve_the_others(self):
        no_stmt = lambda i: dict(CASE, case=f"g_{i}", message="**Shart.** Hisoblang.\n\nQadam 5.\n\n"
                                 "Qadam 6.\n\n## Javob\n\n$8$")
        cases = [no_stmt(i) for i in range(6)]
        plan = ve.build_plan(cases, n_inject=9, n_control=0, seed=1)
        kinds = [c["injected"]["kind"] for c in plan]
        self.assertEqual(kinds.count("statement"), 0)
        self.assertEqual(kinds.count("final"), 3)
        self.assertEqual(kinds.count("step"), 3)

    def test_controls_are_what_is_left_after_the_injected_cases(self):
        cases = [dict(CASE, case=f"g_{i}") for i in range(12)]
        plan = ve.build_plan(cases, n_inject=6, n_control=10, seed=1)
        self.assertEqual(len([c for c in plan if c["injected"]]), 6)
        self.assertEqual(len([c for c in plan if c["injected"] is None]), 6)       # 12 - 6, fewer than asked


class Conditions(unittest.TestCase):
    def test_a_receives_the_reply_and_b_does_not(self):
        seen = {}

        def spy(model, system, text, schema, images, timeout):
            seen["text"] = text
            return {"verdict": "correct", "independent_answer": "8", "issues": "", "figure_ok": True,
                    "bad_figures": []}

        ve.condition_a(CASE, "m", 1, call=spy)
        self.assertIn("<solution>", seen["text"])
        self.assertIn("20 - 12 = 8", seen["text"])
        seen.clear()
        ve.condition_b(CASE, "m", 1, call=lambda model, system, text, schema, images, timeout:
                       seen.update(text=text) or {"task_as_read": "", "independent_answer": "8", "confidence": 1})
        self.assertNotIn("<solution>", seen["text"])
        self.assertNotIn("20 - 12 = 8", seen["text"])

    def test_a_flags_incorrect_and_a_statement_mismatch(self):
        def a(verdict, matches=True):
            return ve.condition_a(CASE, "m", 1, call=lambda *x: {"verdict": verdict, "independent_answer": "",
                                                                 "issues": "", "figure_ok": True, "bad_figures": [],
                                                                 "statement_matches": matches})
        self.assertFalse(a("correct")["detected"])
        self.assertTrue(a("incorrect")["detected"])
        self.assertTrue(a("correct", matches=False)["detected"])

    def test_b_detects_a_wrong_answer_a_wrong_reading_and_accepts_a_right_one(self):
        self.assertFalse(ve.condition_b(CASE, "m", 1, call=blind_reply("8"))["detected"])
        bad_answer = ve.inject(CASE, "final")
        self.assertTrue(ve.condition_b(bad_answer, "m", 1, call=blind_reply("8"))["detected"])
        bad_reading = ve.inject(CASE, "statement")
        self.assertTrue(ve.condition_b(bad_reading, "m", 1, call=blind_reply("8"))["detected"])

    def test_b_ignores_the_tasks_own_number_but_not_a_changed_task_number_inside(self):
        numbered = dict(CASE, problem_statement="79. x + 12 = 20")
        self.assertFalse(ve.condition_b(numbered, "m", 1, call=blind_reply("8", "x + 12 = 20"))["detected"])
        self.assertFalse(ve.condition_b(numbered, "m", 1, call=blind_reply("8", "2.8. x + 12 = 20"))["detected"])
        self.assertTrue(ve.condition_b(numbered, "m", 1, call=blind_reply("8", "79. x + 13 = 20"))["detected"])

    def test_reading_flags_a_substitution_not_a_longer_or_shorter_reading(self):
        """Pilot 4: the blind reading is verbatim, the saved statement a summary. Only 4 -> 3 counts."""
        def det(read):
            return ve.condition_b(CASE, "m", 1, call=blind_reply("8", read))["detected"]
        self.assertFalse(det("x + 12 = 20, bundan tashqari 3 va 7 ham berilgan"))     # blind has more numbers
        self.assertFalse(det("x = 20"))                                               # blind has fewer
        self.assertTrue(det("x + 13 = 20"))                                           # a number replaced
        self.assertTrue(det("x + 14 = 20 va 5"))                                      # replaced, plus an extra

    def test_a_dropped_number_is_a_known_blind_spot(self):
        """Stated limit, so a result is never read as covering deletion errors."""
        dropped = dict(CASE, problem_statement="x + 12 = 20 va 5")
        r = ve.condition_b(dropped, "m", 1, call=blind_reply("8", "x + 12 = 20"))
        self.assertFalse(r["detected"])
        self.assertEqual(r["reading_diff"], {"only_blind": [], "only_saved": ["5"]})

    def test_number_diff_reports_numbers_only(self):
        d = ve.number_diff("x + 13 = 20", "x + 12 = 20 and 5")
        self.assertEqual(d, {"only_blind": ["13"], "only_saved": ["12", "5"]})
        self.assertEqual(ve.number_diff("a", "b"), {"only_blind": [], "only_saved": []})
        r = ve.condition_b(CASE, "m", 1, call=blind_reply("8", "yeching x + 13 = 20"))
        self.assertEqual(r["reading_diff"], {"only_blind": ["13"], "only_saved": ["12"]})
        self.assertNotIn("yeching", str(r["reading_diff"]))                 # no task text in the record

    def test_strip_numbering_only_removes_a_leading_task_number(self):
        self.assertEqual(ve.strip_numbering("2.8. Prove A"), "Prove A")
        self.assertEqual(ve.strip_numbering("40-masala. x"), "x")
        self.assertEqual(ve.strip_numbering("79. Formulasi"), "Formulasi")
        self.assertEqual(ve.strip_numbering("x + 12 = 20"), "x + 12 = 20")
        self.assertEqual(ve.strip_numbering("12 + x = 20"), "12 + x = 20")           # starts with an operand, kept
        self.assertEqual(ve.strip_numbering("40 - 5 = 35"), "40 - 5 = 35")           # a minus is not numbering
        self.assertEqual(ve.strip_numbering("3.5 + x = 9"), "3.5 + x = 9")           # a decimal is not numbering

    def test_b_cannot_see_a_wrong_intermediate_step(self):
        """By construction (the blind verifier never sees the steps); the report must say so."""
        bad_step = ve.inject(CASE, "step")
        self.assertFalse(ve.condition_b(bad_step, "m", 1, call=blind_reply("8"))["detected"])

    def test_an_unreadable_task_is_not_counted_as_a_detection(self):
        r = ve.condition_b(CASE, "m", 1, call=blind_reply("UNREADABLE"))
        self.assertFalse(r["detected"])
        self.assertTrue(r["unreadable"])


class Measurement(unittest.TestCase):
    """The negative tests: the harness has to be able to report a miss, not only a catch."""

    def run_all(self, fake_b):
        cases = [dict(CASE, case=f"g_{i}", injected=None) for i in range(3)]
        cases += [dict(ve.inject(CASE, k), case=f"i_{k}") for k in ("final", "statement")]
        return [dict(case=c["case"], condition="B", injected=(c["injected"] or {}).get("kind"),
                     **ve.condition_b(c, "m", 1, call=fake_b)) for c in cases]

    def test_a_verifier_that_always_agrees_scores_zero_detection(self):
        always_agrees = lambda model, system, text, schema, images, timeout: {
            "task_as_read": "", "independent_answer": "UNREADABLE", "confidence": 0}
        s = ve.summarize(self.run_all(always_agrees))
        self.assertEqual(s[("B", "final")]["rate"], 0.0)
        self.assertEqual(s[("B", "statement")]["rate"], 0.0)

    def test_a_correct_blind_verifier_scores_full_detection_and_no_false_alarm(self):
        def solver(model, system, text, schema, images, timeout):
            return {"task_as_read": "x + 12 = 20", "independent_answer": "8", "confidence": 1}
        s = ve.summarize(self.run_all(solver))
        self.assertEqual(s[("B", "final")]["rate"], 1.0)
        self.assertEqual(s[("B", "statement")]["rate"], 1.0)
        self.assertEqual(s[("B", "control")]["rate"], 0.0)

    def test_errors_are_counted_not_dropped(self):
        s = ve.summarize([{"condition": "A", "injected": "final", "error": "timeout"},
                          {"condition": "A", "injected": "final", "detected": True}])
        self.assertEqual(s[("A", "final")], {"n": 1, "detected": 1, "errors": 1, "rate": 1.0,
                                             "ci95": ve.wilson(1, 1)})

    def test_wilson_interval_is_wide_for_small_n_and_bounded(self):
        lo, hi = ve.wilson(3, 10)
        self.assertTrue(0 <= lo < 0.3 < hi <= 1)
        self.assertEqual(ve.wilson(0, 0), (0.0, 0.0))
        self.assertGreater(ve.wilson(30, 100)[1] - ve.wilson(30, 100)[0],
                           0.0)
        self.assertLess(ve.wilson(300, 1000)[1] - ve.wilson(300, 1000)[0],
                        ve.wilson(3, 10)[1] - ve.wilson(3, 10)[0])


class LoadCases(unittest.TestCase):
    """load_cases must rebuild the prompt the way service.process saw it (found by the pilot: a task
    photographed in an earlier message reached the verifier as 'UNREADABLE')."""
    CONF = {"context_messages": 15, "context_image_minutes": 30, "max_images": 8, "languages": {}}
    NOW = 1_800_000_000

    def make(self, jobs, rows):
        import json
        import sqlite3
        import tempfile
        d = Path(tempfile.mkdtemp())
        (d / "jobs").mkdir()
        (d / "media").mkdir()
        db = sqlite3.connect(d / "state.db")
        db.execute("CREATE TABLE messages (chat, id, sender_id, sender, ts, text, media, reply_to, status)")
        db.execute("CREATE TABLE sent (chat, msg_id, kind)")
        for r in rows:
            db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?)", r)
            if r[6] == "photo" and r[3] != "nocache":
                (d / "media" / f"{r[0]}_{r[1]}.jpg").write_bytes(b"x")
        db.commit()
        db.close()
        for name, extra in jobs.items():
            job = {"chat": name, "ids": [10], "triage": {"kind": "task"}, "message": MSG, "figures": {},
                   "solved": {"status": "solved", "problem_statement": "x + 12 = 20", "final_answer": "8"},
                   "verdict": {"verdict": "correct"}}
            job.update(extra)
            (d / "jobs" / f"{name}_10.json").write_text(json.dumps(job), encoding="utf-8")
        return d

    def rows(self, chat, ctx_sender=7, ctx_age=180, cached=True):
        photo_name = "A" if cached else "nocache"
        return [(chat, 9, ctx_sender, photo_name, self.NOW - ctx_age, "mana masala", "photo", None, "done"),
                (chat, 10, 7, "A", self.NOW, "yeching", None, 9, "done")]

    def test_a_photo_in_the_context_from_the_same_author_is_included(self):
        d = self.make({"g1": {}}, self.rows("g1"))
        (c,) = adapter.load_cases(d, self.CONF)
        self.assertEqual(len(c["images"]), 1)
        self.assertIn("context id=9", c["chat_text"])
        self.assertIn("[image 1]", c["chat_text"])
        self.assertIn("NEW id=10", c["chat_text"])

    def test_a_photo_from_another_author_or_older_than_the_window_is_not(self):
        d = self.make({"g2": {}, "g3": {}}, self.rows("g2", ctx_sender=8) + self.rows("g3", ctx_age=31 * 60))
        cases = {c["case"]: c for c in adapter.load_cases(d, self.CONF)}
        self.assertEqual(cases["g2_10"]["images"], [])
        self.assertEqual(cases["g3_10"]["images"], [])
        self.assertIn("[photo, not shown]", cases["g2_10"]["chat_text"])

    def test_proofs_and_prose_answers_are_left_out_of_a_numeric_experiment(self):
        """Found by the second pilot: a proof has no number to compare, so B flagged every one."""
        d = self.make({"g8": {"solved": {"status": "solved", "problem_statement": "Prove A.",
                                         "final_answer": "A is proved: (x,y) in A x C."}},
                       "g9": {"solved": {"status": "solved", "problem_statement": "x + 12 = 20",
                                         "final_answer": "x = 8 " + "tushuntirish " * 12}},
                       "g10": {}}, self.rows("g8") + self.rows("g9") + self.rows("g10"))
        self.assertEqual([c["case"] for c in adapter.load_cases(d, self.CONF)], ["g10_10"])

    def test_jobs_that_cannot_be_rebuilt_are_skipped_not_guessed(self):
        rows = (self.rows("g4") + self.rows("g5", cached=False) + self.rows("g6") + self.rows("g7"))
        d = self.make({"g4": {"earlier_answers": 1}, "g5": {}, "g6": {"verdict": {"verdict": "incorrect"}},
                       "g7": {"figures": {"1": "x.png"}}}, rows)
        self.assertEqual(adapter.load_cases(d, self.CONF), [])

    def test_chat_text_marks_answered_and_waiting_messages(self):
        row = lambda i, status, reply: {"id": i, "status": status, "reply_to": reply, "sender": "A", "ts": 0,
                                        "text": "t", "media": None}
        ctx = [row(1, "done", None), row(2, "me", 1), row(3, "done", None), row(4, "me", 3)]
        text = adapter.chat_text(ctx, [row(5, "done", None)], [], questions={4})
        self.assertIn("context id=1", text.split("\n")[1])
        self.assertIn("[ANSWERED by group owner]", text.split("\n")[1])
        self.assertIn("[not solved yet", text.split("\n")[3])
        self.assertIn("GROUP OWNER (you)", text.split("\n")[2])


class Paired(unittest.TestCase):
    """The analysis rule of DECISION-002, tested before the run so the result cannot move it."""

    def pair(self, case, kind, a, b, a_err=False, b_err=False):
        ra = {"case": case, "condition": "A", "injected": kind, "detected": a}
        rb = {"case": case, "condition": "B", "injected": kind, "detected": b}
        if a_err:
            ra["error"] = "timeout"
        if b_err:
            rb["error"] = "timeout"
        return [ra, rb]

    def test_mcnemar_exact_known_values(self):
        self.assertEqual(ve.mcnemar_exact(0, 0), 1.0)
        self.assertAlmostEqual(ve.mcnemar_exact(5, 0), 0.0625)
        self.assertAlmostEqual(ve.mcnemar_exact(6, 1), 0.125)
        self.assertEqual(ve.mcnemar_exact(3, 3), 1.0)
        self.assertEqual(ve.mcnemar_exact(4, 0), ve.mcnemar_exact(0, 4))      # symmetric

    def test_h1_needs_both_the_difference_and_the_p_value(self):
        # B catches 5 that A misses, A catches none, 7 caught by both: diff 5/12... p = 0.0625
        rs = []
        for i in range(5):
            rs += self.pair(f"x{i}", "final", False, True)
        for i in range(7):
            rs += self.pair(f"y{i}", "statement", True, True)
        r = ve.paired(rs)
        self.assertEqual((r["pairs"], r["only_B_caught"], r["only_A_caught"]), (12, 5, 0))
        self.assertAlmostEqual(r["diff_B_minus_A"], 5 / 12)
        self.assertTrue(r["H1_supported"])

    def test_a_big_difference_without_enough_pairs_is_not_supported(self):
        r = ve.paired(self.pair("x", "final", False, True) + self.pair("y", "final", False, True))
        self.assertEqual(r["diff_B_minus_A"], 1.0)
        self.assertGreaterEqual(r["mcnemar_p"], 0.10)                          # 2 pairs: p = 0.5
        self.assertFalse(r["H1_supported"])

    def test_a_small_difference_is_not_supported_even_if_p_is_small(self):
        rs = []
        for i in range(30):
            rs += self.pair(f"h{i}", "final", True, True)
        for i in range(5):
            rs += self.pair(f"n{i}", "final", False, True)                     # diff 5/35 = 0.143 < 0.15
        r = ve.paired(rs)
        self.assertLess(r["mcnemar_p"], 0.10)
        self.assertFalse(r["H1_supported"])

    def test_when_a_is_better_h1_is_not_supported(self):
        rs = []
        for i in range(8):
            rs += self.pair(f"a{i}", "final", True, False)
        r = ve.paired(rs)
        self.assertLess(r["diff_B_minus_A"], 0)
        self.assertFalse(r["H1_supported"])

    def test_step_and_controls_are_not_in_the_comparison(self):
        rs = self.pair("s", "step", False, True) + self.pair("c", None, False, True)
        r = ve.paired(rs)
        self.assertEqual((r["pairs"], r["left_out"]), (0, 0))
        self.assertFalse(r["H1_supported"])

    def test_pairs_with_an_error_are_counted_as_left_out_not_dropped_silently(self):
        rs = (self.pair("e1", "final", False, True, b_err=True) + self.pair("e2", "statement", True, True, a_err=True)
              + self.pair("ok", "final", True, True))
        r = ve.paired(rs)
        self.assertEqual((r["pairs"], r["left_out"]), (1, 2))

    def test_an_unpaired_case_is_left_out(self):
        r = ve.paired([{"case": "z", "condition": "A", "injected": "final", "detected": True}])
        self.assertEqual((r["pairs"], r["left_out"]), (0, 1))


class Consistent(unittest.TestCase):
    """DECISION-003: a wrong value carried through the steps and the answer, so the reply agrees with itself."""

    def test_the_final_number_is_changed_in_the_steps_and_the_answer_but_not_the_statement(self):
        bad = ve.inject(CASE, "consistent")
        self.assertEqual(bad["final_answer"], "9")
        self.assertIn("20 - 12 = 9", bad["message"])                 # the step now says 9
        self.assertTrue(bad["message"].endswith("$9$"))              # and so does the answer
        self.assertIn("x + 12 = 20", bad["message"].split("\n\n")[0])   # the statement block is untouched
        self.assertEqual(bad["problem_statement"], CASE["problem_statement"])
        self.assertEqual(bad["injected"], {"kind": "consistent", "old": "8", "new": "9"})

    def test_the_reply_no_longer_contradicts_itself(self):
        """The difference from `final`: there the steps keep 8 and only the answer says 9."""
        bad, plain = ve.inject(CASE, "consistent"), ve.inject(CASE, "final")
        self.assertNotIn("8", [str(n) for n in ve.numbers(bad["message"].split("\n\n", 1)[1])])   # no old value left
        self.assertIn("= 9", bad["message"])
        self.assertIn("= 8", plain["message"])                  # `final` keeps the old value in the steps
        self.assertTrue(plain["message"].endswith("$9$"))

    def test_structural_digits_are_not_the_corrupted_number(self):
        """Found on a real case: changing every 1 in 'x1 = 1 va 7' would rewrite indices, not a value."""
        case = dict(CASE, final_answer="x1 = 1 va 7",
                    message="**Shart.** Yeching.\n\nQadam: x1 = 1 va 7.\n\n## Javob\n\n$1$ va $7$")
        bad = ve.inject(case, "consistent")
        self.assertEqual(bad["injected"]["old"], "7")
        self.assertEqual(bad["final_answer"], "x1 = 1 va 8")
        self.assertIn("x1 = 1 va 8", bad["message"])
        only_small = dict(CASE, final_answer="x1 = 1", message="**Shart.** Y.\n\nQadam x1 = 1.\n\n## Javob\n\n$1$")
        self.assertIsNone(ve.inject(only_small, "consistent"))

    def test_a_number_that_is_only_in_the_answer_is_not_a_carried_error(self):
        only_answer = dict(CASE, message="**Shart.** x + 12 = 20.\n\nIkkala tomondan 12 ayiramiz.\n\n## Javob\n\n$8$")
        self.assertIsNone(ve.inject(only_answer, "consistent"))       # that is a `final` error, not this kind

    def test_a_number_is_replaced_whole_in_every_block(self):
        self.assertEqual(ve.replace_all_tokens("28 va 8 va 18", "8", "9"), "28 va 9 va 18")

    def test_plan_with_only_the_consistent_kind(self):
        cases = [dict(CASE, case=f"g_{i}") for i in range(8)]
        plan = ve.build_plan(cases, n_inject=4, n_control=10, seed=2, kinds=("consistent",))
        self.assertEqual([c["injected"]["kind"] for c in plan if c["injected"]], ["consistent"] * 4)
        self.assertEqual(len([c for c in plan if c["injected"] is None]), 4)

    def test_blind_verifier_sees_a_consistent_error_through_the_answer(self):
        bad = ve.inject(CASE, "consistent")
        self.assertTrue(ve.condition_b(bad, "m", 1, call=blind_reply("8"))["detected"])
        self.assertFalse(ve.condition_b(CASE, "m", 1, call=blind_reply("8"))["detected"])


class Fractions(unittest.TestCase):
    """DECISION-003, post-hoc: B's controls were flagged because 11/10 and 1,1 counted as different."""

    def test_fractions_and_decimals_are_the_same_value(self):
        want = [Fraction(11, 10)]
        for text in ("11/10", "1,1", "1.1", "\\frac{11}{10}", "11 / 10"):
            self.assertEqual(ve.numbers(text), want, text)
        self.assertTrue(ve.agree("x = 11/10", "1,1"))
        self.assertFalse(ve.agree("11/10", "1,2"))

    def test_mixed_text_and_a_zero_denominator(self):
        self.assertEqual(ve.numbers("x = 3/2 va 4"), [Fraction(3, 2), Fraction(4)])
        self.assertEqual(ve.numbers("1/0 va 5"), [Fraction(5)])            # not a number: skipped, no crash

    def test_a_changed_fraction_is_still_a_difference(self):
        self.assertFalse(ve.agree("3/2", "5/2"))
        self.assertEqual(ve.number_diff("x = 3/2", "x = 1,5"), {"only_blind": [], "only_saved": []})


class Gate(unittest.TestCase):
    def ctl(self, n, flagged):
        return [{"case": f"c{i}", "condition": "B", "injected": None, "detected": i < flagged} for i in range(n)]

    def inj(self, kind, pairs):
        rs = []
        for i, (a, b) in enumerate(pairs):
            rs += [{"case": f"i{i}", "condition": "A", "injected": kind, "detected": a},
                   {"case": f"i{i}", "condition": "B", "injected": kind, "detected": b}]
        return rs

    def test_two_of_twelve_passes_and_three_fails(self):
        self.assertTrue(ve.b_gate(self.ctl(12, 2))["valid"])
        self.assertFalse(ve.b_gate(self.ctl(12, 3))["valid"])
        self.assertIsNone(ve.b_gate([]))

    def test_a_failed_gate_overrides_a_big_difference(self):
        """Negative test: without the gate this would read SUPPORTED."""
        rs = self.inj("consistent", [(False, True)] * 6 + [(True, True)] * 6) + self.ctl(12, 6)
        self.assertTrue(ve.paired(rs, ("consistent",))["H1_supported"])      # the bare rule says yes
        self.assertTrue(ve.h1_verdict(rs, ("consistent",)).startswith("NOT INTERPRETABLE"))

    def test_no_control_result_for_b_is_not_interpretable(self):
        rs = self.inj("consistent", [(False, True)] * 6 + [(True, True)] * 6)
        self.assertTrue(ve.h1_verdict(rs, ("consistent",)).startswith("NOT INTERPRETABLE"))

    def test_a_passed_gate_and_the_rule_give_supported(self):
        rs = self.inj("consistent", [(False, True)] * 6 + [(True, True)] * 6) + self.ctl(12, 1)
        self.assertEqual(ve.h1_verdict(rs, ("consistent",)), "SUPPORTED")

    def test_a_passed_gate_without_a_difference_is_not_supported(self):
        rs = self.inj("consistent", [(True, True)] * 12) + self.ctl(12, 0)
        self.assertTrue(ve.h1_verdict(rs, ("consistent",)).startswith("NOT SUPPORTED"))


class Report(unittest.TestCase):
    def test_b_on_step_errors_is_labelled_not_measurable_in_the_report(self):
        import io
        import tempfile
        from contextlib import redirect_stdout
        out = Path(tempfile.mkdtemp())
        (out / "results.jsonl").write_text(
            '{"case":"c1","condition":"B","injected":"step","detected":true,"usage":{"cost":0.07}}\n'
            '{"case":"c2","condition":"A","injected":"step","detected":false}\n', encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            ve.main(["report", "--out", str(out)])
        lines = {l.split()[0] + " " + l.split()[1]: l for l in buf.getvalue().splitlines() if l[:1] in "AB"}
        self.assertIn("not a detection rate", lines["B step"])
        self.assertNotIn("not a detection rate", lines["A step"])
        self.assertIn("cost: $0.07", buf.getvalue())


class JsonInput(unittest.TestCase):
    """The json adapter: how a reader of this repository brings their own cases."""

    def run_plan(self, cases, *extra):
        import contextlib
        import io
        import json
        import tempfile
        d = Path(tempfile.mkdtemp())
        (d / "cases.json").write_text(json.dumps(cases), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = ve.main(["plan", "--cases", str(d / "cases.json"), "--out", str(d / "out"), *extra])
        return rc, buf.getvalue(), json.loads((d / "out" / "plan.json").read_text(encoding="utf-8"))

    def test_the_sample_file_plans_into_balanced_injected_and_control_cases(self):
        import json
        cases = json.loads((Path(__file__).resolve().parent.parent / "examples" / "cases.sample.json")
                           .read_text(encoding="utf-8"))
        rc, out, plan = self.run_plan(cases, "--n-inject", "3", "--n-control", "1", "--seed", "1")
        self.assertEqual(rc, 0)
        kinds = sorted((c["injected"] or {}).get("kind", "control") for c in plan)
        self.assertEqual(kinds, ["control", "final", "statement", "step"])
        self.assertIn("eligible cases: 6", out)

    def test_a_case_with_a_missing_field_is_rejected_by_name(self):
        bad = [{"case": "broken", "kind": "task"}]
        with self.assertRaises(SystemExit):
            import contextlib
            import io
            with contextlib.redirect_stderr(io.StringIO()):
                self.run_plan(bad)

    def test_an_unknown_error_kind_is_rejected(self):
        import json
        cases = json.loads((Path(__file__).resolve().parent.parent / "examples" / "cases.sample.json")
                           .read_text(encoding="utf-8"))
        with self.assertRaises(SystemExit):
            import contextlib
            import io
            with contextlib.redirect_stderr(io.StringIO()):
                self.run_plan(cases, "--kinds", "bogus")


class Boundary(unittest.TestCase):
    def test_the_harness_source_cannot_reach_telegram_or_write_state(self):
        self.assertEqual(ve.assert_no_network(SRC), [])

    def test_the_adapter_never_writes(self):
        for bad in ("INSERT ", "UPDATE ", "DELETE ", "subprocess"):
            self.assertNotIn(bad, ADAPTER_SRC)

    def test_the_guard_catches_a_forbidden_use(self):
        """Negative test: the guard must fail on source that does what it forbids."""
        for bad in ("svc = Service(cfg)", "tg = McpClient()", 'db.execute("UPDATE messages SET status=1")',
                    'self.tg.call("delete_message", {})', "subprocess.run(['x'])"):
            self.assertNotEqual(ve.assert_no_network(SRC + "\n" + bad), [], bad)

    def test_the_state_database_is_opened_read_only(self):
        self.assertIn("mode=ro", ADAPTER_SRC)
        self.assertNotIn("sqlite3.connect(str", ADAPTER_SRC)

    def test_cases_come_only_from_correct_solved_jobs_without_drawings(self):
        self.assertIn('v.get("verdict") != "correct"', ADAPTER_SRC)
        self.assertIn('j.get("figures")', ADAPTER_SRC)


if __name__ == "__main__":
    unittest.main()
