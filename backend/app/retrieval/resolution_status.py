"""
Resolution status (Module 9 / Phase 9, Step 4 -- FR-46).

No resolution-status concept exists anywhere in this codebase before this
phase -- confirmed by repository audit, not assumed. The PRD names
"resolution status" as a required filter (FR-46) but never defines its
taxonomy anywhere in the document. This is an INVENTED, minimal,
extensible taxonomy, confirmed with the project owner before
implementation -- not derived from a PRD-specified enum, because none
exists. See docs/resolution_status_design.md for the full record.

No automatic transition logic exists or is implied: nothing in this
codebase currently marks anything "resolved" (no ticket/case workflow, no
agent-action layer). Every email defaults to OPEN at index time and only
ever changes via an explicit, human-driven update
(PATCH /api/v1/retrieval/emails/{id}/resolution) -- pretending an
automatic workflow exists here would misrepresent what this phase built.
"""

OPEN = "OPEN"
IN_PROGRESS = "IN_PROGRESS"
RESOLVED = "RESOLVED"
CLOSED = "CLOSED"

RESOLUTION_STATUSES: tuple[str, ...] = (OPEN, IN_PROGRESS, RESOLVED, CLOSED)

DEFAULT_RESOLUTION_STATUS = OPEN
