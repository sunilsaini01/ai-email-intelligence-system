"""
OutlookProvider: MailboxProvider implementation for Microsoft
Outlook/Exchange via the Microsoft Graph API (Phase 18, FR-01/FR-02).

Talks to Microsoft's identity platform (v2.0 endpoint) and Graph directly
via `httpx` -- no `msal`/`msgraph-sdk` added, same reasoning as
GmailProvider's own docstring for avoiding a wrapper SDK here.

Incremental sync strategy (`fetch_new_messages`): Graph's delta query
(`/me/mailFolders/inbox/messages/delta`) is a paged, resumable diff --
each page carries either an `@odata.nextLink` (more pages exist right
now) or, on the final page, an `@odata.deltaLink` (the cursor to resume
from on the NEXT poll, once new mail exists). `cursor` is one of those
two URLs verbatim -- both are complete, directly-fetchable URLs Graph
itself hands back, so this provider never reconstructs query parameters
by hand for a resumed sync.

Disclosed limitation, mirrors GmailProvider's "start from now" stance:
Graph's delta query has no equivalent of Gmail's historyId shortcut -- a
bare first call would page through the mailbox's ENTIRE current message
list before reaching a deltaLink. On the FIRST sync (`cursor=None`), this
provider walks that pagination using a minimal `$select=id` projection
(cheap: no bodies/attachments fetched) purely to reach the deltaLink,
emitting zero InboundMessages, then stores that deltaLink as the cursor.
The practical effect is the same as Gmail: polling starts from "new mail
from now on," not the mailbox's backlog. If `max_messages` is reached
mid-page on a REAL (non-bootstrap) poll, the current `@odata.nextLink` is
stored as the cursor instead -- the next poll resumes mid-page rather
than re-fetching messages already returned.
"""

import logging
from datetime import UTC, datetime
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

logger = logging.getLogger("app.ingestion.outlook")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
DELTA_URL = f"{GRAPH_BASE}/me/mailFolders/inbox/messages/delta"
PROFILE_URL = f"{GRAPH_BASE}/me"

# openid/profile/email so the token also carries basic identity claims;
# Mail.Read is the one actual data scope; offline_access is required for
# Microsoft to issue a refresh token at all (without it, access-token-only,
# useless for a background poller -- same requirement Gmail's
# access_type=offline serves).
SCOPES = "openid profile email offline_access https://graph.microsoft.com/Mail.Read"

# First-sync bootstrap only (see module docstring) -- cheap enough that
# walking the whole mailbox to reach the deltaLink doesn't fetch bodies.
_BOOTSTRAP_PAGE_SIZE = 100


class OutlookProviderUnavailable(RuntimeError):
    """Raised at construction time when Microsoft OAuth credentials are not configured."""


