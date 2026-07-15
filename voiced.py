"""
voice-loop daemon.

Runs both halves in one warm process:
  - INPUT:  global hotkey -> local STT -> types into the focused window.
  - OUTPUT: a localhost socket server. The Claude Code `Stop` hook sends the
            answer text here; the daemon summarizes it and speaks it with a
            warm Kokoro model. New speech interrupts old; starting to talk
            (the hotkey) interrupts any readback (barge-in).

The hook stays instant because it just hands text over the socket and exits;
all the slow work (summarize + synth + playback) happens here, off Claude's
critical path.

Run:  python voiced.py      Quit: Ctrl+C
"""
import json
import socket
import sys
import threading

from common import load_config
from input_engine import VoiceInput
from speaker import Speaker
from summarize import summarize_for_speech

CFG = load_config()


def _read_all(conn):
    conn.settimeout(2.0)
    chunks = []
    try:
        while True:
            b = conn.recv(65536)
            if not b:
                break
            chunks.append(b)
    except socket.timeout:
        pass
    return b"".join(chunks)


class Server(threading.Thread):
    def __init__(self, speaker, summary_cfg, host, port):
        super().__init__(daemon=True)
        self.speaker = speaker
        self.summary_cfg = summary_cfg
        self.host = host
        self.port = port
        self._sock = None

    def run(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(8)
        print(f"[out] readback server on {self.host}:{self.port}", flush=True)
        while True:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            with conn:
                data = _read_all(conn)
                self._dispatch(data)

    def _dispatch(self, data):
        if not data:
            return
        try:
            msg = json.loads(data.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            msg = {"text": data.decode("utf-8", "replace")}

        cmd = msg.get("cmd")
        if cmd == "stop":
            self.speaker.interrupt()
            return
        if cmd == "ping":
            return

        text = msg.get("text", "")
        if not text:
            return
        spoken = summarize_for_speech(text, self.summary_cfg)
        if spoken:
            print(f"[out] speaking ({len(spoken)} chars): {spoken[:80]}...",
                  flush=True)
            self.speaker.speak(spoken)


def _prewarm(speaker):
    """Load the TTS model in the background so the first readback isn't cold."""
    def run():
        try:
            r = speaker.engine.synth("ready")
            if r:
                print("[out] TTS model warmed.", flush=True)
        except Exception as e:
            print(f"[out] warmup skipped: {e}", flush=True)
    threading.Thread(target=run, daemon=True).start()


def main():
    tts_cfg = CFG["tts"]
    speaker = Speaker(ping=tts_cfg.get("ping", True)) if tts_cfg.get("enabled", True) else None

    def barge_in():
        if speaker:
            speaker.interrupt()

    vin = VoiceInput(CFG, on_activate=barge_in)

    hk = "+".join(sorted(vin.required))
    print(f"[voice-loop] daemon starting. Hotkey: {hk}")
    if speaker:
        print(f"[out] TTS engine: {speaker.engine_name}")
        _prewarm(speaker)
        d = CFG["daemon"]
        Server(speaker, CFG["summary"], d["host"], int(d["port"])).start()
    else:
        print("[out] TTS disabled in config.")

    vin.start()
    print("[voice-loop] ready. Press the hotkey to dictate. Ctrl+C to quit.")
    try:
        vin.join()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
