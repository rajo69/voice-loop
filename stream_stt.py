"""
Incremental speech-to-text streaming.

Why: transcribing a whole clip only after key-release makes a long
utterance wait for its whole transcription. Here audio is segmented at natural pauses
WHILE it is still being recorded, and each closed segment is transcribed in
the background — so on release only the short tail is left to transcribe.

The same machinery drives Mode 2 (conversation mode): a long-lived session
whose closed segments are delivered via a callback instead of finalize().

No Windows / audio-device dependencies — pure numpy + threading, so the
segmentation and ordering logic is unit-testable anywhere.
"""
import queue
import threading

import numpy as np


def resample(audio, src, dst):
    """Linear-interpolation resample (good enough for 16k speech STT)."""
    if src == dst or audio.size == 0:
        return audio
    n = int(round(len(audio) * dst / src))
    if n <= 0:
        return audio
    xs = np.linspace(0.0, 1.0, len(audio), endpoint=False)
    xd = np.linspace(0.0, 1.0, n, endpoint=False)
    return np.interp(xd, xs, audio).astype(np.float32)


class EnergyEndpointer:
    """Frame-energy endpointer: split a live sample stream at pauses.

    feed(samples) -> list of closed segments (np.float32 arrays).
    flush() -> the remaining buffered audio if it contains speech, else None.

    A segment closes after `min_silence_ms` of quiet following at least
    `min_speech_ms` of speech. Segments keep their surrounding silence --
    Whisper's own VAD handles padding, and it keeps this logic simple.
    """

    def __init__(self, sr=16000, frame_ms=30, threshold=0.01,
                 min_silence_ms=600, min_speech_ms=200, max_leading_s=2.0):
        self.sr = int(sr)
        self.frame = max(1, int(self.sr * frame_ms / 1000))
        self.threshold = float(threshold)
        self.min_silence_frames = max(1, int(min_silence_ms / frame_ms))
        self.min_speech_frames = max(1, int(min_speech_ms / frame_ms))
        self.max_leading = int(self.sr * max_leading_s)
        self._buf = np.zeros(0, dtype=np.float32)
        self._pending = np.zeros(0, dtype=np.float32)  # < one frame remainder
        self._speech_frames = 0
        self._silence_run = 0

    def _frames_of(self, samples):
        data = np.concatenate([self._pending, samples]) if self._pending.size \
            else samples
        n_full = (data.size // self.frame) * self.frame
        self._pending = data[n_full:]
        return data[:n_full].reshape(-1, self.frame) if n_full else \
            np.zeros((0, self.frame), dtype=np.float32)

    def feed(self, samples):
        samples = np.asarray(samples, dtype=np.float32).flatten()
        if samples.size == 0:
            return []
        segments = []
        for fr in self._frames_of(samples):
            self._buf = np.concatenate([self._buf, fr])
            if float(np.sqrt(np.mean(fr * fr))) > self.threshold:
                self._speech_frames += 1
                self._silence_run = 0
            else:
                self._silence_run += 1
            if (self._speech_frames >= self.min_speech_frames
                    and self._silence_run >= self.min_silence_frames):
                segments.append(self._buf)
                self._reset()
            elif (self._speech_frames == 0
                    and self._buf.size > self.max_leading):
                # No speech yet: keep only a short tail so silence before the
                # first word can't grow the buffer without bound.
                self._buf = self._buf[-self.frame * self.min_silence_frames:]
        return segments

    def flush(self):
        tail = None
        if self._speech_frames >= 1 and self._buf.size:
            leftover = np.concatenate([self._buf, self._pending]) \
                if self._pending.size else self._buf
            tail = leftover
        self._reset()
        self._pending = np.zeros(0, dtype=np.float32)
        return tail

    def _reset(self):
        self._buf = np.zeros(0, dtype=np.float32)
        self._speech_frames = 0
        self._silence_run = 0


class StreamSession:
    """One recording's incremental transcription.

    feed(samples) from the audio callback; segments closed by the endpointer
    are transcribed in order on a private worker thread. finalize() flushes
    the tail, waits for in-flight work, and returns the joined text.

    `on_segment(text)` (optional) fires as each segment's text lands --
    conversation mode uses this for live drafting.
    """

    def __init__(self, transcribe_fn, sr=16000, on_segment=None, ep=None):
        self._transcribe = transcribe_fn
        self.on_segment = on_segment
        self._ep = ep or EnergyEndpointer(sr=sr)
        self._q = queue.Queue()
        self._texts = []
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _worker(self):
        while True:
            seg = self._q.get()
            if seg is None:
                break
            try:
                text = (self._transcribe(seg) or "").strip()
            except Exception:
                text = ""
            if text:
                self._texts.append(text)
                if self.on_segment:
                    try:
                        self.on_segment(text)
                    except Exception:
                        pass
        self._done.set()

    def feed(self, samples):
        for seg in self._ep.feed(samples):
            self._q.put(seg)

    def finalize(self, timeout=60.0):
        tail = self._ep.flush()
        if tail is not None:
            self._q.put(tail)
        self._q.put(None)
        self._done.wait(timeout)
        return " ".join(self._texts).strip()

    def abort(self):
        """Discard pending work (used when a recording is cancelled)."""
        try:
            while True:
                self._q.get_nowait()
        except queue.Empty:
            pass
        self._q.put(None)
