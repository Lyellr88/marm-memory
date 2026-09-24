"""Query and anchor vocabulary.

Two problems this solves, both found by running the composer against real repos
rather than fixtures:

1. Seeding with the raw task text lets BM25 match on filler. "the Cpu struct and
   how it steps the bus" ranked `the_bounding_box_spans_and_the_count_does_not_
   fill_it` first -- a test whose snake_case name is mostly English stopwords.
2. Gating memories on any shown symbol name lets a generic identifier through.
   A symbol called `check` matched a memory reading "syntax check confirms ...",
   which is about a different repository entirely.

Both are the same failure: treating a common word as if it identified something.
"""

from __future__ import annotations

import re

STOPWORDS = {
    "a",
    "about",
    "after",
    "all",
    "also",
    "an",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "but",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "doing",
    "done",
    "for",
    "from",
    "get",
    "gets",
    "had",
    "has",
    "have",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "just",
    "like",
    "make",
    "makes",
    "may",
    "me",
    "might",
    "more",
    "most",
    "must",
    "my",
    "no",
    "not",
    "now",
    "of",
    "off",
    "on",
    "once",
    "one",
    "only",
    "or",
    "other",
    "our",
    "out",
    "over",
    "own",
    "same",
    "should",
    "since",
    "so",
    "some",
    "such",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "up",
    "use",
    "used",
    "uses",
    "very",
    "was",
    "way",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "while",
    "who",
    "why",
    "will",
    "with",
    "would",
    "you",
    "your",
}

# Identifiers so common across codebases that their presence in a sentence says
# nothing about which project the sentence is about.
GENERIC_IDENTIFIERS = {
    "add",
    "all",
    "app",
    "args",
    "build",
    "call",
    "check",
    "class",
    "clear",
    "client",
    "close",
    "config",
    "content",
    "context",
    "count",
    "create",
    "data",
    "default",
    "delete",
    "error",
    "event",
    "exec",
    "file",
    "files",
    "find",
    "handle",
    "handler",
    "index",
    "info",
    "init",
    "input",
    "item",
    "items",
    "key",
    "keys",
    "line",
    "lines",
    "list",
    "load",
    "log",
    "main",
    "name",
    "new",
    "next",
    "node",
    "open",
    "options",
    "output",
    "parse",
    "path",
    "process",
    "read",
    "render",
    "reset",
    "result",
    "run",
    "save",
    "send",
    "server",
    "set",
    "setup",
    "size",
    "start",
    "state",
    "status",
    "stop",
    "store",
    "test",
    "text",
    "time",
    "type",
    "update",
    "url",
    "user",
    "util",
    "utils",
    "value",
    "version",
    "write",
}

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def content_terms(text: str) -> list[str]:
    """Words worth searching on: drops filler, keeps identifiers and jargon."""
    out, seen = [], set()
    for w in _WORD.findall(text or ""):
        low = w.lower()
        if low in STOPWORDS or len(low) < 3:
            continue
        if low in seen:
            continue
        seen.add(low)
        out.append(w)
    return out


def seed_query(task: str) -> str:
    """Search text for seeding. Falls back to the task when nothing survives."""
    terms = content_terms(task)
    return " ".join(terms) if terms else (task or "")


# Only a category may stand between the question word and the verb: in
# "which functions call X" the functions are the callers, but in "what target
# calls" the named symbol is the subject and the question asks for callees.
_CALLER_CATEGORY = (
    r"(?:else|other|functions?|methods?|code|symbols?|modules?|classes?|files?|"
    r"handlers?|routes?|tests?|places?|parts?|components?|things?)"
)
_CALLER_QUESTION = re.compile(
    r"\bcallers?\b"
    rf"|\b(?:what|who|which)\s+(?:{_CALLER_CATEGORY}\s+){{0,2}}"
    r"(?:calls?|invokes?|uses?)\b"
    r"|\bwhere\b[^?.]*\b(?:called|used|invoked)\b"
    r"|\bcalled\s+(?:by|from)\b",
    re.I,
)


def asks_for_callers(task: str) -> bool:
    """True when the task asks what calls something rather than what it does."""
    return bool(_CALLER_QUESTION.search(task or ""))


def is_distinctive(word: str) -> bool:
    """True when `word` identifies something, rather than being boilerplate."""
    low = word.lower().strip("_")
    return len(low) > 3 and low not in STOPWORDS and low not in GENERIC_IDENTIFIERS


TEST_PATH = re.compile(
    r"(^|/)(tests?|spec|__tests__)/|(^|/)test_[^/]*$|_test\.[a-z]+$"
    r"|\.test\.[a-z]+$|\.spec\.[a-z]+$"
)


def looks_like_test(file_path: str, symbol_name: str = "") -> bool:
    """Tests are real code, but they are rarely the answer to 'how does X work'."""
    if file_path and TEST_PATH.search(file_path):
        return True
    n = (symbol_name or "").lower()
    return n.startswith("test_") or n.startswith("it_") or n.startswith("should_")
