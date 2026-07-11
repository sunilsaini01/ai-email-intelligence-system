from dataclasses import dataclass


@dataclass
class MetadataFeatures:

    # -------------------------
    # Temporal
    # -------------------------

    hour_of_day: int

    day_of_week: int

    is_weekend: bool

    is_after_hours: bool

    is_friday_afternoon: bool

    # -------------------------
    # Sender
    # -------------------------

    is_internal_sender: bool

    is_freemail_sender: bool

    is_external_corporate: bool

    sender_domain_length: int

    # -------------------------
    # Thread
    # -------------------------

    thread_depth: int

    is_reply: bool

    is_forward: bool

    # -------------------------
    # Recipients
    # -------------------------

    recipient_to_count: int

    recipient_cc_count: int

    total_recipient_count: int

    is_broadcast: bool

    # -------------------------
    # Attachments
    # -------------------------

    has_attachments: bool

    attachment_count: int