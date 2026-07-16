from commands import parse, DEFAULT_COMMANDS


def test_plain_content_no_command():
    action, rest = parse("fix the login bug in auth.py")
    assert action is None
    assert rest == "fix the login bug in auth.py"


def test_go_with_content():
    action, rest = parse("fix the bug in main.py, claude go")
    assert action == "go"
    assert rest == "fix the bug in main.py"


def test_go_alone():
    action, rest = parse("Claude, go!")
    assert action == "go"
    assert rest == ""


def test_mishears_still_match():
    for heard in ("cloud go", "clod go", "claud go"):
        action, rest = parse(f"run the tests {heard}")
        assert action == "go", heard
        assert rest == "run the tests"


def test_hold_and_stop_and_scratch():
    assert parse("claude hold")[0] == "hold"
    assert parse("claude halt")[0] == "hold"
    assert parse("claude stop")[0] == "stop"
    assert parse("claude scratch")[0] == "scratch"


def test_exit_variants():
    assert parse("exit conversation")[0] == "exit"
    assert parse("end conversation")[0] == "exit"
    assert parse("exit conversation mode")[0] == "exit"


def test_longest_phrase_wins():
    # "exit conversation mode" must not be split as content + shorter phrase
    action, rest = parse("please exit conversation mode")
    assert action == "exit"
    assert rest == "please"


def test_command_only_at_end():
    action, rest = parse("claude go to the settings page and check")
    assert action is None
    assert rest == "claude go to the settings page and check"


def test_punctuation_and_case():
    action, rest = parse("Add a retry loop. Claude, GO.")
    assert action == "go"
    assert rest == "Add a retry loop."


def test_custom_commands():
    cmds = {"go": ["send it"]}
    action, rest = parse("do the thing send it", cmds)
    assert action == "go"
    assert rest == "do the thing"
    # defaults are replaced, not merged
    assert parse("claude go", cmds)[0] is None


def test_empty_input():
    assert parse("") == (None, "")
    assert parse("   ") == (None, "")


def test_defaults_cover_all_actions():
    assert set(DEFAULT_COMMANDS) == {"go", "hold", "scratch", "stop", "exit"}
