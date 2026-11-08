"""Schemas and the language note the verifier prompt is paired with."""
from pathlib import Path

PROMPTS = Path(__file__).resolve().parent / "prompts"


def load_prompt(name):
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


VERIFY_SCHEMA = {"type": "object", "required": ["verdict", "independent_answer", "issues", "figure_ok", "bad_figures",
                                            "statement_matches", "contradicts_earlier"],
                 "properties": {
    "statement_matches": {"type": "boolean"}, "contradicts_earlier": {"type": "boolean"},
    "figure_ok": {"type": "boolean"}, "bad_figures": {"type": "array", "items": {"type": "integer"}},
    "verdict": {"type": "string", "enum": ["correct", "incorrect", "unsure"]},
    "independent_answer": {"type": "string"}, "issues": {"type": "string"}}}


CHECK_IN = {"ru": """

This group is answered in Russian by design: the reply's **Условие.** section is the **Shart.** section
named above, and "Пример задачи" is "Namuna misol". Do not count the language as a mistake."""}
