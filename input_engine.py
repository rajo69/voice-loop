"""
Voice input engine: global hotkey -> record mic -> local transcription ->
type text into the focused window.

Exposed as a class so the daemon can wire an `on_activate` callback (used to
interrupt readback the moment you start talking -- barge-in).
"""
import threading
import time
import winsound

import numpy as np
import sounddevice as sd
from pynput import keyboard

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


class _Recorder:
    def __init__(self, sr, device_index):
        self.sr = sr
        self.device_index = device_index
        self._frames = []
        self._stream = None
        self.active = False

    def _cb(self, indata, frames, t, status):
        self._frames.append(indata.copy())

    def start(self):
        self._frames = []
        kw = dict(samplerate=self.sr, channels=1, dtype="float32", callback=self._cb)
        if self.device_index is not None:
            kw["device"] = self.device_index
        self._stream = sd.InputStream(**kw)
        self._stream.start()
        self.active = True

    def stop(self):
        self.active = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if not self._frames:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(self._frames, axis=0).flatten()


class VoiceInput:
    def __init__(self, cfg, on_activate=None, on_text=None):
        self.cfg = cfg
        stt = cfg["stt"]
        self.stt = stt
        self.sr = int(stt["sample_rate"])
        self.required = {_ALIASES.get(t.lower(), t.lower()) for t in cfg["hotkey"]}
        self.trigger = stt.get("trigger", "hold")   # "hold" or "toggle"
        self.inject = stt.get("inject", "paste")     # "paste" or "type"
        self.on_activate = on_activate            # called when recording starts
        self.on_text = on_text or self._inject_text  # default: inject into focus
        self._rec = _Recorder(self.sr, stt.get("device_index"))
        self._model = None
        self._model_lock = threading.Lock()
        self._pressed = set()
        self._armed = False
        self._busy = threading.Lock()
        self._kbd = keyboard.Controller()
        self._listener = None

    # -- model / transcription --------------------------------------------
    def _get_model(self):
        with self._model_lock:
            if self._model is None:
                from faster_whisper import WhisperModel
                print(f"[stt] loading model '{self.stt['model']}' "
                      f"({self.stt['compute_type']})...", flush=True)
                self._model = WhisperModel(self.stt["model"], device="cpu",
                                           compute_type=self.stt["compute_type"])
                print("[stt] model ready.", flush=True)
        return self._model

    def _transcribe(self, audio):
        if audio.size < self.sr // 4:
            return ""
        model = self._get_model()
        lang = self.stt.get("language") or None
        segments, _ = model.transcribe(audio, language=lang,
                                       beam_size=int(self.stt.get("beam_size", 1)),
                                       vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()

    # -- typing ------------------------------------------------------------
    def _wait_mods_released(self, timeout=2.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not (self._pressed & _MODS):
                return
            time.sleep(0.03)

    def _inject_text(self, text):
        self._wait_mods_released()
        import injector
        if self.inject == "type":
            injector.type_text(text, float(self.stt.get("type_delay", 0.0)))
        else:
            injector.paste_text(text)
        if self.stt.get("auto_enter"):
            injector.press_enter()

    def _beep(self, kind):
        if not self.stt.get("notify_start_stop"):
            return
        try:
            winsound.Beep(880 if kind == "start" else 440, 90)
        except RuntimeError:
            pass

    # -- orchestration -----------------------------------------------------
    def _start_record(self):
        if not self._busy.acquire(blocking=False):
            return
        try:
            if self._rec.active:
                return
            if self.on_activate:
                try:
                    self.on_activate()   # barge-in: stop any readback
                except Exception:
                    pass
            self._beep("start")
            self._rec.start()
            hint = "release to send" if self.trigger == "hold" else "press again to stop"
            print(f"[stt] recording... ({hint})", flush=True)
        finally:
            self._busy.release()

    def _stop_and_process(self):
        if not self._busy.acquire(blocking=False):
            return
        try:
            if not self._rec.active:
                return
            audio = self._rec.stop()
            self._beep("stop")
            print("[stt] transcribing...", flush=True)
            text = self._transcribe(audio)
            if text:
                print(f"[stt] -> {text}", flush=True)
                self.on_text(text)
            else:
                print("[stt] (no speech detected)", flush=True)
        finally:
            self._busy.release()

    def _toggle(self):
        if self._rec.active:
            self._stop_and_process()
        else:
            self._start_record()

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

    def _on_release(self, key):
        self._pressed.discard(_normalize(key))
        if not (self.required <= self._pressed):
            was_armed = self._armed
            self._armed = False
            if self.trigger == "hold" and was_armed and self._rec.active:
                threading.Thread(target=self._stop_and_process, daemon=True).start()

    def start(self):
        self._listener = keyboard.Listener(on_press=self._on_press,
                                           on_release=self._on_release)
        self._listener.start()
        return self._listener

    def join(self):
        if self._listener:
            self._listener.join()

    def stop(self):
        if self._listener:
            self._listener.stop()