class OutlookProvider:
    provider_name = "outlook"

    def __init__(self, client_id: str, client_secret: str, tenant_id: str, redirect_uri: str):
        if not client_id or not client_secret:
            raise OutlookProviderUnavailable(
                "Outlook is not configured. Set MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET in backend/.env."
            )
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._authorize_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
        self._token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    def build_authorization_url(self, state: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "response_mode": "query",
            "scope": SCOPES,
            "state": state,
        }
        return f"{self._authorize_url}?{urlencode(params)}"

    def exchange_code_for_tokens(self, code: str) -> OAuthTokens:
        try:
            response = httpx.post(
                self._token_url,
                data={
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": self._redirect_uri,
                    "grant_type": "authorization_code",
                    "scope": SCOPES,
                },
                timeout=15.0,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise MailboxProviderError(f"Outlook token exchange failed: {e}") from e

        return self._tokens_from_response(response.json())

    def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        try:
            response = httpx.post(
                self._token_url,
                data={
                    "refresh_token": refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                    "scope": SCOPES,
                },
                timeout=15.0,
            )
        except httpx.HTTPError as e:
            raise MailboxProviderError(f"Outlook token refresh request failed: {e}") from e

        if response.status_code == 400:
            # invalid_grant -- Microsoft's own error for a revoked/expired
            # refresh token. See Microsoft identity platform error codes.
            raise MailboxAuthorizationError(f"Outlook refresh token was rejected: {response.text}")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise MailboxProviderError(f"Outlook token refresh failed: {e}") from e

        data = response.json()
        data.setdefault("refresh_token", refresh_token)  # not every refresh grant rotates it
        return self._tokens_from_response(data)

    def _tokens_from_response(self, data: dict) -> OAuthTokens:
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        if not access_token or not refresh_token:
            raise MailboxProviderError(
                "Outlook token response missing access_token/refresh_token -- "
                "make sure offline_access was included in the consented scopes."
            )
        expires_at = datetime.now(UTC).timestamp() + float(data.get("expires_in", 3600))

        try:
            profile_response = httpx.get(PROFILE_URL, headers=_bearer(access_token), timeout=15.0)
            profile_response.raise_for_status()
        except httpx.HTTPError as e:
            raise MailboxProviderError(f"Outlook profile lookup failed: {e}") from e
        profile = profile_response.json()
        email_address = profile.get("mail") or profile.get("userPrincipalName")
        if not email_address:
            raise MailboxProviderError("Outlook profile response had neither `mail` nor `userPrincipalName`.")

        return OAuthTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=datetime.fromtimestamp(expires_at, tz=UTC),
            email_address=email_address,
            initial_sync_cursor=None,  # Outlook establishes its cursor via fetch_new_messages(cursor=None) instead
        )

    def fetch_new_messages(self, access_token: str, cursor: str | None, max_messages: int) -> MessagePage:
        if cursor is None:
            return self._bootstrap_to_delta_link(access_token)
        try:
            return self._page_through_delta(access_token, cursor, max_messages, parse_messages=True)
        except _DeltaCursorExpired:
            # See module docstring's disclosed limitation, mirrors
            # GmailProvider's 404-on-expired-historyId handling: resync
            # from now rather than getting stuck retrying a dead cursor.
            return self._bootstrap_to_delta_link(access_token)

    def _bootstrap_to_delta_link(self, access_token: str) -> MessagePage:
        """See module docstring's disclosed limitation. Walks every page
        with a minimal projection, discarding message content, until a
        deltaLink is reached."""
        url = f"{DELTA_URL}?{urlencode({'$select': 'id', '$top': _BOOTSTRAP_PAGE_SIZE}, safe='$')}"
        while True:
            data = self._get_delta_page(access_token, url)
            delta_link = data.get("@odata.deltaLink")
            if delta_link:
                return MessagePage(messages=[], next_cursor=delta_link)
            next_link = data.get("@odata.nextLink")
            if not next_link:
                raise MailboxProviderError("Outlook delta bootstrap ended without a deltaLink or nextLink.")
            url = next_link

    def _page_through_delta(self, access_token: str, cursor: str, max_messages: int, *, parse_messages: bool) -> MessagePage:
        messages: list[InboundMessage] = []
        url = cursor
        while True:
            data = self._get_delta_page(access_token, url)
            for entry in data.get("value", []):
                if "@removed" in entry:
                    continue  # a deletion/move, not new mail
                if len(messages) >= max_messages:
                    break
                message = self._parse_message(access_token, entry) if parse_messages else None
                if message is not None:
                    messages.append(message)

            delta_link = data.get("@odata.deltaLink")
            next_link = data.get("@odata.nextLink")
            if len(messages) >= max_messages and next_link:
                # Cap reached mid-page -- resume from exactly here next
                # poll rather than re-fetching messages already returned.
                return MessagePage(messages=messages, next_cursor=next_link)
            if delta_link:
                return MessagePage(messages=messages, next_cursor=delta_link)
            if not next_link:
                raise MailboxProviderError("Outlook delta page ended without a deltaLink or nextLink.")
            url = next_link

    def _get_delta_page(self, access_token: str, url: str) -> dict:
        try:
            response = httpx.get(url, headers=_bearer(access_token), timeout=15.0)
        except httpx.HTTPError as e:
            raise MailboxProviderError(f"Outlook delta request failed: {e}") from e

        if response.status_code == 401:
            raise MailboxAuthorizationError("Outlook rejected the access token during delta sync.")
        if response.status_code == 410:
            # Gone -- Graph's own signal that this deltaLink/nextLink has
            # expired server-side (analogous to Gmail's 404 on an expired
            # historyId). Same resync-from-now handling.
            logger.warning("outlook_delta_cursor_expired_resyncing")
            raise _DeltaCursorExpired
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise MailboxProviderError(f"Outlook delta request failed: {e}") from e
        return response.json()

    def _parse_message(self, access_token: str, entry: dict) -> InboundMessage | None:
        try:
            sender_email = ((entry.get("from") or {}).get("emailAddress") or {}).get("address", "")
            body = entry.get("body") or {}
            content = body.get("content", "")
            body_text = strip_html(content) if body.get("contentType") == "html" else content

            attachments: list[InboundAttachment] = []
            if entry.get("hasAttachments"):
                attachments = self._fetch_attachment_metadata(access_token, entry["id"])

            return InboundMessage(
                message_id=entry["id"],
                thread_id=entry.get("conversationId", entry["id"]),
                sender_email=sender_email,
                subject=entry.get("subject", ""),
                body_text=body_text.strip(),
                received_at=datetime.fromisoformat(entry["receivedDateTime"].replace("Z", "+00:00")),
                attachments=attachments,
            )
        except Exception:
            # One malformed message shouldn't sink the whole poll cycle --
            # same "skip and log" stance as GmailProvider._fetch_message.
            logger.warning("outlook_message_parse_failed", exc_info=True, extra={"message_id": entry.get("id")})
            return None

    def _fetch_attachment_metadata(self, access_token: str, message_id: str) -> list[InboundAttachment]:
        url = f"{GRAPH_BASE}/me/messages/{message_id}/attachments?{urlencode({'$select': 'name,contentType,size'}, safe='$')}"
        try:
            response = httpx.get(url, headers=_bearer(access_token), timeout=15.0)
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning("outlook_attachment_metadata_fetch_failed", extra={"message_id": message_id, "error": str(e)})
            return []
        return [
            InboundAttachment(
                filename=item.get("name", ""),
                mime_type=item.get("contentType", "application/octet-stream"),
                size_bytes=item.get("size", 0),
            )
            for item in response.json().get("value", [])
        ]


class _DeltaCursorExpired(MailboxProviderError):
    """Internal-only signal for a 410 Gone -- caught by fetch_new_messages
    below, never escapes this module."""


def _bearer(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}
