"""
Version metadata for runtime components deliberately NOT registered in
MLflow (Phase 15A / FR-71 audit, "Do not force MLflow on everything").

None of these are trainable artifacts this project produces -- registering
them in a Model Registry would misrepresent what they are (a lexicon
scorer, an algorithmic summarizer, a pretrained third-party model, an
external LLM API). They still need a traceable version identity for the
same reason the registered models do ("which exact thing is this Pod
serving"), so this is a static, code-defined registry instead -- no
database, no MLflow run, just an explicit statement of what's actually
running and what evidence backs it.

Classification (see docs/mlflow_architecture.md "Component Classification"
for the full reasoning behind each):
  zero_shot_algorithm     -- no training data, no model weights of ours
  pretrained_external     -- a third-party model we didn't train, used as-is
  external_llm_provider   -- a hosted API, not a local model at all
"""

from pydantic import BaseModel

from app.mlops.model_metadata import EvidenceStatus


class ComponentVersion(BaseModel):
    component_name: str
    classification: str
    version_identifier: str
    evidence_status: EvidenceStatus
    notes: str


# Kept in sync manually with each module's own MODEL_VERSION/MODEL_NAME
# constant -- see docs/mlflow_architecture.md "Keeping This In Sync" for
# why this isn't derived automatically (the modules live in different
# packages with different import costs; duplicating four short strings
# here is cheaper than adding cross-package imports whose only purpose is
# populating a diagnostics endpoint).
NON_REGISTERED_COMPONENTS: list[ComponentVersion] = [
    ComponentVersion(
        component_name="sentiment",
        classification="zero_shot_algorithm",
        version_identifier="vader-lexicon-3.3.2",
        evidence_status=EvidenceStatus.UNVALIDATED,
        notes="VaderSentimentPredictor (app/inference/sentiment_predictor.py). "
        "sentiment_comparison.joblib exists in artifacts/ but is a comparison-only "
        "artifact, never served -- see scripts/train_sentiment_model.py's own "
        "docstring. No email-domain ground truth exists to validate VADER's "
        "output against.",
    ),
    ComponentVersion(
        component_name="summarization_extractive",
        classification="zero_shot_algorithm",
        version_identifier="textrank-tfidf-v1",
        evidence_status=EvidenceStatus.UNVALIDATED,
        notes="Graph-based extractive summarizer (app/nlp/extractive_summarizer.py), "
        "no training data, no learned weights.",
    ),
    ComponentVersion(
        component_name="summarization_abstractive",
        classification="pretrained_external",
        version_identifier="sshleifer/distilbart-cnn-6-6",
        evidence_status=EvidenceStatus.OFF_DOMAIN,
        notes="Pretrained HuggingFace model, not trained or fine-tuned by this "
        "project. Evaluated on a real but off-domain (news) dataset -- see "
        "docs/model_cards/email_summarization.md.",
    ),
    ComponentVersion(
        component_name="retrieval_embedding",
        classification="pretrained_external",
        version_identifier="all-MiniLM-L6-v2-via-transformers-v1",
        evidence_status=EvidenceStatus.PRETRAINED_EXTERNAL,
        notes="sentence-transformers/all-MiniLM-L6-v2 weights loaded via "
        "transformers directly (app/inference/minilm_embedder.py). "
        "tfidf_embedder.joblib is a real trained artifact but is the "
        "comparison baseline, not what's served.",
    ),
    ComponentVersion(
        component_name="auto_reply_llm",
        classification="external_llm_provider",
        version_identifier="groq/llama-3.3-70b-versatile (primary), ollama/mistral:7b (local fallback)",
        evidence_status=EvidenceStatus.PRETRAINED_EXTERNAL,
        notes="Hosted/local LLM inference, not a model this project trains, "
        "versions, or can register. No Human Acceptance Rate dataset exists "
        "yet -- see README.md Known Limitations.",
    ),
]


def get_component_versions() -> list[ComponentVersion]:
    return NON_REGISTERED_COMPONENTS
