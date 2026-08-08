from dataclasses import dataclass


@dataclass
class ContentFeatures:
    """
    Stores all numerical and boolean content-based features
    extracted from an email.
    """

    # -----------------------
    # Length Features
    # -----------------------

    char_count: int
    word_count: int
    sentence_count: int

    avg_word_length: float
    avg_sentence_length: float

    # -----------------------
    # Capitalization
    # -----------------------

    uppercase_word_count: int
    uppercase_ratio: float

    # -----------------------
    # Punctuation
    # -----------------------

    exclamation_count: int
    question_mark_count: int
    ellipsis_count: int
    total_punctuation_count: int
    punctuation_density: float

    # -----------------------
    # Structural Features
    # -----------------------

    has_url: bool
    url_count: int

    has_email_address: bool
    has_phone_number: bool

    has_currency: bool

    has_numbers: bool
    number_ratio: float

    # -----------------------
    # Spam Signals
    # -----------------------

    spam_keyword_count: int
    spam_keyword_ratio: float

    # -----------------------
    # Priority Signals (Module 3 / FR-17)
    # -----------------------

    urgency_keyword_count: int
    escalation_keyword_count: int
    sla_keyword_count: int

    # -----------------------
    # Category Signals (Module 4 / FR-21) — one count per non-General
    # category; General is the taxonomy's fallback and has no keyword list
    # of its own (see app/feature_engineering/category_keywords.py).
    # -----------------------

    support_keyword_count: int
    sales_keyword_count: int
    billing_keyword_count: int
    legal_keyword_count: int
    hr_keyword_count: int
    it_keyword_count: int
    marketing_keyword_count: int

    # -----------------------
    # Email Metadata
    # -----------------------

    is_reply: bool

    subject_word_count: int
    subject_is_uppercase: bool

    subject_has_re_prefix: bool
    subject_has_fwd_prefix: bool

    subject_exclamation_count: int