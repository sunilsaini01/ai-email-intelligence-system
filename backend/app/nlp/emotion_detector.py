"""
Primary-emotion detection (Module 6, FR-30): Anger / Frustration /
Confusion / Satisfaction / Urgency.

Lexicon-based, same evidentiary footing as VaderSentimentPredictor
(app/inference/sentiment_predictor.py): no labelled email-emotion dataset
exists in this project, so there is nothing to train or validate a
classifier against. Each emotion is scored from word-boundary cue matches
plus two surface signals the PRD's own examples lean on (shouting in
capitals and repeated '!'/'?'), and VADER's compound score is used only to
break the Satisfaction-vs-negative-emotion ambiguity -- e.g. "thanks for
nothing" must not read as Satisfaction.

Scores are a DISCLOSED HEURISTIC, not calibrated probabilities -- same
caveat docs/model_cards/sentiment.md already carries for the sentiment
distribution.
"""

import re
from dataclasses import dataclass

EMOTIONS = ("Anger", "Frustration", "Confusion", "Satisfaction", "Urgency")

EMOTION_DETECTOR_VERSION = "emotion_lexicon_v1"

_CUES: dict[str, tuple[str, ...]] = {
    "Anger": (
        "furious", "outraged", "angry", "unacceptable", "disgusted", "disgraceful",
        "ridiculous", "appalling", "livid", "infuriating", "pathetic", "worst",
        "scam", "rip off", "ripoff", "how dare", "sick of", "fed up",
    ),
    "Frustration": (
        "still not", "still hasn't", "still haven't", "again", "yet again", "once again",
        "multiple times", "several times", "keeps happening", "no response", "no reply",
        "waiting for", "been waiting", "frustrating", "frustrated", "annoying", "annoyed",
        "disappointed", "disappointing", "doesn't work", "does not work", "not working",
        "third time", "second time",
    ),
    "Confusion": (
        "confused", "confusing", "unclear", "don't understand", "do not understand",
        "not sure", "unsure", "what does", "how do i", "how does", "can you explain",
        "could you explain", "clarify", "clarification", "makes no sense", "lost",
        "which one", "what is the difference",
    ),
    "Satisfaction": (
        "thank you", "thanks", "appreciate", "appreciated", "great job", "excellent",
        "happy with", "pleased", "satisfied", "love it", "wonderful", "fantastic",
        "perfect", "well done", "grateful", "helpful",
    ),
    "Urgency": (
        "urgent", "urgently", "asap", "as soon as possible", "immediately", "right away",
        "emergency", "critical", "deadline", "today", "by eod", "end of day",
        "time sensitive", "time-sensitive", "now", "quickly",
    ),
}

_PATTERNS = {
    emotion: re.compile(r"\b(?:" + "|".join(re.escape(c) for c in cues) + r")\b", re.IGNORECASE)
    for emotion, cues in _CUES.items()
}

_SHOUTED_WORD = re.compile(r"\b[A-Z]{4,}\b")
_REPEATED_BANG = re.compile(r"!{2,}")
_REPEATED_QUESTION = re.compile(r"\?{2,}")

# Below this a detected emotion is too weak to name as "primary".
MIN_PRIMARY_SCORE = 0.2


@dataclass(frozen=True)
class EmotionResult:
    primary_emotion: str | None
    scores: dict[str, float]

    def ranked(self) -> list[dict]:
        return [
            {"emotion": e, "confidence": s}
            for e, s in sorted(self.scores.items(), key=lambda kv: kv[1], reverse=True)
            if s > 0
        ]


def detect_emotions(text: str, compound: float | None = None) -> EmotionResult:
    """`compound` is VADER's compound score for the same text, if the
    caller already has it (SentimentService does) -- used only to suppress
    Satisfaction on clearly negative text and negative emotions on clearly
    positive text."""
    text = text or ""
    raw: dict[str, float] = {e: float(len(_PATTERNS[e].findall(text))) for e in EMOTIONS}

    shouted = len(_SHOUTED_WORD.findall(text))
    if shouted:
        raw["Anger"] += 0.5 * min(shouted, 4)
    if _REPEATED_BANG.search(text):
        raw["Anger"] += 0.5
        raw["Urgency"] += 0.5
    if _REPEATED_QUESTION.search(text):
        raw["Confusion"] += 0.5
        raw["Frustration"] += 0.5

    if compound is not None:
        if compound <= -0.05:
            raw["Satisfaction"] *= 0.25
        elif compound >= 0.5:
            raw["Anger"] *= 0.5
            raw["Frustration"] *= 0.5

    # Saturating squash, not a softmax: two Anger cues should read as
    # strong Anger regardless of how many Urgency cues are also present --
    # these emotions co-occur rather than compete.
    scores = {e: round(v / (v + 1.0), 4) for e, v in raw.items()}

    top_emotion, top_score = max(scores.items(), key=lambda kv: kv[1])
    primary = top_emotion if top_score >= MIN_PRIMARY_SCORE else None
    return EmotionResult(primary_emotion=primary, scores=scores)
