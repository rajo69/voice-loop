"""
Spoken-command parsing for conversation mode.

The command word is a spoken button: "fix the bug in main.py, claude go"
-> content "fix the bug in main.py" + action "go". Commands are matched at
the END of an utterance (or as the whole utterance) after normalization, so
"Claude, go!" and Whisper mishears like "cloud go" still land.

Pure text logic -- no audio, no Windows APIs -- so it is fully unit-testable.
"""
import re

# action -> spoken variants (Whisper mishears included). Extendable via
# config: conversation.commands = {"go": ["claude go", ...], ...}
DEFAULT_COMMANDS = {
    "go": ["claude go", "cloud go", "clod go", "claud go", "quad go"],
    "hold": ["claude hold", "cloud hold", "claude hole", "claude old",
             "claude halt", "cloud halt"],
    "scratch": ["claude scratch", "cloud scratch", "claude scrap"],
    "stop": ["claude stop", "cloud stop", "claude shut up"],
    "exit": ["exit conversation", "exit conversation mode",
             "leave conversation", "and conversation", "end conversation"],
}

_PUNCT = re.compile(r"[^\w\s]")


def _norm_words(text):
    return _PUNCT.sub(" ", (text or "").lower()).split()


def parse(text, commands=None):
    """Return (action | None, remaining_text).

    `remaining_text` is the original text with the trailing command phrase
    removed (word-for-word) and trailing punctuation cleaned. When no command
    matches, returns (None, text unchanged).
    """
    words = _norm_words(text)
    if not words:
        return None, (text or "").strip()

    best = None   # (phrase_word_count, action)
    for action, phrases in (commands or DEFAULT_COMMANDS).items():
        for phrase in phrases:
            pw = _norm_words(phrase)
            if pw and len(pw) <= len(words) and words[-len(pw):] == pw:
                if best is None or len(pw) > best[0]:
                    best = (len(pw), action)

    if best is None:
        return None, text.strip()

    n, action = best
    # Remove the trailing command from the ORIGINAL text (keeps the content's
    # punctuation/casing). Tokens can normalize to multiple words ("claude-go"),
    # so walk from the end by normalized-word count, not token count.
    original_tokens = text.strip().split()
    covered, i = 0, len(original_tokens)
    while i > 0 and covered < n:
        i -= 1
        covered += len(_norm_words(original_tokens[i]))
    # Drop separator punctuation before the command ("..., claude go") but
    # keep sentence-ending marks -- they belong to the drafted content.
    remaining = " ".join(original_tokens[:i]).rstrip(" ,;:-").strip()
    return action, remaining
