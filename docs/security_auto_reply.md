# Auto-Reply Generation — Security Review (Phase 10, Step 14)

## Threat Model Summary

Auto-Reply is the first module in this codebase to send user-supplied
content (email text) to a third-party API as part of constructing a
prompt for a generative model. The core, non-negotiable security property
this module is built around: **retrieved historical email content AND
the current email's own content are DATA, never INSTRUCTIONS.**

## PII → External LLM (FR-09, PRD Risk Table: "PII leakage to external LLMs")

**Risk**: Phase 9's `emails.body` is stored raw in Postgres (deliberate,
consistent with every module's storage stance —
`docs/phase9_pii_embedding_strategy.md`). Auto-Reply reads that raw body
for retrieved context, and receives the current email's raw body directly
from the caller. Neither is safe to send to Groq's API as-is.

**Mitigation**: Both the current email and every retrieved historical
email's body are re-anonymized (Presidio, reused from Phase 9's
`app/security/pii_anonymizer.py`) immediately before prompt construction
— a genuinely new obligation this phase introduces, not inherited for
free from Phase 9's own scrubbing (which only ever protected the
embedding path). Verified directly, not just asserted:
`tests/test_auto_reply_service.py::test_pii_in_current_email_never_reaches_the_llm_prompt_raw`,
`::test_pii_in_retrieved_context_never_reaches_the_llm_prompt_raw`, and
confirmed against a REAL Groq response in
`scripts/qualitative_eval_auto_reply.py`'s sensitive-PII case (the
generated draft referenced "the credit card number you provided" without
ever reproducing the actual digits).

**Residual risk, disclosed**: Presidio's PII detection is Groq's own
recognizer set, unmodified, same disclosed limitation Phase 9's model card
already carries — false negatives (missed PII) are possible and not
benchmarked for detection accuracy.

**Third-party data retention**: Groq's own API-tier data-retention policy
applies to any request sent to it. This project has no control over that
policy and does not attempt to represent it here — a disclosed, unresolved
risk, not silently assumed away.

## Prompt Injection (Step 6/Step 14)

