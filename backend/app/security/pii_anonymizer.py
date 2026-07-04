from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

# Initialize once
analyzer = AnalyzerEngine()
anonymizer = AnonymizerEngine()

def anonymize_email_body(text: str):
    """
    Detect and anonymize PII from email body.
    """

    if not text or not text.strip():
        return text, []

    results = analyzer.analyze(text=text, language="en")

    if not results:
        return text, []

    anonymized = anonymizer.anonymize(
        text=text,
        analyzer_results=results,
        operators={
            "PERSON": OperatorConfig("replace", {"new_value": "<PERSON>"}),
            "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "<EMAIL>"}),
            "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "<PHONE>"}),
            "CREDIT_CARD": OperatorConfig("replace", {"new_value": "<CREDIT_CARD>"}),
            "DEFAULT": OperatorConfig("replace", {"new_value": "<REDACTED>"}),
        }
    )

    entity_types = list({r.entity_type for r in results})

    return anonymized.text, entity_types

