"""
Text / keystroke injection into the focused window.

Uses clipboard-paste (save clipboard -> set text -> Ctrl+V -> restore) which is
far more reliable than character-by-character typing for long dictation, and
sends control keys (Enter / Esc) for hands-free submit / interrupt.
"""
import time

from pynput import keyboard

_kbd = keyboard.Controller()


def _get_clipboard():
    try:
        import pyperclip
        return pyperclip.paste()
    except Exception:
        return None


def _set_clipboard(text):
    import pyperclip
    pyperclip.copy(text)


def paste_text(text, restore=True, settle=0.06):
    """Paste `text` into the focused window via the clipboard."""
    if not text:
        return
    prev = _get_clipboard() if restore else None
    try:
        _set_clipboard(text)
    except Exception:
        # Clipboard unavailable -> fall back to typing.
        _kbd.type(text)
        return
    time.sleep(settle)
    _kbd.press(keyboard.Key.ctrl)
    _kbd.press("v")
    _kbd.release("v")
    _kbd.release(keyboard.Key.ctrl)
    time.sleep(settle)
    if restore and prev is not None:
        try:
            _set_clipboard(prev)
        except Exception:
            pass


def type_text(text, per_char_delay=0.0):
    """Character-by-character typing (fallback / small snippets)."""
    if not text:
        return
    if per_char_delay > 0:
        for ch in text:
            _kbd.type(ch)
            time.sleep(per_char_delay)
    else:
        _kbd.type(text)


def press_enter():
    _kbd.press(keyboard.Key.enter)
    _kbd.release(keyboard.Key.enter)


def press_escape():
    _kbd.press(keyboard.Key.esc)
    _kbd.release(keyboard.Key.esc)
