from scipy.sparse import csr_matrix

from app.feature_engineering.feature_models import ContentFeatures
from app.feature_engineering.metadata_models import MetadataFeatures
from app.feature_engineering.feature_matrix import (
    build_feature_matrix,
    feature_summary,
)

# Dummy TF-IDF matrix (2 emails × 3 TF-IDF features)
tfidf = csr_matrix([
    [0.2, 0.5, 0.0],
    [0.1, 0.0, 0.8],
])

content = [
    ContentFeatures(
        char_count=100,
        word_count=20,
        sentence_count=2,
        avg_word_length=5.0,
        avg_sentence_length=10.0,
        uppercase_word_count=1,
        uppercase_ratio=0.05,
        exclamation_count=1,
        question_mark_count=0,
        ellipsis_count=0,
        total_punctuation_count=4,
        punctuation_density=0.20,
        has_url=False,
        url_count=0,
        has_email_address=False,
        has_phone_number=False,
        has_currency=False,
        has_numbers=True,
        number_ratio=0.10,
        spam_keyword_count=1,
        spam_keyword_ratio=0.02,
        is_reply=False,
        subject_word_count=3,
        subject_is_uppercase=False,
        subject_has_re_prefix=False,
        subject_has_fwd_prefix=False,
        subject_exclamation_count=0,
    ),
] * 2

metadata = [
    MetadataFeatures(
        hour_of_day=10,
        day_of_week=1,
        is_weekend=False,
        is_after_hours=False,
        is_friday_afternoon=False,
        is_internal_sender=True,
        is_freemail_sender=False,
        is_external_corporate=False,
        sender_domain_length=11,
        thread_depth=2,
        is_reply=True,
        is_forward=False,
        recipient_to_count=1,
        recipient_cc_count=0,
        total_recipient_count=1,
        is_broadcast=False,
        has_attachments=True,
        attachment_count=2,
    ),
] * 2

feature_summary(content, metadata)

matrix = build_feature_matrix(
    tfidf,
    content,
    metadata,
)

print("\nFinal Feature Matrix Shape:")
print(matrix.shape)