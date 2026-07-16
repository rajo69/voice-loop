"""Phase 4: socket-auth token helpers and plugin manifest sanity."""
import json
import os

import common

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_token_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "TOKEN_PATH", str(tmp_path / "tok"))
    t = common.write_token()
    assert len(t) == 32 and all(c in "0123456789abcdef" for c in t)
    assert common.read_token() == t
    # a rewrite rotates the secret
    assert common.write_token() != t


def test_read_token_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "TOKEN_PATH", str(tmp_path / "absent"))
    assert common.read_token() == ""


def test_plugin_manifest_valid():
    with open(os.path.join(ROOT, ".claude-plugin", "plugin.json")) as f:
        m = json.load(f)
    assert m["name"] == "voice-loop"
    assert m["version"]


def test_marketplace_lists_plugin():
    with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json")) as f:
        m = json.load(f)
    names = [p["name"] for p in m["plugins"]]
    assert "voice-loop" in names


def test_hooks_json_targets_stop_hook():
    with open(os.path.join(ROOT, "hooks", "hooks.json")) as f:
        h = json.load(f)
    groups = h["hooks"]["Stop"]
    cmds = [hk["command"] for g in groups for hk in g["hooks"]]
    assert any("stop_hook.py" in c and "${CLAUDE_PLUGIN_ROOT}" in c
               for c in cmds)
