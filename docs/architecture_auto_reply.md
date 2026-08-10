# Auto-Reply Generation — Architecture (Phase 10)

> **Data status**: Draft quality is unvalidated against real human judgment
> (no Human Acceptance Rate data exists yet — see
> `docs/rag_evaluation_auto_reply.md`). Retrieval context quality inherits
> Phase 9's own caveats, now sharpened: see "Embedder Decision" below and
> "Resolved-Email Data Reality." The LLM itself (Groq/`llama-3.3-70b-versatile`)
> is a third-party model this project does not train, fine-tune, or validate.

## What This Module Establishes

The tenth production module, and the first to call a paid external LLM
API. Composes Phase 9's retrieval infrastructure (reused, not duplicated)
with a new, provider-agnostic LLM abstraction to produce a **draft-only**
reply — never sent, always requiring human review (FR-49/FR-51).

## LLM Provider Decision

The PRD's own ADR-002 named OpenAI GPT-4o primary / Ollama-Mistral-7B
fallback. This project used **Groq** (`llama-3.3-70b-versatile`) instead —
an explicit project-owner decision, confirmed before implementation began
(the same "surface a PRD suggestion's real-world fit before following it"
discipline Phase 9 used when it overrode the PRD's `sentence-transformers`
suggestion after finding it broken in this environment). Groq's rate
limits were independently verified (not assumed) against Groq's own
documentation before any key was configured: limits apply per
**organization**, not per key — multiple keys from the same account do
not multiply throughput, they are only useful as genuine resilience
(rotate past a revoked/rate-limited key) or as credentials from genuinely
separate accounts. `backend/.env` supports `GROQ_API_KEY` through
`GROQ_API_KEY_5`; only one is required.

### Why Groq/Llama Over the PRD's Named GPT-4o/Claude (Post-Phase-10 fix #4)

Documented explicitly, not left implicit in the choice itself:

1. **Cost** — Groq's free tier requires no billing setup at all; GPT-4o/
   Claude require a funded account before a single request succeeds. For
   a project with no real users or revenue yet, that's a real barrier to
   even exercising the code path, not a minor convenience.
2. **Speed** — Groq's entire value proposition is inference latency; the
   real, measured numbers in `docs/phase10_requirements_traceability.md`
   ("Measured Latency," 422-666ms LLM latency, warm) reflect this
   directly. GPT-4o/Claude are not slow in absolute terms, but Groq's
   LPU-based serving is specifically optimized for exactly this profile.
3. **Rate limits sufficient for this project's actual traffic** —
   verified against Groq's own documentation (not assumed) before this
   was built: 12K TPM / 1K RPD on `llama-3.3-70b-versatile` comfortably
   covers development, the qualitative eval script, and even light real
   usage, given this project has no live production traffic (no auth, no
   deployed users) — see the earlier session's rate-limit research.
4. **Project-owner's explicit choice** — offered as a live decision
   (OpenAI vs. Anthropic vs. Groq were all discussed), not defaulted to
   silently.

### The Quality Tradeoff (Disclosed, Not Measured Head-to-Head)

