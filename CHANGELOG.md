# Changelog

## 0.9.0 — 2026-07-16

The "conversational product" release.

### Added
- **Conversation mode (Mode 2):** Shift + triple-tap Win for hands-free use —
  always-on listening, live drafting into the prompt, and spoken commands:
  "claude go" (submit), "claude hold" (interrupt & steer), "claude scratch"
  (clear draft), "claude stop" (halt readback), "exit conversation".
- **Human-tone readback:** conversational style (contractions, spoken symbol
  expansion), closing questions always read in full, rising ping when Claude
  ends with a question.
- **Incremental transcription:** audio is segmented at pauses and transcribed
  *while* you're still holding the hotkey, so the paste lands ~1s after
  release; adaptive beam size for short clips.
- **Claude Code plugin packaging:** `.claude-plugin/plugin.json` +
  `hooks/hooks.json` + `marketplace.json` — installable via `/plugin`.
- **Tray icon** (optional): stop reading, mode toggle, dictation pause, quit.
- **Socket auth:** per-run random token protects the readback socket.
- **Autostart:** `./autostart.ps1 on|off` login shortcut.
- Test suite (76 cases) + Windows CI.

### Fixed
- **"Stopping hook…" hang:** the Stop hook's fallback speech process inherited
  the hook's output pipes, blocking Claude Code until speech ended. It now runs
  fully detached with closed handles.
- Resumable, size-checked Kokoro model download in `install.ps1`.
- Questions were flattened into statements by the summarizer.

## 0.8.x — 2026-07-15 (initial development)

- Mode 1 dictation: hold-to-talk, clipboard-paste injection, window targeting,
  dev-term polish ("dot py" → `.py`), Whisper hallucination filter,
  sample-rate fallback, Start-menu suppression.
- Readback: warm daemon + thin non-blocking Stop hook, extractive summarizer
  (never cuts mid-sentence), Kokoro-82M with SAPI fallback, pipelined gapless
  streaming (~1.8s to first audio), barge-in.
- Reliable shutdown (Ctrl+C / `stop.ps1`), rotating logs, `diagnose.py`.