**Risk**: an email's body could contain text designed to look like an
instruction ("ignore previous instructions," "you are now a different
assistant," "reveal your system prompt") in an attempt to hijack the
LLM's behavior.

**Mitigations, layered, none presented as a complete guarantee**:

1. **Prompt-level data/instruction separation** — the current email and
   retrieved historical emails are placed inside strictly delimited
   (`=== CURRENT EMAIL ===` / `=== END CURRENT EMAIL ===`, etc.) sections,
   with an explicit system-prompt rule stating that content inside those
   sections is never a command. This is the real, primary defense — but
   it relies on the underlying LLM actually following that instruction,
   which this project does not control and has not formally red-teamed
   beyond the tests below.
2. **A heuristic pre-filter** (`_INJECTION_PHRASES`, a small regex of
   classic injection phrasings) skips generation entirely — the LLM is
   never even called — when the current email matches. Explicitly
   disclosed as a heuristic, not a security guarantee: it catches obvious,
   known phrasings, not novel or obfuscated injection attempts.

**Verified**: `tests/test_reply_prompt.py::test_injection_style_content_stays_inert_as_data_not_instructions`
(the system prompt string itself is byte-for-byte unaffected by email
content), `tests/test_auto_reply_security.py::test_prompt_injection_in_current_email_is_flagged_unsafe_and_not_generated`
(end-to-end, real API path exercised via the real qualitative script too
— the injection case in `scripts/qualitative_eval_auto_reply.py` was
correctly blocked in ~10ms, no LLM call made).

**What this does NOT claim**: immunity to all present or future
prompt-injection techniques. Same honesty standard Phase 9's own
prompt-injection test used ("confirms no instruction-following mechanism
exists today," not "proves immune to all future injection techniques").

## API Key Protection

- **Storage**: `backend/.env` only (gitignored), never in source code,
  documentation, or test fixtures.
- **Logging**: `GroqProvider`'s key-rotation log line records `key_index`
  (an integer position), never the key value. Verified statically:
  `tests/test_auto_reply_security.py::test_groq_provider_never_logs_the_raw_key_on_rotation`
  parses the actual `logger.warning` call site's AST and confirms no
  key-bearing variable is referenced.
- **API responses**: no schema field carries the key; verified directly
  by generating a real draft with a deliberately distinctive fake key
  value set via environment variable and confirming it never appears in
  the response body (`tests/test_auto_reply_security.py::test_response_never_contains_the_configured_api_key`).

## Never Auto-Send (FR-49) — Architectural, Not Just Policy

No code anywhere in the reply pipeline (`AutoReplyService`,
`ReplyDraftRepository`, the `reply.py` endpoints, `GroqProvider`) imports
`smtplib` or any mail-transport library — verified with a static AST
check across all four modules, not just a runtime assertion
(`tests/test_auto_reply_security.py::test_no_email_sending_capability_exists_in_the_reply_pipeline`).
`DRAFT_STATUSES` has no `SENT` state — the only terminal states are
`GENERATED`/`EDITED`/`APPROVED`/`REJECTED`/`FAILED`; `APPROVED` means "a
human said yes to this text," never "this was transmitted anywhere."

## Cross-Tenant / Cross-Organization Leakage

Reuses Phase 9's structural `organization_id` scoping unchanged —
`RetrievalService.search()` and `EmailRepository` both require it, same
mechanism `docs/vector_tenant_isolation.md` already documents and tests.
No new cross-tenant surface introduced by this module.

## Authorization

**No real authentication exists** (same standing gap since Phase 1 —
`docs/architecture.md`). `reviewer_id`/`organization_id` on
approve/edit/reject are caller-supplied strings, not verified against any
identity system — the same disclosed stance Routing and Retrieval already
took for their own review-adjacent fields.

## Input Validation

- `body` is required (Pydantic, 422 on missing); `subject` optional,
  defaults to empty string.
- `draft_id` path parameters are typed `uuid.UUID` — FastAPI/Pydantic
  reject malformed values with 422 automatically (verified:
  `tests/test_reply_endpoint.py::test_get_malformed_draft_id_returns_422`).
- `edited_text` requires `min_length=1` — an empty edit is rejected
  (`tests/test_reply_endpoint.py::test_edit_rejects_empty_text`).
- Huge (50,000-word), empty, Unicode, and HTML-containing bodies all
  tested directly and do not crash the endpoint
  (`tests/test_auto_reply_security.py`).

## Output Validation

`GroqProvider.generate()` raises `LLMProviderError` on an empty
completion rather than silently returning an empty draft (RULE 9 — never
mask a failure as an empty success). No further structural validation of
the LLM's output is performed (e.g. no schema-checking of the reply text)
— a disclosed limitation, not a gap this phase claims to have closed; see
`docs/error_analysis_auto_reply.md`'s fabricated-support-hours finding for
a concrete example of ungrounded-but-plausible output this phase's
generation-policy gates do not catch.

## Logging / Audit Trail

Structured logs (`app.auto_reply` logger) record: `draft_id`,
`generation_policy`, `status`, `retrieved_context_count`,
`total_latency_ms` — never raw email bodies, never the full constructed
prompt, never PII entity values (only type names, e.g. `PERSON`, same
convention Phase 9 already established), never API keys. The `reply_drafts`
table itself IS the durable audit trail (source text, generated text,
retrieved context IDs, policy, reviewer, timestamps) — every attempt is
persisted, success or failure.

## Rate Limiting / Availability

Groq's own rate limits (verified against Groq's documentation, not
assumed) apply per organization. `GroqProvider` rotates through up to 5
configured keys on `RateLimitError`/`AuthenticationError` (plausibly
key-specific failures) but does NOT rotate on timeout or connection
errors (not key-specific — rotating would only waste the latency budget).
All keys exhausted → `LLMProviderError` → a persisted `LLM_FAILURE` draft,
never a hang, never a silent success.
