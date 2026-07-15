"""
Voice input engine: global hotkey -> record mic -> local transcription ->
inject text into the target window.

Rock-solid design notes:
  - Recording (fast) runs in the key handler; transcription (slow) runs in a
    single worker thread fed by a queue, so start/stop can never be dropped and
    back-to-back dictations queue cleanly.
  - The focused window is captured when you START talking and refocused before
    pasting, so text can't land in the Start menu or a window that stole focus.
  - Mic open failures, odd sample rates, over-long holds, and Whisper's
    silence hallucinations are all handled instead of crashing or leaking junk.
"""
import queue
import threading
import time
import winsound

import numpy as np
import sounddevice as sd
from pynput import keyboard

import injector
import log

_MODMAP = {
    keyboard.Key.ctrl: "ctrl", keyboard.Key.ctrl_l: "ctrl", keyboard.Key.ctrl_r: "ctrl",
    keyboard.Key.cmd: "cmd", keyboard.Key.cmd_l: "cmd", keyboard.Key.cmd_r: "cmd",
    keyboard.Key.alt: "alt", keyboard.Key.alt_l: "alt", keyboard.Key.alt_r: "alt",
    keyboard.Key.alt_gr: "alt",
    keyboard.Key.shift: "shift", keyboard.Key.shift_l: "shift", keyboard.Key.shift_r: "shift",
    keyboard.Key.space: "space",
}
_ALIASES = {"win": "cmd", "windows": "cmd", "meta": "cmd", "super": "cmd", "control": "ctrl"}
_MODS = {"ctrl", "cmd", "alt", "shift"}

# Phrases Whisper commonly hallucinates on silence/noise; dropped only when the
# segment's no-speech probability is also high.
_FILLER = {"you", "thank you", "thanks for watching", "bye", "please subscribe",
           "thanks", "okay", "so"}


def _normalize(key):
    if key in _MODMAP:
        return _MODMAP[key]
    try:
        ch = key.char
        if ch:
            return ch.lower()
    except AttributeError:
        pass
    name = getattr(key, "name", None)
    return name.lower() if name else None


def _resample(audio, src, dst):
    if src == dst or audio.size == 0:
        return audio
    n = int(round(len(audio) * dst / src))
    if n <= 0:
        return audio
    xs = np.linspace(0.0, 1.0, len(audio), endpoint=False)
    xd = np.linspace(0.0, 1.0, n, endpoint=False)
    return np.interp(xd, xs, audio).astype(np.float32)


class _Recorder:
    def __init__(self, sr, device_index):
        self.sr = sr
        self.device_index = device_index
        self.capture_sr = sr
        self._frames = []
        self._stream = None
        self.active = False

    def _cb(self, indata, frames, t, status):
        self._frames.append(indata.copy())

    def _open(self, sr):
        kw = dict(samplerate=sr, channels=1, dtype="float32", callback=self._cb)
        if self.device_index is not None:
            kw["device"] = self.device_index
        self._stream = sd.InputStream(**kw)
        self._stream.start()

    def start(self):
        self._frames = []
        self.capture_sr = self.sr
        try:
            self._open(self.sr)
        except Exception:
            # Mic doesn't support 16k -> capture at its default rate, resample later.
            try:
                info = sd.query_devices(self.device_index, "input")
                default_sr = int(info["default_samplerate"])
            except Exception:
                default_sr = 48000
            self.capture_sr = default_sr
            self._open(default_sr)      # may raise -> caller handles
        self.active = True

    def stop(self):
        self.active = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if not self._frames:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(self._frames, axis=0).flatten()
        return _resample(audio, self.capture_sr, self.sr)


