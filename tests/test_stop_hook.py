import json
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks"))

from stop_hook import _extract_text, last_assistant_text  # noqa: E402


def _write_jsonl(tmp_path, entries):
    p = tmp_path / "transcript.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return str(p)


def test_extract_text_string_content():
    assert _extract_text({"content": "hello"}) == "hello"


def test_extract_text_block_list():
    msg = {"content": [
        {"type": "text", "text": "part one"},
        {"type": "tool_use", "name": "Bash"},
        {"type": "text", "text": "part two"},
    ]}
    assert _extract_text(msg) == "part one\npart two"


def test_last_assistant_text_picks_latest(tmp_path):
    path = _write_jsonl(tmp_path, [
        {"type": "assistant", "message": {"content": "first answer"}},
        {"type": "user", "message": {"content": "question"}},
        {"type": "assistant", "message": {"content": "second answer"}},
    ])
    assert last_assistant_text(path) == "second answer"


def test_tool_only_turns_skipped(tmp_path):
    path = _write_jsonl(tmp_path, [
        {"type": "assistant", "message": {"content": "real prose"}},
        {"type": "assistant",
         "message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
    ])
    assert last_assistant_text(path) == "real prose"


def test_bad_json_lines_ignored(tmp_path):
    p = tmp_path / "t.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        f.write("{not json}\n")
        f.write(json.dumps(
            {"type": "assistant", "message": {"content": "ok"}}) + "\n")
        f.write("\n")
    assert last_assistant_text(str(p)) == "ok"


def test_missing_file_returns_empty():
    assert last_assistant_text("/nonexistent/path.jsonl") == ""
    assert last_assistant_text("") == ""
