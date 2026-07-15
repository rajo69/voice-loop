from common import _merge, load_config


def test_merge_deep_override():
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    over = {"a": {"y": 9}, "c": 4}
    out = _merge(base, over)
    assert out == {"a": {"x": 1, "y": 9}, "b": 3, "c": 4}


def test_merge_none_override():
    assert _merge({"a": 1}, None) == {"a": 1}


def test_load_config_has_all_sections():
    cfg = load_config()
    for key in ("hotkey", "stt", "summary", "tts", "daemon"):
        assert key in cfg
