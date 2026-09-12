import { apiGet, apiPost } from "./client";
import type { ReplyDraft, ReplyDraftListResponse, ReplyDraftStatus } from "../types/replyDrafts";

export const replyDraftsApi = {
  list: (status: ReplyDraftStatus = "GENERATED") =>
    apiGet<ReplyDraftListResponse>("/reply", { status }),

  approve: (draftId: string, reviewerId: string) =>
    apiPost<ReplyDraft>(`/reply/${draftId}/approve`, { reviewer_id: reviewerId || null }),

  edit: (draftId: string, editedText: string, reviewerId: string) =>
    apiPost<ReplyDraft>(`/reply/${draftId}/edit`, { edited_text: editedText, reviewer_id: reviewerId || null }),

  reject: (draftId: string, reviewerId: string) =>
    apiPost<ReplyDraft>(`/reply/${draftId}/reject`, { reviewer_id: reviewerId || null }),
};
