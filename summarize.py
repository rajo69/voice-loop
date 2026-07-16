"""
Turn a Claude markdown response into a short, listenable spoken summary.

Design goals (learned from v1's bug):
  - Never cut off mid-sentence. If we must shorten, we DROP whole sentences.
  - Short answers are read (cleaned) verbatim.
  - Long answers are compressed extractively: headings + lead sentences +
    the concluding sentence, capped by sentence-count and characters.
  - Code blocks are announced ("2 code blocks omitted"), never read.
"""
import re

_CODE_FENCE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

# -- conversational style ("human tone", fully offline) ----------------------
# Written shorthand -> how a person would say it.
_SPOKEN = [
    (re.compile(r"\be\.g\.,?\s*", re.I), "for example, "),
    (re.compile(r"\bi\.e\.,?\s*", re.I), "that is, "),
    (re.compile(r"\bvs\.?\s", re.I), "versus "),
    (re.compile(r"\betc\.(?=[\s,)])"), "et cetera"),
    (re.compile(r"\s*&\s*"), " and "),
    (re.compile(r"(?<=\d)\s*%"), " percent"),
    (re.compile(r"~\s*(?=\d)"), "about "),
    (re.compile(r"(?<=[\w)])\s*(?:->|→)\s*(?=\w)"), " to "),
]
# Stiff written forms -> contractions (case of the first word preserved).
_CONTRACTIONS = [
    ("do not", "don't"), ("does not", "doesn't"), ("did not", "didn't"),
    ("cannot", "can't"), ("can not", "can't"), ("will not", "won't"),
    ("is not", "isn't"), ("are not", "aren't"), ("was not", "wasn't"),
    ("it is", "it's"), ("that is", "that's"), ("there is", "there's"),
    ("you are", "you're"), ("we are", "we're"),
    ("I will", "I'll"), ("we will", "we'll"), ("you will", "you'll"),
    ("I have", "I've"), ("we have", "we've"), ("you have", "you've"),
    ("let us", "let's"), ("I am", "I'm"),
]


def _match_case(repl, original):
    return repl[0].upper() + repl[1:] if original[:1].isupper() else repl


def humanize(text):
    """Make cleaned text sound spoken, not written. Deterministic, offline."""
    for pat, rep in _SPOKEN:
        text = pat.sub(rep, text)
    for written, spoken in _CONTRACTIONS:
        pat = re.compile(r"\b" + written.replace(" ", r"\s+") + r"\b", re.I)
        text = pat.sub(lambda m, s=spoken: _match_case(s, m.group(0)), text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_inline(t):
    t = _INLINE_CODE.sub(r"\1", t)                       # `code` -> code
    t = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", t)      # images
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)       # links -> label
    t = re.sub(r"https?://\S+", "link", t)               # bare url
    # path-like tokens (with an extension or drive) -> "a file"
    t = re.sub(r"(?:[A-Za-z]:\\|~?/)?[\w./\\-]*[/\\][\w.\\-]+\.\w+", "a file", t)
    t = re.sub(r"^[\s>#|]+", "", t)                      # leading markdown marks
    t = re.sub(r"[*_~`]+", "", t)                        # emphasis marks
    t = t.replace("|", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _split_sentences(text):
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]


def _units(md):
    """Ordered list of (kind, text) units: headings, bullets, sentences."""
    out = []
    for block in re.split(r"\n\s*\n", md):
        block = block.strip("\n")
        if not block.strip():
            continue
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if lines and all(_HEADING.match(ln) for ln in lines):
            for ln in lines:
                h = _clean_inline(_HEADING.match(ln).group(1))
                if h:
                    out.append(("heading", h))
            continue
        if lines and all(_LIST_ITEM.match(ln) for ln in lines):
            for ln in lines:
                c = _clean_inline(_LIST_ITEM.sub("", ln))
                if c:
                    out.append(("bullet", c))
            continue
        para = _clean_inline(" ".join(lines))
        for s in _split_sentences(para):
            out.append(("sentence", s))
    return out


def _cap_by_chars(sentences, max_chars):
    out, total = [], 0
    for s in sentences:
        if out and total + len(s) + 1 > max_chars:
            break
        out.append(s)
        total += len(s) + 1
    return out


def summarize_for_speech(md, cfg):
    md = md or ""
    skip_code = cfg.get("skip_code_blocks", True)
    short = int(cfg.get("short_threshold_chars", 350))
    max_sent = int(cfg.get("max_sentences", 6))
    max_chars = int(cfg.get("max_chars", 1000))
    mode = cfg.get("mode", "extractive")
    conversational = cfg.get("style", "conversational") == "conversational"

    n_code = len(_CODE_FENCE.findall(md))
    body = _CODE_FENCE.sub(" ", md)

    code_note = ""
    if skip_code and n_code:
        if conversational:
            code_note = " I've skipped {} code block{}.".format(
                n_code, "s" if n_code > 1 else "")
        else:
            code_note = " {} code block{} omitted.".format(
                n_code, "s" if n_code > 1 else "")

    cleaned_all = _clean_inline(body.replace("\n", " "))

    # Short answers (or explicit verbatim mode): read them (nearly) whole.
    if mode == "verbatim" or len(cleaned_all) <= short:
        sents = _split_sentences(cleaned_all)
        sents = _cap_by_chars(sents, max_chars)
        spoken = (" ".join(sents) + code_note).strip()
        return humanize(spoken) if conversational else spoken

    # Extractive: keep document order, lead + conclusion.
    units = _units(body)
    texts = [t for _, t in units]
    if not texts:
        return code_note.strip()

    if len(texts) <= max_sent:
        picked = texts
    else:
        # lead (max_sent - 1 units) + the final unit (usually a conclusion)
        picked = texts[: max_sent - 1] + [texts[-1]]

    picked = _cap_by_chars(picked, max_chars)

    # A closing question is the most actionable sentence in the answer --
    # never drop it. If the last question isn't already picked, append it.
    questions = [t for t in texts if t.rstrip().endswith("?")]
    if questions and questions[-1] not in picked:
        picked.append(questions[-1])

    # Keep ?/! endings -- flattening a question into a statement changes its
    # meaning when spoken.
    spoken = " ".join(p if p.rstrip()[-1:] in ".!?" else p + "." for p in picked)
    spoken = (spoken + code_note).strip()
    return humanize(spoken) if conversational else spoken
