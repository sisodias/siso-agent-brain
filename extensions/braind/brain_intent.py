#!/usr/bin/env python3
"""Query-intent router for /brain/ask.

Classifies a free-text query to one or more session_extract dims so the
ask pipeline can narrow candidate sets before ranking. Pure regex router
- no LLM, deterministic, sub-millisecond.
"""
import re
import sys
from typing import List, Tuple

Pattern = re.Pattern
Rule = Tuple[Pattern, List[str]]

RULES: List[Rule] = [
    (
        re.compile(
            r"\b(why\s+(?:does|do|did|is)\s+\w+\s+(?:break|fail|broken|failing)"
            r"|keeps?\s+(?:breaking|failing)"
            r"|error|bug|broken|fail(?:ed|ing|s)?)\b",
            re.IGNORECASE,
        ),
        ["ai_failures", "friction_patterns", "framework_gaps"],
    ),
    (
        re.compile(
            r"\b(what\s+(?:did|do|have)\s+we\s+decid"
            r"|decision|should\s+we|agreed|decid(?:ed|e)?)\b",
            re.IGNORECASE,
        ),
        ["decisions"],
    ),
    (
        re.compile(
            r"\b(what\s+(?:was|am)\s+I\s+(?:doing|working|todo)"
            r"|todo|next(?:\s+step)?|forgot|intend(?:ed|ing)?)\b",
            re.IGNORECASE,
        ),
        ["intentions", "tasks"],
    ),
    (
        re.compile(
            r"\b(north\s+star|trying\s+to|want\s+to\s+build|goals?)\b",
            re.IGNORECASE,
        ),
        ["goals"],
    ),
    (
        re.compile(
            r"\b(what\s+worked|win|succeed(?:s|ed|ing)?)\b",
            re.IGNORECASE,
        ),
        ["wins"],
    ),
    (
        re.compile(
            r"\b(how\s+do\s+I\s+prompt|better\s+prompt|prompt\s+improv)\b",
            re.IGNORECASE,
        ),
        ["prompt_improvements"],
    ),
    (
        re.compile(
            r"\b(who|what\s+is\s+\w+|tool|project\s+named)\b",
            re.IGNORECASE,
        ),
        ["entities"],
    ),
]


def classify(query: str) -> List[str]:
    if not query or not query.strip():
        return []
    for pattern, dims in RULES:
        if pattern.search(query):
            return list(dims)
    return []


def main() -> int:
    if len(sys.argv) > 1:
        print(classify(" ".join(sys.argv[1:])))
        return 0

    tests = [
        "why does the deploy keep failing",
        "what did we decide about the API rate limits",
        "what was I doing yesterday with the convex migration",
        "what's my north star for this quarter",
        "what worked last sprint with the new onboarding",
        "how do I prompt Claude better",
        "who built the convex backend",
        "the weather is nice today",
    ]
    for q in tests:
        print(f"{q!r:62s} -> {classify(q)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
