"""Builds a MailboxProvider from configured settings (Phase 18).

One place that knows how to construct GmailProvider/OutlookProvider from
Settings -- used by both the mailbox endpoints (connect/callback) and the
poller (app/agents/runner.py), so the redirect_uri construction in
particular can't drift between the two callers.
"""

from app.core.config import get_settings
from app.ingestion.gmail_provider import GmailProvider
from app.ingestion.imap_provider import ImapProvider
from app.ingestion.mailbox_provider import MailboxProvider
from app.ingestion.outlook_provider import OutlookProvider
from app.models.mailbox_connection import (
    MAILBOX_PROVIDERS,
    PROVIDER_GMAIL,
    PROVIDER_IMAP,
    PROVIDER_OUTLOOK,
)


class UnknownMailboxProvider(ValueError):
    pass


def build_provider(provider: str) -> MailboxProvider:
    settings = get_settings()
    redirect_uri = f"{settings.APP_BASE_URL}/api/{settings.API_VERSION}/mailbox/{provider}/callback"

    if provider == PROVIDER_GMAIL:
        return GmailProvider(
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
            redirect_uri=redirect_uri,
        )
    if provider == PROVIDER_OUTLOOK:
        return OutlookProvider(
            client_id=settings.MICROSOFT_CLIENT_ID,
            client_secret=settings.MICROSOFT_CLIENT_SECRET,
            tenant_id=settings.MICROSOFT_TENANT_ID,
            redirect_uri=redirect_uri,
        )
    if provider == PROVIDER_IMAP:
        return ImapProvider()
    raise UnknownMailboxProvider(f"Unknown mailbox provider: {provider!r}. Expected one of {MAILBOX_PROVIDERS!r}.")
