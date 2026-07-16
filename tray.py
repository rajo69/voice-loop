"""
System tray icon for the voice-loop daemon (optional).

Needs pystray + Pillow; if they're missing (or there's no desktop session)
the daemon simply runs without a tray. The icon is the daemon's "I'm alive"
signal and gives mouse access to the common actions: stop a readback, toggle
conversation mode, pause the dictation hotkey, quit.
"""
import threading

try:                                    # optional; daemon works without it
    import pystray
    from PIL import Image, ImageDraw
except Exception:                       # ImportError, or no display backend
    pystray = None


def _dot(rgba):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((8, 8, 56, 56), fill=rgba)
    return img


class Tray:
    """`ctrl` supplies the daemon's controls:
    interrupt_readback(), toggle_conversation(), conversation_on(),
    dictation_enabled(), set_dictation(bool), quit().
    """

    def __init__(self, ctrl):
        self._ctrl = ctrl
        self._icon = None
        if pystray is None:
            return
        menu = pystray.Menu(
            pystray.MenuItem("Stop reading",
                             lambda: ctrl.interrupt_readback()),
            pystray.MenuItem("Conversation mode",
                             lambda: ctrl.toggle_conversation(),
                             checked=lambda item: ctrl.conversation_on()),
            pystray.MenuItem("Dictation hotkey",
                             lambda: ctrl.set_dictation(
                                 not ctrl.dictation_enabled()),
                             checked=lambda item: ctrl.dictation_enabled()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit voice-loop", lambda: ctrl.quit()),
        )
        self._icon = pystray.Icon("voice-loop", _dot((46, 160, 67, 255)),
                                  "voice-loop", menu)

    @property
    def available(self):
        return self._icon is not None

    def start(self):
        if self._icon is None:
            return False
        threading.Thread(target=self._icon.run, daemon=True).start()
        return True

    def stop(self):
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
