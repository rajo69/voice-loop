# voice-loop

A **two-way voice interface for the Claude Code CLI** — talk instead of type, listen instead of read. Fully local and offline (after a one-time model download).

- **Input:** hold **Shift + Win**, speak, release. Transcribed locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and pasted into your prompt. Press **Enter** to send. *(Already have Wispr Flow? You can use that for input instead — see "Pluggable input".)*
- **Output:** when Claude finishes, you hear a **ping** and a **spoken summary** — read with the natural-sounding [Kokoro-82M](https://github.com/thewh1teagle/kokoro-onnx) voice (falls back to Windows SAPI if the model isn't present). Code blocks and file paths are skipped so it stays listenable.
- **Conversation mode (hands-free):** hold **Shift** and **triple-tap Win** — then just talk. Your speech drafts live into the prompt, and spoken commands are your keyboard: say **"claude go"** to submit, **"claude hold"** to interrupt a running response and steer, **"claude scratch"** to clear the draft, **"claude stop"** to halt a readback, **"exit conversation"** (or triple-tap again) to leave.

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
| `input_engine.py` | Hotkey → record → transcribe → paste (+ triple-tap gesture). |
| `conversation.py` | Mode 2: hands-free listening, live drafting, state machine. |
| `commands.py` | Spoken-command parsing ("claude go/hold/scratch/stop"). |
| `stream_stt.py` | Pause-based segmentation + incremental transcription. |
| `summarize.py` | Markdown → short spoken summary (no mid-sentence cutoff). |
| `tts.py` | Engine abstraction (Kokoro / SAPI). |
| `speaker.py` | Interruptible, single-instance playback. |
| `hooks/stop_hook.py` | Thin Stop-hook client (falls back to `speak.py` if daemon is down). |
| `speak.py` | One-shot readback for testing / fallback. |

## Install

```powershell
./install.ps1        # venv, deps, STT model, Kokoro model (~350MB download, one-time; resumable)
./register_hook.ps1  # adds the readback hook to ~/.claude/settings.json
```
Restart Claude Code so it picks up the hook.

**Or install the hook as a Claude Code plugin** (instead of `register_hook.ps1` — use one or the other, not both, or answers get read twice):
```
/plugin marketplace add rajo69/voice-loop
/plugin install voice-loop@voice-loop-marketplace
```
The plugin registers the Stop hook automatically (`hooks/hooks.json`); you still run the daemon from this folder with `./start.ps1`.

**Start at login (optional):**
```powershell
./autostart.ps1 on    # hidden window at login; ./autostart.ps1 off to remove
```

## Use

1. Start the daemon (leave it running):
   ```powershell
   ./start.ps1
   ```
2. Open Claude Code in another terminal.
3. **Hold Shift + Win**, speak, **release** → your words are pasted into the prompt → press **Enter** to send. *(Set `stt.trigger` to `"toggle"` for press-once-to-start, press-again-to-stop instead.)*
4. Claude answers → ping + spoken summary, **streamed** so it starts within ~1s. Start talking (or send a new prompt) to cut a readback short.

### Conversation mode (hands-free)

1. Focus your Claude Code terminal, then hold **Shift** and **triple-tap Win** (within ~1.2s). An ascending chime confirms the mode is on and the mic stays hot; the focused window is captured as the target.
2. Talk naturally — each phrase (split at your pauses) is transcribed, dev-polished, and pasted into the prompt as a live draft.
3. Say a command at the end of (or as) an utterance:
   | You say | It does |
   |---------|---------|
   | *"… claude go"* | pastes the last phrase, presses **Enter** — Claude runs |
   | *"claude hold"* | presses **Esc** to interrupt Claude mid-run so you can steer |
   | *"claude scratch"* | clears the drafted prompt |
   | *"claude stop"* | stops the current readback |
   | *"exit conversation"* | leaves the mode (descending chime); triple-tap works too |
4. While Claude runs, chatter is ignored (so you can think out loud); when it answers, the summary is spoken and listening resumes. While the readback plays, content is dropped (the mic would hear our own voice) but commands still work — half-duplex by design.

Common Whisper mishears ("cloud go", "claude halt") are accepted. Add your own phrasings under `conversation.commands` in `config.json`.

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
| `conversation.enabled` | Turn the triple-tap gesture / Mode 2 on or off. |
| `conversation.triple_tap_ms` | Window for the three Win taps (default 1200). |
| `conversation.min_silence_ms` | Pause length that ends an utterance in Mode 2. |
| `conversation.commands` | Override the spoken commands, e.g. `{"go": ["send it"]}`. |
| `summary.mode` | `extractive` (compress long answers) or `verbatim` (read cleaned text). |
| `summary.style` | `conversational` (default: contractions, spoken symbols, "I've skipped 2 code blocks") or `neutral`. A closing question is always read in full, with a distinct rising ping. |
| `summary.short_threshold_chars` | Answers shorter than this are read (nearly) whole. |
| `summary.max_sentences` / `max_chars` | Caps for long-answer compression. |
| `tts.engine` | `auto` (Kokoro if model present, else SAPI), `kokoro`, or `sapi`. |
| `tts.kokoro.voice` | Kokoro voice id, e.g. `af_heart`, `af_sarah`, `am_michael`. See [Kokoro VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md). |
| `tts.kokoro.speed` | Speaking rate (1.0 = normal). |
| `tts.ping` | Play a chime before reading. |

### Pluggable input (use Wispr Flow instead)
If you prefer Wispr Flow / Win+H for dictation, just don't rely on the hotkey — the readback half works independently. To disable our STT hotkey entirely, set `hotkey` to `[]`. The daemon still runs the readback server.

## Tray icon

If `pystray`/`Pillow` are installed (they're in `requirements.txt`), the daemon shows a green tray dot: **Stop reading**, **Conversation mode** (toggle), **Dictation hotkey** (pause/resume), **Quit**. The daemon runs fine without them.

## Privacy & security

- **100% local at runtime** — audio, transcription, and speech never leave your machine; the only network use is the one-time model download in `install.ps1`.
- The readback socket (`127.0.0.1:8765`) is protected by a **per-run random token** (`%USERPROFILE%\.voiceloop_token`), so other local processes can't make your machine talk or shut the daemon down.
- The dictation hotkey uses a global keyboard listener (that's how push-to-talk works system-wide). Keystrokes are only *matched* against the hotkey — never stored or transmitted.

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

## Credits & licenses

voice-loop is MIT-licensed (see `LICENSE`). It stands on:
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT) — local speech-to-text
- [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache-2.0) via [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) (MIT) — natural text-to-speech
- pynput, sounddevice, pyperclip, pywin32, pystray — input/audio plumbing

## Troubleshooting
- **Start menu pops up on the hotkey?** Change `hotkey` to `["ctrl","alt","space"]`.
- **Robotic voice / SAPI used?** Check `models/kokoro-v1.0.onnx` and `voices-v1.0.bin` exist; the daemon prints `TTS engine: kokoro` on startup.
- **No audio input?** Set `stt.device_index`. List devices: `.venv\Scripts\python.exe -c "import sounddevice as sd; print(sd.query_devices())"`.
- **Remove the hook:** delete the `stop_hook.py` entry from `~/.claude/settings.json`.
