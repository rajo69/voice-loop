"""
Interruptible, single-instance speaker.

speak(text) preempts any in-progress speech (barge-in) and plays a ping
followed by the synthesized audio. Kokoro audio is played through
sounddevice (stoppable mid-stream); SAPI is played via a PowerShell child
process that we can terminate.
"""
import threading
import time
import winsound

import sounddevice as sd

from tts import make_engine, SapiEngine


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

    def interrupt(self):
        """Stop whatever is currently playing."""
        self._stop.set()
        try:
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

    def speak(self, text):
        if not text:
            return
        self.interrupt()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(text, self._stop),
                                        daemon=True)
        self._thread.start()

    # -- internals ---------------------------------------------------------
    def _run(self, text, stop):
        if self.ping and not stop.is_set():
            try:
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
        result = self.engine.synth(text)
        if stop.is_set() or not result:
            return
        samples, sr = result
        if samples is None or len(samples) == 0:
            return
        sd.play(samples, sr)
        duration = len(samples) / float(sr)
        deadline = time.time() + duration + 0.2
        while time.time() < deadline:
            if stop.is_set():
                sd.stop()
                return
            time.sleep(0.05)
        try:
            sd.wait()
        except Exception:
            pass

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
