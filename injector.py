"""
Text / keystroke injection into a target window.

Reliability features for rock-solid dictation:
  - clipboard-paste (save -> set -> Ctrl+V -> restore) instead of flaky typing
  - window targeting: refocus the window that was active when you started
    talking, so text can't land in the Start menu or a window that stole focus
  - explicit modifier release before pasting (prevents Ctrl+Win+V leaks)
  - newline collapsing so pasted dictation can't submit the prompt early
"""
import re
import time

from pynput import keyboard

_kbd = keyboard.Controller()

_MOD_KEYS = (
    keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r,
    keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r,
    keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr,
    keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r,
)


# -- clipboard -------------------------------------------------------------
def _get_clipboard():
    try:
        import pyperclip
        return pyperclip.paste()
    except Exception:
        return None


def _set_clipboard(text):
    import pyperclip
    pyperclip.copy(text)


# -- window targeting ------------------------------------------------------
def get_active_window():
    """Handle of the currently focused window (or None)."""
    try:
        import win32gui
        return win32gui.GetForegroundWindow()
    except Exception:
        return None


def focus_window(hwnd):
    """Best-effort: bring `hwnd` to the foreground. Returns True on success."""
    if not hwnd:
        return False
    try:
        import ctypes
        import win32gui
        import win32con
        import win32process
        import win32api
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        cur = win32api.GetCurrentThreadId()
        target = win32process.GetWindowThreadProcessId(hwnd)[0]
        user32 = ctypes.windll.user32
        attached = user32.AttachThreadInput(cur, target, True)
        try:
            win32gui.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(cur, target, False)
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        try:
            import win32gui
            win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception:
            return False


def release_modifiers():
    """Force-release any modifier keys so injected keystrokes are clean."""
    for k in _MOD_KEYS:
        try:
            _kbd.release(k)
        except Exception:
            pass


# -- injection -------------------------------------------------------------
def paste_text(text, target_hwnd=None, restore=True, collapse_newlines=True,
               settle=0.06):
    """Paste `text` into the target (or focused) window via the clipboard."""
    if not text:
        return False
    if collapse_newlines:
        text = re.sub(r"\s*[\r\n]+\s*", " ", text).strip()
    if not text:
        return False

    if target_hwnd:
        focus_window(target_hwnd)
    release_modifiers()

    prev = _get_clipboard() if restore else None
    try:
        _set_clipboard(text)
    except Exception:
        _kbd.type(text)   # clipboard unavailable -> fall back to typing
        return True
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
    return True


def type_text(text, per_char_delay=0.0):
    if not text:
        return
    if per_char_delay > 0:
        for ch in text:
            _kbd.type(ch)
            time.sleep(per_char_delay)
    else:
        _kbd.type(text)


def _tap(key, target_hwnd=None):
    if target_hwnd:
        focus_window(target_hwnd)
    release_modifiers()
    _kbd.press(key)
    _kbd.release(key)


def press_enter(target_hwnd=None):
    _tap(keyboard.Key.enter, target_hwnd)


def press_escape(target_hwnd=None):
    _tap(keyboard.Key.esc, target_hwnd)
