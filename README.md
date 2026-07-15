# voice-loop

A **two-way voice interface for the Claude Code CLI** — talk instead of type, listen instead of read. Fully local and offline (after a one-time model download).

- **Input:** press **Shift + Win**, speak, press it again to stop. Transcribed locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and typed into your prompt. Press **Enter** to send. *(Already have Wispr Flow? You can use that for input instead — see "Pluggable input".)*
- **Output:** when Claude finishes, you hear a **ping** and a **spoken summary** — read with the natural-sounding [Kokoro-82M](https://github.com/thewh1teagle/kokoro-onnx) voice (falls back to Windows SAPI if the model isn't present). Code blocks and file paths are skipped so it stays listenable.

## Architecture

One warm daemon runs both halves; the Claude Code hook is a thin, non-blocking client.

```
[Shift+Win] ─▶ input_engine ─▶ faster-whisper ─▶ types text ─▶ you press Enter
                    │ (barge-in: talking interrupts any readback)
                    ▼
Claude answers ─▶ Stop hook ─(socket, ~0.1s)─▶  voiced.py daemon
                                                   │
                                        summarize.py (extractive)
                                                   │
                                        speaker.py ─▶ Kokoro / SAPI
                                        (interruptible; new answer preempts old)
```

Why a daemon: the Stop hook only *sends text over a socket and exits* (~0.1s), so Claude Code is never blocked while a long answer is spoken. The daemon keeps the TTS model warm and plays speech that can be interrupted.

### Files
| File | Role |
|------|------|
| `voiced.py` | The daemon: input listener + readback socket server. |
| `input_engine.py` | Hotkey → record → transcribe → type. |
| `summarize.py` | Markdown → short spoken summary (no mid-sentence cutoff). |
| `tts.py` | Engine abstraction (Kokoro / SAPI). |
| `speaker.py` | Interruptible, single-instance playback. |
| `hooks/stop_hook.py` | Thin Stop-hook client (falls back to `speak.py` if daemon is down). |
| `speak.py` | One-shot readback for testing / fallback. |

## Install

```powershell
./install.ps1        # venv, deps, STT model, Kokoro model (~350MB download, one-time)
./register_hook.ps1  # adds the readback hook to ~/.claude/settings.json
```
Restart Claude Code so it picks up the hook.

## Use

1. Start the daemon (leave it running):
   ```powershell
   ./start.ps1
   ```
2. Open Claude Code in another terminal.
3. **Hold Shift + Win**, speak, **release** → your words are pasted into the prompt → press **Enter** to send. *(Set `stt.trigger` to `"toggle"` for press-once-to-start, press-again-to-stop instead.)*
4. Claude answers → ping + spoken summary, **streamed** so it starts within ~1s. Start talking (or send a new prompt) to cut a readback short.

## Configuration — `config.json`

| Key | Meaning |
|-----|---------|
| `hotkey` | Dictation trigger keys. Default `["shift","cmd"]` (Shift+Win). `cmd` = Windows key. |
| `stt.trigger` | `hold` (hold-to-talk, release to send) or `toggle` (press to start/stop). |
| `stt.inject` | `paste` (clipboard paste — reliable for long text) or `type` (char-by-char). |
| `stt.target_window` | `capture` (paste into the window focused when you started talking) or `focused` (whatever's focused at paste time). |
| `stt.max_record_seconds` | Auto-stop + send if a hold runs this long (guards against a missed key-release). |
| `stt.collapse_newlines` | Flatten newlines in dictation so a paste can't submit the prompt early. |
| `stt.drop_no_speech_prob` | Drop filler/hallucinated segments above this no-speech probability. |
| `stt.model` | `base.en` (default); `tiny.en` for weaker machines; `small.en`/`medium.en` for more accuracy. |
| `stt.auto_enter` | `true` to submit automatically after dictation. |
| `summary.mode` | `extractive` (compress long answers) or `verbatim` (read cleaned text). |
| `summary.short_threshold_chars` | Answers shorter than this are read (nearly) whole. |
| `summary.max_sentences` / `max_chars` | Caps for long-answer compression. |
| `tts.engine` | `auto` (Kokoro if model present, else SAPI), `kokoro`, or `sapi`. |
| `tts.kokoro.voice` | Kokoro voice id, e.g. `af_heart`, `af_sarah`, `am_michael`. See [Kokoro VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md). |
| `tts.kokoro.speed` | Speaking rate (1.0 = normal). |
| `tts.ping` | Play a chime before reading. |

### Pluggable input (use Wispr Flow instead)
If you prefer Wispr Flow / Win+H for dictation, just don't rely on the hotkey — the readback half works independently. To disable our STT hotkey entirely, set `hotkey` to `[]`. The daemon still runs the readback server.

## Health check

Verify the whole dictation chain (mic → transcription → TTS) on your machine:
```powershell
.venv\Scripts\python.exe diagnose.py            # records 3s and checks each stage
.venv\Scripts\python.exe diagnose.py --devices  # just list input devices
```
If the wrong mic is picked, note its index from `--devices` and set `stt.device_index` in `config.json`.

## Reliability (Mode 1)

Dictation is hardened against the common failure modes:
- **Window targeting** — the window focused when you *start* talking is refocused before pasting, so text can't land in the Start menu or a window that stole focus.
- **Decoupled transcription** — recording is instant; transcription runs in a worker queue, so fast or back-to-back holds never drop.
- **Sample-rate fallback** — if your mic doesn't do 16 kHz it's captured at its native rate and resampled.
- **Hallucination filter** — Whisper's phantom "thank you"/"you" on silence is dropped.
- **Guards** — max-record auto-stop, clean modifier release before paste, single-instance daemon, and a rotating log at `logs/voiceloop.log`.

## Test without Claude

```powershell
# Readback + ping (uses Kokoro if installed):
"Here is **a summary**. `code` and C:\path\file.py are skipped." | .venv\Scripts\python.exe speak.py
```

## Performance notes
- Kokoro warm synthesis is ~0.5× real-time on a modest CPU (2× faster than the speech is long); the daemon pre-warms the model at startup so the first readback isn't slow.
- Kokoro outputs 24 kHz audio. Model files live in `models/`.

## Troubleshooting
- **Start menu pops up on the hotkey?** Change `hotkey` to `["ctrl","alt","space"]`.
- **Robotic voice / SAPI used?** Check `models/kokoro-v1.0.onnx` and `voices-v1.0.bin` exist; the daemon prints `TTS engine: kokoro` on startup.
- **No audio input?** Set `stt.device_index`. List devices: `.venv\Scripts\python.exe -c "import sounddevice as sd; print(sd.query_devices())"`.
- **Remove the hook:** delete the `stop_hook.py` entry from `~/.claude/settings.json`.
