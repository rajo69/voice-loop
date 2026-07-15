"""
TTS engine abstraction.

Two engines share one interface:
  - synth(text) -> (samples: np.float32[], sample_rate: int) | None
    Kokoro returns audio samples we play ourselves (so playback is
    interruptible via sounddevice). SAPI returns None from synth and is
    handled by the speaker's process-based fallback path.

make_engine() picks Kokoro when its model files exist, else SAPI.
"""
import os

from common import load_config, abspath

_CFG = load_config()["tts"]


class KokoroEngine:
    name = "kokoro"

    def __init__(self, kcfg):
        self.model_path = abspath(kcfg["model_path"])
        self.voices_path = abspath(kcfg["voices_path"])
        self.voice = kcfg.get("voice", "af_heart")
        self.speed = float(kcfg.get("speed", 1.0))
        self.lang = kcfg.get("lang", "en-us")
        self._kokoro = None

    @staticmethod
    def available(kcfg):
        return (os.path.exists(abspath(kcfg["model_path"]))
                and os.path.exists(abspath(kcfg["voices_path"])))

    def _load(self):
        if self._kokoro is None:
            from kokoro_onnx import Kokoro
            self._kokoro = Kokoro(self.model_path, self.voices_path)
        return self._kokoro

    def synth(self, text):
        import numpy as np
        k = self._load()
        samples, sr = k.create(text, voice=self.voice,
                               speed=self.speed, lang=self.lang)
        samples = np.asarray(samples, dtype=np.float32)
        return samples, int(sr)


class SapiEngine:
    """Windows System.Speech fallback (no samples; plays via PowerShell)."""
    name = "sapi"

    def __init__(self, scfg):
        self.rate = int(scfg.get("rate", 1))
        self.volume = int(scfg.get("volume", 100))
        self.voice = scfg.get("voice")

    def synth(self, text):
        return None  # handled by Speaker's subprocess path

    def build_command(self, text):
        voice_line = ""
        if self.voice:
            safe = str(self.voice).replace("'", "''")
            voice_line = f"try {{ $s.SelectVoice('{safe}') }} catch {{}}"
        script = (
            "Add-Type -AssemblyName System.Speech\n"
            "$t = [Console]::In.ReadToEnd()\n"
            "if ([string]::IsNullOrWhiteSpace($t)) { exit 0 }\n"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
            f"$s.Rate = {self.rate}\n$s.Volume = {self.volume}\n{voice_line}\n"
            "$s.Speak($t)\n"
        )
        return ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]


def make_engine(cfg=None):
    cfg = cfg or _CFG
    choice = cfg.get("engine", "auto")
    kcfg, scfg = cfg["kokoro"], cfg["sapi"]
    if choice == "kokoro" or (choice == "auto" and KokoroEngine.available(kcfg)):
        try:
            return KokoroEngine(kcfg)
        except Exception:
            pass
    return SapiEngine(scfg)
