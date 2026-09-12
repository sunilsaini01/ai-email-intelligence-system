import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { replyDraftsApi } from "../api/replyDrafts";
import type { ReplyDraftStatus } from "../types/replyDrafts";

// Same 30s baseline as every other dashboard query (see
// hooks/useDashboardData.ts's own comment) -- a fresh AI-drafted reply
// sitting unreviewed is exactly the kind of thing this page exists to
// surface promptly.
const REFETCH_INTERVAL_MS = 30_000;

export function useReplyDrafts(status: ReplyDraftStatus = "GENERATED") {
  return useQuery({
    queryKey: ["reply-drafts", status],
    queryFn: () => replyDraftsApi.list(status),
    refetchInterval: REFETCH_INTERVAL_MS,
  });
}

export function useReplyDraftMutations() {
  const queryClient = useQueryClient();
  const invalidate = () => void queryClient.invalidateQueries({ queryKey: ["reply-drafts"] });

  const approve = useMutation({
    mutationFn: ({ draftId, reviewerId }: { draftId: string; reviewerId: string }) =>
      replyDraftsApi.approve(draftId, reviewerId),
    onSuccess: invalidate,
  });

  const edit = useMutation({
    mutationFn: ({ draftId, editedText, reviewerId }: { draftId: string; editedText: string; reviewerId: string }) =>
      replyDraftsApi.edit(draftId, editedText, reviewerId),
    onSuccess: invalidate,
  });

  const reject = useMutation({
    mutationFn: ({ draftId, reviewerId }: { draftId: string; reviewerId: string }) =>
      replyDraftsApi.reject(draftId, reviewerId),
    onSuccess: invalidate,
  });

  return { approve, edit, reject };
}
