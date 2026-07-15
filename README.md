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
3. **Shift + Win** → speak → **Shift + Win** to stop → text appears → **Enter** to send.
4. Claude answers → ping + spoken summary. Start talking (or send a new prompt) to cut a readback short.

## Configuration — `config.json`

| Key | Meaning |
|-----|---------|
| `hotkey` | Dictation toggle. Default `["shift","cmd"]` (Shift+Win). `cmd` = Windows key. |
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
