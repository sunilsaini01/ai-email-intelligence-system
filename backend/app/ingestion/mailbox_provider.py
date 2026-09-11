"""
Protocol boundary for a connected mailbox provider (Phase 18, FR-01/
FR-02/FR-03).

Mirrors app/inference/llm_provider.py's Protocol-over-concrete-provider
pattern: GmailProvider/OutlookProvider/FakeMailboxProvider (tests) all
implement this Protocol, and every caller -- the connect/callback
endpoints, the poller in app/agents/runner.py -- depends on the Protocol
only, never a concrete provider class directly. Adding a third provider
later is a new implementation of this Protocol, not a change to any
caller.

Calls are deliberately synchronous (plain `httpx.get`/`httpx.post`), same
as app/inference/ollama_provider.py -- this is a small, blocking API
surface, not a place this codebase reaches for an async HTTP client (see
that module's docstring for the precedent). The poller in
app/agents/runner.py is the one caller running inside an asyncio event
loop alongside six Kafka consumers; it wraps these calls in
`asyncio.to_thread` rather than accepting them as a blocking call on that
shared loop -- see that module's own comment.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


class MailboxProviderError(RuntimeError):
    """A provider (Google/Microsoft) API call failed: network error,
    malformed response, or an HTTP error not specifically an auth
    rejection (see MailboxAuthorizationError below for that case)."""


class MailboxAuthorizationError(MailboxProviderError):
    """The stored refresh token (or a just-used access token) was
    rejected by the provider -- typically because the user revoked this
    app's access from their Google/Microsoft account security settings,
    outside of this application entirely. Distinguished from a generic
    MailboxProviderError so the poller can mark the connection `error`
    with an actionable message instead of retrying forever against a
    token that will never work again (see
    app/database/repositories/mailbox_connection_repository.py's
    mark_error)."""


@dataclass(frozen=True)
class OAuthTokens:
    access_token: str
    # None on a refresh grant that didn't issue a new refresh token --
    # Google in particular only issues one on the very first authorization
    # unless the request explicitly forces re-consent. See
    # MailboxConnectionRepository.update_tokens's own docstring for how
    # callers are expected to handle this (keep the existing one).
    refresh_token: str | None
    expires_at: datetime
    # Confirmed by calling the provider's OWN profile endpoint with the
    # just-issued access token, never trusted from client-supplied input
    # -- this is the mailbox address that gets stored and displayed, so
    # it must be real.
    email_address: str
    # Gmail: the profile's historyId at connect time, used as the very
    # first sync_cursor so the poller starts from "new mail from now on,"
    # not the mailbox's entire history. Outlook's delta API has no
    # equivalent concept -- always None for OutlookProvider (its first
    # fetch_new_messages call establishes the initial deltaLink instead).
    initial_sync_cursor: str | None = None


@dataclass(frozen=True)
class InboundAttachment:
    filename: str
    mime_type: str
    size_bytes: int


@dataclass(frozen=True)
class InboundMessage:
    message_id: str
    thread_id: str
    sender_email: str
    subject: str
    body_text: str  # HTML already stripped to plain text -- see each provider's own body extraction
    received_at: datetime
    attachments: list[InboundAttachment] = field(default_factory=list)


@dataclass(frozen=True)
class MessagePage:
    messages: list[InboundMessage]
    next_cursor: str  # opaque -- see MailboxConnection.sync_cursor's own docstring on why


@runtime_checkable
class MailboxProvider(Protocol):
    provider_name: str

    def build_authorization_url(self, state: str) -> str:
        """`state` is an opaque, signed token (app/ingestion/oauth_state.py)
        the provider round-trips back unmodified to the callback -- this
        Protocol never sees or interprets it."""
        ...

    def exchange_code_for_tokens(self, code: str) -> OAuthTokens:
        """Raises MailboxProviderError on any failure -- an authorization
        code is single-use and short-lived, so there is no meaningful
        distinction between "revoked" and "expired/already used" worth a
        separate exception type here (unlike refresh_access_token below,
        where that distinction matters for a long-lived stored credential)."""
        ...

    def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        """Raises MailboxAuthorizationError if the refresh token itself was
        rejected (revoked/expired), MailboxProviderError for anything else."""
        ...

    def fetch_new_messages(self, access_token: str, cursor: str | None, max_messages: int) -> MessagePage:
        """`cursor=None` means "first sync for this connection" -- both
        providers interpret that as "start from now," never as "fetch this
        mailbox's entire history" (see OAuthTokens.initial_sync_cursor and
        each provider's own module docstring). Raises
        MailboxAuthorizationError if access_token is rejected -- callers
        are expected to have already refreshed a token close to expiry, so
        this is specifically the "expired mid-poll or revoked" case, not
        the routine path. Raises MailboxProviderError for anything else."""
        ...
