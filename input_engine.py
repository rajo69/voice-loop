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

try:                                    # Windows-only; absent on CI/Linux
    import winsound
except ImportError:
    winsound = None

import numpy as np
import sounddevice as sd
from pynput import keyboard

import injector
import log
import stream_stt

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


_resample = stream_stt.resample


class _Recorder:
    def __init__(self, sr, device_index):
        self.sr = sr
        self.device_index = device_index
        self.capture_sr = sr
        self._frames = []
        self._stream = None
        self.active = False
        self.on_chunk = None   # optional live-audio tap (incremental STT)

    def _cb(self, indata, frames, t, status):
        self._frames.append(indata.copy())
        if self.on_chunk is not None:
            try:
                self.on_chunk(indata.flatten())
            except Exception:
                pass

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
    def __init__(self, cfg, on_activate=None, on_text=None,
                 on_mode_toggle=None):
        self.cfg = cfg
        stt = dict(cfg["stt"])
        if stt.get("speed_profile", "accurate") == "fast":
            # Trade accuracy for latency on weak machines.
            stt["model"] = "base.en"
            stt["beam_size"] = 2
        self.stt = stt
        conv = cfg.get("conversation") or {}
        self.enabled = True                     # False while Mode 2 owns the mic
        self.on_mode_toggle = on_mode_toggle    # Shift + triple-tap Win
        self._tap_enabled = bool(conv.get("enabled", True)) and on_mode_toggle
        self._hold_confirm_s = float(conv.get("hold_confirm_ms", 180)) / 1000.0
        self._triple_tap_s = float(conv.get("triple_tap_ms", 1200)) / 1000.0
        self._hold_timer = None
        self._hold_confirmed = False
        self._chord_t0 = 0.0
        self._taps = []
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
        self._session = None
        self._queue = queue.Queue()
        self._worker = None
        self._listener = None
        self._kbd = keyboard.Controller()   # used by _neutralize_start_menu

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
        beam = int(self.stt.get("beam_size", 5))
        if self.stt.get("adaptive_beam", True) and audio.size < self.sr * 4:
            beam = min(beam, 2)   # short utterances don't need a wide search
        kw = dict(language=lang, beam_size=beam,
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
        if winsound is None:
            return
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

    # -- incremental transcription ------------------------------------------
    def _make_session(self):
        """Create a StreamSession that transcribes pauses mid-recording, and
        tap the recorder so live audio feeds it. Returns None when disabled."""
        if not self.stt.get("incremental", True):
            self._rec.on_chunk = None
            return None
        scfg = self.stt.get("stream") or {}
        ep = stream_stt.EnergyEndpointer(
            sr=self.sr,
            threshold=float(scfg.get("threshold", 0.01)),
            min_silence_ms=int(scfg.get("min_silence_ms", 600)),
            min_speech_ms=int(scfg.get("min_speech_ms", 200)))
        session = stream_stt.StreamSession(self._transcribe, sr=self.sr, ep=ep)
        rec = self._rec

        def _tap(chunk):
            session.feed(_resample(chunk, rec.capture_sr, rec.sr))

        rec.on_chunk = _tap
        return session

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
            self._session = self._make_session()
            try:
                self._rec.start()
            except Exception:
                log.exception("[stt] microphone open failed")
                self._rec.on_chunk = None
                self._session = None
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
                audio = self._rec.stop()   # stops the stream: no more taps
            except Exception:
                log.exception("[stt] microphone stop failed")
                self._beep("error")
                return
            finally:
                self._rec.on_chunk = None
            hwnd = self._cur_hwnd
            session, self._session = self._session, None
        self._beep("stop")
        if session is not None:
            self._queue.put(("session", session, hwnd))
        else:
            self._queue.put(("audio", audio, hwnd))

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
            kind, payload, hwnd = item
            try:
                if kind == "session":
                    # Segments were transcribed during the hold; this just
                    # finishes the tail and joins the pieces.
                    text = payload.finalize()
                else:
                    text = self._transcribe(payload)
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
            self._chord_t0 = time.time()
            self._hold_confirmed = False
            if self.trigger == "hold":
                if self._tap_enabled:
                    # Wait a beat: a quick release is a tap (mode gesture),
                    # a sustained press is hold-to-talk.
                    self._hold_timer = threading.Timer(self._hold_confirm_s,
                                                       self._confirm_hold)
                    self._hold_timer.daemon = True
                    self._hold_timer.start()
                else:
                    self._confirm_hold()
            else:
                threading.Thread(target=self._toggle, daemon=True).start()

    def _confirm_hold(self):
        if not (self.required <= self._pressed):
            return                       # already released -> it was a tap
        self._hold_confirmed = True
        if self.enabled:
            threading.Thread(target=self._start_record, daemon=True).start()

    def _register_tap(self):
        now = time.time()
        self._taps = [t for t in self._taps if now - t <= self._triple_tap_s]
        self._taps.append(now)
        if len(self._taps) >= 3:
            self._taps = []
            threading.Thread(target=self._fire_mode_toggle, daemon=True).start()

    def _fire_mode_toggle(self):
        try:
            self.on_mode_toggle()
        except Exception:
            log.exception("[conv] mode toggle failed")

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
                if self._hold_timer is not None:
                    self._hold_timer.cancel()
                    self._hold_timer = None
                if self._hold_confirmed:
                    threading.Thread(target=self._stop_and_process,
                                     daemon=True).start()
                elif (self._tap_enabled and
                      time.time() - self._chord_t0 < self._hold_confirm_s * 2):
                    self._register_tap()

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
