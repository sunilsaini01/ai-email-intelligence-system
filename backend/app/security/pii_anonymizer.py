"""
PII detection and anonymization (Presidio-backed).

Existed in this codebase since early on (Phase 1/2 scaffolding) but was
never wired into any request path until Phase 9 needed it
(app/retrieval/embedding_input.py, docs/phase9_pii_embedding_strategy.md).

`AnalyzerEngine`/`AnonymizerEngine` are LAZY-loaded (constructed on first
call, cached), not built at module import time. This is both the
established convention every other heavy-dependency component in this
codebase already follows (SpamService/PriorityService/CategoryService/
IntentService/AbstractiveSummarizer/MiniLmEmbedder all defer real
construction past import time) AND fixes a real, reproduced bug: eager
construction here (the original shape of this file, `analyzer =
AnalyzerEngine()` at module level) triggers spaCy's native-extension
loading during `app.api.v1.router`'s import sweep -- and when that
happens BEFORE `torch`/`transformers` finish loading their own native
runtime (import order in `app/api/v1/router.py` is alphabetical, so
`retrieval` imports before `summarization`), a Windows access violation
inside `pyarrow` (imported later, indirectly, by anything reading a
parquet file) reliably follows. Verified directly: `import
app.api.v1.router` then `pandas.read_parquet(...)` segfaults with the
original eager-loading shape of this file, and does not with this lazy
version -- see docs/error_analysis_retrieval.md for the full incident
writeup and the exact reproduction commands.
"""

from functools import lru_cache

from presidio_anonymizer.entities import OperatorConfig

_OPERATORS = {
    "PERSON": OperatorConfig("replace", {"new_value": "<PERSON>"}),
    "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "<EMAIL>"}),
    "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "<PHONE>"}),
    "CREDIT_CARD": OperatorConfig("replace", {"new_value": "<CREDIT_CARD>"}),
    "DEFAULT": OperatorConfig("replace", {"new_value": "<REDACTED>"}),
}


@lru_cache
def _get_analyzer():
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    # Presidio's AnalyzerEngine(), built with no explicit nlp_engine, defaults
    # to looking for en_core_web_lg -- not en_core_web_sm, the model this
    # project actually installs (requirements.txt, see the CI dependency
    # notes there). Since en_core_web_lg was never installed, Presidio's
    # SpacyNlpEngine.load() tried to `spacy.cli.download("en_core_web_lg")`
    # at request time -- a live pip install from inside a running request,
    # which fails in this container (no route to PyPI's model index) and
    # takes the whole request down with a SystemExit. Reproduced directly:
    # any call to /retrieval/index 500'd on this exact stack trace before
    # this fix. Pointing NlpEngineProvider at en_core_web_sm explicitly
    # avoids the mismatch and the network call entirely.
    provider = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }
    )
    return AnalyzerEngine(nlp_engine=provider.create_engine())


@lru_cache
def _get_anonymizer():
    from presidio_anonymizer import AnonymizerEngine

    return AnonymizerEngine()


def anonymize_email_body(text: str) -> tuple[str, list[str]]:
    """Detect and anonymize PII from email body. Returns (anonymized_text,
    entity_types_found) -- entity type NAMES only (e.g. "PERSON"), never
    the raw detected values."""
    if not text or not text.strip():
        return text, []

    results = _get_analyzer().analyze(text=text, language="en")

    if not results:
        return text, []

    anonymized = _get_anonymizer().anonymize(
        text=text,
        analyzer_results=results,
        operators=_OPERATORS,
    )

    entity_types = list({r.entity_type for r in results})

    return anonymized.text, entity_types
