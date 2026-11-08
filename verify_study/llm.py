"""Headless Claude Code calls (`claude -p`) with no tools and no MCP servers.

The model only ever returns structured JSON; it cannot read files or reach the network through
tools, so text planted in a case cannot make it act.
"""
import base64
import json
import shutil
import subprocess
from pathlib import Path

MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


def media_type(data: bytes, suffix: str) -> str:
    """By content first: a PNG sent as a document is saved under a .jpg name."""
    if data[:4] == bytes([0x89]) + b"PNG":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == bytes([0xFF, 0xD8]):
        return "image/jpeg"
    return MEDIA_TYPES.get(suffix.lower(), "image/jpeg")


# What the last run() spent, read by the caller right after it returns or raises.
last_usage = None


class LLMError(RuntimeError):
    pass


def run(model: str, system: str, text: str, schema: dict, images=(), timeout=600) -> dict:
    global last_usage
    content = []
    for path in images:
        path = Path(path)
        data = path.read_bytes()
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": media_type(data, path.suffix),
            "data": base64.b64encode(data).decode()}})
    content.append({"type": "text", "text": text})
    cmd = [
        shutil.which("claude") or "claude", "-p", "--model", model,
        "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        "--disable-slash-commands", "--no-session-persistence",
        # no settings, CLAUDE.md or memory: they cost about 5000 tokens per call, and the owner's
        # private notes must not share a context with text from a public group
        "--setting-sources", "",
        "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
        "--system-prompt", system, "--json-schema", json.dumps(schema),
    ]
    try:
        p = subprocess.run(
            cmd, input=json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n",
            capture_output=True, text=True, encoding="utf-8", timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise LLMError(f"{model}: timeout after {timeout}s") from None
    result = None
    for line in p.stdout.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "result":
            result = obj
    if result is None:
        raise LLMError(f"{model}: no result (rc={p.returncode}) {p.stderr[:300]}")
    usage = result.get("usage") or {}
    last_usage = {"input": usage.get("input_tokens", 0), "cache_create": usage.get("cache_creation_input_tokens", 0),
                  "cache_read": usage.get("cache_read_input_tokens", 0), "output": usage.get("output_tokens", 0),
                  "cost": result.get("total_cost_usd") or 0}
    if result.get("is_error") or not isinstance(result.get("structured_output"), dict):
        raise LLMError(f"{model}: {str(result.get('result'))[:300]}")
    return result["structured_output"]