class VoiceInput:
    def __init__(self, cfg, on_activate=None, on_text=None):
        self.cfg = cfg
        stt = cfg["stt"]
        self.stt = stt
        self.sr = int(stt["sample_rate"])
        self.required = {_ALIASES.get(t.lower(), t.lower()) for t in cfg["hotkey"]}
        self.trigger = stt.get("trigger", "hold")
        self.inject = stt.get("inject", "paste")
        self.on_activate = on_activate
        self.on_text = on_text or self._inject_text
        self._rec = _Recorder(self.sr, stt.get("device_index"))
        self._model = None
        self._model_lock = threading.Lock()
        self._pressed = set()
        self._armed = False
        self._rec_lock = threading.Lock()
        self._timer = None
        self._cur_hwnd = None
        self._queue = queue.Queue()
        self._worker = None
        self._listener = None

    # -- model / transcription --------------------------------------------
    def _get_model(self):
        with self._model_lock:
            if self._model is None:
                from faster_whisper import WhisperModel
                log.info(f"[stt] loading model '{self.stt['model']}' "
                         f"({self.stt['compute_type']})...")
                self._model = WhisperModel(self.stt["model"], device="cpu",
                                           compute_type=self.stt["compute_type"])
                log.info("[stt] model ready.")
        return self._model

    def prewarm(self):
        threading.Thread(target=self._get_model, daemon=True).start()

    def _transcribe(self, audio):
        if audio.size < self.sr // 4:      # < 0.25s -> nothing useful
            return ""
        model = self._get_model()
        lang = self.stt.get("language") or None
        kw = dict(language=lang, beam_size=int(self.stt.get("beam_size", 5)),
                  vad_filter=bool(self.stt.get("vad_filter", True)))
        if kw["vad_filter"]:
            # Pad speech edges and require a longer silence so words at the
            # start/end of a phrase aren't clipped.
            kw["vad_parameters"] = dict(
                speech_pad_ms=int(self.stt.get("vad_speech_pad_ms", 400)),
                min_silence_duration_ms=int(self.stt.get("vad_min_silence_ms", 700)),
            )
        if self.stt.get("polish", True):
            import polish as _polish
            hints = self.stt.get("initial_prompt") or (
                "Software developer dictating: files like main.py, app.js, "
                "package.json; tools like git, npm, Docker.")
            kw["initial_prompt"] = hints
            try:
                kw["hotwords"] = _polish.build_hotwords(self.stt.get("vocabulary"))
            except Exception:
                pass
        try:
            segments, _ = model.transcribe(audio, **kw)
        except TypeError:
            kw.pop("hotwords", None)        # older faster-whisper
            segments, _ = model.transcribe(audio, **kw)
        drop = float(self.stt.get("drop_no_speech_prob", 0.8))
        parts = []
        for s in segments:
            txt = (s.text or "").strip()
            if not txt:
                continue
            nsp = getattr(s, "no_speech_prob", 0.0) or 0.0
            if nsp > drop and txt.lower().strip(" .!?,") in _FILLER:
                continue
            parts.append(txt)
        text = " ".join(parts).strip()
        if text.lower().strip(" .!?,") in _FILLER and len(text) <= 12:
            return ""
        if self.stt.get("polish", True) and text:
            import polish as _polish
            text = _polish.polish(text, self.stt.get("vocabulary"))
        return text

    # -- injection ---------------------------------------------------------
    def _inject_text(self, text, hwnd=None):
        self._wait_mods_released()
        target = hwnd if self.stt.get("target_window", "capture") == "capture" else None
        if self.inject == "type":
            if target:
                injector.focus_window(target)
                injector.release_modifiers()
            injector.type_text(text, float(self.stt.get("type_delay", 0.0)))
        else:
            injector.paste_text(text, target_hwnd=target,
                                collapse_newlines=self.stt.get("collapse_newlines", True))
        if self.stt.get("auto_enter"):
            injector.press_enter(target)

    def _wait_mods_released(self, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not (self._pressed & _MODS):
                return
            time.sleep(0.03)

    # -- feedback ----------------------------------------------------------
    def _beep(self, kind):
        if not self.stt.get("notify_start_stop") and kind in ("start", "stop"):
            return
        try:
            if kind == "start":
                winsound.Beep(880, 90)
            elif kind == "stop":
                winsound.Beep(440, 90)
            elif kind == "empty":
                winsound.Beep(330, 150)
            elif kind == "error":
                winsound.Beep(250, 120)
                winsound.Beep(200, 160)
        except RuntimeError:
            pass

    # -- recording orchestration ------------------------------------------
    def _cancel_timer(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _arm_timer(self):
        self._cancel_timer()
        secs = float(self.stt.get("max_record_seconds", 60))
        if secs > 0:
            self._timer = threading.Timer(secs, self._auto_stop)
            self._timer.daemon = True
            self._timer.start()

    def _auto_stop(self):
        log.info("[stt] max record duration reached; sending.")
        self._stop_and_process()

    def _start_record(self):
        with self._rec_lock:
            if self._rec.active:
                return
            self._cur_hwnd = injector.get_active_window()
            if self.on_activate:
                try:
                    self.on_activate()
                except Exception:
                    pass
            try:
                self._rec.start()
            except Exception:
                log.exception("[stt] microphone open failed")
                self._beep("error")
                return
            self._beep("start")
            self._arm_timer()
            hint = "release to send" if self.trigger == "hold" else "press again to stop"
            log.info(f"[stt] recording... ({hint})")
        # Fast-tap race: if the chord was already released, stop immediately.
        if self.trigger == "hold" and not (self.required <= self._pressed):
            self._stop_and_process()

    def _stop_and_process(self):
        with self._rec_lock:
            if not self._rec.active:
                return
            self._cancel_timer()
            try:
                audio = self._rec.stop()
            except Exception:
                log.exception("[stt] microphone stop failed")
                self._beep("error")
                return
            hwnd = self._cur_hwnd
        self._beep("stop")
        self._queue.put((audio, hwnd))

    def _toggle(self):
        if self._rec.active:
            self._stop_and_process()
        else:
            self._start_record()

    def _worker_loop(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            audio, hwnd = item
            try:
                text = self._transcribe(audio)
            except Exception:
                log.exception("[stt] transcription failed")
                self._beep("error")
                continue
            if not text:
                log.info("[stt] (no speech detected)")
                self._beep("empty")
                continue
            log.info(f"[stt] -> {text}")
            try:
                self.on_text(text, hwnd)
            except Exception:
                log.exception("[stt] injection failed")
                self._beep("error")

    # -- key handlers ------------------------------------------------------
    def _on_press(self, key):
        tok = _normalize(key)
        if tok:
            self._pressed.add(tok)
        if self.required and self.required <= self._pressed and not self._armed:
            self._armed = True
            if self.trigger == "hold":
                threading.Thread(target=self._start_record, daemon=True).start()
            else:
                threading.Thread(target=self._toggle, daemon=True).start()

    def _neutralize_start_menu(self):
        """Mask the Windows-key release with a Ctrl tap so the Start menu
        doesn't pop (the same trick AutoHotkey uses for Win-based hotkeys)."""
        if not self.stt.get("suppress_start_menu", True) or "cmd" not in self.required:
            return
        try:
            self._kbd.press(keyboard.Key.ctrl)
            self._kbd.release(keyboard.Key.ctrl)
        except Exception:
            pass

    def _on_release(self, key):
        self._pressed.discard(_normalize(key))
        if not (self.required <= self._pressed):
            was_armed = self._armed
            self._armed = False
            if was_armed:
                self._neutralize_start_menu()
            if self.trigger == "hold" and was_armed:
                threading.Thread(target=self._stop_and_process, daemon=True).start()

    # -- lifecycle ---------------------------------------------------------
    def start(self):
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        self._listener = keyboard.Listener(on_press=self._on_press,
                                           on_release=self._on_release)
        self._listener.start()
        return self._listener

    def join(self):
        if self._listener:
            self._listener.join()

    def stop(self):
        self._cancel_timer()
        self._queue.put(None)
        if self._listener:
            self._listener.stop()
