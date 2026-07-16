"""
Interruptible, single-instance speaker.

speak(text) preempts any in-progress speech (barge-in) and plays a ping
followed by the synthesized audio. Kokoro audio is played through
sounddevice (stoppable mid-stream); SAPI is played via a PowerShell child
process that we can terminate.
"""
import queue
import re
import threading
import time

try:                                    # Windows-only; absent on CI/Linux
    import winsound
except ImportError:
    winsound = None
try:                                    # needs PortAudio; absent on CI/Linux
    import sounddevice as sd
except (ImportError, OSError):
    sd = None

from tts import make_engine, SapiEngine

_SENT = re.compile(r"(?<=[.!?])\s+")


def _chunks(text, min_len=90, max_len=200):
    """Group sentences into chunks for streaming synthesis.

    The FIRST chunk is a single sentence so audio starts fast; later sentences
    are merged (~min_len) so each synthesizes before the previous finishes
    playing (no mid-stream gaps), and over-long sentences are word-wrapped.
    """
    # hard-wrap over-long sentences at word boundaries first
    parts = []
    for s in (x.strip() for x in _SENT.split(text) if x.strip()):
        while len(s) > max_len:
            cut = s.rfind(" ", 0, max_len)
            cut = cut if cut > 0 else max_len
            parts.append(s[:cut].strip())
            s = s[cut:].strip()
        if s:
            parts.append(s)

    out, buf = [], ""
    for s in parts:
        if not buf:
            buf = s
        elif len(buf) + 1 + len(s) <= max_len:
            buf = f"{buf} {s}"
        else:
            out.append(buf)
            buf = s
        # first chunk: flush after one sentence (fast start); then flush at min_len
        if (not out) or len(buf) >= min_len:
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


class Speaker:
    def __init__(self, engine=None, ping=True):
        self.engine = engine or make_engine()
        self.ping = ping
        self._thread = None
        self._stop = threading.Event()
        self._proc = None
        self._lock = threading.Lock()

    @property
    def engine_name(self):
        return getattr(self.engine, "name", "unknown")

    @property
    def speaking(self):
        """True while a readback is playing (conversation half-duplex gate)."""
        t = self._thread
        return bool(t is not None and t.is_alive() and not self._stop.is_set())

    def interrupt(self):
        """Stop whatever is currently playing."""
        self._stop.set()
        try:
            if sd is not None:
                sd.stop()
        except Exception:
            pass
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.5)

    def speak(self, text, ping_kind="done"):
        if not text:
            return
        self.interrupt()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run,
                                        args=(text, self._stop, ping_kind),
                                        daemon=True)
        self._thread.start()

    # -- internals ---------------------------------------------------------
    def _run(self, text, stop, ping_kind="done"):
        if self.ping and winsound is not None and not stop.is_set():
            try:
                if ping_kind == "question":     # rising: Claude needs input
                    winsound.Beep(660, 90)
                    winsound.Beep(880, 120)
                else:
                    winsound.Beep(660, 120)
            except RuntimeError:
                pass
        if stop.is_set():
            return
        try:
            if isinstance(self.engine, SapiEngine):
                self._play_sapi(text, stop)
            else:
                self._play_samples(text, stop)
        except Exception as e:
            print(f"[tts] playback error: {e}", flush=True)

    def _play_samples(self, text, stop):
        if sd is None:
            return
        # Pipelined streaming: a producer thread synthesizes the NEXT sentence
        # while the current one is playing, so there are no gaps between them.
        chunks = _chunks(text)
        audio_q = queue.Queue(maxsize=2)
        SENTINEL = object()

        def producer():
            for ch in chunks:
                if stop.is_set():
                    break
                try:
                    res = self.engine.synth(ch)
                except Exception as e:
                    print(f"[tts] synth error: {e}", flush=True)
                    continue
                if stop.is_set():
                    break
                if res and res[0] is not None and len(res[0]) > 0:
                    while not stop.is_set():
                        try:
                            audio_q.put(res, timeout=0.1)
                            break
                        except queue.Full:
                            continue
            try:
                audio_q.put(SENTINEL, timeout=0.5)
            except queue.Full:
                pass

        threading.Thread(target=producer, daemon=True).start()

        while not stop.is_set():
            try:
                item = audio_q.get(timeout=0.1)
            except queue.Empty:
                continue
            if item is SENTINEL:
                return
            samples, sr = item
            sd.play(samples, sr)
            deadline = time.time() + len(samples) / float(sr)   # gapless hand-off
            while time.time() < deadline:
                if stop.is_set():
                    sd.stop()
                    return
                time.sleep(0.02)

    def _play_sapi(self, text, stop):
        import subprocess
        cmd = self.engine.build_command(text)
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, text=True, encoding="utf-8",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        with self._lock:
            self._proc = proc
        try:
            proc.stdin.write(text)
            proc.stdin.close()
        except Exception:
            pass
        while proc.poll() is None:
            if stop.is_set():
                try:
                    proc.terminate()
                except Exception:
                    pass
                return
            time.sleep(0.05)
        with self._lock:
            if self._proc is proc:
                self._proc = None
