from datetime import datetime

from app.feature_engineering.domains import (
    FREEMAIL_DOMAINS,
    INTERNAL_DOMAINS,
)
from app.feature_engineering.metadata_models import MetadataFeatures


class MetadataFeatureExtractor:
    """
    Extract metadata-based numerical features from an email.
    """

    def extract(
        self,
        received_at: datetime,
        sender_email: str,
        recipient_to: list[str],
        recipient_cc: list[str],
        thread_depth: int,
        is_reply: bool,
        is_forward: bool,
        has_attachments: bool,
        attachment_count: int,
    ) -> MetadataFeatures:

        # Temporal Features

        hour_of_day = received_at.hour

        day_of_week = received_at.weekday()

        is_weekend = day_of_week >= 5

        is_after_hours = (
            hour_of_day < 8
            or hour_of_day >= 19
        )

        is_friday_afternoon = (
            day_of_week == 4
            and hour_of_day >= 14
        )
        
        # Sender Features

        sender_domain = ""

        if "@" in sender_email:
            sender_domain = sender_email.split("@")[-1].lower()

        is_internal_sender = (
            sender_domain in INTERNAL_DOMAINS
        )

        is_freemail_sender = (
            sender_domain in FREEMAIL_DOMAINS
        )

        is_external_corporate = (
            sender_domain != ""
            and not is_internal_sender
            and not is_freemail_sender
        )

        sender_domain_length = len(sender_domain)
        
        # Thread Features

        thread_depth = max(0, thread_depth)

        is_reply = bool(is_reply)

        is_forward = bool(is_forward)
        
        # Recipient Features

        recipient_to_count = len(recipient_to)

        recipient_cc_count = len(recipient_cc)

        total_recipient_count = (
            recipient_to_count
            + recipient_cc_count
        )

        is_broadcast = (
            total_recipient_count > 5
        )
        
        # Attachment Features

        has_attachments = bool(has_attachments)

        attachment_count = max(
            0,
            attachment_count,
        )
        
        return MetadataFeatures(

            # Temporal
            hour_of_day=hour_of_day,
            day_of_week=day_of_week,
            is_weekend=is_weekend,
            is_after_hours=is_after_hours,
            is_friday_afternoon=is_friday_afternoon,

            # Sender
            is_internal_sender=is_internal_sender,
            is_freemail_sender=is_freemail_sender,
            is_external_corporate=is_external_corporate,
            sender_domain_length=sender_domain_length,

            # Thread
            thread_depth=thread_depth,
            is_reply=is_reply,
            is_forward=is_forward,

            # Recipients
            recipient_to_count=recipient_to_count,
            recipient_cc_count=recipient_cc_count,
            total_recipient_count=total_recipient_count,
            is_broadcast=is_broadcast,

            # Attachments
            has_attachments=has_attachments,
            attachment_count=attachment_count,
        )