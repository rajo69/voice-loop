"""
One-shot readback: read text on stdin, summarize it, ping + speak, exit.

Used as the fallback path when the voice-loop daemon isn't running, and handy
for testing:   echo "some text" | python speak.py
"""
import sys

from common import load_config
from speaker import Speaker
from summarize import summarize_for_speech


def main():
    text = sys.stdin.read()
    if not text.strip():
        return
    cfg = load_config()
    if not cfg["tts"].get("enabled", True):
        return
    spoken = summarize_for_speech(text, cfg["summary"])
    if not spoken:
        return
    speaker = Speaker(ping=cfg["tts"].get("ping", True))
    speaker.speak(spoken)
    # Block until playback finishes (this is a short-lived process).
    t = speaker._thread
    if t is not None:
        t.join()


if __name__ == "__main__":
    main()
