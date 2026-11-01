"""
IMAP mailbox provider (FR-01: "connect to email servers via IMAP, SMTP,
and OAuth2 protocols"). Gmail and Outlook keep using their OAuth2 APIs
(gmail_provider.py / outlook_provider.py); this covers every other mail
server -- self-hosted, Fastmail, Zoho, corporate Exchange with IMAP
enabled -- that speaks plain IMAP over TLS with an (app-)password.

Fits the existing MailboxProvider protocol without changing the poller
(app/agents/runner.py):
  - The "refresh token" is the encrypted credential blob (host, port,
    username, password) -- JSON, encrypted at rest by the same
    app/core/token_encryption.py every other provider's tokens use.
  - refresh_access_token() returns that same blob as the "access token"
    with a 24h expiry: IMAP has no token exchange, so "refreshing" is
    just re-validating the credentials with a LOGIN.
  - The sync cursor is the highest IMAP UID already seen in INBOX,
    qualified by UIDVALIDITY ("<uidvalidity>:<uid>"); if the server
    reports a different UIDVALIDITY (mailbox rebuilt), the cursor resets
    to "now" rather than re-ingesting the whole mailbox.
  - First sync (cursor None) starts from "now", the same rule the Gmail
    and Outlook providers follow.

TLS only (IMAP4_SSL, port 993 by default). Plaintext IMAP is not offered:
it would send the mailbox password in the clear.
"""

import email
import imaplib
import json
import logging
import re
from datetime import UTC, datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime

from app.ingestion.mailbox_provider import (
    InboundAttachment,
    InboundMessage,
    MailboxAuthorizationError,
    MailboxProviderError,
    MessagePage,
    OAuthTokens,
)
from app.preprocessing.text_helpers import strip_html

logger = logging.getLogger("app.ingestion.imap")

DEFAULT_IMAP_PORT = 993
IMAP_TIMEOUT_SECONDS = 30
_CREDENTIAL_LIFETIME = timedelta(hours=24)
_UIDVALIDITY = re.compile(rb"UIDVALIDITY (\d+)")
_UIDNEXT = re.compile(rb"UIDNEXT (\d+)")


def encode_credentials(host: str, port: int, username: str, password: str) -> str:
    return json.dumps({"host": host, "port": port, "username": username, "password": password})


def _decode_credentials(blob: str) -> dict:
    try:
        creds = json.loads(blob)
        return {"host": creds["host"], "port": int(creds["port"]), "username": creds["username"], "password": creds["password"]}
    except (ValueError, KeyError, TypeError) as e:
        raise MailboxAuthorizationError("Stored IMAP credentials are malformed -- reconnect this mailbox.") from e


def _header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _extract_body_and_attachments(message: Message) -> tuple[str, list[InboundAttachment]]:
    """Prefers text/plain over text/html, same rule as the Gmail provider."""
    plain_text: str | None = None
    html_text: str | None = None
    attachments: list[InboundAttachment] = []

    for part in message.walk() if message.is_multipart() else [message]:
        if part.is_multipart():
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename or part.get_content_disposition() == "attachment":
            attachments.append(
                InboundAttachment(
                    filename=_header(filename) or "attachment",
                    mime_type=part.get_content_type(),
                    size_bytes=len(payload),
                )
            )
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:  # unknown charset name (FR-06)
            text = payload.decode("utf-8", errors="replace")
        if part.get_content_type() == "text/plain" and plain_text is None:
            plain_text = text
        elif part.get_content_type() == "text/html" and html_text is None:
            html_text = text

    if plain_text:
        return plain_text.strip(), attachments
    if html_text:
        return strip_html(html_text).strip(), attachments
    return "", attachments


def parse_message(uid: str, raw: bytes) -> InboundMessage:
    message = email.message_from_bytes(raw)
    body, attachments = _extract_body_and_attachments(message)
    try:
        received_at = parsedate_to_datetime(message.get("Date"))
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        received_at = datetime.now(UTC)
    message_id = (message.get("Message-ID") or "").strip() or f"imap-uid-{uid}"
    thread_root = (message.get("References") or "").split()
    return InboundMessage(
        message_id=message_id,
        thread_id=thread_root[0] if thread_root else (message.get("In-Reply-To") or message_id).strip(),
        sender_email=parseaddr(message.get("From", ""))[1].lower(),
        subject=_header(message.get("Subject")),
        body_text=body,
        received_at=received_at,
        attachments=attachments,
    )


