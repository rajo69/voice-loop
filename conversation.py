"""
Mode 2 -- hands-free conversation with Claude Code.

Entered via Shift + triple-tap Win (see input_engine) or left by saying
"exit conversation". While active:

  LISTENING  you talk; each utterance is transcribed + polished and pasted
             live into the captured Claude Code window. Say "claude go" to
             press Enter hands-free; "claude scratch" clears the draft.
  RUNNING    Claude is executing. Say "claude hold" to press Esc and steer;
             content speech is ignored (configurable) until Claude finishes.
  readback   when Claude answers, the daemon speaks it. Half-duplex rule:
             while the speaker is playing, content speech is dropped (the
             mic hears our own TTS) but commands still work -- "claude stop"
             halts the readback.

The audio plumbing lives here; all decision logic is in handle_text(), which
is pure and unit-testable with a fake injector/speaker.
"""
import queue
import threading

try:                                    # Windows-only; absent on CI/Linux
    import winsound
except ImportError:
    winsound = None
try:                                    # needs PortAudio; absent on CI/Linux
    import sounddevice as sd
except (ImportError, OSError):
    sd = None

import commands as _commands
import log
from stream_stt import EnergyEndpointer, resample

LISTENING = "listening"
RUNNING = "running"


def _chime(kind):
    if winsound is None:
        return
    try:
        if kind == "enter":         # ascending: conversation is on
            winsound.Beep(660, 90)
            winsound.Beep(990, 120)
        elif kind == "exit":        # descending: back to normal
            winsound.Beep(990, 90)
            winsound.Beep(660, 120)
        elif kind == "sent":        # prompt submitted
            winsound.Beep(1200, 80)
        elif kind == "held":        # execution interrupted
            winsound.Beep(500, 80)
            winsound.Beep(500, 80)
    except RuntimeError:
        pass


class ConversationMode:
    """One active conversation session bound to a Claude Code window."""

    def __init__(self, cfg, transcribe_fn, speaker, hwnd,
                 on_exit=None, inj=None):
        conv = cfg.get("conversation") or {}
        stt = cfg.get("stt") or {}
        self.commands = conv.get("commands") or None   # None -> defaults
        self.paste_while_running = bool(conv.get("paste_while_running", False))
        self.sr = int(stt.get("sample_rate", 16000))
        self.device_index = stt.get("device_index")
        self.collapse_newlines = bool(stt.get("collapse_newlines", True))
        scfg = stt.get("stream") or {}
        self._ep = EnergyEndpointer(
            sr=self.sr,
            threshold=float(scfg.get("threshold", 0.01)),
            min_silence_ms=int(conv.get("min_silence_ms",
                                        scfg.get("min_silence_ms", 600))),
            min_speech_ms=int(scfg.get("min_speech_ms", 200)))

        self._transcribe = transcribe_fn
        self.speaker = speaker
        self.hwnd = hwnd
        self.on_exit = on_exit
        if inj is None:                 # injectable for tests (pynput-free)
            import injector as inj      # noqa: PLC0415
        self._inj = inj

        self.state = LISTENING
        self.active = False
        self._q = queue.Queue()
        self._worker = None
        self._stream = None
        self._capture_sr = self.sr

    # -- lifecycle -----------------------------------------------------------
    def start(self):
        if sd is None:
            raise RuntimeError("sounddevice unavailable")
        self.active = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        self._open_stream()
        _chime("enter")
        log.info("[conv] conversation mode ON (say 'exit conversation' or "
                 "triple-tap to leave)")

    def _open_stream(self):
        def cb(indata, frames, t, status):
            if not self.active:
                return
            try:
                chunk = resample(indata.flatten(), self._capture_sr, self.sr)
                for seg in self._ep.feed(chunk):
                    self._q.put(seg)
            except Exception:
                pass

        kw = dict(samplerate=self.sr, channels=1, dtype="float32", callback=cb)
        if self.device_index is not None:
            kw["device"] = self.device_index
        self._capture_sr = self.sr
        try:
            self._stream = sd.InputStream(**kw)
            self._stream.start()
        except Exception:
            try:
                info = sd.query_devices(self.device_index, "input")
                self._capture_sr = int(info["default_samplerate"])
            except Exception:
                self._capture_sr = 48000
            kw["samplerate"] = self._capture_sr
            self._stream = sd.InputStream(**kw)
            self._stream.start()

    def stop(self, chime=True):
        if not self.active:
            return
        self.active = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._q.put(None)
        if chime:
            _chime("exit")
        log.info("[conv] conversation mode OFF")

    # -- processing ------------------------------------------------------------
    def _worker_loop(self):
        while True:
            seg = self._q.get()
            if seg is None:
                return
            try:
                text = (self._transcribe(seg) or "").strip()
            except Exception:
                log.exception("[conv] transcription failed")
                continue
            if text:
                self.handle_text(text)

    def _speaking(self):
        sp = self.speaker
        return bool(sp is not None and getattr(sp, "speaking", False))

    def handle_text(self, text):
        """Decide what one transcribed utterance means. Pure logic."""
        action, remaining = _commands.parse(text, self.commands)
        speaking = self._speaking()
        log.info(f"[conv] heard: {text!r} -> action={action}")

        if action == "exit":
            self._exit()
            return
        if action == "stop":
            if self.speaker is not None:
                self.speaker.interrupt()
            return
        if action == "go":
            if self.state != LISTENING:
                return
            if self.speaker is not None:
                self.speaker.interrupt()
            if remaining and not speaking:
                self._paste(remaining)
            self._inj.press_enter(self.hwnd)
            self.state = RUNNING
            _chime("sent")
            return
        if action == "hold":
            if self.speaker is not None:
                self.speaker.interrupt()
            if self.state == RUNNING:
                self._inj.press_escape(self.hwnd)   # Claude Code's interrupt
                self.state = LISTENING
                _chime("held")
            return
        if action == "scratch":
            if self.state == LISTENING and not speaking:
                self._inj.press_escape(self.hwnd)   # Esc clears the draft
            return

        # Plain content: live drafting. Half-duplex -- while our TTS plays the
        # mic hears the readback, so content is dropped (commands still work).
        if speaking:
            return
        if self.state == RUNNING and not self.paste_while_running:
            return
        if remaining:
            self._paste(remaining)

    def _paste(self, text):
        self._inj.paste_text(text + " ", target_hwnd=self.hwnd,
                             collapse_newlines=self.collapse_newlines)

    def on_claude_done(self):
        """Called by the daemon when the Stop hook reports Claude finished."""
        if self.state == RUNNING:
            self.state = LISTENING

    def _exit(self):
        self.stop(chime=True)
        if self.on_exit:
            try:
                self.on_exit()
            except Exception:
                pass
