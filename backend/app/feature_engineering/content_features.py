import string

import numpy as np

from app.feature_engineering.category_keywords import CATEGORY_KEYWORDS
from app.feature_engineering.feature_models import ContentFeatures
from app.feature_engineering.patterns import (
    CURRENCY_PATTERN,
    EMAIL_PATTERN,
    PHONE_PATTERN,
    SENTENCE_PATTERN,
    URL_PATTERN,
)
from app.feature_engineering.priority_keywords import (
    ESCALATION_KEYWORDS,
    SLA_KEYWORDS,
    URGENCY_KEYWORDS,
)
from app.feature_engineering.spam_keywords import SPAM_KEYWORDS


class ContentFeatureExtractor:
    """
    Production-ready content feature extractor.
    """

    def extract(
        self,
        body_clean: str,
        subject_raw: str = "",
        is_reply: bool = False,
    ) -> ContentFeatures:

        body = body_clean or ""
        subject = subject_raw or ""

        words = body.split()


        
        # Length Features

        char_count = len(body)

        word_count = len(words)

        sentences = [
            sentence.strip()
            for sentence in SENTENCE_PATTERN.split(body)
            if sentence.strip()
        ]

        sentence_count = max(len(sentences), 1)

        avg_word_length = (
            np.mean([len(word) for word in words])
            if words
            else 0.0
        )

        avg_sentence_length = (
            word_count / sentence_count
            if sentence_count > 0
            else 0.0
        )
        
        # Capitalization Features

        uppercase_words = [
            word
            for word in words
            if word.isupper() and len(word) > 1
        ]

        uppercase_word_count = len(uppercase_words)

        uppercase_ratio = (
            uppercase_word_count / word_count
            if word_count > 0
            else 0.0
        )
        
        # Punctuation Features

        exclamation_count = body.count("!")

        question_mark_count = body.count("?")

        ellipsis_count = body.count("...")

        total_punctuation_count = sum(
            1
            for character in body
            if character in string.punctuation
        )

        punctuation_density = (
            total_punctuation_count / word_count
            if word_count > 0
            else 0.0
        )
        
        # Structural Features

        urls = URL_PATTERN.findall(body)

        email_addresses = EMAIL_PATTERN.findall(body)

        phone_numbers = PHONE_PATTERN.findall(body)

        currencies = CURRENCY_PATTERN.findall(body)

        numeric_tokens = [
            word
            for word in words
            if any(char.isdigit() for char in word)
        ]

        has_url = len(urls) > 0

        url_count = len(urls)

        has_email_address = len(email_addresses) > 0

        has_phone_number = len(phone_numbers) > 0

        has_currency = len(currencies) > 0

        has_numbers = len(numeric_tokens) > 0

        number_ratio = (
            len(numeric_tokens) / word_count
            if word_count > 0
            else 0.0
        )
        
        # Spam Features

        body_lower = body.lower()

        spam_keyword_count = sum(
            1
            for keyword in SPAM_KEYWORDS
            if keyword in body_lower
        )

        spam_keyword_ratio = (
            spam_keyword_count / len(SPAM_KEYWORDS)
            if len(SPAM_KEYWORDS) > 0
            else 0.0
        )

        # Priority Features (Module 3 / FR-17)

        urgency_keyword_count = sum(
            1
            for keyword in URGENCY_KEYWORDS
            if keyword in body_lower
        )

        escalation_keyword_count = sum(
            1
            for keyword in ESCALATION_KEYWORDS
            if keyword in body_lower
        )

        sla_keyword_count = sum(
            1
            for keyword in SLA_KEYWORDS
            if keyword in body_lower
        )

        # Subject Features

        subject_words = subject.split()

        subject_lower = subject.lower()

        subject_word_count = len(subject_words)

        # Category Features (Module 4 / FR-21) — combines subject + body so
        # a category cue in the subject line (frequently the strongest
        # signal, e.g. "RE: Invoice #4471") counts the same as one in the
        # body, matching how the synthetic label generator scores emails
        # (scripts/generate_synthetic_category_dataset.py). Computed after
        # subject_lower exists (moved below the Subject Features block).
        combined_lower = f"{subject_lower} {body_lower}"

        category_keyword_counts = {
            category: sum(1 for keyword in keywords if keyword in combined_lower)
            for category, keywords in CATEGORY_KEYWORDS.items()
        }

        subject_is_uppercase = (
            subject.isupper()
            if subject
            else False
        )

        subject_has_re_prefix = subject_lower.startswith("re:")

        subject_has_fwd_prefix = (
            subject_lower.startswith("fwd:")
            or subject_lower.startswith("fw:")
        )

        subject_exclamation_count = subject.count("!")
        
        return ContentFeatures(

            # Length
            char_count=char_count,
            word_count=word_count,
            sentence_count=sentence_count,
            avg_word_length=round(avg_word_length, 3),
            avg_sentence_length=round(avg_sentence_length, 3),

            # Capitalization
            uppercase_word_count=uppercase_word_count,
            uppercase_ratio=round(uppercase_ratio, 4),

            # Punctuation
            exclamation_count=exclamation_count,
            question_mark_count=question_mark_count,
            ellipsis_count=ellipsis_count,
            total_punctuation_count=total_punctuation_count,
            punctuation_density=round(punctuation_density, 4),

            has_url=has_url,
            url_count=url_count,

            has_email_address=has_email_address,
            has_phone_number=has_phone_number,

            has_currency=has_currency,

            has_numbers=has_numbers,
            number_ratio=round(number_ratio, 4),

            # Spam
            spam_keyword_count=spam_keyword_count,
            spam_keyword_ratio=round(spam_keyword_ratio, 4),

            # Priority
            urgency_keyword_count=urgency_keyword_count,
            escalation_keyword_count=escalation_keyword_count,
            sla_keyword_count=sla_keyword_count,

            # Category
            support_keyword_count=category_keyword_counts["Support"],
            sales_keyword_count=category_keyword_counts["Sales"],
            billing_keyword_count=category_keyword_counts["Billing"],
            legal_keyword_count=category_keyword_counts["Legal"],
            hr_keyword_count=category_keyword_counts["HR"],
            it_keyword_count=category_keyword_counts["IT"],
            marketing_keyword_count=category_keyword_counts["Marketing"],

            is_reply=is_reply,

            subject_word_count=subject_word_count,

            subject_is_uppercase=subject_is_uppercase,

            subject_has_re_prefix=subject_has_re_prefix,

            subject_has_fwd_prefix=subject_has_fwd_prefix,

            subject_exclamation_count=subject_exclamation_count,
        )