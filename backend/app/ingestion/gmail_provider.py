"""
GmailProvider: MailboxProvider implementation for Gmail (Phase 18,
FR-01/FR-02).

Talks to Google's OAuth2 endpoints and the Gmail REST API directly via
`httpx` -- no `google-api-python-client`/`google-auth` SDK added, same
"direct HTTP call over a wrapper SDK for a small, well-documented API
surface" preference app/inference/ollama_provider.py's docstring already
states for this codebase.

Incremental sync strategy (`fetch_new_messages`): Gmail's `users.history.list`
is the only API that returns "what changed since X" rather than "the
whole mailbox" -- `messages.list` alone has no cursor semantics. `cursor`
is a Gmail `historyId` (an opaque, monotonically increasing string Gmail
itself defines). On the FIRST sync for a connection (`cursor=None`), this
does NOT call history.list (there is nothing to diff against yet) --
`exchange_code_for_tokens` already captured the profile's `historyId` at
connect time as `OAuthTokens.initial_sync_cursor`, so the very first poll
starts from "new mail from now on," never floods the pipeline with the
mailbox's entire backlog.

Disclosed limitation: Gmail retains history for a rolling ~7 days
(Google's own documented limit, not a number this codebase chose). If a
connection's stored cursor falls outside that window (the poller has been
down, or a connection sat unrefreshed, for longer than that), Gmail
returns 404 for history.list. This provider treats that specifically as
"resync from now" -- refetches the current historyId as the new cursor
and returns an empty page for this poll -- rather than raising, so one
stale connection doesn't get stuck in a permanent error loop. The
practical consequence is disclosed, not hidden: mail received during that
gap is never ingested. Fixing that (a full backfill on cursor-expiry) is
real additional complexity this phase's scope doesn't require.
"""

import base64
import logging
from datetime import UTC, datetime
from email.utils import parseaddr
from urllib.parse import urlencode

import httpx

from app.ingestion.mailbox_provider import (
    InboundAttachment,
    InboundMessage,
    MailboxAuthorizationError,
    MailboxProviderError,
    MessagePage,
    OAuthTokens,
)
from app.preprocessing.text_helpers import strip_html

logger = logging.getLogger("app.ingestion.gmail")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 -- an API endpoint URL, not a credential
PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
HISTORY_URL = "https://gmail.googleapis.com/gmail/v1/users/me/history"

# openid+email so the token also carries an ID token we could use to
# double check the address; gmail.readonly is the one actual data scope
# -- FR-01/FR-02 need to READ mail, never send/modify/delete.
SCOPES = "openid email https://www.googleapis.com/auth/gmail.readonly"


class GmailProviderUnavailable(RuntimeError):
    """Raised at construction time when Google OAuth credentials are not configured."""


