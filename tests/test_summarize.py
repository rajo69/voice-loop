from summarize import summarize_for_speech

CFG = {
    "mode": "extractive",
    "short_threshold_chars": 350,
    "max_sentences": 6,
    "max_chars": 1000,
    "skip_code_blocks": True,
}


def test_short_answer_read_verbatim():
    text = "Done. The bug in the login flow is fixed."
    out = summarize_for_speech(text, CFG)
    assert "bug in the login flow is fixed" in out


def test_code_blocks_announced_not_read():
    text = "Here is the fix.\n\n```python\nsecret_code = 1\n```\n\nAll tests pass."
    out = summarize_for_speech(text, CFG)
    assert "secret_code" not in out
    assert "1 code block omitted" in out


def test_multiple_code_blocks_pluralized():
    text = "Intro.\n\n```\na\n```\n\nMiddle.\n\n```\nb\n```\n\nEnd."
    out = summarize_for_speech(text, CFG)
    assert "2 code blocks omitted" in out


def test_long_answer_compressed_no_midsentence_cut():
    sentences = [f"This is sentence number {i} of a long explanation." for i in range(40)]
    text = " ".join(sentences)
    out = summarize_for_speech(text, CFG)
    assert len(out) <= CFG["max_chars"] + 50
    assert not out.rstrip().endswith("...")
    # every emitted fragment ends at a sentence boundary
    assert out.rstrip().endswith(".")


def test_long_answer_keeps_lead_and_conclusion():
    body = " ".join(f"Filler sentence number {i} explaining things." for i in range(30))
    text = f"First key point here. {body} Final conclusion sentence."
    out = summarize_for_speech(text, CFG)
    assert "First key point here" in out
    assert "Final conclusion sentence" in out


def test_inline_markdown_cleaned():
    text = "Use `npm install` and see [the docs](https://example.com/x) for **details**."
    out = summarize_for_speech(text, CFG)
    assert "`" not in out and "**" not in out and "https://" not in out
    assert "npm install" in out
    assert "the docs" in out


def test_file_paths_spoken_as_a_file():
    text = "Edited C:\\Users\\Rajo\\project\\main.py to fix the crash."
    out = summarize_for_speech(text, CFG)
    assert "C:\\" not in out
    assert "a file" in out


def test_verbatim_mode_reads_whole_short_text():
    cfg = dict(CFG, mode="verbatim")
    out = summarize_for_speech("One. Two. Three.", cfg)
    assert "One" in out and "Three" in out


def test_empty_input():
    assert summarize_for_speech("", CFG) == ""
    assert summarize_for_speech(None, CFG) == ""
