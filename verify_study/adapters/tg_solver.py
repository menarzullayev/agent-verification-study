"""Adapter for the data of a private Telegram study-group assistant (tg-solver).

Reads its data directory read-only: saved jobs (jobs/*.json), the message store (state.db, opened
with mode=ro) and cached photos (media/). It is published as documentation of how the cases of
the study were rebuilt; the data itself is not published.
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from ..eval import numeric_answer

DATA = Path.home() / ".tg-solver"
DEFAULT_CONF = {"context_messages": 15, "context_image_minutes": 30, "max_images": 8, "languages": {}}


def chat_text(context, batch, images, questions=frozenset()):
    """The <chat> block as service.chat_text builds it: context first, then the NEW messages."""
    answered = {r["reply_to"] for r in context if r["status"] == "me" and r["reply_to"] and r["id"] not in questions}
    waiting = {r["reply_to"] for r in context if r["id"] in questions}
    img_no = {mid: n for n, mid in enumerate(images, 1)}
    lines = []
    for tag, rows in (("context", context), ("NEW", batch)):
        for r in rows:
            who = "GROUP OWNER (you)" if r["status"] == "me" else r["sender"]
            when = datetime.fromtimestamp(r["ts"]).strftime("%H:%M")
            extra = ""
            if r["media"]:
                extra = f" [image {img_no[r['id']]}]" if r["id"] in img_no else f" [{r['media']}, not shown]"
            if r["id"] in answered:
                extra += " [ANSWERED by group owner]"
            elif r["id"] in waiting:
                extra += " [not solved yet: the group owner asked for the missing part and is still waiting]"
            reply = f" (reply to {r['reply_to']})" if r["reply_to"] else ""
            lines.append(f"{tag} id={r['id']} {when} {who}{reply}: {r['text']}{extra}")
    return "<chat>\n" + "\n".join(lines) + "\n</chat>"


def load_cases(data=DATA, conf=None):
    """Saved jobs the service called solved and verified, rebuilt the way service.process saw them:
    the 15-message context, and the author's photos from the last 30 minutes. A job is skipped
    when its photos are not cached or when earlier answers were part of its prompt (not rebuilt)."""
    conf = conf or DEFAULT_CONF
    db = sqlite3.connect(f"file:{(data / 'state.db').as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    langs = conf.get("languages", {})
    cases = []
    for f in sorted((data / "jobs").glob("*.json")):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        s, v = j.get("solved") or {}, j.get("verdict") or {}
        if (s.get("status") != "solved" or v.get("verdict") != "correct" or not j.get("message")
                or j.get("figures") or (j.get("earlier_answers") or 0) > 0
                or not numeric_answer(s.get("final_answer"))):
            continue
        ids, chat = j.get("ids") or [], j["chat"]
        q = ",".join("?" * len(ids))
        batch = db.execute(f"SELECT * FROM messages WHERE chat=? AND id IN ({q}) ORDER BY id", (chat, *ids)).fetchall()
        if not batch or len(batch) != len(ids):
            continue
        context = db.execute("SELECT * FROM messages WHERE chat=? AND id<? ORDER BY id DESC LIMIT ?",
                             (chat, min(ids), conf["context_messages"])).fetchall()[::-1]
        recent = max(r["ts"] for r in batch) - conf["context_image_minutes"] * 60
        sender = batch[0]["sender_id"]
        photo_rows = ([r for r in context if r["sender_id"] == sender and r["media"] == "photo" and r["ts"] >= recent]
                      + [r for r in batch if r["media"] == "photo"])[-conf["max_images"]:]
        paths = [data / "media" / f"{chat}_{r['id']}.jpg" for r in photo_rows]
        if any(not p.exists() for p in paths):
            continue
        try:
            questions = {r[0] for r in db.execute("SELECT msg_id FROM sent WHERE chat=? AND kind='question'", (chat,))}
        except sqlite3.Error:
            questions = set()
        cases.append({"case": f.stem, "kind": (j.get("triage") or {}).get("kind", "task"),
                      "problem_statement": s["problem_statement"], "final_answer": s["final_answer"],
                      "message": j["message"], "chat_text": chat_text(context, batch, [r["id"] for r in photo_rows], questions),
                      "images": [str(p) for p in paths], "language": langs.get(str(chat), "uz")})
    db.close()
    return cases


