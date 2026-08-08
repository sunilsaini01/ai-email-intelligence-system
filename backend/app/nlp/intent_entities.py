"""
Entity extraction for Intent Detection (Module 7 / FR-35 — "extract key
entities: order IDs, dates, amounts, product names, person names").

Reuses app/nlp/summary_grounding.py's extract_entities() for dates/amounts/
names rather than reimplementing regex/NER logic a second time -- that
function's job (find dates/amounts/names in text) is identical here; only
the CALLER's purpose differs (FR-35 wants entities returned to the caller,
FR-26 wants them compared against a summary for preservation). Reusing the
cached spaCy NER pipeline (`_get_ner_pipeline`) instead of loading a second
one avoids paying spaCy's load cost twice in the same process.

Order IDs and product names are NEW extraction this phase (FR-35 needs
them, FR-26 never did): order IDs via a new regex
(app/feature_engineering/patterns.py's ORDER_ID_PATTERN), product names via
spaCy's PRODUCT NER label -- disclosed as the weakest-recall piece of this
module (en_core_web_sm's PRODUCT category is known to under-perform PERSON/
ORG/DATE for the small model tier; not solved this phase, see the model
card's "Limitations").
"""

from dataclasses import dataclass, field

from app.feature_engineering.patterns import ORDER_ID_PATTERN
from app.nlp.summary_grounding import _get_ner_pipeline, extract_entities


@dataclass
class IntentEntities:
    order_ids: list[str] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    monetary_amounts: list[str] = field(default_factory=list)
    person_names: list[str] = field(default_factory=list)
    product_names: list[str] = field(default_factory=list)


def extract_order_ids(text: str) -> list[str]:
    if not text or not text.strip():
        return []
    return list(dict.fromkeys(m.strip() for m in ORDER_ID_PATTERN.findall(text)))


def extract_product_names(text: str) -> list[str]:
    """
    Best-effort, low-recall by disclosure -- see module docstring. Uses
    spaCy's PRODUCT NER label via the same cached pipeline
    summary_grounding.py already loads for PERSON extraction.
    """
    if not text or not text.strip():
        return []
    doc = _get_ner_pipeline()(text)
    return list(dict.fromkeys(ent.text.strip() for ent in doc.ents if ent.label_ == "PRODUCT"))


def extract_intent_entities(text: str) -> IntentEntities:
    """FR-35's full entity set for one email's text (subject+body combined,
    same convention as every other module's preprocessing input)."""
    dates, amounts, names = extract_entities(text)
    return IntentEntities(
        order_ids=extract_order_ids(text),
        dates=dates,
        monetary_amounts=amounts,
        person_names=names,
        product_names=extract_product_names(text),
    )