class GmailProvider:
    provider_name = "gmail"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        if not client_id or not client_secret:
            raise GmailProviderUnavailable(
                "Gmail is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env."
            )
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri

    def build_authorization_url(self, state: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            # offline: issue a refresh token (the default without this is
            # access-token-only, useless for a background poller).
            # prompt=consent: forces Google to issue a refresh token on
            # EVERY authorization, not just the account's first-ever one
            # -- without it, reconnecting after a revoke would silently
            # get no refresh_token back at all.
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_tokens(self, code: str) -> OAuthTokens:
        try:
            response = httpx.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": self._redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=15.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise MailboxProviderError(f"Gmail token exchange failed: {e}") from e

        return self._tokens_from_response(response.json(), require_refresh_token=True)

    def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        try:
            response = httpx.post(
                TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                },
                timeout=15.0,
            )
        except httpx.HTTPError as e:
            raise MailboxProviderError(f"Gmail token refresh request failed: {e}") from e

        if response.status_code in (400, 401):
            # invalid_grant is Google's own error for "this refresh token
            # was revoked or is no longer valid" -- see Google's OAuth2 error docs.
            raise MailboxAuthorizationError(f"Gmail refresh token was rejected: {response.text}")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise MailboxProviderError(f"Gmail token refresh failed: {e}") from e

        data = response.json()
        data.setdefault("refresh_token", refresh_token)  # refresh grants don't echo it back
        return self._tokens_from_response(data, require_refresh_token=False)

    def _tokens_from_response(self, data: dict, *, require_refresh_token: bool) -> OAuthTokens:
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        if not access_token or (require_refresh_token and not refresh_token):
            raise MailboxProviderError(
                "Gmail token response missing access_token/refresh_token -- "
                "if reconnecting, make sure Google's consent screen was actually shown."
            )
        expires_at = datetime.now(UTC).timestamp() + float(data.get("expires_in", 3600))

        profile = self._fetch_profile(access_token)
        return OAuthTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=datetime.fromtimestamp(expires_at, tz=UTC),
            email_address=profile["emailAddress"],
            initial_sync_cursor=str(profile["historyId"]),
        )

    def _fetch_profile(self, access_token: str) -> dict:
        try:
            response = httpx.get(PROFILE_URL, headers=_bearer(access_token), timeout=15.0)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise MailboxProviderError(f"Gmail profile lookup failed: {e}") from e
        return response.json()

    def fetch_new_messages(self, access_token: str, cursor: str | None, max_messages: int) -> MessagePage:
        if cursor is None:
            # No baseline yet -- establish one from the current profile
            # rather than fetching this mailbox's entire history. Same
            # "start from now" stance the module docstring commits to.
            profile = self._fetch_profile(access_token)
            return MessagePage(messages=[], next_cursor=str(profile["historyId"]))

        try:
            response = httpx.get(
                HISTORY_URL,
                headers=_bearer(access_token),
                params={"startHistoryId": cursor, "historyTypes": "messageAdded", "maxResults": max_messages},
                timeout=15.0,
            )
        except httpx.HTTPError as e:
            raise MailboxProviderError(f"Gmail history lookup failed: {e}") from e

        if response.status_code == 401:
            raise MailboxAuthorizationError("Gmail rejected the access token during history lookup.")
        if response.status_code == 404:
            # startHistoryId outside Gmail's retention window -- see module
            # docstring's disclosed limitation.
            logger.warning("gmail_history_cursor_expired_resyncing", extra={"cursor": cursor})
            profile = self._fetch_profile(access_token)
            return MessagePage(messages=[], next_cursor=str(profile["historyId"]))
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise MailboxProviderError(f"Gmail history lookup failed: {e}") from e

        data = response.json()
        message_ids: list[str] = []
        for entry in data.get("history", []):
            for added in entry.get("messagesAdded", []):
                message_ids.append(added["message"]["id"])

        messages = []
        for message_id in message_ids[:max_messages]:
            message = self._fetch_message(access_token, message_id)
            if message is not None:
                messages.append(message)

        next_cursor = str(data.get("historyId", cursor))
        return MessagePage(messages=messages, next_cursor=next_cursor)

    def _fetch_message(self, access_token: str, message_id: str) -> InboundMessage | None:
        try:
            response = httpx.get(
                f"{MESSAGES_URL}/{message_id}",
                headers=_bearer(access_token),
                params={"format": "full"},
                timeout=15.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            # One malformed/deleted message shouldn't sink the whole poll
            # cycle for this connection -- log and skip, same "one bad row
            # doesn't crash the loop" stance as TokenDecryptionError.
            logger.warning("gmail_message_fetch_failed", extra={"message_id": message_id, "error": str(e)})
            return None

        data = response.json()
        payload = data.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        sender_email = parseaddr(headers.get("from", ""))[1]
        body_text, attachments = _extract_body_and_attachments(payload)

        return InboundMessage(
            message_id=data["id"],
            thread_id=data.get("threadId", data["id"]),
            sender_email=sender_email,
            subject=headers.get("subject", ""),
            body_text=body_text,
            received_at=datetime.fromtimestamp(int(data["internalDate"]) / 1000, tz=UTC),
            attachments=attachments,
        )


def _bearer(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def _b64url_decode(data: str) -> str:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _extract_body_and_attachments(payload: dict) -> tuple[str, list[InboundAttachment]]:
    """Walks Gmail's MIME part tree. Prefers text/plain over text/html
    (the first non-empty one found, matching typical multipart/alternative
    ordering); falls back to stripping HTML to text (app/preprocessing/
    text_helpers.strip_html, reused rather than re-implemented) if only an
    HTML part exists. A part with a `filename` is recorded as attachment
    METADATA ONLY (FR-04's literal scope) -- its `body.data` is never
    fetched or stored."""
    plain_text: str | None = None
    html_text: str | None = None
    attachments: list[InboundAttachment] = []

    def walk(part: dict) -> None:
        nonlocal plain_text, html_text
        mime_type = part.get("mimeType", "")
        filename = part.get("filename") or ""
        body = part.get("body", {})

        if filename:
            attachments.append(
                InboundAttachment(
                    filename=filename,
                    mime_type=mime_type or "application/octet-stream",
                    size_bytes=body.get("size", 0),
                )
            )
        elif mime_type == "text/plain" and body.get("data") and plain_text is None:
            plain_text = _b64url_decode(body["data"])
        elif mime_type == "text/html" and body.get("data") and html_text is None:
            html_text = _b64url_decode(body["data"])

        for sub_part in part.get("parts") or []:
            walk(sub_part)

    walk(payload)

    if plain_text:
        return plain_text.strip(), attachments
    if html_text:
        return strip_html(html_text).strip(), attachments
    return "", attachments
