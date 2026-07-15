"""
voice-loop doctor: verify the whole Mode 1 chain works on this machine.

  python diagnose.py            # full check (records 3s from your mic)
  python diagnose.py --devices  # just list audio input devices

Checks: audio devices -> mic capture + level -> local transcription -> TTS.
"""
import sys
import time

import numpy as np
import sounddevice as sd

from common import load_config


def list_devices():
    print("Input devices:")
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            mark = " (default)" if i == sd.default.device[0] else ""
            print(f"  [{i}] {d['name']}  {int(d['default_samplerate'])}Hz{mark}")


def record(seconds, sr, device):
    print(f"\nRecording {seconds}s -- say something like "
          f"'open main dot py and fix the bug'...")
    for i in range(3, 0, -1):
        print(f"  {i}...", end=" ", flush=True)
        time.sleep(0.6)
    print("go!")
    audio = sd.rec(int(seconds * sr), samplerate=sr, channels=1,
                   dtype="float32", device=device)
    sd.wait()
    return audio.flatten()


def main():
    cfg = load_config()
    stt = cfg["stt"]

    if "--devices" in sys.argv:
        list_devices()
        return

    print("== voice-loop doctor ==\n")
    list_devices()

    sr = int(stt["sample_rate"])
    device = stt.get("device_index")
    try:
        audio = record(3.0, sr, device)
    except Exception as e:
        print(f"\n[FAIL] microphone capture error: {e}")
        print("       Try setting stt.device_index in config.json "
              "(see the device list above).")
        return

    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    print(f"\nMic level (peak): {peak:.3f}  ", end="")
    if peak < 0.01:
        print("[WARN] very quiet -- is the right mic selected / unmuted?")
    else:
        print("[OK]")

    print("\nTranscribing locally...")
    t = time.time()
    from faster_whisper import WhisperModel
    model = WhisperModel(stt["model"], device="cpu", compute_type=stt["compute_type"])
    segments, _ = model.transcribe(audio, language=stt.get("language") or None,
                                   vad_filter=True)
    text = " ".join(s.text.strip() for s in segments).strip()
    print(f"  heard: {text!r}   ({time.time() - t:.1f}s)")
    if not text:
        print("  [WARN] nothing transcribed -- speak louder or check the mic.")

    print("\nTesting text-to-speech...")
    try:
        from speaker import Speaker
        sp = Speaker(ping=False)
        print(f"  engine: {sp.engine_name}")
        sp.speak("Voice loop diagnostics complete. If you can hear this, "
                 "text to speech is working.")
        th = sp._thread
        if th:
            th.join()
        print("  [OK] spoke a test line.")
    except Exception as e:
        print(f"  [FAIL] TTS error: {e}")

    print("\nDone. If all checks passed, run ./start.ps1 and hold your hotkey.")


if __name__ == "__main__":
    main()
