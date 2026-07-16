"""handle_text() decision logic, driven with a fake injector/speaker."""
from conversation import ConversationMode, LISTENING, RUNNING


class FakeInjector:
    def __init__(self):
        self.pastes = []
        self.enters = 0
        self.escapes = 0

    def paste_text(self, text, target_hwnd=None, collapse_newlines=True):
        self.pastes.append(text)
        return True

    def press_enter(self, hwnd=None):
        self.enters += 1

    def press_escape(self, hwnd=None):
        self.escapes += 1


class FakeSpeaker:
    def __init__(self, speaking=False):
        self.speaking = speaking
        self.interrupts = 0

    def interrupt(self):
        self.interrupts += 1


def make_mode(speaking=False, on_exit=None, **conv_overrides):
    cfg = {"conversation": conv_overrides, "stt": {"sample_rate": 16000}}
    inj = FakeInjector()
    sp = FakeSpeaker(speaking=speaking)
    mode = ConversationMode(cfg, lambda seg: "", sp, hwnd=42,
                            on_exit=on_exit, inj=inj)
    return mode, inj, sp


def test_content_drafts_live():
    mode, inj, _ = make_mode()
    mode.handle_text("add a retry loop to the fetcher")
    assert inj.pastes == ["add a retry loop to the fetcher "]
    assert mode.state == LISTENING


def test_go_pastes_tail_and_presses_enter():
    mode, inj, sp = make_mode()
    mode.handle_text("fix the bug in main.py, claude go")
    assert inj.pastes == ["fix the bug in main.py "]
    assert inj.enters == 1
    assert mode.state == RUNNING
    assert sp.interrupts == 1          # readback preempted before sending


def test_go_alone_just_presses_enter():
    mode, inj, _ = make_mode()
    mode.handle_text("some drafted text")
    mode.handle_text("claude go")
    assert inj.enters == 1
    assert inj.pastes == ["some drafted text "]


def test_go_ignored_while_running():
    mode, inj, _ = make_mode()
    mode.state = RUNNING
    mode.handle_text("claude go")
    assert inj.enters == 0


def test_hold_interrupts_running_claude():
    mode, inj, _ = make_mode()
    mode.state = RUNNING
    mode.handle_text("claude hold")
    assert inj.escapes == 1
    assert mode.state == LISTENING


def test_hold_noop_while_listening():
    mode, inj, _ = make_mode()
    mode.handle_text("claude hold")
    assert inj.escapes == 0
    assert mode.state == LISTENING


def test_scratch_clears_draft():
    mode, inj, _ = make_mode()
    mode.handle_text("claude scratch")
    assert inj.escapes == 1


def test_stop_halts_readback():
    mode, _, sp = make_mode(speaking=True)
    mode.handle_text("claude stop")
    assert sp.interrupts == 1


def test_half_duplex_drops_content_while_speaking():
    mode, inj, sp = make_mode(speaking=True)
    mode.handle_text("this is our own tts echoing back")
    assert inj.pastes == []
    # but commands still work mid-readback
    mode.handle_text("claude stop")
    assert sp.interrupts == 1


def test_content_dropped_while_running_by_default():
    mode, inj, _ = make_mode()
    mode.state = RUNNING
    mode.handle_text("random chatter during execution")
    assert inj.pastes == []


def test_paste_while_running_opt_in():
    mode, inj, _ = make_mode(paste_while_running=True)
    mode.state = RUNNING
    mode.handle_text("queue this thought")
    assert inj.pastes == ["queue this thought "]


def test_exit_fires_callback():
    calls = []
    mode, _, _ = make_mode(on_exit=lambda: calls.append(1))
    mode.handle_text("exit conversation")
    assert calls == [1]
    assert not mode.active


def test_on_claude_done_returns_to_listening():
    mode, _, _ = make_mode()
    mode.state = RUNNING
    mode.on_claude_done()
    assert mode.state == LISTENING
