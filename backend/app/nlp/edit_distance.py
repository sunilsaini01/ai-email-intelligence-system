"""
Character-level Levenshtein edit distance (Post-Phase-10 fix #2 -- Human
Acceptance Rate tracking, FR-52).

Pure function, no dependency added -- `difflib` (stdlib) gives a similarity
RATIO, not an edit-operation COUNT, and the PRD's own secondary metric
list (§14.1: "BLEU-4, BERTScore, Edit Distance") names edit distance
specifically, which conventionally means Levenshtein distance. A
textbook O(len(a) * len(b)) DP implementation is small enough (~15 lines)
that a new dependency isn't justified for it -- same "hand-roll a small,
well-understood algorithm rather than add a package" precedent
`app/routing/keyword_matcher.py` already set for this codebase.
"""


def compute_edit_distance(a: str, b: str) -> int:
    a = a or ""
    b = b or ""
    if a == b:
        return 0

    previous_row = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current_row = [i]
        for j, char_b in enumerate(b, start=1):
            insert_cost = current_row[j - 1] + 1
            delete_cost = previous_row[j] + 1
            substitute_cost = previous_row[j - 1] + (0 if char_a == char_b else 1)
            current_row.append(min(insert_cost, delete_cost, substitute_cost))
        previous_row = current_row

    return previous_row[-1]
