import numpy as np
import pytest

pytest.importorskip("numpy")

from stream_stt import EnergyEndpointer, StreamSession

SR = 16000


def _tone(seconds, amp=0.3):
    t = np.arange(int(SR * seconds), dtype=np.float32)
    return (amp * np.sin(2 * np.pi * 440 * t / SR)).astype(np.float32)


def _silence(seconds):
    return np.zeros(int(SR * seconds), dtype=np.float32)


def _feed_chunked(ep_or_session, audio, chunk=1024):
    out = []
    for i in range(0, audio.size, chunk):
        res = ep_or_session.feed(audio[i:i + chunk])
        if res:
            out.extend(res)
    return out


def test_endpointer_splits_at_pauses():
    audio = np.concatenate([
        _silence(0.2), _tone(0.6), _silence(0.9),
        _tone(0.5), _silence(0.9),
    ])
    ep = EnergyEndpointer(sr=SR, min_silence_ms=600, min_speech_ms=200)
    segs = _feed_chunked(ep, audio)
    assert len(segs) == 2
    # each segment actually contains speech energy
    for s in segs:
        assert float(np.max(np.abs(s))) > 0.1
    assert ep.flush() is None


def test_endpointer_flush_returns_unfinished_tail():
    audio = np.concatenate([_silence(0.2), _tone(0.5)])   # no closing pause
    ep = EnergyEndpointer(sr=SR)
    segs = _feed_chunked(ep, audio)
    assert segs == []
    tail = ep.flush()
    assert tail is not None and float(np.max(np.abs(tail))) > 0.1
    assert ep.flush() is None   # flushing again yields nothing


def test_endpointer_pure_silence_yields_nothing():
    ep = EnergyEndpointer(sr=SR)
    assert _feed_chunked(ep, _silence(3.0)) == []
    assert ep.flush() is None


def test_endpointer_leading_silence_bounded():
    ep = EnergyEndpointer(sr=SR, max_leading_s=1.0)
    _feed_chunked(ep, _silence(10.0))
    assert ep._buf.size < SR * 2   # buffer must not grow with silence


def test_session_orders_segments_and_tail():
    calls = []

    def fake_transcribe(seg):
        calls.append(seg.size)
        return f"seg{len(calls)}"

    audio = np.concatenate([
        _tone(0.5), _silence(0.9), _tone(0.5), _silence(0.9), _tone(0.4),
    ])
    sess = StreamSession(fake_transcribe, sr=SR)
    _feed_chunked(sess, audio)
    text = sess.finalize(timeout=5)
    assert text == "seg1 seg2 seg3"   # two closed segments + the tail


def test_session_skips_empty_transcriptions():
    results = iter(["hello", "", "world"])
    sess = StreamSession(lambda seg: next(results), sr=SR)
    audio = np.concatenate([
        _tone(0.5), _silence(0.9), _tone(0.5), _silence(0.9), _tone(0.4),
    ])
    _feed_chunked(sess, audio)
    assert sess.finalize(timeout=5) == "hello world"


def test_session_survives_transcribe_errors():
    def flaky(seg):
        if flaky.n == 0:
            flaky.n += 1
            raise RuntimeError("boom")
        return "ok"
    flaky.n = 0

    sess = StreamSession(flaky, sr=SR)
    audio = np.concatenate([_tone(0.5), _silence(0.9), _tone(0.4)])
    _feed_chunked(sess, audio)
    assert sess.finalize(timeout=5) == "ok"


def test_session_on_segment_callback():
    seen = []
    sess = StreamSession(lambda seg: "chunk", sr=SR,
                         on_segment=lambda t: seen.append(t))
    audio = np.concatenate([_tone(0.5), _silence(0.9)])
    _feed_chunked(sess, audio)
    sess.finalize(timeout=5)
    assert seen == ["chunk"]
