import { useState } from "react";
import { useDashboardFilters } from "../hooks/useDashboardFilters";
import { useReplyDraftMutations, useReplyDrafts } from "../hooks/useReplyDrafts";
import { QueryState } from "../components/QueryState";
import type { ReplyDraft } from "../types/replyDrafts";

function ReplyDraftCard({ draft, reviewerId }: { draft: ReplyDraft; reviewerId: string }) {
  const [text, setText] = useState(draft.generated_text ?? "");
  const { approve, edit, reject } = useReplyDraftMutations();
  const isEdited = text !== (draft.generated_text ?? "");
  const isBusy = approve.isPending || edit.isPending || reject.isPending;

  return (
    <div className="reply-draft-card">
      <div className="reply-draft-card__source">
        <div className="reply-draft-card__subject">{draft.source_subject || "(no subject)"}</div>
        <p className="reply-draft-card__body">{draft.source_body}</p>
      </div>

      <label className="reply-draft-card__label">
        Drafted reply
        {draft.retrieved_context_count === 0 && (
          <span className="reply-draft-card__warning"> — no similar past emails found, review carefully</span>
        )}
      </label>
      <textarea
        className="reply-draft-card__textarea"
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={6}
        disabled={draft.generated_text === null}
      />
      {draft.failure_reason && <p className="state-message state-message--error">{draft.failure_reason}</p>}

      <div className="reply-draft-card__meta">
        {draft.llm_provider && <span>via {draft.llm_provider}</span>}
        {draft.retrieved_context_count > 0 && <span>{draft.retrieved_context_count} similar email(s) used</span>}
      </div>

      <div className="reply-draft-card__actions">
        <button
          type="button"
          className="preset-btn preset-btn--active"
          disabled={isBusy || draft.generated_text === null}
          onClick={() => (isEdited ? edit.mutate({ draftId: draft.draft_id, editedText: text, reviewerId }) : approve.mutate({ draftId: draft.draft_id, reviewerId }))}
        >
          {isEdited ? "Save edited reply" : "Approve as-is"}
        </button>
        <button type="button" className="preset-btn preset-btn--danger" disabled={isBusy} onClick={() => reject.mutate({ draftId: draft.draft_id, reviewerId })}>
          Reject
        </button>
      </div>
    </div>
  );
}

export function ReplyDraftsPage() {
  const { reviewerId } = useDashboardFilters();
  const query = useReplyDrafts("GENERATED");

  return (
    <div>
      <h2>Reply Drafts</h2>
      <p className="page-note">
        AI-drafted replies waiting for a human decision. Nothing here is ever sent automatically -- approving,
        editing, or rejecting is the only way a draft leaves this queue. Set a reviewer name in the "Reviewer" field
        above to attach it to your decisions.
      </p>
      <QueryState query={query}>
        {(data) =>
          data.drafts.length === 0 ? (
            <div className="state-message">No reply drafts waiting for review right now.</div>
          ) : (
            <div className="reply-draft-list">
              {data.drafts.map((draft) => (
                <ReplyDraftCard key={draft.draft_id} draft={draft} reviewerId={reviewerId} />
              ))}
            </div>
          )
        }
      </QueryState>
    </div>
  );
}
