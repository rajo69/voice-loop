from polish import polish, build_hotwords


def test_dot_py_and_mishears():
    assert polish("open main dot py") == "open main.py"
    assert polish("open main dot pi") == "open main.py"
    assert polish("open main dot pie") == "open main.py"


def test_various_extensions():
    assert polish("edit app dot js and styles dot css") == "edit app.js and styles.css"
    assert polish("check package dot json") == "check package.json"
    assert polish("read readme dot markdown") == "read readme.md"


def test_unknown_extension_untouched():
    assert polish("connect the dot matrix") == "connect the dot matrix"


def test_phrase_fixes():
    assert polish("push it to get hub") == "push it to GitHub"
    assert polish("use type script and java script") == "use TypeScript and JavaScript"
    assert polish("open v s code") == "open VS Code"


def test_custom_vocabulary():
    vocab = [["fast api", "FastAPI"], ["my repo", "voice-loop"]]
    assert polish("use fast api in my repo", vocab) == "use FastAPI in voice-loop"


def test_vocabulary_case_insensitive():
    assert polish("Fast API rocks", [["fast api", "FastAPI"]]) == "FastAPI rocks"


def test_malformed_vocabulary_ignored():
    assert polish("hello world", [["only-one"], None, "bad"]) == "hello world"


def test_empty_text():
    assert polish("") == ""
    assert polish(None) is None


def test_build_hotwords_includes_custom_terms():
    hw = build_hotwords([["k eight s", "k8s"]])
    assert "k8s" in hw and "main.py" in hw
