"""
Claude Code `Stop` hook (thin, non-blocking client).

Reads the last assistant message from the transcript and hands it to the
running voice-loop daemon over a localhost socket, then exits immediately --
so Claude Code is never blocked while the answer is spoken. If the daemon
isn't running, it falls back to a detached one-shot speak so you still hear
something.
"""
import io
import json
import os
import socket
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common import load_config  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _extract_text(message):
    content = message.get("content")
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
    return "\n".join(p for p in parts if p).strip()


def last_assistant_text(transcript_path):
    if not transcript_path or not os.path.exists(transcript_path):
        return ""
    latest = ""
    with io.open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "assistant":
                continue
            text = _extract_text(obj.get("message") or {})
            if text:
                latest = text
    return latest


def send_to_daemon(text, cfg):
    d = cfg["daemon"]
    payload = json.dumps({"text": text}).encode("utf-8")
    with socket.create_connection((d["host"], int(d["port"])), timeout=1.0) as s:
        s.sendall(payload)
        s.shutdown(socket.SHUT_WR)


def fallback_speak(text):
    """Detached one-shot readback if the daemon isn't up (never blocks).

    stdout/stderr must go to DEVNULL: with them inherited, the detached child
    holds the hook's output pipes open and Claude Code waits on them until the
    speech process exits ("stopping hook..." hang). stdin is closed after the
    write so speak.py sees EOF, and the text is capped so the write itself can
    never block on a full pipe.
    """
    py = sys.executable
    proc = subprocess.Popen(
        [py, os.path.join(ROOT, "speak.py")],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8", cwd=ROOT,
        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0)
                       | getattr(subprocess, "DETACHED_PROCESS", 0)
                       | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)),
    )
    try:
        proc.stdin.write(text[:4000])
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    if payload.get("stop_hook_active"):
        return

    text = last_assistant_text(payload.get("transcript_path", ""))
    if not text:
        return

    cfg = load_config()
    try:
        send_to_daemon(text, cfg)
    except OSError:
        try:
            fallback_speak(text)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # a readback failure must never break the hook chain
