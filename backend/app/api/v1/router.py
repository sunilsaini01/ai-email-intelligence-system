"""
Versioned API router.

Why version at the router level (/api/v1/...) from day one:
    Retrofitting versioning after you have live consumers is painful — every
    client breaks the moment you change a response shape. Starting at /v1
    costs nothing now and means a future breaking change ships as /v2
    alongside the old one, not as a flag day for every integration.

Why the auth boundary lives HERE, not sprinkled across each endpoint
file (Phase 17, real authentication): a `Depends(get_current_user)` added
to one router at a time is exactly the kind of thing a future new
endpoint forgets to add -- fail-open by omission. Every business router
below is nested under `protected_router`, which carries the dependency
ONCE; a new endpoint file only has to be included here to be protected
automatically, the same "the layering exists now" principle
docs/architecture/architecture.md already established for the
services/ extraction seam. `health` and `auth` themselves are the only
two routers that must stay reachable without a token -- health for
liveness/readiness probes (see that router's own module docstring on
why it must never gate on anything), auth because you cannot present a
token to get a token.

Phase 18 (live mailbox ingestion) adds a THIRD reason a router must stay
outside `protected_router`: `mailbox.callback_router` is hit by the
user's browser being redirected by Google/Microsoft, which never carries
an Authorization header. `mailbox.router` (connect/list/disconnect) is a
normal business router and stays under `protected_router` like everything
else -- only the callback itself is the exception, and it authenticates
via its own signed `state` parameter instead (see
app/ingestion/oauth_state.py).
"""

from fastapi import APIRouter, Depends

from app.api.v1.endpoints import (
    admin,
    auth,
    category,
    dashboard,
    health,
    intent,
    mailbox,
    models,
    notifications,
    priority,
    reply,
    retrieval,
    routing,
    sentiment,
    spam,
    summarization,
    workflows,
)
from app.core.auth_dependency import get_current_user

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(mailbox.callback_router)
# The dashboard live-update socket authenticates itself (a WebSocket can't
# carry the Authorization header protected_router's dependency reads) --
# see app/api/v1/endpoints/dashboard.py's ws_router.
api_router.include_router(dashboard.ws_router)

protected_router = APIRouter(dependencies=[Depends(get_current_user)])
protected_router.include_router(spam.router)
protected_router.include_router(priority.router)
protected_router.include_router(category.router)
protected_router.include_router(summarization.router)
protected_router.include_router(sentiment.router)
protected_router.include_router(intent.router)
protected_router.include_router(routing.router)
protected_router.include_router(retrieval.router)
protected_router.include_router(reply.router)
protected_router.include_router(dashboard.router)
protected_router.include_router(workflows.router)
protected_router.include_router(mailbox.router)
protected_router.include_router(admin.router)
protected_router.include_router(notifications.router)
protected_router.include_router(models.router)
api_router.include_router(protected_router)
