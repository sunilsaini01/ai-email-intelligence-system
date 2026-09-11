"""
Unit tests for OutlookProvider (Phase 18). NEVER makes a real network
call -- httpx.post/httpx.get are monkeypatched, same convention as
tests/test_ollama_provider.py.
"""

import httpx
import pytest

from app.ingestion.outlook_provider import OutlookProvider
from app.ingestion.mailbox_provider import MailboxAuthorizationError, MailboxProviderError


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
    return OutlookProvider(
        client_id="client-id", client_secret="client-secret", tenant_id="common", redirect_uri="https://app.example/callback"
    )


def test_build_authorization_url_includes_client_id_state_and_offline_access_scope(provider):
    url = provider.build_authorization_url("signed-state-token")

    assert "login.microsoftonline.com/common/oauth2/v2.0/authorize" in url
    assert "client_id=client-id" in url
    assert "state=signed-state-token" in url
    assert "offline_access" in url


def test_exchange_code_for_tokens_returns_email_from_mail_field(monkeypatch, provider):
    def fake_post(url, data, timeout):
        assert data["code"] == "auth-code"
        assert data["grant_type"] == "authorization_code"
        return _FakeResponse({"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600})

    def fake_get(url, headers, timeout):
        assert headers["Authorization"] == "Bearer at-1"
        return _FakeResponse({"mail": "user@outlook.com", "userPrincipalName": "user@outlook.com"})

    monkeypatch.setattr("httpx.post", fake_post)
    monkeypatch.setattr("httpx.get", fake_get)

    tokens = provider.exchange_code_for_tokens("auth-code")

    assert tokens.access_token == "at-1"
    assert tokens.refresh_token == "rt-1"
    assert tokens.email_address == "user@outlook.com"
    assert tokens.initial_sync_cursor is None


def test_exchange_code_falls_back_to_user_principal_name_when_mail_is_null(monkeypatch, provider):
    monkeypatch.setattr("httpx.post", lambda url, data, timeout: _FakeResponse({"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600}))
    monkeypatch.setattr("httpx.get", lambda url, headers, timeout: _FakeResponse({"mail": None, "userPrincipalName": "user@tenant.onmicrosoft.com"}))

    tokens = provider.exchange_code_for_tokens("auth-code")

    assert tokens.email_address == "user@tenant.onmicrosoft.com"


def test_exchange_code_missing_refresh_token_raises_provider_error(monkeypatch, provider):
    monkeypatch.setattr("httpx.post", lambda url, data, timeout: _FakeResponse({"access_token": "at-1", "expires_in": 3600}))

    with pytest.raises(MailboxProviderError):
        provider.exchange_code_for_tokens("auth-code")


def test_refresh_access_token_rejected_raises_authorization_error(monkeypatch, provider):
    monkeypatch.setattr("httpx.post", lambda url, data, timeout: _FakeResponse({"error": "invalid_grant"}, status_code=400))

    with pytest.raises(MailboxAuthorizationError):
        provider.refresh_access_token("revoked-rt")


def test_fetch_new_messages_with_no_cursor_walks_to_delta_link_without_parsing_messages(monkeypatch, provider):
    calls = {"count": 0}

    def fake_get(url, headers, timeout):
        calls["count"] += 1
        assert "$select=id" in url or url == "https://graph.microsoft.com/v1.0/next-page"
        if calls["count"] == 1:
            # Bootstrap's first page has more pages -- must not be parsed
            # into a message (only `id` was even requested).
            return _FakeResponse({"value": [{"id": "m1"}], "@odata.nextLink": "https://graph.microsoft.com/v1.0/next-page"})
        return _FakeResponse({"value": [], "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta-link-1"})

    monkeypatch.setattr("httpx.get", fake_get)

    page = provider.fetch_new_messages("at-1", cursor=None, max_messages=10)

    assert page.messages == []
    assert page.next_cursor == "https://graph.microsoft.com/v1.0/delta-link-1"
    assert calls["count"] == 2


def test_fetch_new_messages_with_cursor_parses_messages_and_returns_delta_link(monkeypatch, provider):
    def fake_get(url, headers, timeout):
        assert url == "https://graph.microsoft.com/v1.0/stored-delta-link"
        return _FakeResponse(
            {
                "value": [
                    {
                        "id": "msg-1",
                        "conversationId": "thread-1",
                        "subject": "Refund status",
                        "from": {"emailAddress": {"address": "jane@customer.com"}},
                        "body": {"contentType": "text", "content": "When will my refund arrive?"},
                        "receivedDateTime": "2026-09-01T10:00:00Z",
                        "hasAttachments": False,
                    }
                ],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta-link-2",
            }
        )

    monkeypatch.setattr("httpx.get", fake_get)

    page = provider.fetch_new_messages("at-1", cursor="https://graph.microsoft.com/v1.0/stored-delta-link", max_messages=10)

    assert page.next_cursor == "https://graph.microsoft.com/v1.0/delta-link-2"
    assert len(page.messages) == 1
    message = page.messages[0]
    assert message.message_id == "msg-1"
    assert message.thread_id == "thread-1"
    assert message.sender_email == "jane@customer.com"
    assert message.subject == "Refund status"
    assert message.body_text == "When will my refund arrive?"


def test_fetch_new_messages_strips_html_body(monkeypatch, provider):
    monkeypatch.setattr(
        "httpx.get",
        lambda url, headers, timeout: _FakeResponse(
            {
                "value": [
                    {
                        "id": "msg-2",
                        "from": {"emailAddress": {"address": "a@b.com"}},
                        "subject": "S",
                        "body": {"contentType": "html", "content": "<p>Hello <b>there</b></p>"},
                        "receivedDateTime": "2026-09-01T10:00:00Z",
                        "hasAttachments": False,
                    }
                ],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta-link-3",
            }
        ),
    )

    page = provider.fetch_new_messages("at-1", cursor="https://graph.microsoft.com/v1.0/some-link", max_messages=10)

    assert page.messages[0].body_text == "Hello there"


def test_fetch_new_messages_fetches_attachment_metadata_only(monkeypatch, provider):
    def fake_get(url, headers, timeout):
        if "/attachments" in url:
            return _FakeResponse({"value": [{"name": "invoice.pdf", "contentType": "application/pdf", "size": 4096}]})
        return _FakeResponse(
            {
                "value": [
                    {
                        "id": "msg-3",
                        "from": {"emailAddress": {"address": "a@b.com"}},
                        "subject": "S",
                        "body": {"contentType": "text", "content": "See attached."},
                        "receivedDateTime": "2026-09-01T10:00:00Z",
                        "hasAttachments": True,
                    }
                ],
                "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta-link-4",
            }
        )

    monkeypatch.setattr("httpx.get", fake_get)

    page = provider.fetch_new_messages("at-1", cursor="https://graph.microsoft.com/v1.0/some-link", max_messages=10)

    assert len(page.messages[0].attachments) == 1
    assert page.messages[0].attachments[0].filename == "invoice.pdf"
    assert page.messages[0].attachments[0].size_bytes == 4096


def test_fetch_new_messages_401_raises_authorization_error(monkeypatch, provider):
    monkeypatch.setattr("httpx.get", lambda url, headers, timeout: _FakeResponse({}, status_code=401))

    with pytest.raises(MailboxAuthorizationError):
        provider.fetch_new_messages("at-1", cursor="https://graph.microsoft.com/v1.0/some-link", max_messages=10)


def test_fetch_new_messages_410_gone_resyncs_from_now_instead_of_raising(monkeypatch, provider):
    calls = {"count": 0}

    def fake_get(url, headers, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            return _FakeResponse({}, status_code=410)
        return _FakeResponse({"value": [], "@odata.deltaLink": "https://graph.microsoft.com/v1.0/fresh-delta-link"})

    monkeypatch.setattr("httpx.get", fake_get)

    page = provider.fetch_new_messages("at-1", cursor="https://graph.microsoft.com/v1.0/an-expired-link", max_messages=10)

    assert page.messages == []
    assert page.next_cursor == "https://graph.microsoft.com/v1.0/fresh-delta-link"


def test_fetch_new_messages_stops_at_max_messages_and_resumes_from_next_link(monkeypatch, provider):
    def fake_get(url, headers, timeout):
        return _FakeResponse(
            {
                "value": [
                    {
                        "id": f"msg-{i}",
                        "from": {"emailAddress": {"address": "a@b.com"}},
                        "subject": "S",
                        "body": {"contentType": "text", "content": "body"},
                        "receivedDateTime": "2026-09-01T10:00:00Z",
                        "hasAttachments": False,
                    }
                    for i in range(5)
                ],
                "@odata.nextLink": "https://graph.microsoft.com/v1.0/page-2",
            }
        )

    monkeypatch.setattr("httpx.get", fake_get)

    page = provider.fetch_new_messages("at-1", cursor="https://graph.microsoft.com/v1.0/page-1", max_messages=2)

    assert len(page.messages) == 2
    assert page.next_cursor == "https://graph.microsoft.com/v1.0/page-2"