**No direct GPT-4o/Claude comparison has been run in this project** — RULE
2 (never fabricate an evaluation this project didn't actually do) applies
here as much as anywhere else. What can be honestly said:

- `llama-3.3-70b-versatile` is a strong, capable open-weight model (70B
  parameters, instruction-tuned), and this project's own qualitative
  testing (`scripts/qualitative_eval_auto_reply.py`,
  `docs/error_analysis_auto_reply.md`) found it produced coherent,
  appropriately-toned, context-aware drafts in every case tried.
- Independent of this project, GPT-4o and Claude are generally positioned
  (by their own vendors and widely, though not measured here) as stronger
  on complex multi-step reasoning, nuanced tone control, and
  instruction-following consistency under adversarial or ambiguous input
  than most openly-available 70B-class models. This is a **general,
  known positioning**, disclosed as such — not a benchmark number this
  project measured or verified independently.
- The one concrete, project-specific data point that exists is the
  fabricated-support-hours hallucination in
  `docs/error_analysis_auto_reply.md` — observed on `llama-3.3-70b-versatile`
  specifically. Whether GPT-4o/Claude would have hallucinated less on the
  same ungrounded query is unknown; this project has not run that
  comparison and will not claim an answer it doesn't have evidence for.

### What Would Trigger Switching

Not a hypothetical list — concrete, checkable conditions:

1. **Human Acceptance Rate data** (once real agents generate it — see
   `docs/model_cards/auto_reply.md`) showing an edit/rejection rate that,
   on inspection, traces to model quality (tone, reasoning, factual
   errors) rather than context availability (Phase 9's own resolved-email
   gap) — the two are currently indistinguishable without real usage data.
2. **Groq rate limits becoming an actual constraint** at real traffic
   levels — not a concern today (see "Cost" above), but the first thing
   to check if `LLM_FAILURE`/`LLMRateLimitedError` rates rise in production
   logs.
3. **A category of reply that specifically needs stronger reasoning** —
   e.g. nuanced legal/compliance language, complex multi-turn escalations
   — where a stronger model's cost might be justified for a subset of
   traffic even if Groq remains the default for routine replies.
4. **Groq service reliability issues** at a rate the Ollama fallback
   (below) can't reasonably absorb.

Because `LLMProvider` is a Protocol (not a hard-coded dependency),
switching or adding a second provider for a subset of traffic is a
constructor-argument change to `AutoReplyService`, not a redesign —
already proven true once, when `OllamaProvider` slotted in as a fallback
with zero changes to `AutoReplyService` itself (see "Ollama Fallback"
below).

## Request Flow — Generation

```
POST /api/v1/reply/generate {subject?, body, category?, department?, source_email_id?}
        │
        ▼
RetrievalService.search()  -- reused from Phase 9, now MiniLM-backed (see below)
        │
        ▼
For each candidate (over-fetched, same pattern as Phase 9's own search endpoint):
        EmailRepository.get_by_content_hash() -- fresh Postgres lookup
        keep only: not deleted, resolution_status == RESOLVED
        ▼
select_context() -- similarity-score floor (MIN_CONTEXT_SCORE), truncate to top 3 (FR-48)
        ▼
AutoReplyService.generate()
        │  re-anonymize current email (Presidio, reused) -- NEW obligation, see "PII" below
        │  re-anonymize each retrieved email's raw body
        │  injection-heuristic pre-filter -> UNSAFE_CONTENT (skip LLM entirely) if matched
        │  sensitive-entity check -> NEEDS_HUMAN_REVIEW flag (generation still proceeds safely)
        │  build_reply_prompt() -- strictly delimited DATA sections
        │  LLMProvider.generate(system_prompt, user_prompt, timeout=8s)
        ▼
ReplyDraft persisted (Postgres) -- ALWAYS, even on failure (Step 8 audit trail)
        ▼
ReplyDraftResponse {draft_id, status, generation_policy, generated_text, ...}
```

## Human-in-the-Loop Lifecycle (FR-49/FR-51)

```
GENERATED (or FAILED, if generation itself did not produce text)
   │
   ├── POST /reply/{id}/approve  -> APPROVED
   ├── POST /reply/{id}/edit     -> EDITED (edited_text set, generated_text preserved for audit)
   └── POST /reply/{id}/reject   -> REJECTED
```

There is no `SENT` state and no code path capable of transmitting an
email anywhere in this pipeline — verified architecturally, not just
asserted (`tests/test_auto_reply_security.py::test_no_email_sending_capability_exists_in_the_reply_pipeline`,
a static AST check that none of Auto-Reply's own modules import
`smtplib` or any mail-transport library).

## Generation Policy (Step 7)

| Policy | Meaning | LLM called? |
|---|---|---|
| `NORMAL_REPLY` | At least one usable RESOLVED context item found | Yes |
| `NO_SIMILAR_EMAILS` | Retrieval succeeded, nothing qualifying found (RESOLVED + above score floor) — **the currently-common case**, see below | Yes, drafted without historical grounding |
| `INSUFFICIENT_CONTEXT` | Retrieval itself failed/errored | Yes, drafted without historical grounding, flagged differently from the above so the two causes aren't conflated |
| `NEEDS_HUMAN_REVIEW` | Current email contains a high-sensitivity PII type (credit card, SSN, bank number) | Yes — the LLM never sees the raw value, only an anonymized placeholder; this flag exists because the underlying situation (a payment dispute, etc.) deserves human eyes regardless of how safely the anonymized text was handled |
| `UNSAFE_CONTENT` | Current email matches a classic prompt-injection phrasing heuristic | **No** — generation is skipped entirely |
| `TIMEOUT` | The 8s LLM budget (or the outer 10s total budget) was exceeded | Attempted, no text produced |
| `LLM_FAILURE` | Provider error (all configured keys exhausted, connection failure, malformed response) | Attempted, no text produced |

A draft is **always** persisted, whatever the policy — the row IS the
audit trail of what was attempted, same "not best-effort" stance Phase
9's `emails` table already established for its own canonical record.

### Confidence Gate — Low-Context Warning (Post-Phase-10 fix #1)

A generation policy alone (e.g. `NO_SIMILAR_EMAILS`) is visible in the
API response and the DB row, but not necessarily to an agent glancing at
the drafted TEXT itself. `AutoReplyService.generate()` appends a visible
line — `"Note: limited historical context — verify before sending."` —
directly to `generated_text` whenever fewer than `MIN_CONFIDENT_CONTEXT_COUNT`
(2) usable RESOLVED context items were used, regardless of which
generation policy applies (covers `NO_SIMILAR_EMAILS`,
`INSUFFICIENT_CONTEXT`, and a `NORMAL_REPLY` grounded in only 1 item
alike). This does not refuse to draft — refusing was rejected as a
design choice for the same reason given in "Resolved-Email Data Reality"
below: this is the common case, not the exception, and a warning an agent
actually sees when reading the draft is more useful than a policy field
they might not check. The `2`-item threshold is a disclosed heuristic,
not derived from a measured hallucination-rate curve — no such curve
exists (the one real data point, `docs/error_analysis_auto_reply.md`'s
fabricated-support-hours finding, was itself a 0-context case).

## Resolved-Email Data Reality (Step 3 Finding)

Phase 9's `resolution_status` (`docs/resolution_status_design.md`) never
auto-transitions — the only way an email becomes `RESOLVED` is an
explicit `PATCH /retrieval/emails/{id}/resolution` call, and Phase 9's
indexing itself is not auto-wired into the existing pipeline
(`docs/architecture_rag.md` "Not Auto-Wired"). Combined, this means: **in
this system's actual current state, `NO_SIMILAR_EMAILS` is very likely
the common generation policy, not the rare one.** This was not smoothed
over or hidden — `AutoReplyService` is deliberately designed to still
produce a usable draft in this case (a reply grounded only in the current
email, still requiring human review regardless per FR-49), rather than
refusing to draft anything until Phase 9's data gap closes.

**This gap now has a real, if partial, closing mechanism (Post-Phase-10
fix #3)**: see "Auto-Mark-Resolved on Approve" below.

## Auto-Mark-Resolved on Approve (Post-Phase-10 fix #3)

`POST /reply/{id}/approve` now does one thing beyond setting
`status=APPROVED`: if the draft carries a `source_email_id` (the caller
supplied one at generation time — still optional, per "Not Auto-Wired,"
below), the referenced `emails` row's `resolution_status` is set to
`RESOLVED` via `EmailRepository.update_resolution_status()`. The
reasoning: an agent approving a drafted reply is the closest signal this
codebase has to "this situation was actually handled" — there is no send
step to hook (FR-49 means one never exists), so approval is the natural
point.

**Best-effort, explicitly**: this side effect is wrapped in its own
try/except and logged on failure, but never blocks the approve action
itself — a missing `source_email_id` (the common case today, since
indexing isn't required to call `/reply/generate`) or a stale/deleted
`EmailRecord` both degrade gracefully rather than turning a successful
review action into an error. Verified directly:
`tests/test_reply_endpoint.py::test_approve_auto_marks_source_email_resolved`,
`::test_approve_without_source_email_id_does_not_crash`,
`::test_approve_with_nonexistent_source_email_id_does_not_crash`,
`::test_reject_does_not_auto_resolve` (only APPROVE triggers this, not
EDIT-then-approve's own approve call is covered by the same code path,
and REJECT never does).

**What this does NOT solve**: it only marks the CURRENT email resolved,
not the retrieved historical context items, and only fires when a caller
bothers to supply `source_email_id` in the first place — genuinely
closing the gap at scale still needs Phase 9's own indexing to be
auto-wired into the upstream pipeline (unchanged from before this fix).
This is real progress on the gap, not a full fix, and is described that
way rather than overstated.

## Embedder Decision — Why Phase 9's Own Default Changed

Auto-Reply's context quality depends entirely on Phase 9's retrieval
quality. TF-IDF (Phase 9's structural default) has a measured, literal
0.000-similarity blindness to paraphrased text
(`docs/embedding_model_decision.md`) — disqualifying for a feature whose
value proposition IS finding genuinely similar past cases. The fix is
NOT "inject MiniLM into Auto-Reply's own calls only" — Chroma collections
are not cross-model-compatible (`docs/embedding_versioning.md`'s own
rule: never mix vectors from different embedding models in one
collection), and a second, disconnected MiniLM-only collection would
never find anything indexed via Phase 9's own TF-IDF-backed
`/retrieval/index` endpoint. The correct fix, made now specifically
because no real data exists yet to migrate (Section C above), was to
switch Phase 9's OWN structural default (`RetrievalService._resolve_embedder()`)
to MiniLM and bump the collection name (`email_embeddings_v1` →
`email_embeddings_v2`, per `docs/embedding_versioning.md`'s own
prescribed mechanism — a new collection, `v1` not deleted). One
consistent retrieval subsystem now serves both Phase 9's own endpoints
and Auto-Reply.

## A Real Bug Found and Fixed During This Phase's Own End-to-End Testing

Running the real end-to-end path (real Postgres, real Groq API) exposed
a genuine performance bug that unit tests — which always inject an
explicit embedder — could not have caught:
`RetrievalService._resolve_embedder()`/`_resolve_vector_store()` used to
construct a brand-new default object on **every call**. Invisible with
TF-IDF (cheap either way); a real, measured ~1.4s-per-request cost once
MiniLM became the default (`AutoModel.from_pretrained()` reloading the
model into memory each time). Fixed by memoizing both on the
`RetrievalService` instance; `app/main.py`'s startup warmup was extended
to force both (previously only the embedder), since Chroma's
`PersistentClient` was separately found to have its own multi-second cold
start. Re-measured directly after the fix — see
`docs/phase10_requirements_traceability.md` "Measured Latency" for the
real before/after numbers. Full incident record:
`docs/error_analysis_auto_reply.md`.

## PII — A New Obligation Beyond Phase 9's Own Scrubbing

Phase 9's PII anonymization protected exactly one thing: the text going
INTO the vector store (`docs/phase9_pii_embedding_strategy.md`) — it
never touched `emails.body` in Postgres, which is stored raw, consistent
with every module's storage stance. Auto-Reply reads that same raw
`emails.body` for retrieved context AND receives the current email's raw
body directly — **both must be re-anonymized before they reach the LLM
prompt**, or FR-09 ("anonymize PII before passing email content to any
external API") is violated. This is a genuinely new code path
(`AutoReplyService.anonymize()`), not something inherited for free from
Phase 9. Verified directly:
`tests/test_auto_reply_service.py::test_pii_in_current_email_never_reaches_the_llm_prompt_raw`,
`::test_pii_in_retrieved_context_never_reaches_the_llm_prompt_raw`.

## Composition Boundary

Same in-process, no-HTTP boundary `docs/architecture_routing.md` and
`docs/architecture_rag.md` both established — `AutoReplyService` never
makes an HTTP call to another endpoint in this same application; it calls
`RetrievalService` (in-process, reused) and `LLMProvider` (the one
genuinely external call this module makes, to Groq's API).

## Security

See `docs/security_auto_reply.md` for the full review. Summary: retrieved/
current email content is treated as DATA, never INSTRUCTIONS (strict
prompt delimiting + an injection-heuristic pre-filter); PII is
re-anonymized before every LLM call; API keys are env-var only, never
logged (rotation logs `key_index`, never the key), never returned in a
response; no send capability exists anywhere, architecturally, not just
by policy.

## Performance

See `docs/phase10_requirements_traceability.md` "Measured Latency" for
real numbers (real Postgres + real Groq API, not estimated). All within
FR-50's 10s ceiling, including the cold-start case. **Not measured**:
concurrent load, P95/P99 under realistic traffic — no load-testing
infrastructure exists for any module in this codebase.

## Human Acceptance Rate Tracking (Post-Phase-10 fix #2)

FR-52 requires approval/rejection decisions to "feed back into reply
quality improvement" — the PRD's own >60% Human Acceptance Rate target
(§14.1) needs real per-action data to ever be measurable. Two mechanisms,
neither new infrastructure beyond what already existed:

1. **Durable**: `reply_drafts.status`/`reviewer_id`/`reviewed_at` already
   captured the action and its timing; `edit_distance` (new column,
   `app/nlp/edit_distance.py` — a plain Levenshtein implementation, no new
   dependency) is now computed and stored whenever a draft is edited,
   directly answering the PRD's own named secondary metric ("Average Edit
   Distance," §14.1).
2. **Observable**: each approve/edit/reject call also emits a structured
   log line (`auto_reply_review_action`: `draft_id`, `action`,
   `edit_distance`, `reviewed_at`) — the same `logger.info(..., extra={...})`
   convention every other module's endpoint already uses, not a new
   logging mechanism.

Computing the actual Human Acceptance Rate (approved+low-edit-distance
fraction of all reviewed drafts) is a query over `reply_drafts` once real
review data exists — not built as a dashboard/report this fix, since no
real data exists yet to report on (see `docs/rag_evaluation_auto_reply.md`).

## Ollama Fallback (Post-Phase-10 fix #5)

Previously deferred (see the PRD's own ADR-002, Ollama/Mistral-7B as a
self-hosted fallback) — now implemented, triggered specifically when Groq
returns a 429 (rate-limited, all configured keys exhausted) or 503
(service unavailable), not on every failure:

```
AutoReplyService._resolve_llm_provider() default:
    FallbackLLMProvider(primary=GroqProvider(...), fallback=OllamaProvider(...))
        .generate() tries GroqProvider first
        → LLMRateLimitedError (429) or LLMServiceUnavailableError (503) → retries via OllamaProvider
        → any other failure (timeout, auth, malformed request) → raises straight through, no fallback
```

`app/inference/ollama_provider.py` talks to a locally-running Ollama
server's REST API (`POST /api/chat`) directly via `httpx` — no `ollama`
SDK package added (same "direct HTTP call over a wrapper SDK" reasoning
`minilm_embedder.py` used to avoid `sentence-transformers`). No new
Protocol was introduced (`LLMProvider`'s Protocol already covered this —
the actual instruction that motivated this fix) — `FallbackLLMProvider`
is itself just another `LLMProvider` implementation, composing two
others, so `AutoReplyService` required zero changes beyond its default
construction.

**Verified against a real, locally-running Ollama server** (found
running in this dev environment during this fix, not assumed) — with one
disclosed caveat: the configured default model, `mistral:7b`, was not
pulled in that environment (a ~4GB download not warranted just to prove
the wiring). The request/response mechanism was instead verified for
real against a different, already-pulled model
(`qwen2.5:3b`), including the full fallback chain end-to-end (a simulated
Groq 429 correctly triggered a real HTTP call to the real local server,
returning real generated text). **A real, disclosed latency finding from
that verification**: the real Ollama call took ~11 seconds (cold model
load) — meaning if the fallback fires in production with a cold/unloaded
model, it can by itself exceed FR-50's 10s total budget. This is not
silently hidden: `FallbackLLMProvider` does not time-account the
fallback's budget against what the primary already spent (a disclosed
simplification, see that module's own docstring), and no attempt was
made to pre-warm Ollama's model the way `RetrievalService`'s embedder/
vector-store are warmed at startup (Ollama warmup was judged out of this
fix's minimal scope — a candidate follow-up, not silently assumed fine).

## Known Gaps

| Gap | Reason |
|---|---|
| `NO_SIMILAR_EMAILS` is likely still common, though less than before | Phase 9's `resolution_status` never auto-transitioned; Post-Phase-10 fix #3 (auto-mark-resolved on approve) now closes this gap gradually, one approved draft at a time, not all at once |
| No Human Acceptance Rate data yet | Tracking mechanism now exists (fix #2); still requires real agents using the review endpoints against real traffic, which does not exist yet |
| Ollama fallback's cold-start latency can exceed FR-50's budget | Real, measured (~11s) — disclosed above, not fixed this round (no Ollama pre-warming built) |
| `mistral:7b` (the configured Ollama model) was not pulled/verified in this dev environment | Wiring verified for real against a different, already-available model instead — disclosed, not assumed equivalent in quality |
| No auto-wiring into the Spam/Category/Routing pipeline | Same class of gap Phase 9 already disclosed for its own indexing — Auto-Reply's `/generate` works from raw subject/body directly, so this does not block FR-48 mechanically |
| No real tenant authentication | Same gap since Phase 1 — `reviewer_id`/`organization_id` are caller-supplied, not verified |
| No load testing | No infrastructure exists for this in any module |
| Injection pre-filter is a heuristic, not a guarantee | A small phrase-match list; the real defense is prompt-level data/instruction separation, disclosed as such |
| Presidio's analyzer/anonymizer are not warmed at startup | A pre-existing Phase 9 gap, not introduced or fixed by Phase 10 — contributes a smaller, disclosed remainder of the cold-start latency seen on a process's first request |
| No direct GPT-4o/Claude quality comparison | Disclosed explicitly in "The Quality Tradeoff" above — a general, known positioning, not a benchmark this project ran |
