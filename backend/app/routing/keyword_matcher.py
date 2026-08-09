"""
Word-boundary-safe department keyword matcher (FR-38's "keywords" signal).

The codebase's one existing keyword-matching implementation
(app/feature_engineering/content_features.py) does plain `keyword in
body_lower` substring containment -- not word-boundary-safe (e.g. "cancel"
matches inside "cancellation"). That is a feature of Category's own trained
classifier, already shipped and evaluated; this module does NOT modify it.
Routing needs its own, more precise signal specifically because keyword
evidence here can push a decision toward auto-route or human review, so a
false-positive substring match has more direct consequence than one
contributing feature among thousands in a trained model.

Reuses CATEGORY_KEYWORDS (app/feature_engineering/category_keywords.py) as
the vocabulary -- the same 7 department lexicons (no "General", by design,
see that module) already used to build the synthetic category dataset. No
new lexicon was invented for routing.

Regex-DoS note (Phase 8 brief SS25/SS36): every pattern is a flat alternation
of `re.escape()`-d literal phrases with no nested quantifiers, so there is no
catastrophic-backtracking risk regardless of input -- but input length is
still capped defensively before matching (SS25's "limit input size").
"""

import re

from app.feature_engineering.category_keywords import CATEGORY_KEYWORDS

KEYWORD_MATCHER_VERSION = "routing_keywords_v1"

# Defensive cap, not a precision/recall tuning knob -- an email body far
# beyond this is already pathological input for a routing decision, and
# capping keeps regex evaluation cost bounded regardless of vocabulary size.
MAX_MATCH_INPUT_CHARS = 20_000


def _compile_pattern(phrases: frozenset[str]) -> re.Pattern[str]:
    # Longest-first doesn't change match COUNT here (each phrase is counted
    # independently via finditer per phrase group), but escaping each phrase
    # keeps multi-word phrases ("not working") boundary-safe on both ends.
    escaped = sorted((re.escape(p) for p in phrases), key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(escaped) + r")\b", re.IGNORECASE)


_DEPARTMENT_PATTERNS: dict[str, re.Pattern[str]] = {
    department: _compile_pattern(keywords) for department, keywords in CATEGORY_KEYWORDS.items()
}


def _normalize(text: str) -> str:
    # Collapses irregular whitespace (tabs, newlines, repeated spaces) so a
    # multi-word phrase like "not working" still matches across a
    # line-wrapped email -- \b boundaries alone don't handle that.
    return re.sub(r"\s+", " ", text or "")[:MAX_MATCH_INPUT_CHARS]


def match_department_keywords(text: str) -> dict[str, int]:
    """Per-department match counts (word-boundary-safe). Departments with
    zero matches are omitted, not returned as 0 -- callers should treat
    absence as "no evidence", not "negative evidence"."""
    normalized = _normalize(text)
    counts: dict[str, int] = {}
    for department, pattern in _DEPARTMENT_PATTERNS.items():
        n = len(pattern.findall(normalized))
        if n > 0:
            counts[department] = n
    return counts


def top_department_by_keywords(text: str) -> tuple[str | None, dict[str, int]]:
    """(winning department, full vote counts). Deterministic tie-break by
    department name (RULE 18 / SS29 -- routing must never resolve ties
    randomly) when two or more departments have the same top count."""
    votes = match_department_keywords(text)
    if not votes:
        return None, votes
    max_count = max(votes.values())
    tied = sorted(d for d, c in votes.items() if c == max_count)
    return tied[0], votes
