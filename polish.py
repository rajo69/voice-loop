"""
Dev-aware post-correction for dictated text.

Whisper hears "open main dot pi" -- a developer means "open main.py". This maps
spoken forms to written code conventions: file extensions ("dot py" -> ".py"),
and common tool/term spellings ("get hub" -> "GitHub"). Extend via
config: stt.vocabulary = [["spoken form", "Written Form"], ...].
"""
import re

# spoken extension word -> canonical extension (handles Whisper mishears)
_EXT = {
    "py": "py", "pi": "py", "pie": "py",
    "js": "js", "mjs": "mjs", "jsx": "jsx",
    "ts": "ts", "tsx": "tsx",
    "json": "json", "md": "md", "markdown": "md",
    "txt": "txt", "text": "txt", "log": "log",
    "html": "html", "css": "css", "scss": "scss",
    "cpp": "cpp", "hpp": "hpp", "java": "java",
    "rb": "rb", "go": "go", "rs": "rs",
    "sh": "sh", "bash": "sh", "ps1": "ps1",
    "yml": "yml", "yaml": "yaml", "toml": "toml", "ini": "ini",
    "cfg": "cfg", "conf": "conf", "env": "env", "lock": "lock",
    "sql": "sql", "xml": "xml", "csv": "csv",
    "png": "png", "jpg": "jpg", "jpeg": "jpeg", "svg": "svg",
    "gif": "gif", "pdf": "pdf", "zip": "zip",
}

# "<name> dot <ext>" -> "<name>.<ext>" (only when ext is a known extension)
_DOT = re.compile(r"\b([A-Za-z0-9_-]+)\s+dot\s+([A-Za-z0-9]+)\b", re.IGNORECASE)

# high-confidence multi-word term fixes
_PHRASES = [
    (re.compile(r"\b(?:get|git)\s*hub\b", re.I), "GitHub"),
    (re.compile(r"\bnode\s*(?:js|js\.?)\b", re.I), "Node.js"),
    (re.compile(r"\btype\s*script\b", re.I), "TypeScript"),
    (re.compile(r"\bjava\s*script\b", re.I), "JavaScript"),
    (re.compile(r"\bv\.?\s*s\.?\s*code\b", re.I), "VS Code"),
    (re.compile(r"\bnum\s*py\b", re.I), "NumPy"),
    (re.compile(r"\bpip\s*install\b", re.I), "pip install"),
    (re.compile(r"\bnpm\s*install\b", re.I), "npm install"),
]


def _fix_ext(m):
    name, extword = m.group(1), m.group(2).lower()
    ext = _EXT.get(extword)
    if not ext:
        return m.group(0)
    return f"{name}.{ext}"


def polish(text, vocabulary=None):
    if not text:
        return text
    t = _DOT.sub(_fix_ext, text)
    for pat, rep in _PHRASES:
        t = pat.sub(rep, t)
    for pair in (vocabulary or []):
        try:
            spoken, written = pair[0], pair[1]
        except (TypeError, IndexError):
            continue
        t = re.sub(r"\b" + re.escape(spoken) + r"\b", written, t, flags=re.IGNORECASE)
    return t


def build_hotwords(vocabulary=None):
    """A hint string to bias Whisper toward dev vocabulary."""
    base = ["main.py", "app.js", "package.json", "README.md", "git", "npm",
            "Docker", "Kubernetes", "async", "API", "JSON", "config"]
    extra = [p[1] for p in (vocabulary or []) if isinstance(p, (list, tuple)) and p]
    return ", ".join(base + extra)
