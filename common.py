"""Shared helpers: config loading and paths."""
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")

_DEFAULTS = {
    "hotkey": ["shift", "cmd"],
    "stt": {
        "model": "small.en",
        "compute_type": "int8",
        "language": "en",
        "sample_rate": 16000,
        "device_index": None,
        "beam_size": 5,
        "adaptive_beam": True,
        "speed_profile": "accurate",
        "incremental": True,
        "stream": {
            "threshold": 0.01,
            "min_silence_ms": 600,
            "min_speech_ms": 200,
        },
        "vad_filter": True,
        "vad_speech_pad_ms": 400,
        "vad_min_silence_ms": 700,
        "polish": True,
        "vocabulary": [],
        "initial_prompt": "",
        "trigger": "hold",
        "inject": "paste",
        "target_window": "capture",
        "collapse_newlines": True,
        "max_record_seconds": 60,
        "drop_no_speech_prob": 0.8,
        "suppress_start_menu": True,
        "auto_enter": False,
        "type_delay": 0.0,
        "notify_start_stop": True,
    },
    "conversation": {
        "enabled": True,
        "triple_tap_ms": 1200,
        "hold_confirm_ms": 180,
        "min_silence_ms": 600,
        "paste_while_running": False,
        "commands": None,
    },
    "summary": {
        "mode": "extractive",
        "style": "conversational",
        "short_threshold_chars": 350,
        "max_sentences": 6,
        "max_chars": 1000,
        "skip_code_blocks": True,
    },
    "tts": {
        "enabled": True,
        "engine": "auto",
        "ping": True,
        "kokoro": {
            "model_path": "models/kokoro-v1.0.onnx",
            "voices_path": "models/voices-v1.0.bin",
            "voice": "af_heart",
            "speed": 1.0,
            "lang": "en-us",
        },
        "sapi": {"rate": 1, "volume": 100, "voice": None},
    },
    "daemon": {"host": "127.0.0.1", "port": 8765},
}


def _merge(base, override):
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (json.JSONDecodeError, OSError):
            cfg = {}
    return _merge(_DEFAULTS, cfg)


def abspath(p):
    """Resolve a path from config relative to the project root."""
    if not p:
        return p
    return p if os.path.isabs(p) else os.path.join(ROOT, p)
