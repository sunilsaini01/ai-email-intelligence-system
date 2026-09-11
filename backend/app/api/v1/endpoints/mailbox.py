"""
Mailbox connect/callback/list/disconnect endpoints (Phase 18, FR-01/FR-02).

`connect` and `callback` are split across two routers on purpose (see
app/api/v1/router.py's own module docstring for the general pattern):
`connect` requires a normal Bearer token like every other business
endpoint, but `callback` is hit by the user's BROWSER being redirected by
Google/Microsoft -- there is no Authorization header on that request, so
it cannot sit behind protected_router's `Depends(get_current_user)`.
Identity for `callback` instead comes from the signed `state` parameter
`connect` minted (app/ingestion/oauth_state.py), which the provider
guarantees to round-trip back unmodified.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_dependency import get_current_user
from app.core.token_encryption import encrypt_token
from app.database.repositories.mailbox_connection_repository import MailboxConnectionRepository
from app.database.session import get_db
from app.ingestion.gmail_provider import GmailProviderUnavailable
from app.ingestion.mailbox_provider import MailboxProviderError
from app.ingestion.oauth_state import InvalidOAuthState, build_state, verify_state
from app.ingestion.outlook_provider import OutlookProviderUnavailable
from app.ingestion.provider_factory import build_provider
from app.models.mailbox_connection import MAILBOX_PROVIDERS
from app.models.user import User
from app.schemas.mailbox import MailboxConnectionListResponse, MailboxConnectionResponse, MailboxConnectResponse

router = APIRouter(prefix="/mailbox", tags=["Mailbox Ingestion"])
callback_router = APIRouter(prefix="/mailbox", tags=["Mailbox Ingestion"])
logger = logging.getLogger("app.mailbox")


def _validate_provider(provider: str) -> None:
    if provider not in MAILBOX_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Unknown mailbox provider: {provider!r}.")


@router.get("/{provider}/connect", response_model=MailboxConnectResponse)
async def connect_mailbox(
    provider: str,
    current_user: User = Depends(get_current_user),
) -> MailboxConnectResponse:
    _validate_provider(provider)
    try:
        mailbox_provider = build_provider(provider)
    except (GmailProviderUnavailable, OutlookProviderUnavailable) as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    state = build_state(organization_id=current_user.organization_id, user_id=current_user.id, provider=provider)
    return MailboxConnectResponse(authorization_url=mailbox_provider.build_authorization_url(state))


@callback_router.get("/{provider}/callback")
async def mailbox_callback(
    provider: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    _validate_provider(provider)

    if error is not None:
        # The user declined consent on Google/Microsoft's own screen --
        # not a bug, not something to log as an error.
        return _html_response(f"Mailbox connection was not completed: {error}", status_code=400)
    if code is None or state is None:
        return _html_response("Mailbox connection callback is missing 'code' or 'state'.", status_code=400)

    try:
        organization_id, user_id = verify_state(state, expected_provider=provider)
    except InvalidOAuthState as e:
        logger.warning("mailbox_callback_invalid_state", extra={"provider": provider, "error": str(e)})
        return _html_response("This connection link has expired or is invalid. Please try connecting again.", status_code=400)

    try:
        mailbox_provider = build_provider(provider)
        tokens = mailbox_provider.exchange_code_for_tokens(code)
    except (GmailProviderUnavailable, OutlookProviderUnavailable, MailboxProviderError) as e:
        logger.error("mailbox_token_exchange_failed", exc_info=True, extra={"provider": provider})
        return _html_response(f"Could not complete the mailbox connection: {e}", status_code=502)

    repo = MailboxConnectionRepository(db)
    connection = await repo.upsert(
        organization_id=organization_id,
        connected_by_user_id=user_id,
        provider=provider,
        email_address=tokens.email_address,
        access_token_encrypted=encrypt_token(tokens.access_token),
        access_token_expires_at=tokens.expires_at,
        refresh_token_encrypted=encrypt_token(tokens.refresh_token) if tokens.refresh_token else "",
    )
    if tokens.initial_sync_cursor is not None:
        await repo.update_sync_cursor(connection, tokens.initial_sync_cursor)

    logger.info("mailbox_connected", extra={"provider": provider, "connection_id": str(connection.id)})
    return _html_response(f"Connected {tokens.email_address} ({provider}). You can close this tab.")


@router.get("/connections", response_model=MailboxConnectionListResponse)
async def list_mailbox_connections(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MailboxConnectionListResponse:
    repo = MailboxConnectionRepository(db)
    connections = await repo.list_for_organization(current_user.organization_id)
    return MailboxConnectionListResponse(
        connections=[
            MailboxConnectionResponse(
                id=c.id,
                provider=c.provider,
                email_address=c.email_address,
                status=c.status,
                last_synced_at=c.last_synced_at,
                last_error=c.last_error,
                created_at=c.created_at,
            )
            for c in connections
        ]
    )


@router.delete("/connections/{connection_id}", status_code=204)
async def disconnect_mailbox(
    connection_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    repo = MailboxConnectionRepository(db)
    connection = await repo.get_by_id(current_user.organization_id, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Mailbox connection not found.")
    await repo.soft_delete(connection)


def _html_response(message: str, status_code: int = 200) -> Response:
    return Response(content=f"<html><body><p>{message}</p></body></html>", media_type="text/html", status_code=status_code)
