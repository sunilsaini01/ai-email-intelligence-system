"""
Unit tests for GmailProvider (Phase 18). NEVER makes a real network call --
httpx.post/httpx.get are monkeypatched, same convention as
tests/test_ollama_provider.py.
"""

import base64

import httpx
import pytest

from app.ingestion.gmail_provider import GmailProvider
from app.ingestion.mailbox_provider import MailboxAuthorizationError, MailboxProviderError


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


class _FakeResponse:
    def __init__(self, json_data=None, status_code=200, text=""):
        self._json_data = json_data or {}
        self.status_code = status_code
        self.text = text or str(json_data)

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.com")
            raise httpx.HTTPStatusError("error", request=request, response=httpx.Response(self.status_code, request=request))

    def json(self):
        return self._json_data


@pytest.fixture
def provider():
    return GmailProvider(client_id="client-id", client_secret="client-secret", redirect_uri="https://app.example/callback")


def test_build_authorization_url_includes_client_id_state_and_offline_access(provider):
    url = provider.build_authorization_url("signed-state-token")

    assert "client_id=client-id" in url
    assert "state=signed-state-token" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url


def test_exchange_code_for_tokens_returns_email_and_initial_cursor(monkeypatch, provider):
    def fake_post(url, data, timeout):
        assert url == "https://oauth2.googleapis.com/token"
        assert data["code"] == "auth-code-123"
        assert data["grant_type"] == "authorization_code"
        return _FakeResponse({"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600})

    def fake_get(url, headers, timeout, params=None):
        assert headers["Authorization"] == "Bearer at-1"
        return _FakeResponse({"emailAddress": "user@gmail.com", "historyId": "1000"})

    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr("httpx.get", fake_get)

    tokens = provider.exchange_code_for_tokens("auth-code-123")

    assert tokens.access_token == "at-1"
    assert tokens.refresh_token == "rt-1"
    assert tokens.email_address == "user@gmail.com"
    assert tokens.initial_sync_cursor == "1000"


def test_exchange_code_missing_refresh_token_raises_provider_error(monkeypatch, provider):
    monkeypatch.setattr("httpx.post", lambda url, data, timeout: _FakeResponse({"access_token": "at-1", "expires_in": 3600}))

    with pytest.raises(MailboxProviderError):
        provider.exchange_code_for_tokens("auth-code-123")


def test_refresh_access_token_keeps_existing_refresh_token_when_not_reissued(monkeypatch, provider):
    def fake_post(url, data, timeout):
        assert data["grant_type"] == "refresh_token"
        assert data["refresh_token"] == "existing-rt"
        return _FakeResponse({"access_token": "new-at", "expires_in": 3600})  # no refresh_token in response

    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr("httpx.get", lambda url, headers, timeout, params=None: _FakeResponse({"emailAddress": "user@gmail.com", "historyId": "2000"}))

    tokens = provider.refresh_access_token("existing-rt")

    assert tokens.access_token == "new-at"
    assert tokens.refresh_token == "existing-rt"


def test_refresh_access_token_rejected_raises_authorization_error(monkeypatch, provider):
    monkeypatch.setattr("httpx.post", lambda url, data, timeout: _FakeResponse({"error": "invalid_grant"}, status_code=400))

    with pytest.raises(MailboxAuthorizationError):
        provider.refresh_access_token("revoked-rt")


def test_fetch_new_messages_with_no_cursor_establishes_baseline_without_fetching_messages(monkeypatch, provider):
    calls = []

    def fake_get(url, headers, timeout, params=None):
        calls.append(url)
        return _FakeResponse({"emailAddress": "user@gmail.com", "historyId": "5000"})

    monkeypatch.setattr("httpx.get", fake_get)

    page = provider.fetch_new_messages("at-1", cursor=None, max_messages=10)

    assert page.messages == []
    assert page.next_cursor == "5000"
    assert len(calls) == 1  # only the profile lookup, no message fetches


def test_fetch_new_messages_with_cursor_returns_parsed_plain_text_message_and_attachment(monkeypatch, provider):
    def fake_get(url, headers, timeout, params=None):
        if url.endswith("/history"):
            return _FakeResponse(
                {
                    "history": [{"messagesAdded": [{"message": {"id": "msg-1", "threadId": "thread-1"}}]}],
                    "historyId": "5001",
                }
            )
        if url.endswith("/messages/msg-1"):
            return _FakeResponse(
                {
                    "id": "msg-1",
                    "threadId": "thread-1",
                    "internalDate": "1700000000000",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "Jane Doe <jane@customer.com>"},
                            {"name": "Subject", "value": "Order question"},
                        ],
                        "mimeType": "multipart/mixed",
                        "parts": [
                            {"mimeType": "text/plain", "body": {"data": _b64url("Where is my order?")}},
                            {"mimeType": "application/pdf", "filename": "invoice.pdf", "body": {"size": 1234}},
                        ],
                    },
                }
            )
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("httpx.get", fake_get)

    page = provider.fetch_new_messages("at-1", cursor="4000", max_messages=10)

    assert page.next_cursor == "5001"
    assert len(page.messages) == 1
    message = page.messages[0]
    assert message.message_id == "msg-1"
    assert message.thread_id == "thread-1"
    assert message.sender_email == "jane@customer.com"
    assert message.subject == "Order question"
    assert message.body_text == "Where is my order?"
    assert len(message.attachments) == 1
    assert message.attachments[0].filename == "invoice.pdf"
    assert message.attachments[0].size_bytes == 1234


def test_fetch_new_messages_falls_back_to_stripped_html_when_no_plain_text_part(monkeypatch, provider):
    def fake_get(url, headers, timeout, params=None):
        if url.endswith("/history"):
            return _FakeResponse({"history": [{"messagesAdded": [{"message": {"id": "msg-2"}}]}], "historyId": "5002"})
        return _FakeResponse(
            {
                "id": "msg-2",
                "internalDate": "1700000000000",
                "payload": {
                    "headers": [{"name": "From", "value": "a@b.com"}, {"name": "Subject", "value": "S"}],
                    "mimeType": "text/html",
                    "body": {"data": _b64url("<p>Hello <b>there</b></p>")},
                },
            }
        )

    monkeypatch.setattr("httpx.get", fake_get)

    page = provider.fetch_new_messages("at-1", cursor="4000", max_messages=10)

    assert page.messages[0].body_text == "Hello there"


def test_fetch_new_messages_401_raises_authorization_error(monkeypatch, provider):
    monkeypatch.setattr("httpx.get", lambda url, headers, timeout, params=None: _FakeResponse({}, status_code=401))

    with pytest.raises(MailboxAuthorizationError):
        provider.fetch_new_messages("at-1", cursor="4000", max_messages=10)


def test_fetch_new_messages_404_resyncs_from_now_instead_of_raising(monkeypatch, provider):
    def fake_get(url, headers, timeout, params=None):
        if url.endswith("/history"):
            return _FakeResponse({}, status_code=404)
        return _FakeResponse({"emailAddress": "user@gmail.com", "historyId": "9999"})

    monkeypatch.setattr("httpx.get", fake_get)

    page = provider.fetch_new_messages("at-1", cursor="an-expired-cursor", max_messages=10)

    assert page.messages == []
    assert page.next_cursor == "9999"
