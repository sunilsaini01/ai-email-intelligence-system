"""
Entity-preservation grounding check (FR-26 — "Summaries shall preserve:
key names, dates, monetary amounts, and action items").

This module does NOT prevent hallucination or guarantee preservation — it
MEASURES it, after the fact, so FR-26 compliance is a reported number, not
an assumed property of whichever summarizer produced the text. This is the
Step 9/10 "hallucination control" and "completeness" work for this phase:
extractive summarization grounds trivially (it can only ever return
substrings of the source, so anything it selects is definitionally
present), but abstractive summarization can paraphrase, drop, or (rarely,
for this model class — see the model card) invent entities, and the only
honest way to know which happened is to check.

Why regex for dates/amounts but spaCy NER for names: dates and monetary
amounts have a small number of common surface forms a regex can cover
adequately (see app/feature_engineering/patterns.py's DATE_PATTERN/
CURRENCY_PATTERN docstrings for the disclosed gap in exotic formats).
Names do not — "John Smith," "J. Smith," "Smith" are all the same entity
in different surface forms, and a regex has no principled way to recognize
a capitalized word as a person's name versus the start of a sentence.
spaCy's NER model (already a dependency via EmailPreprocessor's
lemmatization pipeline, though that usage explicitly disables NER — see
below) is a real, if imperfect, model for this, not a heuristic.
"""

from dataclasses import dataclass, field
from functools import lru_cache

from app.feature_engineering.patterns import CURRENCY_PATTERN, DATE_PATTERN


@dataclass
class EntityPreservationReport:
    source_dates: list[str] = field(default_factory=list)
    source_amounts: list[str] = field(default_factory=list)
    source_names: list[str] = field(default_factory=list)

    preserved_dates: list[str] = field(default_factory=list)
    preserved_amounts: list[str] = field(default_factory=list)
    preserved_names: list[str] = field(default_factory=list)

    @property
    def preservation_rate(self) -> float | None:
        """
        Fraction of ALL source entities (dates + amounts + names combined)
        that appear in the summary. None (not 0.0 or 1.0) when the source
        contained zero entities of any kind — "preserved 0 of 0" is not
        the same claim as "preserved 0 of 5," and collapsing them to the
        same number would misrepresent a source email that simply had no
        names/dates/amounts to preserve in the first place.
        """
        total_source = len(self.source_dates) + len(self.source_amounts) + len(self.source_names)
        if total_source == 0:
            return None
        total_preserved = (
            len(self.preserved_dates) + len(self.preserved_amounts) + len(self.preserved_names)
        )
        return round(total_preserved / total_source, 4)


@lru_cache
def _get_ner_pipeline():
    """
    A SEPARATE spaCy load from EmailPreprocessor's — that one runs with
    `disable=["parser", "ner"]` (it only needs the tagger, for
    lemmatization). NER is exactly the piece this module needs and that
    one deliberately turned off, so it cannot be reused as-is; this loads
    its own pipeline with only `ner` enabled (parser/lemmatizer disabled
    here instead, since grounding doesn't need them) to keep both paths
    each as cheap as their actual job requires.
    """
    import spacy

    return spacy.load("en_core_web_sm", disable=["parser", "lemmatizer", "tagger"])


def extract_entities(text: str) -> tuple[list[str], list[str], list[str]]:
    """Returns (dates, monetary_amounts, person_names) found in `text`."""
    if not text or not text.strip():
        return [], [], []

    dates = list(dict.fromkeys(m.strip() for m in DATE_PATTERN.findall(text)))
    amounts = list(dict.fromkeys(m.strip() for m in CURRENCY_PATTERN.findall(text)))

    doc = _get_ner_pipeline()(text)
    names = list(dict.fromkeys(ent.text.strip() for ent in doc.ents if ent.label_ == "PERSON"))

    return dates, amounts, names


def check_preservation(source_text: str, summary_text: str) -> EntityPreservationReport:
    """
    Case-insensitive substring match — deliberately simple (not fuzzy
    matching or coreference resolution). A summary that writes "J. Smith"
    for a source's "John Smith" will be scored as NOT preserving that name,
    which understates true preservation somewhat — disclosed as a known
    conservative bias in the model card rather than papered over with
    fuzzy matching that could just as easily overstate it.
    """
    source_dates, source_amounts, source_names = extract_entities(source_text)
    summary_lower = (summary_text or "").lower()

    preserved_dates = [d for d in source_dates if d.lower() in summary_lower]
    preserved_amounts = [a for a in source_amounts if a.lower() in summary_lower]
    preserved_names = [n for n in source_names if n.lower() in summary_lower]

    return EntityPreservationReport(
        source_dates=source_dates,
        source_amounts=source_amounts,
        source_names=source_names,
        preserved_dates=preserved_dates,
        preserved_amounts=preserved_amounts,
        preserved_names=preserved_names,
    )
