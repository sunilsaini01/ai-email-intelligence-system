# Embedding Input Strategy (Module 9 / Phase 9, Step 7)

## What Gets Embedded

`subject` then `body`, separated by a blank line
(`app/retrieval/embedding_input.py:build_embedding_text()`):

```
f"{subject}\n\n{body}"
```

Not blindly concatenated with every available field. Explicitly excluded:
database IDs, timestamps, `sender_email`, `category`/`department` labels,
and any other technical metadata — those live as **vector-store metadata**
(`ChromaVectorStore`'s `metadata` argument, `docs/vector_store_decision.md`),
never baked into the text a model turns into semantic content. Including
e.g. a UUID or a raw timestamp string in the embedded text would inject
noise a TF-IDF/transformer model would treat as meaningful tokens, actively
degrading similarity quality for no benefit.

## Why Subject Is Not Weighted Differently From Body

Considered (per the brief's example: `"Subject: Refund request for order
#12345"` carrying dense signal) but not implemented as a separate
weighting mechanism — both embedders already handle this reasonably by
construction:

- **TF-IDF**: subject and body are concatenated into one document before
  vectorization; a short, topic-dense subject line's terms compete on
  equal footing with the (usually longer) body's terms in the resulting
  sparse vector. No artificial subject boost was added — no evidence
  (from the benchmark or the qualitative gold set) that this concatenation
  underperforms enough to justify the complexity of a weighted-field
  scheme.
- **MiniLM**: mean-pooling over all tokens in the combined text — a
  transformer's attention mechanism already lets contextually important
  tokens (which a well-written subject often contains) contribute more to
  the final representation than a naive weighting scheme would hand-tune.

If a future evaluation (with a larger, more representative gold set) shows
subject-weighting matters, it's a small, contained change to
`build_embedding_text()` — not a redesign.

## Cleaning Before Embedding

`EmailPreprocessor(SUMMARY_CONFIG)` — the same "strip HTML, signatures,
quoted-reply blocks; otherwise preserve natural phrasing" config Module 6
already established, reused rather than inventing a fourth preprocessing
config for this codebase's `EmailPreprocessor` (see
`docs/embedding_model_decision.md` for why individual embedders, not this
shared cleaning step, are responsible for any further stopword/lemmatization
tuning they specifically need).

## PII

See `docs/phase9_pii_embedding_strategy.md` for the full record — cleaning
happens before anonymization, so Presidio's recognizers see natural text,
not raw HTML markup.
