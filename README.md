# voice-loop

Speak your prompt to the Claude Code CLI and hear the answer read back. voice-loop is a two-way voice interface that runs on your own machine. [faster-whisper](https://github.com/SYSTRAN/faster-whisper) turns your speech into text and pastes it into the prompt; when Claude finishes, the [Kokoro-82M](https://github.com/thewh1teagle/kokoro-onnx) voice reads you a spoken summary of the answer. After the one-time model download it needs no network.

To dictate, hold **Shift + Win**, speak, release. Your words are transcribed locally and pasted into the prompt; press **Enter** to send. If you already dictate with Wispr Flow, keep it and use voice-loop for the readback alone (see [Pluggable input](#pluggable-input-use-wispr-flow-instead)).

When Claude finishes, you hear a ping and then the summary, read with Kokoro (Windows SAPI if the model is not present). Code blocks and file paths are skipped so the readback stays listenable.

For hands-free work, hold **Shift** and **triple-tap Win**, then talk. Your speech drafts live into the prompt and spoken commands take the place of the keyboard: say **"claude go"** to submit, **"claude hold"** to interrupt a running response and steer, **"claude scratch"** to clear the draft, **"claude stop"** to halt a readback, and **"exit conversation"** (or triple-tap again) to leave.

## Architecture

One warm daemon runs both halves; the Claude Code hook is a thin, non-blocking client.

```
[Shift+Win] ─▶ input_engine ─▶ faster-whisper ─▶ types text ─▶ you press Enter
                    │ (barge-in: talking interrupts any readback)
                    ▼
Claude answers ─▶ Stop hook ─(socket, exits)─▶  voiced.py daemon
                                                   │
                                        summarize.py (extractive)
                                                   │
                                        speaker.py ─▶ Kokoro / SAPI
                                        (interruptible; new answer preempts old)
```

Why a daemon: the Stop hook only *sends text over a socket and exits*, so Claude Code is never blocked while a long answer is spoken. Keeping the TTS model warm in one long-lived process means no readback waits for a model load, and playback can be interrupted mid-sentence.

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

**Or install the hook as a Claude Code plugin** (instead of `register_hook.ps1`; use one or the other, not both, or answers get read twice):
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
4. Claude answers → ping + spoken summary, **streamed** so it starts as soon as the first sentence is synthesized. Start talking (or send a new prompt) to cut a readback short.

### Conversation mode (hands-free)

1. Focus your Claude Code terminal, then hold **Shift** and **triple-tap Win** (within 1.2 seconds; configurable). An ascending chime confirms the mode is on and the mic stays hot; the focused window is captured as the target.
2. Talk normally: each phrase (split at your pauses) is transcribed, cleaned up and pasted into the prompt as a live draft.
3. Say a command at the end of (or as) an utterance:
   | You say | It does |
   |---------|---------|
   | *"… claude go"* | pastes the last phrase, presses **Enter**, and Claude runs |
   | *"claude hold"* | presses **Esc** to interrupt Claude mid-run so you can steer |
   | *"claude scratch"* | clears the drafted prompt |
   | *"claude stop"* | stops the current readback |
   | *"exit conversation"* | leaves the mode (descending chime); triple-tap works too |
4. While Claude runs, chatter is ignored (so you can think out loud); when it answers, the summary is spoken and listening resumes. While the readback plays, content is dropped (the mic would hear our own voice) but commands still work: half-duplex by design.

Common Whisper mishears ("cloud go", "claude halt") are accepted. Add your own phrasings under `conversation.commands` in `config.json`.

## Configuration: `config.json`

| Key | Meaning |
|-----|---------|
| `hotkey` | Dictation trigger keys. Default `["shift","cmd"]` (Shift+Win). `cmd` = Windows key. |
| `stt.trigger` | `hold` (hold-to-talk, release to send) or `toggle` (press to start/stop). |
| `stt.inject` | `paste` (clipboard paste, reliable for long text) or `type` (char-by-char). |
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
If you prefer Wispr Flow or Win+H for dictation, ignore the hotkey; the readback half works on its own. To switch our STT hotkey off entirely, set `hotkey` to `[]`. The readback server keeps running in the daemon either way.

## Tray icon

If `pystray`/`Pillow` are installed (they're in `requirements.txt`), the daemon shows a green tray dot with four entries: **Stop reading**, **Conversation mode** (toggle), **Dictation hotkey** (pause/resume) and **Quit**. Without them the daemon runs the same, minus the icon.

## Privacy & security

Audio, transcription and speech never leave your machine; the only network use is the one-time model download in `install.ps1`.

The readback socket (`127.0.0.1:8765`) is protected by a per-run random token (`%USERPROFILE%\.voiceloop_token`), so other local processes can't make your machine talk or shut the daemon down.

Push-to-talk works system-wide because the dictation hotkey uses a global keyboard listener. Keystrokes are only *matched* against the hotkey, never stored or transmitted.

## Health check

Verify the whole dictation chain (mic → transcription → TTS) on your machine:
```powershell
.venv\Scripts\python.exe diagnose.py            # records 3s and checks each stage
.venv\Scripts\python.exe diagnose.py --devices  # just list input devices
```
If the wrong mic is picked, note its index from `--devices` and set `stt.device_index` in `config.json`.

## Reliability (Mode 1)

Dictation is built to survive the ways push-to-talk usually goes wrong on a desktop.

The window that was focused when you *started* talking is refocused before pasting, so text can't land in the Start menu or in a window that stole focus. Recording is instant and transcription runs in a worker queue, so fast or back-to-back holds never drop. If your mic doesn't do 16 kHz it's captured at its native rate and resampled. Whisper's phantom "thank you" and "you" on silence are filtered out. Round that sit a max-record auto-stop, a clean modifier release before paste, a single-instance daemon, and a rotating log at `logs/voiceloop.log`.

## Test without Claude

```powershell
# Readback + ping (uses Kokoro if installed):
"Here is **a summary**. `code` and C:\path\file.py are skipped." | .venv\Scripts\python.exe speak.py
```

## Performance notes
- Kokoro is loaded at daemon startup and stays loaded. It outputs 24 kHz audio; model files live in `models/`.

## Credits & licenses

voice-loop is MIT-licensed (see `LICENSE`). It stands on:
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT): local speech-to-text
- [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache-2.0) via [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) (MIT): text-to-speech
- pynput, sounddevice, pyperclip, pywin32, pystray: input/audio plumbing

## Troubleshooting
- A Start menu that pops up on the hotkey means Windows took the Win key: change `hotkey` to `["ctrl","alt","space"]`.
- A robotic voice means SAPI is in use: check that `models/kokoro-v1.0.onnx` and `voices-v1.0.bin` exist; the daemon prints `TTS engine: kokoro` on startup when they do.
- With no audio input, set `stt.device_index`. List devices: `.venv\Scripts\python.exe -c "import sounddevice as sd; print(sd.query_devices())"`.
- To remove the hook, delete the `stop_hook.py` entry from `~/.claude/settings.json`.
