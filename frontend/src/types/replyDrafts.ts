// Mirrors backend/app/schemas/auto_reply.py exactly -- see dashboard.ts's
// own comment on why (one field added/renamed on either side without the
// other is a real bug, not a typo).

export type ReplyDraftStatus = "GENERATED" | "EDITED" | "APPROVED" | "REJECTED" | "FAILED";

export interface ReplyDraft {
  draft_id: string;
  status: ReplyDraftStatus;
  generation_policy: string;
  source_subject: string;
  source_body: string;
  generated_text: string | null;
  edited_text: string | null;
  edit_distance: number | null;
  retrieved_context_count: number;
  retrieved_email_ids: string[];
  llm_provider: string | null;
  llm_model: string | null;
  embedding_model: string | null;
  retrieval_latency_ms: number | null;
  llm_latency_ms: number | null;
  total_latency_ms: number | null;
  failure_reason: string | null;
  created_at: string;
  reviewed_at: string | null;
}

export interface ReplyDraftListResponse {
  drafts: ReplyDraft[];
}
