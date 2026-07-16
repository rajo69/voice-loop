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
import signal
import socket
import sys
import threading
import time

import log
from common import load_config, write_token
from input_engine import VoiceInput
from speaker import Speaker
from summarize import summarize_for_speech

CFG = load_config()
SHUTDOWN = threading.Event()


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
    def __init__(self, speaker, summary_cfg, host, port, on_answer=None,
                 token=""):
        super().__init__(daemon=True)
        self.speaker = speaker
        self.summary_cfg = summary_cfg
        self.host = host
        self.port = port
        self.on_answer = on_answer    # fires when Claude finishes (conv mode)
        self.token = token
        self._sock = None

    def bind(self):
        """Bind the port up front so a second instance fails loudly, not silently."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind((self.host, self.port))
        self._sock.listen(8)

    def run(self):
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

        if self.token and msg.get("token") != self.token:
            log.info("[out] dropped a message with a bad/missing token.")
            return

        cmd = msg.get("cmd")
        if cmd == "stop":
            self.speaker.interrupt()
            return
        if cmd == "shutdown":
            log.info("[voice-loop] shutdown requested.")
            SHUTDOWN.set()
            return
        if cmd == "ping":
            return

        text = msg.get("text", "")
        if not text:
            return
        if self.on_answer:
            try:
                self.on_answer()
            except Exception:
                pass
        spoken = summarize_for_speech(text, self.summary_cfg)
        if spoken:
            print(f"[out] speaking ({len(spoken)} chars): {spoken[:80]}...",
                  flush=True)
            kind = "question" if spoken.rstrip().endswith("?") else "done"
            self.speaker.speak(spoken, ping_kind=kind)


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

    # -- Mode 2 (conversation) lifecycle ------------------------------------
    conv_holder = {"mode": None}

    def notify_answer():
        m = conv_holder["mode"]
        if m is not None:
            m.on_claude_done()

    def conv_exited():
        # Spoken "exit conversation" -- the mode already stopped itself.
        conv_holder["mode"] = None
        vin.enabled = True

    def conv_toggle():
        m = conv_holder["mode"]
        if m is not None:
            conv_holder["mode"] = None
            m.stop()
            vin.enabled = True
            return
        import injector
        from conversation import ConversationMode
        hwnd = injector.get_active_window()
        mode = ConversationMode(CFG, vin._transcribe, speaker, hwnd,
                                on_exit=conv_exited)
        try:
            mode.start()
        except Exception:
            log.exception("[conv] could not start conversation mode")
            return
        conv_holder["mode"] = mode
        vin.enabled = False    # Mode 2 owns the mic; hold-to-talk pauses

    vin = VoiceInput(CFG, on_activate=barge_in, on_mode_toggle=conv_toggle)

    hk = "+".join(sorted(vin.required))
    log.info(f"[voice-loop] daemon starting. Hotkey: {hk}")
    if (CFG.get("conversation") or {}).get("enabled", True):
        log.info("[conv] Shift + triple-tap Win toggles conversation mode.")

    if speaker:
        log.info(f"[out] TTS engine: {speaker.engine_name}")
        _prewarm(speaker)
        d = CFG["daemon"]
        try:
            token = write_token()
        except OSError:
            log.error("[voice-loop] could not write the auth token; "
                      "socket runs unauthenticated.")
            token = ""
        server = Server(speaker, CFG["summary"], d["host"], int(d["port"]),
                        on_answer=notify_answer, token=token)
        try:
            server.bind()
        except OSError:
            log.error(f"[voice-loop] port {d['port']} already in use -- is the "
                      f"daemon already running? Exiting.")
            sys.exit(1)
        server.start()
    else:
        log.info("[out] TTS disabled in config.")

    vin.prewarm()   # load STT model now so the first dictation isn't slow
    vin.start()

    # -- tray icon (optional) ------------------------------------------------
    class _TrayCtrl:
        def interrupt_readback(self):
            if speaker:
                speaker.interrupt()

        def toggle_conversation(self):
            conv_toggle()

        def conversation_on(self):
            return conv_holder["mode"] is not None

        def dictation_enabled(self):
            return vin.enabled

        def set_dictation(self, on):
            vin.enabled = bool(on)

        def quit(self):
            SHUTDOWN.set()

    from tray import Tray
    tray = Tray(_TrayCtrl())
    if tray.start():
        log.info("[voice-loop] tray icon running.")

    log.info("[voice-loop] ready. Hold the hotkey to dictate. "
             "Ctrl+C (or stop.ps1) to quit.")

    # Wait on an interruptible loop rather than the listener's blocking join(),
    # so Ctrl+C reaches us even though pynput holds the input hook.
    try:
        signal.signal(signal.SIGINT, lambda *_: SHUTDOWN.set())
        signal.signal(signal.SIGBREAK, lambda *_: SHUTDOWN.set())
    except (ValueError, AttributeError, OSError):
        pass
    try:
        while not SHUTDOWN.is_set():
            time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    m = conv_holder["mode"]
    if m is not None:
        m.stop(chime=False)
    tray.stop()
    vin.stop()
    log.info("[voice-loop] stopped.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
