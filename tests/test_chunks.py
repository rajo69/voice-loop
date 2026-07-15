from speaker import _chunks


def test_first_chunk_is_single_sentence():
    text = "Short opener. " + "This is a following sentence that adds detail. " * 6
    chunks = _chunks(text)
    assert chunks[0] == "Short opener."


def test_chunks_respect_max_len():
    text = "One sentence here. " * 30
    for ch in _chunks(text, min_len=90, max_len=200):
        assert len(ch) <= 200


def test_long_sentence_word_wrapped():
    text = "word " * 100  # a single 500-char "sentence", no punctuation
    chunks = _chunks(text, min_len=90, max_len=200)
    assert len(chunks) > 1
    for ch in chunks:
        assert len(ch) <= 200
        assert not ch.startswith(" ") and not ch.endswith(" ")


def test_all_words_preserved():
    text = "Alpha bravo. Charlie delta echo. Foxtrot golf hotel india juliet."
    joined = " ".join(_chunks(text))
    for word in ["Alpha", "bravo.", "Charlie", "juliet."]:
        assert word in joined


def test_later_sentences_merged():
    # Many tiny sentences after the first should merge toward min_len.
    text = "Go. " + "Hi. " * 40
    chunks = _chunks(text, min_len=90, max_len=200)
    assert chunks[0] == "Go."
    assert any(len(c) >= 60 for c in chunks[1:])


def test_empty_text():
    assert _chunks("") == []
