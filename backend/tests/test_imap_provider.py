"""Unit tests for app/ingestion/imap_provider.py (FR-01 IMAP) against an
in-process fake IMAP server -- no network."""

import imaplib
from email.message import EmailMessage

import pytest

from app.ingestion.imap_provider import ImapProvider, encode_credentials, parse_message
from app.ingestion.mailbox_provider import MailboxAuthorizationError, MailboxProviderError

CREDS = encode_credentials("imap.example.com", 993, "inbox@example.com", "app-password")


def _raw(subject: str, body: str, html: str | None = None, sender: str = "Alice <alice@example.com>") -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["Subject"] = subject
    msg["Message-ID"] = f"<{subject.replace(' ', '-')}@example.com>"
    msg["Date"] = "Tue, 27 Oct 2026 10:00:00 +0000"
    if html is not None:
        msg.set_content(body)
        msg.add_alternative(html, subtype="html")
    else:
        msg.set_content(body)
    return msg.as_bytes()


class FakeImap:
    def __init__(self, messages: dict[int, bytes], uidvalidity: int = 7, password: str = "app-password"):
        self.messages = messages
        self.uidvalidity = uidvalidity
        self.password = password

    def __call__(self, host, port, timeout=None):  # acts as the IMAP4_SSL factory
        return self

    def login(self, user, password):
        if password != self.password:
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")

    def select(self, mailbox, readonly=False):
        return "OK", [b"1"]

    def status(self, mailbox, items):
        uidnext = max(self.messages, default=0) + 1
        return "OK", [f"INBOX (UIDVALIDITY {self.uidvalidity} UIDNEXT {uidnext})".encode()]

    def uid(self, command, *args):
        if command == "SEARCH":
            low = int(args[1].split()[1].split(":")[0])
            # Real servers include the highest UID even when below `low`.
            matches = [u for u in self.messages if u >= low] or ([max(self.messages)] if self.messages else [])
            return "OK", [" ".join(str(u) for u in sorted(matches)).encode()]
        if command == "FETCH":
            uid = int(args[0])
            return "OK", [(f"{uid} (RFC822)".encode(), self.messages[uid])]
        raise AssertionError(command)

    def logout(self):
        pass


def test_connect_validates_credentials_and_starts_from_now():
    server = FakeImap({1: _raw("old", "old mail"), 2: _raw("older", "x")})
    tokens = ImapProvider(imap_factory=server).validate_credentials(CREDS)
    assert tokens.email_address == "inbox@example.com"
    assert tokens.initial_sync_cursor == "7:2"


def test_bad_password_is_an_authorization_error():
    with pytest.raises(MailboxAuthorizationError):
        ImapProvider(imap_factory=FakeImap({}, password="other")).validate_credentials(CREDS)


def test_fetch_returns_only_new_messages_and_advances_cursor():
    server = FakeImap({1: _raw("old", "old"), 2: _raw("New order", "Where is order 123?"), 3: _raw("Hi", "x")})
    page = ImapProvider(imap_factory=server).fetch_new_messages(CREDS, "7:1", max_messages=10)
    assert [m.subject for m in page.messages] == ["New order", "Hi"]
    assert page.messages[0].sender_email == "alice@example.com"
    assert page.next_cursor == "7:3"


def test_fetch_with_nothing_new_keeps_cursor():
    page = ImapProvider(imap_factory=FakeImap({1: _raw("a", "b")})).fetch_new_messages(CREDS, "7:1", 10)
    assert page.messages == [] and page.next_cursor == "7:1"


def test_uidvalidity_change_resets_to_now_instead_of_reingesting():
    server = FakeImap({1: _raw("a", "b"), 2: _raw("c", "d")}, uidvalidity=9)
    page = ImapProvider(imap_factory=server).fetch_new_messages(CREDS, "7:1", 10)
    assert page.messages == [] and page.next_cursor == "9:2"


def test_max_messages_caps_a_poll():
    server = FakeImap({i: _raw(f"m{i}", "b") for i in range(1, 6)})
    page = ImapProvider(imap_factory=server).fetch_new_messages(CREDS, "7:0", 2)
    assert len(page.messages) == 2 and page.next_cursor == "7:2"


def test_html_only_body_is_stripped_and_plain_preferred():
    msg = EmailMessage()
    msg["Subject"] = "html"
    msg.set_content("<p>Hello <b>there</b></p>", subtype="html")
    assert "Hello" in parse_message("1", msg.as_bytes()).body_text
    assert "<p>" not in parse_message("1", msg.as_bytes()).body_text
    both = parse_message("2", _raw("both", "plain version", html="<p>html version</p>"))
    assert both.body_text == "plain version"


def test_malformed_credentials_are_rejected():
    with pytest.raises(MailboxAuthorizationError):
        ImapProvider(imap_factory=FakeImap({})).refresh_access_token("not json")


def test_oauth_methods_are_not_supported():
    with pytest.raises(MailboxProviderError):
        ImapProvider().build_authorization_url("state")