class ImapProvider:
    provider_name = "imap"

    def __init__(self, imap_factory=imaplib.IMAP4_SSL):
        # Injectable so tests can substitute a fake server.
        self._imap_factory = imap_factory

    def _connect(self, creds: dict):
        try:
            client = self._imap_factory(creds["host"], creds["port"], timeout=IMAP_TIMEOUT_SECONDS)
        except (OSError, imaplib.IMAP4.error) as e:
            raise MailboxProviderError(f"Could not reach IMAP server {creds['host']}:{creds['port']}: {e}") from e
        try:
            client.login(creds["username"], creds["password"])
        except imaplib.IMAP4.error as e:
            raise MailboxAuthorizationError(f"IMAP login rejected for {creds['username']}: {e}") from e
        return client

    # --- MailboxProvider protocol ---------------------------------------

    def build_authorization_url(self, state: str) -> str:
        raise MailboxProviderError("IMAP connections use credentials, not an OAuth2 redirect.")

    def exchange_code_for_tokens(self, code: str) -> OAuthTokens:
        raise MailboxProviderError("IMAP connections use credentials, not an OAuth2 code exchange.")

    def validate_credentials(self, blob: str) -> OAuthTokens:
        """Used at connect time: proves the credentials work and captures
        the starting cursor, so the first poll only sees new mail."""
        creds = _decode_credentials(blob)
        client = self._connect(creds)
        try:
            cursor = self._current_cursor(client)
        finally:
            _safe_logout(client)
        return OAuthTokens(
            access_token=blob,
            refresh_token=blob,
            expires_at=datetime.now(UTC) + _CREDENTIAL_LIFETIME,
            email_address=creds["username"],
            initial_sync_cursor=cursor,
        )

    def refresh_access_token(self, refresh_token: str) -> OAuthTokens:
        creds = _decode_credentials(refresh_token)
        _safe_logout(self._connect(creds))
        return OAuthTokens(
            access_token=refresh_token,
            refresh_token=None,
            expires_at=datetime.now(UTC) + _CREDENTIAL_LIFETIME,
            email_address=creds["username"],
        )

    def fetch_new_messages(self, access_token: str, cursor: str | None, max_messages: int) -> MessagePage:
        creds = _decode_credentials(access_token)
        client = self._connect(creds)
        try:
            uidvalidity, current_cursor_uid = self._select_inbox(client)
            last_uid = self._cursor_uid(cursor, uidvalidity)
            if last_uid is None:
                return MessagePage(messages=[], next_cursor=f"{uidvalidity}:{current_cursor_uid}")

            status, data = client.uid("SEARCH", None, f"UID {last_uid + 1}:*")
            if status != "OK":
                raise MailboxProviderError(f"IMAP UID SEARCH failed: {data!r}")
            # "n:*" always matches the highest existing UID even when it is
            # below n, so filter explicitly.
            uids = sorted(int(u) for u in (data[0] or b"").split() if int(u) > last_uid)[:max_messages]

            messages = []
            for uid in uids:
                status, fetched = client.uid("FETCH", str(uid), "(RFC822)")
                if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                    raise MailboxProviderError(f"IMAP FETCH failed for UID {uid}.")
                messages.append(parse_message(str(uid), fetched[0][1]))

            next_uid = uids[-1] if uids else last_uid
            return MessagePage(messages=messages, next_cursor=f"{uidvalidity}:{next_uid}")
        except imaplib.IMAP4.error as e:
            raise MailboxProviderError(f"IMAP error: {e}") from e
        finally:
            _safe_logout(client)

    # --- helpers --------------------------------------------------------

    def _select_inbox(self, client) -> tuple[str, int]:
        status, _ = client.select("INBOX", readonly=True)
        if status != "OK":
            raise MailboxProviderError("Could not open INBOX.")
        status, data = client.status("INBOX", "(UIDVALIDITY UIDNEXT)")
        if status != "OK" or not data:
            raise MailboxProviderError("IMAP STATUS failed.")
        validity = _UIDVALIDITY.search(data[0])
        uidnext = _UIDNEXT.search(data[0])
        if validity is None or uidnext is None:
            raise MailboxProviderError(f"Unexpected IMAP STATUS response: {data[0]!r}")
        return validity.group(1).decode(), int(uidnext.group(1)) - 1

    def _current_cursor(self, client) -> str:
        uidvalidity, last_uid = self._select_inbox(client)
        return f"{uidvalidity}:{last_uid}"

    @staticmethod
    def _cursor_uid(cursor: str | None, uidvalidity: str) -> int | None:
        if not cursor:
            return None
        stored_validity, _, uid = cursor.partition(":")
        if stored_validity != uidvalidity or not uid.isdigit():
            logger.warning("imap_uidvalidity_changed_resetting_cursor")
            return None
        return int(uid)


def _safe_logout(client) -> None:
    try:
        client.logout()
    except Exception:
        pass
