"""
Deterministic MailboxProvider fake for tests (mirrors
app/inference/fake_llm_provider.py's precedent -- see that module's
docstring: a real object satisfying the Protocol, not a mock library
patch, so tests exercise real caller code against a real collaborator)."""

from datetime import UTC, datetime

from app.ingestion.mailbox_provider import (
    InboundMessage,
    MailboxAuthorizationError,
    MessagePage,
    OAuthTokens,
)


class FakeMailboxProvider:
    provider_name = "fake"

    def __init__(
        self,
        email_address: str = "user@example.com",
        pages: list[MessagePage] | None = None,
        raise_auth_error: bool = False,
    ):
        self._email_address = email_address
        self._pages = list(pages or [])
        self._raise_auth_error = raise_auth_error
        self.authorization_urls_built: list[str] = []
        self.refresh_calls: list[str] = []
        self.fetch_calls: list[tuple[str | None, int]] = []

    def build_authorization_url(self, state: str) -> str:
        url = f"https://fake-provider.example/authorize?state={state}"
        self.authorization_urls_built.append(url)
        return url

    def exchange_code_for_tokens(self, code: str) -> OAuthTokens:
        return OAuthTokens(
            access_token=f"fake-access-token-for-{code}",
            refresh_token=f"fake-refresh-token-for-{code}",
            expires_at=datetime.now(UTC),
            email_address=self._email_address,
            initial_sync_cursor="fake-cursor-0",
        )

    def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        self.refresh_calls.append(refresh_token)
        return OAuthTokens(
            access_token=f"refreshed-access-token-for-{refresh_token}",
            refresh_token=None,
            expires_at=datetime.now(UTC),
            email_address=self._email_address,
        )

    def fetch_new_messages(self, access_token: str, cursor: str | None, max_messages: int) -> MessagePage:
        self.fetch_calls.append((cursor, max_messages))
        if self._raise_auth_error:
            raise MailboxAuthorizationError("fake provider configured to simulate a revoked token")
        if not self._pages:
            return MessagePage(messages=[], next_cursor=cursor or "fake-cursor-0")
        return self._pages.pop(0)


def make_message(
    message_id: str = "msg-1",
    subject: str = "Test subject",
    body_text: str = "Test body.",
    sender_email: str = "sender@example.com",
) -> InboundMessage:
    return InboundMessage(
        message_id=message_id,
        thread_id=message_id,
        sender_email=sender_email,
        subject=subject,
        body_text=body_text,
        received_at=datetime.now(UTC),
    )
